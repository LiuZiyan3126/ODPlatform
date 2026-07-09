# ODPlatform 项目完成情况进度记录

> 最后更新: 2026-07-09 (团队扩展合并完成)

## 总体进度

| 子系统 | 核心功能 | 扩展项 | 文档 |
|--------|---------|--------|------|
| D1 项目初始化 | ✅ 完成 | — | ✅ |
| D2 项目重置 | ✅ 完成 | ✅ 备份打包 | ✅ |
| D3 数据流水线 | ✅ 完成 | ✅ preserve 模式 + 4种策略 + SHA-256 指纹 | ✅ |
| D4 数据质检 | ✅ 完成 (9项) | ✅ CSV/HTML 报告 + Pascal VOC 修正 | ✅ |
| D5 运行时配置 | ✅ 完成 | — | ✅ |
| D6 训练系统 | ✅ 完成 | ✅ 训练报告 (MD+HTML) + auto-eval | ✅ |
| D7 模型评估 | ✅ 完成 | ✅ 多模型对比 + 评估报告 | ✅ |
| D8 推理系统 | ✅ 完成 | ✅ 帧源注册表 + 视频 stride | ✅ |
| **桌面端** | **✅ 已完成** | — | ✅ |
| Web 端 | ⬜ 未实现 | — | — |

✅ 完成 | 🟡 部分完成 | ⬜ 未开始 | ❌ 无代码

---

## 团队分工与贡献

| 成员 | 负责模块 | 主要贡献 |
|------|---------|---------|
| 本项目 (主体) | D1-D8 核心架构 + 桌面端 | 项目基础设施、推理系统、帧源、可视化、PySide6 GUI (26 .py) |
| 成员1 | D6 扩展 + D7 新建 | 训练报告系统、模型评估系统 (ValService + compare_models) |
| 成员4 | D3 扩展 + D4 扩展 | 数据流水线 (preserve/策略/指纹)、质检扩展 (9项+报告)、Pascal VOC 修正 |

---

## D3 数据流水线 — 扩展详情 ✅

> 来源: 成员4 (`resources/四号扩展.md` §1-3)

### split_mode: 保留已有划分

- 新增 `--split-mode {resplit,preserve}` 参数
- `resplit` (默认): 转换格式后重新划分
- `preserve`: 读取已有 `train/valid/test` 目录，只做格式转换 (Roboflow 兼容)
- 实现: `DatasetPipeline.run()` 拆分为 `_run_resplit()` + `_run_preserve_split()`

### 4 种划分策略

| 策略 | 说明 | requires_labels |
|------|------|:---:|
| `random` | 随机划分 (原始) | No |
| `stratified` | 单标签分层 (最稀有类别为代表) | Yes |
| `stratified_multilabel` | 多标签分层 (稀有标签优先迭代分配) | Yes |
| `hash` | BLAKE2b 稳定哈希 (增量数据不变) | No |

- 文件: `data_pipeline/split/strategies/` 下 6 个模块
- 通过 `@register_strategy` 装饰器注册，`split_service.py` 统一调度

### SHA-256 数据指纹

- 记录在 YAML `odp_meta.fingerprint`，schema_version 升级为 2
- 覆盖: 类别名+索引 + split 归属 + 文件名 + 文件内容 (分块 SHA-256)
- 总指纹 + 3 个 split 子指纹，可定位变化的 split
- 路径无关: 数据集搬迁后指纹不变
- 文件: `data_pipeline/split/fingerprint.py`
- 测试: `tests/test_dataset_fingerprint.py`

---

## D4 数据质检 — 扩展详情 ✅

> 来源: 成员4 (`resources/四号扩展.md` §4-6)

### 9 项检查 (原 5 项 + 新增 5 项 - 1 项 placeholder)

