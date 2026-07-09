"""Resolve data-validation artifacts associated with a training dataset."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from od_platform.common.paths import VALIDATION_RUNS_DIR


def _normalized_path(value: str | Path) -> str:
    """Return a comparison key that is stable for Windows path casing."""
    return str(Path(value).expanduser().resolve()).casefold()


def _report_timestamp(payload: dict[str, Any], report_path: Path) -> float:
    started_at = payload.get("started_at")
    if isinstance(started_at, str):
        try:
            return datetime.fromisoformat(started_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return report_path.stat().st_mtime


def find_latest_validation_report(
    dataset_yaml_path: str | Path,
    *,
    validation_runs_dir: Path = VALIDATION_RUNS_DIR,
    not_after: datetime | None = None,
) -> Path | None:
    """Find the newest matching validation report available by ``not_after``."""
    target = _normalized_path(dataset_yaml_path)
    matches: list[tuple[float, Path]] = []
    cutoff = not_after.timestamp() if not_after is not None else None

    if not validation_runs_dir.is_dir():
        return None

    for report_path in validation_runs_dir.glob("*/report.json"):
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            yaml_path = payload.get("yaml_path")
            if not isinstance(yaml_path, str) or _normalized_path(yaml_path) != target:
                continue
            timestamp = _report_timestamp(payload, report_path)
            if cutoff is None or timestamp <= cutoff:
                matches.append((timestamp, report_path))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue

    return max(matches, default=(0.0, None), key=lambda item: item[0])[1]
