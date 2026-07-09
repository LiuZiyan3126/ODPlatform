"""QtSignalSink —— 将推理标注帧通过 Qt 信号发送到 UI 线程."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from od_platform.frame_source import SourceType

logger = logging.getLogger(__name__)


class QtSignalSink(QObject):
    """OutputSink 协议实现, 通过 Qt 信号发送标注帧 (跨线程安全).

    不继承 OutputSink ABC (避免 QObject/ABC 元类冲突),
    直接实现 open/write/close 协议 (Python duck typing).
    """

    frame_ready = Signal(np.ndarray)       # annotated BGR image (copy)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._count = 0

    def open(self, output_dir: Path, source_type: SourceType) -> None:
        self._count = 0
        logger.debug("QtSignalSink opened (source_type=%s)", source_type.value)

    def write(self, frame, annotated: np.ndarray) -> None:
        try:
            # copy 确保跨线程安全
            self.frame_ready.emit(annotated.copy())
            self._count += 1
        except Exception as e:
            logger.warning("QtSignalSink.write 失败: %s", e)

    def close(self) -> None:
        logger.debug("QtSignalSink closed (%d frames)", self._count)
