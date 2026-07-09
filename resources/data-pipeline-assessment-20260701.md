# data_pipeline 架构评估报告

> 评估日期: 2026-07-01
> 评估范围: `apps/platform/src/od_platform/data_pipeline/` 全模块
> 状态: 管道已通，convert/split/orchestrator/report/CLI 各层职责分明

---

## 一、模块全景

```
data_pipeline/
├── __init__.py                      # ⚠️ 模板代码，无公开 API 导出
├── orchestrator.py                  # ✅ 编排器：DatasetPipeline.run()
├── report.py                        # ✅ 类别平衡报告（只读，不过滤）
├── convert/                         # ✅ 转换子系统
│   ├── __init__.py                  # ⚠️ 模板代码
│   ├── registry.py                  # ✅ 格式注册表 + @register + ConvertOptions
│   ├── service.py                   # ✅ 调度层：convert_data_to_yolo()
│   └── converters/
│       ├── __init__.py              # ⚠️ 模板代码
│       ├── pascal_voc.py            # ✅ VOC → YOLO
│       ├── coco.py                  # ⚠️ 声明支持 SEGMENT 但只处理 bbox
│       └── yolo.py                  # ✅ YOLO 直通
└── split/                           # ✅ 划分子系统
    ├── __init__.py                  # ⚠️ 模板代码
    ├── manifest.py                  # ✅ SplitManifest + Pair/PairList
    ├── strategy_registry.py         # ✅ 策略注册表 + SplitOptions
    ├── split_service.py             # ✅ 调度层：split_pairs()
    ├── materializer.py              # ✅ 落盘：SplitOutputDirs + materialize()
    ├── yaml_writer.py               # ✅ 生成 dataset.yaml
    └── strategies/
        ├── __init__.py              # ⚠️ 模板代码
        ├── _common.py               # ✅ validate_rates / three_way_counts / seeded_shuffled
        └── random_split.py          # ✅ 纯随机划分策略
```

### CLI 入口

```
cli/transform_data.py → orchestrator.DatasetPipeline.run()
```

### 支撑模块

```
common/
├── constants.py          # AnnotationFormat, Task, SplitStrategy, 各类阈值
├── registry_utils.py     # import_submodules (convert 和 split 共用)
├── paths.py              # 全局路径定义
├── refs.py               # 引用解析 (resolve_dataset 等)
├── logging_utils.py      # 彩色日志 + 文件日志
└── string_utils.py       # CJK 感知的表格渲染
```

---

## 二、管道数据流

```
CLI: transform_data.py
       │
       ▼
orchestrator.py (DatasetPipeline.run)
       │
       ├── _check_raw()                  ← 预检：目录存在 + 覆盖率 fail-fast
       ├── convert_data_to_yolo()        ← 标注 → YOLO（写入临时目录，用完即删）
       ├── _pair_images_with_labels()    ← 按 stem 配对 (图, 标) → PairList
       ├── _build_labels_per_image()     ← 读 txt 还原 {图: [类别名]}
       ├── analyze_class_balance()       ← 类别平衡报告（只读，不过滤）
       ├── split_pairs()                 ← 划分 → SplitManifest
       ├── materialize()                 ← 落盘到 data/processed/<name>/train|val|test/
       └── write_dataset_yaml()          ← 生成 configs/datasets/<name>.yaml
```

关键设计决策:
- **data/raw/ 是只读圣地**: 转换中间产物写入 `tempfile.TemporaryDirectory`，出了 with 自动清理
- **按数据集分桶**: 每个数据集独占 `data/processed/<name>/`，多数据集互不覆盖
- **报告与修改分离**: report.py 只打表、只提醒，绝不替用户删数据

---

## 三、架构模式：convert 与 split 完全同构

两个子系统遵循统一模式：**注册表 + 装饰器 + 参数包 + 调度层**。

