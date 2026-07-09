"""检查存在标签文件、但不存在对应图片的孤儿标签。"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from od_platform.common.constants import LABEL_ORPHAN_WARN_RATIO
from od_platform.validate_dataset.registry import (
    CheckContext,
    CheckResult,
    CheckSeverity,
    check,
)

_PREVIEW_LIMIT = 20


def _resolve_image_dir(ctx: CheckContext, split: str) -> Optional[Path]:
    raw = ctx.snapshot.yaml_data.get(split)
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw)
    return path if path.is_absolute() else ctx.snapshot.data_root / path


def _label_dir_from_image_dir(image_dir: Path) -> Path:
    parts = list(image_dir.parts)
    for index in range(len(parts) - 1, -1, -1):
        if parts[index] == "images":
            parts[index] = "labels"
            return Path(*parts)
    return image_dir.parent / "labels"


@check("orphan_labels")
def validate_orphan_labels(ctx: CheckContext) -> CheckResult:
    orphan_per_split: Dict[str, List[str]] = {}
    total_labels = 0

    for split in ("train", "val", "test"):
        image_dir = _resolve_image_dir(ctx, split)
        if image_dir is None:
            continue
        label_dir = _label_dir_from_image_dir(image_dir)
        if not label_dir.is_dir():
            continue

        image_stems = {
            image.stem
            for image in ctx.snapshot.images_per_split.get(split, ())
        }
        labels = sorted(label_dir.glob("*.txt"))
        total_labels += len(labels)
        orphans = [str(label) for label in labels if label.stem not in image_stems]
        if orphans:
            orphan_per_split[split] = orphans

    total_orphans = sum(len(paths) for paths in orphan_per_split.values())
    orphan_ratio = total_orphans / max(total_labels, 1)
    if total_orphans == 0:
        severity = CheckSeverity.PASS
        summary = f"全部 {total_labels} 个标签都有对应图片"
    elif orphan_ratio >= LABEL_ORPHAN_WARN_RATIO:
        severity = CheckSeverity.WARNING
        summary = (
            f"孤儿标签比例 {orphan_ratio:.1%} ≥ "
            f"{LABEL_ORPHAN_WARN_RATIO:.0%} ({total_orphans}/{total_labels})"
        )
    else:
        severity = CheckSeverity.INFO
        summary = f"存在少量孤儿标签 ({total_orphans}/{total_labels} = {orphan_ratio:.2%})"

    return CheckResult(
        name="orphan_labels",
        severity=severity,
        summary=summary,
        details={
            "total_labels": total_labels,
            "total_orphans": total_orphans,
            "orphan_ratio": round(orphan_ratio, 4),
            "warn_at": LABEL_ORPHAN_WARN_RATIO,
            "orphan_per_split": {
                split: len(paths)
                for split, paths in orphan_per_split.items()
            },
            "orphan_files": orphan_per_split,
            "orphan_examples": {
                split: paths[:_PREVIEW_LIMIT]
                for split, paths in orphan_per_split.items()
            },
        },
    )
