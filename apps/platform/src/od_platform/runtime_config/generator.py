#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :generator.py.py
# @Time      :2026/7/3 14:50:31
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : generator.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统——反射式 YAML 模板生成器
"""配置生成器: 从 Pydantic 字段反射出自解释 YAML 模板.

★ 缺口④(模板手维护)在此填上.
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from od_platform.common.paths import runtime_config_path
from od_platform.runtime_config.registry import CONFIG_REGISTRY

logger = logging.getLogger(__name__)


class ConfigGenerator:
    """反射式 YAML 模板生成器."""

    def generate(self, config_class, output_path, *,
                overwrite: bool = False,
                backup: bool = True,
                title: str | None = None) -> bool:
        output_path = Path(output_path)

        if output_path.exists() and not overwrite:
            logger.info(f"配置文件已存在, 跳过生成: {output_path}")
            return False

        if output_path.exists() and backup:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            bak = output_path.with_name(f"{output_path.name}.bak.{stamp}")
            shutil.copy2(output_path, bak)
            logger.warning(f"覆盖前已备份原配置: {bak}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self._generate_yaml(config_class, title), encoding="utf-8")
        logger.info(f"配置文件已生成: {output_path}")
        return True

    def _generate_yaml(self, config_class, title: str | None = None) -> str:
        try:
            config = config_class()
        except Exception:
            config = config_class.model_construct()

        lines: list[str] = []
        display_title = title or config_class.__name__
        lines.append(f"#{'='*78}")
        lines.append(f"# {display_title}")
        lines.append(f"# 自动生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"# 编辑后保存; 重新生成(--overwrite)会覆盖并备份原文件.")
        lines.append(f"#{'='*78}")
        lines.append("")

        groups = config.get_field_groups()
        for group_name, field_names in groups.items():
            lines.append(f"#{'-'*78}")
            lines.append(f"# {group_name}")
            lines.append(f"#{'-'*78}")
            lines.append("")

            for fname in field_names:
                meta = config.get_field_metadata(fname)
                lines.append(f"# {meta['yaml_comment']}")
                examples = meta.get("examples", [])
                if examples:
                    lines.append(f"# 示例: {', '.join(self._format_value(e) for e in examples)}")
                tips = meta.get("tips", [])
                if tips:
                    lines.append("# 提示:")
                    lines.extend(f"#   - {t}" for t in tips)
                default_val = meta.get("default")
                lines.append(f"{fname}: {self._format_value(default_val)}")
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_value(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):                       # ★ 必须在 int 之前!
            return "true" if value else "false"
        if isinstance(value, str):
            if any(c in value for c in [":", "#", "[", "]", "{", "}"]):
                return f'"{value}"'
            return value
        if isinstance(value, (list, tuple)):
            if not value:
                return "[]"
            return f"[{', '.join(str(v) for v in value)}]"
        return str(value)


def main():
    """odp-gen-config 命令入口."""
    import argparse
    parser = argparse.ArgumentParser(prog="odp-gen-config", description="生成 YOLO 运行配置 YAML 模板")
    parser.add_argument("name", choices=list(CONFIG_REGISTRY), help="配置名 (train/val/infer)")
    parser.add_argument("-o", "--output", type=Path, default=None, help="输出路径")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有文件(默认不覆盖)")
    parser.add_argument("--no-backup", action="store_true", help="覆盖时不备份(默认备份)")
    args = parser.parse_args()

    config_class, title = CONFIG_REGISTRY[args.name]
    output_path = args.output or runtime_config_path(args.name)
    ok = ConfigGenerator().generate(config_class, output_path,
                                    overwrite=args.overwrite, backup=not args.no_backup, title=title)
    print(f"[OK] 已生成: {output_path}" if ok else
        f"[SKIP] 文件已存在, 未覆盖. 如需重新生成加 --overwrite(会自动备份).\n  路径: {output_path}")


if __name__ == "__main__":
    main()
