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

## CLI 命令一览

### 项目管理

| 命令 | 功能 |
|------|------|
| `odp-init` | 初始化项目目录结构 |
| `odp-reset` | 重置项目（清除运行时产物，支持 dry-run、备份） |

### 数据工程

| 命令 | 功能 |
|------|------|
| `odp-transform` | 数据集格式转换 + 划分（resplit / preserve 模式） |
| `odp-validate` | 数据集质量验证（9 项检查，退出码 0/1/2） |
| `odp-gen-config` | 生成训练 / 验证 / 推理 YAML 配置模板 |

### 模型训练与评估

| 命令 | 功能 |
|------|------|
| `odp-train` | 训练 YOLO 模型（自动生成训练报告） |
| `odp-eval` | 单模型评估（支持 test / val / train 分片） |
| `odp-compare` | 多模型对比（并列指标 + 终端彩色表格） |

### 推理与终端

| 命令 | 功能 |
|------|------|
| `odp-infer` | 模型推理（支持摄像头 / 视频 / 图片 / 图片文件夹） |
| `od-desktop` | 启动桌面 GUI（6 Tab 全覆盖） |

### 报告系统

| 命令 | 功能 |
|------|------|
| `odp-reports` | 统一报告查询与导出 |

## 完整工作流示例

```bash
# 1. 初始化
odp-init

# 2. 数据流水线（Pascal VOC → YOLO → 划分）
odp-transform --dataset fire --format pascal_voc --task detect --split-mode preserve --classes fire human-fire
# 第二次运行可跳过已完成的划分：
odp-transform --dataset fire --format pascal_voc --skip-if-exists

# 3. 数据质检
odp-validate --dataset fire --task detect
# 产出: report.json + issues.csv + report.html + report.docx

# 4. YAML生成
odp-gen-config train / val / infer
# 产出: train.yaml / val.yaml / infer.yaml

# 5. 模型训练
odp-train --epochs 1 --batch 16 --device 0 --model yolo11n.pt --data fire.yaml --yaml train.yaml --experiment-name fire_smoke_test --author zpx
# 产出: 权重归档 + report.md + report.html + od_audit.json

# 6. 模型评估
odp-eval --model train-4-20260707-233005-yolo11n-best.pt --yaml val.yaml --data fire.yaml
odp-compare --models train-4-20260707-233005-yolo11n-best.pt train-20260708-224717-yolo11n-best.pt --yaml val.yaml --data fire.yaml   # 多模型对比

# 7. 模型推理
odp-infer --source fire.mp4 --batch 1 --warmup 30 --show --model train-4-20260707-233005-yolo11n-best.pt --pipeline-yaml infer_pipeline.yaml --yaml infer.yaml --no-save

# 8. 推理加速
yolo export model=models\trained\train-4-20260707-233005-yolo11n-best.pt format=engine half=True dynamic=True batch=1 workspace=2 device=0

# 9. 重置项目（自动备份后清理）
odp-reset               # 预览（dry-run）
odp-reset --yes         # 备份到 backups/ 后删除
odp-reset --yes --no-backup  # 跳过备份直接删除
```

## 桌面 GUI

```bash
od-desktop
```

6 个功能 Tab：**项目管理** → **数据流水线** → **数据质检** → **配置编辑器** → **模型训练** → **模型推理**（实时预览）。

所有阻塞操作运行在后台 QThread 中，UI 线程保持响应。推理支持实时帧预览和 FPS 统计。

## 核心特性

### 数据流水线
- **格式转换**：支持 Pascal VOC、COCO、YOLO 三种标注格式互转
- **划分策略**：随机 / 哈希（增量稳定） / 分层 / 多标签分层，通过注册表可扩展
- **数据指纹**：SHA-256 指纹记录到 YAML，涵盖类别、文件内容、划分分配
- **智能跳过**：`--skip-if-exists` 自动检测已划分数据，避免重复执行

### 数据质检（9 项检查）
YAML 结构校验、图像-标注配对、空标签、孤儿标签、标签格式、图像完整性、标注几何、划分唯一性、指纹完整性。

每项问题附带 **中文修复建议**，支持 **JSON / CSV / HTML / Word** 四种报告格式。

### 模型训练
- 运行时配置：Pydantic 模型 + YAML 三源合并（默认 → YAML → CLI），配置审计可追溯
- 训练报告：自动生成 Markdown + HTML 报告，包含指标仪表盘、10 张可视化图表、环境快照
- 训练后自动评估（`auto_eval` 选项）

### 模型评估
- 单模型评估：在 test / val / train 分片上运行，生成完整报告
- 多模型对比：同一数据集上并列对比 mAP@50、mAP@50-95、Precision、Recall、Fitness，终端彩色表格 + Markdown 报告

### 帧源捕获（推理输入）
- 4 种输入源：摄像头、视频文件 / 流、单张图片、图片文件夹
- 注册表 + 自动注册机制（`frame_source/` 可整包拷走）
- 视频步长：高效跳过（`cv2.VideoCapture.grab()` 不解码）

### 报告系统
- **统一报告 API**：`odp-reports` 一键发现训练 / 评估 / 质检 / 对比 / 数据流水线五类报告
- **多格式导出**：HTML / Markdown / Word 全覆盖
- **汇总索引**：`odp-reports export` 生成带 index.html 的统一报告目录

### 项目管理
- **项目初始化**：`odp-init` 创建完整目录骨架
- **安全重置**：`odp-reset` 默认 dry-run，删除前自动打包备份为 `.zip`
- **受保护目录**：原始数据、预训练权重、源代码、文档等不会被误删

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
│   └── trained/           # 训练产物归档
├── configs/
│   ├── datasets/          # 数据集 YAML（含指纹）
│   └── runtime/           # 训练 / 验证 / 推理运行时配置
├── runs/                  # 训练 / 评估 / 推理 / 质检运行产物
├── backups/               # 重置前的项目备份
├── scripts/               # 开发脚本
├── resources/             # 设计文档
└── docs/                  # 项目文档
```

## 可用模型

| 模型 | 路径 | 说明 |
|------|------|------|
| yolo11n | `models/pretrained/yolo11n.pt` | COCO 80 类预训练 |
| fire-best | `models/trained/train-4-20260707-233005-yolo11n-best.pt` | 火灾检测训练产物 |

> 模型权重文件不进入 Git，需自行下载或训练生成。
