# ODPlatform 项目说明

## 项目定位

ODPlatform 是一个基于 YOLO 的目标检测开发平台（教学项目），提供完整的机器学习工作流：数据处理、数据验证、模型训练、模型评估和实时推理。

## 技术栈

- **语言**: Python >= 3.10
- **深度学习**: PyTorch >= 2.1.1, Ultralytics >= 8.4.82 (YOLO)
- **数据验证**: Pydantic >= 2.13.4
- **数据处理**: Pandas >= 3.0.3
- **构建系统**: Hatchling (PEP 621)
- **代码质量**: ruff (lint), mypy (type check), pytest (test)

## 目录结构

```
ODPlatform/
├── .odp-workspace              # 项目根标记文件（路径解析依据）
├── apps/                       # 可交付应用
│   ├── platform/               # 核心引擎（训练 + 推理 Python 包）
│   │   ├── pyproject.toml      # 包配置与 CLI 入口
│   │   └── src/od_platform/    # 核心源码
│   ├── desktop/                # 桌面端（PySide6，待开发）
│   ├── web-backend/            # Web 后端（占位）
│   └── web-frontend/           # Web 前端（占位）
├── data/                       # 共享数据
│   ├── raw/                    # 原始数据（只读）
│   └── processed/              # 处理后的数据集
├── models/                     # 模型权重
│   ├── pretrained/             # 预训练权重
│   └── trained/                # 训练产物
├── runs/                       # 训练运行产物（日志、检查点）
├── resources/                  # 设计文档与课程讲义（D0-D8）
├── docs/                       # 项目文档（分工、扩展说明）
└── scripts/                    # 开发脚本
```

## 核心模块架构

```
od_platform/
├── common/          # 公共基础层（路径、日志、常量、工具）—— 所有模块的依赖
├── data_pipeline/   # 数据流水线（格式转换 + 数据集划分）
├── validate_dataset/ # 数据质检系统
├── runtime_config/  # 运行时配置系统（Pydantic 模型 + YAML 合并）
├── training/        # 训练子系统
├── inference/       # 推理子系统
├── frame_source/    # 统一帧输入源抽象层（摄像头/视频/图片/文件夹）
├── visualization/   # 推理结果美化
└── cli/             # CLI 命令行入口
```

**依赖方向**: 严格单向。`common/` 被所有模块依赖，业务模块之间不互相依赖。

## CLI 命令

| 命令 | 功能 |
|------|------|
| `odp-init` | 初始化项目目录结构 |
| `odp-reset` | 重置项目（清除运行时产物） |
| `odp-transform` | 数据集格式转换 + 划分 |
| `odp-validate` | 数据集质量验证 |
| `odp-gen-config` | 生成训练/验证/推理配置文件 |
| `odp-train` | 训练 YOLO 模型 |
| `odp-infer` | 模型推理（支持多种输入源） |

## 编码约定

- **路径**: 使用 `od_platform.common.paths.ROOT_DIR` 解析项目根目录，不硬编码路径
- **依赖**: `apps/platform` 可被其他端 import，但不能反向依赖
- **配置**: 使用 `runtime_config` 的 Pydantic 模型，支持 DEFAULT -> YAML -> CLI 三源合并
- **注册表模式**: convert 和 split 子系统使用 `@register` 装饰器 + 懒加载自动发现
- **帧源**: `frame_source/` 模块零依赖宿主项目，可整包拷走
- **日志**: 使用 `common/logging_utils.py` 的统一日志接口，支持彩色控制台 + 文件输出
- **代码质量**: poetry 风格的 src-layout，ruff 检查，mypy 类型检查

## 资源文档

设计文档位于 `resources/` 目录：
- D0: 设计指南与架构决策
- D1-D8: 各子系统设计文档
- `frame_source_四源版_讲义.md`: 帧源模块讲义
- `项目扩展项.md`: 扩展功能列表
- `data-pipeline-assessment-20260701.md`: 数据流水线架构评估

## 当前状态

核心引擎（D0-D8）基本完成。扩展项（桌面端、Web 端、数据指纹、分层策略等）详见 `AGENTS.md`。
