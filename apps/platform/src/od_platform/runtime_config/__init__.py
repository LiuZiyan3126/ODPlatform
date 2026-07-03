#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :__init__.py.py
# @Time      :2026/7/3 14:11:38
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
"""runtime_config 子系统对外公共 API.

只 import 这里 __all__ 列的符号. 没列出的(如 ConfigMetadata)是内部实现, 随时可能改.
"""
from od_platform.runtime_config.base      import BaseConfig
from od_platform.runtime_config.train     import YOLOTrainConfig
from od_platform.runtime_config.val       import YOLOValConfig
from od_platform.runtime_config.infer     import YOLOInferConfig
from od_platform.runtime_config.loaders   import YAMLLoader, CLILoader
from od_platform.runtime_config.merger    import ConfigMerger, ConfigSource
from od_platform.runtime_config.generator import ConfigGenerator
from od_platform.runtime_config.registry  import CONFIG_REGISTRY
from od_platform.runtime_config.api       import (
    build_train_config, build_val_config, build_infer_config,
)

__all__ = [
    "BaseConfig", "YOLOTrainConfig", "YOLOValConfig", "YOLOInferConfig",
    "YAMLLoader", "CLILoader", "ConfigMerger", "ConfigSource", "ConfigGenerator",
    "CONFIG_REGISTRY",
    "build_train_config", "build_val_config", "build_infer_config",
]