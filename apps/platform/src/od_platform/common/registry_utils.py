# 注册表机制通用工具：自动发现并import一个包下面的所有实现模块，触发其中的@register装饰器

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

def import_submodules(package: ModuleType) -> None:
    """
    import package下面的所有子模块,触发其中的@register装饰器,实现自动注册机制
    """
    for m in pkgutil.iter_modules(package.__path__):
        if not m.name.startswith("_"):
            importlib.import_module(f"{package.__name__}.{m.name}")