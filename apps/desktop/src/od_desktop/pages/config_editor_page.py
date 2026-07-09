"""配置编辑器页面 —— Form + YAML 双模式, 双向同步."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from od_platform.runtime_config.registry import CONFIG_REGISTRY
from od_platform.runtime_config.generator import ConfigGenerator
from od_platform.common.paths import runtime_config_path as _runtime_config_path
from od_platform.common.paths import CONFIGS_DIR

from ..widgets.config_form import ConfigForm
from ..widgets.yaml_editor import YamlEditor

logger = logging.getLogger(__name__)

RUNTIME_CONFIGS_DIR = CONFIGS_DIR / "runtime"


def _scan_config_files() -> list[str]:
    """扫描 configs/runtime/*.yaml."""
    if not RUNTIME_CONFIGS_DIR.exists():
        return []
    return sorted(p.name for p in RUNTIME_CONFIGS_DIR.glob("*.yaml") if p.is_file())


class ConfigEditorPage(QWidget):
    """配置编辑器 Tab: 选择配置类型 → 编辑 → 保存."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config_class: Optional[type] = None
        self._config: object = None
        self._current_file: Optional[str] = None
        self._generator = ConfigGenerator()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 顶部控制栏 ──
        control_row = QHBoxLayout()

        control_row.addWidget(QLabel("配置类型:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(list(CONFIG_REGISTRY))
        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        control_row.addWidget(self._type_combo)

        control_row.addWidget(QLabel("文件:"))
        self._file_combo = QComboBox()
        self._file_combo.setEditable(True)
        self._file_combo.setMinimumWidth(200)
        self._file_combo.setInsertPolicy(QComboBox.NoInsert)
        self._file_combo.currentTextChanged.connect(self._on_file_changed)
        control_row.addWidget(self._file_combo)

        self._new_btn = QPushButton("生成默认")
        self._new_btn.clicked.connect(self._on_generate_default)
        control_row.addWidget(self._new_btn)

        control_row.addStretch()

        self._save_btn = QPushButton("保存")
        self._save_btn.clicked.connect(self._on_save)
        control_row.addWidget(self._save_btn)

        self._reload_btn = QPushButton("重新加载")
        self._reload_btn.clicked.connect(self._on_reload)
        control_row.addWidget(self._reload_btn)

        # ── 双模式编辑器 ──
        self._editor_tabs = QTabWidget()
        self._editor_tabs.setDocumentMode(True)

        self._form = ConfigForm()
        self._yaml_editor = YamlEditor()

        self._editor_tabs.addTab(self._form, "表单")
        self._editor_tabs.addTab(self._yaml_editor, "YAML")
        self._editor_tabs.currentChanged.connect(self._on_editor_tab_changed)

        layout.addLayout(control_row)
        layout.addWidget(self._editor_tabs, 1)

        self._refresh_files()
        self._on_type_changed(self._type_combo.currentText())

    # ── 数据源 ──────────────────────────────────────────

    def _refresh_files(self) -> None:
        self._file_combo.clear()
        files = _scan_config_files()
        if files:
            self._file_combo.addItems(files)
            self._file_combo.setCurrentIndex(0)

    def _on_type_changed(self, config_type: str) -> None:
        if config_type not in CONFIG_REGISTRY:
            return
        cls, _ = CONFIG_REGISTRY[config_type]
        self._config_class = cls
        # 尝试加载对应的默认文件
        default_name = f"{config_type}.yaml"
        idx = self._file_combo.findText(default_name)
        if idx >= 0:
            self._file_combo.setCurrentIndex(idx)
        self._load_current()

    def _on_file_changed(self, filename: str) -> None:
        if not filename:
            return
        self._load_file(filename)

    def _load_current(self) -> None:
        filename = self._file_combo.currentText().strip()
        if filename:
            self._load_file(filename)
        else:
            self._load_defaults()

    def _load_defaults(self) -> None:
        if self._config_class is None:
            return
        try:
            self._config = self._config_class()
        except Exception:
            self._config = self._config_class.model_construct()
        self._form.load_config(self._config)
        self._sync_form_to_yaml()

    def _load_file(self, filename: str) -> None:
        if self._config_class is None:
            return
        filepath = RUNTIME_CONFIGS_DIR / filename
        if not filepath.exists():
            self._load_defaults()
            return

        try:
            raw = yaml.safe_load(filepath.read_text(encoding="utf-8")) or {}
            self._config = self._config_class(**raw)
            self._current_file = filename
            self._form.load_config(self._config)
            # 显示原始 YAML 文本
            self._yaml_editor.set_yaml_text(filepath.read_text(encoding="utf-8"))
            logger.info("已加载配置: %s", filename)
        except Exception as e:
            logger.warning("加载配置失败: %s", e)
            self._load_defaults()

    # ── 操作 ──────────────────────────────────────────

    def _on_generate_default(self) -> None:
        if self._config_class is None:
            return
        self._load_defaults()
        # 也更新 YAML 编辑器为生成的默认内容
        try:
            yaml_text = self._generator._generate_yaml(
                self._config_class,
                CONFIG_REGISTRY[self._type_combo.currentText()][1],
            )
            self._yaml_editor.set_yaml_text(yaml_text)
        except Exception:
            pass
        logger.info("已加载默认配置")

    def _on_save(self) -> None:
        config_type = self._type_combo.currentText()
        filename = self._file_combo.currentText().strip()
        if not filename:
            filename = f"{config_type}.yaml"
        if not filename.endswith(".yaml"):
            filename += ".yaml"

        # 先从 YAML 同步到表单(确保保存的是最新编辑)
        if self._editor_tabs.currentIndex() == 1:  # YAML tab
            self._sync_yaml_to_form()

        filepath = RUNTIME_CONFIGS_DIR / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)

        try:
            yaml_text = self._yaml_editor.get_yaml_text()
            if not yaml_text.strip():
                yaml_text = self._build_yaml_from_form()
            filepath.write_text(yaml_text, encoding="utf-8")
            self._current_file = filename
            logger.info("配置已保存: %s", filepath)

            # 刷新文件列表
            self._refresh_files()
            idx = self._file_combo.findText(filename)
            if idx >= 0:
                self._file_combo.setCurrentIndex(idx)

            QMessageBox.information(self, "已保存", f"配置已保存到:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _on_reload(self) -> None:
        self._load_current()
        logger.info("已重新加载")

    # ── 双向同步 ──────────────────────────────────────

    def _on_editor_tab_changed(self, index: int) -> None:
        if index == 1:  # 切换到 YAML tab
            self._sync_form_to_yaml()
        else:           # 切换到 Form tab
            self._sync_yaml_to_form()

    def _sync_form_to_yaml(self) -> None:
        """表单 → YAML: 用当前表单值生成 YAML 文本."""
        if self._config is None:
            return
        yaml_text = self._build_yaml_from_form()
        self._yaml_editor.set_yaml_text(yaml_text)

    def _sync_yaml_to_form(self) -> None:
        """YAML → 表单: 解析 YAML 并更新表单字段."""
        if self._config_class is None:
            return
        try:
            raw = yaml.safe_load(self._yaml_editor.get_yaml_text()) or {}
            if not isinstance(raw, dict):
                return
            self._config = self._config_class(**raw)
            self._form.load_config(self._config)
        except Exception as e:
            logger.debug("YAML 解析失败(表单未更新): %s", e)

    def _build_yaml_from_form(self) -> str:
        """从当前表单值构建 YAML 文本."""
        if self._config is None:
            return ""
        values = self._form.get_values()

        lines: list[str] = []
        config_type = self._type_combo.currentText()
        title = CONFIG_REGISTRY.get(config_type, (None, self._config.__class__.__name__))[1]
        lines.append(f"# {title}")
        lines.append("")

        groups = self._config.get_field_groups()
        for group_name, field_names in groups.items():
            lines.append(f"# ── {group_name} ──")
            for fname in field_names:
                if fname not in values:
                    continue
                meta = self._config.get_field_metadata(fname)
                desc = meta.get("yaml_comment", meta.get("description", ""))
                lines.append(f"# {desc}")
                val = values[fname]
                lines.append(f"{fname}: {self._format_yaml_value(val)}")
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_yaml_value(value) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return value if value else '""'
        if isinstance(value, (list, tuple)):
            if not value:
                return "[]"
            return f"[{', '.join(str(v) for v in value)}]"
        return str(value)