| # | 检查项 | PASS | INFO | WARNING | ERROR |
|---|--------|------|------|---------|-------|
| 1 | yaml_schema | 结构完整 | — | — | 结构缺失 |
| 2 | pair_existence | 全部配对 | — | — | 图片/标签不匹配 |
| 3 | label_format | 格式合法 | — | — | 数值越界/格式错误 |
| 4 | split_uniqueness | 无重复 | — | — | 样本跨集合重复 |
| 5 | **orphan_labels** | 无孤儿 | <10% | ≥10% | — |
| 6 | **empty_labels** | 无空标签 | <20% | ≥20% | — |
| 7 | **image_integrity** | 全部可解码 | Pillow 不可用 | — | 图片损坏 |
| 8 | **annotation_geometry** | 几何合法 | — | — | 零面积框/越界框 |
| 9 | **fingerprint_integrity** | 指纹一致 | 旧 YAML 无指纹 | — | 指纹不一致 |

加粗为新增项。`placeholder.py` 为注册机制冒烟测试，不计入有效检查项。

### CSV + HTML 质检报告

- `odp-validate` 现在同时生成: `report.json` + `issues.csv` + `report.html`
- CSV: BOM UTF-8，公式注入防护，逐行记录问题数据 + 修复建议
- HTML: 自包含单页面，统计卡 + 问题表 (固定高度滚动) + 中文修复建议
- `validate_dataset/artifacts.py`: 统一 `IssueRecord` 结构，8 个字段
- 各检查项扩展 `details` 输出完整文件列表 (不再只截断 preview)
- 测试: `tests/test_validation_artifacts.py`

### Pascal VOC 坐标修正

- **问题**: VOC 从 1 开始坐标，旧转换直接除宽高 → 345/5210 框越界
- **修复**: `_voc_box_to_yolo()` 先 `xmin-1` 转 0-based，clip 到 `[0,W]×[0,H]`
- 修正后 fire 全量 5210 框: `5210 valid / 0 invalid`
- 文件: `data_pipeline/convert/converters/pascal_voc.py`
- 测试: `tests/test_pascal_voc_converter.py`

---

## D6 训练系统 — 扩展详情 ✅

> 来源: 成员1 (`resources/扩展_1.md`)

### 训练报告

- `odp-train` 训练完成后自动生成 Markdown + HTML 报告
- **报告内容**: 训练人/时间/环境/数据集质量引用/超参表格/指标仪表盘/10张可视化/文件清单
- **HTML 特性**: 渐变蓝色 Hero + SVG 纹理、指标卡片 (hover 上浮)、自动着色 (绿≥0.7/橙≥0.4/红<0.4)
- **CLI 新增参数**: `--author`、`--data-quality-report`、`--auto-eval`
- 文件: `training/report.py`
- 零外部依赖: 纯本地字符串拼接 + CSS 内嵌

### 实际训练验证

| 实验 | 配置 | val mAP50 | val mAP50-95 |
|------|------|:---:|:---:|
| 原始版 | AdamW / lr0=0.01 / 1 epoch | 0.342 | 0.153 |
| 失败版 | SGD / lr0=0.001 / 1 epoch | 0.088 | 0.042 |
| **优化版** | **AdamW / lr0=0.002 / 10 epochs** | **0.689** | **0.414** |

优化版 mAP50 提升 **101%** (0.342 → 0.689)。

---

## D7 模型评估 — 新建完成 ✅

> 来源: 成员1 (`resources/扩展_1.md`)

### ValService (单模型评估)

- 流程: `build_val_config()` → `resolve_model_path()` → `model.val()` → 提取指标 → `od_eval_audit.json` → MD/HTML 报告
- 支持 test/val/train 分片
- 复用 TrainMetrics 指标结构
- 文件: `evaluation/service.py`、`evaluation/report.py`

### compare_models (多模型对比)

- 终端: ANSI 彩色表格，每列最优值绿色 ▲ 标记
- Markdown: 对比表 + 自动结论 (每模型优势指标)
- 流程: 对每个模型逐一调用 ValService.evaluate() 后汇总
- 文件: `evaluation/compare.py`

### CLI 入口

- `odp-eval`: 单模型评估
- `odp-compare`: 多模型对比

### 三模型对比结果 (test 分片)

