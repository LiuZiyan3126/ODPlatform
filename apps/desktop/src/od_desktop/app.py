"""ODPlatform Desktop 入口."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> None:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("ODPlatform Desktop")
    app.setOrganizationName("ODPlatform")

    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    app.setStyleSheet("""
        QMainWindow { background-color: #252526; }
        QGroupBox {
            border: 1px solid #3c3c3c;
            border-radius: 6px;
            margin-top: 10px;
            padding-top: 16px;
            color: #cccccc;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
            color: #4ec9b0;
        }
        QTreeWidget {
            background-color: #2d2d2d;
            alternate-background-color: #333333;
            color: #d4d4d4;
            border: 1px solid #3c3c3c;
            border-radius: 4px;
        }
        QTreeWidget::item { padding: 3px 0; }
        QHeaderView::section {
            background-color: #383838;
            color: #cccccc;
            padding: 4px;
            border: none;
            border-bottom: 1px solid #3c3c3c;
        }
        QPushButton {
            background-color: #0e639c;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 6px 16px;
            font-weight: bold;
        }
        QPushButton:hover { background-color: #1177bb; }
        QPushButton:pressed { background-color: #094771; }
        QPushButton:disabled { background-color: #555555; color: #888888; }
        QComboBox {
            background-color: #3c3c3c;
            color: #d4d4d4;
            border: 1px solid #555;
            border-radius: 4px;
            padding: 4px 8px;
        }
        QSpinBox, QDoubleSpinBox, QLineEdit {
            background-color: #3c3c3c;
            color: #d4d4d4;
            border: 1px solid #555;
            border-radius: 4px;
            padding: 4px 8px;
        }
        QStatusBar { background-color: #007acc; color: white; }
        QStatusBar QLabel { color: white; }
        QMenuBar { background-color: #3c3c3c; color: #d4d4d4; }
        QMenuBar::item:selected { background-color: #094771; }
        QMenu { background-color: #3c3c3c; color: #d4d4d4; }
        QMenu::item:selected { background-color: #094771; }
    """)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
