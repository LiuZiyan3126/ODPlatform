from __future__ import annotations

from types import SimpleNamespace

from od_platform.common.result import TrainMetrics


def _results(**overrides):
    values = {
        "results_dict": {"metrics/mAP50(B)": 0.8},
        "speed": {},
        "names": {},
        "maps": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_explicit_task_is_used_when_ultralytics_result_has_no_task() -> None:
    metrics = TrainMetrics.from_yolo_results(_results(), task="detect")

    assert metrics.task == "detect"


def test_task_falls_back_to_metric_key_shape() -> None:
    metrics = TrainMetrics.from_yolo_results(_results())

    assert metrics.task == "detect"


def test_segment_metric_keys_are_detected() -> None:
    metrics = TrainMetrics.from_yolo_results(
        _results(results_dict={"metrics/mAP50(M)": 0.7})
    )

    assert metrics.task == "segment"
