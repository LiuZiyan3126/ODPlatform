#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : camera.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : 摄像头输入源 — 跨平台 + 后端协商 + 参数验证
"""
摄像头输入源。

工程要点(均为撞墙记录,改动前请先理解):
    1. MSMF 后端必须在 cv2.VideoCapture 创建之前设置环境变量
       OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS=0,否则帧率下降 20-30%
    2. 参数设置顺序必须是: 宽高 → FOURCC → FPS,
       否则 MSMF 下高帧率请求会被驱动重新协商时覆盖,完全失效
    3. set() 是请求不是命令,必须 read 一帧触发驱动协商,再 get 读回真实值

stride 说明:
    摄像头硬件按固有 fps 产帧, 跳帧不省采集开销, 反而徒增延迟。
    实时降频请用 ThreadedSource 的 latest 缓冲 + 主循环按节奏拉,
    比 stride 更优雅。本类覆盖 set_stride 给出 warning 并强制忽略。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import cv2

from ..core.base   import FrameSource
from ..core.config import CameraConfig
from ..core.types  import Frame, FrameInfo, SourceType
from ..registry     import register_source


logger = logging.getLogger(__name__)


def _video_writer_fourcc(codec: str) -> int:
    return int(getattr(cv2, "VideoWriter_fourcc")(*codec))


class CameraSource(FrameSource):
    """
    摄像头输入源,支持指定分辨率/帧率/后端/编码。
    """

    def __init__(self, config: CameraConfig):
        super().__init__(str(config.camera_id))
        self.config = config
        self._cap: Optional[cv2.VideoCapture] = None
        self._width  = 0
        self._height = 0
        self._fps    = 0.0

    def open(self) -> bool:
        # ── 撞墙记录 ①: MSMF 必须在 VideoCapture 之前设置环境变量 ──
        # 该环境变量关闭 MSMF 自动插入的硬件色彩转换滤镜(HW Transforms),
        # 否则会导致帧率下降 20~30%。必须在初始化前设置才生效。
        if self.config.backend == "msmf":
            os.environ["OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"] = "0"

        self._cap = cv2.VideoCapture(self.config.camera_id, self._get_backend())

        if not self._cap.isOpened():
            logger.error(f"无法打开摄像头 {self.config.camera_id}")
            return False

        # ── 撞墙记录 ②: 参数设置顺序 宽高 → FOURCC → FPS ──
        # 正确顺序:
        #   1. 先设分辨率:驱动据此筛选可用的媒体类型列表
        #   2. 再设 FOURCC:从上一步的列表中选择编码格式(MJPG)
        #   3. 最后设 FPS:格式锁定后才约束帧率
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.config.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        self._cap.set(cv2.CAP_PROP_FOURCC, _video_writer_fourcc(self.config.codec))
        self._cap.set(cv2.CAP_PROP_FPS, self.config.fps)

        # ── 撞墙记录 ③: MSMF/DSHOW 懒初始化,必须 read 一帧触发协商 ──
        # set() 只是登记意图,驱动在第一次 read() 时才真正与摄像头硬件
        # 协商并锁定格式。没有这次 read(),下面的 get() 读回的是"请求值"
        # 而非"实际值"。
        ret, _ = self._cap.read()
        if not ret:
            logger.warning("格式协商触发帧读取失败,实际参数可能不准确")

        # 读回实际生效的参数
        self._width  = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._fps    = self._cap.get(cv2.CAP_PROP_FPS)

        # ── "我设了" ≠ "它生效了":验证差异并 warning ──
        if self._width != self.config.width or self._height != self.config.height:
            logger.warning(
                f"分辨率未完全生效:期望 {self.config.width}x{self.config.height},"
                f"实际 {self._width}x{self._height}"
            )
        if self._fps < self.config.fps * 0.9:    # 允许 10% 误差
            logger.warning(
                f"帧率未完全生效:期望 {self.config.fps}fps,"
                f"实际标称 {self._fps:.1f}fps"
            )

        logger.info(
            f"摄像头已打开 (backend={self.config.backend}, codec={self.config.codec})"
        )
        logger.info(
            f"  目标: {self.config.width}x{self.config.height} @ {self.config.fps}fps"
        )
        logger.info(
            f"  实际: {self._width}x{self._height} @ {self._fps:.1f}fps"
        )
        # 同步起始时间, 让 timestamp = 0 对应"open 完成", 而不是对象构造
        self._start_time = time.time()
        self._frame_index = 0       # 复位: 重新 open 即重头计数(timestamp 也从 0 起)
        return True

    def _get_backend(self) -> int:
        """将配置字符串映射为 OpenCV 后端常量(Pydantic 已保证不会传非法值)"""
        backends = {
            "auto":  cv2.CAP_ANY,
            "msmf":  cv2.CAP_MSMF,
            "dshow": cv2.CAP_DSHOW,
            "v4l2":  cv2.CAP_V4L2,
        }
        return backends[self.config.backend]

    def read(self) -> Optional[Frame]:
        # 摄像头不支持 stride 跳帧(见类 docstring), 直接读最新一帧
        if self._cap is None:
            return None

        ret, image = self._cap.read()
        if not ret:
            return None

        info = FrameInfo(
            width=self._width,
            height=self._height,
            source_type=SourceType.CAMERA,
            source_path=self.source_path,
            frame_index=self._frame_index,
            timestamp=time.time() - self._start_time,
            fps=self._fps,
            filename=f"camera:{self.config.camera_id}",
        )
        self._frame_index += 1
        return Frame(image=image, info=info)

    def set_stride(self, stride: int) -> None:
        """
        摄像头不支持 stride 跳帧。

        理由: 摄像头硬件按固有 fps 产帧, read-and-discard 既不省采集开销,
        又会让"latest 缓冲" 拿到的"最新一帧" 反而是更旧的一帧, 加大端到端
        延迟。实时降频请用 ThreadedSource 的 latest 缓冲 + 主循环按节奏拉。

        本方法不 raise(保持与统一接口兼容), 但若 stride>1 会 warning
        并强制锁回 1。
        """
        if stride != 1:
            logger.warning(
                "摄像头不支持 stride 跳帧(硬件按固有 fps 产帧, 跳帧无收益)。"
                "实时降频请使用 ThreadedSource 的 latest 缓冲 + 主循环按节奏拉。"
                f" 收到的 stride={stride} 已忽略。"
            )
        # 强制锁回 1, 不沿用基类的"登记任意整数"语义
        self._stride = 1

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("摄像头已关闭")

    def get_source_type(self) -> SourceType:
        return SourceType.CAMERA


@register_source("camera", detect=lambda s: s.isdigit(), priority=0)
def _build_camera_source(source: str, camera_config, options) -> CameraSource:
    camera_id = int(source)
    cfg = camera_config or CameraConfig()
    cfg = cfg.model_copy(update={"camera_id": camera_id})
    return CameraSource(cfg)
