#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :transform_data.py
# @Time      :2026/7/1 15:35:11
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
from __future__ import  annotations
import argparse
import logging
import sys

from od_platform.common.constants import  AnnotationFormat,SplitStrategy, Task
from od_platform.data_pipeline.orchestrator import DatasetPipeline
from od_platform.common.logging_utils import get_logger
from od_platform.common.paths import LOGGING_DIR

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_DATA_ERR = 1
EXOT_USAGE = 2


def main(argv = None) -> int:
    logger = get_logger(
        base_path=LOGGING_DIR,
        log_type="transform_data",
        temp_log=False,
    )
    p = argparse.ArgumentParser(prog='odp-transform', description="完成数据集的转换划分和落盘已经对应yaml文件的生成")
    p.add_argument("--dataset", required=True,help="数据集的名称")
    p.add_argument("--format", required=True,choices=AnnotationFormat.all(), dest="fmt")
    p.add_argument("--task", default=Task.DETECT, choices=Task.all())
    p.add_argument("--split-strategy", default=SplitStrategy.RANDOM, choices=SplitStrategy.all(),dest='strategy')
    p.add_argument("--classes", nargs="+", default=None, help="类别白名单")
    p.add_argument("--train-rate", type=float, default=0.8)
    p.add_argument("--val-rate", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=1210)

    a = p.parse_args(argv)

    pipe = DatasetPipeline(
        a.dataset, a.fmt, task=a.task, train_rate=a.train_rate, val_rate=a.val_rate, classes=a.classes, split_strategy=a.strategy,
        random_state=a.seed,
    )
    try:
        res = pipe.run()
    except (FileNotFoundError,ValueError) as e:
        logger.error(f"处理失败：{e}")
        return  EXIT_DATA_ERR
    return EXIT_OK

if __name__ == "__main__":
    sys.exit(main())
