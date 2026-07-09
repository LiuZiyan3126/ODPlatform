# ODPlatform D6: training 子系统

> **课程定位**: 实训第 6 天讲义
>
> **核心叙事**: 从 D5 立好的 `runtime_config/` 子系统出发, 把【D2 日志 + D4 校验 + D5 配置 + ultralytics 训练】四方接起来——构建一个完整的 `training/` 子系统, 顺手获得**业务日志干净接入 D2 通道**、**训练前数据集 fail-fast 校验**、**ultralytics save_dir 跟 logging 文件名一眼能配对**、**权重归档 + audit 快照给 experiment_db 留落点**.
>
> **三面真撞墙** (D6 是\"接好\"不是\"立新\", 撞墙集中在【边界纪律】上):
> 1. **朴素方案: 一切都在 `train.py` 里** → 推出 TrainService 编排器 + 边界纪律
> 2. **handler 装哪里? `logging.getLogger()` 不带参数 ≠ `\"odp_platform\"`** → 推出"业务模块只发声, handler 只在 CLI 入口装一次"硬纪律
> 3. **日志文件名怎么跟 ultralytics save_dir 对齐? rename 跑在哪个根 logger 上?** → 推出"操作 D2 named root, 永不操作 unnamed root"的实现纪律
>
> **配套上一节**: 《D5: runtime_config 子系统》
>
> **配套下一节**: 《D7: evaluation 子系统》(D6 立训练侧, D7 用 D6 归档的 best/last 做验证)
>
> **设计原则**: **training 子系统是【编排器】, 不是【发明者】**——D6 内部不再写 YAMLLoader / ConfigMerger / validate_dataset / get_logger, 这些 D2 / D4 / D5 已经做完了, D6 只负责把它们用对地方接起来. 当你的编排器代码比你接到的工具还重, 说明你抢错了戏.
>
> **建议时长**: 5-6 课时 (比 D5 短 — D5 立 7 个新模块, D6 只立 2 个训练专属 + 6 个 common 工具, 复杂度降一档)

---

## 📌 跨平台命令说明

沿用 D2 / D3 / D4 / D5 的约定, 本文不再重复. 需要区分平台时用并列代码块, 普通 `python` / `pip` / `git` 命令跨平台一致只写一次. Windows 用户**推荐 Git Bash**——绝大多数命令直接跟 Linux 走, 省心.

---

## 文档使用说明

D6 的产物有两类: **代码**和**对代码的解释**.

- **完整代码**: 每个文件都是终态, 可直接复制粘贴
- **⚠️ 设计点框**: 容易写错或容易选错的地方提前告诉你
- **🧱 撞墙时刻**: 仅 3 次, 亲手体验
- **🤔 思考题**: 给读者 30 秒, 思考再往下看
- **shell 命令**: 测试 / 运行 / git 操作
- **git commit**: 每个里程碑对应一次提交

**强烈建议**: **跟着文档自己敲一遍**——D6 的核心价值不在"代码长什么样", 在"为什么把这块拆到 common/、那块留在 training/、handler 装在 cli 不装在 service". 这些边界判断不亲手过一遍, 看到 D7 / D8 写出来"验证模块从训练模块 import"才会理解.

---

## 上一节回顾 + 本节挑战

D5 解决了\"我的训练**怎么跑**?\"——一份 Pydantic `YOLOTrainConfig` + 一行 `build_train_config(yaml_path, cli_args)` 拿到合并好的配置 + `ConfigMerger` 记录三源溯源, 配置这层守住了.

D6 接下来要回答的问题是: **\"配置都准备好了, 训练怎么跑起来?\"**

听起来很简单——`ultralytics.YOLO("yolo11n.pt").train(**config.to_ultralytics_kwargs())` 不就完了? 一行代码的事.

**朴素方案**: 写个 `cli/train.py`, 200 行 argparse 把所有参数列出来, 然后 `args = parser.parse_args(); model = YOLO(args.model); model.train(...)`. 这是绝大多数 yolo 教程的做法.

**问题**: 这套朴素方案在 ODPlatform 这种"端到端实验工程"场景下会暴露 4 个伤痛:

1. **D2/D4/D5 都没接进来**: 配置硬编码在 argparse(D5 白立了), 日志用 `print`(D2 白立了), 数据集校验跳过(D4 白立了)——前 5 天的活全废了.
2. **崩了不知道在训啥**: `Dataset 'rsod.yaml' error 'rsod.yaml' does not exist`——但用户写的明明是相对路径, 应该去 `configs/datasets/` 找; 用户用的什么模型? 在哪个目录找? 谁知道, 错误栈里没有.
3. **训练完日志和结果对不上**: ultralytics 把权重存在 `runs/detect/train3/`(自增编号), 我自己的 `train.log` 存在 `logging/train/train_20260524-091632.log`——用户问\"train3 对应哪份日志?\" `ls` 是看不出来的, 只能开 audit JSON 查.
4. **权重 / audit 都没归档**: 训练完产物分散在 `runs/detect/train3/weights/best.pt`——D7 验证时怎么找到这份 best? 没归档就只能"用户手动复制黏贴", 然后变量名一变, 实验复现就断了.

D6 的任务: **写一个 TrainService 编排器**, 一头接 D5 拿配置, 一头接 D4 做数据校验, 一头接 D2 走日志通道, 一头接 ultralytics 跑训练, 末了再把日志名、权重、audit 三件事整理好——把上面 4 个伤痛一次干掉.

> **金句**: **\"训练子系统不发明任何新方法——把 D2/D4/D5/ultralytics 用对地方接起来就行. 当你的编排器代码比你接到的工具还重, 说明你抢错了戏.\"**

---

## 起点与终点

**起点**: 完成 D5, 仓库当前长这样:

```
apps/platform/src/odp_platform/
├── common/                     (D2 立 + D5 增量)
│   ├── paths.py                (RUNTIME_CONFIGS_DIR 来自 D5)
│   ├── constants.py            (Task.DETECT/SEGMENT)
│   ├── logging_utils.py        (D2: get_logger 挂在 "odp_platform" named root)
│   ├── string_utils.py         (D2: pad_to_width — CJK-aware)
│   ├── system_utils.py         (D2: log_device_info)
│   └── performance_utils.py    (D2)
│
├── data_pipeline/              (D3 产出 — odp-transform 用)
├── data_validation/            (D4 产出 — validate_dataset + render_to_logger)
├── runtime_config/             (D5 产出 — build_train_config + ConfigMerger)
│
├── cli/
│   ├── init_project.py         (odp-init)
│   ├── reset_project.py        (odp-reset)
│   ├── transform_data.py       (odp-transform)
│   ├── validate_data.py        (odp-validate)
│   └── generate_config.py 或 odp-gen-config entry-point  (D5)
│
└── configs/
    ├── datasets/               (D3 立)
    └── runtime/                (D5 立)
```

**终点**: 仓库新增 **6 个 common 工具 + 2 个 training 训练专属 + 1 个 cli 入口**:

```
apps/platform/src/odp_platform/
├── common/                     🔄 D6 增量 (6 个跨任务通用工具)
│   ├── ...(D2/D5 已有)...
│   ├── model_path.py           ✨ resolve_model_path(model, *, search_dirs=...)
│   ├── dataset_path.py         ✨ resolve_dataset_path(data)
│   ├── log_rename.py           ✨ rename_log_to_save_dir(save_dir, model_stem)
│   ├── config_log.py           ✨ log_effective_config + log_override_chains
│   ├── result.py               ✨ TrainMetrics + log_train_metrics
│   └── plot_style.py           ✨ apply_academic_style
│
├── training/                   ✨ D6 产出 — 训练专属(本节主角)
│   ├── __init__.py             (对外公共 API, 只 4 个符号)
│   ├── service.py              (TrainService + TrainResult + train_yolo)
│   └── archive.py              (archive_checkpoints)
│
└── cli/
    └── train_model.py          ✨ odp-train entry-point
```

⚠️ **设计点 (这是 D6 跟 D7/D8 的边界承诺)**: 6 个跨任务通用工具**全部放在 `common/`**——意思是 D7 ValService / D8 InferService 写出来时, 它们的 `service.py` 顶部 import 长这样:

```python
from odp_platform.common.model_path   import resolve_model_path
from odp_platform.common.dataset_path import resolve_dataset_path
from odp_platform.common.log_rename   import rename_log_to_save_dir
```

**而不是** `from odp_platform.training import resolve_model_path`——验证 / 推理子系统不应该从训练子系统 import 工具. 这条边界 D6 必须**一开始就立准**, 否则 D7 写出来名字跟语义对不上, 全套审美崩盘.

跑通后, 用户的工作流是:

```bash
# 1. 准备好 D5 立的 train.yaml(或者 odp-gen-config train 现生成一份)
odp-gen-config train       # D5 的命令, 写出 configs/runtime/train.yaml

# 2. 准备好 D3 立的 dataset.yaml(或者 odp-transform 产出的)
ls apps/platform/configs/datasets/    # rsod.yaml / safety_helmet.yaml ...

# 3. 一行起训练
odp-train                              # 用默认 train.yaml + configs/datasets/<data>.yaml
odp-train --epochs 100 --batch 32      # CLI 覆盖
odp-train --yaml my_train.yaml         # 指定别的配置
odp-train --no-pre-validate            # 跳过 D4 校验(不推荐)
odp-train --academic-plots             # 应用 matplotlib 学术发表风格
```

D6 子系统的 entry-point 边界: **只把 `TrainService` 包成 `odp-train`**——`TrainService` / `train_yolo` / `TrainResult` 这些仍然是**库**(给未来的 jupyter notebook / 自定义脚本 / experiment_db 调用). D6 提供:

- 一个 `odp-train` entry-point 跑训练
- 一份对外公共 API(4 个符号: TrainService / TrainResult / TrainMetrics / train_yolo)
- 6 个 common 工具(给 D7 / D8 复用, 不通过 training 子系统中转)

---

## D6 全部 git commit (终态)

```
* docs(training): add ADR-006 documenting training subsystem boundaries
* test(training+common): add unit tests for 6 common tools + 2 training modules
* feat(training): add public API in __init__.py (4 symbols only)
* feat(cli): add odp-train entry-point
* feat(training): add TrainService + TrainResult + train_yolo
* feat(training): add archive_checkpoints
* feat(common): add plot_style.apply_academic_style
* feat(common): add config_log (log_effective_config + log_override_chains)
* feat(common): add result.py (TrainMetrics + log_train_metrics)
* feat(common): add log_rename (operates on D2 named root)
* feat(common): add dataset_path
* feat(common): add model_path with search_dirs
```

**12 次提交, 从底到顶**: 先把 6 个 common 工具立稳(D7/D8 复用基础设施), 再立 training 专属(archive → service), 再 CLI 入口, 再对外面板, 最后测试 + ADR.

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 0: 立规矩

跟 D3 / D4 / D5 阶段 0 一样, 本阶段不写业务代码, 只立规矩. D6 要立的规矩有 3 条, 一条比一条重要.

## 0.1 D6 跟 D2 / D4 / D5 / ultralytics 的边界

```
                ┌──────────────────────────────────┐
                │   D6: TrainService 编排器        │
                │                                  │
                │   不发明:                        │
                │     - 配置合并 (走 D5)           │
                │     - 数据校验 (走 D4)           │
                │     - logging handler (走 D2)    │
                │     - 训练执行 (走 ultralytics)  │
                │                                  │
                │   只做:                          │
                │     - 调用顺序编排               │
                │     - 训练后整理 (rename/archive)│
                │     - audit 快照                 │
                │     - 错误兜底 (永不抛)          │
                └──────────────────────────────────┘
```

**自检命令** (D6 模块边界硬指标, CI 可以跑这条):

```bash
# service.py 里不能再有 D5 内部细节
grep "YAMLLoader\|CLILoader\|ConfigMerger\|build_snapshot" \
  apps/platform/src/odp_platform/training/service.py
# 期望: 没有输出(只有 docstring 里字面提及, 不算调用)
```

任何时候你在 `service.py` 里冒出"要不要这里再合并一下 yaml/cli"的念头, 立刻回去看 D5 的 `build_train_config`——99% 已经做过了.

> **金句**: **\"想在 service 里再写一遍 D5/D4/D2 的活, 说明你忘了它们存在. 边界纪律的第一条是【记得自己有哪些邻居】.\"**

## 0.2 common/ vs training/ 的拆分原则

D6 一共要立 **8 个新文件**(忽略 `__init__.py`):

| 文件 | 跨任务通用? | 放哪里 | 理由 |
|---|---|---|---|
| `model_path.py` | ✓ (D7 验证 / D8 推理都要解析模型路径) | `common/` | |
| `dataset_path.py` | ✓ (D7 验证也要解析数据集路径) | `common/` | |
| `log_rename.py` | ✓ (D7 也想让日志名跟 save_dir 对得上) | `common/` | |
| `config_log.py` | ✓ (D7 也要打印自己配置的来源) | `common/` | |
| `result.py` | ✓ (D7 验证指标结构跟训练几乎一样) | `common/` | TrainMetrics 直接复用 |
| `plot_style.py` | ✓ (D7 验证出图也要学术风格) | `common/` | |
| **`archive.py`** | ✗ (验证/推理不产权重, 没东西可归档) | **`training/`** | 训练专属副作用 |
| **`service.py`** | ✗ (TrainService 是训练编排, D7 自己写 ValService) | **`training/`** | 训练业务编排 |

⚠️ **设计点 (这条规矩反着说效果更强)**: 不要把"训练这一节先写到的工具"全堆 `training/`. 写到的顺序 ≠ 模块归属——**归属看跨任务通用与否**.

反模式(典型新手做法):

```
training/
  ├── model_path.py        ← D6 时先写到的
  ├── dataset_path.py      ← D6 时先写到的
  ├── log_rename.py        ← D6 时先写到的
  └── ...
```

D7 ValService 写出来 import 长成这样:

```python
# evaluation/service.py
from odp_platform.training import (
    resolve_model_path,     # ← "验证模块从训练模块 import 工具"
    resolve_dataset_path,   # ← 名字跟语义打架
    rename_log_to_save_dir,
)
```

读到这一行你就该警觉了: **验证子系统为什么依赖训练子系统?** 它依赖的不是"训练", 是"几个跟训练/验证/推理都通用的工具". 工具放错了门牌号.

正解(D6 一开始就立):

```
common/
  ├── model_path.py        ← D6/D7/D8 共用基础设施
  ├── dataset_path.py
  ├── log_rename.py
  └── ...
training/
  ├── service.py           ← 训练专属编排
  └── archive.py           ← 训练专属副作用
```

D7 ValService:

```python
from odp_platform.common.model_path   import resolve_model_path
from odp_platform.common.dataset_path import resolve_dataset_path
from odp_platform.common.log_rename   import rename_log_to_save_dir
```

读起来就是"验证模块用公共基础设施"——名字跟语义对上了.

🤔 **思考题(30 秒)**: ODPlatform 项目定位是"目标检测平台"——`common/` 已经放了 `system_utils.log_device_info`(GPU/CUDA 检测, 明显 ML-only). 那 `common/` 是不是已经被 YOLO 概念污染了? 再加 6 个 YOLO 工具进去, 不就更脏吗?

**答**: 这是**端私有的 common**, 不是 monorepo 顶层共享. `apps/platform/src/odp_platform/common/` 这个 common 的真实定位是"**这个目标检测平台的共享底层**"——它**应该**被 YOLO 概念污染, 因为整个端的定位就是 YOLO. 反过来真正纯通用的工具(比如 string padding, datetime utils)放在 `ROOT_DIR` 下的 workspace 共享层, 跟 platform 端无关.

立一层 `yolo_common/` 来"隔离 YOLO 工具"反而奇怪——等于在 YOLO 平台里加一个"yolo 子标签", 跟项目名打架.

> **金句**: **\"模块归属看【跨任务通用与否】, 不看【哪一节先写到】. 这条规矩立晚了, D7 写出来时再返工就是大手术.\"**

## 0.3 paths.py 复用 (本节不立新常量)

D6 需要的所有路径常量 D2/D3/D4 都立好了:

| 路径常量 | 立于 | D6 用来干嘛 |
|---|---|---|
| `LOGGING_DIR` | D2 | D2 `get_logger` 的 base_path |
| `RUNS_DIR` | D2 | ultralytics `project` 默认根目录 (`RUNS_DIR/<task>/`) |
| `PRETRAINED_MODELS_DIR` | D2 | `resolve_model_path` 默认查的目录 |
| `CHECKPOINTS_DIR` | D2 | `archive_checkpoints` 归档目标目录 |
| `DATASET_CONFIGS_DIR` | D3 | `resolve_dataset_path` 默认查的目录 |
| `RUNTIME_CONFIGS_DIR` | D5 | D5 默认 yaml 搜索路径 (D6 透传给 D5) |

⚠️ **设计点 (D6 不动 paths.py)**: 如果你在写 D6 时发现"诶, 缺一个路径常量"——立刻停下问自己: 是 D6 漏看了 paths.py, 还是真的少一条? 99% 是前者. paths.py 是 D2 立的, 进 D6 之前应该已经有 `LOGGING_DIR / RUNS_DIR / PRETRAINED_MODELS_DIR / CHECKPOINTS_DIR / DATASET_CONFIGS_DIR / RUNTIME_CONFIGS_DIR` 全套.

## 0.4 constants.py 复用 (本节不立新常量)

D6 需要的所有词汇 D3 都立好了:

- `Task.DETECT / Task.SEGMENT`——`config.task` 的合法值, 用在 `result.py` 的 `_METRIC_FIELDS_BY_TASK` 表里
- 没有别的需求

⚠️ **设计点 (跟 D5 阶段 0.3 同款警告)**: 不要在 `training/` 子系统内部立第二份 task 字符串集. 反模式:

```python
# ❌ 反模式 — 在 training/result.py 里立第二份
class TrainTask:
    DETECT  = "detect"
    SEGMENT = "segment"
```

立刻产生"`Task.DETECT == TrainTask.DETECT`?"的问号——SSoT 立马破. 遇到"我需要任务类型"的需求, 第一反应永远是 `from odp_platform.common.constants import Task`.

## 0.5 立 3 条工程规矩

### 0.5.1 规矩 A: "业务模块只发声, handler 只在 CLI 入口装一次"

这条规矩是 D2 立的, D6 是它的**第一次大规模兑现**. 阶段 3 整章会专门讲为什么这条这么重要.

简述: 任何子系统的 `service.py` / 工具模块, 顶部统一写

```python
import logging
logger = logging.getLogger(__name__)
```

**然后再也不碰 `addHandler` / `setLevel` / `propagate`**. 配 handler 是 CLI 入口的事——通过 D2 `get_logger(base_path=LOGGING_DIR, log_type="train")` 装在 `"odp_platform"` named root 上, 业务模块 `getLogger(__name__)`(比如 `odp_platform.training.service`) 通过冒泡机制自动继承.

⚠️ **设计点 (这条规矩怎么自检)**:

```bash
# 业务模块不应该出现 addHandler / setLevel — CLI 入口除外
grep -rn "addHandler\|setLevel(" apps/platform/src/odp_platform/training/ \
  apps/platform/src/odp_platform/common/

# 期望: training/service.py / archive.py / common/各模块 都没有
# 唯一豁免: common/log_rename.py — 它的工作就是重新挂 handler(下面会讲为什么这是合法豁免)
```

### 0.5.2 规矩 B: "service 永不抛, 错误装进 TrainResult.error"

这是给"想在 jupyter notebook / 自定义脚本里调 service" 的人留的稳定 API. 凡是从外界进来的 exception(网络断、磁盘满、ultralytics 内部 RuntimeError), 在 `TrainService.train()` 顶层一律 `except Exception` 包成 `TrainResult(success=False, error=str(e))` 返回, **不让异常穿过 service 边界**.

```python
# ✅ 正例 — service 调用风格
result = service.train(yaml_path=..., cli_args=...)
if not result.success:
    print(f"训练失败: {result.error}")
    sys.exit(1)
print(f"OK, 用时 {result.train_time}s, 输出 {result.output_dir}")

# ❌ 反例 — service 让 exception 穿过去
try:
    service.train(...)
except RuntimeError as e:    # ← 调用方还得自己 try, 没意义
    ...
```

CLI 在最外层兜底再做一次 try, 但那是\"理论上 service 应该兜住, 万一漏了\"的双保险, 不是常规路径.

### 0.5.3 规矩 C: 跨任务工具放 `common/`, 不放 `training/`

已经在 §0.2 讲过, 这是 D6 跟 D7/D8 的边界契约——D7 写出来时不能 `from odp_platform.training import resolve_model_path`. 这条规矩**最容易在写 D6 时违反**, 因为这一节确实先用到这些工具——但写到的顺序 ≠ 归属.

CI 守门(可选, 给整套项目用):

```bash
# scripts/check_subsystem_boundary.sh
# evaluation / inference 模块不应该 import 训练子系统
grep -rn "from odp_platform.training" \
    apps/platform/src/odp_platform/evaluation/ \
    apps/platform/src/odp_platform/inference/ \
    2>/dev/null

# 期望: 没有输出
```

> **金句**: **\"边界纪律是用 grep 写出来的硬指标, 不是写在 README 里的承诺.\"**

## 0.6 第一阶段收尾

阶段 0 不动代码, 也没 commit. 心智模型先立好——D6 是编排器、common/ 跟 training/ 各管各、handler 只在 CLI 装一次——才能动手.

下一阶段我们先写**朴素第一版**, 让它跑起来, 然后**亲手撞墙①**.


---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 1: 朴素第一版——直接调 ultralytics

跟 D5 阶段 1 一样, 这一阶段写"绝大多数 yolo 教程的做法", 跑通它, 然后亲手撞墙. **亲手撞墙的价值远大于"作者告诉你这里会出问题"**——D6 整套设计是 4 个伤痛的反向工程, 不撞痛过就理解不了为什么 service.py 长这样.

## 1.1 任务设定: 复刻一份 legacy `yolo_train.py`

新建一个临时文件 `/tmp/yolo_train_naive.py` (**这个版本不进 git, 演完就丢**):

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# /tmp/yolo_train_naive.py — 朴素方案, 演示用, 不进 git
"""绝大多数 yolo 教程的做法 — 跑通即可, 不考虑工程化."""
import argparse
import logging
from datetime import datetime
from pathlib import Path

from ultralytics import YOLO


def build_parser():
    parser = argparse.ArgumentParser(description="YOLO 训练 (朴素版)")
    # 60+ 训练字段全部列出来 — 这里只列最常用的, 省略一大半
    parser.add_argument("--model",      type=str,   default="yolo11n.pt")
    parser.add_argument("--data",       type=str,   default="rsod.yaml")
    parser.add_argument("--epochs",     type=int,   default=100)
    parser.add_argument("--batch",      type=int,   default=16)
    parser.add_argument("--imgsz",      type=int,   default=640)
    parser.add_argument("--device",     type=str,   default="0")
    parser.add_argument("--lr0",        type=float, default=0.01)
    parser.add_argument("--optimizer",  type=str,   default="auto")
    parser.add_argument("--workers",    type=int,   default=8)
    parser.add_argument("--seed",       type=int,   default=0)
    parser.add_argument("--project",    type=str,   default="runs/detect")
    parser.add_argument("--name",       type=str,   default="train")
    # ... 假装还有 50 个 ...
    return parser


def setup_logging(log_dir):
    """配 logging — 朴素版自己手挂 handler."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = log_dir / f"train_{timestamp}.log"

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    root = logging.getLogger()                   # ← 这里是 unnamed root
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(logging.StreamHandler())     # console
    return log_file


def main():
    args = build_parser().parse_args()

    log_file = setup_logging("./logs")
    log = logging.getLogger(__name__)
    log.info(f"开始训练, 日志: {log_file}")

    # 直接调 ultralytics
    model = YOLO(args.model)
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=args.device,
        lr0=args.lr0,
        optimizer=args.optimizer,
        workers=args.workers,
        seed=args.seed,
        project=args.project,
        name=args.name,
    )
    log.info(f"训练完成: {results.save_dir}")


if __name__ == "__main__":
    main()
```

## 1.2 把它先跑一下

```bash
# 拿 D4 立的数据集试一下
cd <ODPlatform-root>
python /tmp/yolo_train_naive.py \
    --model yolo11n.pt \
    --data /abs/path/to/rsod.yaml \
    --epochs 3 \
    --device 0
```

跑几个 epoch 看效果——它**能跑**, 给你产出权重, 也给你产出日志. 表面上看一切 OK.

```
Using 8 dataloader workers
Logging results to C:\Users\Matri\Desktop\ODPlatform_tea\apps\platform\runs\detect\runs\detect\train

keys: ['metrics/precision(B)', 'metrics/recall(B)', 'metrics/mAP50(B)', 'metrics/mAP50-95(B)']
maps: array([     0.5352,     0.75741,     0.13919,     0.76868])
names: {0: 'aircraft', 1: 'oiltank', 2: 'overpass', 3: 'playground'}
nt_per_class: array([594, 189,  13,  17])
nt_per_image: array([46, 18, 13, 17])
results_dict: {'metrics/precision(B)': 0.727787759827597, 'metrics/recall(B)': 0.8469223498135754, 'metrics/mAP50(B)': 0.8087183915965699, 'metrics/mAP50-95(B)': 0.5501196894654274, 'fitness': 0.5501196894654274}
save_dir: WindowsPath('C:/Users/Matri/Desktop/ODPlatform_tea/apps/platform/runs/detect/runs/detect/train')
speed: {'preprocess': 0.14674148932247957, 'inference': 1.4155872340005713, 'loss': 0.00016808514780503639, 'postprocess': 1.2685393617272331}
stats: {'tp': [], 'conf': [], 'pred_cls': [], 'target_cls': [], 'target_img': []}

Using 8 dataloader workers
Logging results to C:\Users\Matri\Desktop\ODPlatform_tea\apps\platform\runs\detect\runs\detect\train-2
```



## 1.3 🧱 撞墙①: 朴素方案的 4 个伤痛

现在请你回到这个脚本, 模拟 4 个真实场景:

### 伤痛①: D5 配置子系统形同虚设

D5 立了 `YOLOTrainConfig` (60+ 字段、字段级元数据、三源合并 CLI←YAML←DEFAULT、配置溯源链), 但朴素版**完全没接**——argparse 自己列了一份, default 自己写一份, 用户的 train.yaml 没人加载. D5 阶段 1 那 4 个伤痛(字段散乱 / 无验证 / 无溯源 / 配置即文档失效)在 D6 这里全部复活.

```bash
# 用户问: 我这次跑的 lr0=0.001 是 CLI 给的还是 default 给的?
# 朴素版回答: 看脚本里 argparse 的 default 是 0.01, 你 CLI 没传 --lr0
#            所以是 default 0.01——但日志里 lr0=0.001? 那是 yaml 给的吗? 
#            你的 yaml 在哪? 朴素版根本没加载 yaml.
```

D5 留的 `build_train_config(yaml_path, cli_args) → (config, merger)` 一行就解决了, 朴素版白白不用.

### 伤痛②: D4 校验跳过, 训练 5 分钟后崩在数据脏数据上

```bash
# 用户的 rsod.yaml 里 nc=4 但标签文件里出现了 class_id=7
# 朴素版: 训练直接开跑, 跑到第 50 个 batch ultralytics 自己崩
# → "IndexError: index 7 out of bounds"
# 用户要 debug 30 分钟才发现是标签脏
```

D4 的 `validate_dataset(data_path, task_type) → ValidationReport` 在训练前一行调用就能 fail-fast——4 个 check 跑完, 脏数据直接拦在训练之外.

### 伤痛③: handler 挂错地方 — 现在感觉不到, D6 接上 D2 时会炸

朴素版 `setup_logging` 把 handler 挂在 `logging.getLogger()` (无参) 上, 即 **Python 的 unnamed root**. 朴素版独立跑时这没问题——所有模块的 logger 通过冒泡都能走到 unnamed root.

但是 ODPlatform 端的 D2 是这样设计的(看 `common/logging_utils.py` 第 1460 行附近):

```python
def get_logger(base_path, log_type, ...) -> logging.Logger:
    root_logger = logging.getLogger("odp_platform")    # ← named root
    # 装 console + file handler
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.propagate = False                       # ★ 关键
    return root_logger
```

`propagate = False` **截断了消息向 Python unnamed root 的冒泡**. 业务模块 `getLogger("odp_platform.training.service")` 的 log 走到 `"odp_platform"` 就**停**了, 不会再往 unnamed root 走.

如果你在 D6 集成时既调了 D2 `get_logger()` 又像朴素版一样手挂在 `logging.getLogger()` 上——**手挂的那个 handler 一条消息也收不到**, 因为消息被 `"odp_platform"` 截在前面了. 你以为日志会双写, 实际上有一份是空的——debug 时痛不欲生.

这就是阶段 3 的撞墙②的预演——朴素版能跑只是因为它**没接 D2**, 真正接上 D2 之后必须明白"handler 装哪个 root logger".

### 伤痛④: 训练完, 权重 / 日志 / audit 三件事都没人管

跑完之后:

```bash
ls runs/detect/train*/weights/best.pt    # ← ultralytics 工作目录里的, 但 train/train2/train3 自增
ls ./logs/train_*.log                     # ← 日志, 跟 weights 名字不对应
cat odp_audit.json                        # ← 这文件不存在, 朴素版根本没写
```

用户问"我上周跑的那次 train3 对应哪个日志?"——你只能 `ls -la` 比对时间戳猜. 用户问"那次的配置和指标在哪个 audit 文件里?"——朴素版没写 audit.

这就是阶段 5 (log_rename) + 阶段 6 (archive / odp_audit.json) 要解决的事.

## 1.4 这版不 commit

```bash
# /tmp/yolo_train_naive.py 别 git add——它在我们文件系统外, 演完就丢
```

## 1.5 朴素方案的 4 个伤痛 → D6 的对应设计

把上面 4 个伤痛跟 D6 设计点对一下:

| 伤痛 | D6 设计点 | 阶段 |
|---|---|---|
| ① D5 配置子系统没接 | TrainService 内部一行 `build_train_config(yaml_path, cli_args)` | §6.2 (阶段 1) |
| ② D4 校验跳过 | TrainService 内部 `pre_validate=True` 时调 `validate_dataset` + 看 exit_code | §6.2 (阶段 3) |
| ③ handler 挂错位置 | CLI 入口调 D2 `get_logger()` 装在 named root, 业务模块只发声 | §3 整章 |
| ④ 日志 / 权重 / audit 都没整理 | log_rename(§5) + archive(§6.1) + audit JSON(§6.3) | §5, §6 |

每个伤痛都有专门一章对应——D6 整套结构就是这 4 个伤痛的反向工程.

> **金句**: **\"D6 服务层不是发明出来的——它是【朴素方案 4 个伤痛】被一一治好的副产品.\"**

下一阶段我们先立**TrainService 的对外面板**——TrainResult dataclass + train() 签名——然后再一层一层把内脏填进去.


---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 2: TrainResult + TrainService 对外面板

我们先**只立面板**——dataclass + class 签名 + train() 的方法签名 + docstring. 内脏空着.

这一步的价值是: **接口想清楚之前不要写实现**. service 的稳定 API 一旦立好, 哪怕 train() 内部从 0 行实现到 200 行实现, 调用方一行不用改.

## 2.1 选型: 编排器 (orchestrator) 模式 — 不是 model.train 的包装器

D6 的核心选型问题: **TrainService 是什么?**

候选三种:

| 模式 | 长什么样 | 缺点 |
|---|---|---|
| (a) **包装器** | `TrainService.train_yolo11n_detect(epochs=...)` | 每种任务一个方法, 60 个参数 6 个方法 = 爆炸 |
| (b) **薄壳函数** | `def train(yaml, cli_args): model.train(**load(yaml))` | 没编排, 缺 D4 校验/audit/archive, 跟朴素版区别不大 |
| (c) **编排器** ✓ | `class TrainService: def train(yaml, cli_args, *, pre_validate, archive, rename_log) → TrainResult` | 内部明确分 8 个阶段, 每阶段调一个邻居子系统 |

选 (c). 理由:

1. **8 个阶段是天然的边界划分**——配置加载 / 上下文日志 / D4 校验 / 加载模型 / 执行训练 / 结果指标 / 整理输出 / audit 快照——每个阶段都有一个唯一邻居. 看 service.py 就是看一遍\"这次训练做了哪些事, 顺序是什么\".
2. **`__init__` 不接参数, 配置都通过 `train()` 传**——跟 D5 `build_train_config(yaml_path, cli_args)` 风格一致, **配置参数和服务实例解耦**. 同一个 TrainService 实例可以接连跑 5 次不同配置的训练, 不需要重建.
3. **`train()` 的 keyword-only 开关分离行为**——`pre_validate` / `archive` / `rename_log` 三个 bool 让用户能精细控制 service 行为(测试时关掉 archive 防污染 CHECKPOINTS_DIR / 跑 smoke test 时关掉 pre_validate / 自定义日志命名时关掉 rename_log).

⚠️ **设计点 (为什么不放在 `__init__` 而放在 `train()` 的 kwargs)**: 把 `pre_validate=True` 放进 `__init__(pre_validate=True)` 看起来\"对象配置一次终生有效\", 实际是反模式——同一个 service 实例第二次跑可能就想关掉 pre_validate, 这种"动态切换的开关"应该跟"具体那一次调用"绑定, 不跟"对象生命周期"绑定. 所以放 `train()`.

> **金句**: **\"对象生命周期 vs 单次调用——这两者的状态不要混. service 实例稳定, 调用参数动态.\"**

## 2.2 TrainResult 设计 — frozen dataclass

`TrainResult` 是 `train()` 的**唯一**返回类型——成功失败都返回它, 不抛异常. 字段一次定稿:

```python
from dataclasses import dataclass, field
from pathlib import Path

@dataclass(frozen=True)
class TrainResult:
    """训练结果一次性快照.

    success=False 时 output_dir 可能是 'unknown' Path, error 字段填错误描述.
    success=True  时 best_weight / last_weight / metrics 一定有值(metrics 至少含 fitness).
    """
    success:     bool
    output_dir:  Path
    best_weight: Path | None = None
    last_weight: Path | None = None
    metrics:     dict[str, float] = field(default_factory=dict)
    train_time:  float | None = None       # 秒
    error:       str | None = None
    audit_path:  Path | None = None        # odp_audit.json 的位置
    log_path:    Path | None = None        # 本次训练的日志文件位置
```

设计点:

- **`frozen=True`**: 不可变. 训练结果一旦产生就不允许修改——调用方误改 `.success = False` 不会让训练真的失败, 那是状态不一致.
- **`best_weight` / `last_weight` 用 `| None`**: 失败时这俩没值, 用 None 显式表达. 不用 sentinel 字符串(像 `"unknown"` 那种)避免类型不统一.
- **`metrics: dict[str, float]`**: 不用 `TrainMetrics` 直接放——TrainMetrics 字段太多(speed_ms / overall / class_map_50_95), `TrainResult` 只放 overall("外部最关心的: fitness, mAP, precision, recall"), 完整 metrics 通过 `audit_path` 指向的 JSON 取.
- **`log_path` 字段**: 让调用方一行 `print(result.log_path)` 就能告诉用户"这次的日志在哪". 这是 D6 给 jupyter / 自动化脚本的便利接口.

🤔 **思考题 (30 秒)**: 为什么 `TrainResult` 里**不直接放 `TrainMetrics`** 而只放 `metrics: dict[str, float]`?

**答**: 关注点分离. `TrainResult` 是"调用方关心的最少必要信息"(成败 / 输出位置 / 几个关键指标 / 错误描述), 给**外面看的**. `TrainMetrics` 是"完整指标快照"(含速度细节 / 类别 mAP / 时间戳等), 给**audit / DB / 完整日志看的**. 如果把 TrainMetrics 嵌进 TrainResult, 调用方 `print(result)` 直接喷出 50 个数值, 不友好; 把它放进 audit JSON 由 `audit_path` 字段指向, 调用方按需取.

## 2.3 TrainService.train() 签名

```python
class TrainService:
    """YOLO 训练流程编排."""

    def __init__(self) -> None:
        """__init__ 不接任何参数 — 配置都通过 train() 传, 跟 D5 同款."""
        pass

    def train(
        self,
        yaml_path: str | Path | None = None,
        cli_args: dict[str, Any] | None = None,
        *,
        pre_validate: bool = True,
        archive: bool = True,
        rename_log: bool = True,
    ) -> TrainResult:
        """跑一次完整训练.

        Args:
            yaml_path:        YAML 路径 (None 走 paths.runtime_config_path("train") 默认)
            cli_args:         CLI 字典 (argparse.Namespace.__dict__ 也 OK)
            pre_validate:     训练前调 D4 validate_dataset (默认 True, fail-fast)
            archive:          训练后复制 best/last.pt 到 CHECKPOINTS_DIR (默认 True)
            rename_log:       训练后把日志文件名改成 <save_dir.name>_<ts>_<model>.log 形式

        Returns:
            TrainResult — 永不抛, 错误装进 .error.
        """
        ...
```

⚠️ **设计点 (`*` 之后的 keyword-only)**: `pre_validate / archive / rename_log` 三个开关用 keyword-only 强制调用方写参数名:

```python
# ✅ 强制写参数名 — 一眼看出是在关哪个开关
service.train(yaml_path=..., cli_args=..., pre_validate=False)

# ❌ 如果不用 keyword-only, 这种调用合法但难读
service.train("train.yaml", {"epochs": 100}, False, True, True)
#                                            ↑ 这第 3 个 False 是 pre_validate? archive? rename_log? 谁知道
```

`pre_validate` / `archive` / `rename_log` 三个 bool 容易记错顺序, keyword-only 把这个错堵死.

## 2.4 train_yolo() — 给"不想要 service 实例化"的人

```python
def train_yolo(
    yaml_path: str | Path | None = None,
    cli_args: dict[str, Any] | None = None,
    *,
    pre_validate: bool = True,
    archive: bool = True,
    rename_log: bool = True,
) -> TrainResult:
    """一行启动训练 — 风格跟 D5 build_train_config 一致.

    >>> from odp_platform.training import train_yolo
    >>> result = train_yolo(yaml_path="train.yaml", cli_args={"epochs": 100})
    >>> result.success
    True
    """
    service = TrainService()
    return service.train(
        yaml_path=yaml_path,
        cli_args=cli_args,
        pre_validate=pre_validate,
        archive=archive,
        rename_log=rename_log,
    )
```

便捷函数. 跟 D5 `build_train_config(yaml_path, cli_args)` 的风格一致——\"我只是想一行跑起来, 别给我 class 实例化\". 让用户的两种调用方式都顺手:

```python
# 实例化路: 适合长进程 / 服务化 / 复用 service
service = TrainService()
for cfg in configs:
    result = service.train(cli_args=cfg)

# 便捷函数路: 适合 notebook / 一次性脚本
from odp_platform.training import train_yolo
result = train_yolo(cli_args={"model": "yolo11n.pt", "epochs": 100})
```

## 2.5 这阶段还没法 commit

train() 里只有 docstring + `...`, 不算可工作代码. 阶段 6 才把它完整实现, 然后才一起 commit. 这一阶段的产物是**心智模型**——你知道了 TrainService 长什么样, train() 接收什么、返回什么, 接下来填内脏的时候每一步都对得上整体.

下一阶段我们去解决**最容易出错的一件事**: handler 装哪里.


---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 3: handler 装哪里? — logging 边界的硬纪律

D6 整个子系统**最容易写错**的一件事是 logging. 不是因为 logging 难, 是因为 Python 的 logging 默认行为太顺——`logging.getLogger().addHandler(...)` 在大多数小项目里都能跑, 你以为自己写对了, 接到 D2 的 named root 框架上立刻炸.

这一章只解决一件事: **handler 装哪个 logger 上, 业务模块怎么获取 logger**.

## 3.1 D2 logging_utils 的设计回顾

打开 `apps/platform/src/odp_platform/common/logging_utils.py`(D2 立的), 找到 `get_logger` 函数:

```python
# D2 的 get_logger (简化版, 真版还有彩色输出 / 路径约定 / 幂等保护)
ROOT_LOGGER_NAME = "odp_platform"

def get_logger(
    base_path: Path,
    log_type: str,                # "train" / "val" / "predict"
    log_level: int = logging.INFO,
    model_name: str | None = None,
    temp_log: bool = False,
) -> logging.Logger:
    """初始化 'odp_platform' named root logger.
    
    挂上 console + file 两个 handler.
    business 模块通过 getLogger(__name__) 冒泡到这里, 自动继承.
    """
    root_logger = logging.getLogger(ROOT_LOGGER_NAME)        # ← named, 不是 unnamed
    
    if root_logger.handlers:        # 幂等保护
        return root_logger
    
    root_logger.setLevel(log_level)
    
    # 装 console handler (彩色输出)
    console_handler = _make_colored_console_handler()
    root_logger.addHandler(console_handler)
    
    # 装 file handler (路径: <base_path>/<log_type>/<log_type>_<timestamp>.log)
    log_file_path = _build_log_file_path(base_path, log_type, model_name)
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    root_logger.addHandler(file_handler)
    
    root_logger.propagate = False    # ★ 关键: 截断到 unnamed root 的冒泡
    
    return root_logger
```

两个关键设计:

1. **`logging.getLogger("odp_platform")` — named root**: 整个 `odp_platform.*` 包下所有模块的 logger(比如 `odp_platform.training.service`) 都会冒泡到这个 named root, 而**不是** Python 默认的 unnamed root.
2. **`propagate = False`**: 消息走到 `"odp_platform"` 就**截止**, 不再继续冒泡到 Python 的 unnamed root.

这两个设计组合起来等于在说: **想接 ODPlatform 的日志通道? 只能跟 `"odp_platform"` named root 打交道. unnamed root 上发生的事情, 我们这边一概不感知**.

## 3.2 🧱 撞墙②: `logging.getLogger()` 不带参数 ≠ `"odp_platform"`

现在请你想象一下, 你正在写 CLI 入口 `cli/train_model.py`, 没仔细看 D2, 凭直觉写出了下面这段:

```python
# ❌ 反模式 — D6 CLI 入口
import logging
from pathlib import Path
from datetime import datetime

def _setup_logging(log_dir):
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"train_{datetime.now():%Y%m%d-%H%M%S}.log"
    
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    ))
    
    root = logging.getLogger()          # ← 这里!
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(logging.StreamHandler())
    return log_file
```

跑起来感觉一切正常——`log.info("...")` 也能输出到 console, file 也能写——但**这是个错误的位置**.

`logging.getLogger()` 不带参数拿的是 **Python 的 unnamed root logger**, 不是 `"odp_platform"`. 当业务模块发出日志:

```python
# odp_platform/training/service.py 里
import logging
logger = logging.getLogger(__name__)     # → "odp_platform.training.service"
logger.info("训练开始")
```

这条消息的冒泡链是:

```
"odp_platform.training.service"
        ↓ (冒泡)
"odp_platform.training"
        ↓
"odp_platform"          ← D2 在这里挂了 handler, 且 propagate=False
        ✗ 截止!
"" (unnamed root)        ← 你刚才挂的 handler 在这, 但消息根本不到这里
```

**结果**: 你挂的 file handler 一条日志都收不到, 但你不会立刻发现, 因为 D2 已经在 named root 上挂了自己的 file handler, **D2 那份日志在写, 你那份永远空**. 调试时打开自己挂的那份 log 文件——空的——以为是路径错了, 以为是权限错了, 折腾半天.

这就是撞墙②: **`logging.getLogger()` 不等于 `"odp_platform"`**.

⚠️ **设计点 (这个错有多隐蔽)**: 朴素方案能跑只是因为它没接 D2——朴素版自己挂在 unnamed root, 业务模块也没人调 `get_logger("odp_platform")`, 所以冒泡一路畅通. 一旦你想"我把朴素版的 logging 升级到接 D2"——只要同时调用了 D2 `get_logger()` 和自己手挂 `addHandler`, 就立刻撞这堵墙.

> **金句**: **\"`logging.getLogger()` 不带参数拿的是 unnamed root, 不是你的项目根. 这两个东西的区别决定了 logging 子系统能不能用.\"**

## 3.3 正解: CLI 入口调 D2 `get_logger()`, 不要自己挂

正确的 CLI `_setup_logging` 长这样——**一行**:

```python
# ✅ 正解
from odp_platform.common.logging_utils import get_logger
from odp_platform.common.paths import LOGGING_DIR

def _setup_logging(log_level: str) -> None:
    """调 D2 的 get_logger 给 'odp_platform' 根 logger 装上 console + file handler.

    D2 已经把彩色 console + 文件 handler + 路径约定 + 幂等保护全做完了,
    CLI 这里只是触发一次配置. 装完之后, 整个进程里所有
    logging.getLogger(__name__) 通过冒泡机制自动继承.

    日志文件路径: LOGGING_DIR/train/train_<timestamp>.log
    """
    get_logger(
        base_path=LOGGING_DIR,
        log_type="train",
        log_level=getattr(logging, log_level),
        temp_log=False,
    )
```

完事. 一行调用, 没有 `addHandler`、没有 `FileHandler`、没有 `Formatter`——D2 都做完了, D6 不重复.

⚠️ **设计点 (这里**不要**传 model_name)**: D2 的 `get_logger` 接受可选 `model_name` 参数把它编进文件名(`train_<ts>_<model>.log`). 你可能会想"我知道用户传了 `--model yolo11n.pt`, 顺手传进去". **不要**——CLI 启动时**还没读 YAML**, 你不知道用户最终生效的模型是什么(可能 yaml 里又覆盖了). 阶段 5 的 `log_rename` 才是改文件名的合适时机, 那时候 ultralytics save_dir 已经定了, 模型也加载完了.

## 3.4 业务模块统一只发声

所有 `odp_platform/training/*.py` 和 `odp_platform/common/*.py` 模块顶部一律:

```python
import logging
logger = logging.getLogger(__name__)
```

**然后再也不碰 `addHandler / setLevel / propagate`**. log 怎么走、走到哪、写不写文件、彩不彩色, 一律由 D2 在 CLI 入口装的那套决定.

CI 守门:

```bash
grep -rn "addHandler\|setLevel(" \
    apps/platform/src/odp_platform/training/ \
    apps/platform/src/odp_platform/common/
# 期望: 只有 cli/train_model.py 间接调 D2 get_logger 才会出现这些操作
# 业务模块出现就是违反纪律
```

唯一豁免: `common/log_rename.py`——它的工作就是替换 `"odp_platform"` named root 上的 FileHandler. 这是合法豁免, 阶段 5 会专门讲为什么这个豁免不矛盾.

## 3.5 service 也不持有 FileHandler

D5 / D4 跟 D6 共享同一个 `"odp_platform"` named root, 那 service 想知道"这次训练的日志写在哪个文件"怎么办?

**只读探测**——不持有, 不操作, 只看:

```python
# training/service.py 顶部
import logging
from pathlib import Path

def _find_project_log_path() -> Path | None:
    """从 D2 'odp_platform' 根 logger 找 FileHandler 的实际文件路径.

    只读检查, 不操作 handler. 给 audit JSON 用 — 让用户能从 odp_audit.json
    一眼看出"这次训练对应哪个 .log 文件".

    返回 None 如果根 logger 没挂 FileHandler(比如有人单测时跳过了 CLI 入口).
    """
    root = logging.getLogger("odp_platform")
    for h in root.handlers:
        if isinstance(h, logging.FileHandler):
            return Path(h.baseFilename)
    return None
```

⚠️ **设计点 (为什么是"探测"不是"传参")**: 你可能会想"那就让 CLI 把 log_path 传给 service 嘛, `service.train(log_path=...)`"——**不要**. 这就破坏了规矩 A: "业务模块不感知 handler 细节". 让 service 通过遍历 `"odp_platform"` root 的 handlers 自己**只读探测**, 才能保持"配 handler 是 CLI 的事, service 自己不感知"的边界.

> **金句**: **\"业务模块只发声, handler 由 CLI 入口装一次. service 想知道日志在哪, 只读探测, 不持有.\"**

## 3.6 这阶段先把 CLI 雏形和纪律敲下来

完整 `cli/train_model.py` 等阶段 7 才写——这一章只是先把"handler 装哪、business 模块怎么发声"立准. 阶段 7 把 argparse、退出码翻译、`_setup_logging` 一起完整提交.

下一阶段我们开始填 common/ 的 6 个跨任务通用工具.


---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 4: common/ 跨任务通用工具 (前 5 个)

按 §0.2 立的边界, 6 个跨任务通用工具都放在 `common/`. 阶段 4 一次写完前 5 个(`model_path / dataset_path / result / config_log / plot_style`), 阶段 5 单独讲第 6 个 `log_rename`(它有撞墙③要展开).

每个工具都遵循同一个套路:
- 顶部 `logger = logging.getLogger(__name__)`(不挂 handler)
- 单一职责, 不依赖训练专属概念
- 永不抛(失败用 `logger.warning`, 返回 None 或原值, 让调用方决定下一步)

## 4.1 `common/model_path.py` — 模型路径解析 + search_dirs

### 问题

用户在 yaml / CLI 里通常写 `model: yolo11n.pt` 这种**仅文件名**形式. ultralytics 会去当前工作目录找, 找不到就去自己的下载 cache. 但 ODPlatform 想要的是: **优先去本项目 `PRETRAINED_MODELS_DIR` 找一份**, 没有再让 ultralytics 自己下.

### 方案

3 个分支, 从具体到 fallback:

1. **绝对路径** → 直接用 (用户精确指定了, 不再 fallback)
2. **仅文件名** → 在 `search_dirs` 里**依次**找, 命中即用
3. **都没命中** → 返回原值, 让 ultralytics 自己处理 (下载 / 报错都是它的事)

### 为什么有 `search_dirs` 参数?

D6 训练时, 用户写 `model: yolo11n.pt`——应该去 `PRETRAINED_MODELS_DIR` 找.

但 D7 验证 / D8 推理时, 用户写 `model: train3-best.pt`——他想验证 D6 归档的某次训练产物, 应该**优先**去 `CHECKPOINTS_DIR` 找, fallback 才查 `PRETRAINED_MODELS_DIR`.

所以 `resolve_model_path` 不应该写死"只查 PRETRAINED_MODELS_DIR", 应该接受 `search_dirs: Sequence[Path]` 参数让下游决定查哪些目录、按什么顺序.

⚠️ **设计点 (向后兼容)**: 默认 `search_dirs=None` 等价于 `[PRETRAINED_MODELS_DIR]`——D6 调用方一行不用改, 行为跟"没有这个参数"一样. D7/D8 才需要显式传 `[CHECKPOINTS_DIR, PRETRAINED_MODELS_DIR]`.

```python
# D6: 不传 search_dirs, 默认行为
resolve_model_path("yolo11n.pt")

# D7/D8: 显式传 search_dirs
resolve_model_path("train3-best.pt", 
                   search_dirs=[CHECKPOINTS_DIR, PRETRAINED_MODELS_DIR])
```

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : model_path.py
# @Project   : ODPlatform
# @Function  : 解析 YOLO 模型路径 — 绝对路径 / 仅文件名 fallback 到 search_dirs 列表
"""模型路径解析.

策略(3 个分支, 从具体到 fallback):
  1. 绝对路径 → 直接用
  2. 仅文件名 → 在 search_dirs 里依次找, 命中即用
  3. 都没命中 → 返回原值, 让 ultralytics 走自己的下载/搜索逻辑
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from odp_platform.common.paths import PRETRAINED_MODELS_DIR

logger = logging.getLogger(__name__)


def resolve_model_path(
    model: str | Path,
    *,
    search_dirs: Sequence[Path] | None = None,
) -> Path:
    """把 YOLO 模型名/路径解析成实际 Path."""
    model_path = Path(model)

    # 分支 1: 绝对路径
    if model_path.is_absolute():
        return model_path

    # 分支 2: 仅文件名 → 按顺序查 search_dirs
    dirs: Sequence[Path] = search_dirs if search_dirs is not None else [PRETRAINED_MODELS_DIR]
    for d in dirs:
        candidate = d / model_path.name
        if candidate.exists():
            logger.info(f"模型已定位: {candidate} (来自 {d})")
            return candidate

    # 分支 3: fallback — 让 ultralytics 自己处理
    logger.warning(
        f"模型文件未在任何搜索目录命中: {model_path.name}\n"
        f"  搜索过的目录: {[str(d) for d in dirs]}\n"
        f"  ultralytics 将尝试自动下载或从其他位置加载."
    )
    return model_path
```

### 为什么分支 3 不 raise?

ultralytics 自己有强大的"模型仓库 + 自动下载"逻辑——你写 `YOLO("yolo11n.pt")`, 它会去 huggingface / github 找. 如果 `resolve_model_path` 提前 raise, 等于**剥夺了 ultralytics 自动下载的能力**. 所以分支 3 只 warning + 返回原值, 把决定权还给 ultralytics.

> **金句**: **\"resolve 函数的职责是【试一试】, 不是【保证一定行】. 真正的错误归宿在下游, 不在 resolve.\"**

## 4.2 `common/dataset_path.py` — 数据集 yaml 路径解析

跟 `model_path` **完全对称**——只是搜索目录换成了 `DATASET_CONFIGS_DIR`. 因为数据集 yaml 走的是 D3 立的 `configs/datasets/<name>.yaml` 约定.

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : dataset_path.py
# @Project   : ODPlatform
# @Function  : 解析数据集 yaml 路径 — 绝对路径 / 仅文件名 fallback 到 DATASET_CONFIGS_DIR
"""数据集 yaml 路径解析.

用户在 train.yaml 或 CLI 里通常写 `data: rsod.yaml` 这种**仅文件名**形式,
期望从项目的 DATASET_CONFIGS_DIR (apps/platform/configs/datasets/) 加载.
本模块负责把这种简写解析成实际绝对路径, 解析不到时返回原值
(让 D4 validate_dataset / ultralytics 自己报"找不到").

策略跟 resolve_model_path 同款 3 分支, 但**没有 search_dirs 参数** —
数据集配置目录只有一个 SSoT (DATASET_CONFIGS_DIR), D6/D7/D8 用法一致.
"""
from __future__ import annotations

import logging
from pathlib import Path

from odp_platform.common.paths import DATASET_CONFIGS_DIR

logger = logging.getLogger(__name__)


def resolve_dataset_path(data: str | Path) -> Path:
    """把数据集 yaml 名/路径解析成实际 Path."""
    data_path = Path(data)

    # 分支 1: 绝对路径
    if data_path.is_absolute():
        return data_path

    # 分支 2: 仅文件名 → 查 DATASET_CONFIGS_DIR
    config_candidate = DATASET_CONFIGS_DIR / data_path.name
    if config_candidate.exists():
        logger.info(f"从数据集配置目录加载: {config_candidate}")
        return config_candidate

    # 分支 3: 都没命中 → 让下游报错
    logger.warning(
        f"数据集 yaml 未在 DATASET_CONFIGS_DIR 找到: {data_path.name}\n"
        f"  DATASET_CONFIGS_DIR: {DATASET_CONFIGS_DIR}\n"
        f"  D4 / ultralytics 接下来会按 '{data_path}' 原样解析, 可能报'找不到文件'."
    )
    return data_path
```

🤔 **思考题 (30 秒)**: `model_path` 有 `search_dirs` 参数, `dataset_path` 为什么没有? 哪一个的判断是对的?

**答**: 两个都对——因为它们的 SSoT 数量不一样.

- **模型权重**有两个合法来源: `PRETRAINED_MODELS_DIR` (ultralytics 官方/用户预下载的) 和 `CHECKPOINTS_DIR` (D6 训练产出归档). D7/D8 时这两个都要查, 所以 `search_dirs` 参数让调用方控制查的顺序.
- **数据集 yaml** 只有一个合法来源: `DATASET_CONFIGS_DIR` (D3 立的). D6/D7/D8 都从这里加载, 用法完全一致, 不需要参数化.

设计原则: **参数化不是免费的**——多一个参数, 多一种调用方式, 多一份测试覆盖. 真正需要才加, 没需要就不加.

> **金句**: **\"对称的 API 不一定是好 API. 让差异显眼比让差异藏起来更重要.\"**

## 4.3 `common/result.py` — TrainMetrics dataclass + log_train_metrics

### 问题

ultralytics 训练完返回一个 `DetMetrics` (或 `SegmentMetrics`) 对象, 字段散乱:
- `.task` (str)
- `.save_dir` (Path)
- `.fitness` (float)
- `.maps` (numpy array, 类别级 mAP)
- `.names` (dict[int, str], 类别名)
- `.results_dict` (dict[str, float], 一堆 metrics)
- `.speed` (dict[str, float], ms/image)

如果 D6 service.py 直接拿 `results.fitness`, `results.results_dict["metrics/mAP50(B)"]` 这样到处用, 有两个问题:

1. **跟 ultralytics 强耦合**——ultralytics 改 attr 名(他们历史上改过几次), D6 多处崩.
2. **没有"训练结果"的实体概念**——audit JSON 怎么写? D7 验证的 metrics 是不是跟训练的一样? 没有共同 dataclass 就重复造.

### 方案

写一个 `TrainMetrics` frozen dataclass, 它做两件事:
- **提取**: 从 ultralytics results 对象抽取所有想要的字段成结构化 dict
- **稳定**: 一旦 ultralytics 改字段名, 只动一个 `from_yolo_results` 方法

然后写一个**纯日志函数** `log_train_metrics(metrics, logger=...)`, 消费 `TrainMetrics` 漂亮打印.

⚠️ **设计点 (数据 / 日志分离)**: 老代码风格 `log_results(yolo_results)` 250 行揉两件事——既要 extract 又要 log. 分开之后, audit JSON 复用同一个 `TrainMetrics.to_dict()`, 单测可以单独测 extract 逻辑(不用 capture log).

```python
# ✅ 正例 — 数据和日志分离
metrics = TrainMetrics.from_yolo_results(yolo_results)
log_train_metrics(metrics, logger=logger)   # 给终端看
audit["metrics"] = metrics.to_dict()         # 给 JSON 看
db.save(metrics.to_dict())                   # 给 DB 看(未来 experiment_db)

# ❌ 反例 — 揉一块
log_and_extract_metrics(yolo_results)        # 想要 dict 怎么办? 重新解析一遍?
```

### 完整代码 — TrainMetrics

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : result.py
# @Project   : ODPlatform
# @Function  : 训练/验证结果 dataclass + 日志输出函数(数据/日志分离)
"""训练结果指标 dataclass + 日志输出函数.

设计:
  - TrainMetrics:    数据 dataclass (frozen, 给 audit/DB/log 共用)
  - log_train_metrics: 纯日志函数 (消费 TrainMetrics, 不持有数据)

复用: D7 ValService 直接共用 TrainMetrics — train/val 指标结构基本一致.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from odp_platform.common.constants import Task
from odp_platform.common.string_utils import pad_to_width

logger = logging.getLogger(__name__)


# ============================================================================
# task → 该任务下要 log 的 metric 字段列表 (数据驱动, 加新任务只加一行)
# ============================================================================
_METRIC_FIELDS_BY_TASK: dict[str, list[tuple[str, str]]] = {
    Task.DETECT: [
        ("metrics/precision(B)", "Precision(B)"),
        ("metrics/recall(B)",    "Recall(B)"),
        ("metrics/mAP50(B)",     "mAP50(B)"),
        ("metrics/mAP50-95(B)",  "mAP50-95(B)"),
    ],
    Task.SEGMENT: [
        ("metrics/precision(B)", "Precision(B)"),
        ("metrics/recall(B)",    "Recall(B)"),
        ("metrics/mAP50(B)",     "mAP50(B)"),
        ("metrics/mAP50-95(B)",  "mAP50-95(B)"),
        ("metrics/precision(M)", "Precision(M)"),
        ("metrics/recall(M)",    "Recall(M)"),
        ("metrics/mAP50(M)",     "mAP50(M)"),
        ("metrics/mAP50-95(M)",  "mAP50-95(M)"),
    ],
}


def _safe_float(value: Any, default: float = math.nan) -> float:
    """把 numpy scalar / None / 字符串安全转 float, 失败给 NaN."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class TrainMetrics:
    """训练/验证后 ultralytics results 的结构化快照.

    设计点:
      - frozen=True: 不可变, 给 audit_log 安全用
      - field 类型用 PEP 585 (dict / list 而不是 Dict / List)
      - speed_ms / overall / class_map_50_95 用 dict 而不是固定字段 — ultralytics
        的 results_dict 内容会随版本变, 字典更兼容
      - to_dict() 给 audit 用; log_train_metrics 给终端/文件 log 用
    """
    task:             str
    save_dir:         Path
    timestamp:        str
    speed_ms:         dict[str, float]
    overall:          dict[str, float]
    class_map_50_95:  dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_yolo_results(
        cls,
        results: Any,
        model_trainer: Any = None,
    ) -> "TrainMetrics":
        """从 ultralytics 的训练/验证结果对象构造 TrainMetrics."""
        # 1. task
        task = getattr(results, "task", "unknown")

        # 2. save_dir(results 优先, trainer 备胎, 都没就 unknown)
        save_dir_raw = getattr(results, "save_dir", None)
        if save_dir_raw is None and model_trainer is not None:
            save_dir_raw = getattr(model_trainer, "save_dir", None)
        save_dir = Path(save_dir_raw) if save_dir_raw is not None else Path("unknown")

        # 3. 速度信息(都是 ms/image)
        speed_raw = getattr(results, "speed", {}) or {}
        speed_ms: dict[str, float] = {
            "preprocess":  _safe_float(speed_raw.get("preprocess")),
            "inference":   _safe_float(speed_raw.get("inference")),
            "loss":        _safe_float(speed_raw.get("loss")),
            "postprocess": _safe_float(speed_raw.get("postprocess")),
        }
        valid = [v for v in speed_ms.values() if not math.isnan(v)]
        speed_ms["total"] = sum(valid) if valid else math.nan

        # 4. overall 指标
        results_dict = getattr(results, "results_dict", {}) or {}
        overall: dict[str, float] = {
            "fitness": _safe_float(getattr(results, "fitness", None)),
        }
        for k, v in results_dict.items():
            overall[k] = _safe_float(v)

        # 5. 类别级 mAP
        class_map: dict[str, float] = {}
        names = getattr(results, "names", {}) or {}
        maps = getattr(results, "maps", np.array([]))
        if names and hasattr(maps, "size") and maps.size > 0:
            for idx, class_name in names.items():
                if idx < maps.size:
                    class_map[class_name] = _safe_float(maps[idx])

        return cls(
            task=task,
            save_dir=save_dir,
            timestamp=datetime.now().isoformat(timespec="seconds"),
            speed_ms=speed_ms,
            overall=overall,
            class_map_50_95=class_map,
        )

    def to_dict(self) -> dict[str, Any]:
        """转 dict, 路径转字符串, NaN 转 None. 可直接 json.dumps."""
        def _clean_nan(d: dict[str, float]) -> dict[str, float | None]:
            return {k: (None if isinstance(v, float) and math.isnan(v) else v)
                    for k, v in d.items()}
        return {
            "task":            self.task,
            "save_dir":        str(self.save_dir),
            "timestamp":       self.timestamp,
            "speed_ms":        _clean_nan(self.speed_ms),
            "overall":         _clean_nan(self.overall),
            "class_map_50_95": _clean_nan(self.class_map_50_95),
        }
```

### 完整代码 — log_train_metrics

```python
def log_train_metrics(
    metrics: TrainMetrics,
    *,
    logger: logging.Logger | None = None,
    key_width: int = 20,
    section_width: int = 60,
) -> None:
    """把 TrainMetrics 漂亮打印到 logger."""
    log = logger or logging.getLogger(__name__)
    line = "=" * section_width
    thin = "-" * section_width

    log.info(line)
    log.info(f"训练结果 ({metrics.task.capitalize()} Task)".center(section_width))
    log.info(line)

    # 基本信息
    log.info("基本信息".center(section_width))
    log.info(thin)
    log.info(f"{pad_to_width('任务类型', key_width)}: {metrics.task}")
    log.info(f"{pad_to_width('保存目录', key_width)}: {metrics.save_dir}")
    log.info(f"{pad_to_width('时间戳', key_width)}: {metrics.timestamp}")

    # 处理速度
    log.info("处理速度 (ms/image)".center(section_width))
    log.info(thin)
    for k_disp, k_data in [
        ("预处理",   "preprocess"),
        ("推理",     "inference"),
        ("损失计算", "loss"),
        ("后处理",   "postprocess"),
        ("总计",     "total"),
    ]:
        val = metrics.speed_ms.get(k_data, math.nan)
        log.info(f"{pad_to_width(k_disp, key_width)}: {val:.3f} ms")

    # 整体指标
    log.info("整体评估指标".center(section_width))
    log.info(thin)
    log.info(f"{pad_to_width('Fitness 分数', key_width)}: "
             f"{metrics.overall.get('fitness', math.nan):.4f}")

    metric_fields = _METRIC_FIELDS_BY_TASK.get(metrics.task, [])
    if metric_fields:
        for raw_key, display in metric_fields:
            log.info(f"{pad_to_width(display, key_width)}: "
                     f"{metrics.overall.get(raw_key, math.nan):.4f}")
    else:
        log.info(f"(task='{metrics.task}' 不在 _METRIC_FIELDS_BY_TASK, "
                 f"打印 results_dict 全量)")
        for k, v in metrics.overall.items():
            if k == "fitness":
                continue
            log.info(f"{pad_to_width(k, key_width)}: {v:.4f}")

    # 类别级 mAP
    if metrics.class_map_50_95:
        log.info("类别级 mAP@0.5:0.95 (Box)".center(section_width))
        log.info(thin)
        valid = {k: v for k, v in metrics.class_map_50_95.items() if not math.isnan(v)}
        if valid:
            for class_name, mAP in sorted(valid.items(), key=lambda kv: kv[1], reverse=True):
                log.info(f"{pad_to_width(class_name, key_width)}: {mAP:.4f}")
        else:
            log.warning("类别 mAP 全为 NaN, 跳过打印")

    log.info(line)
```

⚠️ **设计点 (`_METRIC_FIELDS_BY_TASK` 是数据驱动)**: 加新任务(比如 pose / classify)只需要在这个 dict 加一行 `Task.POSE: [...]`, 不用动 `log_train_metrics` 的代码——经典的"数据驱动 > 方法驱动".

⚠️ **设计点 (task='unknown' fallback)**: 兜底逻辑把 `results_dict` 全量打出来——比直接报错友好得多. 如果 ultralytics 某个新版本改了 task 字段, D6 不会崩, 只是输出格式差点. 健壮性比美观重要.

## 4.4 `common/config_log.py` — 按字段维度的配置溯源日志

### 问题

D5 的 `merger.get_source_report()` 返回**按来源分组**的字符串:

```
CLI (3 项)
----------
  batch  = 32
  epochs = 200
  lr0    = 0.001

YAML (5 项)
----------
  imgsz     = 640
  optimizer = AdamW
  ...
```

按调参视角看不错, 但**每个字段的 provenance 散在多个段里**. 想看"batch 这个字段最终怎么来的"得在多个段里翻.

用户实际想要的是**按字段一行**:

```
batch     : 32        (来源: CLI)
epochs    : 200       (来源: CLI)
imgsz     : 640       (来源: YAML)
lr0       : 0.001     (来源: CLI)
optimizer : AdamW     (来源: YAML)
```

以及完整来源链:

```
batch     : 16(DEFAULT) <- 16(YAML) <- 32(CLI)
epochs    : 100(DEFAULT) <- 200(YAML)
lr0       : 0.01(DEFAULT) <- 0.01(YAML) <- 0.001(CLI)
```

### 方案

写两个函数, 都消费 D5 的 `merger.get_metadata(name)` 接口:

- `log_effective_config(config, merger, logger)`: 按字段当前值 + 来源, 一行一字段
- `log_override_chains(config, merger, logger)`: 按字段完整来源链 (DEFAULT → YAML → CLI 顺序)

⚠️ **设计点 (D5 chain 是 newest-first, 这里 reverse 成 oldest-first)**: D5 的 `ConfigMetadata.chain()` 返回 `[CLI 在前, YAML 中, DEFAULT 后]`——但用户阅读习惯是\"从默认开始, 一步步怎么变成现在\"——`DEFAULT → YAML → CLI`. 所以本模块 reverse 一下显示, 符合用户预期.

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : config_log.py
# @Project   : ODPlatform
# @Function  : 按字段维度打印配置参数信息 / 配置覆盖情况
"""配置参数日志输出.

跟 D5 的 get_source_report (按来源分组) 互补 — 本模块按字段一行展示.
"""
from __future__ import annotations

import logging
from typing import Any

from odp_platform.common.string_utils import pad_to_width


def log_effective_config(
    config: Any,
    merger: Any,
    *,
    logger: logging.Logger | None = None,
    key_width: int = 20,
    section_width: int = 60,
) -> None:
    """打印"配置参数信息" — 每个字段当前生效值 + 来源, 一行一个."""
    log = logger or logging.getLogger(__name__)

    log.info("=" * section_width)
    log.info("配置参数信息".center(section_width))
    log.info("-" * section_width)

    for field_name in config.__class__.model_fields.keys():
        value = getattr(config, field_name, None)
        meta = _safe_get_metadata(merger, field_name)
        source_label = meta.source_label if meta is not None else "未知"
        log.info(
            f"{pad_to_width(field_name, key_width)}: {value}  "
            f"(来源: {source_label})"
        )


def log_override_chains(
    config: Any,
    merger: Any,
    *,
    logger: logging.Logger | None = None,
    key_width: int = 20,
    section_width: int = 60,
) -> None:
    """打印"配置覆盖情况" — 每个字段的完整来源链(DEFAULT → YAML → CLI 顺序).

    跟 D5 get_conflict_report 的差别:
        - get_conflict_report 只展示**被覆盖**的字段, 只显示最近一次覆盖
        - 本函数展示**所有**字段(覆盖与否都有, 看出"为什么这值是这值")
        - 本函数完整链不只一步
        - 顺序是 oldest→newest 跟用户阅读习惯一致
    """
    log = logger or logging.getLogger(__name__)

    log.info("-" * section_width)
    log.info("配置覆盖情况".center(section_width))
    log.info("-" * section_width)

    for field_name in config.__class__.model_fields.keys():
        meta = _safe_get_metadata(merger, field_name)
        if meta is None:
            value = getattr(config, field_name, None)
            log.info(f"{pad_to_width(field_name, key_width)}: {value}")
            continue

        # D5 chain() 是 newest-first, reverse 成 oldest-first
        chain = list(reversed(meta.chain()))
        chain_str = " <- ".join(f"{m.value}({m.source_label})" for m in chain)
        log.info(f"{pad_to_width(field_name, key_width)}: {chain_str}")


def _safe_get_metadata(merger: Any, field_name: str) -> Any:
    """get_metadata 的防御性封装.

    merger 是 D5 的 ConfigMerger, 但万一测试时传了 mock 没这个方法, 不要崩.
    """
    if not hasattr(merger, "get_metadata"):
        return None
    try:
        return merger.get_metadata(field_name)
    except Exception:
        return None
```

⚠️ **设计点 (`_safe_get_metadata` 的防御性)**: 这是给单测留的口子. 主流程里 merger 总是 D5 真实 ConfigMerger, 这个分支永远走不到; 但测试 service 时常常传 MagicMock 跳过 D5 真实合并, 这时候 `merger.get_metadata` 是个 `MagicMock()`(不抛错但返回值也不对). 防御性封装让 service 测试不必处理这个细节.

## 4.5 `common/plot_style.py` — matplotlib 学术发表风格

### 问题

legacy 代码喜欢把 `plt.rcParams.update({...})` **写在训练脚本顶部**——任何 import 都会污染全局 rcParams. 一旦你写了 `from odp_platform.training import xxx`, 哪怕只是 import 一个工具函数, 整个 Python 进程的 matplotlib 出图都会被改成学术风格. 这是反模式.

### 方案

抽成函数 `apply_academic_style()`, **用户显式调用才生效**. CLI 的 `--academic-plots` 触发, Python API 用户也可以手动调.

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : plot_style.py
# @Project   : ODPlatform
# @Function  : matplotlib 学术发表风格(显式调用版, 不污染全局 import)
"""学术发表风格的 matplotlib 设置."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_ACADEMIC_RCPARAMS: dict[str, object] = {
    "font.family":        ["Times New Roman", "SimSun"],
    "font.size":          14,
    "axes.titlesize":     18,
    "axes.labelsize":     16,
    "xtick.labelsize":    14,
    "ytick.labelsize":    14,
    "legend.fontsize":    14,
    "figure.titlesize":   20,
    "savefig.dpi":        600,
    "savefig.format":     "png",
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.1,
    "figure.constrained_layout.use": True,
}


def apply_academic_style(
    *,
    use_matplotx: bool = True,
    matplotx_style: str = "pitaya_smoothie_light",
) -> bool:
    """对当前 Python 进程的 matplotlib 全局应用学术发表风格.

    ⚠️ 调用此函数后, 当前 Python 进程内所有 matplotlib 出图都会受影响.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib 未安装, 跳过学术风格应用")
        return False

    # rcParams (基础配置, 永远生效)
    plt.rcParams.update(_ACADEMIC_RCPARAMS)
    logger.info(f"已应用学术 rcParams ({len(_ACADEMIC_RCPARAMS)} 项)")

    # matplotx 配色 (可选, 没装也不报错)
    if use_matplotx:
        try:
            import matplotx
            if "_" in matplotx_style and matplotx_style.endswith(("_light", "_dark")):
                style_name, _, variant = matplotx_style.rpartition("_")
                style_dict = getattr(matplotx.styles, style_name, None)
                if isinstance(style_dict, dict) and variant in style_dict:
                    plt.style.use(style_dict[variant])
                    logger.info(f"已应用 matplotx 配色: {matplotx_style}")
                else:
                    logger.warning(f"matplotx 找不到 style: {matplotx_style}")
            else:
                plt.style.use(matplotx_style)
                logger.info(f"已应用 matplotx 配色: {matplotx_style}")
        except ImportError:
            logger.info("matplotx 未安装, 跳过配色(rcParams 仍生效)")
        except (KeyError, AttributeError, ValueError) as e:
            logger.warning(f"matplotx 配色应用失败: {e}(rcParams 仍生效)")

    return True
```

⚠️ **设计点 (matplotx 可选依赖)**: matplotx 装了能用就用, 没装也不报错, rcParams 仍生效. 这是给"我只想要学术字体, 不要花哨配色"的用户留的渐进式开关.

## 4.6 git commit (5 个 common 工具)

阶段 5 还有一个 `log_rename` 要专门讲, 一起 commit 不合并到这里——下面的 5 个先各自 commit:

```bash
git add apps/platform/src/odp_platform/common/model_path.py
git commit -m "feat(common): add resolve_model_path with search_dirs

3 分支策略:
  1. 绝对路径 → 直接用
  2. 仅文件名 → 按 search_dirs 顺序找
  3. 都没命中 → 返回原值, 让 ultralytics 自己处理

search_dirs 默认 [PRETRAINED_MODELS_DIR], D7/D8 时可以传
[CHECKPOINTS_DIR, PRETRAINED_MODELS_DIR] 优先查 D6 归档产物.

Why:
  - 模型权重有两个合法来源(预训练 / 归档)
  - 参数化让 D7/D8 不用重复造 resolve
"

git add apps/platform/src/odp_platform/common/dataset_path.py
git commit -m "feat(common): add resolve_dataset_path

跟 resolve_model_path 同款 3 分支, 但不参数化 search_dirs —
DATASET_CONFIGS_DIR 是唯一 SSoT, 没必要让调用方控制."

git add apps/platform/src/odp_platform/common/result.py
git commit -m "feat(common): add TrainMetrics + log_train_metrics (data/log split)

  - TrainMetrics: frozen dataclass, from ultralytics results
  - log_train_metrics: pure logging fn, consumes TrainMetrics
  - _METRIC_FIELDS_BY_TASK 数据驱动, 加新任务只加一行

D7 ValService 可以直接复用 TrainMetrics — val/train 指标结构同款."

git add apps/platform/src/odp_platform/common/config_log.py
git commit -m "feat(common): add config_log (effective + override chains)

  - log_effective_config: 按字段一行 + 当前值 + 来源
  - log_override_chains:  按字段一行 + 完整来源链(DEFAULT → CLI 顺序)

跟 D5 的 get_source_report (按来源分组) 互补 — 按字段视角看更直观."

git add apps/platform/src/odp_platform/common/plot_style.py
git commit -m "feat(common): add plot_style.apply_academic_style

  - 抽成函数, 不再写在脚本顶部污染全局 rcParams
  - matplotx 配色可选(没装也不报错, rcParams 仍生效)
  - 用户显式调用才生效: CLI --academic-plots 或 Python API"
```

下一阶段我们去填第 6 个 common 工具——`log_rename`, 它有撞墙③要展开.


---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 5: 日志名跟 save_dir 对齐 — log_rename

这一阶段写最后一个 common 工具 `log_rename`. 它单独成章, 因为这里有一个**关于"什么时候才知道日志该叫什么名"** 的关键问题, 它的解法是 D6 整套设计里最巧的一处.

## 5.1 🧱 撞墙③: ultralytics save_dir 训练前不知道

请你想象一下: 你正在 CLI 入口装日志 handler. 你想让日志名跟 ultralytics 的 `save_dir` 对齐, **方便用户 ls 一下就能配对**. 比如:

```
runs/detect_train/train3/        ← ultralytics save_dir
logging/train/train3_<ts>_yolo11n.log    ← 对应日志
```

**问题**: ultralytics 的 save_dir 是 `train / train2 / train3` **自增编号**——你在训练**开始之前**根本不知道这次会编到几号. 等 `model.train()` 返回, save_dir 才落定.

但是日志在训练**开始之前**就要建立(否则训练阶段的日志都丢). 所以日志名只能先用占位:

```
logging/train/train_<timestamp>.log    ← D2 get_logger 默认就长这样
```

**矛盾出现**: 训练前不知道 save_dir, 但日志要先建立. 训练后知道 save_dir, 但日志已经在写了——文件名已经定了, 改不改?

🤔 **思考题 (30 秒)**: 你能想到几种解决方案?

我能想到 3 种:

**方案 A — audit JSON 记 log_path 字段**

不改日志名. 训练完写一份 `odp_audit.json` 到 `runs/detect_train/train3/`, 里面 `log_path` 字段指向 `logging/train/train_<timestamp>.log`. 用户想查"train3 对应哪份日志", 打开 audit JSON 看一眼.

- 优点: 0 操作 handler, 零风险
- 缺点: 多一步——用户必须**打开 JSON 才能查**到对应关系. `ls` 看不出来.

**方案 B — 训练完物理 rename 日志文件**

训练完, 拿到 save_dir, 把 `logging/train/train_<ts>.log` 物理 rename 成 `logging/train/<save_dir.name>_<ts>_<model>.log`. 同时把 FileHandler 重定向到新文件.

- 优点: `ls logging/train/` 一眼就能跟 `ls runs/detect_train/` 配对.
- 缺点: 三步走(close handler → 物理 rename → 新建 handler)每步都有失败模式, Windows 上文件句柄释放慢经常 rename 不动.

**方案 C — 训练完把日志拷贝一份进 save_dir**

不动原日志, 训练完 `shutil.copy2(log_path, save_dir / log_path.name)`. 在 ultralytics 的输出目录里留一份完整训练日志的快照.

- 优点: 零风险(拷贝不动原 handler), `cat runs/detect_train/train3/train_<ts>.log` 也能看到完整日志
- 缺点: 多一份日志副本, 占空间; 还是没改 `logging/train/` 那一边的命名问题——用户仍然 `ls logging/train/` 看不出对应

## 5.2 D6 选方案 B + A 组合

实际选择: **方案 B 做主, 方案 A 兜底**.

理由:
- **B 的命名价值最大**——`ls logging/train/` 一眼对得上 `ls runs/detect_train/` 是日常最高频的需求, 不能为了"零风险"放弃这个体验.
- **B 的风险用边界设计治住**——下面会讲, 操作 D2 named root + best-effort 永不抛 + 失败回滚, 单点失败不影响训练结果.
- **A 的 audit JSON 仍然写**——即使 B 失败, audit JSON 里仍有 log_path 字段, 用户仍能找到对应——`odp_audit.json` 是双保险.

## 5.3 log_rename 的实现要点

### 要点 1 — 操作 D2 named root, 不是 unnamed root

这是 §3 撞墙②的延续:

```python
# ❌ 反模式 — 在 unnamed root 上找 FileHandler
root = logging.getLogger()                  # ← unnamed root, D2 没在这里挂任何东西
for h in root.handlers:
    if isinstance(h, logging.FileHandler):
        ...   # 永远找不到, D2 的 FileHandler 在 "odp_platform" 上

# ✅ 正解 — 操作 D2 named root
root = logging.getLogger("odp_platform")    # ← named root, D2 把 FileHandler 挂在这里
for h in root.handlers:
    if isinstance(h, logging.FileHandler):
        ...
```

⚠️ **设计点 (硬编码 `"odp_platform"` 而不是 import D2 常量)**: 你可能会想"我从 `logging_utils` import 那个 `ROOT_LOGGER_NAME` 常量, 别硬编码". **不要**——D2 logging_utils 可能反向 import log_rename(比如未来某天 logging_utils 想做"先 init log 再 rename"的优化), import 就循环了. 硬编码加一行注释\"如果 D2 改名, 这里也要改\"——简单粗暴但稳.

```python
# log_rename.py 顶部
ROOT_LOGGER_NAME: str = "odp_platform"
# ↑ 硬编码避免 import 循环依赖; 如果 D2 改名, 这里也要改
```

### 要点 2 — 调用方不持有 FileHandler

D6 的所有调用方(service / cli)**都不持有 FileHandler**. log_rename 自己去 named root 上找:

```python
# ✅ 正解 — 调用方不传 handler
file_handler = next(
    (h for h in root.handlers if isinstance(h, logging.FileHandler)),
    None,
)

# ❌ 反例 — 让调用方传 handler 进来
def rename_log_to_save_dir(save_dir, model_stem, file_handler):  # ← 调用方持有 handler
    ...
```

这跟 §3 的"业务模块只发声"纪律一致——`service.train()` 永远不感知 FileHandler 存在.

### 要点 3 — 三步走 + 失败回滚

完整流程:

```
1. 找到 named root 上的 FileHandler
   - 没找到 → 跳过, warning, 返回 None (单测场景没调 get_logger 是合法的)
2. 从原文件名提取时间戳 (正则匹配 D2 的 datetime 格式)
   - 提取失败 → 用占位符 'unknown-time'
3. 计算新文件名: <save_dir.name>_<timestamp>_<model_stem>.log
4. 关闭旧 handler 释放文件句柄(Windows 必须先关才能 rename)
5. 物理 rename
   - 失败 → 回滚: 重新挂回旧文件的 handler, 让后续日志不丢
6. 创建新 FileHandler 指向新文件
   - 失败 → error log, 但文件本身改名是成功的, 返回 new_path
7. 成功: info log "日志文件已重命名: <name>"
```

每一步都有失败处理. **永不抛异常**——失败靠 logger.warning 表达, 不影响训练结果.

### 要点 4 — 时间戳正则要匹配 D2 的格式

D2 的 `get_logger` 用 `datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:21]` 生成时间戳, 即 `20260524-001234-567`(末尾 `-567` 是微秒前 3 位). 正则要把这个吃进去:

```python
_TIMESTAMP_RE = re.compile(r"(\d{8}-\d{6}(?:-\d+)?)")
# 匹配 20260524-001234 后可能跟 -<微秒前几位>; 把可选微秒尾也吃进去
```

⚠️ **设计点 (为什么不用 datetime.now() 重新生成)**: 你可能想"训练时长那么久, rename 时重新 `datetime.now()` 就好了". **不行**——新时间戳跟原文件名的时间戳对不上, 用户想知道"这次训练**开始**的时间", 看的应该是日志文件名里的时间戳, 不是 rename 那一刻的. 时间戳要**复用原文件名里的**.

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : log_rename.py
# @Project   : ODPlatform
# @Function  : 训练结束后, 把 D2 'odp_platform' 根 logger 的日志文件名跟 ultralytics save_dir 对齐
"""日志文件重命名.

ultralytics 训练完才知道 save_dir 的实际名字 (train / train2 / train3 ...),
而日志在训练**开始之前**就要建立, 名字只能是占位.

本模块在训练结束后, 把已经在写的日志文件 rename 成跟 save_dir 对齐的名字,
**同时**把对应的 FileHandler 重定向到新文件, 让训练结束之后的日志(归档/审计/
最终统计)依然能写进同一份日志.

★ 设计纪律:
  - 操作对象是 D2 'odp_platform' **named root logger**, 不是 unnamed root.
  - 调用方不需要持有 FileHandler — 本模块自己去 named root 上找.

命名格式:
  原文件名(D2 get_logger 产出): train_<timestamp>.log
  新文件名:                     <save_dir.name>_<timestamp>_<model_stem>.log
  例: train3_20260524-001234-567_yolo11n.log
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

# 跟 D2 logging_utils.ROOT_LOGGER_NAME 对齐 (硬编码避免循环依赖)
ROOT_LOGGER_NAME: str = "odp_platform"

logger = logging.getLogger(__name__)

# 匹配 D2 时间戳格式: 20260524-001234 后可能跟 -<微秒前几位>
_TIMESTAMP_RE = re.compile(r"(\d{8}-\d{6}(?:-\d+)?)")


def rename_log_to_save_dir(
    save_dir: Path,
    model_stem: str,
) -> Path | None:
    """把 'odp_platform' 根 logger 的 FileHandler 改名跟 save_dir 对齐.

    Args:
        save_dir:   ultralytics 实际 save_dir (e.g. runs/detect_train/train3)
        model_stem: 模型 stem (e.g. 'yolo11n', 用于新文件名)

    Returns:
        新文件 Path. 失败时返回 None (失败原因通过 logger.warning 输出).

    永不抛异常 — 改名失败靠 logger.warning 表达, 不影响训练结果本身.
    """
    root = logging.getLogger(ROOT_LOGGER_NAME)

    # 1. 在 named root 上找 FileHandler
    file_handler = next(
        (h for h in root.handlers if isinstance(h, logging.FileHandler)),
        None,
    )
    if file_handler is None:
        logger.warning(
            f"'{ROOT_LOGGER_NAME}' 根 logger 上没有 FileHandler, "
            f"跳过日志改名 (CLI 入口可能没调 get_logger?)"
        )
        return None

    old_path = Path(file_handler.baseFilename)

    # 2. 从原文件名提取时间戳
    match = _TIMESTAMP_RE.search(old_path.stem)
    if match:
        timestamp = match.group(1)
    else:
        timestamp = "unknown-time"
        logger.warning(f"原日志文件名缺时间戳, 用占位符: {old_path.name}")

    new_name = f"{save_dir.name}_{timestamp}_{model_stem}.log"
    new_path = old_path.parent / new_name

    if new_path == old_path:
        return old_path     # 已经对齐, 不重复操作

    # 3. 保存旧 handler 配置给新 handler 复用
    formatter = file_handler.formatter
    level = file_handler.level
    encoding = getattr(file_handler, "encoding", None) or "utf-8"

    # 4. 关闭旧 handler 释放文件句柄(Windows 必须先关才能 rename)
    file_handler.close()
    root.removeHandler(file_handler)

    # 5. 物理 rename
    if not old_path.exists():
        logger.warning(f"旧日志文件不存在, 无法改名: {old_path}")
        return None

    try:
        old_path.rename(new_path)
    except OSError as e:
        logger.warning(f"日志 rename 失败 ({e}), 尝试恢复旧 handler 继续写...")
        # 失败回滚: 重新挂回旧文件, 确保后续日志不丢
        try:
            restored = logging.FileHandler(old_path, encoding=encoding)
            if formatter:
                restored.setFormatter(formatter)
            restored.setLevel(level)
            root.addHandler(restored)
        except OSError as e2:
            logger.error(f"回滚 handler 也失败 ({e2}) — 后续日志可能丢失")
        return None

    # 6. 新 handler 指向新文件
    try:
        new_handler = logging.FileHandler(new_path, encoding=encoding)
        if formatter:
            new_handler.setFormatter(formatter)
        new_handler.setLevel(level)
        root.addHandler(new_handler)
    except OSError as e:
        logger.error(
            f"创建新 FileHandler 失败 ({e}) — 文件已改名, 但后续日志写不进新文件"
        )
        return new_path

    logger.info(f"日志文件已重命名: {new_path.name}")
    return new_path
```

