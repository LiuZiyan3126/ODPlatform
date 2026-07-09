# ODPlatform — 目标检测开发平台

基于 YOLO 的目标检测教学平台，提供数据处理、验证、训练、评估、推理的完整机器学习工作流，支持 CLI 和桌面 GUI 两种使用方式。

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/LiuZiyan3126/ODPlatform.git
cd ODPlatform

# 2. 创建 conda 环境
conda create -n odplat python=3.10 -y
conda activate odplat

# 3. 安装核心引擎（必装）
pip install -e apps/platform

# 4. 安装桌面端（可选，需要 GUI）
pip install -e apps/desktop
```

## 使用方式

### CLI 命令行

```bash
odp-init                                    # 初始化项目目录
odp-transform --dataset fire --format pascal_voc --task detect --split-mode preserve --classes fire human-fire
odp-validate --dataset fire --task detect
odp-gen-config train                        # 生成训练配置模板
odp-train --epochs 300 --batch 16 --device 0 --model yolo11n.pt --data fire.yaml --yaml train.yaml --experiment-name fire_v1
odp-infer --source fire.mp4 --model train-4-xxx-best.pt --show
```

### 桌面 GUI

```bash
od-desktop
```

6 个功能 Tab：项目管理 → 数据流水线 → 数据质检 → 配置编辑 → 模型训练 → 模型推理（实时预览）。

## 环境要求

| 依赖 | 版本 |
|------|------|
| Python | >= 3.10 |
| PyTorch | >= 2.1.1 |
| Ultralytics | >= 8.4.82 |
| PySide6 | >= 6.6.0（仅桌面端） |
| Pydantic | >= 2.13.4 |

## 目录结构

```
ODPlatform/
├── apps/
│   ├── platform/          # 核心引擎（训练 + 推理）
│   ├── desktop/           # 桌面 GUI（PySide6）
│   ├── web-backend/       # Web 后端（占位）
│   └── web-frontend/      # Web 前端（占位）
├── data/
│   ├── raw/               # 原始数据集
│   └── processed/         # 处理后的数据集
├── models/
│   ├── pretrained/        # 预训练权重
│   └── trained/           # 训练产物
├── configs/
│   ├── datasets/          # 数据集 YAML
│   └── runtime/           # 训练/推理运行时配置
├── runs/                  # 训练/推理运行产物
├── resources/             # 设计文档
└── docs/                  # 项目文档
```

## 可用模型

| 模型 | 路径 | 说明 |
|------|------|------|
| yolo11n | `models/pretrained/yolo11n.pt` | COCO 80 类预训练 |
| fire-best | `models/trained/train-4-20260707-233005-yolo11n-best.pt` | 火灾检测训练产物 |

> 模型权重文件不进入 Git，需自行下载或训练生成。
