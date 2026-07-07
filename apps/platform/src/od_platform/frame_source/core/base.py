from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Iterator, Optional
from .types import Frame, SourceType

logger = logging.getLogger(__name__)


class FrameSource(ABC):
    def __init__(self, source_path: str):
        self.source_path = source_path
        self.frame_index = 0
        self._strike = 1
        self._start_time = time.time()

    @abstractmethod
    def open(self) -> bool:
        """打开输入源，返回是否成功"""

    @abstractmethod
    def read(self) -> Optional[Frame]:
        """读取一帧数据，返回是否成功"""

    @abstractmethod
    def close(self) -> None:
        """关闭输入源，释放资源"""

    @abstractmethod
    def get_source_type(self) -> SourceType:
        """返回输入源类型"""

    def seek(self, frame: Optional[list], time_sec: Optional[float] = None) -> bool:
        logger.warning(f"{self.__class__.__name__} 不支持seek操作")
        return False
    
    def seekable(self) -> bool:
        """是否支持seek，子类覆盖返回True"""
        return False
    
    def set_stride(self, stride: int) -> None:
        """设置跳采步长"""
        if stride < 1:
            raise ValueError("stride必须大于等于1")
        if stride > 1:
            logger.debug(f"{self.__class__.__name__} 设置跳采步长为{stride}")

    def stride(self) -> int:
        return self._strike
    
    # 上下文管理器
    def __enter__(self) -> "FrameSource":
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False
    
    # 迭代器协议
    def __iter__(self) -> Iterator[Frame]:
        return self
    
    def __next__(self) -> Frame:
        frame = self.read()
        if frame is None:
            raise StopIteration
        return frame