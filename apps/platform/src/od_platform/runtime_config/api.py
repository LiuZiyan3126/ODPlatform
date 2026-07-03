#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :api.py
# @Time      :2026/7/3 14:58:34
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : api.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统——对外管线门面(build_* 便捷函数)
"""对外公共 API: build_train/val/infer_config 一行构建配置."""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import List, Optional, Tuple, Union

from od_platform.common.paths import RUNTIME_CONFIGS_DIR
from od_platform.runtime_config.loaders import YAMLLoader, CLILoader
from od_platform.runtime_config.merger import ConfigMerger, ConfigSource
from od_platform.runtime_config.train import YOLOTrainConfig
from od_platform.runtime_config.val import YOLOValConfig
from od_platform.runtime_config.infer import YOLOInferConfig


def build_train_config(
    yaml_path: Optional[Union[str, Path]] = "train.yaml",
    cli_args:  Optional[Namespace] = None,
    *,
    dry_run: bool = False,
) -> Tuple[Optional[YOLOTrainConfig], ConfigMerger]:
    merger = ConfigMerger()
    sources: List[Tuple[ConfigSource, dict]] = []
    if yaml_path is not None:
        yaml_dict = YAMLLoader(config_dir=RUNTIME_CONFIGS_DIR).load(yaml_path)
        sources.append((ConfigSource.YAML, yaml_dict))
    if cli_args is not None:
        cli_dict = CLILoader().load(cli_args)
        sources.append((ConfigSource.CLI, cli_dict))
    if dry_run:
        merger.preview(YOLOTrainConfig, sources=sources)
        return None, merger
    config = merger.merge(YOLOTrainConfig, sources=sources)
    return config, merger


def build_val_config(
    yaml_path: Optional[Union[str, Path]] = "val.yaml",
    cli_args:  Optional[Namespace] = None,
    *,
    dry_run: bool = False,
) -> Tuple[Optional[YOLOValConfig], ConfigMerger]:
    """与 build_train_config 同构, 仅配置类和默认 yaml 不同."""
    merger = ConfigMerger()
    sources: List[Tuple[ConfigSource, dict]] = []
    if yaml_path is not None:
        yaml_dict = YAMLLoader(config_dir=RUNTIME_CONFIGS_DIR).load(yaml_path)
        sources.append((ConfigSource.YAML, yaml_dict))
    if cli_args is not None:
        cli_dict = CLILoader().load(cli_args)
        sources.append((ConfigSource.CLI, cli_dict))
    if dry_run:
        merger.preview(YOLOValConfig, sources=sources)
        return None, merger
    config = merger.merge(YOLOValConfig, sources=sources)
    return config, merger


def build_infer_config(
    yaml_path: Optional[Union[str, Path]] = "infer.yaml",
    cli_args:  Optional[Namespace] = None,
    *,
    dry_run: bool = False,
) -> Tuple[Optional[YOLOInferConfig], ConfigMerger]:
    """与 build_train_config 同构, 仅配置类和默认 yaml 不同."""
    merger = ConfigMerger()
    sources: List[Tuple[ConfigSource, dict]] = []
    if yaml_path is not None:
        yaml_dict = YAMLLoader(config_dir=RUNTIME_CONFIGS_DIR).load(yaml_path)
        sources.append((ConfigSource.YAML, yaml_dict))
    if cli_args is not None:
        cli_dict = CLILoader().load(cli_args)
        sources.append((ConfigSource.CLI, cli_dict))
    if dry_run:
        merger.preview(YOLOInferConfig, sources=sources)
        return None, merger
    config = merger.merge(YOLOInferConfig, sources=sources)
    return config, merger