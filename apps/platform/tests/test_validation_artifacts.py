from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from od_platform.data_pipeline.split.manifest import SplitManifest
from od_platform.data_pipeline.split.yaml_writer import write_dataset_yaml
from od_platform.validate_dataset.service import validate_dataset


def _image(path: Path, color: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 20), color=color).save(path)


def _dataset_with_issues(tmp_path: Path) -> Path:
    root = tmp_path / "processed"
    images = root / "train" / "images"
    labels = root / "train" / "labels"
    labels.mkdir(parents=True)

    good_image = images / "good.jpg"
    empty_image = images / "empty.jpg"
    geometry_image = images / "geometry.jpg"
    _image(good_image, "red")
    _image(empty_image, "green")
    _image(geometry_image, "blue")

    good_label = labels / "good.txt"
    empty_label = labels / "empty.txt"
    geometry_label = labels / "geometry.txt"
    good_label.write_text("0 0.5 0.5 0.4 0.4", encoding="utf-8")
    empty_label.write_text("", encoding="utf-8")
    geometry_label.write_text("0 0.5 0.5 0 0.4", encoding="utf-8")

    yaml_path = tmp_path / "dataset.yaml"
    write_dataset_yaml(
        yaml_path,
        dataset_root=root,
        classes=["object"],
        manifest=SplitManifest(train=[
            (good_image, good_label),
            (empty_image, empty_label),
            (geometry_image, geometry_label),
        ]),
        dataset_name="artifact-demo",
        source_format="yolo",
        task="detect",
    )

    (labels / "orphan.txt").write_text(
        "0 0.5 0.5 0.2 0.2",
        encoding="utf-8",
    )
    good_image.write_bytes(b"corrupt-image")
    return yaml_path


def _validate_without_device_probe(yaml_path: Path, run_dir: Path, run_id: str):
    with patch("od_platform.validate_dataset.service.log_device_info"):
        return validate_dataset(
            yaml_path,
            run_id=run_id,
            run_dir=run_dir,
            write_report=True,
        )


def test_validation_writes_csv_html_and_json(tmp_path: Path) -> None:
    yaml_path = _dataset_with_issues(tmp_path)
    run_dir = tmp_path / "validation-report"

    report = _validate_without_device_probe(
        yaml_path,
        run_dir,
        "test_run",
    )

    assert report.report_path.is_file()
    assert report.issues_csv_path.is_file()
    assert report.html_report_path.is_file()

    with report.issues_csv_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    issue_types = {row["issue_type"] for row in rows}
    assert {
        "empty_label",
        "orphan_label",
        "non_positive_box_size",
        "corrupt_image",
        "fingerprint_mismatch",
    } <= issue_types
    assert all(row["recommendation"] for row in rows)
    geometry_row = next(
        row for row in rows
        if row["issue_type"] == "non_positive_box_size"
    )
    assert geometry_row["line"] == "1"
    assert geometry_row["file"].endswith("geometry.txt")

    html = report.html_report_path.read_text(encoding="utf-8")
    assert "问题数据与修复建议" in html
    assert "non_positive_box_size" in html
    assert "重新标注目标框" in html

    json_report = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert json_report["artifacts"]["issues_csv"].endswith("issues.csv")
    assert json_report["artifacts"]["html"].endswith("report.html")


def test_clean_dataset_writes_header_only_csv(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    image_path = root / "train" / "images" / "clean.jpg"
    label_path = root / "train" / "labels" / "clean.txt"
    _image(image_path, "white")
    label_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.write_text("0 0.5 0.5 0.4 0.4", encoding="utf-8")
    yaml_path = tmp_path / "clean.yaml"
    write_dataset_yaml(
        yaml_path,
        dataset_root=root,
        classes=["object"],
        manifest=SplitManifest(train=[(image_path, label_path)]),
        dataset_name="clean-demo",
        source_format="yolo",
        task="detect",
    )

    report = _validate_without_device_probe(
        yaml_path,
        tmp_path / "clean-report",
        "clean_run",
    )

    with report.issues_csv_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows == []
    assert "没有发现需要记录的问题数据" in report.html_report_path.read_text(
        encoding="utf-8",
    )
