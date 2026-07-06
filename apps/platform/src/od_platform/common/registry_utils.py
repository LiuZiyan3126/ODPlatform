#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :registry_utils.py
# @Time      :2026/7/1 13:18:00
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :注册表机制通用工具：自动发现并import 一个包下面的所有实现模块，触发其中的@register装饰器
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

def import_submodules(package: ModuleType) -> None:
    """
    import package下所有非下划线的子模块，触发其中的@register装饰器，实现自动注册机制
    """
    for m in pkgutil.iter_modules(package.__path__):
        if not m.name.startswith("_"):
            importlib.import_module(f"{package.__name__}.{m.name}")
