#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :registry.py.py
# @Time      :2026/7/3 14:49:41
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : registry.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统——配置注册表(name → 配置类)
"""配置注册表: 唯一的 "名字 → 配置类" 真相.
生成器 CLI 与 build_* 同读这张表, 掐灭"同一映射散多处"的漂移.
"""
from od_platform.runtime_config.train import YOLOTrainConfig
from od_platform.runtime_config.val   import YOLOValConfig
from od_platform.runtime_config.infer import YOLOInferConfig

CONFIG_REGISTRY: dict[str, tuple[type, str]] = {
    "train": (YOLOTrainConfig, "YOLO 训练配置"),
    "val":   (YOLOValConfig,   "YOLO 验证配置"),
    "infer": (YOLOInferConfig, "YOLO 推理配置"),
}