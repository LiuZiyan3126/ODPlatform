# 训练报告 — smoke_test_v2

## 基本信息

| 字段 | 值 |
|------|-----|
| 训练人 | 张测试 |
| 开始时间 | 2026-07-09 11:32:37 |
| 结束时间 | 2026-07-09 11:41:27 |
| 总耗时 | 8 分 50 秒 |
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
| 数据集路径 | C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\apps\platform\configs\datasets\fire.yaml |
| 数据质量报告 | 未验证 |

## 训练配置

| 参数 | 值 |
|------|-----|
| model | yolo11n.pt |
| data | fire.yaml |
| epochs | 1 |
| batch | 2 |
| imgsz | 640 |
| optimizer | SGD |
| lr0 | 0.001 |
| device | cpu |
| amp | True |
完整配置见 `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\runs\detect_train\train-2\od_audit.json`

## 训练结果

| 指标 | 值 |
|------|-----|
| fitness | 0.0418 |
| metrics/precision(B) | 0.7012 |
| metrics/recall(B) | 0.0181 |
| metrics/mAP50(B) | 0.0881 |
| metrics/mAP50-95(B) | 0.0418 |

## 产出文件

| 类型 | 路径 |
|------|------|
| 输出目录 | `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\runs\detect_train\train-2` |
| 最佳权重 | `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\models\trained\train-2-20260709-114127-yolo11n-best.pt` |
| 最后权重 | `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\models\trained\train-2-20260709-114127-yolo11n-last.pt` |
| 审计快照 | `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\runs\detect_train\train-2\od_audit.json` |
| 训练日志 | `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\apps\platform\logging\train_model\train-2_20260709-113237-01069_yolo11n.log` |
