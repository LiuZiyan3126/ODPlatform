"""检查格式正确的 YOLO 标注是否具有有效几何形状。"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from od_platform.common.constants import Task
from od_platform.validate_dataset.registry import (
    CheckContext,
    CheckResult,
    CheckSeverity,
    check,
)

_PREVIEW_LIMIT = 20
_EPSILON = 1e-12
_BOUNDARY_TOLERANCE = 1e-6


def _detect_geometry(parts: List[str]) -> Optional[Tuple[str, str]]:
    if len(parts) != 5:
        return None
    try:
        cx, cy, width, height = (float(value) for value in parts[1:])
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return "non_positive_box_size", f"width={width}, height={height}"
    left, right = cx - width / 2, cx + width / 2
    top, bottom = cy - height / 2, cy + height / 2
    if (
        left < -_BOUNDARY_TOLERANCE
        or top < -_BOUNDARY_TOLERANCE
        or right > 1 + _BOUNDARY_TOLERANCE
        or bottom > 1 + _BOUNDARY_TOLERANCE
    ):
        return (
            "box_outside_image",
            f"bounds=({left:.6f}, {top:.6f}, {right:.6f}, {bottom:.6f})",
        )
    return None


def _segment_geometry(parts: List[str]) -> Optional[Tuple[str, str]]:
    if len(parts) < 7 or (len(parts) - 1) % 2:
        return None
    try:
        coords = [float(value) for value in parts[1:]]
    except ValueError:
        return None
    points = list(zip(coords[::2], coords[1::2]))
    twice_area = abs(sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    ))
    if twice_area <= _EPSILON:
        return "zero_area_polygon", "多边形面积为 0 或所有点共线"
    return None


@check("annotation_geometry")
def validate_annotation_geometry(ctx: CheckContext) -> CheckResult:
    errors: List[Dict[str, Any]] = []
    error_kinds: Counter = Counter()
    total_annotations = 0

    for split, labels in ctx.snapshot.labels_per_split.items():
        for label in labels:
            if not label.is_file():
                continue
            try:
                lines = label.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            for line_number, line in enumerate(lines, 1):
                parts = line.strip().split()
                if not parts:
                    continue
                total_annotations += 1
                if ctx.snapshot.task_type == Task.DETECT:
                    error = _detect_geometry(parts)
                else:
                    error = _segment_geometry(parts)
                if error is None:
                    continue
                kind, detail = error
                error_kinds[kind] += 1
                errors.append({
                    "split": split,
                    "label": str(label),
                    "line_no": line_number,
                    "kind": kind,
                    "detail": detail,
                })

    if not error_kinds:
        return CheckResult(
            name="annotation_geometry",
            severity=CheckSeverity.PASS,
            summary=f"全部 {total_annotations} 个标注的几何形状合法",
            details={"total_annotations": total_annotations},
        )

    total_errors = sum(error_kinds.values())
    return CheckResult(
        name="annotation_geometry",
        severity=CheckSeverity.ERROR,
        summary=f"{total_errors}/{total_annotations} 个标注的几何形状非法",
        details={
            "reason": "invalid_annotation_geometry",
            "total_annotations": total_annotations,
            "total_errors": total_errors,
            "error_kinds": dict(error_kinds),
            "errors": errors,
            "errors_preview": errors[:_PREVIEW_LIMIT],
        },
    )
