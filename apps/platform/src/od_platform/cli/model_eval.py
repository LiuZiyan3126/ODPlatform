#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""odp-eval — 单模型评估 CLI."""
from __future__ import annotations

import argparse
import logging
import sys

from od_platform.common.logging_utils import get_logger
from od_platform.common.paths import LOGGING_DIR
from od_platform.evaluation.service import ValService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odp-eval",
        description="YOLO 模型评估 — 在指定数据分片上评估模型表现",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  odp-eval --model models/trained/xxx-best.pt --data fire.yaml --split test
  odp-eval --model xxx-best.pt --data fire.yaml --yaml val.yaml --split val
  odp-eval --model xxx-best.pt --data fire.yaml --author "张三"
        """,
    )

    parser.add_argument(
        "--model", type=str, required=True,
        help="模型权重路径（支持相对路径，会自动在 models/trained/ 下查找）",
    )
    parser.add_argument(
        "--data", type=str, required=True,
        help="数据集声明名或 YAML 路径",
    )
    parser.add_argument(
        "--yaml", type=str, default=None,
        help="评估配置 YAML（默认 val.yaml）",
    )
    parser.add_argument(
        "--split", type=str, default="test",
        choices=["test", "val", "train"],
        help="评估分片（默认 test）",
    )
    parser.add_argument(
        "--author", type=str, default="",
        help="评估人标识",
    )
    parser.add_argument(
        "--no-plots", dest="plots", action="store_false", default=True,
        help="不保留可视化产物",
    )
    parser.add_argument(
        "--batch", type=int, default=None,
        help="覆盖 batch size",
    )
    parser.add_argument(
        "--device", type=str, default=None,
        help="覆盖设备选择",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )

    return parser


def _setup_logging(log_level: str) -> None:
    get_logger(
        base_path=LOGGING_DIR,
        log_type="eval_model",
        log_level=getattr(logging, log_level),
        temp_log=False,
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    _setup_logging(args.log_level)
    log = logging.getLogger("odp_platform.cli.model_eval")

    # 构建 CLI 覆盖参数（只传非配置项之外的覆盖值）
    cli_args = {}
    if args.batch is not None:
        cli_args["batch"] = args.batch
    if args.device is not None:
        cli_args["device"] = args.device
    if args.split is not None:
        cli_args["split"] = args.split

    log.info(f"启动 odp-eval: model={args.model}, data={args.data}, split={args.split}")

    try:
        service = ValService()
        result = service.evaluate(
            model_path=args.model,
            data_path=args.data,
            yaml_path=args.yaml,
            cli_args=cli_args or None,
            split=args.split,
            author=args.author,
            save_plots=args.plots,
        )
    except KeyboardInterrupt:
        log.warning("用户中断 (Ctrl+C)")
        return 130
    except Exception as e:
        log.error(f"未预期异常: {e}", exc_info=True)
        return 1

    if result.success:
        log.info(f"评估成功. 用时 {result.eval_time:.2f}s")
        if result.report_path:
            log.info(f"评估报告: {result.report_path}")
        return 0
    else:
        log.error(f"评估失败: {result.error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
