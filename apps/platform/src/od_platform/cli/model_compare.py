#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""odp-compare — 多模型对比 CLI.

MVP: 同数据集不同模型的评估对比。
"""
from __future__ import annotations

import argparse
import logging
import sys

from od_platform.common.logging_utils import get_logger
from od_platform.common.paths import LOGGING_DIR
from od_platform.evaluation.compare import compare_models
from od_platform.evaluation.service import ValService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odp-compare",
        description="多模型对比 — 在同一数据集上对比多个模型的表现",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  odp-compare --models a-best.pt b-best.pt --data fire.yaml
  odp-compare --models a.pt b.pt c.pt --data fire.yaml --split val
  odp-compare --models a.pt b.pt --data fire.yaml --author "张三"
        """,
    )

    parser.add_argument(
        "--models", type=str, nargs="+", required=True,
        help="要对比的模型权重路径列表",
    )
    parser.add_argument(
        "--data", type=str, required=True,
        help="数据集声明名或 YAML 路径",
    )
    parser.add_argument(
        "--yaml", type=str, default=None,
        help="评估配置 YAML（默认 val.yaml，所有模型共用）",
    )
    parser.add_argument(
        "--split", type=str, default="test",
        choices=["test", "val", "train"],
        help="评估分片（默认 test）",
    )
    parser.add_argument(
        "--author", type=str, default="",
        help="对比人标识",
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
        log_type="compare_models",
        log_level=getattr(logging, log_level),
        temp_log=False,
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    _setup_logging(args.log_level)
    log = logging.getLogger("odp_platform.cli.model_compare")

    log.info(f"启动 odp-compare: models={args.models}, data={args.data}, split={args.split}")

    # 对每个模型逐一评估
    eval_results = []
    service = ValService()

    cli_args = {}
    if args.batch is not None:
        cli_args["batch"] = args.batch
    if args.device is not None:
        cli_args["device"] = args.device

    try:
        for model_path in args.models:
            log.info(f"评估模型: {model_path}")
            result = service.evaluate(
                model_path=model_path,
                data_path=args.data,
                yaml_path=args.yaml,
                cli_args=cli_args or None,
                split=args.split,
                author=args.author,
            )
            eval_results.append({
                "model_name": result.model_path.stem,
                "model_path": str(result.model_path),
                "metrics": result.metrics,
                "eval_result": result,
            })

    except KeyboardInterrupt:
        log.warning("用户中断 (Ctrl+C)")
        return 130

    # 对比
    if not eval_results:
        log.error("无有效评估结果可对比")
        return 1

    compare_models(
        eval_results=eval_results,
        data_name=args.data,
        split=args.split,
        author=args.author,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
