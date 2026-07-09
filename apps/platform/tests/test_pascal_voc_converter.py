from __future__ import annotations

from pathlib import Path

from od_platform.data_pipeline.convert.converters.pascal_voc import (
    _voc_box_to_yolo,
    convert_voc,
)
from od_platform.data_pipeline.convert.registry import ConvertOptions


def _write_voc(
    path: Path,
    *,
    width: int,
    height: int,
    boxes: list[tuple[str, int, int, int, int]],
) -> None:
    objects = "".join(
        (
            "<object>"
            f"<name>{name}</name>"
            "<bndbox>"
            f"<xmin>{xmin}</xmin><ymin>{ymin}</ymin>"
            f"<xmax>{xmax}</xmax><ymax>{ymax}</ymax>"
            "</bndbox>"
            "</object>"
        )
        for name, xmin, ymin, xmax, ymax in boxes
    )
    path.write_text(
        (
            "<annotation>"
            f"<size><width>{width}</width><height>{height}</height></size>"
            f"{objects}"
            "</annotation>"
        ),
        encoding="utf-8",
    )


def test_voc_one_based_border_maps_inside_image() -> None:
    converted = _voc_box_to_yolo(
        xmin=205,
        ymin=405,
        xmax=641,
        ymax=501,
        image_width=640,
        image_height=640,
    )

    assert converted is not None
    cx, cy, width, height = converted
    assert abs((cx - width / 2) - 204 / 640) < 1e-12
    assert abs((cx + width / 2) - 1.0) < 1e-12
    assert abs((cy - height / 2) - 404 / 640) < 1e-12
    assert abs((cy + height / 2) - 500 / 640) < 1e-12


def test_voc_box_is_clipped_and_degenerate_box_is_rejected() -> None:
    clipped = _voc_box_to_yolo(
        xmin=-10,
        ymin=-20,
        xmax=700,
        ymax=800,
        image_width=640,
        image_height=640,
    )
    assert clipped == (0.5, 0.5, 1.0, 1.0)

    assert _voc_box_to_yolo(
        xmin=641,
        ymin=10,
        xmax=700,
        ymax=20,
        image_width=640,
        image_height=640,
    ) is None


def test_convert_voc_writes_only_valid_clipped_boxes(tmp_path: Path) -> None:
    input_dir = tmp_path / "xml"
    output_dir = tmp_path / "labels"
    input_dir.mkdir()
    _write_voc(
        input_dir / "sample.xml",
        width=640,
        height=640,
        boxes=[
            ("fire", 205, 405, 641, 501),
            ("fire", 641, 10, 700, 20),
        ],
    )

    classes = convert_voc(input_dir, output_dir, ConvertOptions(task="detect"))
    lines = (output_dir / "sample.txt").read_text(encoding="utf-8").splitlines()

    assert classes == ["fire"]
    assert len(lines) == 1
    parts = lines[0].split()
    assert parts[0] == "0"
    cx, cy, width, height = map(float, parts[1:])
    assert cx + width / 2 <= 1.0
    assert cy + height / 2 <= 1.0
    assert width > 0
    assert height > 0
