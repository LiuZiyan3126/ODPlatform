# 模型评估报告 — train-20260709-112529-yolo11n-best

## 基本信息

| 字段 | 值 |
|------|-----|
| 评估人 | 张对比 |
| 评估时间 | 2026-07-09 12:24:03 |
| 任务类型 | detect |
| 评估分片 | test |

## 模型与数据

| 字段 | 值 |
|------|-----|
| 模型 | train-20260709-112529-yolo11n-best |
| 模型路径 | C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\models\trained\train-20260709-112529-yolo11n-best.pt |
| 数据集 | C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\apps\platform\configs\datasets\fire.yaml |

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
| fitness | 0.1890 |
| metrics/precision(B) | 0.5075 |
| metrics/recall(B) | 0.5123 |
| metrics/mAP50(B) | 0.4197 |
| metrics/mAP50-95(B) | 0.1890 |

## 逐类指标 (mAP@0.5:0.95)

| 类别 | mAP@50-95 |
|------|-----------|
| human-fire | 0.2669 |
| fire | 0.1111 |

## 产出文件

| 类型 | 路径 |
|------|------|
| 输出目录 | `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\runs\eval\val-2` |
| 审计快照 | `C:\Users\不会飞纸飞机\Desktop\实习文档\更新文档\模型训练\ODPlatform\runs\eval\val-2\od_eval_audit.json` |
