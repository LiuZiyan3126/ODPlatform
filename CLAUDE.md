# ODPlatform 项目说明

## 项目定位

ODPlatform 是一个基于 YOLO 的目标检测开发平台（教学项目），提供完整的机器学习工作流：数据处理、数据验证、模型训练、模型评估和实时推理。

## 环境

- **Python 环境**: `D:\conda_envs\odplat` (conda)
- **项目根目录**: `D:\lab\internship_school\ODPlatform\ODPlatform`
- **安装方式**: `pip install -e apps/platform` + `pip install -e apps/desktop`

## 技术栈

- **语言**: Python >= 3.10
- **深度学习**: PyTorch >= 2.1.1, Ultralytics >= 8.4.82 (YOLO)
- **数据验证**: Pydantic >= 2.13.4
- **GUI**: PySide6 >= 6.6.0 (Qt 6)
- **构建系统**: Hatchling (PEP 621)
- **代码质量**: ruff (lint), mypy (type check), pytest (test)

## 目录结构

```
ODPlatform/
├── .odp-workspace              # 项目根标记文件（路径解析依据）
├── apps/
│   ├── platform/               # 核心引擎（训练 + 推理 Python 包）
│   │   ├── pyproject.toml      # CLI 入口: odp-init/transform/validate/train/infer 等
│   │   └── src/od_platform/    # 核心源码
│   ├── desktop/                # 桌面端（PySide6，已完成 Phase 1-6）
│   │   ├── pyproject.toml      # CLI 入口: od-desktop
│   │   └── src/od_desktop/     # 桌面端源码 (26 个 .py 文件)
│   ├── web-backend/            # Web 后端（占位）
│   └── web-frontend/           # Web 前端（占位）
├── data/
│   ├── raw/                    # 原始数据（fire 火灾数据集）
│   └── processed/              # 处理后的数据集
├── models/
│   ├── pretrained/yolo11n.pt   # 预训练权重 (COCO 80类)
│   └── trained/train-4-*-best.pt  # fire 数据集训练产物
├── configs/
│   ├── datasets/               # 处理后的数据集 YAML
│   └── runtime/                # 训练/验证/推理运行时配置
├── runs/                       # 训练/推理运行产物
├── resources/                  # 设计文档 D0-D8 + 讲义
├── docs/                       # 项目文档（桌面端实施计划等）
└── scripts/                    # 开发脚本
```

## 核心模块架构

```
od_platform/
├── common/          # 公共基础层（路径/ROOT_DIR、日志、常量、工具）
├── data_pipeline/   # 数据流水线（格式转换 + DatasetPipeline 编排器）
├── validate_dataset/ # 数据质检（5 项检查，@check 装饰器注册）
├── runtime_config/  # 运行时配置（Pydantic 模型 + YAML 三源合并 + 审计）
├── training/        # 训练子系统（TrainService + 归档）
├── inference/       # 推理子系统（多线程流水线 + OutputSink + InferHooks + CancelToken）
├── frame_source/    # 帧输入源（摄像头/视频/图片/文件夹，可整包拷走）
├── visualization/   # 推理结果美化（BeautifyVisualizer）
└── cli/             # CLI 入口（薄层，调 service）
```

**依赖方向**: 严格单向。`common/` 被所有模块依赖，业务模块之间不互相依赖。
**桌面端依赖**: `od_desktop` → `od_platform`（直接 import 服务层，不通过 subprocess）

## CLI 命令

| 命令 | 功能 |
|------|------|
| `odp-init` | 初始化项目目录结构 |
| `odp-reset` | 重置项目（清除运行时产物，支持 dry-run） |
| `odp-transform` | 数据集格式转换 + 划分（resplit/preserve 模式） |
| `odp-validate` | 数据集质量验证（退出码 0/1/2） |
| `odp-gen-config` | 生成训练/验证/推理 YAML 配置模板 |
| `odp-train` | 训练 YOLO 模型 |
| `odp-infer` | 模型推理（支持多种输入源 + 美化 + HUD） |
| `od-desktop` | 启动桌面端 GUI（6 Tab 全覆盖） |

## 桌面端架构

### 6 个页面（Tab）

| Tab | 页面类 | 功能 |
|-----|--------|------|
| 项目 | `ProjectPage` | 系统信息 + 初始化/重置（QThread workers） |
| 数据流水线 | `DataPipelinePage` | 格式转换 + 划分（DatasetPipeline） |
| 数据质检 | `ValidationPage` | 质量检查 + 结果表格（CheckResultsTable） |
| 配置编辑器 | `ConfigEditorPage` | Pydantic 表单 + YAML 编辑器（双向同步） |
| 模型训练 | `TrainingPage` | 训练启动 + 日志解析进度（TrainingWorker） |
| 模型推理 | `InferencePage` | 源选择 + 实时预览（QtSignalSink + FrameViewer） |

### 数据流模式

```
UI Thread ──(启动)──> Worker (QThread) ──(调用)──> od_platform 服务层
  │                                                    │
  └── LogViewer <──(信号)── QtLogHandler ──(捕获)───────┤
  └── ProgressPanel <──(信号)── progress ───────────────┤
  └── FrameViewer <──(信号)── QtSignalSink ──(帧数据)───┤
```

### 关键设计决策

- **所有阻塞调用跑在 QThread 中**，UI 线程只处理 Qt 事件
- **QtSignalSink 实现 OutputSink 协议**（duck typing，不继承 ABC 避免元类冲突）
- **推理帧传递**: 渲染线程 → QtSignalSink.write(copy) → signal(QueuedConnection) → FrameViewer.on_frame → QTimer 30FPS 刷新
- **训练进度**: 自定义 logging.Handler 正则解析 Ultralytics epoch/loss 输出
- **配置表单**: 从 Pydantic model_fields 反射生成（`types.UnionType` 检测 Optional, `getattr(field_info, 'ge/le')` 读取约束）
- **日志桥接**: 根 logger 挂 QtLogHandler，emit 信号到 LogViewer

## 编码约定

- **路径**: 使用 `od_platform.common.paths.ROOT_DIR`（通过 `.odp-workspace` 标记文件向上搜索）
- **依赖**: `apps/platform` 可被 desktop 等端 import，不能反向依赖
- **配置**: Pydantic `BaseConfig` 模型，`extra="forbid"`，DEFAULT → YAML → CLI 三源合并
- **注册表模式**: convert (`@register`)、split (`@register_strategy`)、validate (`@check`) 均使用装饰器 + 懒加载
- **帧源**: `frame_source/` 零依赖宿主项目，可 `cp -r` 整包拷走
- **Worker**: 继承 `BaseWorker(QThread)`，定义 `started/finished/error/progress` 信号
- **PySide6 注意事项**: QPlainTextEdit 没有 `setTextColor`，用 `QTextCharFormat` + `setCurrentCharFormat`

## 可用模型

| 模型 | 路径 | 说明 |
|------|------|------|
| yolo11n | `models/pretrained/yolo11n.pt` | COCO 80类预训练 |
| fire-best | `models/trained/train-4-20260707-233005-yolo11n-best.pt` | fire 火灾检测训练产物 |

## 当前数据集

- `data/raw/fire/` — 火灾检测（Pascal VOC 格式，已预划分 train/valid/test）
- 运行数据流水线后生成 `configs/datasets/fire.yaml`