## 5.4 这就是 §3 那个"合法豁免"

§3 规矩 A 说"业务模块不碰 `addHandler / setLevel`". `log_rename.py` 显然违反了——它 `close()` 旧 handler、`removeHandler()`、`addHandler()` 新的. 为什么这是合法豁免?

因为**它的工作本身就是配 handler**——这不是"业务逻辑顺带配了 handler"那种违反纪律, 这是"专门一个模块的唯一职责就是替换 named root 上的 FileHandler". 跟 D2 `get_logger` 同性质——D2 也违反"业务模块只发声"纪律(它是装 handler 的那个), 因为它的职责就是装.

⚠️ **设计点 (区分"违反纪律"和"职责本身就是这个")**: 看一个模块是否合法豁免, 问一个问题:"这个模块的**唯一职责**是不是就是 logging 配置?"如果是, 合法豁免. 如果不是(业务模块顺手配了 handler), 违反纪律.

| 模块 | 职责 | 配 handler 合法? |
|---|---|---|
| `common/logging_utils.py` (D2) | 装基础 handler | ✓ 合法 |
| `common/log_rename.py` (D6) | 替换 named root 的 FileHandler | ✓ 合法 |
| `cli/train_model.py` (D6) | CLI 入口, 调 D2 get_logger 触发装载 | ✓ 合法 |
| `training/service.py` (D6) | 训练编排 | ✗ 不合法 |
| `common/result.py` (D6) | 训练指标 dataclass | ✗ 不合法 |
| 其他 business 模块 | 业务逻辑 | ✗ 不合法 |

