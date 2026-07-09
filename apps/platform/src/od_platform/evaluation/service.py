#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""模型评估编排服务.

ValService 负责在指定数据分片上评估模型：
  1. 加载评估配置
  2. 解析模型权重路径与数据集路径
  3. 调用 YOLO model.val() 获取评估结果
  4. 提取结构化指标
  5. 写入审计快照
  6. 生成 Markdown 评估报告
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ultralytics import YOLO

from od_platform.common.config_log import log_effective_config, log_override_chains
from od_platform.common.dataset_path import resolve_dataset_path
from od_platform.common.model_path import resolve_model_path
from od_platform.common.paths import RUNS_DIR, TRAINED_MODELS_DIR
from od_platform.common.result import TrainMetrics, log_train_metrics
from od_platform.common.system_utils import log_device_info
from od_platform.runtime_config import build_val_config

from .report import generate_eval_report

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvalResult:
    """单次模型评估的结果快照。"""
    success: bool
    output_dir: Path
    model_path: Path
    metrics: dict[str, float] = field(default_factory=dict)
    eval_time: float | None = None
    error: str | None = None
    audit_path: Path | None = None
    report_path: Path | None = None


class ValService:
    """模型评估流程编排。"""

    def evaluate(
        self,
        model_path: str | Path,
        data_path: str | Path = "",
        *,
        yaml_path: str | Path | None = None,
        cli_args: dict[str, Any] | None = None,
        split: str = "test",
        author: str = "",
        save_plots: bool = True,
    ) -> EvalResult:
        """在指定数据分片上评估模型。

        Args:
            model_path: 模型权重路径（如 models/trained/xxx-best.pt）。
            data_path: 数据集声明名或 YAML 路径。
            yaml_path: 评估配置 YAML（默认 val.yaml）。
            cli_args: CLI 覆盖参数。
            split: 评估使用的分片（test/val/train）。
            author: 评估人标识。
            save_plots: 是否保留 ultralytics 生成的可视化产物。

        Returns:
            EvalResult 快照。
        """
        start = datetime.now()
        output_dir: Path | None = None

        try:
            # 阶段 1：配置加载
            config, merger = build_val_config(
                yaml_path=yaml_path,
                cli_args=cli_args,
            )
            if config is None:
                raise RuntimeError("评估配置构建失败")

            logger.info("=" * 60)
            logger.info("开始模型评估")
            logger.info("=" * 60)

            # 阶段 2：路径解析
            resolved_model = resolve_model_path(
                model_path,
                search_dirs=[TRAINED_MODELS_DIR],
            )
            logger.info(f"模型路径: {resolved_model}")

            resolved_data = (
                resolve_dataset_path(data_path) if data_path
                else Path("unknown")
            )
            logger.info(f"数据集路径: {resolved_data}")

            # 阶段 3：系统快照 & 配置溯源
            log_device_info()
            log_effective_config(config, merger, logger=logger)
            log_override_chains(config, merger, logger=logger)

            # 阶段 4：加载模型 & 执行验证
            model = YOLO(str(resolved_model))

            val_kwargs = config.to_ultralytics_kwargs()
            val_kwargs["data"] = str(resolved_data)
            val_kwargs["split"] = split
            val_kwargs.setdefault("project", str(RUNS_DIR / "eval"))

            logger.info("=" * 60)
            logger.info(f"在 {split} 分片上评估模型".center(60))

            val_results = model.val(**val_kwargs)

            save_dir_value = None
            if isinstance(val_results, dict):
                save_dir_value = val_results.get("save_dir")
            else:
                save_dir_value = getattr(val_results, "save_dir", None)

            if not save_dir_value:
                # 手动构造输出目录
                output_dir = RUNS_DIR / "eval" / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                output_dir.mkdir(parents=True, exist_ok=True)
            else:
                output_dir = Path(save_dir_value)

            logger.info("评估完成")

            # 阶段 5：提取指标
            metrics = TrainMetrics.from_yolo_results(
                val_results,
                model_trainer=getattr(model, "trainer", None),
            )
            log_train_metrics(metrics, logger=logger)

            # 阶段 6：审计快照
            audit_path = output_dir / "od_eval_audit.json"
            try:
                audit_payload = {
                    "config": config.to_audit_snapshot(),
                    "merger": merger.to_audit_log(),
                    "metrics": metrics.to_dict(),
                    "result_summary": {
                        "model": str(resolved_model),
                        "data": str(resolved_data),
                        "split": split,
                        "eval_time_sec": (datetime.now() - start).total_seconds(),
                    },
                }
                audit_path.write_text(
                    json.dumps(audit_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(f"审计快照: {audit_path}")
            except OSError as e:
                logger.warning(f"审计快照失败: {e}")
                audit_path = None

            # 阶段 7：评估报告
            report_path = generate_eval_report(
                EvalResult(
                    success=True,
                    output_dir=output_dir,
                    model_path=resolved_model,
                    metrics=metrics.overall,
                    eval_time=None,
                    audit_path=audit_path,
                ),
                author=author,
                model_name=Path(model_path).stem,
                data_name=str(resolved_data),
                split=split,
                task=config.task,
                class_map=metrics.class_map_50_95,
            )
            logger.info(f"评估报告: {report_path}")

            eval_time = (datetime.now() - start).total_seconds()
            return EvalResult(
                success=True,
                output_dir=output_dir,
                model_path=resolved_model,
                metrics=metrics.overall,
                eval_time=eval_time,
                audit_path=audit_path,
                report_path=report_path,
            )

        except Exception as e:
            logger.error(f"评估失败: {e}", exc_info=True)
            eval_time = (datetime.now() - start).total_seconds()
            return EvalResult(
                success=False,
                output_dir=output_dir or Path("unknown"),
                model_path=Path(model_path),
                metrics={},
                eval_time=eval_time,
                error=str(e),
            )
