"""训练页面 —— 配置 + 启动训练 + 实时进度监控."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSpinBox, QDoubleSpinBox, QFormLayout,
    QVBoxLayout, QWidget, QLineEdit,
)

from od_platform.common.paths import (
    DATASET_CONFIGS_DIR, PRETRAINED_MODELS_DIR, MODELS_DIR,
)

from ..workers.training_worker import TrainingWorker
from ..widgets.progress_panel import ProgressPanel

logger = logging.getLogger(__name__)


def _scan_models() -> list[str]:
    """扫描模型文件."""
    models: list[str] = []
    for d in (PRETRAINED_MODELS_DIR, MODELS_DIR / "trained"):
        if d.exists():
            for p in sorted(d.rglob("*.pt")):
                rel = p.relative_to(MODELS_DIR)
                models.append(str(rel))
    if not models:
        models = ["yolo11n.pt", "yolo11s.pt", "yolo11m.pt"]
    return models


def _scan_datasets() -> list[str]:
    """扫描已处理的数据集."""
    if not DATASET_CONFIGS_DIR.exists():
        return []
    return sorted(p.stem for p in DATASET_CONFIGS_DIR.glob("*.yaml"))


class TrainingPage(QWidget):
    """训练 Tab: 选择模型/数据集 → 配置 → 训练."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._worker: Optional[TrainingWorker] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── 核心配置 ──
        core_group = QGroupBox("核心配置")
        core_form = QFormLayout(core_group)
        core_form.setLabelAlignment(Qt.AlignRight)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.addItems(_scan_models())
        core_form.addRow("模型:", self._model_combo)

        self._dataset_combo = QComboBox()
        datasets = _scan_datasets()
        self._dataset_combo.addItems(datasets)
        core_form.addRow("数据集:", self._dataset_combo)

        task_row = QHBoxLayout()
        self._epochs_spin = QSpinBox()
        self._epochs_spin.setRange(1, 10000)
        self._epochs_spin.setValue(100)
        task_row.addWidget(QLabel("Epochs:"))
        task_row.addWidget(self._epochs_spin)

        self._imgsz_spin = QSpinBox()
        self._imgsz_spin.setRange(32, 2560)
        self._imgsz_spin.setSingleStep(32)
        self._imgsz_spin.setValue(640)
        task_row.addWidget(QLabel("Imgsz:"))
        task_row.addWidget(self._imgsz_spin)

        self._batch_spin = QSpinBox()
        self._batch_spin.setRange(1, 512)
        self._batch_spin.setValue(16)
        task_row.addWidget(QLabel("Batch:"))
        task_row.addWidget(self._batch_spin)

        task_row.addStretch()
        core_form.addRow("训练参数:", task_row)

        self._device_edit = QLineEdit()
        self._device_edit.setPlaceholderText("留空=自动, 如: 0, cpu, 0,1")
        core_form.addRow("设备:", self._device_edit)

        # ── 操作按钮 ──
        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("开始训练")
        self._run_btn.setMinimumHeight(36)
        self._run_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._run_btn)

        self._stop_btn = QPushButton("停止")
        self._stop_btn.setMinimumHeight(36)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._stop_btn)

        btn_row.addStretch()

        # ── 进度 ──
        self._progress = ProgressPanel()

        # ── 实时指标 ──
        metrics_group = QGroupBox("训练指标")
        metrics_layout = QHBoxLayout(metrics_group)

        self._label_epoch = QLabel("Epoch: —")
        self._label_epoch.setStyleSheet("font-size: 14px; font-weight: bold; color: #4ec9b0;")
        metrics_layout.addWidget(self._label_epoch)

        self._label_box = QLabel("Box: —")
        self._label_box.setStyleSheet("color: #ce9178;")
        metrics_layout.addWidget(self._label_box)

        self._label_cls = QLabel("Cls: —")
        self._label_cls.setStyleSheet("color: #dcdcaa;")
        metrics_layout.addWidget(self._label_cls)

        self._label_dfl = QLabel("DFL: —")
        self._label_dfl.setStyleSheet("color: #c586c0;")
        metrics_layout.addWidget(self._label_dfl)

        self._label_map = QLabel("mAP: —")
        self._label_map.setStyleSheet("color: #569cd6;")
        metrics_layout.addWidget(self._label_map)

        self._label_time = QLabel("耗时: —")
        self._label_time.setStyleSheet("color: #888;")
        metrics_layout.addWidget(self._label_time)

        metrics_layout.addStretch()

        # ── 组装 ──
        layout.addWidget(core_group)
        layout.addLayout(btn_row)
        layout.addWidget(self._progress)
        layout.addWidget(metrics_group)
        layout.addStretch()

        self._refresh()

    def _refresh(self) -> None:
        models = _scan_models()
        current = self._model_combo.currentText()
        self._model_combo.clear()
        self._model_combo.addItems(models)
        if current:
            idx = self._model_combo.findText(current)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)

        datasets = _scan_datasets()
        cur_ds = self._dataset_combo.currentText()
        self._dataset_combo.clear()
        self._dataset_combo.addItems(datasets)
        if cur_ds:
            idx = self._dataset_combo.findText(cur_ds)
            if idx >= 0:
                self._dataset_combo.setCurrentIndex(idx)

    def _on_start(self) -> None:
        if self._worker and self._worker.isRunning():
            return

        dataset = self._dataset_combo.currentText().strip()
        model = self._model_combo.currentText().strip()
        if not dataset:
            QMessageBox.warning(self, "缺少参数", "请先选择数据集 (需先在数据流水线中处理)")
            return
        if not model:
            QMessageBox.warning(self, "缺少参数", "请选择模型")
            return

        device_text = self._device_edit.text().strip()
        device = device_text if device_text else None

        self._set_running(True)
        self._reset_metrics()

        self._worker = TrainingWorker(
            dataset=dataset,
            model=model,
            epochs=self._epochs_spin.value(),
            imgsz=self._imgsz_spin.value(),
            batch=self._batch_spin.value(),
            device=device,
            parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.metrics_update.connect(self._on_metrics)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_stop(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.terminate()
            self._worker.wait(3000)
            self._set_running(False)
            self._progress.set_status("已停止")

    def _set_running(self, running: bool) -> None:
        self._run_btn.setEnabled(not running)
        self._run_btn.setText("训练中..." if running else "开始训练")
        self._stop_btn.setEnabled(running)
        self._model_combo.setEnabled(not running)
        self._dataset_combo.setEnabled(not running)
        self._epochs_spin.setEnabled(not running)
        self._imgsz_spin.setEnabled(not running)
        self._batch_spin.setEnabled(not running)
        self._device_edit.setEnabled(not running)

    def _reset_metrics(self) -> None:
        self._label_epoch.setText("Epoch: —")
        self._label_box.setText("Box: —")
        self._label_cls.setText("Cls: —")
        self._label_dfl.setText("DFL: —")
        self._label_map.setText("mAP: —")
        self._label_time.setText("耗时: —")

    def _on_progress(self, percent: int, status: str) -> None:
        self._progress.set_progress(percent, status)

    def _on_metrics(self, metrics: dict) -> None:
        epoch = metrics.get("epoch", "")
        if epoch:
            self._label_epoch.setText(f"Epoch: {epoch}")
        if "box_loss" in metrics:
            self._label_box.setText(f"Box: {metrics['box_loss']:.4f}")
        if "cls_loss" in metrics:
            self._label_cls.setText(f"Cls: {metrics['cls_loss']:.4f}")
        if "dfl_loss" in metrics:
            self._label_dfl.setText(f"DFL: {metrics['dfl_loss']:.4f}")

    def _on_finished(self, result: object) -> None:
        self._set_running(False)
        if hasattr(result, "success") and result.success:
            self._progress.set_progress(100, f"训练完成 ({getattr(result, 'train_time', 0):.0f}s)")
            self._label_time.setText(f"耗时: {getattr(result, 'train_time', 0):.0f}s")
            QMessageBox.information(
                self, "训练完成",
                f"模型已保存到:\n{getattr(result, 'output_dir', '')}",
            )
        else:
            err = getattr(result, "error", "") if hasattr(result, "error") else "未知错误"
            self._progress.set_progress(0, f"训练失败: {err}")

    def _on_error(self, error_msg: str) -> None:
        self._set_running(False)
        self._progress.set_progress(0, f"错误: {error_msg}")