> **金句**: **\"看一个模块是否合法配 handler, 问'这是不是它的唯一职责'. 是, 就合法; 不是, 就是违反纪律.\"**

## 5.5 git commit

```bash
git add apps/platform/src/odp_platform/common/log_rename.py
git commit -m "feat(common): add log_rename (operates on D2 named root)

  - 训练后把日志名改成 <save_dir.name>_<ts>_<model>.log
  - 操作 'odp_platform' named root (不是 unnamed root)
  - 调用方不持有 FileHandler, 本模块自己探测
  - 三步走 + 失败回滚, 永不抛异常

Why:
  - ls logging/train/ 一眼跟 ls runs/detect_train/ 对得上
  - 比 audit JSON 查映射体验好(audit JSON 仍然写, 双保险)
"
```

下一阶段我们写 training/ 训练专属的两个模块: archive + service.


---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 6: training/ 训练专属 (archive + service)

`common/` 6 个工具齐了, 该写 `training/` 自己的两个模块——`archive.py` (权重归档) 和 `service.py` (TrainService 编排器). 这俩**只有训练用**, D7 / D8 不复用——验证 / 推理本来就不产权重, 也不需要"配置 → 数据校验 → 训练 → 归档"的编排.

## 6.1 archive.py — 权重归档

### 问题

