#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :model_train.py
# @Time      :2026/7/6 14:53:18
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
from __future__ import annotations

import argparse
import logging
import sys

from od_platform.common.logging_utils import get_logger
from od_platform.common.paths import LOGGING_DIR

from od_platform.training.service import TrainService


# ============================================================================
# argparse
# ============================================================================

def build_parser() -> argparse.ArgumentParser:
    """构造 argparse parser. 拆出来让测试可以独立验证 CLI 表面."""
    parser = argparse.ArgumentParser(
        prog="odp-train",
        description="YOLO 训练 — 调 D5 配置 + D4 校验 + ultralytics 训练",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  odp-train                                       # 默认 train.yaml
  odp-train --yaml my_train.yaml --epochs 200
  odp-train --batch 32 --device 0
  odp-train --device 0,1                          # 多 GPU
  odp-train --no-pre-validate                     # 跳过 D4 校验
  odp-train --academic-plots                      # 学术风格出图
        """,
    )

    # ---- 配置文件 ----
    parser.add_argument(
        "--yaml", type=str, default=None,
        help="YAML 配置文件路径(默认走 RUNTIME_CONFIGS_DIR/train.yaml)",
    )


    # ---- 训练超参数(覆盖 yaml) ----
    parser.add_argument("--model",     type=str,   help="模型路径 / 文件名(默认走 yaml)")
    parser.add_argument("--data",      type=str,   help="数据集 yaml(默认走 yaml)")
    parser.add_argument("--epochs",    type=int,   help="训练轮数")
    parser.add_argument("--batch",     type=int,   help="batch size(支持 -1/0-1.0)")
    parser.add_argument("--imgsz",     type=int,   help="输入图像尺寸")
    parser.add_argument("--device",    type=str,   help="训练设备(0/cpu/0,1)")
    parser.add_argument("--lr0",       type=float, help="初始学习率")
    parser.add_argument("--optimizer", type=str,   help="优化器")
    parser.add_argument("--workers",   type=int,   help="DataLoader workers")
    parser.add_argument("--seed",      type=int,   help="随机种子")
    parser.add_argument("--project",   type=str,   help="输出根目录")
    parser.add_argument("--name",      type=str,   help="运行名(yolo 用)")
    parser.add_argument("--experiment-name", dest="experiment_name", type=str,
                        help="实验名(ODP 用, 进 runs/<task>_train/<experiment_name>/)")

    # ---- D6 开关(service 层的 keyword-only 参数) ----
    parser.add_argument(
        "--no-archive", dest="archive", action="store_false", default=True,
        help="不复制 best/last.pt 到 CHECKPOINTS_DIR",
    )
    parser.add_argument(
        "--no-rename-log", dest="rename_log", action="store_false", default=True,
        help="不把日志文件名改成 <save_dir>_<ts>_<model>.log 形式",
    )

    # ---- 可选辅助 ----
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )

    return parser


# ============================================================================
# 日志 handler 装载 — 业务模块只发声, handler 唯一装的地方就在这
# ============================================================================

def _setup_logging(log_level: str) -> None:
    """调 D2 的 get_logger 给 'odp_platform' 根 logger 装上 console + file handler."""
    get_logger(
        base_path=LOGGING_DIR,
        log_type="train_model",
        log_level=getattr(logging, log_level),
        temp_log=False,
    )


# ============================================================================
# main 入口
# ============================================================================

def main() -> int:
    """odp-train 主入口. 返回退出码 0/1/130."""
    parser = build_parser()
    args = parser.parse_args()

    # 1. 学术 plots (可选, 影响全局 — 越早 apply 越好)
    # if args.academic_plots:
    #     from odp_platform.common.plot_style import apply_academic_style
    #     apply_academic_style()

    # 2. 装日志 handler (走 D2 get_logger, 唯一一次)
    _setup_logging(args.log_level)
    log = logging.getLogger("odp_platform.cli.train_model")

    # 3. argparse.Namespace → dict, 过滤 None(让 D5 走默认值) + 拆出非配置字段
    NON_CONFIG_KEYS = {
        "yaml", "pre_validate", "archive", "rename_log",
        "academic_plots", "log_level",
    }
    cli_args = {
        k: v for k, v in vars(args).items()
        if v is not None and k not in NON_CONFIG_KEYS
    }

    # 4. 调 service
    log.info(f"启动 odp-train, CLI 字段: {list(cli_args.keys())}")
    try:
        service = TrainService()
        result = service.train(
            yaml_path=args.yaml,
            cli_args=cli_args,
            archive=args.archive,
            rename_log=args.rename_log,
        )
    except KeyboardInterrupt:
        log.warning("用户中断 (Ctrl+C)")
        return 130
    except Exception as e:        # service 本应 not raise, 兜底
        log.error(f"未预期异常: {e}", exc_info=True)
        return 1

    # 5. 退出码
    if result.success:
        log.info(f"✓ 训练成功. 用时 {result.train_time:.2f}s, 输出 {result.output_dir}")
        return 0
    else:
        log.error(f"✗ 训练失败: {result.error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
