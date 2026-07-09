"""帧查看器 —— QLabel 实时显示推理帧 (BGR ndarray → QPixmap)."""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget


class FrameViewer(QWidget):
    """实时显示推理标注帧.

    通过 on_frame() slot 接收 BGR ndarray, 转为 QPixmap 显示.
    使用 QTimer 限制刷新率避免 UI 过载.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._label = QLabel("推理预览区域")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("""
            QLabel {
                background-color: #1a1a1a;
                color: #555;
                border: 2px dashed #3c3c3c;
                border-radius: 6px;
                font-size: 16px;
            }
        """)
        self._label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._label.setMinimumSize(320, 240)

        self._latest_frame: Optional[np.ndarray] = None
        self._has_frame = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        # 定时器限帧: ~30 FPS
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_display)
        self._timer.start(33)

    def on_frame(self, frame: np.ndarray) -> None:
        """接收标注帧 (BGR ndarray), 可能在非 UI 线程调用."""
        self._latest_frame = frame
        self._has_frame = True

    def _update_display(self) -> None:
        if not self._has_frame or self._latest_frame is None:
            return

        try:
            frame = self._latest_frame
            h, w = frame.shape[:2]

            # BGR → RGB
            rgb = frame[..., ::-1].copy()

            # 按 Label 尺寸缩放
            qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            scaled = pixmap.scaled(
                self._label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self._label.setPixmap(scaled)
            self._label.setStyleSheet("border: none; background-color: #000;")
        except Exception:
            pass

    def clear(self) -> None:
        self._latest_frame = None
        self._has_frame = False
        self._label.clear()
        self._label.setText("推理预览区域")
        self._label.setStyleSheet("""
            QLabel {
                background-color: #1a1a1a;
                color: #555;
                border: 2px dashed #3c3c3c;
                border-radius: 6px;
                font-size: 16px;
            }
        """)