ultralytics 把 best.pt / last.pt 存在工作目录 `runs/detect_train/train3/weights/`——但这是它的**工作目录**, 跟下次训练 / 验证 / 推理的"权重仓库"完全不同位置. D7 ValService 怎么找到"上次训练 train3 的 best"? 难道遍历 `runs/detect_train/train*` 比对时间戳猜?

ODPlatform 立了 `CHECKPOINTS_DIR` 作为**权重归档的 SSoT**. 训练完把 best/last 复制一份过去, 带时间戳和实验后缀防止跨实验覆盖.

### 命名格式

`<train_dir_name>-<timestamp>-<model_stem>-<best|last>.pt`

例: `train3-20260524-103045-yolo11n-best.pt`

四段信息:
- `train3` — ultralytics save_dir 名(对得上 `runs/detect_train/train3/`)
- `20260524-103045` — 归档时间戳(不是训练开始时间)
- `yolo11n` — 模型 stem(知道这是哪个 backbone)
- `best | last` — 权重类型

⚠️ **设计点 (归档 vs 原文件不删)**: 原 `runs/detect_train/train3/weights/best.pt` **保留**——ultralytics resume 训练 / val 直接用 save_dir 都需要原文件. 归档 = 复制一份, 不是搬走.

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : archive.py
# @Project   : ODPlatform
# @Function  : 训练完归档 best/last.pt 到 CHECKPOINTS_DIR
"""权重归档.

ultralytics 训练完产出 `<train_dir>/weights/best.pt` 和 `last.pt`,
本模块把它们复制一份到 ODPlatform 的 CHECKPOINTS_DIR (权重归档 SSoT),
重命名带上时间戳和训练目录后缀, 防止跨实验覆盖.

命名格式: `<train_dir_name>-<timestamp>-<model_stem>-<best|last>.pt`
例: `train3-20260523-103045-yolo11n-best.pt`

归档逻辑跟 ultralytics 的输出完全解耦:
  - 原文件保留在 train_dir/weights/ (供 ultralytics resume/val 用)
  - 归档文件供 D7 ValService / D8 InferService 通过 CHECKPOINTS_DIR 引用
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from odp_platform.common.paths import CHECKPOINTS_DIR

logger = logging.getLogger(__name__)


def archive_checkpoints(
    train_dir: Path,
    model_filename: str | Path,
    *,
    checkpoint_dir: Path | None = None,
) -> dict[str, Path]:
    """归档 best.pt 和 last.pt 到 CHECKPOINTS_DIR.

    Args:
        train_dir:       ultralytics 训练输出目录 (e.g. runs/detect_train/train3)
        model_filename:  模型名 (用来生成归档文件名, e.g. 'yolo11n.pt' → 'yolo11n')
        checkpoint_dir:  归档目录 (默认 CHECKPOINTS_DIR, 测试时可注入临时目录)

    Returns:
        {'best': PosixPath('.../train3-20260523-103045-yolo11n-best.pt'),
         'last': PosixPath('.../train3-20260523-103045-yolo11n-last.pt')}
        某个文件不存在 / 复制失败时, 该 key 不在返回字典里(best-effort).

    永不抛异常 — train_dir 不存在 / 权限错误 / 磁盘满都靠 logger.warning 表达,
    返回空字典让调用方决定下一步.
    """
    checkpoint_dir = checkpoint_dir or CHECKPOINTS_DIR
    results: dict[str, Path] = {}

    # 防御 1: train_dir 必须存在且是目录
    if not train_dir.is_dir():
        logger.warning(f"训练目录不存在或不是目录, 跳过归档: {train_dir}")
        return results

    # 防御 2: 归档目录 mkdir(idempotent)
    try:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning(f"创建归档目录失败, 跳过归档: {e}")
        return results

    # 准备命名组件
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_model_name = Path(model_filename).stem      # 'yolo11n.pt' → 'yolo11n'
    train_suffix = train_dir.name                    # 'train3'

    # 逐个复制 best / last
    for model_type in ("best", "last"):
        src_path = train_dir / "weights" / f"{model_type}.pt"
        if not src_path.exists():
            logger.warning(f"未找到权重文件, 跳过: {src_path}")
            continue

        dest_name = f"{train_suffix}-{timestamp}-{base_model_name}-{model_type}.pt"
        dest_path = checkpoint_dir / dest_name

        try:
            shutil.copy2(src_path, dest_path)        # copy2 保留 mtime/permissions
            logger.info(f"权重已归档: {dest_path.name}")
            results[model_type] = dest_path
        except (OSError, shutil.Error) as e:
            logger.warning(f"归档 {model_type}.pt 失败: {e}")

    return results
```

⚠️ **设计点 (`checkpoint_dir` 注入开关)**: 关键字参数 `checkpoint_dir` 默认 `CHECKPOINTS_DIR`(走 paths.py 的 SSoT). 测试时可以注入 `tmp_path / "fake_ckpt"` 防止污染真实归档目录. 这是给单测的标准做法.

⚠️ **设计点 (best-effort 永不抛)**: archive 失败**绝不影响训练结果**——训练已经成功跑完, best/last.pt 都在工作目录 `runs/detect_train/train3/weights/` 里, 只是没复制到归档目录. 用户最坏情况是"自己手动复制一下", 不应该让 archive 失败把 `TrainResult.success` 整成 False.

## 6.2 service.py — TrainService 8 阶段编排

### service.py 的 8 个阶段

D6 `TrainService.train()` 内部分 8 个阶段, 每个阶段调一个邻居子系统或本地工具:

```
阶段 1: 配置加载            → 调 D5 build_train_config(yaml, cli_args)
阶段 2: 上下文日志           → 调 D2 log_device_info + common.config_log
阶段 3: 数据集预校验          → 调 D4 validate_dataset + render_to_logger
阶段 4: 加载模型             → ultralytics.YOLO(model_path)
阶段 5: 执行训练             → model.train(**yolo_kwargs)
阶段 6: 结果指标             → common.result (TrainMetrics + log_train_metrics)
阶段 7: 整理输出             → common.log_rename + training.archive
阶段 8: 审计快照             → 写 odp_audit.json
```

每个阶段只有几行代码——**纯编排, 不发明新方法**.

### 设计点 (顺序很重要)

⚠️ **设计点 (上下文日志在 D4 校验之前)**: 阶段 2 把数据集声明 / 解析路径 / 模型声明 / 解析路径都立即 log 出来——**即使阶段 3 D4 校验失败崩了, 用户也已经看到这次训练打算用什么**. 这是诊断体验的关键: 错误信息要让用户立刻看出"我在训啥", 而不是"训啥来着? 怎么崩了".

⚠️ **设计点 (log_rename 在 archive 之前)**: 阶段 7 先 rename 日志再 archive 权重——这样**归档动作本身也能写进新文件名的日志里**. 如果反过来, archive 时的 log 还是写在旧文件名里, 用户拿 `train3_xxx.log` 看不到归档过程.

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : service.py
# @Project   : ODPlatform
# @Function  : TrainService — 编排 D5 配置 + D4 校验 + D2 系统 + ultralytics 训练
"""训练服务编排器.