| 模型 | mAP@50 | mAP@50-95 | Precision | Recall |
|------|:---:|:---:|:---:|:---:|
| 原始版 1epoch | 0.420 | 0.189 | 0.508 | 0.512 |
| 失败版 SGD | 0.123 | 0.057 | 0.774 | 0.014 |
| **优化版 10epoch ▲** | **0.674** | **0.393** | **0.752** | **0.518** |

---

## D8 推理系统 — 扩展详情 ✅

- **帧源注册表**: `frame_source/registry.py` + 自动注册机制 (`@register`)
- **4 种帧源**: camera / video / image / folder (各自独立模块)
- **视频 stride**: `cv2.VideoCapture.grab()` 不解码高效跳过
- **可移植**: `frame_source/` 零依赖宿主项目，可整包拷走

---

## 桌面端 — 完成详情

### 文件清单 (26 个 Python 文件)

```
apps/desktop/
├── pyproject.toml                           # CLI 入口 od-desktop
├── src/od_desktop/
│   ├── app.py                               # QApplication + 深色主题
│   ├── main_window.py                       # QMainWindow + 6 Tab + 优雅关闭
│   ├── pages/ (6 个页面全部完成)
│   │   ├── project_page.py                  # 系统信息 + 初始化/重置
│   │   ├── data_pipeline_page.py            # 数据转换 + 划分
│   │   ├── validation_page.py               # 数据质检 + 结果表格
│   │   ├── config_editor_page.py            # 配置编辑 (Form + YAML 双模式)
│   │   ├── training_page.py                 # 训练 + 日志解析进度
│   │   └── inference_page.py                # 推理 + 实时预览
│   ├── workers/ (5 个)
│   │   ├── base_worker.py                   # QThread 基类
│   │   ├── pipeline_worker.py               # DatasetPipeline.run()
│   │   ├── validation_worker.py             # validate_dataset()
│   │   ├── training_worker.py               # train_yolo() + 日志解析
│   │   └── inference_worker.py              # infer_yolo() + CancelToken
│   ├── widgets/ (6 个)
│   │   ├── log_viewer.py                    # QtLogHandler 桥接
│   │   ├── progress_panel.py                # QProgressBar + 状态
│   │   ├── config_form.py                   # Pydantic → Qt 表单
│   │   ├── yaml_editor.py                   # QSyntaxHighlighter 6 色
│   │   ├── frame_viewer.py                  # BGR ndarray → QPixmap (30FPS)
│   │   └── check_results_table.py           # 质检结果 + 颜色编码
│   └── sinks/
│       └── qt_signal_sink.py                # OutputSink → Qt 信号
```

### 已修复的 Bug

| Bug | 修复 |
|-----|------|
| `QPlainTextEdit.setTextColor` 不存在 | 改用 `QTextCharFormat` + `setCurrentCharFormat` |
| ConfigForm Optional 类型检测错误 | 改用 `types.UnionType` + `get_args` |
| ConfigForm 约束读取 | 改用 `getattr(field_info, 'ge/le')` |
| QtSignalSink QObject/ABC 元类冲突 | duck typing 实现协议 |
| QHBoxLayout.addWidget(toolbar) | 改为 `addLayout(toolbar)` |
| validation_page.py 缺少 QColor import | 添加 `from PySide6.QtGui import QColor` |

### 实现阶段回顾

| Phase | 内容 | 状态 |
|-------|------|------|
| 1 | 骨架 + 项目页面 (系统信息/初始化/重置) | ✅ |
| 2 | 数据流水线 (格式转换 + 划分) | ✅ |
| 3 | 数据质检 (检查结果表格 + 详情) | ✅ |
| 4 | 配置编辑器 (Pydantic表单 + YAML双向同步) | ✅ |
| 5 | 模型训练 (日志解析 epoch/loss 进度) | ✅ |
| 6 | 模型推理 (QtSignalSink + FrameViewer 实时预览) | ✅ |
| 7 | 打磨 (ConfigForm修复/优雅关闭/空状态) | ✅ |

---

## 各子系统核心文件

### D1 — 项目初始化 ✅
- `common/paths.py`: 标记文件模式根目录、APP_DIR
- `common/logging_utils.py`: 彩色控制台 + 文件日志
- `common/system_utils.py`: 环境快照 (OS/CPU/GPU/Memory)
- `cli/init_project.py`: 完整实现

