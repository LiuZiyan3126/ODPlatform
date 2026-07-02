# 引用解析，把命令行用户给的dataset / yaml / model等等名字或路径统一做好解析，解析成统一的path

from __future__ import annotations

from pathlib import Path
from typing import Optional
from od_platform.common.paths import RAW_DATA_DIR, TRAINED_MODELS_DIR, PRETRAINED_MODELS_DIR, DATASET_CONFIGS_DIR

def resolve_ref(ref: str, *, base_dir:Path, default_suffiex:Optional[str] = None) -> Path:
    p = Path(ref)
    if p.is_absolute() or len(p.parts) > 1:
        return p.resolve()
    name = ref if (not default_suffiex or ref.endswith(default_suffiex)) else ref + default_suffiex
    return (base_dir / name).resolve()

def resolve_dataset(ref: str) -> Path:
    return resolve_ref(ref, base_dir = RAW_DATA_DIR)