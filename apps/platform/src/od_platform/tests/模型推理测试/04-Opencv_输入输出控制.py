#!/usr/bin/env python
# -*- coding:utf-8 -*-

# @FileName  :04-Opencv_输入输出控制.py
# @Time      :2026/7/7 10:05:13
# @Author    :雨篷同学
# @Project   :ODPlatform
# @Function  :

import cv2, time
from ultralytics import YOLO


# 输入控制
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 90


# 输出控制
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 720


model = YOLO('./train3-20250704-165500-yolo11n-best.pt')
cap = cv2.VideoCapture(0)


# 设置摄像头参数
cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)


# 拿一下实际的信息
actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
actual_fps = int(cap.get(cv2.CAP_PROP_FPS))

total_frame = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
if total_frame > 0:
    print(f"摄像头参数: {actual_width}x{actual_height} @ {actual_fps}, 总帧数: {total_frame}")
else:
    print(f"摄像头参数: {actual_width}x{actual_height} @ {actual_fps} (没有总帧数)")

frame_index = 0
fps = 0.0
last_time = time.time()

while True:
    ret, frame = cap.read()  # 读取摄像头的帧画面
    if not ret:
        break

    t_start = time.time()
    results = model(frame, verbose=False)  # 控制点，只让模型进行推理，不显示结果
    t_end = time.time()
    infer_ms = (t_end - t_start) * 1000

    now = time.time()
    fps = 1.0 / (now - last_time)
    last_time = now

    annotated_frame = results[0].plot()  # 这里可以拿到推理结果的图片
    cv2.putText(annotated_frame, f"FPS: {fps:.2f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    cv2.putText(annotated_frame, f"Infer: {infer_ms:.2f}", (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    cv2.putText(annotated_frame, f"Frame: {frame_index}", (10, 90),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    cv2.putText(annotated_frame, f"Size: {actual_width} * {actual_height}", (10, 120),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    # 输出控制
    if DISPLAY_WIDTH is not None and DISPLAY_HEIGHT is not None:
        display_frame = cv2.resize(annotated_frame, (DISPLAY_WIDTH, DISPLAY_HEIGHT), interpolation=cv2.INTER_AREA)
    else:
        display_frame = annotated_frame
    cv2.imshow('frame', display_frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q') or key == 27:
        break
    frame_index += 1

cap.release()
cv2.destroyAllWindows()
