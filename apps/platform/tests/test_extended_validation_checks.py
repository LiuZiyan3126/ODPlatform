from __future__ import annotations

from pathlib import Path

from PIL import Image

from od_platform.data_pipeline.split.manifest import SplitManifest
from od_platform.data_pipeline.split.yaml_writer import write_dataset_yaml
from od_platform.validate_dataset.registry import CheckContext, CheckSeverity, list_check_names
from od_platform.validate_dataset.service import run_all_checks
from od_platform.validate_dataset.snapshot import build_snapshot


def _create_image(path: Path, color: str = "red") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color=color).save(path)


def _build_dataset(tmp_path: Path) -> tuple[Path, Path, Path]:
    dataset_root = tmp_path / "processed"
    image_path = dataset_root / "train" / "images" / "sample.jpg"
    label_path = dataset_root / "train" / "labels" / "sample.txt"
    _create_image(image_path)
    label_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.write_text("0 0.5 0.5 0.5 0.5", encoding="utf-8")

    yaml_path = tmp_path / "dataset.yaml"
    write_dataset_yaml(
        yaml_path,
        dataset_root=dataset_root,
        classes=["fire"],
        manifest=SplitManifest(train=[(image_path, label_path)]),
        dataset_name="demo",
        source_format="yolo",
        task="detect",
    )
    return yaml_path, image_path, label_path


def _results_by_name(yaml_path: Path):
    snapshot = build_snapshot(yaml_path)
    results = run_all_checks(CheckContext(yaml_path=yaml_path, snapshot=snapshot))
    return {result.name: result for result in results}


def test_registry_discovers_extended_checks() -> None:
    names = set(list_check_names())
    assert {
        "orphan_labels",
        "empty_labels",
        "image_integrity",
        "annotation_geometry",
        "fingerprint_integrity",
    } <= names


def test_clean_dataset_passes_extended_checks(tmp_path: Path) -> None:
    yaml_path, _, _ = _build_dataset(tmp_path)
    results = _results_by_name(yaml_path)

    for name in (
        "orphan_labels",
        "empty_labels",
        "image_integrity",
        "annotation_geometry",
        "fingerprint_integrity",
    ):
        assert results[name].severity == CheckSeverity.PASS


def test_orphan_and_empty_labels_are_reported(tmp_path: Path) -> None:
    yaml_path, _, label_path = _build_dataset(tmp_path)
    label_path.write_text("", encoding="utf-8")
    orphan_path = label_path.parent / "orphan.txt"
    orphan_path.write_text("0 0.5 0.5 0.2 0.2", encoding="utf-8")

    results = _results_by_name(yaml_path)

    assert results["empty_labels"].severity == CheckSeverity.WARNING
    assert results["empty_labels"].details["total_empty"] == 1
    assert results["orphan_labels"].severity == CheckSeverity.WARNING
    assert results["orphan_labels"].details["total_orphans"] == 1
    assert results["fingerprint_integrity"].severity == CheckSeverity.ERROR


def test_corrupt_image_and_invalid_geometry_are_errors(tmp_path: Path) -> None:
    yaml_path, image_path, label_path = _build_dataset(tmp_path)
    image_path.write_bytes(b"not-an-image")
    label_path.write_text("0 0.5 0.5 0 0.5", encoding="utf-8")

    results = _results_by_name(yaml_path)

    assert results["image_integrity"].severity == CheckSeverity.ERROR
    assert results["annotation_geometry"].severity == CheckSeverity.ERROR
    assert (
        results["annotation_geometry"].details["error_kinds"]["non_positive_box_size"]
        == 1
    )
    assert results["fingerprint_integrity"].severity == CheckSeverity.ERROR


def test_segment_task_is_loaded_from_odp_metadata(tmp_path: Path) -> None:
    dataset_root = tmp_path / "processed"
    image_path = dataset_root / "train" / "images" / "segment.jpg"
    label_path = dataset_root / "train" / "labels" / "segment.txt"
    _create_image(image_path)
    label_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.write_text(
        "0 0.1 0.1 0.9 0.1 0.9 0.9 0.1 0.9",
        encoding="utf-8",
    )
    yaml_path = tmp_path / "segment.yaml"
    write_dataset_yaml(
        yaml_path,
        dataset_root=dataset_root,
        classes=["object"],
        manifest=SplitManifest(train=[(image_path, label_path)]),
        dataset_name="segment-demo",
        source_format="yolo",
        task="segment",
    )

    snapshot = build_snapshot(yaml_path)
    results = _results_by_name(yaml_path)

    assert snapshot.task_type == "segment"
    assert results["label_format"].severity == CheckSeverity.PASS
    assert results["annotation_geometry"].severity == CheckSeverity.PASS
