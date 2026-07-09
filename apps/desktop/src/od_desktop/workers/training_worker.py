"""训练后台 worker —— 封装 TrainService.train() + 日志解析进度."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Signal

from .base_worker import BaseWorker


_EPOCH_PATTERN = re.compile(r"^\s*(\d+)/(\d+)\s+")
_LOSS_PATTERN = re.compile(
    r"^\s*\d+/\d+\s+[\d.]+\w*\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)"
)
_RESULTS_PATTERN = re.compile(r"(mAP50|mAP50-95|precision|recall)\s")


class TrainingWorker(BaseWorker):
    """在 QThread 中运行 train_yolo() + 日志解析进度.

    通过解析 Ultralytics 训练日志提取 epoch/loss/mAP 信息.
    进度信号: (percent, status_text)
    指标信号: metrics dict
    """

    metrics_update = Signal(dict)

    def __init__(
        self,
        dataset: str,
        model: str = "yolo11n.pt",
        epochs: int = 100,
        imgsz: int = 640,
        batch: int = 16,
        device: Optional[str] = None,
        extra_args: Optional[dict[str, Any]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._dataset = dataset
        self._model = model
        self._epochs = epochs
        self._imgsz = imgsz
        self._batch = batch
        self._device = device
        self._extra_args = extra_args or {}
        self._log_handler: Optional[_TrainingLogHandler] = None

    def run(self) -> None:
        self.started.emit()
        self.progress.emit(0, "正在准备训练...")
        try:
            self._log_handler = _TrainingLogHandler(self)
            root = logging.getLogger()
            root.addHandler(self._log_handler)

            from od_platform.training.service import train_yolo

            cli_args: dict[str, Any] = {
                "epochs": self._epochs,
                "imgsz": self._imgsz,
                "batch": self._batch,
                "data": self._dataset,
                "model": self._model,
                **self._extra_args,
            }
            if self._device:
                cli_args["device"] = self._device

            self.progress.emit(2, "正在初始化训练...")
            result = train_yolo(cli_args=cli_args)

            if result.success:
                self.progress.emit(100, f"训练完成 ({result.train_time:.0f}s)")
                self.finished.emit(result)
            else:
                self.error.emit(result.error or "训练失败")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self._log_handler:
                root = logging.getLogger()
                root.removeHandler(self._log_handler)


class _TrainingLogHandler(logging.Handler):
    """解析 Ultralytics 训练日志提取 epoch 进度."""

    def __init__(self, worker: TrainingWorker) -> None:
        super().__init__()
        self._worker = worker
        self._total_epochs = worker._epochs
        self._in_results = False

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()

        # 检测 epoch 行: "    1/200    3.12G    0.8324    0.4562..."
        m = _EPOCH_PATTERN.match(msg)
        if m and not self._in_results:
            current = int(m.group(1))
            total = int(m.group(2))
            if total > 0:
                self._total_epochs = total
            pct = int(current / max(self._total_epochs, 1) * 100)

            # 尝试提取 loss
            lm = _LOSS_PATTERN.match(msg)
            metrics = {
                "epoch": f"{current}/{self._total_epochs}",
                "percent": pct,
            }
            if lm:
                metrics["box_loss"] = float(lm.group(1))
                metrics["cls_loss"] = float(lm.group(2))
                metrics["dfl_loss"] = float(lm.group(3))

            self._worker.progress.emit(pct, f"Epoch {current}/{self._total_epochs}")
            self._worker.metrics_update.emit(metrics)

        # 检测结果行: "Class  Images  Instances  Box(P  R  mAP50  mAP50-95)"
        if _RESULTS_PATTERN.search(msg):
            self._in_results = True

        # 重置标志
        if msg.strip() == "":
            return
