#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :yaml_schema.py
# @Time      :2026/7/2 13:01:52
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
"""
yaml_schema check: 验证数据集yaml文件的字段完整性和一致性

检查项: 任何一项失败都要标记ERROR
    1. yaml文件存在而且要能解析
    2. yaml文件的顶层肯定是一个字典
    3. 包含nc字段, 是正整数
    4. 包含names字段, 是一个字符串列表, 或者是一个字典
    5. nc字段的值等于names字段中元素个数
"""

from __future__ import annotations

from typing import List

from od_platform.validate_dataset.registry import (check, CheckContext, CheckResult, CheckSeverity)


@check("yaml_schema")  # 新*
def validate_yaml_schema(ctx: CheckContext) -> CheckResult:
    snap = ctx.snapshot

    if snap.yaml_load_error is not None:
        return CheckResult(
            name="yaml_schema",
            severity=CheckSeverity.ERROR,
            summary=snap.yaml_load_error,
            details={
                "reason": "yaml_load_error",
                "yaml_path": str(snap.yaml_path),
                "yaml_load_error": snap.yaml_load_error
            }
        )

    problems: List[str] = []
    nc = snap.nc
    if nc is None or nc <= 0:
        problems.append(f"nc字段不存在或者nc字段的值不是正整数: {snap.yaml_data.get('nc')}")

    names = snap.class_names
    if not names:
        raw = snap.yaml_data.get("names")
        problems.append(f"names 缺失或者是不合法的字典或者列表: {type(raw).__name__}")

    if nc is not None and nc > 0 and names and (len(names) != nc):
        problems.append(f"nc 和 names长度不一致, nc: {nc}, names: {names}")

    if problems:
        return CheckResult(
            name="yaml_schema",
            severity=CheckSeverity.ERROR,
            summary=f"yaml字典不一致: 共有 {len(problems)} 个问题",
            details={
                "reason": "field_inconsistency",
                "problems": problems,
                "nc": nc,
                "names_count": len(names) if names else 0
            }
        )

    return CheckResult(
        name="yaml_schema",
        severity=CheckSeverity.INFO,
        summary=f"yaml字段一致 (nc = {nc}, names_count = {len(names)}) ",
        details={
            "nc": nc,
            "names_count": len(names) if names else 0
        }
    )
