"""重新计算数据指纹并与 dataset YAML 中记录的值比较。"""
from __future__ import annotations

import hmac
from typing import Any, Dict, List

from od_platform.data_pipeline.split.fingerprint import build_dataset_fingerprint
from od_platform.data_pipeline.split.manifest import SplitManifest
from od_platform.validate_dataset.registry import (
    CheckContext,
    CheckResult,
    CheckSeverity,
    check,
)


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


@check("fingerprint_integrity")
def validate_fingerprint_integrity(ctx: CheckContext) -> CheckResult:
    odp_meta = ctx.snapshot.yaml_data.get("odp_meta")
    stored = odp_meta.get("fingerprint") if isinstance(odp_meta, dict) else None
    if stored is None:
        return CheckResult(
            name="fingerprint_integrity",
            severity=CheckSeverity.INFO,
            summary="YAML 未记录数据指纹，跳过一致性验证",
            details={"reason": "fingerprint_missing"},
        )
    stored_splits = stored.get("splits") if isinstance(stored, dict) else None
    metadata_valid = (
        isinstance(stored, dict)
        and stored.get("algorithm") == "sha256"
        and stored.get("version") == 1
        and _is_sha256(stored.get("value"))
        and isinstance(stored_splits, dict)
        and all(
            isinstance(stored_splits.get(split), dict)
            and _is_sha256(stored_splits[split].get("value"))
            and isinstance(stored_splits[split].get("samples"), int)
            for split in ("train", "val", "test")
        )
    )
    if not metadata_valid:
        return CheckResult(
            name="fingerprint_integrity",
            severity=CheckSeverity.ERROR,
            summary="YAML 中的数据指纹结构或算法不受支持",
            details={"reason": "fingerprint_metadata_invalid"},
        )

    manifest = SplitManifest()
    missing_labels: List[str] = []
    for split in ("train", "val", "test"):
        images = ctx.snapshot.images_per_split.get(split, ())
        labels = ctx.snapshot.labels_per_split.get(split, ())
        pairs = []
        for image, label in zip(images, labels):
            if not label.is_file():
                missing_labels.append(str(label))
                continue
            pairs.append((image, label))
        setattr(manifest, split, pairs)

    if missing_labels:
        return CheckResult(
            name="fingerprint_integrity",
            severity=CheckSeverity.ERROR,
            summary=f"缺少 {len(missing_labels)} 个标签，无法验证数据指纹",
            details={
                "reason": "fingerprint_inputs_missing",
                "missing_labels": missing_labels[:20],
            },
        )

    current = build_dataset_fingerprint(
        manifest,
        list(ctx.snapshot.class_names),
    )
    stored_value = stored["value"]

    changed_splits: List[str] = []
    for split in ("train", "val", "test"):
        stored_split = stored_splits[split]
        current_value = current["splits"][split]["value"]
        if not hmac.compare_digest(stored_split["value"], current_value):
            changed_splits.append(split)

    if hmac.compare_digest(stored_value, str(current["value"])):
        return CheckResult(
            name="fingerprint_integrity",
            severity=CheckSeverity.PASS,
            summary="当前数据内容与 YAML 中记录的指纹一致",
            details={
                "fingerprint": current["value"],
                "algorithm": current["algorithm"],
            },
        )

    return CheckResult(
        name="fingerprint_integrity",
        severity=CheckSeverity.ERROR,
        summary="当前数据内容或划分与 YAML 中记录的指纹不一致",
        details={
            "reason": "fingerprint_mismatch",
            "stored": stored_value,
            "current": current["value"],
            "changed_splits": changed_splits,
        },
    )
