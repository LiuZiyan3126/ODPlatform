#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :05_opencv捕获_真实输入测试.py
# @Time      :2026/4/11 17:24:09
# @Author    :雨霓同学
# @Project   :YOLOP
# @Function  :
import cv2
import time
from ultralytics import YOLO

# ══════════════════════════════════════════════════════════════
#  输入控制配置
#  摄像头：可以主动要求设备以指定分辨率和帧率工作
#  视频文件：分辨率和帧率由文件本身决定，这里不做输入控制
# ══════════════════════════════════════════════════════════════
CAMERA_WIDTH  = 1280   # 期望摄像头输入宽度（像素）
CAMERA_HEIGHT = 720    # 期望摄像头输入高度（像素）
CAMERA_FPS    = 90     # 期望摄像头帧率

# ══════════════════════════════════════════════════════════════
#  输出控制配置
#  无论输入源是什么，最终显示的窗口都缩放到这个大小
#  设置为 None 表示不缩放，保持原始大小
# ══════════════════════════════════════════════════════════════
DISPLAY_WIDTH  = 1280  # 显示窗口宽度，设为 None 则不缩放
DISPLAY_HEIGHT = 720   # 显示窗口高度，设为 None 则不缩放

# ── 1. 加载模型 ──────────────────────────────────────────────
model = YOLO("train3-20250704-165500-yolo11n-best.pt")

# ── 2. 打开输入源 ─────────────────────────────────────────────
# 切换输入源只需改这一行：
#   摄像头  →  cv2.VideoCapture(0)
#   视频    →  cv2.VideoCapture("demo.mp4")
cap = cv2.VideoCapture(0)

# ── 3. 摄像头输入控制 ─────────────────────────────────────────
# 注意：这里只对摄像头生效，视频文件设置这些参数不会有任何效果
# OpenCV 只是"请求"摄像头按这个参数工作
# 实际能否达到取决于摄像头硬件是否支持
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAMERA_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
cap.set(cv2.CAP_PROP_FPS,          CAMERA_FPS)

# ── 4. 读取输入源实际参数 ─────────────────────────────────────
# 打开之后立刻读取实际生效的参数
# cap.get() 返回的是摄像头自己上报的标称值
# 不一定是真实采集帧率，后面会用计时器实测
actual_width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
actual_fps    = cap.get(cv2.CAP_PROP_FPS)
total_frames  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

# ── 5. 验证参数是否设置成功 ───────────────────────────────────
# cap.set() 失败不会报错，必须用 cap.get() 读回来验证
if actual_width != CAMERA_WIDTH or actual_height != CAMERA_HEIGHT:
    print(f"⚠️  分辨率设置未生效：期望 {CAMERA_WIDTH}x{CAMERA_HEIGHT}，"
          f"实际 {actual_width}x{actual_height}")
if actual_fps < CAMERA_FPS:
    print(f"⚠️  帧率设置未生效：期望 {CAMERA_FPS} FPS，"
          f"实际标称 {actual_fps:.1f} FPS")

# ── 6. 打印输入源信息 ─────────────────────────────────────────
print("=" * 40)
print("         输入源信息")
print("=" * 40)
print(f"  分辨率:      {actual_width}x{actual_height}")
print(f"  标称帧率:    {actual_fps:.1f} FPS  ← 摄像头自己上报，不一定准确")
if total_frames > 0:
    # 只有视频文件才有总帧数
    duration = total_frames / actual_fps if actual_fps > 0 else 0
    print(f"  总帧数:      {total_frames} 帧")
    print(f"  视频时长:    {duration:.1f} 秒")
print("=" * 40)

# ── 7. 初始化统计变量 ─────────────────────────────────────────
frame_index    = 0
loop_fps       = 0.0    # 推理循环帧率（包含读帧+推理+显示所有耗时）
last_loop_time = time.time()

total_infer_ms = 0.0
start_time     = time.time()

