#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :paths.py
# @Time      :2026/6/29 13:39:33
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :定义所有的路径变量信息，方便其他模块调用

from pathlib import Path
from typing import  List, Tuple

# 找到Workspace根目录
WORKSPACE_MARKER: str = ".odp-workspace"

def _find_workspace_root(start: Path,
                markers: Tuple[str, ...] = (WORKSPACE_MARKER,)
                ) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for parent in [current, *current.parents]:
        for marker in markers:
            if (parent / marker).exists():
                return parent
    raise FileNotFoundError(f"找不到workspace marker文件 ({markers})"
                            f"请确认仓库根目录已存在 {WORKSPACE_MARKER} 文件")


# 计算ROOT_DIR位置
ROOT_DIR: Path = _find_workspace_root(Path(__file__))

# 端的根目录APP_DIR
APP_DIR: Path = ROOT_DIR / "apps" / "platform"

# 共享资产
DATA_DIR: Path = ROOT_DIR / "data"
MODELS_DIR: Path = ROOT_DIR / "models"
RUNS_DIR: Path = ROOT_DIR / "runs"

# 模型的子目录
PRETRAINED_MODELS_DIR: Path = MODELS_DIR / "pretrained"  # 存放哪些预训练模型
TRAINED_MODELS_DIR: Path = MODELS_DIR / "trained"  # 训练好的哪些归档模型

# 数据集的子目录
RAW_DATA_DIR: Path = DATA_DIR / "raw"  # 这个存放用户原始的数据
PROCESSED_DATA_DIR: Path = DATA_DIR / "processed"  # 派生的数据集,含冻结后的train/val/test

# 端私有资产
CONFIGS_DIR: Path = APP_DIR / "configs"
DATASET_CONFIGS_DIR: Path = CONFIGS_DIR / "datasets"
LOGGING_DIR: Path = APP_DIR / "logging"
UNIT_TEST_DIR: Path = APP_DIR / "tests"

# 顶层的文档目录
DOCS_DIR: Path = ROOT_DIR / "docs"

# 工程基础设置目录共享的
SCRIPTS_DIR: Path = ROOT_DIR / "scripts"

# 元工具数据目录 / 工具自身的一些日志
META_DIR: Path = ROOT_DIR / '.odp-meta'
META_LOGGING_DIR: Path = META_DIR / "logging"

# 对外暴露的要初始化的目录列表
def get_dirs_to_initialize() -> List[Path]:
    return [
        DATA_DIR,
        MODELS_DIR,
        RUNS_DIR,
        PRETRAINED_MODELS_DIR,
        TRAINED_MODELS_DIR,
        RAW_DATA_DIR,
        PROCESSED_DATA_DIR,
        CONFIGS_DIR,
        LOGGING_DIR,
        UNIT_TEST_DIR,
        DOCS_DIR,
        SCRIPTS_DIR,
        META_LOGGING_DIR,
        DATASET_CONFIGS_DIR
    ]

def get_dirs_to_reset() -> List[Path]:
    """返回reset_project可以安全清理的目录列表"""
    return [
        PROCESSED_DATA_DIR,
        RUNS_DIR,
        LOGGING_DIR,
        CONFIGS_DIR,
        TRAINED_MODELS_DIR,
    ]

# 绝对保护目录：reset工具永远不能删除这些内容
PROTECTED_DIRS: tuple[Path,...] = (
    ROOT_DIR,
    APP_DIR,
    SCRIPTS_DIR,
    DOCS_DIR,
    UNIT_TEST_DIR,
    ROOT_DIR / '.git',
    ROOT_DIR / WORKSPACE_MARKER,
    RAW_DATA_DIR,
    PRETRAINED_MODELS_DIR,
    APP_DIR / 'src',
    META_DIR,
    META_LOGGING_DIR,
)

def is_protected(path: Path) -> bool:
    """
    路径是否受保护，即reset工具是否可以删除该路径
    1. 路径本身在PROTECTED_DIRS中
    2. 路径是PROTECTED_DIRS中某个目录的子目录的祖先目录
    Args:
    """
    path = path.resolve(strict=False)
    for protected in PROTECTED_DIRS:
        protected_resolve = protected.resolve(strict=False)
        if path == protected_resolve:
            return True
        if protected_resolve.is_relative_to(path):
            return True
    return False


