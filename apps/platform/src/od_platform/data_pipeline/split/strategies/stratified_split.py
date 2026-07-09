"""按每张图片的代表类别进行分层划分。"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Dict, List

from od_platform.common.constants import SplitStrategy
from od_platform.data_pipeline.split.manifest import PairList, SplitManifest
from od_platform.data_pipeline.split.strategies._common import three_way_counts, validate_rates
from od_platform.data_pipeline.split.strategy_registry import SplitOptions, register_strategy

_BACKGROUND = "__background__"
_SPLITS = ("train", "val", "test")


@register_strategy(SplitStrategy.STRATIFIED, requires_labels=True)
def stratified_split(pairs: PairList, options: SplitOptions) -> SplitManifest:
    """以图片中全局最稀有的类别作为代表类别，再做容量受限的分层划分。"""
    test_rate = validate_rates(options.train_rate, options.val_rate)
    manifest = SplitManifest(
        train_rate=options.train_rate,
        val_rate=options.val_rate,
        test_rate=test_rate,
        random_state=options.random_state,
        strategy=SplitStrategy.STRATIFIED,
    )
    if not pairs:
        return manifest

    labels_per_image = options.labels_per_image or {}
    normalized: Dict[str, List[str]] = {
        pair[0].stem: sorted(set(labels_per_image.get(pair[0].stem, [])))
        for pair in pairs
    }
    frequencies = Counter(
        label
        for labels in normalized.values()
        for label in labels
    )

    strata: Dict[str, PairList] = defaultdict(list)
    for pair in sorted(pairs, key=lambda item: (item[0].name, str(item[0]))):
        labels = normalized[pair[0].stem]
        primary = min(labels, key=lambda label: (frequencies[label], label)) if labels else _BACKGROUND
        strata[primary].append(pair)

    counts = three_way_counts(len(pairs), options.train_rate, options.val_rate)
    capacities = dict(zip(_SPLITS, counts))
    assigned = {name: 0 for name in _SPLITS}
    rng = random.Random(options.random_state)

    # 稀有层优先，避免其在大层填满子集后无处可放。
    for label in sorted(strata, key=lambda name: (len(strata[name]), name)):
        items = list(strata[label])
        rng.shuffle(items)
        layer_targets = {
            name: len(items) * capacities[name] / len(pairs)
            for name in _SPLITS
        }
        layer_assigned = {name: 0 for name in _SPLITS}

        for pair in items:
            available = [name for name in _SPLITS if assigned[name] < capacities[name]]
            best_score = max(
                (
                    layer_targets[name] - layer_assigned[name],
                    capacities[name] - assigned[name],
                )
                for name in available
            )
            candidates = [
                name for name in available
                if (
                    layer_targets[name] - layer_assigned[name],
                    capacities[name] - assigned[name],
                ) == best_score
            ]
            destination = rng.choice(candidates)
            getattr(manifest, destination).append(pair)
            assigned[destination] += 1
            layer_assigned[destination] += 1

    return manifest