| 模式要素 | convert | split |
|---------|---------|-------|
| 注册表字典 | `_REGISTRY: Dict[str, ConverterEntry]` | `_STRATEGY_REGISTRY: Dict[str, StrategyEntry]` |
| 装饰器 | `@register(name, supported_tasks=...)` | `@register_strategy(name, requires_labels=...)` |
| 条目类型 | `ConverterEntry(func, supported_tasks)` | `StrategyEntry(func, requires_labels)` |
| 参数包 | `ConvertOptions(task, classes)` | `SplitOptions(train_rate, val_rate, ...)` |
| 统一函数签名 | `(Path, Path, ConvertOptions) -> List[str]` | `(PairList, SplitOptions) -> SplitManifest` |
| 调度层 | `service.convert_data_to_yolo()` | `split_service.split_pairs()` |
| 能力检查点 | `entry.supports(task)` in service | `entry.requires_labels` check in service |
| 懒加载 | `registry_utils.import_submodules` | `registry_utils.import_submodules` |
| 实现目录 | `converters/` (3 个) | `strategies/` (1 个: random) |

**评价**: 新人看懂了 convert 就能秒懂 split。`registry_utils.import_submodules` 在两个子系统间正确复用。

---

## 四、剩余问题

### 🟡 腐化代码（不影响运行，但会积累）

#### 4.1 `orchestrator.py:63-65` — 重复校验

```python
# orchestrator.py 第 63-65 行
entry = get_converter(self.annotation_format)
if not entry.supports(self.task):
    raise ValueError(...)
```

然后第 70 行调用 `convert_data_to_yolo()`，而 `convert/service.py` 里已经做了一遍完全相同的检查。两次 `get_converter` + 两次 `supports` 判断。

**建议**: 删除 orchestrator 中的重复校验，信任 service 层。

#### 4.2 `split_service.py` — 未使用的 import 和 logger

```python
import logging                          # ← 未使用
from typing import Dict, List, Optional # ← Dict、List 未使用（有 `from __future__ import annotations`）

logger = logging.getLogger(__name__)    # ← 创建了但从未调用
```

**建议**: 删掉死代码，或在 `split_pairs` 中加一行 `logger.info("用策略 %s 划分 %d 对样本", strategy, len(pairs))`。

#### 4.3 `random_split.py:11` — 未使用的模块 import

```python
from od_platform.data_pipeline.split import manifest        # ← 从未用 manifest.xxx
from od_platform.data_pipeline.split.manifest import PairList, SplitManifest  # ← 实际只用这个
```

**建议**: 删掉第 11 行。

#### 4.4 `convert/registry.py:4-5` — 腐化注释

```python
# 注:本阶段把"扫描 converters/ 目录"的逻辑【内联】在 _lazy_init 里;等阶段 4 的 split
#    第二张表也要同样扫描时,我们才把它抽进 common/registry_utils.py(第二次才抽象)。
```

代码早已改用 `registry_utils.import_submodules`，注释描述的状态已过时。

**建议**: 更新注释或直接删除（代码即文档）。

#### 4.5 五个 `__init__.py` 无公开 API 导出

| 文件 | 当前内容 |
|------|---------|
| `data_pipeline/__init__.py` | `if __name__ == "__main__": print(...)` |
| `convert/__init__.py` | 同上 |
| `convert/converters/__init__.py` | 同上 |
| `split/__init__.py` | 同上 |
| `split/strategies/__init__.py` | 同上 |

外部调用需要记住每个子模块路径，import 冗长:
```python
from od_platform.data_pipeline.split.manifest import SplitManifest, PairList
from od_platform.data_pipeline.split.split_service import split_pairs
from od_platform.data_pipeline.split.strategy_registry import SplitOptions
from od_platform.data_pipeline.split.materializer import materialize, SplitOutputDirs
from od_platform.data_pipeline.split.yaml_writer import write_dataset_yaml
```

**建议**: 在 `__init__.py` 中收拢公开 API，让外部只需:
```python
from od_platform.data_pipeline.split import split_pairs, SplitManifest, materialize, ...
```

---

### 🟠 设计层面的小问题

