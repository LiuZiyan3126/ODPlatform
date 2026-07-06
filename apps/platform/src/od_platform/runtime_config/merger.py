#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :merger.py.py
# @Time      :2026/7/3 14:44:57
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : merger.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统——三源合并 + 链表式溯源
"""配置合并器: 多源合并 + 链表式溯源 + 来源报告.

★ 缺口③(无溯源)在此填上.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import ValidationError

from od_platform.common.string_utils import pad_to_width


class ConfigSource(str, Enum):
    DEFAULT = "DEFAULT"
    YAML    = "YAML"
    CLI     = "CLI"


@dataclass
class ConfigMetadata:
    key:             str
    value:           Any
    source:          Union[ConfigSource, str]
    timestamp:       datetime
    overridden_from: Optional["ConfigMetadata"] = None

    @property
    def source_label(self) -> str:
        return self.source.value if isinstance(self.source, ConfigSource) else self.source

    def chain(self) -> List["ConfigMetadata"]:
        result, cur = [self], self.overridden_from
        while cur:
            result.append(cur); cur = cur.overridden_from
        return result

    def chain_str(self) -> str:
        return " ← ".join(f"{m.value}({m.source_label})" for m in self.chain())


def _center(text: str, width: int = 70) -> str:
    """CJK 感知的居中 —— 复用 D1 string_utils."""
    return pad_to_width(text, width, align="center")


class ConfigMerger:
    """三源合并 + 链表式溯源(sources list 接口, 支持任意源)."""

    def __init__(self, track_sources: bool = True):
        self.track_sources = track_sources
        self._metadata: Dict[str, ConfigMetadata] = {}
        self._overridden_keys: List[str] = []
        self._last_config_class = None

    def merge(self, config_class, *, sources=None):
        merged = self._do_merge(config_class, sources)
        try:
            return config_class(**merged)
        except ValidationError as e:
            if self.track_sources:
                self._enhance_validation_error(e)
            raise

    def preview(self, config_class, *, sources=None) -> Dict[str, Any]:
        """Dry-run: 合并 + 维护溯源, 但不实例化、不验证."""
        return self._do_merge(config_class, sources)

    def _do_merge(self, config_class, sources) -> Dict[str, Any]:
        self._metadata.clear(); self._overridden_keys.clear()
        self._last_config_class = config_class
        all_sources = [(ConfigSource.DEFAULT, self._extract_defaults(config_class))]
        all_sources.extend(sources or [])
        merged: Dict[str, Any] = {}
        for source, cfg in all_sources:
            self._apply_source(merged, dict(cfg or {}), source)
        return merged

    def _apply_source(self, merged, config, source):
        for key, value in config.items():
            if value is None:
                continue
            if key in merged and self.track_sources:
                self._overridden_keys.append(key)
            merged[key] = value
            if self.track_sources:
                prev = self._metadata.get(key)
                self._metadata[key] = ConfigMetadata(
                    key=key, value=value, source=source,
                    timestamp=datetime.now(), overridden_from=prev,
                )

    @staticmethod
    def _extract_defaults(config_class) -> Dict[str, Any]:
        return {n: f.default for n, f in config_class.model_fields.items()
                if f.default is not None}

    def get_metadata(self, key: str) -> Optional[ConfigMetadata]:
        return self._metadata.get(key)

    # ============ 来源报告 ============
    def get_source_report(self) -> str:
        if not self.track_sources:
            return "配置溯源未启用"
        lines = ["=" * 70, _center("配置来源报告"), "=" * 70]
        by_source: Dict[str, List[str]] = {}
        for key, meta in self._metadata.items():
            by_source.setdefault(meta.source_label, []).append(key)
        builtin = [s.value for s in (ConfigSource.CLI, ConfigSource.YAML, ConfigSource.DEFAULT)]
        ordered = [s for s in builtin if s in by_source]
        custom  = sorted(s for s in by_source if s not in builtin)
        for label in ordered + custom:
            keys = sorted(by_source[label])
            lines.append(f"\n{label} ({len(keys)} 项)")
            lines.append("-" * 70)
            for key in keys:
                value = self._display_value(key, self._metadata[key].value)
                lines.append(f"  {key} = {value}")
        return "\n".join(lines)

    def get_override_report(self) -> str:
        if not self.track_sources:
            return "配置溯源未启用"
        lines = ["=" * 70, _center("字段覆盖链报告"), "=" * 70]
        for key in self._overridden_keys:
            meta = self._metadata.get(key)
            if meta:
                lines.append(f"  {key}: {meta.chain_str()}")
        if not self._overridden_keys:
            lines.append("  (无覆盖, 所有字段来自单一来源)")
        return "\n".join(lines)

    # ============ mask ============
    def _is_sensitive(self, key: str) -> bool:
        cls = self._last_config_class
        return bool(cls and hasattr(cls, "sensitive_field_names")
                    and key in cls.sensitive_field_names())

    def _display_value(self, key: str, value: Any) -> Any:
        if value is None:
            return value
        if self._is_sensitive(key):
            return getattr(self._last_config_class, "SENSITIVE_MASK", "***")
        return value

    # ============ 审计产物 ============
    def to_audit_log(self) -> Dict[str, Any]:
        return {
            "fields": {
                k: {"value": self._display_value(k, m.value),
                    "source": m.source_label,
                    "chain": [f"{x.value}({x.source_label})" for x in m.chain()]}
                for k, m in self._metadata.items()
            },
            "overridden": list(dict.fromkeys(self._overridden_keys)),
        }

    def _enhance_validation_error(self, e: ValidationError) -> None:
        try:
            for error in e.errors():
                field_name = error.get("loc", [])
                if field_name:
                    key = field_name[0] if isinstance(field_name, (list, tuple)) else str(field_name)
                    meta = self._metadata.get(key)
                    if meta:
                        e.add_note(f"[溯源] {key}: {meta.chain_str()}")
        except Exception:
            pass