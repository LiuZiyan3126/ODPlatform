"""项目页面 —— 系统信息 / 项目初始化 / 项目重置."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from od_platform.common.paths import ROOT_DIR, RAW_DATA_DIR, DATA_DIR, MODELS_DIR, RUNS_DIR
from od_platform.common.system_utils import get_basic_device_info

logger = logging.getLogger(__name__)


def _get_workspace_info() -> dict:
    """扫描工作区状态."""
    info = {
        "项目根目录": str(ROOT_DIR),
        "raw 数据集": f"{_count_dirs(RAW_DATA_DIR)} 个数据集",
        "processed 数据集": f"{_count_dirs(DATA_DIR / 'processed')} 个数据集",
        "模型文件": f"{_count_files(MODELS_DIR)}",
        "运行记录": f"{_count_dirs(RUNS_DIR)} 个",
    }
    return info


def _count_dirs(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(1 for x in p.iterdir() if x.is_dir())


def _count_files(p: Path) -> int:
    if not p.exists():
        return 0
    count = 0
    for x in p.iterdir():
        if x.is_file():
            count += 1
        elif x.is_dir():
            count += sum(1 for _ in x.rglob("*") if _.is_file())
    return count


class _InitWorker(QThread):
    """后台线程执行 initialize_project."""

    finished_signal = Signal(bool, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        try:
            from od_platform.cli.init_project import initialize_project
            initialize_project()
            self.finished_signal.emit(True, "项目初始化完成")
        except SystemExit as e:
            ok = e.code == 0 or e.code is None
            self.finished_signal.emit(ok, f"初始化{'成功' if ok else '失败'} (exit {e.code})")
        except Exception as e:
            self.finished_signal.emit(False, f"初始化失败: {e}")


class _ResetWorker(QThread):
    """后台线程执行 reset_project (dry-run 或实际删除)."""

    finished_signal = Signal(int, str)

    def __init__(self, yes: bool = False, force: bool = True, dry_run: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._yes = yes
        self._force = force
        self._dry_run = dry_run

    def run(self) -> None:
        try:
            from od_platform.cli.reset_project import reset_project
            code = reset_project(yes=self._yes, force=self._force, dry_run=self._dry_run)
            if self._dry_run:
                self.finished_signal.emit(code, "Dry-run 完成，点击「执行重置」确认删除")
            else:
                self.finished_signal.emit(code, "重置完成" if code == 0 else "重置被取消或出错")
        except Exception as e:
            self.finished_signal.emit(1, f"重置异常: {e}")


class ProjectPage(QWidget):
    """项目 Tab: 系统信息 + 初始化/重置操作."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_worker: _InitWorker | None = None
        self._reset_worker: _ResetWorker | None = None
        self._dry_run_done = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── 系统信息 ──
        sys_group = QGroupBox("系统信息")
        self._sys_tree = QTreeWidget()
        self._sys_tree.setHeaderLabels(["项目", "值"])
        self._sys_tree.setColumnWidth(0, 180)
        self._sys_tree.setAlternatingRowColors(True)
        sys_layout = QVBoxLayout(sys_group)
        sys_layout.addWidget(self._sys_tree)

        # ── 工作区概览 ──
        ws_group = QGroupBox("工作区概览")
        self._ws_tree = QTreeWidget()
        self._ws_tree.setHeaderLabels(["项目", "状态"])
        self._ws_tree.setColumnWidth(0, 180)
        self._ws_tree.setAlternatingRowColors(True)
        ws_btn_row = QHBoxLayout()
        ws_btn_row.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.setFixedWidth(80)
        refresh_btn.clicked.connect(self._refresh_workspace)
        ws_btn_row.addWidget(refresh_btn)
        ws_layout = QVBoxLayout(ws_group)
        ws_layout.addWidget(self._ws_tree)
        ws_layout.addLayout(ws_btn_row)

        # ── 操作按钮 ──
        action_group = QGroupBox("操作")
        self._init_btn = QPushButton("初始化项目")
        self._init_btn.setMinimumHeight(36)
        self._init_btn.clicked.connect(self._on_init)

        self._reset_dry_btn = QPushButton("重置项目 (Dry-Run)")
        self._reset_dry_btn.setMinimumHeight(36)
        self._reset_dry_btn.clicked.connect(lambda: self._on_reset(dry_run=True))

        self._reset_btn = QPushButton("执行重置")
        self._reset_btn.setMinimumHeight(36)
        self._reset_btn.setEnabled(False)
        self._reset_btn.setStyleSheet("QPushButton { color: #ff6666; }")
        self._reset_btn.clicked.connect(lambda: self._on_reset(yes=True))

        self._action_status = QLabel("")
        self._action_status.setStyleSheet("color: #888;")

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._init_btn)
        btn_row.addWidget(self._reset_dry_btn)
        btn_row.addWidget(self._reset_btn)

        action_layout = QVBoxLayout(action_group)
        action_layout.addLayout(btn_row)
        action_layout.addWidget(self._action_status)

        layout.addWidget(sys_group)
        layout.addWidget(ws_group)
        layout.addWidget(action_group)
        layout.addStretch()

        self._refresh_system_info()
        self._refresh_workspace()

    def _refresh_system_info(self) -> None:
        self._sys_tree.clear()
        info = get_basic_device_info()
        for key, value in info.items():
            item = QTreeWidgetItem([key, str(value)])
            self._sys_tree.addTopLevelItem(item)

    def _refresh_workspace(self) -> None:
        self._ws_tree.clear()
        info = _get_workspace_info()
        for key, value in info.items():
            item = QTreeWidgetItem([key, str(value)])
            self._ws_tree.addTopLevelItem(item)

    def _on_init(self) -> None:
        if self._init_worker and self._init_worker.isRunning():
            return
        self._set_buttons_enabled(False)
        self._action_status.setText("正在初始化项目...")
        self._action_status.setStyleSheet("color: #4ec9b0;")
        self._init_worker = _InitWorker(self)
        self._init_worker.finished_signal.connect(self._on_init_done)
        self._init_worker.start()

    def _on_init_done(self, ok: bool, msg: str) -> None:
        self._set_buttons_enabled(True)
        color = "#4ec9b0" if ok else "#ff6666"
        self._action_status.setText(msg)
        self._action_status.setStyleSheet(f"color: {color};")
        self._refresh_workspace()

    def _on_reset(self, yes: bool = False, dry_run: bool = False) -> None:
        if not yes and not dry_run:
            return
        if self._reset_worker and self._reset_worker.isRunning():
            return

        if yes:
            reply = QMessageBox.warning(
                self, "确认重置",
                "确定要删除所有运行时产物吗？\n此操作不可撤销！",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self._action_status.setText("用户取消重置")
                return

        self._set_buttons_enabled(False)
        mode = "正在 dry-run..." if dry_run else "正在删除..."
        self._action_status.setText(mode)
        self._action_status.setStyleSheet("color: #4ec9b0;" if dry_run else "color: #ff6666;")
        self._reset_worker = _ResetWorker(yes=yes, force=True, dry_run=dry_run, parent=self)
        self._reset_worker.finished_signal.connect(self._on_reset_done)
        self._reset_worker.start()

    def _on_reset_done(self, code: int, msg: str) -> None:
        self._set_buttons_enabled(True)
        if "Dry-run" in msg:
            self._dry_run_done = True
            self._reset_btn.setEnabled(True)
        elif "重置完成" in msg:
            self._dry_run_done = False
            self._reset_btn.setEnabled(False)
        color = "#4ec9b0" if code == 0 else "#ff6666"
        self._action_status.setText(msg)
        self._action_status.setStyleSheet(f"color: {color};")
        self._refresh_workspace()

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._init_btn.setEnabled(enabled)
        self._reset_dry_btn.setEnabled(enabled)
        if not enabled or not self._dry_run_done:
            self._reset_btn.setEnabled(False)
        else:
            self._reset_btn.setEnabled(enabled)
