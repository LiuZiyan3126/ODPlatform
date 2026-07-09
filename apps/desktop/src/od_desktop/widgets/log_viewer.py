"""日志查看器 —— QPlainTextEdit + logging.Handler 桥接."""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget, QPushButton, QHBoxLayout

LEVEL_COLORS = {
    logging.DEBUG: QColor(128, 128, 128),
    logging.INFO: QColor(200, 200, 200),
    logging.WARNING: QColor(220, 180, 60),
    logging.ERROR: QColor(220, 80, 80),
    logging.CRITICAL: QColor(255, 60, 60),
}


class _QtLogSignalEmitter(QObject):
    log_received = Signal(str, int)  # message, levelno


_emitter: Optional[_QtLogSignalEmitter] = None


def _get_emitter() -> _QtLogSignalEmitter:
    global _emitter
    if _emitter is None:
        _emitter = _QtLogSignalEmitter()
    return _emitter


class QtLogHandler(logging.Handler):
    """将 Python logging 记录转发为 Qt 信号(线程安全)."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                                             datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        _get_emitter().log_received.emit(msg, record.levelno)


def _install_handler() -> None:
    root = logging.getLogger()
    h = QtLogHandler()
    h.setLevel(logging.DEBUG)
    root.addHandler(h)


class LogViewer(QWidget):
    """带清空按钮的日志查看器."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        _install_handler()

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(5000)
        self._text.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
            }
        """)

        clear_btn = QPushButton("清空")
        clear_btn.setFixedWidth(60)
        clear_btn.clicked.connect(self._text.clear)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addStretch()
        toolbar.addWidget(clear_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(toolbar)
        layout.addWidget(self._text)

        _get_emitter().log_received.connect(self._on_log, Qt.QueuedConnection)

    def _on_log(self, message: str, levelno: int) -> None:
        color = LEVEL_COLORS.get(levelno, QColor(200, 200, 200))
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        self._text.setCurrentCharFormat(fmt)
        self._text.appendPlainText(message)
