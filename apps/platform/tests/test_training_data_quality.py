from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from od_platform.training.data_quality import find_latest_validation_report


def _write_report(
    root: Path,
    run_id: str,
    *,
    yaml_path: Path,
    started_at: str,
) -> Path:
    report_path = root / run_id / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "yaml_path": str(yaml_path),
                "started_at": started_at,
            }
        ),
        encoding="utf-8",
    )
    return report_path


def test_finds_latest_report_for_exact_dataset(tmp_path: Path) -> None:
    dataset = tmp_path / "configs" / "fire.yaml"
    dataset.parent.mkdir()
    dataset.touch()
    runs = tmp_path / "runs"

    older = _write_report(
        runs,
        "older",
        yaml_path=dataset,
        started_at="2026-07-08T10:00:00+00:00",
    )
    newer = _write_report(
        runs,
        "newer",
        yaml_path=dataset,
        started_at="2026-07-09T10:00:00+00:00",
    )
    _write_report(
        runs,
        "other-dataset",
        yaml_path=tmp_path / "configs" / "smoke.yaml",
        started_at="2026-07-10T10:00:00+00:00",
    )

    assert older != newer
    assert (
        find_latest_validation_report(dataset, validation_runs_dir=runs)
        == newer
    )


def test_ignores_invalid_and_unmatched_reports(tmp_path: Path) -> None:
    dataset = tmp_path / "fire.yaml"
    dataset.touch()
    runs = tmp_path / "runs"
    invalid = runs / "invalid" / "report.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("{", encoding="utf-8")
    _write_report(
        runs,
        "other",
        yaml_path=tmp_path / "other.yaml",
        started_at="2026-07-09T10:00:00+00:00",
    )

    assert find_latest_validation_report(dataset, validation_runs_dir=runs) is None


def test_does_not_link_validation_created_after_training_started(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "fire.yaml"
    dataset.touch()
    runs = tmp_path / "runs"
    older = _write_report(
        runs,
        "older",
        yaml_path=dataset,
        started_at="2026-07-09T10:00:00+00:00",
    )
    _write_report(
        runs,
        "later",
        yaml_path=dataset,
        started_at="2026-07-09T12:00:00+00:00",
    )

    assert find_latest_validation_report(
        dataset,
        validation_runs_dir=runs,
        not_after=datetime.fromisoformat("2026-07-09T11:00:00+00:00"),
    ) == older
