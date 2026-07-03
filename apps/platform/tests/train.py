#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :train.py
# @Time      :2026/7/3
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :训练脚本 — 从数据集 YAML + 配置 → 产出训练好的模型
"""简单的 YOLO 训练脚本。

两种用法:
    # 1) 纯 CLI (最简, 适合快速实验)
    python -m od_platform.training.train --data rsod.yaml --model yolo11n.pt

    # 2) YAML 配置 + CLI 覆盖 (配置进 YAML, 覆盖用 CLI)
    python -m od_platform.training.train --data rsod.yaml --epochs 200 --lr0 0.001

依赖:
    ultralytics>=8.4.82, torch>=2.1.1

设计原则:
    - 不重复造轮子: 训练逻辑直接委托 ultralytics.model.train()
    - 跟项目基础设施接轨: 日志走 od_platform, 路径走 paths, 常量走 constants
    - 训练产出目录: runs/<task>/<experiment_name>/
"""

from __future__ import annotations

import argparse
import logging
from os import PathLike
from pathlib import Path
from typing import Any, Dict, Optional

from ultralytics import YOLO

from od_platform.common.constants import DEFAULT_RANDOM_STATE, Task
from od_platform.common.logging_utils import get_logger
from od_platform.common.paths import DATASET_CONFIGS_DIR, LOGGING_DIR
from od_platform.common.system_utils import log_device_info

logger = logging.getLogger(__name__)

# 默认值 —— 跟 runtime_config.YOLOTrainConfig 保持一致
DEFAULTS: Dict[str, Any] = {
    "model":    "yolo11n.pt",
    "epochs":   100,
    "batch":    16,
    "imgsz":    640,
    "device":   None,        # None = 自动 (优先 GPU)
    "workers":  8,
    "lr0":      0.01,
    "lrf":      0.01,
    "optimizer":"auto",
    "seed":     DEFAULT_RANDOM_STATE,
    "project":  None,        # None = 框架自动 (runs/<task>/)
    "name":     None,        # None = ultralytics 自动 (exp, exp2...)
    "exist_ok": False,
    "resume":   False,
    "patience": 100,
    "task":     Task.DETECT,
}


# ============================================================
# 路径解析
# ============================================================

def _resolve_data(data_ref: str) -> Path:
    """解析数据集引用: 优先当作绝对路径, 其次在 configs/datasets/ 下找。"""
    p = Path(data_ref)
    if p.exists():
        return p.resolve()
    # 允许省略 .yaml 后缀
    for candidate in (p, p.with_suffix(".yaml"), DATASET_CONFIGS_DIR / p, DATASET_CONFIGS_DIR / p.with_suffix(".yaml")):
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(
        f"找不到数据集配置文件: {data_ref}\n"
        f"  搜过: {p}, {p.with_suffix('.yaml')}, "
        f"{DATASET_CONFIGS_DIR / p}, {DATASET_CONFIGS_DIR / p.with_suffix('.yaml')}"
    )


def _resolve_model(model_ref: Optional[str]) -> str:
    """解析模型引用。None → yolo11n.pt。"""
    return model_ref or DEFAULTS["model"]


def _extract_save_dir(results: Any, yolo: Any) -> Path:
    """从 Ultralytics 训练结果中提取保存目录。"""
    save_dir_raw = getattr(results, "save_dir", None)
    if save_dir_raw is None:
        trainer = getattr(yolo, "trainer", None)
        save_dir_raw = getattr(trainer, "save_dir", None)

    if save_dir_raw is None:
        raise RuntimeError("训练完成, 但 Ultralytics 未返回 save_dir")
    if not isinstance(save_dir_raw, (str, PathLike)):
        raise TypeError(f"save_dir 类型不支持: {type(save_dir_raw).__name__}")

    return Path(save_dir_raw)


# ============================================================
# 构建 ultralytics kwargs
# ============================================================

def _build_kwargs(
    data: str,
    model: str,
    epochs: int,
    batch: int,
    imgsz: int,
    device: Optional[str],
    workers: int,
    lr0: float,
    lrf: float,
    optimizer: str,
    seed: int,
    project: Optional[str],
    name: Optional[str],
    exist_ok: bool,
    resume: bool,
    patience: int,
    **extra,
) -> Dict[str, Any]:
    """把 CLI 参数组装成 model.train() 能吃的 kwargs dict。"""
    kwargs: Dict[str, Any] = {
        "data":       str(_resolve_data(data)),
        "epochs":     epochs,
        "batch":      batch,
        "imgsz":      imgsz,
        "workers":    workers,
        "lr0":        lr0,
        "lrf":        lrf,
        "optimizer":  optimizer,
        "seed":       seed,
        "exist_ok":   exist_ok,
        "resume":     resume,
        "patience":   patience,
        "pretrained": True,
        "verbose":    True,
        "val":        True,
        "save":       True,
        "plots":      True,
    }
    if device is not None:
        kwargs["device"] = device
    if project is not None:
        kwargs["project"] = project
    if name is not None:
        kwargs["name"] = name

    # 混入 —yaml_config 过来的覆盖项
    kwargs.update({k: v for k, v in extra.items() if k in kwargs or v is not None})
    return kwargs


