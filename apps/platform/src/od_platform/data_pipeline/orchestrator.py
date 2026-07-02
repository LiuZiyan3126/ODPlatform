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
from pathlib import Path
from typing import Dict, List, Optional

from od_platform.common import paths
from od_platform.common.constants import (
    COVERAGE_HARD_THRESHOLD, COVERAGE_SOFT_THRESHOLD, DEFAULT_RANDOM_STATE, DEFAULT_SPLIT_STRATEGY,
    IMAGE_EXTENSIONS, AnnotationFormat, Task
)

from od_platform.common.refs import  resolve_dataset
from od_platform.data_pipeline.convert.registry import ConvertOptions, get_converter
from od_platform.data_pipeline.convert.service import convert_data_to_yolo
from od_platform.data_pipeline.report import analyze_class_balance, render_balance_report
from od_platform.data_pipeline.split.manifest import PairList
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
    ):
        self.annotation_format = annotation_format
        self.task = task
        self.train_rate = train_rate
        self.val_rate = val_rate
        self.random_state = random_state
        self.split_strategy = split_strategy
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

    # ---- 配对 / 标签提取 ----------------------------------------------------
    def _pair_images_with_labels(self, labels_dir: Path) -> PairList:
        """把转换出的 txt 与原图按 stem 配对成 (图, 标) 列表。

        图像索引遍历 IMAGE_EXTENSIONS,所以 png/jpeg/... 都不会被漏(回避"只认 .jpg"的坑)。
        只保留"图存在"的标注;sorted 是复现前提。
        """
        image_index = {}
        for ext in IMAGE_EXTENSIONS:
            for img in self.raw_images.glob(f"*{ext}"):
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
