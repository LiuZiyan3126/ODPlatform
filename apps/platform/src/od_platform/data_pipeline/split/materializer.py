#!/usr/bin/env python
# -*- coding:utf-8 -*-
# FileName    :materializer.py
# Time    :2026/7/1 10:32:32
# Author    :周周同学
# Project    :ODPlatform
# Function    :把 SplitManifest 的三组样本真正的落盘到train_val,test目录中
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from od_platform.data_pipeline.split.manifest import PairList, SplitManifest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)  # 让数据类的实例成为不可变对象
class SplitOutputDirs:
    train_images: Path
    val_images: Path
    test_images: Path
    train_labels: Path
    val_labels: Path
    test_labels: Path

    @classmethod
    def for_dataset_root(cls, root: Path) -> "SplitOutputDirs":
        return cls(
            train_images=root / "train" / "images",
            val_images=root / "val" / "images",
            test_images=root / "test" / "images",
            train_labels=root / "train" / "labels",
            val_labels=root / "val" / "labels",
            test_labels=root / "test" / "labels",
        )

    def all_dirs(self):
        return (
            self.train_images,
            self.train_labels,
            self.test_images,
            self.test_labels,
            self.val_images,
            self.val_labels,
        )


def _place(src: Path, dst: Path) -> None:
    try:
        if dst.exists():
            dst.unlink()
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def materialize_one(pair_list: PairList, img_dir: Path, label_dir: Path) -> int:
    img_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    
    count = 0
    for img_path, label_path in pair_list:
        # 使用原始文件名
        img_name = img_path.name
        label_name = label_path.name
        
        dst_img = img_dir / img_name
        dst_label = label_dir / label_name
        
        _place(img_path, dst_img)
        _place(label_path, dst_label)
        count += 1
    
    return count


def materialize(manifest: SplitManifest, dirs: SplitOutputDirs) -> Dict[str, int]:
    # 清理旧目录
    for d in dirs.all_dirs():
        if d.exists():
            shutil.rmtree(d)
    
    counts = {
        "train": materialize_one(manifest.train, dirs.train_images, dirs.train_labels),
        "val": materialize_one(manifest.val, dirs.val_images, dirs.val_labels),
        "test": materialize_one(manifest.test, dirs.test_images, dirs.test_labels),
    }
    
    logger.info(f"materialized {counts}")
    return counts