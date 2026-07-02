"""convert 框架层:一张表(格式名→条目) + 登记装饰器 @register + 参数包 ConvertOptions。

框架(本文件 + service.py)永远不动;加新格式 = 在 converters/ 加一个文件。
注:本阶段把"扫描 converters/ 目录"的逻辑【内联】在 _lazy_init 里;等阶段 4 的 split
   第二张表也要同样扫描时,我们才把它抽进 common/registry_utils.py(第二次才抽象)。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── 参数包:所有 converter 签名统一成 (input_dir, out_labels_dir, options) ──
@dataclass
class ConvertOptions:
    """所有格式转换共用的参数包。

    task   : 目标任务(detect / segment)。默认 detect 覆盖多数场景。
    classes: 类别白名单。
             None  = 用户没指定,由 converter 自行探测(仅 voc/coco 支持探测)。
             [...] = 用户指定的类别(同时决定 class_id 顺序)。
             ⚠️ 不要用 [] 当默认:None="没提供",[]="确实没有任何类别",语义不同。
    """
    task: str = "detect"
    classes: Optional[List[str]] = field(default=None)


# 一个 converter = 吃 (input_dir, out_labels_dir, options)、返回类名列表(顺序即 class_id)的函数。
ConverterFunc = Callable[[Path, Path, ConvertOptions], List[str]]


@dataclass(frozen=True)
class ConverterEntry:
    """注册表里一条记录:实现函数 + 它"能干哪些 task"的能力声明。"""
    func: ConverterFunc
    supported_tasks: Tuple[str, ...]

    def supports(self, task: str) -> bool:
        return task in self.supported_tasks


# 注册表本体:就是一个 {格式名: 条目} 的字典(模块级单例)
_REGISTRY: Dict[str, ConverterEntry] = {}


def register(format_name: str, *, supported_tasks: Tuple[str, ...]):
    """装饰器:把被装饰的函数(连同它支持的 task)登记进 _REGISTRY。

        @register("coco", supported_tasks=("detect", "segment"))
        def convert_coco(...): ...

    完全等价于在文件底部手写:
        _REGISTRY["coco"] = ConverterEntry(convert_coco, ("detect", "segment"))
    它在【该文件被 import 的那一刻】执行。
    """
    def decorator(func: ConverterFunc) -> ConverterFunc:
        if format_name in _REGISTRY:
            logger.warning("格式 %s 被重复注册,后者覆盖前者", format_name)
        _REGISTRY[format_name] = ConverterEntry(func=func, supported_tasks=tuple(supported_tasks))
        return func                       # 函数原样还回去,本身不变
    return decorator


def get_converter(format_name: str) -> ConverterEntry:
    """按 format 名取出条目。Raises: ValueError 未注册的格式。"""
    _lazy_init()
    if format_name not in _REGISTRY:
        raise ValueError(f"未注册的格式: {format_name!r}。已注册: {sorted(_REGISTRY)}")
    return _REGISTRY[format_name]


def available_formats() -> List[str]:
    """当前已注册的格式名(会先触发自动发现)。"""
    _lazy_init()
    return sorted(_REGISTRY)


# ── 自动发现:首次用表时,扫描 converters/ 把每个实现 import 一遍,触发它们的 @register ──
_LAZY_INITIALIZED = False


def _lazy_init() -> None:
    """扫描 converters/*.py 自动触发 @register。
    · 跳过 _ 开头的私有模块。
    · 标志位放在 import 全部成功【之后】——任何 import 失败都不污染状态,下次可重试。
    """
    global _LAZY_INITIALIZED
    if _LAZY_INITIALIZED:
        return
    from od_platform.data_pipeline.convert import converters
    from od_platform.common.registry_utils import import_submodules
    import_submodules(converters)
    _LAZY_INITIALIZED = True