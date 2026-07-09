"""主窗口 —— QMainWindow + QTabWidget + 菜单 + 状态栏."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QLabel, QMainWindow, QMessageBox, QStatusBar, QTabWidget, QVBoxLayout, QWidget,
)

from od_platform.common.paths import ROOT_DIR
from od_platform.common.system_utils import get_basic_device_info

from .pages.project_page import ProjectPage
from .pages.data_pipeline_page import DataPipelinePage
from .pages.validation_page import ValidationPage
from .pages.training_page import TrainingPage
from .pages.inference_page import InferencePage
from .pages.config_editor_page import ConfigEditorPage
from .widgets.log_viewer import LogViewer

logger = logging.getLogger(__name__)

TAB_LABELS = [
    ("项目", "project"),
    ("数据流水线", "pipeline"),
    ("数据质检", "validation"),
    ("配置编辑器", "config"),
    ("模型训练", "training"),
    ("模型推理", "inference"),
]


class MainWindow(QMainWindow):
    """ODPlatform 桌面端主窗口."""

    def __init__(self) -> None:
        super().__init__()
        self._settings = QSettings("ODPlatform", "Desktop")
        self._setup_ui()
        self._setup_menu()
        self._setup_statusbar()
        self._restore_geometry()

        logger.info("ODPlatform Desktop 已启动")

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"ODPlatform Desktop — {ROOT_DIR}")

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #3c3c3c; }
            QTabBar::tab { padding: 8px 16px; min-width: 80px; }
        """)

        self._pages: dict[str, QWidget] = {
            "project": ProjectPage(),
            "pipeline": DataPipelinePage(),
            "validation": ValidationPage(),
            "config": ConfigEditorPage(),
            "training": TrainingPage(),
            "inference": InferencePage(),
        }

        for label, key in TAB_LABELS:
            page = self._pages[key]
            page_wrapper = QWidget()
            wrapper_layout = QVBoxLayout(page_wrapper)
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
            wrapper_layout.addWidget(page)
            self._tabs.addTab(page_wrapper, label)

        # 日志查看器（固定在底部）
        self._log_viewer = LogViewer()
        self._log_viewer.setMinimumHeight(120)
        self._log_viewer.setMaximumHeight(250)

        main_layout.addWidget(self._tabs)
        main_layout.addWidget(self._log_viewer)

        self.resize(1100, 750)

    def _setup_menu(self) -> None:
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")

        exit_action = QAction("退出(&Q)", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 视图菜单
        view_menu = menubar.addMenu("视图(&V)")

        for i, (label, _) in enumerate(TAB_LABELS):
            action = QAction(f"{label}(&{i + 1})", self)
            action.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            idx = i
            action.triggered.connect(lambda checked, n=idx: self._tabs.setCurrentIndex(n))
            view_menu.addAction(action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")
        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_statusbar(self) -> None:
        self._status = QStatusBar()
        self.setStatusBar(self._status)

        info = get_basic_device_info()
        gpu_name = info.get("GPU", "未知")
        python_ver = info.get("Python", "")

        self._ws_label = QLabel(f"工作区: {ROOT_DIR}")
        self._ws_label.setStyleSheet("color: #888; padding: 0 8px;")
        self._status.addWidget(self._ws_label)

        self._gpu_label = QLabel(f"GPU: {gpu_name}")
        self._gpu_label.setStyleSheet("color: #888; padding: 0 8px;")
        self._status.addWidget(self._gpu_label)

        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet("color: #4ec9b0; padding: 0 8px; font-weight: bold;")
        self._status.addPermanentWidget(self._status_label)

    def _show_about(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from ._version import __version__
        QMessageBox.about(
            self, "关于 ODPlatform Desktop",
            f"<h3>ODPlatform Desktop</h3>"
            f"<p>版本: {__version__}</p>"
            f"<p>基于 YOLO 的目标检测开发平台</p>"
            f"<p>技术栈: PySide6 (Qt 6) + PyTorch + Ultralytics</p>",
        )

    def _restore_geometry(self) -> None:
        geom = self._settings.value("window/geometry")
        if geom:
            self.restoreGeometry(geom)
        state = self._settings.value("window/state")
        if state:
            self.restoreState(state)
        last_tab = self._settings.value("window/last_tab", 0, type=int)
        if last_tab < self._tabs.count():
            self._tabs.setCurrentIndex(last_tab)

    def closeEvent(self, event) -> None:
        # 检查运行中的 worker
        running = self._find_running_workers()
        if running:
            reply = QMessageBox.question(
                self, "确认退出",
                f"有 {len(running)} 个后台任务正在运行:\n"
                + "\n".join(f"  • {n}" for n in running)
                + "\n\n确定要退出吗？未完成的任务将丢失。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            # 停止所有 worker
            for _page, worker_name in running:
                page = self._pages.get(worker_name)
                if page and hasattr(page, '_worker') and page._worker:
                    try:
                        page._worker.cancel()
                        page._worker.terminate()
                        page._worker.wait(2000)
                    except Exception:
                        pass

        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        self._settings.setValue("window/last_tab", self._tabs.currentIndex())
        super().closeEvent(event)

    def _find_running_workers(self) -> list[tuple[QWidget, str]]:
        """查找运行中的 worker. 返回 [(page, worker_name), ...]."""
        running = []
        for key in ("training", "inference", "pipeline"):
            page = self._pages.get(key)
            if page and hasattr(page, '_worker') and page._worker:
                if page._worker.isRunning():
                    running.append((page, key))
        return running
