"""进度面板 —— QProgressBar + 状态标签."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget,
)


class ProgressPanel(QWidget):
    """水平进度条 + 状态文本 + 百分比."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(18)

        self._pct_label = QLabel("0%")
        self._pct_label.setFixedWidth(40)
        self._pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet("color: #888;")

        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.addWidget(self._bar)
        bar_row.addWidget(self._pct_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(bar_row)
        layout.addWidget(self._status_label)

    def set_progress(self, percent: int, status: str = "") -> None:
        self._bar.setValue(percent)
        self._pct_label.setText(f"{percent}%")
        if status:
            self._status_label.setText(status)

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def reset(self) -> None:
        self._bar.setValue(0)
        self._pct_label.setText("0%")
        self._status_label.setText("就绪")