# ============================================================
# 主训练逻辑
# ============================================================

def train(
    data: str,
    model: Optional[str] = None,
    *,
    epochs: int = 100,
    batch: int = 16,
    imgsz: int = 640,
    device: Optional[str] = None,
    workers: int = 8,
    lr0: float = 0.01,
    lrf: float = 0.01,
    optimizer: str = "auto",
    seed: int = DEFAULT_RANDOM_STATE,
    project: Optional[str] = None,
    name: Optional[str] = None,
    exist_ok: bool = False,
    resume: bool = False,
    patience: int = 100,
    **extra,
) -> None:
    """训练 YOLO 模型。

    Args:
        data:       数据集 YAML 路径 (绝对 / 相对 / 仅名字)
        model:      模型文件 (默认 yolo11n.pt)
        epochs:     训练轮数
        batch:      批次大小
        imgsz:      输入图像尺寸
        device:     设备 (None=自动, "0"/"cpu"/"0,1")
        workers:    数据加载线程数
        lr0:        初始学习率
        lrf:        最终学习率因子 (final_lr = lr0 * lrf)
        optimizer:  优化器 (auto/SGD/Adam/AdamW)
        seed:       随机种子
        project:    输出根目录 (None=自动)
        name:       实验名 (None=自动)
        exist_ok:   是否覆盖已有实验目录
        resume:     是否从检查点恢复
        patience:   Early Stopping 耐心值

    Returns: None. 训练产出写在 project/name/ 下。
    """
    model_path = _resolve_model(model)
    kwargs = _build_kwargs(
        data=data, model=model_path, epochs=epochs, batch=batch,
        imgsz=imgsz, device=device, workers=workers, lr0=lr0, lrf=lrf,
        optimizer=optimizer, seed=seed, project=project, name=name,
        exist_ok=exist_ok, resume=resume, patience=patience, **extra,
    )

    logger.info("加载模型: %s", model_path)
    yolo = YOLO(model_path)

    logger.info(
        "开始训练: data=%s, epochs=%d, batch=%d, imgsz=%d, device=%s",
        kwargs["data"], epochs, batch, imgsz, device or "auto",
    )
    results = yolo.train(**kwargs)

    save_dir = _extract_save_dir(results, yolo)
    best_pt = save_dir / "weights" / "best.pt"
    last_pt = save_dir / "weights" / "last.pt"
    logger.info("训练完成。best.pt: %s, last.pt: %s", best_pt, last_pt)


# ============================================================
# CLI
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="YOLO 目标检测训练 (od_platform)",
    )
    parser.add_argument("--data", required=True, help="数据集 YAML 路径 (必填)")
    parser.add_argument("--model", default=None, help=f"模型文件 (默认: {DEFAULTS['model']})")
    parser.add_argument("--epochs", type=int, default=DEFAULTS["epochs"])
    parser.add_argument("--batch", type=int, default=DEFAULTS["batch"])
    parser.add_argument("--imgsz", type=int, default=DEFAULTS["imgsz"])
    parser.add_argument("--device", default=None, help="设备 (0/cpu/mps/0,1)")
    parser.add_argument("--workers", type=int, default=DEFAULTS["workers"])
    parser.add_argument("--lr0", type=float, default=DEFAULTS["lr0"])
    parser.add_argument("--lrf", type=float, default=DEFAULTS["lrf"])
    parser.add_argument("--optimizer", default=DEFAULTS["optimizer"])
    parser.add_argument("--seed", type=int, default=DEFAULTS["seed"])
    parser.add_argument("--project", default=None, help="输出根目录")
    parser.add_argument("--name", default=None, help="实验名")
    parser.add_argument("--exist-ok", action="store_true", default=False)
    parser.add_argument("--resume", action="store_true", default=False)
    parser.add_argument("--patience", type=int, default=DEFAULTS["patience"])
    args = parser.parse_args()

    # 装配日志
    get_logger(base_path=LOGGING_DIR, log_type="train")
    log_device_info()

    train(
        data=args.data,
        model=args.model,
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=args.device,
        workers=args.workers,
        lr0=args.lr0,
        lrf=args.lrf,
        optimizer=args.optimizer,
        seed=args.seed,
        project=args.project,
        name=args.name,
        exist_ok=args.exist_ok,
        resume=args.resume,
        patience=args.patience,
    )


if __name__ == "__main__":
    main()