### D2 — 项目重置 ✅
- `cli/reset_project.py`: dry-run、RESET 键入确认、审计上下文、Windows 只读文件处理
- 支持 `--yes` 确认删除、`--no-backup` 跳过备份

### D5 — 运行时配置 ✅
- Pydantic 模型 + YAML 合并 + CLI 覆盖 + 审计溯源
- `ConfigGenerator` 反射生成 YAML 模板
- CONFIG_REGISTRY: train/val/infer 三种

---

## 报告系统 ✅

| 报告类型 | 格式 | 触发方式 |
|---------|------|---------|
| 训练报告 | MD + HTML | `odp-train` 自动生成 |
| 评估报告 | MD + HTML | `odp-eval` |
| 多模型对比 | MD | `odp-compare` |
| 质检报告 | JSON + CSV + HTML | `odp-validate` |
| 统一索引 | HTML | `odp-reports export` |

CLI `odp-reports`: 一键发现 + 导出训练/评估/质检/对比/数据流水线五类报告。

---

## 测试覆盖

| 测试文件 | 覆盖范围 |
|---------|---------|
| `test_split_strategies.py` | 策略自动发现、分层容量、哈希稳定性 |
| `test_dataset_fingerprint.py` | 路径无关性、内容变化、split变化 |
| `test_extended_validation_checks.py` | 5项新增质检、segment 任务解析 |
| `test_pascal_voc_converter.py` | VOC 1-based→0-based、越界裁剪 |
| `test_validation_artifacts.py` | CSV/HTML 报告生成、IssueRecord 结构 |

---

## 可用模型

| 模型 | 路径 | 说明 |
|------|------|------|
| yolo11n | `models/pretrained/yolo11n.pt` | COCO 80类预训练 |
| fire-best | `models/trained/train-4-20260707-233005-yolo11n-best.pt` | fire 火灾检测 (mAP50=0.689) |
| fire-best (ONNX) | `models/trained/...-best.onnx` | ONNX 导出 |
| fire-best (FP16) | `models/trained/...-best.fp16.onnx` | FP16 ONNX |
| fire-best (TensorRT) | `models/trained/...-best.engine` | TensorRT 引擎 |

## 可用数据集

- `data/raw/fire/` — 火灾检测 (Pascal VOC, 预划分 train/valid/test)
- 处理后生成: `apps/platform/configs/datasets/fire.yaml` (含 SHA-256 指纹)

## 其他扩展项

| 扩展项 | 状态 | 优先级 |
|--------|------|--------|
| Web 端 (Vue/FastAPI 或 Streamlit) | ⬜ 未开始 | P1 |
| 大模型 API 集成（检测结果建议） | ⬜ 未开始 | P2 |
| 智能体扩展（CLI 封装为工具） | ⬜ 未开始 | P2 |
| COCO segment 支持 | ⬜ 未开始 | P2 |
| Word 质检报告 | ⬜ 依赖 python-docx 已安装 | P2 |

## 已知技术债务

详见 `resources/data-pipeline-assessment-20260701.md`:
- `orchestrator.py` 与 service 重复校验
- 五个子包 `__init__.py` 无公开 API 导出
- `Pair = Tuple[Path, Path]` 语义缺失
- `materializer` 无回滚机制

## 文件统计

| 分类 | 数量 |
|------|:---:|
| `od_platform/` 核心源码 (.py) | 82+ |
| `od_desktop/` 桌面端 (.py) | 26 |
| CLI 命令 | 11 |
| 正式测试文件 | 7 |
| 数据质检项 | 9 |
| 划分策略 | 4 |
| 帧源类型 | 4 |
| 训练实验 | 3 (含 1 次失败对照) |

## Git 仓库

- **Remote**: `https://github.com/LiuZiyan3126/ODPlatform.git`
- **当前分支**: master
- **扩展文档**: `resources/四号扩展.md` (成员4)、`resources/扩展_1.md` (成员1)、`resources/项目扩展项_2.md` (需求清单)
