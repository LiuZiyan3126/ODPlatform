#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :snapshot.py
# @Time      :2026/7/2 14:45:37
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :Dataset snapshot - 一次扫描多次复用
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

from od_platform.common.constants import IMAGE_EXTENSIONS, Task
from od_platform.common.performance_utils import time_it

logger = logging.getLogger(__name__)

# SplitStats轻量统计

@dataclass(frozen=True)
class SplitStats:
    image_count: int
    annotated_count: int
    total_instances: int

@dataclass(frozen=True)
class DatasetSnapshot:
    """对数据集做一次完整的快照，供所有check共享消费"""
    yaml_path: Path
    yaml_data: Dict[str, Any]
    yaml_load_error: Optional[str]
    data_root: Path
    nc: Optional[int]
    class_names: Tuple[str, ...]
    task_type: str
    images_per_split: Dict[str, Tuple[Path,...]]
    labels_per_split: Dict[str, Tuple[Path,...]]
    stats_per_split: Dict[str, SplitStats]
    scan_warnings: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def splits(self) -> Tuple[str,...]:
        order = ("train", "val", "test")
        return tuple(s for s in order if s in self.images_per_split)

    @property
    def total_images(self) -> int:
        return sum(len(imgs) for imgs in self.images_per_split.values())


# 定义内部辅助函数
def _load_yaml(yaml_path: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    if not yaml_path.exists():
        return {}, f"YAML file does not exist: {yaml_path}"
    try:
        with open(yaml_path, "r", encoding='utf-8') as f:
            data =  yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                return {}, f"YAML 的顶层不是一个dict: {type(data).__name__}"
            return data, None
    except yaml.YAMLError as e:
        return {}, f"Error loading YAML file: {e}"
    except OSError as e:
        return {}, f"Error reading YAML file: {e}"

def _resolve_data_root(yaml_path:Path, yaml_data: Dict[str,Any]) -> Path:
    path_str = yaml_data.get("path")
    if not path_str:
        return yaml_path.parent.resolve()
    p = Path(path_str)
    return p.resolve() if p.is_absolute() else (yaml_path.parent / p).resolve()


def _resolve_split_dir(data_root: Path, split_filed: Any) -> Optional[Path]:
    if not isinstance(split_filed, str) or not split_filed.strip():
        return None
    p = Path(split_filed)
    return p.resolve() if p.is_absolute() else (data_root / p).resolve()

def _list_images(split_dir:Path) -> List[Path]:
    if not split_dir.exists() or not split_dir.is_dir():
        return []
    images: List[Path] = []
    for ext in IMAGE_EXTENSIONS:
        images.extend(split_dir.glob(f"*{ext}"))
        images.extend(split_dir.glob(f"*{ext.upper()}"))
    return sorted(set(images))

def _label_path_for_images(image_path: Path) -> Path:
    parts = list(image_path.parts)
    for i in range(len(parts) -1, -1, -1):
        if parts[i] == "images":
            parts[i] = "labels"
            break
    return Path(*parts[:-1], image_path.stem + ".txt")

def _normalize_names(names_raw: Any) -> Tuple[str, ...]:
    if isinstance(names_raw, list):
        if all(isinstance(n, str) for n in names_raw):
            return tuple(names_raw)
        return  ()

    if isinstance(names_raw, dict):
        if all(isinstance(k, int) for k in names_raw.keys()) and all(isinstance(v, str) for v in names_raw.values()):
            return  tuple(v for _, v in sorted(names_raw.items()))
        return  ()
    return ()

def _build_split_stats(labels: List[Path]) -> SplitStats:
    image_count = len(labels)
    annotations = 0
    total_instances = 0

    for lbl in labels:
        if not lbl.exists():
            continue
        try:
            content = lbl.read_text(encoding='utf-8')
        except OSError:
            continue
        lines = [l for l in content.splitlines() if l.strip()]
        if not lines:
            continue
        annotations += 1
        total_instances += len(lines)

    return  SplitStats(
        image_count = image_count,
        annotated_count = annotations,
        total_instances = total_instances
    )

# 构建最终的快照
def build_snapshot(yaml_path: Path,task_type: Optional[str] = None)-> DatasetSnapshot:
    yaml_path = yaml_path.resolve()
    warnings: List[str] = []
    yaml_data, yaml_err = _load_yaml(yaml_path)
    if yaml_err:
        warnings.append(yaml_err)

    data_root = _resolve_data_root(yaml_path, yaml_data)
    nc = yaml_data.get("nc") if isinstance(yaml_data.get('nc'), int) else None
    class_names = _normalize_names(yaml_data.get("names"))
    # 任务类型：兼容旧 YAML 顶层 task，也读取当前 odp_meta.task。
    odp_meta = yaml_data.get("odp_meta")
    metadata_task = odp_meta.get("task") if isinstance(odp_meta, dict) else None
    resolved_task = task_type or yaml_data.get("task") or metadata_task or Task.DETECT
    if resolved_task not in (Task.DETECT, Task.SEGMENT):
        warnings.append(f"Invalid task type: {resolved_task}. Using {Task.DETECT} instead.")
        resolved_task = Task.DETECT

    images_per_split: Dict[str, Tuple[Path, ...]] = {}
    labels_per_split: Dict[str, Tuple[Path, ...]] = {}
    stats_per_split: Dict[str, SplitStats] = {}

    for split in ("train", "val", "test"):
        split_dir = _resolve_split_dir(data_root, yaml_data.get(split))
        if split_dir is None:
            if split in yaml_data:
                warnings.append(f"Split directory '{split_dir}' 目录不可用.")
            continue
        if not split_dir.exists():
            warnings.append(f"Split directory '{split_dir}' 目录不可用.")
            continue
        images = _list_images(split_dir)
        if not images:
            warnings.append(f"split: {split} 目录下没有图像： {split_dir}")
            continue
        labels = [_label_path_for_images(img) for img in images]
        images_per_split[split] = tuple(images)
        labels_per_split[split] = tuple(labels)
        stats_per_split[split] = _build_split_stats(labels)

    snapshot = DatasetSnapshot(
        yaml_path=yaml_path,
        yaml_data=yaml_data,
        yaml_load_error=yaml_err,
        data_root=data_root,
        nc=nc,
        class_names=class_names,
        task_type=resolved_task,
        images_per_split=images_per_split,
        labels_per_split=labels_per_split,
        stats_per_split=stats_per_split,
        scan_warnings=tuple(warnings)
    )
    logger.info(f"Dataset snapshot built for {yaml_path}"
                f"split={list(snapshot.splits)}, task = {resolved_task}")

    return snapshot

























