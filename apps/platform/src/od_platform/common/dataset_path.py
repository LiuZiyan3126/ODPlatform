#!/usr/bin/env python
# -*- coding:utf-8 -*-
from __future__ import annotations

import logging
from pathlib import Path

from od_platform.common.paths import DATASET_CONFIGS_DIR

logger = logging.getLogger(__name__)


def resolve_dataset_path(data: str | Path) -> Path:
    """Resolve dataset config references used by train/eval.

    Supported inputs:
    - absolute YAML path;
    - relative YAML path;
    - YAML filename such as ``fire.yaml``;
    - bare dataset name such as ``fire`` -> ``configs/datasets/fire.yaml``.
    """
    data_path = Path(data)
    if data_path.is_absolute():
        return data_path

    candidates: list[Path] = [
        data_path,
        DATASET_CONFIGS_DIR / data_path.name,
    ]
    if data_path.suffix == "":
        candidates.extend(
            [
                data_path.with_suffix(".yaml"),
                data_path.with_suffix(".yml"),
                DATASET_CONFIGS_DIR / f"{data_path.name}.yaml",
                DATASET_CONFIGS_DIR / f"{data_path.name}.yml",
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            resolved = candidate.resolve()
            logger.info("数据集配置文件已找到: %s", resolved)
            return resolved

    logger.warning(
        "数据集配置文件未找到: %s DATASET_CONFIG_DIR: %s",
        data_path,
        DATASET_CONFIGS_DIR,
    )
    return data_path
