#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :factory.py
# @Time      :2026/7/7 15:56:48
# @Author    :雨霁同学
# @Project   :ODPlatform
# @Function  :
from __future__ import annotations

import logging
from typing import Any, Optional

from .core.base import FrameSource
from .core.config import CameraConfig

logger = logging.getLogger(__name__)


def _build_source(
        source: str,
        camera_config: Optional[CameraConfig],
        options: dict[str, Any]
    ) -> FrameSource:
    from .registry import find_source
    return find_source(source, camera_config, options)


def create_frame_source(
        source: str,
        camera_config: Optional[CameraConfig] = None,
        *,
        stride: int = 1,
        **options: Any
) -> FrameSource:
    if stride < 1:
        raise ValueError(f"stride必须大于等于1")
    inner = _build_source(source, camera_config, options)
    if stride > 1:
        inner.set_stride(stride)
    return inner
