# 模型评估报告 — optimized

## 基本信息

| 字段 | 值 |
|------|-----|
| 评估人 | 李评估 |
| 评估时间 | 2026-07-09 15:24:06 |
| 任务类型 | detect |
| 评估分片 | test |

## 模型与数据

| 字段 | 值 |
|------|-----|
| 模型 | optimized |
| 模型路径 | x |
| 数据集 | fire.yaml |

## 运行环境

| 项目 | 值 |
|------|-----|
| 操作系统 | Windows 11 AMD64 |
| CPU | Intel64 Family 6 Model 183 Stepping 1, GenuineIntel |
| Python | 3.13.13 |
| PyTorch | 2.12.1+cpu |
| Ultralytics | 8.4.83 |

## 整体评估指标

| 指标 | 值 |
|------|-----|
| - | - |
## 逐类指标 (mAP@0.5:0.95)

| 类别 | mAP@50-95 |
|------|-----------|
| - | - |
## 评估可视化

### PR 曲线
![PR curve](./BoxPR_curve.png)

### F1 曲线
![F1 curve](./BoxF1_curve.png)

### 混淆矩阵
![confusion](./confusion_matrix.png)

### 规范化混淆矩阵
![confusion normalized](./confusion_matrix_normalized.png)

### 验证批次预测
![val pred0](./val_batch0_pred.jpg)
![val pred1](./val_batch1_pred.jpg)

## 产出文件

| 类型 | 路径 |
|------|------|
| 输出目录 | `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\runs\eval\val` |
| 审计快照 | `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\runs\eval\val\od_eval_audit.json` |
