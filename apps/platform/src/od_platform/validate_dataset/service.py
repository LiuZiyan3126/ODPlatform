#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :service.py
# @Time      :2026/7/2 10:15:37
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :validate_dataset 调度层 要跑所有的检查
from __future__ import  annotations

import logging
from typing import List

from od_platform.validate_dataset.registry import (CheckContext,CheckEntry, CheckResult, CheckSeverity, get_all_checks)
from od_platform.common.performance_utils import time_it

import json
import time
from typing import Optional
from pathlib import Path
from datetime import datetime, timezone
from od_platform.common.paths import  validation_run_dir
from od_platform.common.system_utils import log_device_info
from od_platform.validate_dataset.artifacts import (
    collect_issue_records,
    write_html_report,
    write_issues_csv,
)
from od_platform.validate_dataset.report import ValidationReport
from od_platform.validate_dataset.snapshot import  build_snapshot


logger = logging.getLogger(__name__)

@time_it(name="所有检测耗时总计",logger_instance=logger, iterations=1)
def run_all_checks(ctx: CheckContext) -> List[CheckResult]:
    """跑全部注册的check, 收集结果"""
    entries = get_all_checks()  # 拿到所有的检查
    logger.info(f"开始执行 {len(entries)} 个 checks")
    results: List[CheckResult] = []

    for entry in entries:
        result = _safe_run_on(entry, ctx)  # 执行一个检测
        _log_check_result(result)  # 检测的结果日志输出下
        results.append(result)  # 收集检测的结果
    _log_summary(results)
    return results

@time_it(name=lambda entry, ctx: f"检查:【{entry.name}】", logger_instance=logger, iterations=1)
def _safe_run_on(entry: CheckEntry, ctx: CheckContext) -> CheckResult:
    """跑单个check,  异常做好包装"""
    try:
        return entry.func(ctx)  # 执行一个check
    except Exception as e:
        logger.exception(f"check {entry.name} 出现异常, 已捕获未ERROR 级结果")
        return CheckResult(
            name = entry.name,
            severity=CheckSeverity.ERROR,
            summary=f"check {entry.name} 出现异常, {type(e).__name__}:{e}",
            details={"exception_type": type(e).__name__,
                    "exception_msg": str(e)}
        )


def _log_check_result(r: CheckResult) -> None:
    log_method = {
        CheckSeverity.ERROR: logger.error,
        CheckSeverity.WARNING: logger.warning,
        CheckSeverity.INFO: logger.info,
        CheckSeverity.PASS: logger.debug,
    }.get(r.severity, logger.info)
    log_method(f"[{r.severity:7s}] {r.name}: {r.summary}")

def _log_summary(results: List[CheckResult]) -> None:
    counts = {}
    for r in results:
        counts[r.severity] = counts.get(r.severity, 0) + 1
        parts = [f"{n} {s}" for s,n in counts.items()]
    logger.info(f"检查完成, 结果如下：{' / '.join(parts)}")



def validate_dataset(
    yaml_path:    Path,
    task_type:    Optional[str] = None,
    run_id:       Optional[str] = None,
    run_dir:      Optional[Path] = None,
    write_report: bool = True,
) -> ValidationReport:
    """端到端验证: 构造 snapshot → 跑 check → 包装 report → 可选写盘。

    Args:
        yaml_path:    数据集 yaml 文件路径
        task_type:    'detect' / 'segment' / None (None → 读 yaml.task, 再不行 detect)
        run_id:       手动指定运行 ID; None 表示自动用时间戳
        run_dir:      手动指定运行目录; None 表示用 validation_run_dir(run_id)
        write_report: 是否写 JSON、CSV 和 HTML 报告到 run_dir

    Returns:
        ValidationReport（可通过三个 path 属性取得报告产物位置）
    """
    # ---- 解析 run_id / run_dir ----
    resolved_run_id  = run_id  or datetime.now().strftime("%Y%m%d_%H%M%S")
    resolved_run_dir = run_dir or (validation_run_dir(resolved_run_id) if write_report else None)

    if write_report and resolved_run_dir is not None:
        resolved_run_dir.mkdir(parents=True, exist_ok=True)

    # ---- 跑核心流程 ----
    t0 = time.perf_counter()
    started_iso = datetime.now(timezone.utc).isoformat()

    log_device_info(logger)   # 端到端入口打一次设备信息, 让"慢"可归因
    snapshot = build_snapshot(yaml_path=yaml_path, task_type=task_type)
    ctx      = CheckContext(yaml_path=yaml_path, snapshot=snapshot)
    results  = run_all_checks(ctx)

    duration = time.perf_counter() - t0

    # ---- 包装 ValidationReport ----
    report = ValidationReport(
        run_id=resolved_run_id,
        yaml_path=yaml_path,
        snapshot=snapshot,
        results=results,
        duration_seconds=duration,
        started_at_iso=started_iso,
        run_dir=resolved_run_dir,
    )

    # ---- 写 JSON + 问题 CSV + HTML 报告 ----
    if write_report and resolved_run_dir is not None:
        issue_records = collect_issue_records(report.results)
        report.report_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        write_issues_csv(issue_records, report.issues_csv_path)
        write_html_report(report, issue_records, report.html_report_path)
        logger.info(
            "质检报告已生成: JSON=%s, CSV=%s, HTML=%s",
            report.report_path,
            report.issues_csv_path,
            report.html_report_path,
        )

    return report
