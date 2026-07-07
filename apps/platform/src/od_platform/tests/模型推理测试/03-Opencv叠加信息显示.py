#!/usr/bin/env python
# -*- coding:utf-8 -*-

# @FileName  :03-Opencv叠加信息显示.py
# @Time      :2026/7/7 09:45:23
# @Author    :雨镜同学
# @Project   :ODPlatform
# @Function  :
import time
import cv2
from polars.testing.asserts import frame
from ultralytics import YOLO


if __name__ == "__main__":
    model = YOLO('train3-20250704-165500-yolo11n-best.pt')
    cap = cv2.VideoCapture(0)  # 自己打开摄像头

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
        h, w = frame.shape[:2]

        annotated_frame = results[0].plot()  # 这里可以拿到推理结果的图片
        cv2.putText(
            annotated_frame,
            f"FPS: {fps:.2f}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            annotated_frame,
            f"Infer: {infer_ms:.2f} ms",
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            annotated_frame,
            f"Frame: {frame_index}",
            (10, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            annotated_frame,
            f"Frame Size: {w}x{h}",
            (10, 120),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2,
        )

        cv2.imshow("YOLO Inference", annotated_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q") or key == 27:
            break

        frame_index += 1

    cap.release()
    cv2.destroyAllWindows()
