#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :demo.py
# @Time      :2026/7/8 11:19:05
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
import cv2
import numpy as np
from od_platform.visualization import BeautifyVisualizer, Detection

def main():
    # 1. 模拟 YOLO 模型类别 + 中文/颜色映射
    labels = ["person", "car", "dog", "cat", "bicycle"]

    viz = BeautifyVisualizer(
        labels=labels,
        label_mapping={
            "person": "人员",
            "car": "汽车",
            "dog": "狗",
            "cat": "猫",
            "bicycle": "自行车",
        },
        color_mapping={
            "person": (0, 255, 0),  # 绿
            "car": (255, 100, 0),  # 橙(BGR 蓝多一点)
            "dog": (0, 100, 255),  # 红橙
            "cat": (255, 0, 255),  # 紫
        },
        default_color=(200, 200, 200),  # 灰
    )

    # 2. 构造一张 720p 测试图 (灰底)
    img = np.full((720, 1280, 3), 60, dtype=np.uint8)

    # 3. 构造 5 个检测框, 覆盖不同位置 / 大小 / 类别
    detections = [
        Detection(box=(100, 100, 400, 500), confidence=0.92, label="person"),
        Detection(box=(500, 200, 900, 600), confidence=0.87, label="car"),
        Detection(box=(950, 100, 1150, 350), confidence=0.78, label="dog"),
        Detection(box=(1100, 50, 1270, 180), confidence=0.95, label="cat"),  # 靠右
        Detection(box=(50, 600, 250, 700), confidence=0.65, label="bicycle"),  # 靠底
    ]

    # 4. 美化绘制 - 用中文映射
    annotated = viz.draw(img, detections, use_label_mapping=True)

    # 5. 显示 + 保存
    cv2.imshow("visualization-demo", annotated)
    cv2.imwrite("demo_output.jpg", annotated)
    print("已保存 demo_output.jpg")
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()