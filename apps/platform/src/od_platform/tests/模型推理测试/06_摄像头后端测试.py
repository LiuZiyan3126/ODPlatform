#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :06_摄像头后端测试.py
# @Time      :2026/7/7 10:36:49
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
"""
摄像头高帧率基准测试
- 后端   : MSMF (Windows Media Foundation)
- 格式   : MJPG
- 架构   : 采集线程 + 显示主线程分离，避免 imshow 阻塞采集
"""

import os
import time
import threading
from typing import Optional, List, Tuple   # ★ 修复：向 Python 3.9 兼容

import cv2
import numpy as np

# ── MSMF 必须在创建 VideoCapture 之前设置，禁用硬件加速变换
# 否则 MSMF 会插入额外的色彩转换滤镜，导致帧率下降
os.environ["OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"] = "0"

# ────────────────────────────────────────────────────────────
# 配置区
# ────────────────────────────────────────────────────────────
CAMERA_ID  = 0      # 摄像头设备索引
WIDTH      = 1280   # 目标分辨率
HEIGHT     = 720
TARGET_FPS = 90     # 目标帧率
DURATION   = 60     # 测速总时长（秒）
MJPG_FOURCC = ord("M") | (ord("J") << 8) | (ord("P") << 16) | (ord("G") << 24)

# ────────────────────────────────────────────────────────────
# 线程间共享状态
# ────────────────────────────────────────────────────────────

# 最新一帧，供显示线程读取（采集线程持续覆盖）
# ★ 修复：原用 cv2.typing.MatLike（需 opencv-python ≥ 4.8）+ PEP 604 联合（需 Python ≥ 3.10）
latest_frame: Optional[np.ndarray] = None
frame_lock = threading.Lock()           # 保护 latest_frame 的读写

stop_event  = threading.Event()         # 任意一方请求停止时置位
ready_event = threading.Event()         # 采集线程初始化完成后置位

# 统计数据（只有采集线程写，主线程只读，int/float 赋值在 CPython 下是原子的）
count   = 0             # 累计成功读取的帧数
dropped = 0             # 累计读取失败次数（ret=False）
samples: List[float] = []  # 每秒瞬时 FPS 采样列表   # ★ list[float] 需 3.9+，统一用 typing.List
min_fps = float("inf")
max_fps = 0.0
t0: Optional[float] = None   # 采集开始时间，ready_event 置位后主线程才会使用
BgrColor = Tuple[int, int, int]


# ────────────────────────────────────────────────────────────
# 采集线程
# ────────────────────────────────────────────────────────────
def capture_thread():
    global count, dropped, min_fps, max_fps, latest_frame, t0

    # ── 打开摄像头 ──────────────────────────────────────────
    cap = cv2.VideoCapture(CAMERA_ID, cv2.CAP_MSMF)
    if not cap.isOpened():
        print(f"[错误] 无法打开摄像头 #{CAMERA_ID}")
        stop_event.set()
        ready_event.set()   # 防止主线程永久阻塞在 wait()
        return

    # ── 参数设置：分辨率 → FOURCC → FPS ────────────────────
    # MSMF 下顺序不像 DSHOW 那么敏感，但仍建议 FOURCC 在分辨率之后设置
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FOURCC, MJPG_FOURCC)
    cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)

    # ── 触发格式协商 ────────────────────────────────────────
    # 驱动在第一次 read() 时才真正锁定格式，之后 get() 读回的值才准确
    cap.read()

    # ── 读回实际参数 ─────────────────────────────────────────
    actual_w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    # MSMF 不回报 FOURCC 数值（读回为 0），直接标注已显式设置
    fourcc_str = "MJPG (已显式设置，MSMF不回报数值)"

    print("=" * 56)
    print(f"  摄像头 #{CAMERA_ID}  后端: MSMF")
    print(f"  分辨率 : {actual_w}x{actual_h}  (目标 {WIDTH}x{HEIGHT})")
    print(f"  FPS    : {actual_fps:.1f}  (目标 {TARGET_FPS})")
    print(f"  格式   : {fourcc_str}")
    print(f"  测速   : {DURATION}s，主窗口按 q 提前结束")
    print("=" * 56)

    # ── 记录开始时间，通知主线程可以开始显示 ────────────────
    start_time = time.perf_counter()
    t0 = start_time
    tw = start_time         # 滑动窗口起点（每秒重置一次）
    wc = 0          # 当前 1 秒窗口内的帧计数
    ready_event.set()

    # ── 采集主循环 ───────────────────────────────────────────
    while not stop_event.is_set():
        ret, frame = cap.read()

        if not ret:
            # 读取失败：驱动偶发错误，记录后继续，不中断循环
            dropped += 1
            continue

        count += 1
        wc    += 1
        now    = time.perf_counter()
        elapsed = now - start_time

        # 将最新帧写入共享变量（加锁保证显示线程不会读到撕裂帧）
        with frame_lock:
            latest_frame = frame

        # ── 每 1 秒向终端打印一次统计 ───────────────────────
        if now - tw >= 1.0:
            inst    = wc / (now - tw)       # 本窗口瞬时 FPS
            avg     = count / elapsed       # 全程均值 FPS
            samples.append(inst)
            min_fps = min(min_fps, inst)
            max_fps = max(max_fps, inst)
            remaining = max(0.0, DURATION - elapsed)

            print(f"  [{elapsed:5.1f}s]"
                  f"  瞬时={inst:5.1f}"
                  f"  均值={avg:5.1f}"
                  f"  峰值={max_fps:5.1f}"
                  f"  低谷={min_fps:5.1f}"
                  f"  丢帧={dropped}"
                  f"  剩余={remaining:.0f}s")

            tw, wc = now, 0     # 重置滑动窗口

        # 到达测速时长，通知所有线程退出
        if elapsed >= DURATION:
            stop_event.set()

    cap.release()


