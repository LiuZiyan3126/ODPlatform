"""帧源注册表: @register_source 装饰器 + 自动发现 sources/*.py.

跟 data_pipeline/convert/registry.py 同构:
  - 装饰器在模块 import 时触发, 把条目登记进 _REGISTRY
  - _lazy_init() 扫描 sources/ 下所有非 _ 开头的 .py, 触发其中的 @register_source
  - find_source() 按 priority 顺序匹配, 第一个 detect 返回 True 的获胜
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .core.base import FrameSource
from .core.config import CameraConfig

logger = logging.getLogger(__name__)


@dataclass
class SourceEntry:
    name: str
    detect: Callable[[str], bool]
    build: Callable[[str, Optional[CameraConfig], dict[str, Any]], FrameSource]
    priority: int = 0


_REGISTRY: list[SourceEntry] = []


def register_source(name: str, *, detect: Callable[[str], bool], priority: int = 0):
    def decorator(build_fn):
        entry = SourceEntry(name=name, detect=detect, build=build_fn, priority=priority)
        _REGISTRY.append(entry)
        _REGISTRY.sort(key=lambda e: e.priority)
        return build_fn
    return decorator


_LAZY_INITIALIZED = False


def _lazy_init() -> None:
    global _LAZY_INITIALIZED
    if _LAZY_INITIALIZED:
        return
    from od_platform.frame_source import sources
    from od_platform.common.registry_utils import import_submodules
    import_submodules(sources)
    _LAZY_INITIALIZED = True


def find_source(source: str, camera_config: Optional[CameraConfig], options: dict[str, Any]) -> FrameSource:
    _lazy_init()
    for entry in _REGISTRY:
        if entry.detect(source):
            logger.debug(f"帧源匹配: {entry.name} ← {source!r}")
            return entry.build(source, camera_config, options)
    raise ValueError(f"Source {source!r} is not a valid frame source. "
                     f"已注册类型: {[e.name for e in _REGISTRY]}")
