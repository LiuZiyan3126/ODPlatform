"""面向目标检测数据的迭代式多标签分层划分。"""
from __future__ import annotations

import random
from collections import Counter
from typing import List, Tuple

from od_platform.common.constants import SplitStrategy
from od_platform.data_pipeline.split.manifest import PairList, SplitManifest
from od_platform.data_pipeline.split.strategies._common import three_way_counts, validate_rates
from od_platform.data_pipeline.split.strategy_registry import SplitOptions, register_strategy

_BACKGROUND = "__background__"
_SPLITS = ("train", "val", "test")


@register_strategy(SplitStrategy.STRATIFIED_MULTILABEL, requires_labels=True)
def stratified_multilabel_split(pairs: PairList, options: SplitOptions) -> SplitManifest:
    """稀有标签优先，在满足集合容量的同时逼近每个类别的目标分布。"""
    test_rate = validate_rates(options.train_rate, options.val_rate)
    manifest = SplitManifest(
        train_rate=options.train_rate,
        val_rate=options.val_rate,
        test_rate=test_rate,
        random_state=options.random_state,
        strategy=SplitStrategy.STRATIFIED_MULTILABEL,
    )
    if not pairs:
        return manifest

    labels_per_image = options.labels_per_image or {}
    ordered_pairs = sorted(pairs, key=lambda item: (item[0].name, str(item[0])))
    sample_labels: List[Tuple[str, ...]] = []
    for pair in ordered_pairs:
        labels = tuple(sorted(set(labels_per_image.get(pair[0].stem, []))))
        sample_labels.append(labels or (_BACKGROUND,))

    counts = three_way_counts(len(pairs), options.train_rate, options.val_rate)
    capacities = dict(zip(_SPLITS, counts))
    remaining_capacity = dict(capacities)
    total_per_label = Counter(label for labels in sample_labels for label in labels)
    targets = {
        label: {
            name: total * capacities[name] / len(pairs)
            for name in _SPLITS
        }
        for label, total in total_per_label.items()
    }
    assigned_per_label = {
        label: {name: 0 for name in _SPLITS}
        for label in total_per_label
    }

    rng = random.Random(options.random_state)
    tie_order = list(range(len(ordered_pairs)))
    rng.shuffle(tie_order)
    tie_rank = {sample_index: rank for rank, sample_index in enumerate(tie_order)}
    unassigned = set(range(len(ordered_pairs)))

    while unassigned:
        remaining_per_label = Counter(
            label
            for index in unassigned
            for label in sample_labels[index]
        )
        rarest_label = min(
            remaining_per_label,
            key=lambda label: (remaining_per_label[label], label),
        )
        candidates = sorted(
            (index for index in unassigned if rarest_label in sample_labels[index]),
            key=lambda index: tie_rank[index],
        )

        for index in candidates:
            if index not in unassigned:
                continue
            available = [name for name in _SPLITS if remaining_capacity[name] > 0]
            labels = sample_labels[index]

            def score(name: str):
                rarest_deficit = (
                    targets[rarest_label][name]
                    - assigned_per_label[rarest_label][name]
                )
                all_deficits = sum(
                    targets[label][name] - assigned_per_label[label][name]
                    for label in labels
                )
                return rarest_deficit, all_deficits, remaining_capacity[name]

            best_score = max(score(name) for name in available)
            destinations = [name for name in available if score(name) == best_score]
            destination = rng.choice(destinations)

            getattr(manifest, destination).append(ordered_pairs[index])
            remaining_capacity[destination] -= 1
            for label in labels:
                assigned_per_label[label][destination] += 1
            unassigned.remove(index)

    return manifest
