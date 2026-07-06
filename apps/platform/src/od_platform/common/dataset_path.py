#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :dataset_path.py
# @Time      :2026/7/6 14:15:14
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
from __future__ import  annotations

import logging
from pathlib import Path


from od_platform.common.paths import DATASET_CONFIGS_DIR

logger = logging.getLogger(__name__)


def resolve_dataset_path(data: str | Path) -> Path:
    data_path = Path(data)
    # 分支1： 绝对路径
    if data_path.is_absolute():
        return data_path

    # 分支2：仅文件名-按顺序查找
    config_candidate = DATASET_CONFIGS_DIR / data_path.name
    if config_candidate.exists():
        logger.info(f"数据集配置文件已找到: {config_candidate}")
        return config_candidate

    # 分支3: fallback - 下游报错
    logger.warning(f"数据集配置文件未找到: {data_path} "
                f"DATASET_CONFIG_DIR: {DATASET_CONFIGS_DIR}")
    return data_path
