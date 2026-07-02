# split子系统的划分策略注册表 + 统一的参数包ConvertOptions

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from od_platform.common.constants import DEFAULT_RANDOM_STATE
from od_platform.data_pipeline.split.manifest import PairList, SplitManifest

logger = logging.getLogger(__name__)

@dataclass
class SplitOptions:
    """
    所有划分策略共用的参数包。
    """
    train_rate: float|int = 0.8
    val_rate: float|int = 0.1
    random_state: int = DEFAULT_RANDOM_STATE
    labels_per_image: Optional[Dict[str, List[str]]] = field(default=None)
    group_per_image: Optional[Dict[str, str]] = field(default=None) # 预留给按组划分的


# 一个划分策略的统一类型：(样本对列表，参数包) -> SplitManifest
StrategyFunc = Callable[[SplitManifest, SplitOptions], SplitManifest]

@dataclass(frozen=True)
class StrategyEntry:
    """注册表里面的一条记录：策略函数+他的能力声明"""
    func: StrategyFunc
    requires_labels: bool = False


_STRATEGY_REGISTRY: Dict[str, StrategyEntry] = {}

def register_strategy(name: str, *, requires_labels: bool = False):
    """装饰器:把花粉策略登记进表"""
    def decorator(func: StrategyFunc) -> StrategyFunc:
        if name in _STRATEGY_REGISTRY:
            logger.warning(f"策略 {name} 已经注册过了,新注册的会覆盖旧的。")
        _STRATEGY_REGISTRY[name] = StrategyEntry(func=func, requires_labels=requires_labels)
        return func
    return decorator

def get_strategy(name: str) -> StrategyEntry:
    """按名字取策略"""
    _lazy_init()
    if name not in _STRATEGY_REGISTRY:
        raise ValueError(f"未注册的划分策略：{name}，已经注册的：{_STRATEGY_REGISTRY.keys()}")
    return _STRATEGY_REGISTRY[name]


def list_strategies() -> Tuple[str,...]:
    _lazy_init()
    return tuple(sorted(_STRATEGY_REGISTRY))


_LAZY_INITIALIZED = False
def _lazy_init() -> None:
    global _LAZY_INITIALIZED
    if _LAZY_INITIALIZED:
        return
    from od_platform.common.registry_utils import import_submodules
    from od_platform.data_pipeline.split import strategies
    import_submodules(strategies)
    _LAZY_INITIALIZED = True

