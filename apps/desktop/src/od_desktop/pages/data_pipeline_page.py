"""数据流水线页面 —— 数据集格式转换 + 划分."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QVBoxLayout, QWidget, QFormLayout, QTextEdit,
)

from od_platform.common.constants import (
    AnnotationFormat, Task, SplitMode, SplitStrategy, DEFAULT_RANDOM_STATE,
    DEFAULT_SPLIT_STRATEGY, DEFAULT_SPLIT_MODE,
)
from od_platform.common.paths import RAW_DATA_DIR
from od_platform.data_pipeline.convert.registry import available_formats
from od_platform.data_pipeline.split.strategy_registry import list_strategies

from ..workers.pipeline_worker import PipelineWorker
from ..widgets.progress_panel import ProgressPanel

logger = logging.getLogger(__name__)


def _scan_datasets() -> list[str]:
    """扫描 data/raw/ 下的数据集目录."""
    if not RAW_DATA_DIR.exists():
        return []
    return sorted(
        d.name for d in RAW_DATA_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )


class DataPipelinePage(QWidget):
    """数据流水线 Tab: 选择数据集 → 配置 → 运行."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._worker: Optional[PipelineWorker] = None
        self._datasets: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── 数据源配置 ──
        src_group = QGroupBox("数据源")
        src_form = QFormLayout(src_group)
        src_form.setLabelAlignment(Qt.AlignRight)

        self._dataset_combo = QComboBox()
        self._dataset_combo.setMinimumWidth(300)
        self._dataset_combo.setEditable(True)
        self._dataset_combo.setInsertPolicy(QComboBox.NoInsert)
        self._dataset_combo.currentTextChanged.connect(self._on_dataset_changed)
        src_form.addRow("数据集:", self._dataset_combo)

        self._format_combo = QComboBox()
        self._format_combo.addItems(self._safe_list(available_formats))
        src_form.addRow("标注格式:", self._format_combo)

        self._task_combo = QComboBox()
        self._task_combo.addItems(list(Task.all()))
        src_form.addRow("任务类型:", self._task_combo)

        # ── 划分配置 ──
        split_group = QGroupBox("划分配置")
        split_form = QFormLayout(split_group)
        split_form.setLabelAlignment(Qt.AlignRight)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(list(SplitMode.all()))
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        split_form.addRow("划分模式:", self._mode_combo)

        self._strategy_combo = QComboBox()
        self._strategy_combo.addItems(self._safe_list(list_strategies))
        split_form.addRow("划分策略:", self._strategy_combo)

        self._train_rate = QDoubleSpinBox()
        self._train_rate.setRange(0.1, 0.98)
        self._train_rate.setValue(0.8)
        self._train_rate.setSingleStep(0.05)
        self._train_rate.valueChanged.connect(self._validate_rates)
        split_form.addRow("训练集比例:", self._train_rate)

        self._val_rate = QDoubleSpinBox()
        self._val_rate.setRange(0.01, 0.5)
        self._val_rate.setValue(0.1)
        self._val_rate.setSingleStep(0.05)
        self._val_rate.valueChanged.connect(self._validate_rates)
        split_form.addRow("验证集比例:", self._val_rate)

        self._test_rate_label = QLabel("0.10")
        split_form.addRow("测试集比例(自动):", self._test_rate_label)

        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(0, 99999)
        self._seed_spin.setValue(DEFAULT_RANDOM_STATE)
        split_form.addRow("随机种子:", self._seed_spin)

        # ── 类别过滤(可选) ──
        filter_group = QGroupBox("类别过滤 (可选)")
        filter_layout = QHBoxLayout(filter_group)
        self._classes_edit = QLineEdit()
        self._classes_edit.setPlaceholderText("留空 = 自动探测, 或输入类别名逗号分隔, 如: fire,smoke")
        filter_layout.addWidget(self._classes_edit)

        # ── 操作 ──
        self._run_btn = QPushButton("运行流水线")
        self._run_btn.setMinimumHeight(36)
        self._run_btn.clicked.connect(self._on_run)

        self._progress = ProgressPanel()

        # ── 结果 ──
        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setMaximumHeight(120)
        self._result_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e2a1e;
                color: #4ec9b0;
                border: 1px solid #3c6b3c;
                border-radius: 4px;
                font-family: "Consolas", monospace;
                font-size: 12px;
            }
        """)
        self._result_text.setVisible(False)

        # ── 组装 ──
        row1 = QHBoxLayout()
        row1.addWidget(src_group)
        row1.addWidget(split_group)

        layout.addLayout(row1)
        layout.addWidget(filter_group)
        layout.addWidget(self._run_btn)
        layout.addWidget(self._progress)
        layout.addWidget(self._result_text)
        layout.addStretch()

        self._refresh_datasets()
        self._validate_rates()

    def _safe_list(self, fn) -> list[str]:
        """安全获取列表(容错自动发现失败)."""
        try:
            result = fn()
            return list(result) if result else []
        except Exception:
            return []

    def _refresh_datasets(self) -> None:
        self._datasets = _scan_datasets()
        self._dataset_combo.clear()
        if self._datasets:
            self._dataset_combo.addItems(self._datasets)
            self._dataset_combo.setCurrentIndex(0)
        else:
            self._dataset_combo.setEditText("")

    def _on_dataset_changed(self, _text: str) -> None:
        # 可用来自动探测格式
        pass

    def _on_mode_changed(self, mode: str) -> None:
        preserve = mode == SplitMode.PRESERVE
        self._strategy_combo.setEnabled(not preserve)
        self._train_rate.setEnabled(not preserve)
        self._val_rate.setEnabled(not preserve)
        self._seed_spin.setEnabled(not preserve)
        if preserve:
            self._test_rate_label.setText("N/A")
        else:
            self._validate_rates()

    def _validate_rates(self) -> None:
        train = self._train_rate.value()
        val = self._val_rate.value()
        test = round(1.0 - train - val, 4)
        self._test_rate_label.setText(f"{test:.2f}")
        if test < -0.01:
            self._test_rate_label.setStyleSheet("color: #ff6666;")
            self._run_btn.setEnabled(False)
        else:
            self._test_rate_label.setStyleSheet("color: #d4d4d4;")
            self._run_btn.setEnabled(True)

    def _on_run(self) -> None:
        if self._worker and self._worker.isRunning():
            return

        dataset = self._dataset_combo.currentText().strip()
        if not dataset:
            QMessageBox.warning(self, "缺少参数", "请选择数据集")
            return

        annotation_format = self._format_combo.currentText()
        task = self._task_combo.currentText()
        split_mode = self._mode_combo.currentText()
        split_strategy = self._strategy_combo.currentText()
        train_rate = self._train_rate.value()
        val_rate = self._val_rate.value()
        seed = self._seed_spin.value()

        classes_raw = self._classes_edit.text().strip()
        classes = [c.strip() for c in classes_raw.split(",") if c.strip()] if classes_raw else None

        self._set_running(True)
        self._result_text.setVisible(False)

        self._worker = PipelineWorker(
            dataset=dataset,
            annotation_format=annotation_format,
            task=task,
            train_rate=train_rate,
            val_rate=val_rate,
            random_state=seed,
            split_strategy=split_strategy,
            split_mode=split_mode,
            classes=classes,
            parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _set_running(self, running: bool) -> None:
        self._run_btn.setEnabled(not running)
        self._run_btn.setText("运行中..." if running else "运行流水线")
        self._dataset_combo.setEnabled(not running)
        self._format_combo.setEnabled(not running)
        self._task_combo.setEnabled(not running)
        self._mode_combo.setEnabled(not running)
        self._strategy_combo.setEnabled(not running and self._mode_combo.currentText() != SplitMode.PRESERVE)
        self._train_rate.setEnabled(not running)
        self._val_rate.setEnabled(not running)
        self._seed_spin.setEnabled(not running)
        self._classes_edit.setEnabled(not running)

    def _on_progress(self, percent: int, status: str) -> None:
        self._progress.set_progress(percent, status)

    def _on_finished(self, result: object) -> None:
        self._set_running(False)
        self._progress.set_progress(100, "完成")
        if isinstance(result, dict):
            counts = result.get("counts", {})
            yaml_path = result.get("yaml", "")
            lines = ["流水线执行成功!", ""]
            lines.append(f"配置文件: {yaml_path}")
            lines.append("")
            for split_name in ("train", "val", "test"):
                c = counts.get(split_name, 0)
                lines.append(f"  {split_name}: {c} 对 (图+标)")
            self._result_text.setText("\n".join(lines))
            self._result_text.setVisible(True)

    def _on_error(self, error_msg: str) -> None:
        self._set_running(False)
        self._progress.set_progress(0, f"错误: {error_msg}")
        self._result_text.setText(f"执行失败:\n{error_msg}")
        self._result_text.setStyleSheet("""
            QTextEdit {
                background-color: #2a1e1e;
                color: #ff6666;
                border: 1px solid #6b3c3c;
                border-radius: 4px;
                font-family: "Consolas", monospace;
                font-size: 12px;
            }
        """)
        self._result_text.setVisible(True)
