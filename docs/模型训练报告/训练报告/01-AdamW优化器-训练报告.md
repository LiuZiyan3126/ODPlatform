# 训练报告 — smoke_test

## 基本信息

| 字段 | 值 |
|------|-----|
| 训练人 | 张测试 |
| 开始时间 | 2026-07-09 13:25:00 |
| 结束时间 | 2026-07-09 15:24:06 |
| 总耗时 | 10 分 13 秒 |
| 任务类型 | detect |
| 训练状态 | 成功 |

## 运行环境

| 项目 | 值 |
|------|-----|
| 操作系统 | Windows 11 AMD64 |
| CPU | Intel64 Family 6 Model 183 Stepping 1, GenuineIntel |
| Python | 3.13.13 |
| PyTorch | 2.12.1+cpu |
| Ultralytics | 8.4.83 |

## 数据集

| 字段 | 值 |
|------|-----|
| 数据集名称 | fire.yaml |
| 数据集路径 | apps/platform/configs/datasets/fire.yaml |
| 数据质量报告 | 未验证 |

## 训练配置

| 参数 | 值 |
|------|-----|
| model | yolo11n.pt |
| data | fire.yaml |
| epochs | 10 |
| batch | 2 |
| imgsz | 640 |
| optimizer | AdamW |
| lr0 | 0.002 |
| device | cpu |
完整配置见 `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\runs\detect_train\train\od_audit.json`

## 训练结果

| 指标 | 值 |
|------|-----|
| - | - |
## 训练可视化

### 训练曲线
![results](./results.png)

### PR 曲线
![PR curve](./BoxPR_curve.png)

### F1 曲线
![F1 curve](./BoxF1_curve.png)

### 混淆矩阵
![confusion](./confusion_matrix.png)

### 规范化混淆矩阵
![confusion normalized](./confusion_matrix_normalized.png)

### 标签分布
![labels](./labels.jpg)

### 训练批次预览
![train batch0](./train_batch0.jpg)
![train batch1](./train_batch1.jpg)

### 验证批次预测
![val pred0](./val_batch0_pred.jpg)
![val pred1](./val_batch1_pred.jpg)

## 产出文件

| 类型 | 路径 |
|------|------|
| 输出目录 | `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\runs\detect_train\train` |
| 最佳权重 | `x` |
| 最后权重 | `x` |
| 审计快照 | `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\runs\detect_train\train\od_audit.json` |
| 训练日志 | `-` |
