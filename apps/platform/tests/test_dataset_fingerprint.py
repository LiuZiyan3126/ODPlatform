from __future__ import annotations

from pathlib import Path

import yaml

from od_platform.data_pipeline.split.fingerprint import build_dataset_fingerprint
from od_platform.data_pipeline.split.manifest import SplitManifest
from od_platform.data_pipeline.split.yaml_writer import write_dataset_yaml


def _pair(root: Path, name: str, image: bytes, label: str):
    image_path = root / f"{name}.jpg"
    label_path = root / f"{name}.txt"
    image_path.write_bytes(image)
    label_path.write_text(label, encoding="utf-8")
    return image_path, label_path


def test_fingerprint_is_path_independent(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first_pair = _pair(first_root, "sample", b"image-content", "0 0.5 0.5 1 1")
    second_pair = _pair(second_root, "sample", b"image-content", "0 0.5 0.5 1 1")

    first = build_dataset_fingerprint(
        SplitManifest(train=[first_pair]),
        ["fire"],
    )
    second = build_dataset_fingerprint(
        SplitManifest(train=[second_pair]),
        ["fire"],
    )

    assert first == second


def test_fingerprint_changes_with_content_split_or_classes(tmp_path: Path) -> None:
    first_pair = _pair(tmp_path, "first", b"first-image", "0 0.5 0.5 1 1")
    second_pair = _pair(tmp_path, "second", b"second-image", "1 0.5 0.5 1 1")
    manifest = SplitManifest(train=[first_pair], val=[second_pair])
    baseline = build_dataset_fingerprint(manifest, ["fire", "smoke"])["value"]

    second_pair[1].write_text("1 0.4 0.4 0.8 0.8", encoding="utf-8")
    changed_content = build_dataset_fingerprint(
        manifest,
        ["fire", "smoke"],
    )["value"]
    second_pair[1].write_text("1 0.5 0.5 1 1", encoding="utf-8")

    changed_split = build_dataset_fingerprint(
        SplitManifest(train=[first_pair, second_pair]),
        ["fire", "smoke"],
    )["value"]
    changed_classes = build_dataset_fingerprint(
        manifest,
        ["smoke", "fire"],
    )["value"]

    assert len({baseline, changed_content, changed_split, changed_classes}) == 4


def test_yaml_contains_dataset_and_split_fingerprints(tmp_path: Path) -> None:
    train_pair = _pair(tmp_path, "train_sample", b"train-image", "0 0.5 0.5 1 1")
    val_pair = _pair(tmp_path, "val_sample", b"val-image", "")
    manifest = SplitManifest(train=[train_pair], val=[val_pair])
    yaml_path = tmp_path / "dataset.yaml"

    write_dataset_yaml(
        yaml_path,
        dataset_root=tmp_path / "processed",
        classes=["fire"],
        manifest=manifest,
        dataset_name="demo",
        source_format="yolo",
        task="detect",
    )
    document = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    fingerprint = document["odp_meta"]["fingerprint"]

    assert document["odp_meta"]["schema_version"] == 2
    assert fingerprint["algorithm"] == "sha256"
    assert len(fingerprint["value"]) == 64
    assert fingerprint["splits"]["train"]["samples"] == 1
    assert fingerprint["splits"]["val"]["samples"] == 1
    assert fingerprint["splits"]["test"]["samples"] == 0
