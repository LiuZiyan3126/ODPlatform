from __future__ import annotations

import logging
from pathlib import Path
from typing import List
import yaml

from od_platform.data_pipeline.split.fingerprint import build_dataset_fingerprint
from od_platform.data_pipeline.split.manifest import SplitManifest

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 2  # 用于记录odp-meta的结构版本


def write_dataset_yaml(
    yaml_path: Path,
    *,
    dataset_root: Path,
    classes: List[str],
    manifest: SplitManifest,
    dataset_name: str,
    source_format: str,
    task: str,
    ) -> None:
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    fingerprint = build_dataset_fingerprint(manifest, classes)

    doc = {
        "path": str(dataset_root),
        "train": "train/images",
        "val": "val/images",
        "test": "test/images",
        "names": {i: name for i, name in enumerate(classes)},
        "nc": len(classes),
        "odp_meta": {
            "schema_version": _SCHEMA_VERSION,
            "dataset_name": dataset_name,
            "source_format": source_format,
            "task": task,
            "fingerprint": fingerprint,
            "split": {
                "strategy": manifest.strategy,
                "random_state": manifest.random_state,
                "rates": {
                    "train": round(manifest.train_rate, 4),
                    "val": round(manifest.val_rate, 4),
                    "test": round(manifest.test_rate, 4),
                },
                "counts": manifest.summary(),
            },
        },
    }

    yaml_path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),encoding="utf-8")
    logger.info(f"已经写入 {yaml_path.name}")
