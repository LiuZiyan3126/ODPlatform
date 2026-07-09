"""推理页面 —— 源选择 + 实时预览 + 统计面板."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QVBoxLayout, QWidget, QFormLayout,
)

from od_platform.common.paths import MODELS_DIR, PRETRAINED_MODELS_DIR

from ..workers.inference_worker import InferenceWorker
from ..widgets.frame_viewer import FrameViewer
from ..widgets.progress_panel import ProgressPanel

logger = logging.getLogger(__name__)

SOURCE_TYPES = ["摄像头", "视频文件", "图片文件", "图片文件夹"]


def _scan_models() -> list[str]:
    models: list[str] = []
    for d in (PRETRAINED_MODELS_DIR, MODELS_DIR / "trained"):
        if d.exists():
            for p in sorted(d.rglob("*.pt")):
                try:
                    rel = p.relative_to(MODELS_DIR)
                    models.append(str(rel))
                except ValueError:
                    models.append(str(p))
    if not models:
        models = ["yolo11n.pt", "yolo11s.pt"]
    return models


class InferencePage(QWidget):
    """推理 Tab."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._worker: Optional[InferenceWorker] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── 左侧控制面板 ──
        left_panel = QVBoxLayout()
        left_panel.setSpacing(8)

        # 源选择
        src_group = QGroupBox("输入源")
        src_form = QFormLayout(src_group)

        self._source_type = QComboBox()
        self._source_type.addItems(SOURCE_TYPES)
        self._source_type.currentIndexChanged.connect(self._on_source_type_changed)
        src_form.addRow("类型:", self._source_type)

        src_path_row = QHBoxLayout()
        self._source_path = QLineEdit()
        self._source_path.setPlaceholderText("0 = 默认摄像头, 或选择文件/目录")
        src_path_row.addWidget(self._source_path)

        self._browse_btn = QPushButton("...")
        self._browse_btn.setFixedWidth(36)
        self._browse_btn.clicked.connect(self._on_browse)
        src_path_row.addWidget(self._browse_btn)
        src_form.addRow("路径:", src_path_row)

        left_panel.addWidget(src_group)

        # 模型 + 参数
        model_group = QGroupBox("模型与参数")
        model_form = QFormLayout(model_group)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.addItems(_scan_models())
        model_form.addRow("模型:", self._model_combo)

        self._conf_spin = QDoubleSpinBox()
        self._conf_spin.setRange(0.01, 1.0)
        self._conf_spin.setValue(0.25)
        self._conf_spin.setSingleStep(0.05)
        model_form.addRow("置信度:", self._conf_spin)

        self._iou_spin = QDoubleSpinBox()
        self._iou_spin.setRange(0.01, 1.0)
        self._iou_spin.setValue(0.7)
        self._iou_spin.setSingleStep(0.05)
        model_form.addRow("IoU 阈值:", self._iou_spin)

        self._imgsz_spin = QSpinBox()
        self._imgsz_spin.setRange(160, 2560)
        self._imgsz_spin.setSingleStep(32)
        self._imgsz_spin.setValue(640)
        model_form.addRow("图像尺寸:", self._imgsz_spin)

        left_panel.addWidget(model_group)

        # 控制按钮
        ctrl_group = QGroupBox("控制")
        ctrl_layout = QVBoxLayout(ctrl_group)

        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("开始推理")
        self._start_btn.setMinimumHeight(36)
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("停止")
        self._stop_btn.setMinimumHeight(36)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._stop_btn)
        ctrl_layout.addLayout(btn_row)

        self._snapshot_btn = QPushButton("截图当前帧")
        self._snapshot_btn.clicked.connect(self._on_snapshot)
        ctrl_layout.addWidget(self._snapshot_btn)

        left_panel.addWidget(ctrl_group)

        # 统计
        stats_group = QGroupBox("实时统计")
        stats_layout = QVBoxLayout(stats_group)

        self._label_fps = QLabel("FPS: —")
        self._label_fps.setStyleSheet("color: #4ec9b0; font-size: 18px; font-weight: bold;")
        stats_layout.addWidget(self._label_fps)

        self._label_frames = QLabel("帧数: —")
        stats_layout.addWidget(self._label_frames)

        self._label_dets = QLabel("检测数: —")
        stats_layout.addWidget(self._label_dets)

        self._label_elapsed = QLabel("耗时: —")
        self._label_elapsed.setStyleSheet("color: #888;")
        stats_layout.addWidget(self._label_elapsed)

        left_panel.addWidget(stats_group)

        self._progress = ProgressPanel()
        left_panel.addWidget(self._progress)
        left_panel.addStretch()

        # ── 右侧预览 ──
        right_panel = QVBoxLayout()
        self._viewer = FrameViewer()
        right_panel.addWidget(self._viewer)

        # ── 组装 ──
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        left_widget.setFixedWidth(280)

        right_widget = QWidget()
        right_widget.setLayout(right_panel)

        layout.addWidget(left_widget)
        layout.addWidget(right_widget, 1)

        self._on_source_type_changed(0)

    def _on_source_type_changed(self, idx: int) -> None:
        if idx == 0:  # 摄像头
            self._source_path.setText("0")
            self._source_path.setPlaceholderText("0, 1, 2... 或 RTSP URL")
            self._browse_btn.setVisible(False)
        else:
            self._source_path.setText("")
            self._browse_btn.setVisible(True)

    def _on_browse(self) -> None:
        idx = self._source_type.currentIndex()
        if idx == 1:  # 视频
            path, _ = QFileDialog.getOpenFileName(
                self, "选择视频", "",
                "视频 (*.mp4 *.avi *.mov *.mkv *.flv);;所有文件 (*)",
            )
        elif idx == 2:  # 图片
            path, _ = QFileDialog.getOpenFileName(
                self, "选择图片", "",
                "图片 (*.jpg *.jpeg *.png *.bmp *.tiff);;所有文件 (*)",
            )
        elif idx == 3:  # 文件夹
            path = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        else:
            return
        if path:
            self._source_path.setText(path)

    def _build_source(self) -> str:
        raw = self._source_path.text().strip()
        idx = self._source_type.currentIndex()
        if idx == 0:  # 摄像头
            return raw or "0"
        return raw

    def _on_start(self) -> None:
        if self._worker and self._worker.isRunning():
            return

        source = self._build_source()
        model = self._model_combo.currentText().strip()
        if not source:
            QMessageBox.warning(self, "缺少参数", "请指定输入源")
            return
        if not model:
            QMessageBox.warning(self, "缺少参数", "请选择模型")
            return

        self._set_running(True)
        self._reset_stats()
        self._viewer.clear()
        self._viewer.setStyleSheet("background-color: #000;")

        self._worker = InferenceWorker(
            source=source,
            model=model,
            conf=self._conf_spin.value(),
            iou=self._iou_spin.value(),
            imgsz=self._imgsz_spin.value(),
            save=False,
            parent=self,
        )
        self._worker.frame_ready.connect(
            self._viewer.on_frame, Qt.QueuedConnection,
        )
        self._worker.stats_signal.connect(self._on_stats, Qt.QueuedConnection)
        self._worker.progress.connect(self._on_progress, Qt.QueuedConnection)
        self._worker.finished.connect(self._on_finished, Qt.QueuedConnection)
        self._worker.error.connect(self._on_error, Qt.QueuedConnection)
        self._worker.start()

    def _on_stop(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        self._set_running(False)
        self._progress.set_status("已停止")

    def _on_snapshot(self) -> None:
        if self._viewer._latest_frame is not None:
            import cv2
            from datetime import datetime
            name = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            cv2.imwrite(name, self._viewer._latest_frame)
            logger.info("截图已保存: %s", name)

    def _set_running(self, running: bool) -> None:
        self._start_btn.setEnabled(not running)
        self._start_btn.setText("推理中..." if running else "开始推理")
        self._stop_btn.setEnabled(running)
        self._source_type.setEnabled(not running)
        self._source_path.setEnabled(not running)
        self._browse_btn.setEnabled(not running)
        self._model_combo.setEnabled(not running)

    def _reset_stats(self) -> None:
        self._label_fps.setText("FPS: —")
        self._label_frames.setText("帧数: —")
        self._label_dets.setText("检测数: —")
        self._label_elapsed.setText("耗时: —")

    def _on_stats(self, stats: dict) -> None:
        fps = stats.get("fps_loop", 0)
        self._label_fps.setText(f"FPS: {fps:.1f}")
        self._label_frames.setText(
            f"帧数: {stats.get('frame_idx', 0)}"
            + (f"/{stats.get('total_frames')}" if stats.get("total_frames") else "")
        )
        self._label_dets.setText(f"检测数: {stats.get('detection_count', 0)}")
        self._label_elapsed.setText(f"耗时: {stats.get('elapsed_sec', 0):.1f}s")

    def _on_progress(self, percent: int, status: str) -> None:
        self._progress.set_progress(percent, status)

    def _on_finished(self, result: object) -> None:
        self._set_running(False)
        logger.info("推理完成")

    def _on_error(self, error_msg: str) -> None:
        self._set_running(False)
        self._progress.set_progress(0, f"错误: {error_msg}")
