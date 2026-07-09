"""为一次确定的数据划分生成路径无关的内容指纹。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Tuple

from od_platform.data_pipeline.split.manifest import PairList, SplitManifest

_ALGORITHM = "sha256"
_FINGERPRINT_VERSION = 1
_SPLITS = ("train", "val", "test")
_CHUNK_SIZE = 1024 * 1024


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _update_field(digest, value: str) -> None:
    """用长度前缀消除多个字段直接拼接可能产生的歧义。"""
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, byteorder="big"))
    digest.update(encoded)


def _fingerprint_split(split_name: str, pairs: PairList) -> Tuple[str, int]:
    records = [
        (
            image_path.name,
            label_path.name,
            _hash_file(image_path),
            _hash_file(label_path),
        )
        for image_path, label_path in pairs
    ]
    records.sort()

    digest = hashlib.sha256()
    _update_field(digest, f"odp-dataset-fingerprint-v{_FINGERPRINT_VERSION}")
    _update_field(digest, split_name)
    for record in records:
        for field in record:
            _update_field(digest, field)
    return digest.hexdigest(), len(records)


def build_dataset_fingerprint(
    manifest: SplitManifest,
    classes: List[str],
) -> Dict[str, Any]:
    """计算类别语义、划分归属、文件名和文件内容的组合 SHA-256。"""
    split_fingerprints: Dict[str, Dict[str, object]] = {}
    for split_name in _SPLITS:
        value, samples = _fingerprint_split(
            split_name,
            getattr(manifest, split_name),
        )
        split_fingerprints[split_name] = {
            "value": value,
            "samples": samples,
        }

    digest = hashlib.sha256()
    _update_field(digest, f"odp-dataset-fingerprint-v{_FINGERPRINT_VERSION}")
    for class_index, class_name in enumerate(classes):
        _update_field(digest, str(class_index))
        _update_field(digest, class_name)
    for split_name in _SPLITS:
        split_data = split_fingerprints[split_name]
        _update_field(digest, split_name)
        _update_field(digest, str(split_data["samples"]))
        _update_field(digest, str(split_data["value"]))

    return {
        "algorithm": _ALGORITHM,
        "version": _FINGERPRINT_VERSION,
        "scope": "classes+split_assignment+file_names+file_contents",
        "value": digest.hexdigest(),
        "splits": split_fingerprints,
    }
