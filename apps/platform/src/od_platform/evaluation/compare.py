#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""多模型对比 — 同数据集不同模型的评估指标对比.

MVP: 只支持同一份 test 数据上多个模型的对比。
输出：终端彩色表格 + Markdown 报告。
"""
from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from od_platform.common.paths import RUNS_DIR
from od_platform.common.string_utils import pad_to_width

logger = logging.getLogger(__name__)

# 终端 ANSI 颜色
_GREEN = "\033[92m"
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _key_metrics(metrics: dict[str, float]) -> dict[str, float]:
    """从 metrics dict 中提取关键的对比指标."""
    keys_of_interest = [
        "metrics/mAP50(B)",
        "metrics/mAP50-95(B)",
        "metrics/precision(B)",
        "metrics/recall(B)",
        "fitness",
    ]
    result: dict[str, float] = {}
    for k in keys_of_interest:
        if k in metrics:
            result[k] = metrics[k]
    return result


def _short_label(key: str) -> str:
    """把 ultralytics key 转成短标签."""
    mapping = {
        "metrics/mAP50(B)": "mAP@50",
        "metrics/mAP50-95(B)": "mAP@50-95",
        "metrics/precision(B)": "Precision",
        "metrics/recall(B)": "Recall",
        "fitness": "Fitness",
    }
    return mapping.get(key, key)


def _best_in_column(
    col_key: str,
    all_metrics: list[dict[str, float]],
) -> set[int]:
    """找出某列的最大值所在的 row 索引集合（可能有并列第一）."""
    vals = []
    for m in all_metrics:
        v = m.get(col_key, math.nan)
        vals.append(v if not math.isnan(v) else -math.inf)
    if not vals:
        return set()
    best_val = max(vals)
    return {i for i, v in enumerate(vals) if v == best_val}


def _format_value(value: float, is_best: bool) -> str:
    """格式化单个指标值，最优值加 ▲ 标记."""
    if math.isnan(value):
        return "N/A"
    s = f"{value:.4f}"
    if is_best:
        s = f"{_GREEN}{s} ▲{_RESET}"
    return s


def _determine_col_widths(
    labels: list[str],
    model_names: list[str],
    all_metrics: list[dict[str, float]],
) -> tuple[list[int], list[str]]:
    """计算终端表格列宽."""
    # 模型名称列宽
    model_width = max(
        max(len(n) for n in model_names) if model_names else 10,
        len("Model"),
    ) + 2
    # 指标列宽
    metric_widths = []
    for label in labels:
        w = len(label) + 4  # 精度 4 位 + 小数点 + 标记
        metric_widths.append(w)
    return [model_width] + metric_widths, ["Model"] + labels


def _print_terminal_table(
    model_names: list[str],
    all_metrics: list[dict[str, float]],
) -> None:
    """终端彩色对比表格."""
    if not all_metrics:
        logger.warning("无评估数据可供对比")
        return

    labels = list(all_metrics[0].keys())
    short_labels = [_short_label(k) for k in labels]
    best_indices = {k: _best_in_column(k, all_metrics) for k in labels}

    widths, headers = _determine_col_widths(short_labels, model_names, all_metrics)

    # 表头
    header_row = "│ " + " │ ".join(
        pad_to_width(h, w) for h, w in zip(headers, widths)
    ) + " │"

    sep = "├" + "┼".join("─" * (w + 2) for w in widths) + "┤"
    top = "┌" + "┬".join("─" * (w + 2) for w in widths) + "┐"
    bottom = "└" + "┴".join("─" * (w + 2) for w in widths) + "┘"

    print(top)
    print(header_row)
    print(sep)

    for i, (name, metrics) in enumerate(zip(model_names, all_metrics)):
        cols = [name]
        for j, k in enumerate(labels):
            val = metrics.get(k, math.nan)
            is_best = i in best_indices.get(k, set())
            cols.append(_format_value(val, is_best))
        row = "│ " + " │ ".join(
            pad_to_width(c, w) for c, w in zip(cols, widths)
        ) + " │"
        print(row)

    print(bottom)
    print(f"标注 {_GREEN}{{*}}{_RESET} 为各列最优值")


def _generate_compare_report_md(
    model_names: list[str],
    all_metrics: list[dict[str, float]],
    data_name: str,
    split: str,
    author: str,
    compare_dir: Path,
) -> Path:
    """生成多模型对比的 Markdown 报告."""
    if not all_metrics:
        report_path = compare_dir / "report.md"
        report_path.write_text("# 模型对比报告\n\n无有效评估数据可供对比。\n", encoding="utf-8")
        return report_path

    labels = list(all_metrics[0].keys())
    short_labels = [_short_label(k) for k in labels]
    best_indices = {k: _best_in_column(k, all_metrics) for k in labels}

    # Markdown 表格
    header = "| Model | " + " | ".join(short_labels) + " |"
    sep = "|---" * (len(short_labels) + 1) + "|"

    rows = []
    for i, (name, metrics) in enumerate(zip(model_names, all_metrics)):
        cols = [name]
        for k in labels:
            val = metrics.get(k, math.nan)
            if math.isnan(val):
                cols.append("N/A")
            else:
                s = f"{val:.4f}"
                if i in best_indices.get(k, set()):
                    s = f"**{s}** *"
                cols.append(s)
        rows.append("| " + " | ".join(cols) + " |")

    table = "\n".join([header, sep] + rows)

    content = f"""\
# 模型对比报告

## 基本信息

| 字段 | 值 |
|------|-----|
| 对比人 | {author or "-"} |
| 对比时间 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |
| 数据集 | {data_name} |
| 评估分片 | {split} |

## 模型对比

{table}

> 加粗且带 * 标记的为该列最优值。

## 结论

| 模型 | 关键优势 |
|------|----------|
"""
    # 自动生成结论：每个模型在哪些指标上最优
    for i, name in enumerate(model_names):
        advantages = []
        for k in labels:
            if i in best_indices.get(k, set()):
                advantages.append(_short_label(k))
        if advantages:
            content += f"| {name} | {', '.join(advantages)} 最优 |\n"
        else:
            content += f"| {name} | - |\n"

    report_path = compare_dir / "report.md"
    report_path.write_text(content, encoding="utf-8")
    return report_path


def compare_models(
    eval_results: list[dict[str, Any]],
    *,
    data_name: str = "",
    split: str = "test",
    author: str = "",
) -> Path:
    """对比多个模型的评估结果。

    Args:
        eval_results: 每个元素是 {"model_name": str, "metrics": dict, ...}
        data_name: 数据集名称。
        split: 评估分片。
        author: 对比人。

    Returns:
        对比报告路径。
    """
    model_names = [r.get("model_name", f"model_{i}") for i, r in enumerate(eval_results)]
    all_metrics = [
        _key_metrics(r.get("metrics", {}))
        for r in eval_results
    ]

    # 终端输出
    print(f"\n{_BOLD}模型对比报告 — 数据集: {data_name} ({split} split){_RESET}\n")
    _print_terminal_table(model_names, all_metrics)

    # Markdown 报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    compare_dir = RUNS_DIR / "compare" / f"compare_{timestamp}"
    compare_dir.mkdir(parents=True, exist_ok=True)

    report_path = _generate_compare_report_md(
        model_names, all_metrics, data_name, split, author, compare_dir,
    )

    logger.info(f"对比报告: {report_path}")
    print(f"\n对比报告已保存: {report_path}")

    return report_path
