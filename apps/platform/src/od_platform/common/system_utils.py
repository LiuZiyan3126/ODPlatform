#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :system_utils.py
# @Time      :2026/6/30 09:08:26
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
from __future__ import annotations

import logging
import os
import platform
import time
from typing import Optional

from od_platform.common.string_utils import format_size, pad_to_width

LINE_WIDTH = 60

logger = logging.getLogger(__name__)


def get_basic_device_info() -> dict:
    """返回结构化的环境信息字典"""
    cpu_name = platform.processor() or platform.machine() or "未知CPU"
    cpu_cores = os.cpu_count() or "未知"

    try:
        import psutil

        memory = psutil.virtual_memory()
        total_ram = format_size(memory.total)
        available_ram = format_size(memory.available)
        ram_usage = f"{memory.percent}%"
    except ImportError:
        total_ram = "N/A(未安装psutil)"
        available_ram = "N/A(未安装psutil)"
        ram_usage = "N/A(未安装psutil)"

    try:
        import torch

        torch_version = torch.__version__
        cuda_available = torch.cuda.is_available()
        gpu_count = torch.cuda.device_count() if cuda_available else 0
        torch_module = torch
    except ImportError:
        torch_version = "N/A(未安装torch)"
        cuda_available = "N/A(未安装torch)"
        gpu_count = "N/A(未安装torch)"
        torch_module = None

    try:
        from ultralytics import __version__ as ultralytics_version
    except ImportError:
        ultralytics_version = "N/A(未安装ultralytics)"

    gpu_info = {
        "GPU可用": cuda_available,
        "GPU数量": gpu_count,
    }
    if cuda_available and torch_module is not None:
        for i in range(gpu_count):
            gpu_info[f"GPU {i}"] = torch_module.cuda.get_device_name(i)
            gpu_info[f"GPU {i} 显存"] = format_size(
                torch_module.cuda.get_device_properties(i).total_memory
            )

    return {
        "系统信息": {
            "操作系统": f"{platform.system()} {platform.release()} {platform.machine()}",
            "主机名": platform.node(),
            "Python版本": platform.python_version(),
            "pytorch版本": torch_version,
            "ultralytics版本": ultralytics_version,
            "当前时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "CPU信息": {
            "cpu型号": cpu_name,
            "核心数": cpu_cores,
        },
        "内存信息": {
            "总内存": total_ram,
            "可用内存": available_ram,
            "内存使用率": ram_usage,
        },
        "GPU信息": gpu_info,
    }


def log_device_info(target_logger: Optional[logging.Logger] = None) -> dict:
    """把环境信息打印到 logger"""
    log = target_logger if target_logger is not None else logger
    info = get_basic_device_info()

    log.info("运行环境信息概览".center(LINE_WIDTH))
    log.info("=" * LINE_WIDTH)

    key_width = 20
    for category, details in info.items():
        log.info(f"{category}".center(LINE_WIDTH))
        log.info("-" * LINE_WIDTH)
        for key, value in details.items():
            padded_key = pad_to_width(key, key_width)
            log.info(f"{padded_key}: {value}")

    return info


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    log_device_info()
