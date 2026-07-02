from __future__ import annotations
import random

from od_platform.common.constants import SplitStrategy
from od_platform.data_pipeline.split import manifest
from od_platform.data_pipeline.split.manifest import PairList, SplitManifest
from od_platform.data_pipeline.split.strategies._common import (
    seeded_shuffled, three_way_counts, validate_rates
)
from od_platform.data_pipeline.split.strategy_registry import SplitOptions, register_strategy


@register_strategy(SplitStrategy.RANDOM, requires_labels=False)
def random_split(pairs: PairList, options: SplitOptions) -> SplitManifest:
    test_rate = validate_rates(options.train_rate, options.val_rate)
    manifest = SplitManifest(
        train_rate=options.train_rate, 
        val_rate=options.val_rate, 
        test_rate=test_rate,
        random_state=options.random_state, 
        strategy=SplitStrategy.RANDOM
    )

    n = len(pairs)
    if n == 0:
        return manifest
    
    rng = random.Random(options.random_state)
    shuffled = seeded_shuffled(sorted(pairs, key=lambda p: p[0].stem), rng)
    n_train, n_val, _ = three_way_counts(n, options.train_rate, options.val_rate)
    
    manifest.train = shuffled[:n_train]
    manifest.val = shuffled[n_train: n_train + n_val]
    manifest.test = shuffled[n_train + n_val:]
    
    return manifest