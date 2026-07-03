#!/usr/bin/env python
# -*- coding:utf-8 -*-
# FileName :registry.py
# Time    :2026/7/2 09:21:32
# Author  :雨雪同学
# Project :ODPLatform
# Function :data_validation注册表+数据契约(CheckResult + CheckSeverity + CheckContext)

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


# ==================== 1. CheckSeverity - 严重程度 ====================
class CheckSeverity:
    """检查结果严重程度枚举"""
    INFO = "INFO"      # 告知级别：工程上知道一下，不阻断
    WARNING = "WARNING"  # 关注级别：能继续，但需要人工review
    ERROR = "ERROR"    # 阻塞级别 CI必须听，训练绝对不能继续
    PASS = "PASS"      # 通过

    _ORDER = {INFO: 1, WARNING: 2, ERROR: 3, PASS: 0}

    @classmethod
    def rank(cls, level: str) -> int:
        """获取严重程度的排序值，数值越大越严重"""
        return cls._ORDER.get(level, 0)


# ==================== 2. CheckResult - 单个check的统一返回类型 ====================
@dataclass
class CheckResult:
    """单个检查的统一返回类型"""
    name: str
    severity: str
    summary: str          # 一句话总结，供终端日志/报告的头部使用，给人看的
    details: Dict[str, Any] = field(default_factory=dict)  # 结构化详情字典 - json报告 给机器看的

    @property
    def passed(self) -> bool:
        """判断检查是否通过(PASS或INFO视为通过)"""
        return self.severity in (CheckSeverity.PASS, CheckSeverity.INFO)


# ==================== 3. CheckContext - check函数的入参 ====================
@dataclass
class CheckContext:
    """check函数的入参: 所有check函数的签名都是这个"""
    yaml_path: Path
    snapshot: Any = None


# ==================== 4. CheckEntry - 注册表条目 ====================
@dataclass(frozen=True)
class CheckEntry:
    """注册表中的一条记录。frozen - 注册后不可改"""
    name: str
    func: Callable[[CheckContext], CheckResult]   # 检查函数


# ==================== 5. 模块级别的注册表 ====================
_REGISTRY: Dict[str, CheckEntry] = {}


# ==================== 6. 装饰器注册 ====================
def check(name: str) -> Callable:
    """装饰器：将函数注册为检查项"""
    def decorator(func: Callable[[CheckContext], CheckResult]) -> Callable:
        if name in _REGISTRY:
            raise ValueError(
                f"check {name} 重复注册 - 第二次出现在 {func.__module__}.{func.__name__}"
            )
        _REGISTRY[name] = CheckEntry(name=name, func=func)
        return func
    return decorator


# ==================== 7. 自动导入 ====================
_LAZY_INITIALIZED = False


def _lazy_init() -> None:
    """
    扫描 checks/*.py 自动触发 @register。
    · 跳过 _ 开头的私有模块。
    · 标志位放在 import 全部成功【之后】— 任何 import 失败都不污染状态，下次可重试。
    """
    global _LAZY_INITIALIZED
    if _LAZY_INITIALIZED:
        return
    from od_platform.validate_dataset import checks
    from od_platform.common.registry_utils import import_submodules
    import_submodules(checks)
    _LAZY_INITIALIZED = True



# ==================== 8. 查询API ====================
def get_all_checks() -> List[CheckEntry]:
    """返回全部注册的check"""
    _lazy_init()
    return list(_REGISTRY.values())


def get_check(name: str) -> CheckEntry:
    """返回指定名称的check"""
    _lazy_init()
    if name not in _REGISTRY:
        raise ValueError(f"check {name} 未注册 - 已经注册的检查有: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]


def list_check_names() -> List[str]:
    """返回已经注册的名字列表"""
    _lazy_init()
    return list(_REGISTRY.keys())
