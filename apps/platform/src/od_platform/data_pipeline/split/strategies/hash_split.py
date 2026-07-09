"""基于稳定样本标识的增量稳定划分。"""
from __future__ import annotations

import hashlib

from od_platform.common.constants import SplitStrategy
from od_platform.data_pipeline.split.manifest import Pair, PairList, SplitManifest
from od_platform.data_pipeline.split.strategies._common import validate_rates
from od_platform.data_pipeline.split.strategy_registry import SplitOptions, register_strategy


def _sample_fraction(pair: Pair, random_state: int) -> float:
    # 使用文件名而不是绝对路径，使数据集搬迁后仍能得到相同划分。
    stable_id = pair[0].name
    payload = f"{random_state}:{stable_id}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big") / (1 << 64)


@register_strategy(SplitStrategy.HASH, requires_labels=False)
def hash_split(pairs: PairList, options: SplitOptions) -> SplitManifest:
    """按哈希区间划分；追加其他样本不会改变已有样本的集合归属。"""
    test_rate = validate_rates(options.train_rate, options.val_rate)
    manifest = SplitManifest(
        train_rate=options.train_rate,
        val_rate=options.val_rate,
        test_rate=test_rate,
        random_state=options.random_state,
        strategy=SplitStrategy.HASH,
    )
    train_boundary = options.train_rate
    val_boundary = options.train_rate + options.val_rate

    for pair in sorted(pairs, key=lambda item: (item[0].name, str(item[0]))):
        fraction = _sample_fraction(pair, options.random_state)
        if fraction < train_boundary:
            manifest.train.append(pair)
        elif fraction < val_boundary:
            manifest.val.append(pair)
        else:
            manifest.test.append(pair)

    return manifest