# ────────────────────────────────────────────────────────────
# 主线程入口
# ────────────────────────────────────────────────────────────
if __name__ == "__main__":

    # ── 启动采集线程 ─────────────────────────────────────────
    t = threading.Thread(target=capture_thread, daemon=True)
    t.start()

    # ── 等待摄像头真正就绪（或超时报错） ────────────────────
    if not ready_event.wait(timeout=10):
        print("[错误] 摄像头初始化超时（10s），请检查设备连接")
        stop_event.set()
        t.join()
        raise SystemExit(1)

    if stop_event.is_set():
        # 采集线程初始化失败时会同时置位 stop_event
        print("[错误] 采集线程初始化失败，退出")
        t.join()
        raise SystemExit(1)

    start_time = t0
    if start_time is None:
        print("[错误] 采集线程未返回开始时间，退出")
        stop_event.set()
        t.join()
        raise SystemExit(1)

    # ── 显示主循环（限 30fps 刷新，不占用采集带宽） ─────────
    # imshow + waitKey 在 Windows 下每帧约 10~16ms，
    # 若在采集线程内调用会直接将帧率压到 60fps 以下；
    # 放到主线程并限速后，采集线程完全不受影响。
    display_interval = 1.0 / 30
    last_display     = 0.0

    while not stop_event.is_set():
        now = time.perf_counter()

        # 未到刷新间隔则短暂休眠，避免空转吃满 CPU
        if now - last_display < display_interval:
            time.sleep(0.001)
            continue
        last_display = now

        # 取最新帧副本（加锁，防止采集线程同时写入）
        with frame_lock:
            frame = None if latest_frame is None else latest_frame.copy()

        if frame is None:
            continue
        draw_frame: np.ndarray = frame

        # ── 计算当前统计值 ───────────────────────────────────
        elapsed = now - start_time
        avg     = count / elapsed if elapsed > 0 else 0.0
        peak    = max_fps if samples else 0.0
        low     = min_fps if min_fps != float("inf") else 0.0

        # ── OSD 绘制：半透明黑底 + 5 行文字 ─────────────────
        overlay = draw_frame.copy()
        cv2.rectangle(overlay, (10, 8), (700, 218), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.45, draw_frame, 0.55, 0, draw_frame)

        def put(text: str, row: int, color: BgrColor = (0, 255, 0)) -> None:
            cv2.putText(draw_frame, text, (20, 42 + row * 38),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.95, color, 2)

        put(f"Realtime : {avg:6.1f} fps  (target {TARGET_FPS})", 0)
        put(f"Peak     : {peak:6.1f} fps",                        1, (0, 200, 255))
        put(f"Low      : {low:6.1f} fps",                         2, (80, 180, 255))
        put(f"Frames   : {count}    Dropped : {dropped}",          3, (180, 180, 180))
        put(f"Elapsed  : {elapsed:5.1f}s / {DURATION}s  (q=quit)", 4, (160, 160, 160))

        # ── 底部进度条 ───────────────────────────────────────
        bar_x2 = int(min(elapsed / DURATION, 1.0) * (WIDTH - 40))
        cv2.rectangle(draw_frame, (20, HEIGHT - 22), (WIDTH - 20, HEIGHT - 8), (50, 50, 50), -1)
        cv2.rectangle(draw_frame, (20, HEIGHT - 22), (20 + bar_x2, HEIGHT - 8), (0, 210, 80), -1)

        cv2.imshow("MSMF MJPG Benchmark", draw_frame)

        # waitKey 是 OpenCV 事件循环的驱动，必须调用；1ms 超时不影响采集
        if cv2.waitKey(1) & 0xFF == ord('q'):
            stop_event.set()

    # ── 收尾 ─────────────────────────────────────────────────
    t.join()
    cv2.destroyAllWindows()

    elapsed_total = time.perf_counter() - start_time
    avg_final = count / elapsed_total if elapsed_total > 0 else 0

    print()
    print("=" * 56)
    print(f"  总帧数   : {count}")
    print(f"  总耗时   : {elapsed_total:.2f} s")
    print(f"  平均 FPS : {avg_final:.1f}")
    print(f"  峰值 FPS : {max_fps:.1f}")
    print(f"  低谷 FPS : {min_fps:.1f}")
    print(f"  丢帧数   : {dropped}")
    stability = (min_fps / max_fps * 100) if max_fps > 0 else 0
    print(f"  稳定性   : {stability:.1f}%  (低谷/峰值)")
    print("=" * 56)
