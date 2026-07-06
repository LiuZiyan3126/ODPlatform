#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :log_rename.py
# @Time      :2026/7/6 13:21:04
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
from __future__ import annotations

import logging
import re
from pathlib import Path

from pandas.core.reshape import encoding

logger = logging.getLogger(__name__)
_TIMESTAMP_RE = re.compile(r"(\d{8}-\d{6}(?:-\d+)?)")
ROOT_LOOGER_NAME: str = 'od_platform'

def rename_log_to_save_dir(
    save_dir: Path,
    model_stem: str,
    ) -> Path | None:
    root = logging.getLogger(ROOT_LOOGER_NAME)
    # 1. 在named_root上找FileHandler
    file_handler =next(
        (h for h in root.handlers if isinstance(h,logging.FileHandler)), None
    )
    if file_handler is None:
        logging.warning(f"{ROOT_LOOGER_NAME} 根logger 没有FileHandler，跳过日志改名")
        return None

    old_path = Path(file_handler.baseFilename)

    # 2.从原文件名提取时间戳
    match = _TIMESTAMP_RE.search(old_path.stem)
    if match:
        timestamp = match.group(1)
    else:
        timestamp = "unkown-time"
        logger.warning(f"原日志{old_path}没有时间戳，使用未知时间戳")

    new_name = f"{save_dir.name}_{timestamp}_{model_stem}.log"
    new_path = old_path.parent / new_name

    # 3.保存旧handler配置给新的handler
    formatter = file_handler.formatter
    level = file_handler.level
    encoding = getattr(file_handler, "encoding", None) or "utf-8"

    # 4.关闭旧的handler释放文件句柄
    file_handler.close()
    root.removeHandler(file_handler)

    # 5.物理改名
    if not old_path.exists():
        logger.warning(f"原日志{old_path}不存在，跳过改名")
        return None
    try:
        old_path.rename(new_path)
    except OSError as e:
        logger.warning(f"原日志{old_path}改名失败，尝试恢复旧handler继续写")
        try:
            restored = logging.FileHandler(old_path, encoding=encoding)
            if formatter:
                restored.setFormatter(formatter)
            restored.setLevel(level)
            root.addHandler(restored)
        except OSError as e2:
            logger.error(f"回滚handler也失败{e2}-后续日志可能丢失")
        return None
    # 6. 新handler指向新文件
    try:
        new_handler = logging.FileHandler(new_path, encoding=encoding)
        if formatter:
            new_handler.setFormatter(formatter)
        new_handler.setLevel(level)
        root.addHandler(new_handler)
    except OSError as e:
        logger.error(
            f"创建新handler失败{e}-后续日志可能丢失"
        )
        return new_path
    logger.info(f"日志文件已经重命名：{new_path.name}")
    return  new_path
