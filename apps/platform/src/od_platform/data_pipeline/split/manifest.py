from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from typing import Dict, List, Tuple

# 先定义好一对样本
Pair = Tuple[Path, Path]
PairList = List[Pair]

@dataclass
class SplitManifest:
    # 三组样本
    train: PairList = field(default_factory=list)
    val: PairList = field(default_factory=list)
    test: PairList = field(default_factory=list)
    # 可复现元数据
    train_rate: float = 0.8
    val_rate: float = 0.1
    test_rate: float = 0.1
    random_state: int = 2023302644
    strategy: str = "random"

    def summary(self) -> Dict[str, int]:
        return {
            "train": len(self.train),
            "val": len(self.val),
            "test": len(self.test),
            "total": len(self.train) + len(self.val) + len(self.test)
        }