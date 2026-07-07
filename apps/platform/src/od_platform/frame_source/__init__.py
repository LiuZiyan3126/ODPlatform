#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :__init__.py.py
# @Time      :2026/7/7 13:01:28
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
from __future__ import annotations

from .core.types import  (SourceType,FrameInfo, Frame, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS)
from .core.config import (CameraConfig, CameraBackend, CameraCodec)
from .core.base import FrameSource

from .sources.camera import CameraSource
from .sources.video import VideoSource
from .sources.image import ImageSource, ImageFolderSource

from .factory import  create_frame_source

__all__ = [
    "create_frame_source",
    "CameraSource",
    "VideoSource",
    "ImageSource",
    "ImageFolderSource",
    "SourceType",
    "FrameInfo",
    "Frame",
    "IMAGE_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "CameraConfig",
    "CameraBackend",
    "CameraCodec",
]