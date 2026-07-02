# split调度层 - 查策略表
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from od_platform.common.constants import DEFAULT_RANDOM_STATE, DEFAULT_SPLIT_STRATEGY
from od_platform.data_pipeline.split.strategy_registry import SplitOptions, get_strategy
from od_platform.data_pipeline.split.manifest import PairList, SplitManifest

logger = logging.getLogger(__name__)

def split_pairs(
    pairs: PairList,
    train_rate: float = 0.8,
    val_rate: float = 0.1,
    random_state: int = DEFAULT_RANDOM_STATE,
    *,
    strategy: str = DEFAULT_SPLIT_STRATEGY,
    labels_per_image: Optional[Dict[str, List[str]]] = None,
    group_per_image: Optional[Dict[str, str]] = None
) -> SplitManifest:
    entry = get_strategy(strategy)
    if entry.requires_labels and labels_per_image is None:
        raise ValueError(f"划分策略{strategy}需要label_per_images, 但是未提供")
    options = SplitOptions(
        train_rate = train_rate, val_rate = val_rate, random_state = random_state,
        labels_per_image = labels_per_image, group_per_image = group_per_image
    )
    return entry.func(pairs, options)