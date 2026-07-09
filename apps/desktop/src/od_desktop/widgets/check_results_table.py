"""质检结果表格 —— QTableWidget + 严重级别颜色编码."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QHeaderView, QTableWidget, QTableWidgetItem,
)


SEVERITY_COLORS = {
    "PASS":    QColor(60, 120, 60),
    "INFO":    QColor(80, 80, 200),
    "WARNING": QColor(200, 160, 40),
    "ERROR":   QColor(220, 60, 60),
}

SEVERITY_BG = {
    "PASS":    QColor(30, 50, 30),
    "INFO":    QColor(25, 25, 60),
    "WARNING": QColor(60, 45, 15),
    "ERROR":   QColor(60, 20, 20),
}


class CheckResultsTable(QTableWidget):
    """显示质检结果: 检查项 | 级别 | 摘要."""

    check_selected = Signal(dict)  # 选中 CheckResult 的 details

    COL_NAME = 0
    COL_SEVERITY = 1
    COL_SUMMARY = 2

    def __init__(self, parent: Optional[object] = None) -> None:
        super().__init__(parent)
        self._results: list = []

        self.setColumnCount(3)
        self.setHorizontalHeaderLabels(["检查项", "级别", "摘要"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)

        self.setStyleSheet("""
            QTableWidget {
                background-color: #2d2d2d;
                alternate-background-color: #333333;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                gridline-color: #3c3c3c;
            }
            QTableWidget::item { padding: 4px 8px; }
            QTableWidget::item:selected {
                background-color: #094771;
                color: white;
            }
            QHeaderView::section {
                background-color: #383838;
                color: #cccccc;
                padding: 4px 8px;
                border: none;
                border-bottom: 1px solid #3c3c3c;
                font-weight: bold;
            }
        """)

        self.itemClicked.connect(self._on_item_clicked)

    def load_results(self, results: list) -> None:
        """加载 CheckResult 列表."""
        self._results = list(results)
        self.setRowCount(len(results))

        for i, r in enumerate(results):
            # 名称
            name_item = QTableWidgetItem(r.name)
            self.setItem(i, self.COL_NAME, name_item)

            # 严重级别
            sev_item = QTableWidgetItem(r.severity)
            sev_color = SEVERITY_COLORS.get(r.severity, QColor(200, 200, 200))
            sev_bg = SEVERITY_BG.get(r.severity, QColor(40, 40, 40))
            sev_item.setForeground(QBrush(sev_color))
            sev_item.setBackground(QBrush(sev_bg))
            self.setItem(i, self.COL_SEVERITY, sev_item)

            # 摘要
            summary_item = QTableWidgetItem(r.summary)
            self.setItem(i, self.COL_SUMMARY, summary_item)

        self.resizeRowsToContents()

    def _on_item_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if 0 <= row < len(self._results):
            r = self._results[row]
            self.check_selected.emit(
                {"name": r.name, "severity": r.severity, "summary": r.summary, "details": r.details}
            )
