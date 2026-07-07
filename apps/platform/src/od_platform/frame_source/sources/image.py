#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :image.py
# @Time      :2026/7/7 14:03:45
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :单张图像 、图像文件夹 同时处理

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional
import cv2
import numpy as np

from ..core.base import FrameSource
from ..core.types import Frame,FrameInfo, IMAGE_EXTENSIONS, SourceType

logger = logging.getLogger(__name__)

class ImageSource(FrameSource):
    def __init__(self, image_path: str):
        super().__init__(image_path)
        self._image: Optional[np.ndarray] = None
        self._read_count = 0
        self._file_name = Path(image_path).name

    def open(self) -> bool:
        self._read_count = 0
        self._image = cv2.imread(self.source_path)
        if self._image is None:
            logger.error(f"Failed to read image: {self.source_path}")
            return False
        h, w = self._image.shape[:2]
        logger.info(f"Image loaded: {self.source_path}, shape: ({w} x {h})")
        return True


    def read(self) -> Optional[Frame]:
        # 单图stride没有意义，忽略它
        if self._image is None or self._read_count > 0:
            return None
        h, w = self._image.shape[:2]
        info = FrameInfo(
            width=w, height=h,
            source_type=SourceType.IMAGE,
            source_path=self.source_path,
            frame_index=0,
            total_frames=1,
            filename=self._file_name
        )
        self._read_count += 1

        return Frame(image=self._image.copy(), info=info)

    def close(self) -> None:
        self._image = None

    def get_source_type(self) -> SourceType:
        return SourceType.IMAGE


class ImageFolderSource(FrameSource):
    def __init__(self, folder_path: str):
        super().__init__(folder_path)
        self._stride: int = 1
        self._image_files: List[Path] = []
        self._current_index = 0

    def open(self) -> bool:
        self._current_index = 0
        folder = Path(self.source_path)
        if not folder.is_dir():
            logger.error(f"不是有效的文件夹：{self.source_path}")
            return False
        self._image_files = sorted([
            f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS])
        if not self._image_files:
            logger.error(f"文件夹{self.source_path}中没有找到有效的图像文件")
            return False
        logger.info(f"文件夹已经加载 {folder.name} 共{len(self._image_files)}张")
        return True


    def read(self) -> Optional[Frame]:
        if self._stride > 1 and self._current_index > 0:
            self._current_index += (self._stride - 1)
        while self._current_index < len(self._image_files):
            image_path = self._image_files[self._current_index]
            image = cv2.imread(str(image_path))

            if image is None:
                logger.warning(f"无法读取，已经跳过： {image_path.name}")
                self._current_index += 1
                continue
            h, w = image.shape[:2]
            info = FrameInfo(
                width=w, height=h,
                source_type=SourceType.IMAGE_FOLDER,
                source_path=self.source_path,
                frame_index=self._current_index,
                total_frames=len(self._image_files),
                filename=image_path.name
            )
            self._current_index += 1
            return Frame(image=image, info=info)
        return None

    def close(self) -> None:
        self._image_files = []
        logger.info("文件夹已经关闭")

    def get_source_type(self) -> SourceType:
        return SourceType.IMAGE_FOLDER

    def seek(self, frame: Optional[int] = None, time_sec: Optional[float] = None) -> bool:
        if time_sec is not None:
            logger.warning(f"图像文件夹不支持按时间跳转，请使用frame参数")
            return False
        if frame is None:
            logger.error("必须要制定frame参数")
            return False
        total = len(self._image_files)
        target = max(0, min(frame, total-1)) if total > 0 else 0
        self._current_index = target
        logger.debug(f"图片文件夹跳转到索引{target}")
        return True
    
    @property
    def seekable(self) -> bool:
        return True