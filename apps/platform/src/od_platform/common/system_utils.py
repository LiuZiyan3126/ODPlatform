#!/usr/bin/env python
# -*- coding:utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import sys
import time
from typing import Any, Optional

from od_platform.common.string_utils import pad_to_width

LINE_WIDTH = 60

logger = logging.getLogger(__name__)


def _format_size(bytes_size: Any) -> str:
    """Format a byte count into a human-readable string."""
    if not bytes_size or not isinstance(bytes_size, (int, float)):
        return "N/A"
    if bytes_size >= 1024 ** 3:
        return f"{bytes_size / 1024 ** 3:.2f} GB"
    if bytes_size >= 1024 ** 2:
        return f"{bytes_size / 1024 ** 2:.2f} MB"
    if bytes_size >= 1024:
        return f"{bytes_size / 1024:.2f} KB"
    return f"{bytes_size} B"


def _compact_error(message: str, max_length: int = 120) -> str:
    """Collapse multiline stderr into a short single-line message."""
    single_line = " ".join(message.split())
    if len(single_line) <= max_length:
        return single_line
    return single_line[: max_length - 3] + "..."


def _run_json_probe(probe_script: str, timeout: int = 20) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Run a short Python probe in a subprocess to isolate native-library crashes."""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe_script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"TimeoutExpired: probe exceeded {timeout}s"
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode != 0:
        return None, stderr or stdout or f"Probe exited with code {completed.returncode}"

    try:
        return json.loads(stdout), None
    except json.JSONDecodeError as exc:
        return None, f"JSONDecodeError: {exc}"


def _probe_torch_info() -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Collect torch/CUDA info without risking the current Python process."""
    probe_script = """
import json

result = {
    "ok": False,
    "error": None,
    "torch_version": None,
    "cuda_available": False,
    "gpu_count": 0,
    "gpus": [],
}

try:
    import torch

    result["ok"] = True
    result["torch_version"] = torch.__version__
    result["cuda_available"] = bool(torch.cuda.is_available())
    if result["cuda_available"]:
        result["gpu_count"] = torch.cuda.device_count()
        for index in range(result["gpu_count"]):
            props = torch.cuda.get_device_properties(index)
            result["gpus"].append(
                {
                    "index": index,
                    "name": torch.cuda.get_device_name(index),
                    "total_memory": props.total_memory,
                }
            )
except Exception as exc:
    result["error"] = f"{type(exc).__name__}: {exc}"

print(json.dumps(result, ensure_ascii=False))
"""
    result, error = _run_json_probe(probe_script)
    if result is None:
        return None, error
    if not result.get("ok"):
        return None, result.get("error") or "unknown torch probe error"
    return result, None


def _probe_ultralytics_version() -> tuple[Optional[str], Optional[str]]:
    """Collect the ultralytics version in isolation from the main process."""
    probe_script = """
import json

result = {
    "ok": False,
    "error": None,
    "ultralytics_version": None,
}

try:
    from ultralytics import __version__ as ultralytics_version

    result["ok"] = True
    result["ultralytics_version"] = ultralytics_version
except Exception as exc:
    result["error"] = f"{type(exc).__name__}: {exc}"

print(json.dumps(result, ensure_ascii=False))
"""
    result, error = _run_json_probe(probe_script)
    if result is None:
        return None, error
    if not result.get("ok"):
        return None, result.get("error") or "unknown ultralytics probe error"
    return result.get("ultralytics_version"), None


def get_basic_device_info() -> dict:
    """Return structured runtime, CPU, memory, and ML-stack information."""
    cpu_name = platform.processor() or platform.machine() or "Unknown CPU"
    cpu_cores = os.cpu_count() or "Unknown"

    try:
        import psutil

        memory = psutil.virtual_memory()
        total_ram = _format_size(memory.total)
        available_ram = _format_size(memory.available)
        ram_usage = f"{memory.percent}%"
    except ImportError:
        total_ram = "N/A(未安装psutil)"
        available_ram = "N/A(未安装psutil)"
        ram_usage = "N/A(未安装psutil)"

    torch_info, torch_error = _probe_torch_info()
    if torch_info is None:
        compact_error = _compact_error(torch_error or "unknown torch probe error")
        torch_version = f"N/A(探测失败: {compact_error})"
        cuda_available: bool | str = "N/A(探测失败)"
        gpu_count: int | str = "N/A(探测失败)"
        gpu_info = {
            "GPU可用": cuda_available,
            "GPU数量": gpu_count,
            "GPU探测异常": compact_error,
        }
    else:
        torch_version = torch_info["torch_version"]
        cuda_available = torch_info["cuda_available"]
        gpu_count = torch_info["gpu_count"]
        gpu_info = {
            "GPU可用": cuda_available,
            "GPU数量": gpu_count,
        }
        for gpu in torch_info["gpus"]:
            gpu_index = gpu["index"]
            gpu_info[f"GPU {gpu_index}"] = gpu["name"]
            gpu_info[f"GPU {gpu_index} 显存"] = _format_size(gpu["total_memory"])

    ultralytics_version, ultralytics_error = _probe_ultralytics_version()
    if ultralytics_version is None:
        compact_error = _compact_error(ultralytics_error or "unknown ultralytics probe error")
        ultralytics_version = f"N/A(探测失败: {compact_error})"

    return {
        "系统信息": {
            "操作系统": f"{platform.system()} {platform.release()} {platform.machine()}",
            "主机名": platform.node(),
            "Python版本": platform.python_version(),
            "PyTorch版本": torch_version,
            "Ultralytics版本": ultralytics_version,
            "当前时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "CPU信息": {
            "CPU型号": cpu_name,
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
    """Log device information through the provided logger."""
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
