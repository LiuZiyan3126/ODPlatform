"""后台工作线程基类."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class BaseWorker(QThread):
    """所有后台 worker 的基类,提供统一的信号接口."""

    started = Signal()
    finished = Signal(object)   # result
    error = Signal(str)         # error message
    progress = Signal(int, str)  # percent (0-100), status text

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