★ 核心纪律: 不重新发明 D5 / D4 / D2 已有的轮子. 这个 service 内部:
  - 不写 YAMLLoader / CLILoader / ConfigMerger 调用 (走 build_train_config)
  - 不读 data.yaml 数样本 (走 validate_dataset)
  - 不配 logging handler / 不感知 FileHandler 细节
    (handler 由 D2 logging_utils.get_logger() 在 CLI 入口装好)

验证方式:
  grep "YAMLLoader\\|CLILoader\\|ConfigMerger\\|build_snapshot" service.py
  → 应该没有任何输出. 子系统边界清晰的硬指标.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ultralytics import YOLO

from odp_platform.common.config_log import log_effective_config, log_override_chains
from odp_platform.common.dataset_path import resolve_dataset_path
from odp_platform.common.log_rename import rename_log_to_save_dir
from odp_platform.common.model_path import resolve_model_path
from odp_platform.common.paths import RUNS_DIR
from odp_platform.common.result import TrainMetrics, log_train_metrics
from odp_platform.common.system_utils import log_device_info
from odp_platform.data_validation import render_to_logger, validate_dataset
from odp_platform.runtime_config import build_train_config

from .archive import archive_checkpoints

logger = logging.getLogger(__name__)


def _find_project_log_path() -> Path | None:
    """从 D2 'odp_platform' 根 logger 找 FileHandler 的实际文件路径.

    只读检查, 不操作 handler. 给 audit JSON 用.
    """
    root = logging.getLogger("odp_platform")
    for h in root.handlers:
        if isinstance(h, logging.FileHandler):
            return Path(h.baseFilename)
    return None


@dataclass(frozen=True)
class TrainResult:
    """训练结果一次性快照."""
    success:     bool
    output_dir:  Path
    best_weight: Path | None = None
    last_weight: Path | None = None
    metrics:     dict[str, float] = field(default_factory=dict)
    train_time:  float | None = None
    error:       str | None = None
    audit_path:  Path | None = None
    log_path:    Path | None = None


