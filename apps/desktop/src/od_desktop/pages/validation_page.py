"""数据质检页面 —— 运行质量检查 + 结构化结果展示."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSplitter, QTextEdit,
    QVBoxLayout, QWidget,
)

from PySide6.QtGui import QColor

from od_platform.common.constants import Task
from od_platform.common.paths import DATASET_CONFIGS_DIR

from ..workers.validation_worker import ValidationWorker
from ..widgets.check_results_table import CheckResultsTable, SEVERITY_COLORS
from ..widgets.progress_panel import ProgressPanel

logger = logging.getLogger(__name__)


def _scan_dataset_yamls() -> list[str]:
    """扫描 configs/datasets/*.yaml 获取已处理的数据集名."""
    if not DATASET_CONFIGS_DIR.exists():
        return []
    return sorted(
        p.stem for p in DATASET_CONFIGS_DIR.glob("*.yaml")
        if p.is_file()
    )


class ValidationPage(QWidget):
    """数据质检 Tab."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._worker: Optional[ValidationWorker] = None
        self._report: object = None  # ValidationReport
        self._datasets: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── 顶部控制栏 ──
        control_group = QGroupBox("验证配置")
        control_row = QHBoxLayout(control_group)

        control_row.addWidget(QLabel("数据集:"))
        self._dataset_combo = QComboBox()
        self._dataset_combo.setMinimumWidth(200)
        control_row.addWidget(self._dataset_combo)

        control_row.addWidget(QLabel("任务:"))
        self._task_combo = QComboBox()
        self._task_combo.addItems(["auto"] + list(Task.all()))
        control_row.addWidget(self._task_combo)

        self._write_report_cb = QCheckBox("写 JSON 报告")
        self._write_report_cb.setChecked(True)
        control_row.addWidget(self._write_report_cb)

        control_row.addStretch()

        self._run_btn = QPushButton("运行质检")
        self._run_btn.setMinimumHeight(32)
        self._run_btn.clicked.connect(self._on_run)
        control_row.addWidget(self._run_btn)

        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.setMinimumHeight(32)
        self._refresh_btn.clicked.connect(self._refresh_datasets)
        control_row.addWidget(self._refresh_btn)

        self._progress = ProgressPanel()

        # ── 严重级别汇总 ──
        self._summary_bar = QHBoxLayout()
        self._severity_labels: dict[str, QLabel] = {}
        for sev in ("PASS", "INFO", "WARNING", "ERROR"):
            lbl = QLabel(f"{sev}: —")
            color = SEVERITY_COLORS.get(sev, QColor(200, 200, 200))
            lbl.setStyleSheet(
                f"color: {color.name()}; padding: 4px 12px; "
                f"font-weight: bold; font-size: 13px;"
            )
            self._severity_labels[sev] = lbl
            self._summary_bar.addWidget(lbl)
        self._summary_bar.addStretch()

        # ── 结果表格 + 详情面板 (QSplitter) ──
        splitter = QSplitter(Qt.Vertical)

        self._table = CheckResultsTable()
        self._table.check_selected.connect(self._on_check_selected)

        detail_group = QGroupBox("详情")
        detail_layout = QVBoxLayout(detail_group)
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                font-family: "Consolas", monospace;
                font-size: 12px;
            }
        """)
        detail_layout.addWidget(self._detail_text)

        splitter.addWidget(self._table)
        splitter.addWidget(detail_group)
        splitter.setSizes([350, 150])

        # ── 组装 ──
        layout.addWidget(control_group)
        layout.addWidget(self._progress)
        layout.addLayout(self._summary_bar)
        layout.addWidget(splitter, 1)

        self._refresh_datasets()

    def _refresh_datasets(self) -> None:
        self._datasets = _scan_dataset_yamls()
        self._dataset_combo.clear()
        if self._datasets:
            self._dataset_combo.addItems(self._datasets)
        else:
            self._dataset_combo.setEditText("(无数据集, 请先运行数据流水线)")

    def _on_run(self) -> None:
        if self._worker and self._worker.isRunning():
            return

        dataset = self._dataset_combo.currentText().strip()
        if not dataset or dataset.startswith("("):
            QMessageBox.warning(self, "缺少参数", "请先选择已处理的数据集")
            return

        task_text = self._task_combo.currentText()
        task_type = None if task_text == "auto" else task_text

        yaml_path = DATASET_CONFIGS_DIR / f"{dataset}.yaml"
        if not yaml_path.exists():
            QMessageBox.warning(self, "配置文件不存在", str(yaml_path))
            return

        self._set_running(True)
        self._table.setRowCount(0)
        self._detail_text.clear()
        for lbl in self._severity_labels.values():
            lbl.setText(lbl.text().split(":")[0] + ": —")

        self._worker = ValidationWorker(
            yaml_path=yaml_path,
            task_type=task_type,
            write_report=self._write_report_cb.isChecked(),
            parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _set_running(self, running: bool) -> None:
        self._run_btn.setEnabled(not running)
        self._run_btn.setText("运行中..." if running else "运行质检")
        self._dataset_combo.setEnabled(not running)
        self._task_combo.setEnabled(not running)
        self._refresh_btn.setEnabled(not running)

    def _on_progress(self, percent: int, status: str) -> None:
        self._progress.set_progress(percent, status)

    def _on_finished(self, report: object) -> None:
        self._set_running(False)
        self._report = report
        self._progress.set_progress(100, f"完成: {len(report.results)} 项检查")

        # 加载结果表格
        self._table.load_results(report.results)

        # 更新严重级别汇总
        counts = report.counts_by_severity
        for sev, lbl in self._severity_labels.items():
            count = counts.get(sev, 0)
            lbl.setText(f"{sev}: {count}")

        # 日志
        logger.info(
            "质检完成 — %s, 耗时 %.1fs",
            report.overall_severity, report.duration_seconds,
        )

    def _on_error(self, error_msg: str) -> None:
        self._set_running(False)
        self._progress.set_progress(0, f"错误: {error_msg}")
        QMessageBox.critical(self, "质检失败", error_msg)

    def _on_check_selected(self, data: dict) -> None:
        """显示选中检查项的详情."""
        details = data.get("details", {})
        lines = [
            f"检查项: {data['name']}",
            f"严重级别: {data['severity']}",
            f"摘要: {data['summary']}",
            "",
            "结构化详情:",
            json.dumps(details, indent=2, ensure_ascii=False, default=str),
        ]
        self._detail_text.setText("\n".join(lines))