def dataset_processed_dir(name: str) -> Path:
    """某数据集的派生根: data/processed/<name>/。

    按数据集分桶(每个数据集独占一个根),多数据集互不覆盖——这是把 train/val/test
    放进各自命名空间的关键。
    """
    return PROCESSED_DATA_DIR / name

def dataset_yaml_path(name: str) -> Path:
    """某数据集生成的 ultralytics yaml 路径: configs/datasets/<name>.yaml。"""
    return DATASET_CONFIGS_DIR / f"{name}.yaml"

# ============================================================
# D4 增量: 数据验证运行目录
# ============================================================
VALIDATION_RUNS_DIR: Path = RUNS_DIR / "data_validation"


def validation_run_dir(run_id: str) -> Path:
    """返回某次验证运行的产出目录: runs/data_validation/<run_id>/

    Args:
        run_id: 形如 "20260516_184523" 的时间戳 ID (由 validate_dataset 生成)

    Returns:
        Path 对象 (尚未创建, 调用方自己 mkdir)

    用法:
        run_dir = validation_run_dir("20260516_184523")
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "report.json").write_text(...)
    """
    return VALIDATION_RUNS_DIR / run_id

# ============================================================
# D5 增量: 运行配置目录
# ============================================================
RUNTIME_CONFIGS_DIR: Path = CONFIGS_DIR / "runtime"


def runtime_config_path(name: str) -> Path:
    """返回某个运行配置文件的路径: <CONFIGS_DIR>/runtime/<name>.yaml

    Args:
        name: 配置名 (如 "train" / "val" / "infer"), 不带 .yaml 后缀

    Returns:
        Path 对象 (尚未创建, 调用方自己负责 mkdir)

    用法:
        train_yaml = runtime_config_path("train")
        # → <APP_DIR>/configs/runtime/train.yaml
    """
    return RUNTIME_CONFIGS_DIR / f"{name}.yaml"


# ============================================================
# D8 增量: 推理管线配置
# ============================================================
INFER_PIPELINE_CONFIG_DIR: Path = RUNTIME_CONFIGS_DIR


def pipeline_config_path(name: str = "infer_pipeline") -> Path:
    """返回推理管线配置文件的路径: <RUNTIME_CONFIGS_DIR>/<name>.yaml

    Args:
        name: 配置名 (如 "infer_pipeline"), 不带 .yaml 后缀

    Returns:
        Path 对象

    用法:
        cfg = pipeline_config_path()
        # → <APP_DIR>/configs/runtime/infer_pipeline.yaml
        cfg = pipeline_config_path("my_pipeline")
        # → <APP_DIR>/configs/runtime/my_pipeline.yaml
    """
    return INFER_PIPELINE_CONFIG_DIR / f"{name}.yaml"


if __name__ == "__main__":
    print(f"ROOT DIR (workspace) = {ROOT_DIR}")
    print(f"APP DIR = {APP_DIR}")
    print(f"DATA DIR = {DATA_DIR}")
    print(f"MODELS DIR = {MODELS_DIR}")
    print(f"RUNS DIR = {RUNS_DIR}")
    print(f"PRETRAINED MODELS DIR = {PRETRAINED_MODELS_DIR}")
    print(f"TRAINED MODELS DIR = {TRAINED_MODELS_DIR}")
    print(f"RAW DATA DIR = {RAW_DATA_DIR}")
    print(f"PROCESSED DATA DIR = {PROCESSED_DATA_DIR}")
    print(f"CONFIGS DIR = {CONFIGS_DIR}")
    print(f"LOGGING DIR = {LOGGING_DIR}")
    print(f"UNIT TEST DIR = {UNIT_TEST_DIR}")
    for d in get_dirs_to_initialize():
        print(f"将要初始化的目录有: {d.relative_to(ROOT_DIR)}")