class TrainService:
    """YOLO 训练流程编排."""

    def __init__(self) -> None:
        """__init__ 不接任何参数 — 配置都通过 train() 传."""
        pass

    def train(
        self,
        yaml_path: str | Path | None = None,
        cli_args: dict[str, Any] | None = None,
        *,
        pre_validate: bool = True,
        archive: bool = True,
        rename_log: bool = True,
    ) -> TrainResult:
        """跑一次完整训练."""
        start = datetime.now()
        output_dir: Path | None = None

        try:
            # ============================================================
            # 阶段 1: 配置加载 (★ D5 接口承诺兑现, 一行)
            # ============================================================
            config, merger = build_train_config(
                yaml_path=yaml_path,
                cli_args=cli_args,
            )

            # ============================================================
            # 阶段 2: 上下文日志 (D2 系统快照 + D5 字段溯源)
            # ============================================================
            logger.info("=" * 60)
            logger.info(f"开始 YOLO 训练 (task={config.task})".center(60))
            logger.info("=" * 60)

            # 立即展示核心标识 — 即使后面崩, 用户也看到"在训啥"
            raw_model = config.model or "yolo11n.pt"
            raw_data = config.data
            logger.info(f"任务类型:    {config.task}")
            logger.info(f"数据集(声明): {raw_data}")
            data_path = resolve_dataset_path(raw_data)
            logger.info(f"数据集(解析): {data_path}")
            logger.info(f"模型(声明):  {raw_model}")
            model_path = resolve_model_path(raw_model)
            logger.info(f"模型(解析):  {model_path}")

            # D2 系统快照
            log_device_info()

            # D5 字段溯源 (两段: 当前值/来源 + 完整链)
            log_effective_config(config, merger, logger=logger)
            log_override_chains(config, merger, logger=logger)

            # ============================================================
            # 阶段 3: 数据集预校验 (D4, 可关)
            # ============================================================
            if pre_validate:
                logger.info("=" * 60)
                logger.info("数据集预校验 (D4)".center(60))
                logger.info("=" * 60)
                report = validate_dataset(data_path, task_type=config.task)
                render_to_logger(report, logger=logger)
                # exit_code: 0=PASS/INFO 1=WARNING 2=ERROR
                if report.exit_code >= 2:
                    error_count = len([
                        r for r in report.results
                        if getattr(r, "severity", None) == "ERROR"
                    ])
                    raise RuntimeError(
                        f"数据集校验失败 ({error_count} 个 ERROR 级问题). "
                        f"请用 `odp-validate --dataset {data_path.stem} "
                        f"--task {config.task}` 修复后再训练. "
                        f"如要跳过校验跑训练(不推荐), 加 --no-pre-validate."
                    )

            # ============================================================
            # 阶段 4: 加载模型
            # ============================================================
            model = YOLO(str(model_path))

            # ============================================================
            # 阶段 5: 执行训练 (ultralytics)
            # ============================================================
            yolo_kwargs = config.to_ultralytics_kwargs()
            # 用解析后的绝对路径覆盖 — 防 ultralytics 拿 'rsod.yaml' 这种
            # 相对名在 cwd 找不到
            yolo_kwargs["data"] = str(data_path)
            # 用户没指定 project 时, 走 RUNS_DIR/<task>_train/ 作为输出根.
            # 扁平化命名 <task>_<mode>: 最终路径形如 runs/detect_train/train,
            # runs/detect_train/train2. D7 评估走 runs/detect_val/, D8 推理走
            # runs/detect_infer/ — 它们在 RUNS_DIR 下一级并列, 不互相穿过.
            # 不做 runs/train/detect/ 这种嵌套(detect 会变成"穿过层", 视觉很丑).
            yolo_kwargs.setdefault("project", str(RUNS_DIR / f"{config.task}_train"))

            logger.info("=" * 60)
            logger.info("启动训练".center(60))
            logger.info("=" * 60)
            logger.info(f"输出目录(project): {yolo_kwargs['project']}")

            yolo_results = model.train(**yolo_kwargs)
            output_dir = Path(yolo_results.save_dir)

            # ============================================================
            # 阶段 6: 结果指标
            # ============================================================
            logger.info("=" * 60)
            logger.info("训练完成".center(60))
            logger.info("=" * 60)
            metrics = TrainMetrics.from_yolo_results(
                yolo_results, model_trainer=getattr(model, "trainer", None)
            )
            log_train_metrics(metrics, logger=logger)

            # ============================================================
            # 阶段 7: 整理输出 (rename_log 先, archive 后)
            # ============================================================
            model_stem = Path(raw_model).stem

            # 7a. 改日志名跟 save_dir 对齐(归档动作也能进新文件名的日志)
            if rename_log:
                rename_log_to_save_dir(output_dir, model_stem)

            # 7b. 归档权重
            archived: dict[str, Path] = {}
            if archive:
                archived = archive_checkpoints(
                    train_dir=output_dir,
                    model_filename=raw_model,
                )

            # ============================================================
            # 阶段 8: 审计快照 (★ 给未来 experiment_db 留落点)
            # ============================================================
            audit_path = output_dir / "odp_audit.json"
            log_path = _find_project_log_path()
            try:
                audit_payload = {
                    "config":  config.to_audit_snapshot(),
                    "merger":  merger.to_audit_log(),
                    "metrics": metrics.to_dict(),
                    "result_summary": {
                        "best_archive": str(archived.get("best", "")) or None,
                        "last_archive": str(archived.get("last", "")) or None,
                        "train_time_sec": (datetime.now() - start).total_seconds(),
                        "log_path": str(log_path) if log_path else None,
                    },
                }
                audit_path.write_text(
                    json.dumps(audit_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(f"审计快照: {audit_path}")
            except OSError as e:
                logger.warning(f"写审计快照失败(不影响训练结果): {e}")
                audit_path = None

            # ============================================================
            # 收尾 — TrainResult
            # ============================================================
            train_time = (datetime.now() - start).total_seconds()
            best_weight = archived.get("best") or (output_dir / "weights" / "best.pt")
            last_weight = archived.get("last") or (output_dir / "weights" / "last.pt")

            logger.info("=" * 60)
            logger.info(f"训练总耗时: {train_time:.2f} 秒")
            logger.info(f"输出目录:   {output_dir}")
            logger.info(f"最佳权重:   {best_weight}")
            if log_path:
                logger.info(f"本次日志:   {log_path}")
            logger.info("=" * 60)

            return TrainResult(
                success=True,
                output_dir=output_dir,
                best_weight=best_weight if best_weight.exists() else None,
                last_weight=last_weight if last_weight.exists() else None,
                metrics=metrics.overall,
                train_time=train_time,
                audit_path=audit_path,
                log_path=log_path,
            )

        # =====================================================================
        # 顶层异常拦截 — 永不抛, 打包成 TrainResult.error
        # =====================================================================
        except Exception as e:
            logger.error(f"训练失败: {e}", exc_info=True)
            train_time = (datetime.now() - start).total_seconds()
            return TrainResult(
                success=False,
                output_dir=output_dir or Path("unknown"),
                metrics={},
                train_time=train_time,
                error=str(e),
                log_path=_find_project_log_path(),  # 失败也带日志路径, 方便排查
            )


def train_yolo(
    yaml_path: str | Path | None = None,
    cli_args: dict[str, Any] | None = None,
    *,
    pre_validate: bool = True,
    archive: bool = True,
    rename_log: bool = True,
) -> TrainResult:
    """一行启动训练 — 风格跟 D5 build_train_config 一致."""
    service = TrainService()
    return service.train(
        yaml_path=yaml_path,
        cli_args=cli_args,
        pre_validate=pre_validate,
        archive=archive,
        rename_log=rename_log,
    )
```

## 6.3 odp_audit.json — 给 experiment_db 留落点

阶段 8 写出来的 `odp_audit.json` 是 D6 跟未来 experiment_db 子系统的接口契约. 文件路径: `<save_dir>/odp_audit.json`(跟 ultralytics 的 args.yaml / results.csv 同目录).

结构:

```json
{
  "config": {
    "task": "detect",
    "model": "yolo11n.pt",
    "data": "rsod.yaml",
    "epochs": 100,
    "batch": 16,
    ...
  },
  "merger": {
    "fields": {
      "epochs": {
        "value": 100,
        "source": "CLI",
        "chain": ["CLI:100", "YAML:50", "DEFAULT:100"]
      },
      ...
    }
  },
  "metrics": {
    "task": "detect",
    "save_dir": "/abs/runs/detect_train/train3",
    "timestamp": "2026-05-24T11:42:36",
    "speed_ms": {...},
    "overall": {"fitness": 0.5805, "metrics/mAP50(B)": 0.62, ...},
    "class_map_50_95": {"person": 0.41, "car": 0.38, ...}
  },
  "result_summary": {
    "best_archive": "/abs/checkpoints/train3-20260524-114236-yolo11n-best.pt",
    "last_archive": "/abs/checkpoints/train3-20260524-114236-yolo11n-last.pt",
    "train_time_sec": 1832.5,
    "log_path": "/abs/logging/train/train3_20260524-093015-567_yolo11n.log"
  }
}
```

3 个调用方:

| 调用方 | 用 audit JSON 干嘛 |
|---|---|
| 用户排查 | `cat odp_audit.json \| jq .result_summary.log_path` → 找到对应日志 |
| 未来 experiment_db | 一行 `db.import(audit_path)` 把这次训练写进 DB |
| D7 ValService | 想验证 train3 的 best → 从 audit JSON 拿 `best_archive` 路径直接用 |

⚠️ **设计点 (写 audit 失败不算训练失败)**: 阶段 8 包了 `try OSError` , 写 audit 失败只 warning, 不让 success 翻成 False. 训练成功才是核心, audit 是附属信息.

## 6.4 git commit

```bash
git add apps/platform/src/odp_platform/training/archive.py
git commit -m "feat(training): add archive_checkpoints

  - 训练完复制 best/last.pt 到 CHECKPOINTS_DIR
  - 命名: <train_dir_name>-<ts>-<model_stem>-<best|last>.pt
  - 原文件保留(供 ultralytics resume), 归档=复制
  - 永不抛(best-effort), 失败不影响 TrainResult.success
"

git add apps/platform/src/odp_platform/training/service.py
git commit -m "feat(training): add TrainService + TrainResult + train_yolo

8 阶段编排: 配置加载 → 上下文日志 → D4 校验 → 加载模型 →
执行训练 → 结果指标 → 整理输出 → 审计快照.

子系统边界硬指标:
  grep 'YAMLLoader\\|CLILoader\\|ConfigMerger' service.py → 0

特性:
  - 永不抛, 错误装进 TrainResult.error
  - pre_validate/archive/rename_log 三个 keyword-only 开关
  - 写 odp_audit.json 给未来 experiment_db 留落点
"
```

下一阶段我们写 CLI 入口 `odp-train`.


---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 7: CLI 入口 (odp-train)

CLI 的职责: **argparse 翻译 + D2 get_logger 触发 + 调 service + 退出码翻译**——4 件事, **不做合并、不做校验、不动 ultralytics**.

## 7.1 CLI 不做什么 (重要!)

| 看似 CLI 该做但其实不该做的事 | 应该谁做 |
|---|---|
| 合并 YAML / CLI / DEFAULT 三源 | D5 (在 service 阶段 1 调一行) |
| 校验数据集 | D4 (在 service 阶段 3 调一行) |
| 调 ultralytics 训练 | service (阶段 5) |
| 解析模型路径 / 数据集路径 | common (service 阶段 2 调) |
| 处理 ultralytics 抛的异常 | service 顶层异常拦截 |

CLI 把这些事**全部转交给 service**, 自己只负责 argparse → dict、装 logging、读 result.success 翻成退出码.

⚠️ **设计点 (CLI 是"翻译层"不是"业务层")**: 这个边界一旦混就麻烦. 如果你在 CLI 里写"如果 args.epochs 太小, 给个 warning"——这是业务校验, 应该走 D5 的 `@field_validator`. CLI 写了, D5 又写一遍, 维护两套.

## 7.2 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : train_model.py
# @Project   : ODPlatform
# @Function  : odp-train CLI 入口 — argparse + 装日志 handler + 调 TrainService
"""odp-train CLI 入口.

★ 职责边界:
  - 解析 argparse (把 CLI 字段变成 dict, 交给 D5 build_train_config 合并)
  - 装文件日志 handler (业务模块只发声纪律的兑现位 — 唯一装 handler 的地方)
  - 调 TrainService.train(...) 跑训练
  - 把退出码翻译给操作系统 (0/1/130)

CLI 不做的事:
  - 不合并配置(那是 D5 的事)
  - 不校验数据集(那是 D4 的事, 由 service 自动调)
  - 不动 ultralytics(那是 service 的事)
"""
from __future__ import annotations

import argparse
import logging
import sys

from odp_platform.common.logging_utils import get_logger
from odp_platform.common.paths import LOGGING_DIR

from odp_platform.training import TrainService


# ============================================================================
# argparse
# ============================================================================

def build_parser() -> argparse.ArgumentParser:
    """构造 argparse parser. 拆出来让测试可以独立验证 CLI 表面."""
    parser = argparse.ArgumentParser(
        prog="odp-train",
        description="YOLO 训练 — 调 D5 配置 + D4 校验 + ultralytics 训练",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  odp-train                                       # 默认 train.yaml
  odp-train --yaml my_train.yaml --epochs 200
  odp-train --batch 32 --device 0
  odp-train --device 0,1                          # 多 GPU
  odp-train --no-pre-validate                     # 跳过 D4 校验
  odp-train --academic-plots                      # 学术风格出图
        """,
    )

    # ---- 配置文件 ----
    parser.add_argument(
        "--yaml", type=str, default=None,
        help="YAML 配置文件路径(默认走 RUNTIME_CONFIGS_DIR/train.yaml)",
    )

    # ---- 训练超参数(覆盖 yaml) ----
    parser.add_argument("--model",     type=str,   help="模型路径 / 文件名(默认走 yaml)")
    parser.add_argument("--data",      type=str,   help="数据集 yaml(默认走 yaml)")
    parser.add_argument("--epochs",    type=int,   help="训练轮数")
    parser.add_argument("--batch",     type=int,   help="batch size(支持 -1/0-1.0)")
    parser.add_argument("--imgsz",     type=int,   help="输入图像尺寸")
    parser.add_argument("--device",    type=str,   help="训练设备(0/cpu/0,1)")
    parser.add_argument("--lr0",       type=float, help="初始学习率")
    parser.add_argument("--optimizer", type=str,   help="优化器")
    parser.add_argument("--workers",   type=int,   help="DataLoader workers")
    parser.add_argument("--seed",      type=int,   help="随机种子")
    parser.add_argument("--project",   type=str,   help="输出根目录")
    parser.add_argument("--name",      type=str,   help="运行名(yolo 用)")
    parser.add_argument("--experiment-name", dest="experiment_name", type=str,
                        help="实验名(ODP 用, 进 runs/<task>_train/<experiment_name>/)")

    # ---- D6 开关(service 层的 keyword-only 参数) ----
    parser.add_argument(
        "--no-pre-validate", dest="pre_validate", action="store_false", default=True,
        help="跳过训练前 D4 数据集校验(不推荐 — fail-fast 原则)",
    )
    parser.add_argument(
        "--no-archive", dest="archive", action="store_false", default=True,
        help="不复制 best/last.pt 到 CHECKPOINTS_DIR",
    )
    parser.add_argument(
        "--no-rename-log", dest="rename_log", action="store_false", default=True,
        help="不把日志文件名改成 <save_dir>_<ts>_<model>.log 形式",
    )

    # ---- 可选辅助 ----
    parser.add_argument(
        "--academic-plots", action="store_true",
        help="应用 matplotlib 学术发表风格(影响本进程全局 rcParams)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )

    return parser


# ============================================================================
# 日志 handler 装载 — 业务模块只发声, handler 唯一装的地方就在这
# ============================================================================

def _setup_logging(log_level: str) -> None:
    """调 D2 的 get_logger 给 'odp_platform' 根 logger 装上 console + file handler."""
    get_logger(
        base_path=LOGGING_DIR,
        log_type="train",
        log_level=getattr(logging, log_level),
        temp_log=False,
    )


# ============================================================================
# main 入口
# ============================================================================

def main() -> int:
    """odp-train 主入口. 返回退出码 0/1/130."""
    parser = build_parser()
    args = parser.parse_args()

    # 1. 学术 plots (可选, 影响全局 — 越早 apply 越好)
    if args.academic_plots:
        from odp_platform.common.plot_style import apply_academic_style
        apply_academic_style()

    # 2. 装日志 handler (走 D2 get_logger, 唯一一次)
    _setup_logging(args.log_level)
    log = logging.getLogger("odp_platform.cli.train_model")

    # 3. argparse.Namespace → dict, 过滤 None(让 D5 走默认值) + 拆出非配置字段
    NON_CONFIG_KEYS = {
        "yaml", "pre_validate", "archive", "rename_log",
        "academic_plots", "log_level",
    }
    cli_args = {
        k: v for k, v in vars(args).items()
        if v is not None and k not in NON_CONFIG_KEYS
    }

    # 4. 调 service
    log.info(f"启动 odp-train, CLI 字段: {list(cli_args.keys())}")
    try:
        service = TrainService()
        result = service.train(
            yaml_path=args.yaml,
            cli_args=cli_args,
            pre_validate=args.pre_validate,
            archive=args.archive,
            rename_log=args.rename_log,
        )
    except KeyboardInterrupt:
        log.warning("用户中断 (Ctrl+C)")
        return 130
    except Exception as e:        # service 本应 not raise, 兜底
        log.error(f"未预期异常: {e}", exc_info=True)
        return 1

    # 5. 退出码
    if result.success:
        log.info(f"✓ 训练成功. 用时 {result.train_time:.2f}s, 输出 {result.output_dir}")
        return 0
    else:
        log.error(f"✗ 训练失败: {result.error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

⚠️ **设计点 (4 个细节)**:

1. **`NON_CONFIG_KEYS` 过滤**: argparse 加进来的非配置字段(yaml / pre_validate / archive / rename_log / academic_plots / log_level)不应该混进 `cli_args` 字典——D5 build_train_config 拿到这些会以为是配置字段, 报错"field not allowed". 显式列举更安全.

2. **`v is not None` 过滤**: argparse 没传的字段返回 None, **必须过滤掉**——否则 D5 会用 None 覆盖 YAML / DEFAULT 的合理值. `cli_args` 字典里只放"用户在 CLI 明确传了的字段".

3. **`KeyboardInterrupt → 130`**: Unix 约定 Ctrl+C 退出码 130 (128 + SIGINT=2). 让 shell 脚本 / Makefile 能区分"用户主动取消"和"训练失败".

4. **顶层 `except Exception` 兜底**: service 本应 not raise(规矩 B), 但这里再兜一道——理论上走不到, 万一某个 corner case 漏了不影响 CLI 退出码.

## 7.3 pyproject.toml entry-point 注册

```toml
# pyproject.toml [project.scripts]
[project.scripts]
odp-init      = "odp_platform.cli.init_project:main"
odp-reset     = "odp_platform.cli.reset_project:main"
odp-transform = "odp_platform.cli.transform_data:main"
odp-validate  = "odp_platform.cli.validate_data:main"
odp-gen-config = "odp_platform.runtime_config.generator:main"
odp-train     = "odp_platform.cli.train_model:main"          # ★ D6 新增
```

跟 D2 / D3 / D4 / D5 同款风格——entry-point 直接绑到 `<module>:main`, 不立薄包装.

⚠️ **设计点 (entry-point 入口要装包)**: `pyproject.toml` 改完要 `pip install -e .` 重装一次, entry-point 才能找到. 不重装的话 `odp-train` 命令不存在, 但 `python -m odp_platform.cli.train_model` 仍然能用——这是 entry-point 的临时备胎.

## 7.4 git commit

```bash
git add apps/platform/src/odp_platform/cli/train_model.py pyproject.toml
git commit -m "feat(cli): add odp-train entry-point

  - argparse (yaml + 训练超参数 + 3 个 D6 开关)
  - _setup_logging: 一行调 D2 get_logger 装在 'odp_platform' named root
  - 调 TrainService.train(...) 跑训练
  - 退出码翻译: 0(成功) / 1(失败 / 未预期异常) / 130(用户 Ctrl+C)

  pyproject.toml: 注册 odp-train entry-point
"
```

下一阶段我们写 `training/__init__.py` — 对外面板.


---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 8: `training/__init__.py` — 对外面板

D6 的 `training/` 子系统**对外只暴露 4 个符号**:

| 符号 | 类型 | 用途 |
|---|---|---|
| `TrainService` | class | 训练流程编排器 |
| `TrainResult`  | dataclass | 训练结果快照(永不抛, 装载成败) |
| `TrainMetrics` | dataclass | 训练/验证指标快照(转再导出, 实际在 common.result) |
| `train_yolo`   | function | 一行启动训练的便捷函数 |

## 8.1 选什么不选什么 — 一张表

不暴露的(故意不放进 `__all__`):

| 符号 | 在哪定义 | 为什么不暴露 |
|---|---|---|
| `resolve_model_path` | `common/` | D7/D8 应该从 common import, 不绕道 training |
| `resolve_dataset_path` | `common/` | 同上 |
| `rename_log_to_save_dir` | `common/` | 同上 |
| `log_effective_config` | `common/` | 同上 |
| `log_override_chains` | `common/` | 同上 |
| `log_train_metrics` | `common/` | 同上 |
| `apply_academic_style` | `common/` | 同上 |
| `archive_checkpoints` | `training/` | 训练专属副作用, 没人需要直接调(service 内部调) |

⚠️ **设计点 (TrainMetrics 转再导出的判断)**: `TrainMetrics` 实际定义在 `common/result.py`(因为 D7 ValMetrics 同款复用), 但 `from odp_platform.training import TrainMetrics` 这个 import 路径足够**直观**——用户拿到 `TrainResult.metrics` 想"哦它对应的完整类是啥?", 第一反应是 `from odp_platform.training import TrainMetrics`. 保留这个肌肉记忆的便利, 在 `__init__.py` 转再导出.

```python
# 这是合法的转再导出
from odp_platform.common.result import TrainMetrics
```

不要把 `TrainMetrics` **物理搬回 training/**——那就是真复制了, 跟 common/ 那一份分叉. **物理 SSoT 在 common/, 逻辑导入路径有两条**.

## 8.2 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : __init__.py
# @Project   : ODPlatform
# @Function  : training 子系统对外公共 API — 只暴露训练专属符号
"""ODPlatform ``training/`` 子系统对外面板.

跟 D5 / D4 / D3 同款风格 — 外部调用只 import 顶层包, 不碰内部模块路径.

★ training/ 只放训练专属(TrainService 编排 + archive 归档),
跨任务通用工具(model_path / dataset_path / log_rename / config_log / result /
plot_style)全部放 ``odp_platform.common.*``. 这一层只暴露真正训练相关的符号:

* ``TrainService``  — 训练流程编排
* ``TrainResult``   — 训练结果 dataclass
* ``TrainMetrics``  — 指标 dataclass (转再导出, 让用户 `from odp_platform.training` 也能拿)
* ``train_yolo``    — 便捷函数

下游子系统(D7 ValService / D8 InferService)需要 model_path / dataset_path 等
工具时, 应该直接 ``from odp_platform.common.xxx import ...`` — 不要绕道
training. 训练子系统不是这些工具的发行渠道.
"""
from __future__ import annotations

# ---- 核心(2): 训练流程 ----
from .service import TrainResult, TrainService, train_yolo

# ---- 指标 dataclass: 转再导出 ----
# TrainMetrics 实际定义在 common.result(因为 D7 ValMetrics 同款复用), 但
# `from odp_platform.training import TrainMetrics` 这个 import 路径足够直观,
# 保留下来让用户的肌肉记忆不破.
from odp_platform.common.result import TrainMetrics

__all__ = [
    "TrainService",
    "TrainResult",
    "TrainMetrics",
    "train_yolo",
]
```

## 8.3 用法示例 — 公共 API 的 3 种典型调用

### 调用 1 — CLI (`odp-train`)

```bash
odp-train --epochs 100 --batch 32 --device 0
```

CLI 内部 `from odp_platform.training import TrainService`, 调 service.

### 调用 2 — Python API (便捷函数)

```python
from odp_platform.training import train_yolo

result = train_yolo(
    yaml_path="train.yaml",
    cli_args={"epochs": 100, "model": "yolo11n.pt"},
)

if result.success:
    print(f"✓ 训练完成. mAP50: {result.metrics.get('metrics/mAP50(B)', 'n/a')}")
    print(f"  Best 权重: {result.best_weight}")
    print(f"  日志:     {result.log_path}")
    print(f"  Audit:    {result.audit_path}")
else:
    print(f"✗ {result.error}")
```

### 调用 3 — Service 实例化(长进程 / 服务化)

```python
from odp_platform.training import TrainService

service = TrainService()

# 连续跑多组配置
for cfg in [
    {"model": "yolo11n.pt", "epochs": 50},
    {"model": "yolo11s.pt", "epochs": 50},
    {"model": "yolo11m.pt", "epochs": 50},
]:
    result = service.train(cli_args=cfg)
    log_to_experiment_db(result)
```

## 8.4 git commit

```bash
git add apps/platform/src/odp_platform/training/__init__.py
git commit -m "feat(training): add public API in __init__.py (4 symbols only)

公开符号:
  - TrainService / TrainResult: 训练流程
  - TrainMetrics: 指标 dataclass (转再导出自 common.result)
  - train_yolo: 便捷函数

不公开:
  - archive_checkpoints: 训练专属副作用, 没人直接调
  - 6 个 common 工具: D7/D8 应该走 common import 路径, 不绕道 training
"
```

下一阶段写单元测试.


---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 9: 单元测试 — 让 D6 进 CI

D5 阶段 8 已经讲了\"为什么子系统层就要写单测, 不留给下一节\"的 3 个理由(端到端测试不能定位错误 / 重构时的安全网 / 测试本身是文档). 那 3 个理由在 D6 全部成立, 不重复——只补 D6 自己的两个理由:

## 9.1 D6 自己额外的两个测试理由

**理由 4**: **D6 的核心价值在【边界纪律】上, 边界要靠测试守住**.

"common/ vs training/ 拆分""service 永不抛""log_rename 操作 named root"——这些纪律没有测试守, 下一次有人改代码可能就破了. 比如 service.train() 不小心忘了套 try, 抛了异常出去——没测试就不知道, 直到 CLI 跑出 traceback 才发现.

**理由 5**: **D7/D8 复用 6 个 common 工具, 这些工具的测试是它们的接口契约**.

如果 `resolve_model_path` 的 search_dirs 参数被 D7 误用导致行为变了, 应该是 D6 的测试先红, 而不是等 D7 的 service 跑崩了再 debug. 测试本身是\"D6 跟 D7 之间的合约\".

## 9.2 测试目录结构

跟代码结构一一对应(规矩 D, D5 立的):

```
apps/platform/tests/
├── common/                      ← 6 个 common 工具的测试
│   ├── conftest.py              (mock_det_results / mock_segment_results)
│   ├── test_model_path.py       (11 个用例, 含 search_dirs 升级)
│   ├── test_dataset_path.py     (5 个用例)
│   ├── test_log_rename.py       (7 个用例)
│   ├── test_config_log.py       (6 个用例)
│   └── test_result.py           (19 个用例)
├── training/                    ← 2 个 training 专属测试
│   ├── conftest.py              (fake_train_dir fixture)
│   ├── test_archive.py
│   └── test_service.py          (mock D5/D4/ultralytics)
└── (其他子系统的测试...)
```

⚠️ **设计点 (conftest 为什么拆开)**: `tests/common/conftest.py` 放\"common 测试需要的 ultralytics results mock\", `tests/training/conftest.py` 放\"training 测试需要的 fake save_dir\". **不要**把所有 fixture 堆在 `tests/conftest.py` 顶层——那样 D7 测试也会自动加载 ultralytics mock fixture(尽管它用不到), 测试启动变慢且让 fixture 来源不清晰.

每个 fixture 只在\"它该被看到的地方\"可见. 这跟代码模块边界是同样的判断.

## 9.3 conftest.py — fixture 拆分原则

### `tests/common/conftest.py` — ultralytics results mock

```python
"""tests/common/ 共用 fixture.

mock_det_results / mock_segment_results 服务 test_result.py — 仿真 ultralytics
DetMetrics / SegmentMetrics 对象的 attribute 形状, 不依赖真实 ultralytics 安装.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest


@pytest.fixture
def mock_det_results():
    """仿真 ultralytics DetMetrics 对象."""
    mock = MagicMock()
    mock.task = "detect"
    mock.save_dir = Path("/tmp/runs/detect_train/train3")
    mock.fitness = 0.5805
    mock.speed = {
        "preprocess": 1.234,
        "inference": 12.345,
        "loss": 0.123,
        "postprocess": 0.567,
    }
    mock.results_dict = {
        "metrics/precision(B)": 0.7234,
        "metrics/recall(B)": 0.6543,
        "metrics/mAP50(B)": 0.6912,
        "metrics/mAP50-95(B)": 0.4321,
        "fitness": 0.5805,
    }
    mock.maps = np.array([0.4521, 0.3812, 0.2103])
    mock.names = {0: "person", 1: "car", 2: "bicycle"}
    return mock


@pytest.fixture
def mock_segment_results():
    """仿真 ultralytics SegmentMetrics — 比 det 多 4 个 mask 指标."""
    mock = MagicMock()
    mock.task = "segment"
    mock.save_dir = Path("/tmp/runs/segment_train/train1")
    mock.fitness = 0.6123
    mock.speed = {
        "preprocess": 1.0, "inference": 15.0, "loss": 0.2, "postprocess": 0.8,
    }
    mock.results_dict = {
        "metrics/precision(B)": 0.72, "metrics/recall(B)": 0.65,
        "metrics/mAP50(B)": 0.70,     "metrics/mAP50-95(B)": 0.45,
        "metrics/precision(M)": 0.68, "metrics/recall(M)": 0.62,
        "metrics/mAP50(M)": 0.66,     "metrics/mAP50-95(M)": 0.42,
        "fitness": 0.6123,
    }
    mock.maps = np.array([0.55, 0.48])
    mock.names = {0: "person", 1: "vehicle"}
    return mock
```

### `tests/training/conftest.py` — fake save_dir

```python
"""tests/training/ 共用 fixture.

fake_train_dir 仿真 ultralytics save_dir(含 weights/best.pt / last.pt),
给 archive 测试用.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fake_train_dir(tmp_path: Path) -> Path:
    """构造一个仿真的 ultralytics save_dir."""
    train_dir = tmp_path / "runs" / "detect_train" / "train3"
    (train_dir / "weights").mkdir(parents=True)
    (train_dir / "weights" / "best.pt").write_bytes(b"fake-best-weights")
    (train_dir / "weights" / "last.pt").write_bytes(b"fake-last-weights")
    return train_dir
```

## 9.4 tests/common/ — 5 个测试模块的关键用例

每个 common 工具我挑 2-3 个最能说明问题的测试用例展开, 全套用例请看代码包.

### 9.4.1 `test_model_path.py` (11 个用例 — 含 search_dirs 升级)

```python
import pytest
from pathlib import Path
from odp_platform.common.model_path import resolve_model_path

# ──── 默认行为(不传 search_dirs) ────────────────────────────────

def test_absolute_path_returned_as_is(tmp_path):
    """绝对路径直接用, 不查 search_dirs."""
    abs_path = tmp_path / "anywhere" / "yolo11n.pt"
    result = resolve_model_path(abs_path)
    assert result == abs_path

def test_filename_falls_back_to_pretrained(tmp_path, monkeypatch):
    """仅文件名默认查 PRETRAINED_MODELS_DIR."""
    fake_pretrained = tmp_path / "pretrained"
    fake_pretrained.mkdir()
    (fake_pretrained / "yolo11n.pt").write_bytes(b"")
    monkeypatch.setattr(
        "odp_platform.common.model_path.PRETRAINED_MODELS_DIR", fake_pretrained
    )
    result = resolve_model_path("yolo11n.pt")
    assert result == fake_pretrained / "yolo11n.pt"

def test_not_found_returns_original(caplog):
    """找不到时返回原值, 不 raise(让 ultralytics 自己处理)."""
    result = resolve_model_path("definitely-not-exists.pt")
    assert str(result) == "definitely-not-exists.pt"
    assert "未在任何搜索目录命中" in caplog.text

# ──── search_dirs 升级 (D7/D8 接口) ──────────────────────────────

def test_search_dirs_first_dir_hit(tmp_path):
    """search_dirs 第 1 个目录命中, 不查后面."""
    dir1 = tmp_path / "a" ; dir1.mkdir() ; (dir1 / "x.pt").write_bytes(b"")
    dir2 = tmp_path / "b" ; dir2.mkdir() ; (dir2 / "x.pt").write_bytes(b"")
    result = resolve_model_path("x.pt", search_dirs=[dir1, dir2])
    assert result == dir1 / "x.pt"           # 第 1 个就命中

def test_search_dirs_fallback_to_second(tmp_path):
    """search_dirs 第 1 个没有, fallback 到第 2 个."""
    dir1 = tmp_path / "ckpt" ; dir1.mkdir()
    dir2 = tmp_path / "pretrained" ; dir2.mkdir()
    (dir2 / "yolo11n.pt").write_bytes(b"")   # 只在第 2 个目录
    result = resolve_model_path(
        "yolo11n.pt", search_dirs=[dir1, dir2]
    )
    assert result == dir2 / "yolo11n.pt"

def test_search_dirs_none_equals_default(tmp_path, monkeypatch):
    """search_dirs=None 等价于不传, 走默认 [PRETRAINED_MODELS_DIR]."""
    fake_pre = tmp_path / "pre" ; fake_pre.mkdir()
    (fake_pre / "y.pt").write_bytes(b"")
    monkeypatch.setattr(
        "odp_platform.common.model_path.PRETRAINED_MODELS_DIR", fake_pre
    )
    explicit_none = resolve_model_path("y.pt", search_dirs=None)
    omitted       = resolve_model_path("y.pt")
    assert explicit_none == omitted == fake_pre / "y.pt"
```

⚠️ **设计点 (`test_search_dirs_none_equals_default`)**: 这条测试守的是\"向后兼容承诺\"——D7/D8 后人误改默认参数把行为搞变了, 这条测试立刻红.

### 9.4.2 `test_dataset_path.py` (5 个用例)

```python
def test_absolute_path_returned_as_is(tmp_path):
    yaml = tmp_path / "rsod.yaml" ; yaml.write_text("path: ...")
    assert resolve_dataset_path(yaml) == yaml

def test_filename_falls_back_to_dataset_configs_dir(tmp_path, monkeypatch):
    fake_dir = tmp_path / "datasets" ; fake_dir.mkdir()
    (fake_dir / "rsod.yaml").write_text("path: ...")
    monkeypatch.setattr(
        "odp_platform.common.dataset_path.DATASET_CONFIGS_DIR", fake_dir
    )
    assert resolve_dataset_path("rsod.yaml") == fake_dir / "rsod.yaml"

def test_not_found_returns_original_with_warning(caplog):
    result = resolve_dataset_path("nonexistent.yaml")
    assert str(result) == "nonexistent.yaml"
    assert "未在 DATASET_CONFIGS_DIR 找到" in caplog.text
```

### 9.4.3 `test_log_rename.py` (7 个用例)

测试 log_rename 重点考虑 4 类场景: **named root 无 handler / 时间戳能/不能提取 / rename 失败回滚 / 已对齐不重复操作**.

```python
import logging
from pathlib import Path
import pytest

from odp_platform.common.log_rename import rename_log_to_save_dir, ROOT_LOGGER_NAME


def _attach_file_handler(root_logger, file_path):
    """辅助: 给 named root 装一个 FileHandler 模拟 D2 get_logger 完成后的状态."""
    handler = logging.FileHandler(file_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(handler)
    return handler

@pytest.fixture
def named_root_with_log(tmp_path):
    """每次测试一个干净的 named root + 一个 file handler 指向 tmp 文件."""
    log_dir = tmp_path / "logs" ; log_dir.mkdir()
    log_file = log_dir / "train_20260524-103045.log"
    log_file.touch()
    
    root = logging.getLogger(ROOT_LOGGER_NAME)
    for h in list(root.handlers):                   # 清场
        root.removeHandler(h) ; h.close()
    _attach_file_handler(root, log_file)
    yield root, log_file
    for h in list(root.handlers):                   # 清场
        root.removeHandler(h) ; h.close()

def test_no_filehandler_returns_none_with_warning(caplog):
    """named root 没 handler — 跳过, 返回 None, warning."""
    root = logging.getLogger(ROOT_LOGGER_NAME)
    for h in list(root.handlers):
        root.removeHandler(h) ; h.close()
    result = rename_log_to_save_dir(Path("/tmp/train3"), "yolo11n")
    assert result is None
    assert "没有 FileHandler" in caplog.text

def test_rename_reuses_timestamp(named_root_with_log, tmp_path):
    """新文件名复用原时间戳, 不用 datetime.now()."""
    root, log_file = named_root_with_log
    save_dir = tmp_path / "runs" / "detect_train" / "train3" ; save_dir.mkdir(parents=True)
    new_path = rename_log_to_save_dir(save_dir, "yolo11n")
    assert new_path is not None
    assert new_path.name == "train3_20260524-103045_yolo11n.log"   # 原 timestamp

def test_no_timestamp_uses_placeholder(tmp_path):
    """原文件名没时间戳, 用 'unknown-time' 占位."""
    root = logging.getLogger(ROOT_LOGGER_NAME)
    for h in list(root.handlers):
        root.removeHandler(h) ; h.close()
    log_file = tmp_path / "weird-name.log" ; log_file.touch()
    _attach_file_handler(root, log_file)
    
    save_dir = tmp_path / "runs" / "train1" ; save_dir.mkdir(parents=True)
    new_path = rename_log_to_save_dir(save_dir, "yolo11n")
    assert "unknown-time" in new_path.name

def test_already_aligned_no_op(named_root_with_log, tmp_path):
    """目标名跟原名一致, 跳过."""
    # 略 - 构造 save_dir 让目标文件名等于原文件名, 期望返回原 path 不操作
```

### 9.4.4 `test_config_log.py` (6 个用例)

```python
def test_log_effective_config_reads_each_field(caplog):
    """每个字段输出一行 + 来源."""
    fake_config = MagicMock()
    fake_config.__class__.model_fields = {"epochs": ..., "batch": ..., "lr0": ...}
    fake_config.epochs = 100 ; fake_config.batch = 16 ; fake_config.lr0 = 0.01
    
    fake_merger = MagicMock()
    fake_merger.get_metadata = MagicMock(side_effect=lambda n: MagicMock(source_label="CLI"))
    
    log_effective_config(fake_config, fake_merger)
    assert "epochs" in caplog.text and "100" in caplog.text and "CLI" in caplog.text

def test_log_override_chains_reverse_order(caplog):
    """chain 显示按 DEFAULT → CLI 方向(reverse D5 chain)."""
    # 略 - 构造一个 3 链 metadata 验证显示是 oldest-first

def test_safe_get_metadata_returns_none_for_mock_without_method(caplog):
    """merger 没 get_metadata(MagicMock 兜底) — 不崩."""
    fake_config = MagicMock()
    fake_config.__class__.model_fields = {"epochs": ...}
    fake_config.epochs = 100
    
    bad_merger = object()      # 完全没 get_metadata
    log_effective_config(fake_config, bad_merger)   # ✗ raise 才算 fail
    assert "epochs" in caplog.text                   # 字段仍然打了, 只是来源 'unknown'
```

### 9.4.5 `test_result.py` (19 个用例, 列 5 个最关键)

```python
def test_train_metrics_from_det_results(mock_det_results):
    metrics = TrainMetrics.from_yolo_results(mock_det_results)
    assert metrics.task == "detect"
    assert metrics.overall["fitness"] == pytest.approx(0.5805)
    assert metrics.overall["metrics/mAP50(B)"] == pytest.approx(0.6912)
    assert "person" in metrics.class_map_50_95

def test_train_metrics_speed_total_excludes_nan(mock_det_results):
    """speed_ms['total'] = sum(非 nan), 4 项有效 = 一切 OK."""
    mock_det_results.speed["loss"] = None    # 让 loss 变 nan
    metrics = TrainMetrics.from_yolo_results(mock_det_results)
    # total 应当只包括 preprocess + inference + postprocess
    expected = 1.234 + 12.345 + 0.567
    assert metrics.speed_ms["total"] == pytest.approx(expected, abs=1e-3)

def test_to_dict_nan_converts_to_none():
    """to_dict 时 NaN → None, 让 JSON 能序列化."""
    metrics = TrainMetrics(
        task="detect", save_dir=Path("/tmp"),
        timestamp="2026-05-24T10:00:00",
        speed_ms={"preprocess": math.nan},
        overall={"fitness": 0.5},
    )
    d = metrics.to_dict()
    assert d["speed_ms"]["preprocess"] is None    # NaN → None
    assert d["overall"]["fitness"] == 0.5

def test_log_train_metrics_unknown_task_falls_back(caplog):
    """task='unknown' 时打 results_dict 全量, 不崩."""
    metrics = TrainMetrics(
        task="unknown", save_dir=Path("/tmp"),
        timestamp="2026-05-24T10:00:00",
        speed_ms={}, overall={"fitness": 0.5, "metric_x": 0.7},
    )
    log_train_metrics(metrics)
    assert "task='unknown' 不在" in caplog.text   # 兜底分支被走到
    assert "metric_x" in caplog.text              # 全量打印

def test_segment_task_logs_8_metrics(mock_segment_results, caplog):
    """segment 任务 8 个指标全部 log."""
    metrics = TrainMetrics.from_yolo_results(mock_segment_results)
    log_train_metrics(metrics)
    for k in ("mAP50(B)", "mAP50(M)", "Precision(M)", "Recall(M)"):
        assert k in caplog.text
```

⚠️ **设计点 (`test_log_train_metrics_unknown_task_falls_back`)**: 这条测试直接验证了\"健壮性 fallback 分支被走到\"——ultralytics 改了 .task 属性 / 第三方 results 对象, D6 仍然能跑, 只是输出格式略糙. 这是合法的 fallback 测试, 不是覆盖 bug 行为.

## 9.5 tests/training/ — 2 个测试

### 9.5.1 `test_archive.py`

```python
def test_archive_copies_both(fake_train_dir, tmp_path):
    ckpt_dir = tmp_path / "ckpt"
    result = archive_checkpoints(
        fake_train_dir, "yolo11n.pt", checkpoint_dir=ckpt_dir
    )
    assert "best" in result and "last" in result
    assert result["best"].exists()
    assert "train3" in result["best"].name           # train_dir 名进文件名
    assert "yolo11n" in result["best"].name          # model_stem 进文件名
    assert "best" in result["best"].name

def test_archive_missing_train_dir_returns_empty(tmp_path):
    """train_dir 不存在 — 返回 {}, warning, 不抛."""
    result = archive_checkpoints(
        tmp_path / "nonexistent", "yolo11n.pt", checkpoint_dir=tmp_path / "ckpt"
    )
    assert result == {}

def test_archive_no_best_no_last(tmp_path):
    """train_dir 存在但 weights/ 是空的 — 跳过, 不抛."""
    empty_train = tmp_path / "train1" / "weights" ; empty_train.mkdir(parents=True)
    result = archive_checkpoints(
        tmp_path / "train1", "yolo11n.pt", checkpoint_dir=tmp_path / "ckpt"
    )
    assert result == {}
```

### 9.5.2 `test_service.py` — mock D5/D4/ultralytics

```python
"""TrainService 单元测试.

★ 关键: service 通过 import 别名调用 D5/D4/ultralytics, 要 patch
`odp_platform.training.service.xxx` 而不是 `odp_platform.runtime_config.xxx`
(patch 的是 service 模块**内部已经持有**的引用).
"""
from unittest.mock import MagicMock, patch
from pathlib import Path

from odp_platform.training import TrainService, TrainResult


def _make_config_mock(task="detect"):
    cfg = MagicMock()
    cfg.task = task
    cfg.model = "yolo11n.pt"
    cfg.data = "rsod.yaml"
    cfg.to_ultralytics_kwargs.return_value = {
        "data": "/abs/rsod.yaml", "model": "yolo11n.pt",
        "epochs": 100, "batch": 16, "imgsz": 640,
    }
    cfg.to_audit_snapshot.return_value = {"task": task, "model": "yolo11n.pt"}
    cfg.__class__.model_fields = {"epochs": ..., "batch": ..., "imgsz": ...}
    return cfg


def test_train_success_full_flow(tmp_path):
    """成功路径全流程 — 验证 8 阶段都被调到."""
    save_dir = tmp_path / "runs" / "detect_train" / "train1" ; save_dir.mkdir(parents=True)
    (save_dir / "weights").mkdir() ; (save_dir / "weights" / "best.pt").touch()
    (save_dir / "weights" / "last.pt").touch()

    cfg = _make_config_mock()
    merger = MagicMock()
    merger.to_audit_log.return_value = {"fields": {}}

    fake_results = MagicMock()
    fake_results.save_dir = save_dir
    fake_results.task = "detect"
    fake_results.fitness = 0.5
    fake_results.speed = {"preprocess": 1, "inference": 10, "loss": 0, "postprocess": 0}
    fake_results.results_dict = {"fitness": 0.5}
    fake_results.maps = MagicMock()
    fake_results.maps.size = 0
    fake_results.names = {}

    with patch("odp_platform.training.service.build_train_config", return_value=(cfg, merger)), \
         patch("odp_platform.training.service.validate_dataset", return_value=MagicMock(exit_code=0, results=[])), \
         patch("odp_platform.training.service.render_to_logger"), \
         patch("odp_platform.training.service.YOLO") as yolo_cls, \
         patch("odp_platform.training.service.log_device_info"), \
         patch("odp_platform.training.service.archive_checkpoints", return_value={}), \
         patch("odp_platform.training.service.rename_log_to_save_dir"):
        yolo_cls.return_value.train.return_value = fake_results
        result = TrainService().train(cli_args={"epochs": 1})

    assert isinstance(result, TrainResult)
    assert result.success is True
    assert result.output_dir == save_dir

def test_train_validation_fail_returns_failure(tmp_path):
    """D4 校验报 ERROR — service 不抛, 装进 result.error."""
    cfg = _make_config_mock()
    merger = MagicMock()
    bad_report = MagicMock()
    bad_report.exit_code = 2     # ERROR 级
    bad_report.results = [MagicMock(severity="ERROR")]

    with patch("odp_platform.training.service.build_train_config", return_value=(cfg, merger)), \
         patch("odp_platform.training.service.validate_dataset", return_value=bad_report), \
         patch("odp_platform.training.service.render_to_logger"), \
         patch("odp_platform.training.service.log_device_info"):
        result = TrainService().train(cli_args={})

    assert result.success is False
    assert "数据集校验失败" in result.error

def test_train_yolo_runtime_error_caught(tmp_path):
    """ultralytics 训练时抛 RuntimeError — service 不传染, 装进 result.error."""
    cfg = _make_config_mock()
    merger = MagicMock()
    
    with patch("odp_platform.training.service.build_train_config", return_value=(cfg, merger)), \
         patch("odp_platform.training.service.validate_dataset", return_value=MagicMock(exit_code=0, results=[])), \
         patch("odp_platform.training.service.render_to_logger"), \
         patch("odp_platform.training.service.YOLO") as yolo_cls, \
         patch("odp_platform.training.service.log_device_info"):
        yolo_cls.return_value.train.side_effect = RuntimeError("CUDA OOM")
        result = TrainService().train(cli_args={})

    assert result.success is False
    assert "CUDA OOM" in result.error
```

⚠️ **设计点 (`patch` 路径必须是 `odp_platform.training.service.xxx`)**: Python `unittest.mock.patch` 的对象是\"name binding\", 不是\"name source\". service.py 顶部 `from odp_platform.runtime_config import build_train_config` 之后, service 模块内部就持有了一个**名字叫 `build_train_config` 的本地引用**——patch 必须冲这个本地引用打.

```python
# ❌ 反例 — patch 不到位
patch("odp_platform.runtime_config.build_train_config", ...)   
# service.py 里 build_train_config 仍然指向原函数

# ✅ 正例 — patch 到 service 内部的本地引用
patch("odp_platform.training.service.build_train_config", ...)
```

这条规则适用于所有 `from X import Y` 风格的 import, 是 mock 测试的常见绊脚石.

## 9.6 pyproject.toml / pytest 配置

D5 已经立好了, D6 不动:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
```

## 9.7 跑一遍 pytest

```bash
cd apps/platform
python -m pytest tests/common/ tests/training/ -v
```

期望输出(片段, 实际还会更多):

```
tests/common/test_model_path.py::test_absolute_path_returned_as_is PASSED
tests/common/test_model_path.py::test_filename_falls_back_to_pretrained PASSED
tests/common/test_model_path.py::test_search_dirs_first_dir_hit PASSED
tests/common/test_model_path.py::test_search_dirs_fallback_to_second PASSED
tests/common/test_model_path.py::test_search_dirs_none_equals_default PASSED
tests/common/test_dataset_path.py::test_absolute_path_returned_as_is PASSED
...
tests/common/test_log_rename.py::test_no_filehandler_returns_none_with_warning PASSED
tests/common/test_log_rename.py::test_rename_reuses_timestamp PASSED
...
tests/common/test_result.py::test_log_train_metrics_unknown_task_falls_back PASSED
...
tests/training/test_archive.py::test_archive_copies_both PASSED
tests/training/test_archive.py::test_archive_missing_train_dir_returns_empty PASSED
tests/training/test_service.py::test_train_success_full_flow PASSED
tests/training/test_service.py::test_train_validation_fail_returns_failure PASSED
tests/training/test_service.py::test_train_yolo_runtime_error_caught PASSED

========= 48 passed in 2.41s =========
```

48 个用例覆盖 8 个新模块. 加上 D2/D3/D4/D5 的已有用例, 整套 ODPlatform 仍然 ✓ 全绿.

## 9.8 git commit

```bash
git add apps/platform/tests/common/ apps/platform/tests/training/
git commit -m "test(training+common): add unit tests for 6 common tools + 2 training modules

48 个用例, 8 个新文件:
  - tests/common/test_model_path.py    (11 用例, 含 search_dirs 升级)
  - tests/common/test_dataset_path.py  (5 用例)
  - tests/common/test_log_rename.py    (7 用例, named root + 时间戳复用)
  - tests/common/test_config_log.py    (6 用例)
  - tests/common/test_result.py        (19 用例, 含 task='unknown' fallback)
  - tests/training/test_archive.py     (best-effort 永不抛验证)
  - tests/training/test_service.py     (mock D5/D4/ultralytics 全流程)

  conftest.py 拆分:
  - tests/common/conftest.py:   mock_det_results / mock_segment_results
  - tests/training/conftest.py: fake_train_dir (含 weights/best.pt/last.pt)
"
```

下一阶段写 ADR-006.


---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 10: ADR-006 — 把"为什么"沉淀下来

跟 D5 阶段 9 一样, D6 也立一份 ADR (Architecture Decision Record). 不是给"现在的我们"看的, 是给"半年后接手 D7 的人"看的——他打开 `docs/adr/` 一翻就知道 D6 当年为什么这么拆.

## 10.1 ADR-006 完整内容

新建 `docs/adr/006-training-subsystem.md`:

```markdown
# ADR-006: training 子系统设计

- **状态**: Accepted
- **日期**: 2026-05-24
- **决策者**: ODPlatform team
- **关联**: ADR-001 (路径 SSoT), ADR-002 (词汇 SSoT), ADR-005 (runtime_config 子系统)

## 1. 背景

D5 完成 runtime_config 子系统后, ODPlatform 已经能:
- 通过 `build_train_config(yaml_path, cli_args)` 得到合并好的 Pydantic 配置 + 溯源 merger
- 通过 `odp-gen-config train` 生成自解释的 YAML 模板
- 通过 D4 `validate_dataset` 对数据集做 fail-fast 校验
- 通过 D2 `get_logger("odp_platform", "train")` 拿到一份"业务模块统一发声"的根 logger

但这些子系统**互相之间没有衔接**——用户拿到配置, 想跑训练, 必须自己写胶水代码:

```python
config, merger = build_train_config(...)
report = validate_dataset(...)         # 自己接 D4
if report.exit_code >= 2: ...           # 自己处理失败
get_logger(...)                         # 自己接 D2
model = YOLO(config.model)              # 自己接 ultralytics
model.train(**config.to_ultralytics_kwargs())
# 然后自己 rename log / archive 权重 / 写 audit JSON / 处理异常 / ...
```

胶水代码量大约 200 行——**且每个新用户都要写一遍**, 错误率非常高(典型错误: 不挂 D2 logging / 跳过 D4 校验 / 不归档权重 / 让 ultralytics 异常直接穿透 CLI).

## 2. 决策

立一个 `training/` 子系统作为编排器, 把上述 4 个邻居子系统 + ultralytics 串起来. 子系统的内部结构遵循\"跨任务通用 → `common/`, 训练专属 → `training/`\"原则.

### 2.1 核心设计选择

| 决策点 | 选项 | 选择 | 理由 |
|---|---|---|---|
| **service 模式** | 包装器 / 薄壳函数 / 编排器 | **编排器** | 8 阶段流水线, 每阶段调一个邻居子系统, 看 service 就是看一次训练做了哪些事 |
| **service 抛不抛异常** | 抛 / 不抛 | **不抛, 装进 `TrainResult.error`** | jupyter / 服务化 / 自动化脚本统一收益 |
| **6 个跨任务工具放哪** | training / common / 新立 yolo_common | **`common/`** | D7 ValService / D8 InferService 都要复用, 放 training 等于让验证 / 推理子系统依赖训练子系统 |
| **TrainMetrics 物理位置** | training/result.py / common/result.py | **`common/result.py`** | D7 ValMetrics 跟 TrainMetrics 几乎同构, 复用一个 dataclass |
| **TrainMetrics 公开路径** | 只 common / common + training 转再导出 | **两条路径都暴露** | `from odp_platform.training import TrainMetrics` 跟 `TrainResult` 一起取符合直觉 |
| **logging handler 装在哪** | 业务模块装 / 每个 service 装 / 只 CLI 入口装 | **只 CLI 入口装一次** | 走 D2 `get_logger("odp_platform", "train")`, 业务模块只发声 |
| **log_rename 操作哪个 root** | unnamed root / `"odp_platform"` named root | **named root** | D2 设计了 named root + `propagate=False`, 操作 unnamed root 等于操作了一个空 logger |
| **best/last.pt 归档** | 不归档 / 移动 / 复制 | **复制** | 原文件留给 ultralytics resume / val 直接读, 归档一份给 D7/D8 引用 |
| **archive 失败影响 result.success** | 是 / 否 | **否(best-effort)** | 训练已经成功, 归档失败只是用户要手动复制, 不让 archive 拖累训练成败判断 |
| **audit JSON 落点** | runs/<task>_train/<train_dir>/odp_audit.json / 独立目录 | **跟 ultralytics save_dir 同目录** | 跟 args.yaml / results.csv 一起, 自然形成"实验快照"概念 |

### 2.2 公开 API (`training/__init__.py` 的 `__all__`)

```python
__all__ = [
    "TrainService",     # class — 训练编排
    "TrainResult",      # dataclass — 训练结果(成败 + 路径 + 指标)
    "TrainMetrics",     # dataclass — 完整指标(转再导出自 common.result)
    "train_yolo",       # function — 便捷一行调用
]
```

下游(D7 / D8 / experiment_db / jupyter)只从这 4 个符号取依赖.

### 2.3 3 条工程规矩 (CI 守门)

| 规矩 | grep 自检 |
|---|---|
| service 内部不重新发明 D5 | `grep "YAMLLoader\|CLILoader\|ConfigMerger" service.py` → 0 |
| 业务模块不挂 handler | `grep -rn "addHandler\|setLevel(" training/ common/` → 只能在 logging_utils / log_rename 出现 |
| 验证/推理子系统不依赖训练 | `grep -rn "from odp_platform.training" evaluation/ inference/` → 0 |

## 3. 不选择的方案

### 方案 A: 把 6 个 common 工具放 `training/`

跟选定方案的差别: 工具的物理位置.

**为什么不选**:
- D7 ValService 需要 `resolve_model_path / resolve_dataset_path / rename_log_to_save_dir`, 必须 `from odp_platform.training import resolve_model_path`
- "验证模块从训练模块 import 工具"——名字跟语义打架, 一眼读不懂
- D8 InferService 同样问题, 一锅端
- 跨任务通用工具不应该挂在任何一个任务的子系统下, 应该挂在 `common/`(项目共享底层)

### 方案 B: 立一层 `yolo_common/` 隔离 YOLO 工具

把 6 个 YOLO 工具放在 `apps/platform/src/odp_platform/yolo_common/`, 跟 `common/` 区分开.

**为什么不选**:
- `odp_platform` 这个端的定位就是\"目标检测平台\"——`common/` 必然被 YOLO 概念污染, 那是合理的
- 再加一层 `yolo_common/` 等于在 YOLO 平台里加一个\"yolo 子标签\", 跟项目名打架
- `common/system_utils.log_device_info` (D2 已立) 也是 ML-only, 同样\"污染\"了 common——但接受度高, 没人提议把它搬走

### 方案 C: 把整个 D6 揉成一个 `train.py` 朴素脚本(不立子系统)

跟绝大多数 yolo 教程同款.

**为什么不选**:
- D5 立的配置溯源、D4 立的数据校验、D2 立的 logging 通道全部要在用户那一侧手工拼接
- 每个用户写 200 行胶水代码, 错误率高
- 没有"训练结果"的实体概念, audit / experiment_db / D7 接 best 都无处接入

### 方案 D: 不立 log_rename, 只靠 `audit JSON` 记录 log_path

D6 只写 audit JSON 一种方式让用户找日志, 不动 named root 的 FileHandler.

**为什么不选**:
- `ls logging/train/` 跟 `ls runs/detect_train/` 对不上是真实高频痛点(每次 debug 都要查映射)
- 文件名直接编码 save_dir 比 audit JSON 查映射的体验好得多
- log_rename 的风险用"操作 named root + best-effort 永不抛 + 失败回滚"治住了, 风险可控

## 4. 后果

### 4.1 好处

- **一行 `odp-train` 跑通完整训练**, 自动接 D2/D4/D5/ultralytics, 用户不写胶水
- **`TrainResult` 永不抛**——jupyter / 服务化 / 自动化脚本调用方式统一
- **`common/` 6 个工具直接被 D7/D8 复用**——D7 写出来的 service.py 跟 D6 高度对称, 维护成本低
- **`odp_audit.json` 给未来 experiment_db 留好落点**——任何一次训练的产物 + 配置 + 指标 + 链路日志都能 1 行 import 进 DB
- **日志文件名跟 save_dir 对得上**——日常 debug 不再查映射表

### 4.2 坏处 / 风险

- **`training/__init__.py` 转再导出 `TrainMetrics`**——一个符号两个路径, 必须靠 ADR + docstring 解释清楚, 否则会让新人疑惑"我到底从哪里 import"
- **log_rename 操作 named root**——一旦 D2 改了 `ROOT_LOGGER_NAME` 常量, log_rename 这个硬编码"odp_platform"要跟着改(已在源码注释里标注)
- **archive 失败不影响 `success`**——用户可能错过 warning, 训练完看不到归档文件以为是 service bug. 缓解: 日志里 warning 级输出 + audit JSON 里 `best_archive` 字段会是 null, 容易排查

### 4.3 性能影响

- **service 内部的额外 logging**(2 段配置溯源 + 1 段指标 + 1 段类别 mAP) → 多写大约 30 行日志, 增量可忽略
- **archive 复制 best+last** → 一次性 IO, 通常 < 200ms(模型 < 100MB 量级)
- **audit JSON 写盘** → 单文件几 KB, 一次性 IO 可忽略

## 5. 关键文件位置

```
apps/platform/src/odp_platform/

common/                              ← 跨任务通用 (6 个新增)
├── model_path.py                    resolve_model_path (含 search_dirs)
├── dataset_path.py                  resolve_dataset_path
├── log_rename.py                    rename_log_to_save_dir (操作 named root)
├── config_log.py                    log_effective_config + log_override_chains
├── result.py                        TrainMetrics + log_train_metrics
└── plot_style.py                    apply_academic_style

training/                            ← 训练专属 (3 个新增)
├── __init__.py                      公开 4 个符号
├── service.py                       TrainService + TrainResult + train_yolo
└── archive.py                       archive_checkpoints

cli/                                 ← CLI 入口 (1 个新增)
└── train_model.py                   odp-train

tests/                               ← 单元测试 (7 个新增 + 2 个 conftest)
├── common/
│   ├── conftest.py                  mock_det_results / mock_segment_results
│   ├── test_model_path.py
│   ├── test_dataset_path.py
│   ├── test_log_rename.py
│   ├── test_config_log.py
│   └── test_result.py
└── training/
    ├── conftest.py                  fake_train_dir
    ├── test_archive.py
    └── test_service.py

docs/adr/
└── 006-training-subsystem.md        本文档
```

## 6. 跟其他 ADR 的关系

- **ADR-001 (路径 SSoT)**: D6 完全靠 `common/paths.py` 拿路径, 不动它. `CHECKPOINTS_DIR` 在 D2 就立好了, D6 只是第一个真正写入它的子系统
- **ADR-002 (词汇 SSoT)**: D6 完全靠 `common/constants.py` 的 `Task.DETECT / Task.SEGMENT`, 不立第二份
- **ADR-005 (runtime_config)**: D6 的 service.py 通过 `build_train_config(yaml_path, cli_args)` 一行获取配置和 merger, 不重新发明任何 D5 已有的合并 / 验证 / 溯源逻辑

## 7. 后续工作

- **D7: evaluation 子系统** — 立 ValService, 复用 D6 的 6 个 common 工具
  - `resolve_model_path("train3-best.pt", search_dirs=[CHECKPOINTS_DIR, PRETRAINED_MODELS_DIR])` 优先查 D6 归档
  - `resolve_dataset_path` 直接复用
  - `rename_log_to_save_dir` 直接复用(把 `train3` 换成 `val3` 即可)
  - `TrainMetrics` 以别名 `ValMetrics = TrainMetrics` 复用(物理同一个类), 复用 `_METRIC_FIELDS_BY_TASK`
- **D8: inference 子系统** — 立 InferService, 同样复用 6 个 common 工具
- **experiment_db 子系统(尚未编号)** — 接管 `odp_audit.json` 的消费侧, 把所有训练 / 验证产物入库
- **`task='unknown'` 优化(P3)** — `TrainMetrics.from_yolo_results` 当前对 task='unknown' 走 fallback 分支(打 results_dict 全量). 可优化为从 config.task 传 task 进来作 fallback. 优先级低, 不影响功能, 列在 ADR-006 后续工作里跟踪
- **`search_dirs` 测试增量** — 加 D7 时同时加"传 2 个目录, 第 1 个命中"和"第 1 个没命中走第 2 个"这两条覆盖

## 8. 修订记录

- **2026-05-24**: 初版 (Accepted)
```

## 10.2 git commit

```bash
git add docs/adr/006-training-subsystem.md
git commit -m "docs(training): add ADR-006 documenting training subsystem boundaries

记录 D6 的核心架构决策:
  - 编排器(orchestrator)模式: 8 阶段流水线, 每阶段调一个邻居子系统
  - common/ vs training/ 拆分: 跨任务通用 vs 训练专属
  - service 永不抛(TrainResult.error)
  - 业务模块只发声, handler 只在 CLI 入口装一次
  - log_rename 操作 D2 named root, 不操作 unnamed root
  - best/last.pt 复制归档, 不移动
  - odp_audit.json 跟 save_dir 同目录, 给 experiment_db 留落点

不选择的方案(4 个) + 3 条 grep 守门规矩 + 后续工作清单.
"
```


---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# D6 回看

D6 走完了, 该停下来看一看. 不是流水账复盘"这一节做了什么", 而是把**整套设计的判断重点**抽出来——让你下次遇到类似问题, 不用从 0 推, 直接套.

## 三次撞墙, 三次拆解

| 撞墙 | 表面问题 | 真正问题 | 拆解 |
|---|---|---|---|
| **①** 朴素方案的 4 个伤痛 | "我直接 `model.train(**vars(args))` 不行吗?" | 子系统边界没立, D2/D4/D5 都白做 | 立 TrainService 编排器, 8 阶段每段调一个邻居 |
| **②** `getLogger()` 不等于 `"odp_platform"` | "我自己挂 handler 不就行了?" | 不理解 D2 的 named root + propagate=False 截断设计 | CLI 唯一装 handler 处, 走 D2 `get_logger`; 业务模块只发声 |
| **③** save_dir 训练前不知道 | "我提前生成最终文件名总行吧?" | 时间序上不可能——save_dir 是 ultralytics 自增的 | 训练前用占位, 训练后操作 named root 改名, 同时写 audit JSON 双保险 |

**共同的方法论**: 每一次的"看似简单的解法"都会撞墙, 撞墙的本质都是**没注意到边界**——D6 的整套结构就是\"把这些边界一次次显式画出来\".

## 两层边界的硬保证

D6 一共立了两层边界, 都用 grep 守门:

### 边界 ① — service 不重新发明 D5/D4/D2

```bash
grep "YAMLLoader\|CLILoader\|ConfigMerger\|build_snapshot" \
  apps/platform/src/odp_platform/training/service.py
# 期望: 0 输出
```

service.py 通过 `build_train_config()` 一行调 D5, 通过 `validate_dataset()` 一行调 D4, 通过 `getLogger(__name__)` 接 D2. **不在 service 里写第二份合并/校验/handler 装载逻辑**.

### 边界 ② — 验证/推理子系统不依赖训练子系统

```bash
grep -rn "from odp_platform.training" \
  apps/platform/src/odp_platform/evaluation/ \
  apps/platform/src/odp_platform/inference/ 2>/dev/null
# 期望: 0 输出 (D7/D8 写完之后这条 grep 必须仍然 0)
```

D7/D8 需要 `resolve_model_path / resolve_dataset_path / rename_log_to_save_dir / log_train_metrics` 时, **必须**走 `from odp_platform.common.xxx`. 训练子系统不是工具的发行渠道.

## 8 个新模块, 单一职责

| 模块 | 职责一句话 | 跨任务? | 永不抛? |
|---|---|---|---|
| `common/model_path.py`   | 解析模型路径(绝对 / 仅文件名 / fallback)             | ✓ | ✓ |
| `common/dataset_path.py` | 解析数据集 yaml 路径                                 | ✓ | ✓ |
| `common/log_rename.py`   | 训练后把 named root 的 FileHandler 改名跟 save_dir 对齐 | ✓ | ✓ |
| `common/config_log.py`   | 按字段维度日志输出(当前值/来源 + 完整链)             | ✓ | ✓ |
| `common/result.py`       | TrainMetrics dataclass + 漂亮打印                   | ✓ | ✓ |
| `common/plot_style.py`   | matplotlib 学术发表风格(显式调用)                   | ✓ | ✓ |
| `training/archive.py`    | 权重归档到 CHECKPOINTS_DIR                          | ✗ | ✓ |
| `training/service.py`    | 8 阶段编排 D5/D4/D2/ultralytics                      | ✗ | ✓ |

每一行"职责"都能用一句话讲完——这是健康设计的标志. 如果某个模块的职责需要 3 句话才能讲清, 多半是揉了不该一起的事.

## 数据驱动 > 方法驱动

`common/result.py` 的 `_METRIC_FIELDS_BY_TASK` 是一个 dict:

```python
_METRIC_FIELDS_BY_TASK: dict[str, list[tuple[str, str]]] = {
    Task.DETECT:  [...4 个指标...],
    Task.SEGMENT: [...8 个指标...],
    # 加 Task.POSE / Task.CLASSIFY 只需要加一行
}
```

加新任务只动数据(加一行), 不动方法(`log_train_metrics` 一行不改). 这是经典的\"用数据描述差异\"而不是\"用 if-else 描述差异\"的设计.

反模式的对照:

```python
# ❌ 反模式 — 方法驱动
def log_train_metrics(metrics):
    if metrics.task == "detect":
        log_detect_metrics(metrics)
    elif metrics.task == "segment":
        log_segment_metrics(metrics)
    elif metrics.task == "pose":
        log_pose_metrics(metrics)
    # 加新任务要 if elif, 加 log_xxx_metrics 函数
```

> **金句**: **\"用数据描述差异, 不用 if-else 描述差异. 加新数据是加行, 加 if-else 是改方法——前者风险低得多.\"**

## 报错信息是 API

D6 的所有"用户面错误信息"都明确告诉用户**下一步该怎么做**:

```python
# data_validation 失败
raise RuntimeError(
    f"数据集校验失败 ({error_count} 个 ERROR 级问题). "
    f"请用 `odp-validate --dataset {data_path.stem} --task {config.task}` 修复后再训练. "
    f"如要跳过校验跑训练(不推荐), 加 --no-pre-validate."
)
# ↑ 用户看到这条 error 立刻知道两个选项: 修 / 加开关跳过
```

```python
# model_path 找不到模型
logger.warning(
    f"模型文件未在任何搜索目录命中: {model_path.name}\n"
    f"  搜索过的目录: {[str(d) for d in dirs]}\n"
    f"  ultralytics 将尝试自动下载或从其他位置加载."
)
# ↑ 用户看到 warning 知道 D6 已经尝试了哪些目录, 接下来发生什么
```

```python
# log_rename 失败
logger.warning(
    f"'{ROOT_LOGGER_NAME}' 根 logger 上没有 FileHandler, "
    f"跳过日志改名 (CLI 入口可能没调 get_logger?)"
)
# ↑ 用户看到 warning 直接知道往哪查问题
```

错误信息不只是"出错了"——它是 API 的一部分. 它告诉用户**接下来你能做什么 / 不能做什么 / 怎么修**.

> **金句**: **\"错误信息是 API 的一部分, 跟函数签名一样要精心设计. 一句话能让用户知道下一步该做什么的错误, 比 stack trace 强 10 倍.\"**

## 给 D7 / D8 的接口承诺

D6 给后面留了 4 个明确的接口承诺. D7/D8 写出来如果不用上, 就说明 D6 没做到位.

### 承诺 1 — `resolve_model_path(model, search_dirs=...)`

D7 写法:

```python
from odp_platform.common.model_path import resolve_model_path
from odp_platform.common.paths import CHECKPOINTS_DIR, PRETRAINED_MODELS_DIR

# 验证 D6 归档的 best 优先, 找不到再 fallback 预训练
model_path = resolve_model_path(
    config.model,
    search_dirs=[CHECKPOINTS_DIR, PRETRAINED_MODELS_DIR],
)
```

D6 默认行为(`search_dirs=None` 等价 `[PRETRAINED_MODELS_DIR]`)保证 D6 自己一行不动. D7 显式传 search_dirs 启用归档优先.

### 承诺 2 — `resolve_dataset_path(data)`

D7 写法**一字不差**跟 D6 一样:

```python
from odp_platform.common.dataset_path import resolve_dataset_path
data_path = resolve_dataset_path(config.data)
```

数据集 yaml 的 SSoT 只有一个(`DATASET_CONFIGS_DIR`), 不需要参数化.

### 承诺 3 — `rename_log_to_save_dir(save_dir, model_stem)`

D7 写法:

```python
from odp_platform.common.log_rename import rename_log_to_save_dir
# D7 ValService 跑完, save_dir 是 runs/detect_val/val3 这种
rename_log_to_save_dir(val_save_dir, model_stem)
# 日志变成 val3_<ts>_<model>.log, 跟 ls runs/detect_val/ 一眼对得上
```

### 承诺 4 — `TrainMetrics` 复用 / `_METRIC_FIELDS_BY_TASK` 复用

D7 ValMetrics 直接复用 `TrainMetrics`(或在 common.result 加一个 ValMetrics 别名). `_METRIC_FIELDS_BY_TASK` 数据驱动, 加新任务只动这个 dict.

```python
from odp_platform.common.result import TrainMetrics, log_train_metrics

val_metrics = TrainMetrics.from_yolo_results(val_results)
log_train_metrics(val_metrics, logger=logger)   # 同一个打印函数
```

## 下一站: D7

D6 立了训练侧, **D7 立验证侧**——拿 D6 归档的 best/last.pt 在测试集上验证 / 拿外部模型在我们的数据上验证.

D7 的写法应该是 D6 的镜像:
- `evaluation/service.py` 跟 `training/service.py` 高度对称(分阶段编排, 永不抛)
- 复用 6 个 common 工具(完全不写第二份)
- 立 `evaluation/__init__.py` 公开 ValService / ValResult / ValMetrics
- CLI `odp-val`, 同款 argparse → service → 退出码翻译流程

D7 写完之后, 你可以**直接 grep 验证 D6 的接口承诺确实兑现了**:

```bash
# D7 的 service 是不是真的复用了 D6 的 common 工具?
grep "from odp_platform.common" apps/platform/src/odp_platform/evaluation/service.py
# 应该看到 6 行: model_path / dataset_path / log_rename / config_log / result / paths

# D7 是不是从 training 误 import 了什么?
grep "from odp_platform.training" apps/platform/src/odp_platform/evaluation/
# 期望: 0 输出
```

这一行 grep 是 D6 和 D7 之间的合约——D6 的设计承诺由 D7 的代码验证.

---

> **D6 收尾金句**:
>
> **\"训练子系统不发明任何新方法——把 D2/D4/D5/ultralytics 用对地方接起来就行. 真正的工作量在【边界纪律】上, 不在【代码行数】上.\"**
>
> **\"业务模块只发声, handler 由 CLI 入口装一次——这条纪律对一切 service 模块都成立, 不止 D6.\"**
>
> **\"模块归属看【跨任务通用与否】, 不看【哪一节先写到】. 这条规矩立晚了, D7 写出来时再返工就是大手术.\"**

