from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import numpy as np


class SourceType(str, Enum):
    """输入源类型枚举"""
    CAMERA = "camera"
    IMAGE = "image"
    VIDEO = "video"
    IMAGE_FOLDER = "image_folder"

IMAGE_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"})
VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv"})

@dataclass
class FrameInfo:
    """定义帧元数据"""
    # 图像的尺寸
    width: int
    height: int
    # 源信息
    source_type: SourceType
    source_path: str
    # 序列信号
    frame_index: int = 0
    total_frames: Optional[int] = None

    # 时间信息
    timestamp: float = 0.0
    fps: Optional[float] = None
    # 文件名
    filename: Optional[str] = None

    # 分辨率
    @property
    def resolution(self) -> tuple[int, int]:
        return self.width, self.height

@dataclass
class Frame:
    image: np.ndarray
    info: FrameInfo

    @property
    def resolution(self) -> tuple[int, int]:
        return self.info.resolution

    @property
    def width(self) -> int:
        return self.info.width

    @property
    def height(self) -> int:
        return self.info.height