#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :video.py
# @Time      :2026/7/7 14:46:19
# @Author    :雨霁同学
# @Project   :ODPlatform
# @Function  :

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
import cv2

from ..core.base import FrameSource
from ..core.types import Frame, FrameInfo, SourceType, VIDEO_EXTENSIONS
from ..registry import register_source

logger = logging.getLogger(__name__)


class VideoSource(FrameSource):
    def __init__(self, video_path: str):
        super().__init__(video_path)
        self._cap: Optional[cv2.VideoCapture] = None
        self._width: int = 0
        self._height: int = 0
        self._fps: float | int = 0.0
        self._total_frames: int = 0
        self._filename = Path(video_path).name
        self._frame_index = 0

    def open(self) -> bool:
        self._frame_index = 0
        self._cap = cv2.VideoCapture(self.source_path)
        if not self._cap.isOpened():
            logger.error(f"Failed to open video: {self.source_path}")
            return False
        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))

        raw_fps = self._cap.get(cv2.CAP_PROP_FPS)
        if not raw_fps or raw_fps <= 0:
            logger.warning(f"视频 {self._filename} FPS元数据确定或者未知，"
                           f"已经回退到默认值30FPS,注意seek(time_sec=...)结果可能准确")
            self._fps = 30.0
        else:
            self._fps = raw_fps

        logger.info(f"视频 {self._filename} 已经打开")
        logger.info(f"视频分辨率: {self._width}x{self._height} @ {self._fps:.1f}FPS")
        logger.info(f"视频总帧数: {self._total_frames}")
        return True

    def read(self) -> Optional[Frame]:
        if self._cap is None:
            return None

        if self._stride > 1 and self._frame_index > 0:
            for _ in range(self._stride - 1):
                if not self._cap.grab():
                    return None
                self._frame_index += 1
        ret, image = self._cap.read()
        if not ret:
            return None
        info = FrameInfo(
            width=self._width,
            height=self._height,
            source_type=SourceType.VIDEO,
            source_path=self.source_path,
            frame_index=self._frame_index,
            total_frames=self._total_frames,
            timestamp=self._frame_index / self._fps if self._fps > 0 else 0,
            fps=self._fps,
            filename=self._filename
        )
        self._frame_index += 1
        return Frame(image=image, info=info)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("视频已经关闭")

    def get_source_type(self) -> SourceType:
        return SourceType.VIDEO

    def seek(self, frame: Optional[int] = None,
             time_sec: Optional[float | int] = None) -> bool:
        if self._cap is None:
            logger.error("视频未打开，无法跳帧")
            return False
        if (frame is None) == (time_sec is None):
            logger.error("frame 和 time_sec必须且只能指定一个")
            return False
        assert frame is not None
        target = int(time_sec * self._fps) if time_sec is not None else int(frame)
        target = max(0, target)
        if self._total_frames > 0:
            target = min(target, self._total_frames - 1)
        ok = self._cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        if ok:
            self._frame_index = target
            logger.debug(f"视频跳转到帧 {target}")
        else:
            logger.warning(f"视频跳转到帧 {target} 失败")
        return ok

    @property
    def seekable(self) -> bool:
        return True

    @property
    def duration(self) -> float | int:
        if self._fps > 0 and self._total_frames > 0:
            return self._total_frames / self._fps
        return 0.0


_STREAM_SCHEMES = ("rtsp://", "http://", "https://", "rtmp://")


@register_source("video_stream",
                 detect=lambda s: s.lower().startswith(_STREAM_SCHEMES), priority=1)
def _build_video_stream(source: str, camera_config, options) -> VideoSource:
    return VideoSource(source)


@register_source("video_file",
                 detect=lambda s: (Path(s).exists() and Path(s).is_file()
                                   and Path(s).suffix.lower() in VIDEO_EXTENSIONS),
                 priority=3)
def _build_video_file(source: str, camera_config, options) -> VideoSource:
    return VideoSource(source)
