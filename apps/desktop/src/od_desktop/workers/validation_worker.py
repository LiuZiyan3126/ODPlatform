"""数据质检后台 worker —— 封装 validate_dataset()."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base_worker import BaseWorker


class ValidationWorker(BaseWorker):
    """在 QThread 中运行 validate_dataset()."""

    def __init__(
        self,
        yaml_path: Path,
        task_type: Optional[str] = None,
        write_report: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._yaml_path = yaml_path
        self._task_type = task_type
        self._write_report = write_report

    def run(self) -> None:
        self.started.emit()
        self.progress.emit(5, "正在扫描数据集...")
        try:
            from od_platform.validate_dataset.service import validate_dataset

            self.progress.emit(20, "正在执行质量检查...")
            report = validate_dataset(
                yaml_path=self._yaml_path,
                task_type=self._task_type,
                write_report=self._write_report,
            )
            self.progress.emit(100, f"检查完成: {len(report.results)} 项")
            self.finished.emit(report)
        except Exception as e:
            self.error.emit(str(e))