# 用于实测摄像头真实采集帧率的变量
# 原理：每隔1秒数一次实际读到了多少帧，比标称值更可信
camera_frame_count = 0          # 当前1秒内读到的帧数
camera_fps_timer   = time.time() # 上次刷新实测帧率的时间
real_camera_fps    = 0.0         # 实测摄像头帧率

# ── 8. 逐帧处理循环 ───────────────────────────────────────────
while True:
    ret, frame = cap.read()
    if not ret:
        break

    # ── 9. 实测摄像头帧率 ─────────────────────────────────────
    # 每成功读到一帧就计数+1
    camera_frame_count += 1
    elapsed = time.time() - camera_fps_timer

    # 每隔1秒刷新一次实测帧率
    # 用实际读到的帧数除以经过的时间，得到真实采集帧率
    if elapsed >= 1.0:
        real_camera_fps    = camera_frame_count / elapsed
        camera_frame_count = 0
        camera_fps_timer   = time.time()

    # ── 10. 推理 + 计时 ───────────────────────────────────────
    t_start = time.time()
    results = model(frame, verbose=False)
    t_end   = time.time()

    infer_ms        = (t_end - t_start) * 1000
    total_infer_ms += infer_ms

    # ── 11. 计算推理循环帧率 ──────────────────────────────────
    # 这个 FPS 反映的是整个循环的速度
    # 包含：读帧 + 推理 + 画框 + 显示，所有耗时都算在内
    loop_fps       = 1.0 / (t_end - last_loop_time)
    last_loop_time = t_end

    # ── 12. 可视化 ────────────────────────────────────────────
    annotated_frame = results[0].plot()

    # ── 13. 把信息叠加到画面上 ────────────────────────────────
    # Loop FPS   : 推理循环实际速度
    # Camera FPS : 摄像头真实采集帧率（实测值，非标称值）
    # 两者对比，能直观看出摄像头是否真的在跑高帧率
    cv2.putText(annotated_frame, f"Loop FPS:   {loop_fps:.1f}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(annotated_frame, f"Camera FPS: {real_camera_fps:.1f}",
                (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(annotated_frame, f"Infer:      {infer_ms:.1f} ms",
                (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(annotated_frame, f"Frame:      {frame_index}",
                (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(annotated_frame, f"Size:       {actual_width}x{actual_height}",
                (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    # ── 14. 输出控制：缩放显示画面 ────────────────────────────
    # 推理始终在原始分辨率上进行，缩放只影响显示
    # 这样既保证了推理精度，又能控制窗口大小
    if DISPLAY_WIDTH is not None and DISPLAY_HEIGHT is not None:
        display_frame = cv2.resize(
            annotated_frame,
            (DISPLAY_WIDTH, DISPLAY_HEIGHT),
            interpolation=cv2.INTER_LINEAR  # 线性插值，缩放效果和速度的平衡
        )
    else:
        display_frame = annotated_frame

    # ── 15. 显示画面 ──────────────────────────────────────────
    # ★ 修复：原版这行被注释掉了，脚本跑起来根本看不到窗口
    cv2.imshow("Detection", display_frame)
    # ── 16. 退出机制 ──────────────────────────────────────────
    # ★ 修复：pollKey 不驱动 GUI 事件，窗口会假死/不刷新
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q') or key == 27:
        break

    frame_index += 1

# ── 17. 释放资源 ──────────────────────────────────────────────
cap.release()
cv2.destroyAllWindows()

# ── 18. 控制台统计输出 ────────────────────────────────────────
total_time   = time.time() - start_time
avg_infer_ms = total_infer_ms / frame_index if frame_index > 0 else 0
avg_fps      = frame_index / total_time     if total_time  > 0 else 0

print("=" * 40)
print("         推理任务统计")
print("=" * 40)
print(f"  总处理帧数:    {frame_index} 帧")
print(f"  总耗时:        {total_time:.1f} 秒")
print(f"  平均Loop FPS:  {avg_fps:.1f}")
print(f"  平均推理耗时:  {avg_infer_ms:.1f} ms")
print("=" * 40)
