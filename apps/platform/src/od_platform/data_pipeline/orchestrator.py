#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :orchestrator.py
# @Time      :2026/7/1 15:20:44
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
from __future__ import annotations

import logging
import tempfile
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

from od_platform.common import paths
from od_platform.common.constants import (
    COVERAGE_HARD_THRESHOLD, COVERAGE_SOFT_THRESHOLD, DEFAULT_RANDOM_STATE, DEFAULT_SPLIT_MODE,
    DEFAULT_SPLIT_STRATEGY, IMAGE_EXTENSIONS, AnnotationFormat, SplitMode, Task
)

from od_platform.common.refs import  resolve_dataset
from od_platform.data_pipeline.convert.registry import ConvertOptions, get_converter
from od_platform.data_pipeline.convert.service import convert_data_to_yolo
from od_platform.data_pipeline.report import analyze_class_balance, render_balance_report
from od_platform.data_pipeline.split.manifest import PairList
from od_platform.data_pipeline.split.manifest import SplitManifest
from od_platform.data_pipeline.split.materializer import SplitOutputDirs, materialize
from od_platform.data_pipeline.split.split_service import split_pairs
from od_platform.data_pipeline.split.yaml_writer import write_dataset_yaml

logger = logging.getLogger(__name__)

class DatasetPipeline:
    """一次"把某数据集转换 + 划分成可训练数据集"的完整流程。"""

    def __init__(
        self, dataset: str, annotation_format: str, *,
        task: str = Task.DETECT, train_rate: float = 0.8, val_rate: float = 0.1,
        classes: Optional[List[str]] = None, random_state: int = DEFAULT_RANDOM_STATE,
        split_strategy: str = DEFAULT_SPLIT_STRATEGY,
        split_mode: str = DEFAULT_SPLIT_MODE,
        skip_if_exists: bool = False,
    ):
        self.annotation_format = annotation_format
        self.task = task
        self.train_rate = train_rate
        self.val_rate = val_rate
        self.random_state = random_state
        self.split_strategy = split_strategy
        self.split_mode = split_mode
        self.skip_if_exists = skip_if_exists
        self._options = ConvertOptions(task=task, classes=classes)

        # 名字或路径 → 具体目录;并据数据集名,提前算好"按数据集分桶"的落盘根与 yaml 路径。
        self.raw_root = resolve_dataset(dataset)
        self.dataset_name = self.raw_root.name
        self.raw_images = self.raw_root / "images"
        self.raw_annotations = self.raw_root / "annotations"
        self.processed_root = paths.dataset_processed_dir(self.dataset_name)   # data/processed/<name>/
        self.output_dirs = SplitOutputDirs.for_dataset_root(self.processed_root)
        self.yaml_out = paths.dataset_yaml_path(self.dataset_name)

    def run(self) -> Dict:
        if self.skip_if_exists and self._already_split():
            logger.info(
                "数据集 %r 已划分，跳过流水线。YAML: %s，处理后数据: %s",
                self.dataset_name, self.yaml_out, self.processed_root,
            )
            return {"skipped": True, "yaml": str(self.yaml_out)}
        if self.split_mode == SplitMode.PRESERVE:
            return self._run_preserve_split()
        if self.split_mode != SplitMode.RESPLIT:
            raise ValueError(f"未知 split_mode: {self.split_mode!r}")
        return self._run_resplit()

    def _already_split(self) -> bool:
        """检查数据集是否已经完成划分。

        当以下条件同时满足时认为已划分:
        1. YAML 配置文件存在
        2. processed/<name>/ 下有 train/images 和 val/images 子目录且均包含文件
        """
        if not self.yaml_out.exists():
            return False
        train_dir = self.output_dirs.train_images
        val_dir = self.output_dirs.val_images
        if not train_dir.is_dir() or not val_dir.is_dir():
            return False
        has_train_files = any(train_dir.iterdir())
        has_val_files = any(val_dir.iterdir())
        return has_train_files and has_val_files

    def _run_resplit(self) -> Dict:
        logger.info("处理数据集 %r (format=%s, task=%s, split=%s)",
                    self.dataset_name, self.annotation_format, self.task, self.split_strategy)
        self._check_raw()                              # 预检(含覆盖率 fail-fast),不合格直接抛

        entry = get_converter(self.annotation_format)
        if not entry.supports(self.task):              # 格式不支持该 task,提前报清楚
            raise ValueError(f"格式 {self.annotation_format!r} 不支持 task={self.task!r}。支持: {entry.supported_tasks}")

        # ★ 转换的中间产物写进系统临时目录,出了 with 自动清理 —— 全程不碰 data/raw/(只读圣地)。
        with tempfile.TemporaryDirectory(prefix="odp_pipe_") as tmp:
            staging = Path(tmp) / "labels"
            classes = convert_data_to_yolo(self.raw_annotations, staging, self.annotation_format, self._options)
            pairs = self._pair_images_with_labels(staging)
            labels_per_image = self._build_labels_per_image(pairs, classes)

            # 划分前先打一份只读平衡报告(偏弱行用 WARNING 高亮)。它只提醒,不影响后续流程。
            report = analyze_class_balance(labels_per_image, classes, self.train_rate, self.val_rate)
            for line, is_warning in render_balance_report(report, self.annotation_format):
                (logger.warning if is_warning else logger.info)(line)

            manifest = split_pairs(
                pairs, train_rate=self.train_rate, val_rate=self.val_rate,
                random_state=self.random_state, strategy=self.split_strategy,
                labels_per_image=labels_per_image,     # 对所有策略统一传;随机会忽略它
            )
            counts = materialize(manifest, self.output_dirs)
            write_dataset_yaml(
                self.yaml_out, dataset_root=self.processed_root, classes=classes,
                manifest=manifest, dataset_name=self.dataset_name,
                source_format=self.annotation_format, task=self.task,
            )
        return {"counts": counts, "yaml": str(self.yaml_out)}

    def _run_preserve_split(self) -> Dict:
        logger.info("处理已划分数据集 %r (format=%s, task=%s)", self.dataset_name, self.annotation_format, self.task)
        split_dirs = self._find_existing_split_dirs()
        self._check_preserved_raw(split_dirs)

        entry = get_converter(self.annotation_format)
        if not entry.supports(self.task):
            raise ValueError(f"格式 {self.annotation_format!r} 不支持 task={self.task!r}。支持: {entry.supported_tasks}")

        classes = self._resolve_preserved_classes(split_dirs)
        options = ConvertOptions(task=self.task, classes=classes)

        with tempfile.TemporaryDirectory(prefix="odp_pipe_") as tmp:
            staging_root = Path(tmp) / "labels"
            manifest = SplitManifest(
                train_rate=0.0,
                val_rate=0.0,
                test_rate=0.0,
                random_state=self.random_state,
                strategy=SplitMode.PRESERVE,
            )

            for split_name, split_dir in split_dirs.items():
                labels_dir = staging_root / split_name
                convert_data_to_yolo(split_dir, labels_dir, self.annotation_format, options)
                pairs = self._pair_images_with_labels(labels_dir, images_dir=split_dir)
                setattr(manifest, split_name, pairs)

            total = len(manifest.train) + len(manifest.val) + len(manifest.test)
            if total > 0:
                manifest.train_rate = len(manifest.train) / total
                manifest.val_rate = len(manifest.val) / total
                manifest.test_rate = len(manifest.test) / total

            labels_per_image = self._build_labels_per_image(
                manifest.train + manifest.val + manifest.test,
                classes,
            )
            report = analyze_class_balance(labels_per_image, classes, manifest.train_rate, manifest.val_rate)
            for line, is_warning in render_balance_report(report, self.annotation_format):
                (logger.warning if is_warning else logger.info)(line)

            counts = materialize(manifest, self.output_dirs)
            write_dataset_yaml(
                self.yaml_out, dataset_root=self.processed_root, classes=classes,
                manifest=manifest, dataset_name=self.dataset_name,
                source_format=self.annotation_format, task=self.task,
            )
        return {"counts": counts, "yaml": str(self.yaml_out)}

    # ---- 预检 ---------------------------------------------------------------
    def _check_raw(self) -> None:
        """开跑前的结构与覆盖率预检 —— 把"数据不对"挡在第一秒,而非训练后才发现。"""
        if not self.raw_root.is_dir():
            raise FileNotFoundError(f"数据集目录不存在: {self.raw_root}")
        if not self.raw_images.is_dir():
            raise FileNotFoundError(f"缺少 images 子目录: {self.raw_images}")
        if not self.raw_annotations.is_dir():
            raise FileNotFoundError(f"缺少 annotations 子目录: {self.raw_annotations}")
        self._check_coverage()

    def _check_coverage(self) -> None:
        """图像-标注覆盖率前置校验(撞墙③的解药)。"""
        n_images = sum(len(list(self.raw_images.glob(f"*{ext}"))) for ext in IMAGE_EXTENSIONS)
        if n_images == 0:
            raise FileNotFoundError(f"{self.raw_images} 下没有任何图像")
        if self.annotation_format == AnnotationFormat.COCO:
            # COCO 是单个 json,不存在"每图一标注文件"的 stem 配对,按文件数算覆盖率没意义 → 跳过。
            logger.debug("COCO 跳过 stem 覆盖率检查")
            return
        n_annos = len(list(self.raw_annotations.glob("*.*")))
        coverage = n_annos / n_images
        logger.info("覆盖率: %d/%d = %.1f%%", n_annos, n_images, coverage * 100)
        if coverage < COVERAGE_HARD_THRESHOLD:
            raise ValueError(
                f"图像-标注覆盖率 {coverage:.1%} 低于硬阈值 {COVERAGE_HARD_THRESHOLD:.0%},"
                f"终止以免训练废了(总图像 {n_images}, 有标注 {n_annos})。请检查 annotations/ 或确认 --format。"
            )
        if coverage < COVERAGE_SOFT_THRESHOLD:
            logger.warning("⚠️ 覆盖率 %.1f%% 低于软阈值 %.0f%%,可继续但建议核对。",
                        coverage * 100, COVERAGE_SOFT_THRESHOLD * 100)

    def _find_existing_split_dirs(self) -> Dict[str, Path]:
        candidates = {
            "train": ("train",),
            "val": ("val", "valid", "validation"),
            "test": ("test",),
        }
        result: Dict[str, Path] = {}
        for canonical, names in candidates.items():
            for name in names:
                candidate = self.raw_root / name
                if candidate.is_dir():
                    result[canonical] = candidate
                    break
        return result

    def _check_preserved_raw(self, split_dirs: Dict[str, Path]) -> None:
        if not self.raw_root.is_dir():
            raise FileNotFoundError(f"数据集目录不存在: {self.raw_root}")

        missing = [name for name in ("train", "val") if name not in split_dirs]
        if missing:
            raise FileNotFoundError(
                f"preserve split 模式缺少必要划分目录: {missing}; "
                "支持 train、val/valid/validation、test"
            )

        for split_name, split_dir in split_dirs.items():
            n_images = sum(len(list(split_dir.glob(f"*{ext}"))) for ext in IMAGE_EXTENSIONS)
            if n_images == 0:
                raise FileNotFoundError(f"{split_dir} 下没有图像文件")

            if self.annotation_format == AnnotationFormat.PASCAL_VOC:
                n_annos = len(list(split_dir.glob("*.xml")))
            elif self.annotation_format == AnnotationFormat.YOLO:
                n_annos = len(list(split_dir.glob("*.txt")))
            elif self.annotation_format == AnnotationFormat.COCO:
                n_annos = len(list(split_dir.glob("*.json")))
            else:
                n_annos = 0

            if n_annos == 0:
                raise FileNotFoundError(f"{split_name} split 缺少 {self.annotation_format} 标注文件: {split_dir}")
            logger.info("%s split: %d images, %d annotations", split_name, n_images, n_annos)

    def _resolve_preserved_classes(self, split_dirs: Dict[str, Path]) -> List[str]:
        if self._options.classes:
            return list(self._options.classes)

        if self.annotation_format == AnnotationFormat.YOLO:
            raise ValueError("preserve + yolo 模式必须通过 --classes 显式提供类别顺序")

        classes: List[str] = []
        if self.annotation_format == AnnotationFormat.PASCAL_VOC:
            for split_dir in split_dirs.values():
                for xml_path in sorted(split_dir.glob("*.xml")):
                    root = ET.parse(xml_path).getroot()
                    for obj in root.findall("object"):
                        name = obj.findtext("name")
                        if name and name not in classes:
                            classes.append(name)
        elif self.annotation_format == AnnotationFormat.COCO:
            for split_dir in split_dirs.values():
                for json_path in sorted(split_dir.glob("*.json")):
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    for cat in data.get("categories", []):
                        name = cat.get("name")
                        if name and name not in classes:
                            classes.append(name)

        if not classes:
            raise ValueError("未能从已划分数据集中发现任何类别，请检查标注或使用 --classes")
        return classes

    # ---- 配对 / 标签提取 ----------------------------------------------------
    def _pair_images_with_labels(self, labels_dir: Path, images_dir: Optional[Path] = None) -> PairList:
        """把转换出的 txt 与原图按 stem 配对成 (图, 标) 列表。

        图像索引遍历 IMAGE_EXTENSIONS,所以 png/jpeg/... 都不会被漏(回避"只认 .jpg"的坑)。
        只保留"图存在"的标注;sorted 是复现前提。
        """
        image_root = images_dir or self.raw_images
        image_index = {}
        for ext in IMAGE_EXTENSIONS:
            for img in image_root.glob(f"*{ext}"):
                image_index[img.stem] = img
        pairs: PairList = []
        for lbl in sorted(labels_dir.glob("*.txt")):
            img = image_index.get(lbl.stem)
            if img is not None:
                pairs.append((img, lbl))
        return pairs

    def _build_labels_per_image(self, pairs: PairList, classes: List[str]) -> Dict[str, List[str]]:
        """从每个 txt 的首列 class_id 还原出"每张图有哪些类别名",供分层策略 / 报告用。"""
        result: Dict[str, List[str]] = {}
        for img_path, label_path in pairs:
            names: List[str] = []
            if label_path.exists():
                for line in label_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        cls_id = int(line.split()[0])
                        if 0 <= cls_id < len(classes):
                            names.append(classes[cls_id])
            result[img_path.stem] = names
        return result