#### 4.6 `Pair = Tuple[Path, Path]` 语义缺失

```python
# manifest.py
Pair = Tuple[Path, Path]   # 哪个是图？哪个是标签？
```

`orchestrator.py` 自身就在两种风格间摇摆:
```python
# _pair_images_with_labels
pairs.append((img, lbl))              # 用 img / lbl

# _build_labels_per_image
for img_path, label_path in pairs:    # 用 img_path / label_path
```

**建议**: 改为 `NamedTuple`，`p.image` / `p.label` 自文档化，`p[0]` 仍可用保持向后兼容。

#### 4.7 `SplitOutputDirs.all_dirs()` 顺序混乱

```python
return (self.train_images, self.train_labels, self.test_images,
        self.test_labels, self.val_images, self.val_labels)
#       train → test → val?  应该是 train → val → test
```

不影响正确性（只是遍历删除），但读者会困惑。

**建议**: 调整为 `train → val → test` 顺序。

#### 4.8 两个 service 的 Options 构建模式相反

| | convert | split |
|---|---|---|
| 谁构建 Options | **调用方**构建 `ConvertOptions` 传入 | **service 内部**从散装参数构建 `SplitOptions` |
| 优点 | service 不感知 Options 字段变更 | 调用方少 import 一个类 |
| 缺点 | 调用方需要知道 Options 类 | Options 加字段时 service 签名也要改 |

**建议**: 统一到 convert 的模式——调用方构建 Options 对象，service 只做分发。这样 Options 字段变更不影响 service 签名。

#### 4.9 可变性缺乏统一规则

| 类 | 可变性 |
|----|--------|
| `SplitManifest` | 可变（`random_split` 直接属性赋值） |
| `SplitOutputDirs` | `frozen=True` |
| `SplitOptions` | 可变 |
| `StrategyEntry` | `frozen=True` |
| `ConvertOptions` | 可变 |
| `ConverterEntry` | `frozen=True` |

规律似乎是"注册表条目应不可变"，但 `SplitOutputDirs`（数据容器）打破了这条——它是 `frozen=True` 但 `SplitManifest`（同样是数据容器）是可变的。

#### 4.10 `SplitManifest` 冗余存储 rates + counts

```python
@dataclass
class SplitManifest:
    train: PairList = field(default_factory=list)   # 实际数据
    val: PairList = field(default_factory=list)
    test: PairList = field(default_factory=list)
    train_rate: float = 0.8                          # 声明比例
    val_rate: float = 0.1
    test_rate: float = 0.1                           # 本应是 1.0 - train_rate - val_rate
```

`summary()` 从数据算出 counts，但 rates 是独立字段——可构造不一致状态。无 `__post_init__` 校验。

**建议**: `test_rate` 改为 property（`1.0 - train_rate - val_rate`），或至少加 `__post_init__` 校验。

#### 4.11 `yaml_writer` 与 `SplitOutputDirs` 隐式耦合

```python
# yaml_writer.py
doc = {
    "train": "train/images",    # ← 硬编码
    "val": "val/images",
    "test": "test/images",
}

# materializer.py
class SplitOutputDirs:
    def for_dataset_root(cls, root):
        return cls(
            train_images=root / "train" / "images",   # ← 同一套约定
            ...
        )
```

改了目录结构需要同时改两个文件。

**建议**: 让 `SplitOutputDirs` 暴露相对路径常量，`yaml_writer` 从同一个源头取。

#### 4.12 `materializer` 无回滚机制

```python
def materialize(manifest, dirs):
    for d in dirs.all_dirs():      # 先全量 rmtree
        if d.exists():
            shutil.rmtree(d)
    counts = { ... }                # 再写入
```

如果写入中途失败（磁盘满），旧数据已删，新数据不完整。

**建议**: 先写到临时目录，成功后再原子替换。

---

### 🔵 仍未实现（诚实标注，非缺陷）

