"""数据流水线后台 worker —— 封装 DatasetPipeline.run()."""
from __future__ import annotations

from typing import Dict

from .base_worker import BaseWorker


class PipelineWorker(BaseWorker):
    """在 QThread 中运行 DatasetPipeline.run().

    通过日志输出提供进度反馈; 结果通过 finished 信号返回.
    """

    def __init__(
        self,
        dataset: str,
        annotation_format: str,
        task: str = "detect",
        train_rate: float = 0.8,
        val_rate: float = 0.1,
        random_state: int = 1210,
        split_strategy: str = "random",
        split_mode: str = "resplit",
        classes: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._dataset = dataset
        self._annotation_format = annotation_format
        self._task = task
        self._train_rate = train_rate
        self._val_rate = val_rate
        self._random_state = random_state
        self._split_strategy = split_strategy
        self._split_mode = split_mode
        self._classes = classes

    def run(self) -> None:
        self.started.emit()
        self.progress.emit(5, "正在初始化数据流水线...")
        try:
            from od_platform.data_pipeline.orchestrator import DatasetPipeline

            pipe = DatasetPipeline(
                dataset=self._dataset,
                annotation_format=self._annotation_format,
                task=self._task,
                train_rate=self._train_rate,
                val_rate=self._val_rate,
                random_state=self._random_state,
                split_strategy=self._split_strategy,
                split_mode=self._split_mode,
                classes=self._classes,
            )
            self.progress.emit(10, "正在运行数据流水线(预检→转换→划分→落盘)...")
            result: Dict = pipe.run()
            self.progress.emit(100, "数据流水线完成")
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
