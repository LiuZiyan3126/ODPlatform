#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :loaders.py.py
# @Time      :2026/7/3 14:38:29
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : loaders.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统——配置加载器(只读成 dict, 不验证不合并)
"""配置加载器: 把外部数据装进 dict.

★ 职责边界: Loader 只把外部数据装进 dict.
    - 字段值验证 → Pydantic(阶段 2-3)
    - 多源合并   → ConfigMerger(阶段 5)
"""
from __future__ import annotations

import logging
from argparse import Namespace
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

import yaml

logger = logging.getLogger(__name__)


def _drop_none(d: Mapping[str, Any]) -> Dict[str, Any]:
    """过滤 None, 保留 False / 0 / '' 等显式值.

    YAML 的 null 等同"没写", 合并时不该参与覆盖, 让下层默认值有机会跑.
    但 False / 0 / '' 是用户显式填的"假", 必须保留 ——
    不要写成 {k: v for k, v in d.items() if v}(经典 falsy 误伤).
    """
    return {k: v for k, v in d.items() if v is not None}


class YAMLLoader:
    """加载 YAML 配置文件 → dict."""

    def __init__(self, config_dir: Optional[Union[str, Path]] = None):
        self.config_dir = Path(config_dir) if config_dir else None

    def load(self, filename: Union[str, Path]) -> Dict[str, Any]:
        # 1. 解析路径(文件名→config_dir 下找; 绝对/相对原样)
        filepath = self._resolve_path(filename)

        # 2. 不存在 → fail-fast + 修复指引(★ 撞墙③)
        if not filepath.exists():
            raise FileNotFoundError(
                f"YAML 配置文件不存在: {filepath}\n\n"
                f"请先生成默认配置模板:\n"
                f"  odp-gen-config {filepath.stem}\n\n"
                f"生成后编辑该文件再重新运行."
            )

        # 3. 读文件(默认 UTF-8, 失败 fallback —— 系统行为, 走 logger)
        try:
            content = filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logger.warning(f"UTF-8 解码失败, 尝试系统默认编码: {filepath}")
            content = filepath.read_text()

        # 4. 空文件 → {}(合法, 等同"全用默认值")
        if not content.strip():
            logger.debug(f"YAML 文件为空: {filepath}")
            return {}

        # 5. 解析 —— 失败 fail-fast, 保留 exception chain
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise ValueError(
                f"YAML 格式错误: {filepath}\n原始错误: {e}\n"
                f"提示: 检查缩进、引号匹配、冒号后是否有空格."
            ) from e

        # 6. 顶层结构检查
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError(
                f"YAML 顶层必须是字典, 当前是 {type(data).__name__}: {filepath}"
            )
        return data

    def _resolve_path(self, filename: Union[str, Path]) -> Path:
        p = Path(filename)
        if p.is_absolute():
            return p
        if self.config_dir is not None:
            return self.config_dir / p
        return p


class CLILoader:
    """从 argparse Namespace 提取配置参数 → dict."""

    CONTROL_FIELDS = {"config", "func", "command"}

    def load(self, args: Namespace, *, exclude: Optional[set[str]] = None) -> Dict[str, Any]:
        exclude = (exclude or set()) | self.CONTROL_FIELDS
        raw = {k: v for k, v in vars(args).items() if k not in exclude}
        return _drop_none(raw)     # None = "用户没在 CLI 给这个参数", 不覆盖