| 项 | 说明 |
|----|------|
| **分层划分策略** | `SplitStrategy.STRATIFIED` / `STRATIFIED_MULTILABEL` 常量已声明，`_build_labels_per_image` 已准备好数据，就差策略实现 |
| **COCO segment** | `coco.py` 声明支持 `SEGMENT` 但只处理 bbox，segment 标注（polygon/RLE）未实现 |
| **测试** | 全模块无测试覆盖 |
| **SplitManifest 序列化** | 无法保存/加载划分结果，复现只能靠重跑 + 相同 seed |
| **进度反馈** | 大批量数据集物化时无进度回调或 tqdm |

---

## 五、设计亮点

1. **convert 和 split 子系统完全同构**: 注册表 → 懒加载 → 调度层 → 能力声明 → 实现模块。降低认知负担。

2. **编排器职责清晰**: `DatasetPipeline` 只做"按顺序调用"，不干具体活。具体活全在子模块里。

3. **临时目录隔离**: 转换中间产物写入 `tempfile.TemporaryDirectory`，出了 with 自动清理。`data/raw/` 是只读圣地。

4. **报告与修改分离**: `report.py` 只打表、只提醒，绝不替用户删数据。`--classes` 的决定权在用户。"检查 ≠ 过滤"的边界守得干净。

5. **CLI 入口薄**: `transform_data.py` 只做参数解析 + 调 pipeline，没有业务逻辑。

6. **`registry_utils` 抽取到位**: convert 和 split 的懒加载共用同一段代码。convert 的注释说"第二次才抽象"——确实做到了。

7. **`paths.py` 集中管理路径**: 全局路径定义 + 初始化/重置/保护逻辑，避免路径散落各处。

8. **CJK 感知的表格渲染**: `string_utils.py` 按显示宽度对齐，中文类名不会错位。

---

## 六、建议优先级

| 优先级 | 事项 | 类型 |
|--------|------|------|
| P1 | 删除 `split_service.py` 和 `random_split.py` 中的未使用 import | 腐化清理 |
| P1 | 更新/删除 `convert/registry.py` 的过时注释 | 腐化清理 |
| P2 | 删除 `orchestrator.py` 中与 service 重复的校验 | 冗余代码 |
| P2 | `__init__.py` 导出公开 API | 可用性 |
| P2 | `Pair` 改为 `NamedTuple` | 代码可读性 |
| P3 | 统一 Options 构建模式 | 设计一致性 |
| P3 | `SplitManifest` 加 `__post_init__` | 数据完整性 |
| P3 | `SplitOutputDirs.all_dirs()` 调整顺序 | 可读性 |
| P3 | `yaml_writer` 从 `SplitOutputDirs` 取路径 | 解耦 |
| P3 | `materializer` 加回滚 | 健壮性 |
| — | 实现分层划分策略 | 新功能 |
| — | 补充测试 | 质量保障 |
| — | COCO segment 支持 | 功能补全 |

---

## 七、附录：关键类型一览

```python
# manifest.py
Pair = Tuple[Path, Path]                    # (image_path, label_path)
PairList = List[Pair]
SplitManifest                               # train/val/test 三组 + 元数据

# strategy_registry.py
SplitOptions                                # train_rate, val_rate, random_state, labels_per_image
StrategyFunc = Callable[[PairList, SplitOptions], SplitManifest]
StrategyEntry(func, requires_labels)        # 注册表条目

# convert/registry.py
ConvertOptions(task, classes)               # task, classes
ConverterFunc = Callable[[Path, Path, ConvertOptions], List[str]]
ConverterEntry(func, supported_tasks)       # 注册表条目

# materializer.py
SplitOutputDirs                             # train/val/test × images/labels 六个目录

# report.py
ClassStat(name, image_count, box_count, image_pct, box_pct, status)
ClassBalanceReport(stats, total_images, total_boxes, usefulness_img_floor)

# orchestrator.py
DatasetPipeline(dataset, annotation_format, task, train_rate, val_rate, classes, random_state, split_strategy)
#   .run() → {"counts": ..., "yaml": ...}
```
