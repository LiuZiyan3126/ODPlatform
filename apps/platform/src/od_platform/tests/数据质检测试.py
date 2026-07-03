#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :数据质检测试.py
# @Time      :2026/7/2 11:10:06
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
from pathlib import Path
from od_platform.validate_dataset.registry import CheckContext,list_check_names
from od_platform.validate_dataset.service import run_all_checks
from od_platform.common.paths import LOGGING_DIR
from od_platform.common.logging_utils import get_logger
from od_platform.validate_dataset.snapshot import build_snapshot
from od_platform.validate_dataset.report import ValidationReport
from od_platform.validate_dataset.render import render_to_logger
import time
from datetime import datetime, timezone

logger = get_logger(
    base_path=LOGGING_DIR,
    log_type="数据质检测试",
    temp_log=False,
)

print(f"已经注册的check: {list_check_names()}")

yaml_path = Path(r"C:\Users\Lenovo\Desktop\ODPlatform\apps\platform\configs\datasets\rsod.yaml")
snap = build_snapshot(yaml_path, task_type='detect')
print(f"数据集： {yaml_path.name}")
print(f"task: {snap.task_type}")
print(f"nc: {snap.nc}")
print(f"names: {snap.class_names}")

t0 = time.perf_counter()
started = datetime.now(timezone.utc).isoformat()
ctx = CheckContext(yaml_path=yaml_path, snapshot=snap)
results = run_all_checks(ctx)

report = ValidationReport(
    run_id="20260702_111006",
    yaml_path=yaml_path,
    snapshot=snap,
    results=results,
    duration_seconds=time.perf_counter() - t0,
    started_at_iso=started
)

render_to_logger(report, logger)
for r in results:
    print(r.severity, r.name, '-', r.summary)
    if r.details.get('problems'):
        for p in r.details['problems']:
            print(f"  - {p}")
