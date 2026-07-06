#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :service.py
# @Time      :2026/7/6 14:11:36
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :流程编排

from __future__ import annotations
import json
import logging
from argparse import Namespace
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import  Any
from ultralytics import YOLO

from od_platform.common.config_log import log_effective_config, log_override_chains
from od_platform.common.dataset_path import resolve_dataset_path
from od_platform.common.log_rename import rename_log_to_save_dir
from od_platform.common.model_path import resolve_model_path
from od_platform.common.paths import RUNS_DIR

from od_platform.common.result import TrainMetrics, log_train_metrics
from od_platform.common.system_utils import log_device_info
from od_platform.validate_dataset.render import  render_to_logger
from od_platform.validate_dataset.service import validate_dataset
from od_platform.runtime_config import build_train_config # 获取训练配置的

from .archive import archive_checkpoints

logger = logging.getLogger(__name__)
def _find_project_log_path() -> Path | None:
    root = logging.getLogger("od_platform")
    for h in root.handlers:
        if isinstance(h,logging.FileHandler):
            return  Path(h.baseFilename)
    return  None

@dataclass(frozen=True)
class TrainResult:
    """训练结果一次性快照"""
    success: bool
    output_dir: Path
    best_weight: Path | None = None
    last_weight: Path | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    train_time: float | None = None
    error: str | None = None
    audit_path: Path | None = None
    log_path: Path | None = None

class TrainService:
    """YOLO训练流程编排"""
    def __init__(self) -> None:
        pass

    def train(
        self,
        yaml_path: str | Path | None = None,
        cli_args: dict[str, Any] | Namespace | None = None,
        *,
        archive: bool = True,
        rename_log: bool = True,
        ) -> TrainResult:
        start = datetime.now()
        output_dir: Path | None = None
        try:
            # 阶段1： 配置加载
            config, merger = build_train_config(
                yaml_path=yaml_path,
                cli_args=cli_args
            )
            if config is None:
                raise RuntimeError("训练配置构建失败，未生成有效配置。")
            logger.info("=" * 60)
            logger.info(f"开始进行YOLO训练 （task = {config.task})".center(60))
            logger.info("=" * 60)
            # 展示训练的核心标识
            raw_model = config.model or "yolo11n.pt"
            raw_data = config.data
            if raw_data is None:
                raise ValueError("训练配置中缺少数据集配置路径: data")
            logger.info(f"任务类型： {config.task}")
            logger.info(f"数据集声明：{raw_data}")
            data_path = resolve_dataset_path(raw_data)
            logger.info(f"数据集路径： {data_path}")
            logger.info(f"模型名称： {raw_model}")
            model_path = resolve_model_path(raw_model)
            logger.info(f"模型路径： {model_path}")

            # D2：系统快照
            log_device_info()

            # 字段溯源
            log_effective_config(config, merger, logger=logger)
            log_override_chains(config, merger, logger=logger)

            # 模型加载
            model = YOLO(str(model_path))

            yolo_kwargs = config.to_ultralytics_kwargs()
            yolo_kwargs["data"] = str(data_path)
            yolo_kwargs.setdefault("project", str(RUNS_DIR / f"{config.task}_train"))

            logger.info("="*60)
            logger.info("启动训练".center(60))

            yolo_results = model.train(**yolo_kwargs)
            save_dir_value = None
            if isinstance(yolo_results, dict):
                save_dir_value = yolo_results.get("save_dir")
            else:
                save_dir_value = getattr(yolo_results, "save_dir", None)
            if not save_dir_value:
                raise RuntimeError("训练结果中未返回有效的 save_dir")
            output_dir = Path(save_dir_value)

            # 记录结果指标
            logger.info("训练完成".center(60))
            metrics = TrainMetrics.from_yolo_results(
                yolo_results, model_trainer=getattr(model, "trainer", None)
            )
            log_train_metrics(metrics, logger=logger)

            # 整理输出
            model_stem = Path(raw_model).stem
            if rename_log:
                rename_log_to_save_dir(output_dir, model_stem)

            archived: dict[str,Path] = {}
            if archive:
                archived = archive_checkpoints(train_dir=output_dir, model_filename=raw_model)

            # 审计快照
            audit_path = output_dir / "od_audit.json"
            log_path = _find_project_log_path()
            try:
                audit_payload = {
                    "config": config.to_audit_snapshot(),
                    "merger": merger.to_audit_log(),
                    "metrics": metrics.to_dict(),
                    "result_summary":{
                        "best_archive": str(archived.get("best","")) or None,
                        "last_archive": str(archived.get("last","")) or None,
                        "train_time_sec": (datetime.now() - start).total_seconds(),
                        "log_path": str(log_path) if log_path else None
                    }
                }
                audit_path.write_text(
                    json.dumps(audit_payload, ensure_ascii=False, indent=2),encoding="utf-8"
                )
                logger.info(f"审计快照：{audit_path}")
            except OSError as e:
                logger.warning(f"审计快照失败: {e}")
                audit_path = None
            # 收尾：TrainResult
            train_time = (datetime.now() - start).total_seconds()
            best_weight = archived.get("best") or (output_dir / "weight"/ "bset.pt")
            last_weight = archived.get("last") or (output_dir / "weight"/ "last.pt")

            logger.info("训练结果".center(60))
            logger.info(f"输出目录： {output_dir}")
            logger.info(f"最佳模型： {best_weight}")
            logger.info(f"最后模型： {last_weight}")
            logger.info(f"训练时间： {train_time}秒")
            if log_path:
                logger.info(f"日志路径： {log_path}")
            return  TrainResult(
                success=True,
                output_dir=output_dir,
                best_weight=best_weight if best_weight.exists() else None,
                last_weight=last_weight if last_weight.exists() else None,
                metrics=metrics.overall,
                train_time=train_time,
                audit_path=audit_path,
                log_path=log_path
            )
        except Exception as e:
            logger.error(f"训练失败: {e}", exc_info=True)
            train_time = (datetime.now() - start).total_seconds()
            return TrainResult(
                success=False,
                output_dir=output_dir or Path('Unknow'),
                metrics={},
                train_time=train_time,
                error=str(e),
                log_path=_find_project_log_path()
            )
def train_yolo(
        yaml_path: str | Path | None = None,
        cli_args: dict[str, Any] | Namespace | None = None,
        *,
        rename_log: bool = True,
        archive: bool = True,
    ) -> TrainResult:
    service = TrainService()
    return service.train(
        yaml_path=yaml_path,
        cli_args=cli_args,
        archive=archive,
        rename_log=rename_log,
    )




