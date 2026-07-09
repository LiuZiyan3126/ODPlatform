"""统计已配对标签中的空文件比例。"""
from __future__ import annotations

from typing import Dict, List

from od_platform.common.constants import EMPTY_LABEL_WARN_RATIO
from od_platform.validate_dataset.registry import (
    CheckContext,
    CheckResult,
    CheckSeverity,
    check,
)

_PREVIEW_LIMIT = 20


@check("empty_labels")
def validate_empty_labels(ctx: CheckContext) -> CheckResult:
    empty_per_split: Dict[str, List[str]] = {}
    total_existing = 0

    for split, labels in ctx.snapshot.labels_per_split.items():
        empty: List[str] = []
        for label in labels:
            if not label.is_file():
                continue
            total_existing += 1
            try:
                is_empty = not label.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                continue
            if is_empty:
                empty.append(str(label))
        if empty:
            empty_per_split[split] = empty

    total_empty = sum(len(paths) for paths in empty_per_split.values())
    empty_ratio = total_empty / max(total_existing, 1)
    if total_empty == 0:
        severity = CheckSeverity.PASS
        summary = f"全部 {total_existing} 个已配对标签均包含目标"
    elif empty_ratio >= EMPTY_LABEL_WARN_RATIO:
        severity = CheckSeverity.WARNING
        summary = (
            f"空标签比例 {empty_ratio:.1%} ≥ "
            f"{EMPTY_LABEL_WARN_RATIO:.0%} ({total_empty}/{total_existing})"
        )
    else:
        severity = CheckSeverity.INFO
        summary = f"存在少量空标签 ({total_empty}/{total_existing} = {empty_ratio:.2%})"

    return CheckResult(
        name="empty_labels",
        severity=severity,
        summary=summary,
        details={
            "total_existing_labels": total_existing,
            "total_empty": total_empty,
            "empty_ratio": round(empty_ratio, 4),
            "warn_at": EMPTY_LABEL_WARN_RATIO,
            "empty_per_split": {
                split: len(paths)
                for split, paths in empty_per_split.items()
            },
            "empty_files": empty_per_split,
            "empty_examples": {
                split: paths[:_PREVIEW_LIMIT]
                for split, paths in empty_per_split.items()
            },
        },
    )
