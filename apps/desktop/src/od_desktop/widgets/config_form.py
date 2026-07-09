"""配置表单 —— 从 Pydantic BaseConfig 字段元数据自动生成表单控件."""
from __future__ import annotations

import types
from typing import Any, Callable, Optional, Union, get_args, get_origin

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)


def _is_optional(annotation) -> bool:
    """检查 annotation 是否为 Optional[X] (Union[X, None])."""
    origin = get_origin(annotation)
    if origin is types.UnionType:
        args = get_args(annotation)
        return type(None) in args and len(args) == 2
    return False


def _unwrap_optional(annotation):
    """从 Optional[X] 中提取 X."""
    args = get_args(annotation)
    return next(a for a in args if a is not type(None))


def _is_union(annotation) -> bool:
    """检查 annotation 是否为 Union 类型(非 Optional)."""
    origin = get_origin(annotation)
    if origin is types.UnionType:
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        return len(non_none) > 1
    return False


class ConfigForm(QScrollArea):
    """从 Pydantic 配置模型自动生成分组表单."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config: Any = None
        self._widgets: dict[str, tuple[QWidget, Callable[[], Any]]] = {}
        self._form_layout: Optional[QVBoxLayout] = None

        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; }")

        container = QWidget()
        self._form_layout = QVBoxLayout(container)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        self._form_layout.setSpacing(8)
        self.setWidget(container)

    def load_config(self, config: Any) -> None:
        """加载 Pydantic BaseConfig 实例并构建表单."""
        self._config = config
        self._widgets.clear()

        while self._form_layout.count():
            item = self._form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        groups = config.get_field_groups()
        for group_name, field_names in groups.items():
            group_box = QGroupBox(group_name)
            group_box.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #3c3c3c; border-radius: 4px;
                    margin-top: 8px; padding-top: 14px;
                    color: #cccccc; font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin; left: 8px;
                    padding: 0 4px; color: #4ec9b0;
                }
            """)
            form = QFormLayout(group_box)
            form.setLabelAlignment(Qt.AlignRight)
            form.setSpacing(4)

            for fname in field_names:
                meta = config.get_field_metadata(fname)
                label = QLabel(fname)
                label.setToolTip(meta.get("description", ""))
                label.setStyleSheet("color: #d4d4d4; font-weight: normal;")

                widget, getter = self._create_widget(fname, meta, config)
                self._widgets[fname] = (widget, getter)
                form.addRow(label, widget)

            self._form_layout.addWidget(group_box)

        self._form_layout.addStretch()

    def get_values(self) -> dict[str, Any]:
        return {name: getter() for name, (_, getter) in self._widgets.items()}

    def set_values(self, values: dict[str, Any]) -> None:
        for name, val in values.items():
            if name not in self._widgets:
                continue
            widget, _ = self._widgets[name]
            self._set_widget_value(widget, val)

    def _create_widget(
        self, fname: str, meta: dict, config: Any
    ) -> tuple[QWidget, Callable[[], Any]]:
        field_info = config.__class__.model_fields.get(fname)
        if field_info is None:
            return QLabel("—"), lambda: None

        annotation = field_info.annotation
        default = meta.get("default")

        # Optional[X]
        if _is_optional(annotation):
            inner_type = _unwrap_optional(annotation)
            return self._create_optional_widget(fname, inner_type, meta, default)

        # Union (multi-type, non-Optional)
        if _is_union(annotation):
            return self._create_union_widget(fname, get_args(annotation), meta, default)

        return self._create_typed_widget(fname, annotation, meta, default)

    def _create_optional_widget(
        self, fname: str, inner_type, meta: dict, default
    ) -> tuple[QWidget, Callable[[], Any]]:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        enable_cb = QCheckBox("启用")
        enable_cb.setChecked(default is not None)
        enable_cb.setStyleSheet("color: #888; font-weight: normal;")

        inner, inner_getter = self._create_typed_widget(
            fname, inner_type, meta, default if default is not None else None,
        )
        inner.setEnabled(default is not None)
        enable_cb.toggled.connect(inner.setEnabled)

        layout.addWidget(enable_cb)
        layout.addWidget(inner)

        def getter():
            if not enable_cb.isChecked():
                return None
            return inner_getter()

        return container, getter

    def _create_union_widget(
        self, fname: str, args: tuple, meta: dict, default
    ) -> tuple[QWidget, Callable[[], Any]]:
        non_none = [a for a in args if a is not type(None)]

        # Union[int, float] → QDoubleSpinBox
        if {int, float}.issuperset(set(non_none)):
            dsb = QDoubleSpinBox()
            dsb.setRange(-9999.0, 9999.0)
            dsb.setDecimals(4)
            dsb.setValue(float(default) if default is not None else 0.0)
            return dsb, lambda d=dsb: int(d.value()) if d.value() == int(d.value()) else d.value()

        # Union[bool, str] → QComboBox
        if {bool, str}.issuperset(set(non_none)):
            combo = QComboBox()
            combo.addItems(["false", "true", "ram", "disk"])
            s = str(default).lower() if default is not None else "false"
            idx = combo.findText(s)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            def combo_getter(cb=combo):
                t = cb.currentText()
                return t == "true" if t in ("true", "false") else t
            return combo, combo_getter

        # Fallback
        le = QLineEdit()
        le.setText(str(default) if default is not None else "")
        return le, le.text

    def _create_typed_widget(
        self, fname: str, annotation, meta: dict, default
    ) -> tuple[QWidget, Callable[[], Any]]:
        origin = get_origin(annotation)

        if annotation is bool:
            cb = QCheckBox()
            cb.setChecked(bool(default) if default is not None else False)
            cb.setStyleSheet("color: #d4d4d4; font-weight: normal;")
            return cb, cb.isChecked

        if annotation is int:
            field_info = self._config.__class__.model_fields.get(fname)
            ge = getattr(field_info, "ge", None) if field_info else None
            le = getattr(field_info, "le", None) if field_info else None
            sb = QSpinBox()
            sb.setRange(
                ge if ge is not None else -999999,
                le if le is not None else 999999,
            )
            sb.setValue(default if default is not None else 0)
            return sb, sb.value

        if annotation is float:
            field_info = self._config.__class__.model_fields.get(fname)
            ge = getattr(field_info, "ge", None) if field_info else None
            le = getattr(field_info, "le", None) if field_info else None
            dsb = QDoubleSpinBox()
            dsb.setRange(
                float(ge) if ge is not None else -9999.0,
                float(le) if le is not None else 9999.0,
            )
            dsb.setSingleStep(0.01)
            dsb.setDecimals(4)
            dsb.setValue(float(default) if default is not None else 0.0)
            return dsb, dsb.value

        if annotation is str:
            le = QLineEdit()
            le.setText(str(default) if default is not None else "")
            if default is not None:
                le.setPlaceholderText(f"(默认: {default})")
            return le, le.text

        if origin is list:
            le = QLineEdit()
            if isinstance(default, (list, tuple)):
                le.setText(", ".join(str(x) for x in default))
            elif default is not None:
                le.setText(str(default))
            le.setPlaceholderText("逗号分隔")
            return le, lambda le=le: [x.strip() for x in le.text().split(",") if x.strip()]

        # Fallback
        le = QLineEdit()
        le.setText(str(default) if default is not None else "")
        return le, le.text

    def _set_widget_value(self, widget: QWidget, val: Any) -> None:
        if val is None:
            return
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(val))
        elif isinstance(widget, QSpinBox):
            widget.setValue(int(val))
        elif isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(val))
        elif isinstance(widget, QLineEdit):
            if isinstance(val, (list, tuple)):
                widget.setText(", ".join(str(x) for x in val))
            else:
                widget.setText(str(val))
        elif isinstance(widget, QComboBox):
            s = str(val).lower()
            idx = widget.findText(s)
            if idx >= 0:
                widget.setCurrentIndex(idx)
        elif isinstance(widget, QWidget):
            for child in widget.findChildren(QCheckBox):
                child.setChecked(True)
            for child in widget.findChildren((QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox)):
                self._set_widget_value(child, val)
