#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :config_log.py
# @Time      :2026/7/6 09:52:39
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :按字段维度的配置溯源日志
from __future__ import annotations

import logging
from typing import Any

from torch.fx.experimental.unification.multipledispatch.dispatcher import source

from od_platform.common.string_utils import pad_to_width

# 记录 字段当前值 + 来源， 一行一个字段
def log_effective_config(
        config: Any,
        merger: Any,
        *,
        logger : logging.Logger | None = None,
        key_width: int = 20,
        section_width: int = 60,
) -> None:
    log = logger or logging.getLogger(__name__)
    log.info("=" * section_width)
    log.info("配置参数信息".center(section_width))
    log.info("-" * section_width)

    for field_name in config.__class__.model_fields.keys():
        value = getattr(config, field_name, None)
        meta = _safe_get_metadata(merger, field_name)
        source_label = meta.source_label if meta is not None else "未知"
        log.info(f"{pad_to_width(field_name, key_width)}: {value}  (来源：{source_label})")


def _safe_get_metadata(merger: Any, field_name: str) -> Any:
    if not hasattr(merger, "get_metadata"):
        return None
    try:
        return merger.get_metadata(field_name)
    except Exception:
        return None

# 记录 字段的完成来源链： DEFAULT -> YAML -> CLI
def log_override_chains(
    config: Any,
    merger: Any,
    *,
    logger : logging.Logger | None = None,
        key_width: int = 20,
        section_width: int = 60,
    ) -> None:
    log = logger or logging.getLogger(__name__)
    log.info("=" * section_width)
    log.info("配置覆盖情况".center(section_width))
    log.info("-" * section_width)

    for field_name in config.__class__.model_fields.keys():
        meta = _safe_get_metadata(merger, field_name)
        if meta is None:
            value = getattr(config, field_name, None)
            log.info(f"{pad_to_width(field_name, key_width)}: {value}")
            continue
        chain = list(reversed(meta.chain()))
        chain_str = "<-".join(f"{m.value}({m.source_label})" for m in chain)
        log.info(f"{pad_to_width(field_name,key_width)}: {chain_str}")

