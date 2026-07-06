#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :model_path.py
# @Time      :2026/7/6 14:16:21
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
from __future__ import  annotations

import logging
from pathlib import Path
from typing import Sequence


from od_platform.common.paths import PRETRAINED_MODELS_DIR

logger = logging.getLogger(__name__)

def resolve_model_path(model:str | Path, *, search_dirs: Sequence[Path] | None = None) -> Path:
    model_path = Path(model)

    # 分支1： 绝对路径
    if model_path.is_absolute():
        return model_path

    # 分支2：仅文件名-按顺序查找
    dirs: Sequence[Path] = search_dirs if search_dirs is not None else [PRETRAINED_MODELS_DIR]
    for d in dirs:
        candidate = d / model_path.name
        if candidate.exists():
            logger.info(f"模型文件已找到: {candidate}")
            return candidate
    # 分支3: fallback - 默认模型
    logger.warning(f"模型文件未找到: {model_path}\n"
                f"搜索过目录： {[str(d) for d in dirs]}\n"
                f"Ultralytics将会自动下载模型或从其他位置加载")
    return model_path
