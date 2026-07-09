"""推理后台 worker —— 封装 infer_yolo() + QtSignalSink + InferHooks + CancelToken."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PySide6.QtCore import Signal

from .base_worker import BaseWorker


class InferenceWorker(BaseWorker):
    """在 QThread 中运行 infer_yolo().

    通过 QtSignalSink 发送标注帧, InferHooks 发送进度.
    """

    frame_ready = Signal(np.ndarray)    # 标注帧 (BGR, copy)
    stats_signal = Signal(dict)         # 实时统计

    def __init__(
        self,
        source: str,
        model: str = "yolo11n.pt",
        conf: float = 0.25,
        iou: float = 0.7,
        imgsz: int = 640,
        device: Optional[str] = None,
        save: bool = False,
        sink: Any = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._model = model
        self._conf = conf
        self._iou = iou
        self._imgsz = imgsz
        self._device = device
        self._save = save
        self._sink = sink
        self._cancel_token: Any = None
        self._start_time: float = 0.0
        self._frame_count = 0
        self._detection_count = 0

    def run(self) -> None:
        self.started.emit()
        self.progress.emit(0, "正在初始化推理...")
        try:
            from od_platform.inference.service import infer_yolo
            from od_platform.inference.cancel import CancelToken
            from od_platform.inference.hooks import InferHooks

            from ..sinks.qt_signal_sink import QtSignalSink

            if self._sink is None:
                self._sink = QtSignalSink()
            # 将 sink 的 frame_ready 信号桥接到 worker 的 frame_ready
            self._sink.frame_ready.connect(self.frame_ready)
            self._cancel_token = CancelToken()
            self._start_time = time.perf_counter()
            self._frame_count = 0
            self._detection_count = 0

            hooks = InferHooks(
                on_frame=self._on_frame,
                on_progress=self._on_progress,
                progress_interval_frames=10,
            )

            cli_args: dict[str, Any] = {
                "source": self._source,
                "model": self._model,
                "conf": self._conf,
                "iou": self._iou,
                "imgsz": self._imgsz,
                "save": self._save,
                "show": False,
            }
            if self._device:
                cli_args["device"] = self._device

            self.progress.emit(5, "正在加载模型和创建流水线...")
            result = infer_yolo(
                cli_args=cli_args,
                output_sink=self._sink,
                hooks=hooks,
                cancel_token=self._cancel_token,
                beautify=True,
                show_info=False,
            )

            if result.success:
                elapsed = time.perf_counter() - self._start_time
                self.progress.emit(100, f"推理完成 ({elapsed:.1f}s, {self._frame_count} 帧)")
                self.finished.emit(result)
            else:
                self.error.emit(result.error or "推理失败")
        except Exception as e:
            self.error.emit(str(e))

    def cancel(self) -> None:
        super().cancel()
        if self._cancel_token:
            self._cancel_token.cancel()
        if self._sink:
            try:
                self._sink.close()
            except Exception:
                pass

    # ── InferHooks 回调 (在引擎线程中调用) ──

    def _on_frame(self, evt) -> None:
        self._frame_count += 1
        self._detection_count += evt.n_detections

    def _on_progress(self, evt) -> None:
        elapsed = time.perf_counter() - self._start_time
        stats = {
            "frame_idx": evt.frame_idx,
            "total_frames": evt.total_frames,
            "elapsed_sec": elapsed,
            "fps_loop": evt.fps_loop,
            "fps_infer": evt.fps_infer,
            "detections_total": 0,
            "frame_count": self._frame_count,
            "detection_count": self._detection_count,
        }
        self.stats_signal.emit(stats)

        if evt.total_frames and evt.total_frames > 0:
            pct = int(evt.frame_idx / evt.total_frames * 100)
        else:
            pct = min(int(self._frame_count / 5), 95)
        status = f"Frame {evt.frame_idx} | FPS {evt.fps_loop:.1f}"
        self.progress.emit(pct, status)
