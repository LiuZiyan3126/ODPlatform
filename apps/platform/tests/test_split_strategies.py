from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from od_platform.common.constants import SplitStrategy
from od_platform.data_pipeline.split.manifest import PairList, SplitManifest
from od_platform.data_pipeline.split.split_service import split_pairs
from od_platform.data_pipeline.split.strategy_registry import list_strategies


def _pairs(count: int) -> PairList:
    return [
        (Path(f"image_{index:05d}.jpg"), Path(f"image_{index:05d}.txt"))
        for index in range(count)
    ]


def _all_pairs(manifest: SplitManifest) -> PairList:
    return manifest.train + manifest.val + manifest.test


def _membership(manifest: SplitManifest) -> dict[str, str]:
    result = {}
    for split_name in ("train", "val", "test"):
        for image_path, _ in getattr(manifest, split_name):
            result[image_path.name] = split_name
    return result


def _label_counts(
    pairs: PairList,
    labels_per_image: dict[str, list[str]],
) -> Counter:
    return Counter(
        label
        for image_path, _ in pairs
        for label in set(labels_per_image[image_path.stem])
    )


def test_registry_discovers_all_split_strategies() -> None:
    assert set(list_strategies()) == {
        SplitStrategy.RANDOM,
        SplitStrategy.STRATIFIED,
        SplitStrategy.STRATIFIED_MULTILABEL,
        SplitStrategy.HASH,
    }


def test_stratified_preserves_primary_class_distribution_and_exact_sizes() -> None:
    pairs = _pairs(30)
    labels = {
        image_path.stem: [f"class_{index // 10}"]
        for index, (image_path, _) in enumerate(pairs)
    }

    manifest = split_pairs(
        pairs,
        train_rate=0.8,
        val_rate=0.1,
        strategy=SplitStrategy.STRATIFIED,
        labels_per_image=labels,
        random_state=7,
    )

    assert manifest.summary() == {"train": 24, "val": 3, "test": 3, "total": 30}
    assert _label_counts(manifest.train, labels) == {
        "class_0": 8,
        "class_1": 8,
        "class_2": 8,
    }
    assert _label_counts(manifest.val, labels) == {
        "class_0": 1,
        "class_1": 1,
        "class_2": 1,
    }
    assert _label_counts(manifest.test, labels) == {
        "class_0": 1,
        "class_1": 1,
        "class_2": 1,
    }


def test_multilabel_stratification_balances_every_label() -> None:
    pairs = _pairs(12)
    labels = {}
    for index, (image_path, _) in enumerate(pairs):
        image_labels = []
        if 0 <= index <= 5:
            image_labels.append("a")
        if 3 <= index <= 8:
            image_labels.append("b")
        if 6 <= index <= 11:
            image_labels.append("c")
        labels[image_path.stem] = image_labels

    manifest = split_pairs(
        pairs,
        train_rate=0.5,
        val_rate=0.25,
        strategy=SplitStrategy.STRATIFIED_MULTILABEL,
        labels_per_image=labels,
        random_state=11,
    )

    assert manifest.summary() == {"train": 6, "val": 3, "test": 3, "total": 12}
    expected_rates = {"train": 0.5, "val": 0.25, "test": 0.25}
    for split_name, rate in expected_rates.items():
        counts = _label_counts(getattr(manifest, split_name), labels)
        for label in ("a", "b", "c"):
            assert abs(counts[label] - 6 * rate) <= 1


@pytest.mark.parametrize(
    "strategy",
    [SplitStrategy.STRATIFIED, SplitStrategy.STRATIFIED_MULTILABEL],
)
def test_label_based_strategies_are_reproducible(strategy: str) -> None:
    pairs = _pairs(20)
    labels = {
        image_path.stem: [f"class_{index % 3}", f"class_{(index + 1) % 4}"]
        for index, (image_path, _) in enumerate(pairs)
    }
    kwargs = {
        "strategy": strategy,
        "labels_per_image": labels,
        "random_state": 19,
    }

    first = split_pairs(pairs, **kwargs)
    second = split_pairs(list(reversed(pairs)), **kwargs)

    assert _membership(first) == _membership(second)
    assert len(set(_all_pairs(first))) == len(pairs)


def test_hash_split_is_stable_when_new_samples_are_added() -> None:
    original = _pairs(100)
    expanded = original + [
        (Path(f"new_{index:03d}.jpg"), Path(f"new_{index:03d}.txt"))
        for index in range(25)
    ]

    before = split_pairs(original, strategy=SplitStrategy.HASH, random_state=23)
    after = split_pairs(expanded, strategy=SplitStrategy.HASH, random_state=23)

    after_membership = _membership(after)
    assert _membership(before) == {
        name: after_membership[name]
        for name in _membership(before)
    }
    assert len(set(_all_pairs(after))) == len(expanded)


def test_hash_split_approximates_requested_rates_on_large_dataset() -> None:
    manifest = split_pairs(
        _pairs(5000),
        train_rate=0.8,
        val_rate=0.1,
        strategy=SplitStrategy.HASH,
        random_state=29,
    )

    assert abs(len(manifest.train) / 5000 - 0.8) < 0.03
    assert abs(len(manifest.val) / 5000 - 0.1) < 0.02
    assert abs(len(manifest.test) / 5000 - 0.1) < 0.02


@pytest.mark.parametrize(
    "strategy",
    [
        SplitStrategy.STRATIFIED,
        SplitStrategy.STRATIFIED_MULTILABEL,
        SplitStrategy.HASH,
    ],
)
def test_new_strategies_reject_invalid_rates(strategy: str) -> None:
    labels = {"image_00000": ["a"]}
    with pytest.raises(ValueError, match="比例越界"):
        split_pairs(
            _pairs(1),
            train_rate=0.9,
            val_rate=0.2,
            strategy=strategy,
            labels_per_image=labels,
        )
