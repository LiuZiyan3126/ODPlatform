# ODPlatform D5: runtime_config 子系统

> **📝 v2 更新说明(2026-05-23)**:
> 本次更新围绕 `odp-gen-config` entry-point 的全面对齐:
> - **统一主推 `odp-gen-config <name>` 命令**(原讲义里"两种都要支持"的规矩 D 在 §0.5.4 早就立了, 这版把全文示例都对齐过来)
> - `python -m odp_platform.runtime_config.generator <name>` 降级为**讲义示例 / 装包前备胎**(实现侧没改, 两个入口仍然共享 `generator.py:main`)
> - **fail-fast 报错信息**(`YAMLLoader`)里的修复指引从 `python -m ...` 改成 `odp-gen-config <name>`——短一倍, 跟其他 odp-* 命令同款
> - 相关测试断言(`test_loaders` / `test_generator`)跟着改用 `odp-gen-config`
> - §6.5 章节标题改为"双入口", 更准确反映实现状态
> - 设计判断保持不变: entry-point 直接绑 `runtime_config.generator:main`, **不立** `cli/generate_config.py` 薄包装(理由: generator 既是反射工具又是 CLI 主流程, 自带 main 即可)
>
> 配套交接文档已升级到 v1.3, D5 功能清单升级到 v1.2. v1 原版本仍可参考, 但全文示例命令请以本 v2 为准.

---

> **课程定位**: 实训第 5 天讲义
>
> **核心叙事**: 从一个干净的 D4 仓库出发, 构建一个完整的【运行配置子系统】 `runtime_config/`——把"散落在 argparse / YAML / 默认值三处的 60+ 训练参数"变成"一份 Pydantic 类 + 一行 `model.train(**kwargs)`", 顺带获得**自解释 YAML 模板**、**三源合并溯源**、**fail-fast + 友好提示**三件套.
>
> **三面真撞墙(比 D4 节制——D5 是\"把已有思路用对地方\", 不是\"立全新模式\")**:
> 1. **60+ 字段散落在 argparse / YAML / 默认值三处** → 推出 Pydantic BaseConfig + 字段级元数据
> 2. **YAML 文件不存在时自动生成默认模板继续跑** → 推出 fail-fast + 修复指引
> 3. **`task = "detect_val"` 既当语义又当目录名** → 拆 `task` (SSoT 语义) + `experiment_name` (实验标识)
>
> **配套上一节**: 《D4: data_validation 子系统》
>
> **配套下一节**: 《D6: training 子系统》(D5 立配置, D6 才有得跑)
>
> **设计原则**: **runtime_config 子系统只描述, 不执行**——决定\"跑什么参数\"归 runtime_config, \"怎么跑\"归 D6 TrainService. 两件事混在一起会让\"我加个参数到底改哪个文件\"这种基本问题都说不清楚.
>
> **建议时长**: 6-8 课时

---

## 📌 跨平台命令说明

沿用 D2 / D3 / D4 的约定, 本文不再重复. 需要区分平台时用并列代码块, 普通 `python` / `pip` / `git` 命令跨平台一致只写一次. Windows 用户**推荐 Git Bash**——绝大多数命令直接跟 Linux 走, 省心.

---

## 文档使用说明

D5 的产物有两类: **代码**和**对代码的解释**.

- **完整代码**: 每个文件都是终态, 可直接复制粘贴
- **⚠️ 设计点框**: 容易写错或容易选错的地方提前告诉你
- **🧱 撞墙时刻**: 仅 3 次, 亲手体验
- **🤔 思考题**: 给读者 30 秒, 思考再往下看
- **shell 命令**: 测试 / 运行 / git 操作
- **git commit**: 每个里程碑对应一次提交

**强烈建议**: **跟着文档自己敲一遍**——D5 是 Pydantic + 字段元数据 + 三源合并 + 溯源链表四样东西组合, 不亲手过一遍, 看到\"为什么 ConfigMetadata 要做成链表\"时就会糊涂.

---

## 上一节回顾 + 本节挑战

D4 解决了\"我的数据**对不对**\"——4 个 check 跑完, 拿到一份带退出码的报告, 数据这层守住了.

D5 接下来要回答的问题是: \"我的训练**怎么跑**?\"

这件事有多少种参数? 翻 ultralytics 文档, `model.train()` 接受 **60+ 个参数**——epochs / batch / lr0 / optimizer / cos_lr / mosaic / mixup / hsv_h / box loss 权重... 每个参数都有自己的合理默认值, 也都有可能需要调.

**朴素方案**: 全部写成 argparse 参数 + 一个 default YAML, 然后 `argparse.parse_args() → vars() → model.train(**args)`. 这是绝大多数 yolo 教程的做法, 也是你 legacy 仓库里的 `yolo_train.py` 那 200 行长长的 argparse 设置块.

**问题**: 这套朴素方案在工业场景下会很快暴露 4 个伤痛:

1. **字段散落**: argparse `add_argument` 一次、YAML 默认值一次、`vars(args)` 过滤一次, 加一个参数要改 3 处.
2. **无验证**: 用户填 `imgsz=649`(非 32 倍数)、`batch=0`(零批)、`device="cpuu"`(拼错)——argparse 全部默默通过, 训练崩溃时栈里看不到\"你是不是 imgsz 填错了\".
3. **无溯源**: 跑完看日志, `lr0=0.001`——这个 0.001 是 CLI 给的还是 YAML 给的还是默认值? 跑完只剩\"它就是这样\".
4. **配置即文档**: 用户拿到一个 default.yaml, 里面写着 `mosaic: 1.0`——这是什么? 范围是 0-1 还是 0-10? 默认值合理吗? 啥时候该调? **没有元数据 = 永远在查 ultralytics 文档**.

D5 的任务: **用 Pydantic + 字段元数据 + 三源合并器 + 配置生成器**, 把这 4 个伤痛一次干掉, 顺手给 D6 留一份能直接 `model.train(**config.to_ultralytics_kwargs())` 的接口.

> **金句**: **\"配置不是\"参数表\", 是子系统的【对外语言】——语言越精确, 误用越少.\"**

---

## 起点与终点

**起点**: 完成 D4, 仓库当前长这样:

```
apps/platform/src/odp_platform/
├── common/
│   ├── paths.py            (D2 + D3 + D4 增量)
│   ├── constants.py        (D3 立 + D4 增量)
│   ├── logging_utils.py    (D2)
│   ├── string_utils.py     (D2)
│   ├── system_utils.py     (D2)
│   └── performance_utils.py (D2)
├── data_pipeline/          (D3 产出)
├── data_validation/        (D4 产出)
└── cli/
    ├── init_project.py     (odp-init)
    ├── reset_project.py    (odp-reset)
    ├── transform_data.py   (odp-transform)
    └── validate_data.py    (odp-validate)
```

**终点**: 仓库新增一个完整的 `runtime_config/` 子系统 + 两个 YAML 模板生成命令:

```
apps/platform/src/odp_platform/
├── common/
│   └── paths.py            🔄 D5 增量 (RUNTIME_CONFIGS_DIR + runtime_config_path)
│
├── runtime_config/         ✨ D5 产出 (本节主角)
│   ├── __init__.py         (对外公共 API)
│   ├── base.py             (BaseConfig — 训练 / 验证 / 推理共享字段)
│   ├── train.py            (YOLOTrainConfig — 60+ 训练字段)
│   ├── val.py              (YOLOValConfig — 含 task/experiment_name 拆分)
│   ├── infer.py            (YOLOInferConfig — 17 推理字段 + source 输入源) ★ 推理闭环
│   ├── loaders.py          (YAMLLoader + CLILoader, fail-fast)
│   ├── merger.py           (ConfigMerger + ConfigSource + ConfigMetadata)
│   └── generator.py        (ConfigGenerator + python -m 入口, 支持 train/val/infer)
│
└── configs/runtime/        🔄 D5 立 (跟 configs/datasets/ 物理分目录)
    ├── train.yaml          (生成器产出, 用户编辑)
    └── val.yaml            (生成器产出, 用户编辑)
```

跑通后, 用户的工作流是:

```bash
# 1. 第一次跑——先生成模板(主推 entry-point 命令)
odp-gen-config train
# → 写出 configs/runtime/train.yaml(带分组 / 注释 / 示例 / 提示)
#
# 备胎(装包前 / 调试 import / 讲义示例时用):
#   python -m odp_platform.runtime_config.generator train
# 两个入口共享同一份 generator.py:main, 行为完全等价.

# 2. 编辑模板——改自己想改的字段, 不想改的留默认

# 3. 跑(这一步要等 D6 TrainService, D5 只准备配置侧)
# 在 D6 里大概会长这样:
odp-train --config train.yaml --epochs 200      # CLI 可覆盖 YAML
```

D5 子系统的 entry-point 边界: **只把 `ConfigGenerator` 包成 `odp-gen-config`**——`build_train_config` / `ConfigMerger` 这些仍然是**库**(给 D6 service 层调用, 不绑命令). D5 提供:

- 一个 `odp-gen-config <name>` entry-point 生成模板(也支持 `python -m odp_platform.runtime_config.generator <name>` 备胎)
- 一份对外公共 API, 供 D6 TrainService 调用

---

## D5 全部 git commit (终态)

```
* docs(runtime_config): add ADR-005 documenting runtime_config subsystem design
* test(runtime_config): add unit tests for BaseConfig / loaders / merger / infer
* feat(runtime_config): add public API in __init__.py
* feat(runtime_config): add ConfigGenerator + python -m entry (train/val/infer)
* feat(runtime_config): add ConfigMerger with source tracking
* feat(runtime_config): add YAMLLoader + CLILoader with fail-fast
* feat(runtime_config): add YOLOInferConfig with source-required field
* feat(runtime_config): add YOLOTrainConfig + YOLOValConfig with task/experiment_name split
* feat(runtime_config): add BaseConfig with field-level metadata
* feat(common): add RUNTIME_CONFIGS_DIR + runtime_config_path
```

**10 次提交, 每一次对应一个具体的\"我解决了什么问题\"**.

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 0: 立规矩 (paths.py 增量)

跟 D3 / D4 阶段 0 一样, 本阶段不写业务代码, 只立规矩.

D5 要立的规矩只有一条: **运行配置文件目录从 `configs/` 拆出来, 放 `configs/runtime/`**.

## 0.1 为什么要拆 `configs/runtime/` 出来?

D3 立的 `configs/datasets/` 装的是\"描述数据的 YAML\"——`safety_helmet.yaml`、`rsod.yaml`, 每份 yaml 写的是 `path / train / val / nc / names`, 由 `odp-transform` 产出, 被 ultralytics 直接消费.

D5 要立的\"运行配置\"装的是\"描述跑法的 YAML\"——`train.yaml`、`val.yaml`, 每份 yaml 写的是 `epochs / lr0 / batch / optimizer`, 由 `python -m ... generator` 产出, 被 TrainService(D6) / ValService(D7) 消费.

**两件事语义完全不同**:

| | configs/datasets/ (D3) | configs/runtime/ (D5) |
|---|---|---|
| 描述什么 | 【数据】长什么样 | 【跑法】是什么 |
| 谁产出 | `odp-transform` | `python -m generator` 或手写 |
| 谁消费 | ultralytics 直接吃 | TrainService 加载 → 转 ultralytics kwargs |
| 改频率 | 数据集做完就基本不动 | 调参时一直在改 |
| 进 git 吗 | ✅ 进(数据契约的一部分) | ✅ 进(实验可复现的一部分) |

⚠️ **设计点 (物理分目录的价值)**: 不是\"为了好看\". 当用户问\"我把 `mosaic: 0.5` 写错了, 改 yaml 还是改 train 配置?\", 一句\"改 `configs/runtime/train.yaml`\"就解决——目录名本身就是\"路径上的文档\". 混在一起的话, 同一目录 grep `safety_helmet`(数据集名)和 `safety_helmet`(实验名)就分不清.

> **金句**: **\"目录名是路径上最便宜也最显眼的文档——能用目录回答的问题, 别留给 README.\"**

## 0.2 paths.py 增量(本节只新增 1 项)

打开 `apps/platform/src/odp_platform/common/paths.py`, 末尾追加:

```python
# ============================================================
# D5 增量: 运行配置目录 (跟 D3 立的 DATASET_CONFIGS_DIR 语义完全不同)
#   DATASET_CONFIGS_DIR: 描述【数据】的 yaml (odp-transform 产出)
#   RUNTIME_CONFIGS_DIR: 描述【跑法】的 yaml (runtime_config 子系统产出)
# 两类 yaml 物理分目录, 语义不会互相污染.
# ============================================================
RUNTIME_CONFIGS_DIR: Path = CONFIGS_DIR / "runtime"


def runtime_config_path(name: str) -> Path:
    """返回某个运行配置文件路径: <CONFIGS_DIR>/runtime/<name>.yaml

    Args:
        name: 配置名 (如 "train" / "val"), 不带 .yaml 后缀

    Returns:
        Path 对象 (尚未创建, 调用方自己 mkdir)

    用法:
        train_yaml = runtime_config_path("train")
        # → <APP_DIR>/configs/runtime/train.yaml
    """
    return RUNTIME_CONFIGS_DIR / f"{name}.yaml"
```

把 `RUNTIME_CONFIGS_DIR` 加进 `get_dirs_to_initialize()` 的返回列表, 让 `odp-init` 顺手把空目录建好:

```python
def get_dirs_to_initialize() -> List[Path]:
    return [
        # ... D2/D3/D4 已有目录 ...
        DATASET_CONFIGS_DIR,    # D3
        RUNTIME_CONFIGS_DIR,    # ★ D5 新增
    ]
```

⚠️ **设计点 (启动建 vs 按需建, 跟 D4 的判断不一样)**: D4 的 `VALIDATION_RUNS_DIR`是\"按需建\"——`runs/data_validation/` 不存在本身就是信息(\"还没跑过验证\"). 但 D5 的 `configs/runtime/` 是\"启动建\"——这是\"项目结构的骨架\", 跟 `configs/datasets/` 一样, 用户哪天会用, 先建好不冤枉.

**两条规则**:
- **运行结果目录** → 按需建(没跑过该不存在)
- **配置目录 / 数据目录骨架** → 启动建(空着没坏处, 让用户一眼看到\"应该放这里\")

⚠️ **设计点 (不用动 PROTECTED_DIRS / get_dirs_to_reset)**: D2.5 把 `CONFIGS_DIR` 放进了 `PROTECTED_DIRS`. `RUNTIME_CONFIGS_DIR` 是它的子目录, `is_protected()` 检查祖先链时自动覆盖——**不用重新登记**.

## 0.3 constants.py 复用(本节不立新常量)

D5 需要的所有词汇 D3 都立好了:

- `Task.DETECT / Task.SEGMENT`(字符串值 `"detect"` / `"segment"`)——`train.task` / `val.task` 的合法取值, 来自 `odp_platform.common.constants`.
- `Task.all()`——SSoT 校验时的合法集合.

⚠️ **陷阱预警(跟 D4 阶段 0.3 同款警告再来一次)**: 不要在 runtime_config 子系统内部立一个新的 task 字符串集. 反模式:

```python
# ❌ 反模式 — 在 runtime_config/train.py 里立第二份
class TrainTask:
    DETECT  = "detect"
    SEGMENT = "segment"
```

立刻产生\"`Task.DETECT == TrainTask.DETECT`?\"的问号——SSoT 立马破. **遇到\"我需要任务类型\"的需求, 第一反应永远是 `from odp_platform.common.constants import Task`**.

⚠️ **设计点 (SSoT 在 validator 里的硬保证)**: 光靠\"开发自觉\"不够. D5 在 `train.py` 和 `val.py` 的 `task` 字段都加了 `@field_validator`, 拒绝任何不在 `Task.all()` 里的值——**在数据进配置对象的入口就拒**, 后面所有代码都不用再担心.

> **金句**: **\"SSoT 不是写在 README 里的承诺, 是写在 validator 里的硬墙——能让代码自己拒绝违规的, 永远比靠人记住强.\"**

## 0.4 第一次 commit

```bash
git add apps/platform/src/odp_platform/common/paths.py
git commit -m "feat(common): add RUNTIME_CONFIGS_DIR + runtime_config_path

paths.py:
  + RUNTIME_CONFIGS_DIR (configs/runtime/)
  + runtime_config_path(name) helper
  Added to get_dirs_to_initialize() — odp-init now creates this dir.

Why:
  - D3 立的 configs/datasets/ 描述【数据】(odp-transform 产出)
  - D5 立的 configs/runtime/ 描述【跑法】(runtime_config 子系统产出)
  - 物理分目录, 语义不互相污染.

Notes:
  - PROTECTED_DIRS unchanged (RUNTIME_CONFIGS_DIR is under CONFIGS_DIR,
    inherits ancestor protection automatically).
  - Task (DETECT/SEGMENT) from D3 reused as-is.
"
```

**中文版** (D2 立的纪律: 重要 commit 给一份中文 message 方便团队回查):

```bash
git commit -m "feat(common): 新增 RUNTIME_CONFIGS_DIR + runtime_config_path 路径常量" \
           -m "paths.py 增量:" \
           -m "  + RUNTIME_CONFIGS_DIR (configs/runtime/)" \
           -m "  + runtime_config_path(name) 帮助函数" \
           -m "  纳入 get_dirs_to_initialize() —— odp-init 会自动创建该目录." \
           -m "为什么:" \
           -m "  - D3 立的 configs/datasets/ 描述【数据】(odp-transform 产出)" \
           -m "  - D5 立的 configs/runtime/ 描述【跑法】(runtime_config 子系统产出)" \
           -m "  物理分目录, 语义不互相污染." \
           -m "备注:" \
           -m "  - PROTECTED_DIRS 未动 (RUNTIME_CONFIGS_DIR 在 CONFIGS_DIR 之下, 自动继承祖先保护)." \
           -m "  - D3 立的 Task (DETECT/SEGMENT) 直接复用, 不再重复登记."
```


至此, **0 行 runtime_config 子系统代码, 但目录骨架和路径常量都已就绪**.

## 0.5 立 4 条工程规矩

paths.py 增量是子系统的"物理骨架". 阶段 0 顺手把 4 条**贯穿全子系统的工程纪律**也立起来——4 条规矩立得早, 后面阶段每写一行业务代码都自动合规, 不需要回头加固.

### 0.5.1 规矩 A: paths.py 是路径的唯一真相

`runtime_config/` 内所有路径都**只从 paths.py 来**, 禁止以下写法:

```python
# ❌ 反例 1: 绝对路径字符串 (跨平台炸雷)
temp_dir = Path(r"C:\Users\Matri\Desktop\yolo_server") / "configs"

# ❌ 反例 2: 相对路径硬编码
yaml_path = "configs/runtime/train.yaml"

# ❌ 反例 3: 业务模块里自己拼 APP_DIR
yaml_dir = APP_DIR / "configs" / "runtime"
```

```python
# ✅ 正例: 一律走 paths.py
from odp_platform.common.paths import (
    RUNTIME_CONFIGS_DIR,        # 路径常量
    runtime_config_path,        # 路径函数
)
yaml_path = runtime_config_path("train")          # → <APP_DIR>/configs/runtime/train.yaml
yaml_dir  = RUNTIME_CONFIGS_DIR
```

这条规矩落到 D2 立的 ADR-001 (路径 SSoT). 跨平台、mock 测试、CI 跑多操作系统——这些痛点全部因为这条规矩自动解决.

**守门员**: pre-commit hook 跑 grep:

```bash
# scripts/check_no_hardcoded_paths.sh
if grep -rn 'Path(r["'\''][A-Z]:\\' apps/platform/src/odp_platform/runtime_config/; then
    echo "禁止硬编码绝对路径"
    exit 1
fi
```

⚠️ **设计点 (规矩要可执行, 不只是文档)**: 写在 ADR 里没人看, grep 写进 CI 才有效. 规矩的"硬度"取决于它有没有自动化的守门员.

### 0.5.2 规矩 B: 警告渠道分离——`warnings.warn` vs `logger`

D5 内部两类"非致命提示"必须严格走两条渠道:

| 用什么 | 适用场景 | 受众 | 测试方式 |
|---|---|---|---|
| `warnings.warn(..., UserWarning)` | **用户输入** 相关 (字段值边缘、配置组合奇怪) | 终端用户 | `with warnings.catch_warnings(record=True):` |
| `logger.warning(...)` | **系统行为** 信息 (UTF-8 fallback、自动备份、降级) | 运维 / SRE | pytest `caplog` fixture |
| `logger.error(...)` | **可恢复错误** (验证失败已 enhance、retry 后) | 运维 / 告警 | `caplog` + 退出码断言 |
| `raise <Error>` | **不可恢复** | 调用栈 / CI | `pytest.raises(...)` |

```python
# ✅ 用户输入边缘 → warnings.warn (用户能用 -W 控制, 测试能 catch)
if v % 32 != 0:
    warnings.warn(f"imgsz={v} 不是 32 的倍数", UserWarning)

# ✅ 系统降级行为 → logger.warning (运维渠道, 进 ELK)
except UnicodeDecodeError:
    logger.warning(f"UTF-8 解码失败, fallback 系统编码: {filepath}")
```

⚠️ **设计点 (为什么混用会出问题)**: CI 跑 `python -W error::UserWarning` 想把"用户配置警告"升级成错误来强制审查, 结果 UTF-8 fallback 这种系统降级也跟着升级——CI 在跟"中文文件名读不准"较劲, 而不是在抓配置质量. 混用之后 `-W` 就再也不能用了, 测试也跟着失去这条武器.

> **金句**: **"`warnings.warn` 是给用户写的字条, `logger` 是给运维写的日志. 写错对象就送错地方."**

### 0.5.3 规矩 C: 类型注解统一 PEP 585/604 + future annotations

**强制** 每个 `runtime_config/` 文件首行:

```python
from __future__ import annotations
```

**全面采用** PEP 585 (内置泛型) + PEP 604 (`|` 联合):

```python
# ✅ D5 风格
def merge(
    self,
    config_class: type[T],                                       # PEP 585
    *,
    sources: list[tuple[ConfigSource, Mapping[str, Any]]] | None = None,   # PEP 585 + 604
) -> T:
    ...
```

依然要 import 的: `from typing import Any, ClassVar, TypeVar` (这些没内置等价物).

⚠️ **设计点 (`from __future__ import annotations` 为什么是必须的)**: 没这行, Python 3.10 才支持 `list[int]` 作为运行时类型. 加这行, 所有注解都"字符串化", 任何 3.7+ 都能写 `list[int]`——同时 mypy / pydantic 仍然能解析. **代价 0, 收益是注解能往未来看齐**.

**守门员**: ruff 加 `UP` 规则集 (pyupgrade):

```toml
[tool.ruff.lint]
select = ["E", "F", "W", "UP"]    # UP = pyupgrade, 自动改 List → list
```

CI 跑 `ruff check --select UP` 失败拦 PR.

### 0.5.4 规矩 D: pyproject.toml entry-point 注册

D5 的 CLI 提供两种使用方式:
1. **`odp-gen-config train`** (entry-point 短命令, ★ 主推 — 日常使用 / CI / Makefile / 报错信息引用 / 普通用户)
2. `python -m odp_platform.runtime_config.generator train` (模块入口, 装包前 / 调试 import / 讲义示例)

**两种都要支持**——主推 entry-point, 但模块入口也要可用(装包前没有 entry-point, 模块入口立刻能用). `apps/platform/pyproject.toml`:

```toml
[project.scripts]
odp-init        = "odp_platform.cli.init_project:main"
odp-reset       = "odp_platform.cli.reset_project:main"
odp-transform   = "odp_platform.cli.transform_data:main"
odp-validate    = "odp_platform.cli.validate_data:main"
# ★ D5 新增 — 直接绑到 runtime_config.generator:main, 不立 cli/ 薄包装
odp-gen-config  = "odp_platform.runtime_config.generator:main"
```

⚠️ **设计点 (为什么 D5 的 entry-point 不走 `cli/` 子目录)**: D2-D4 的 4 个 entry-point 都在 `cli/<name>.py:main` 下, 因为它们**只**作为 CLI 存在, 必须有个 `cli/` 文件作为落点. `generator` 不一样——它既是反射工具(API), 又是 CLI 主流程, `main()` 函数自带就行, 再加一个 30 行 `cli/generate_config.py` 薄包装反而多一层维护. **API + CLI 都是它的本职**.

⚠️ **设计点 (为什么短命令也要给)**: legacy 项目最常见的痛是 "我得记住一长串模块路径". `odp-gen-config train` 一行能搞定, 在 CI yaml / Makefile / 报错信息修复指引里都好看得多. **入口的人体工程学跟代码质量一样重要**.

> **金句**: **"工程规矩立得早, 加固成本就低. 等子系统跑了半年才回头加这些约束, 改一处碰七处."**

## 0.6 第一阶段收尾的金句

> **金句**: **\"子系统从第一行业务代码开始就该有家——目录没建、常量没立、规矩没明, 就开始写 BaseConfig 是反过来的.\"**

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 1: 朴素第一版——argparse 串 60 个参数

D5 的核心架构是 **Pydantic 配置类 + 三源合并 + 字段元数据**. 但**直接抄过来很难体会\"为什么是这样\"**——所以阶段 1 我们故意先写一版\"看起来很自然\"的朴素实现, 等它**长歪了**再砸掉.

跟 D4 阶段 1 的剧本同款——先写一个朴素 `validate()`, 撞墙再重构.

## 1.1 任务设定: 复刻你的 legacy `yolo_train.py`

大概率你电脑上已经有一份这种 200 行的训练脚本(就是讲义资料包里的 `yolo_train.py`). 它长什么样?

```python
# 朴素第一版(几乎 1:1 复刻 legacy yolo_train.py)
import argparse
import yaml
from ultralytics import YOLO


def parse_args():
    p = argparse.ArgumentParser()

    # ---- 核心参数 ----
    p.add_argument("--model", default="yolov8n.pt")
    p.add_argument("--data",  default="data.yaml")
    p.add_argument("--epochs", default=50, type=int)
    p.add_argument("--batch",  default=16, type=int)
    p.add_argument("--imgsz",  default=640, type=int)
    p.add_argument("--device", default=None)

    # ---- 优化器 ----
    p.add_argument("--lr0", default=0.01, type=float)
    p.add_argument("--lrf", default=0.01, type=float)
    p.add_argument("--momentum", default=0.937, type=float)
    p.add_argument("--weight_decay", default=0.0005, type=float)
    p.add_argument("--optimizer", default="auto")
    p.add_argument("--cos_lr", action="store_true")

    # ---- 学习率预热 ----
    p.add_argument("--warmup_epochs", default=3.0, type=float)
    p.add_argument("--warmup_momentum", default=0.8, type=float)
    p.add_argument("--warmup_bias_lr", default=0.1, type=float)

    # ---- 数据增强 (颜色) ----
    p.add_argument("--hsv_h", default=0.015, type=float)
    p.add_argument("--hsv_s", default=0.7, type=float)
    p.add_argument("--hsv_v", default=0.4, type=float)

    # ---- 数据增强 (几何) ----
    p.add_argument("--degrees", default=0.0, type=float)
    p.add_argument("--translate", default=0.1, type=float)
    p.add_argument("--scale", default=0.5, type=float)
    p.add_argument("--shear", default=0.0, type=float)
    p.add_argument("--fliplr", default=0.5, type=float)

    # ---- 数据增强 (拼接) ----
    p.add_argument("--mosaic", default=1.0, type=float)
    p.add_argument("--mixup",  default=0.0, type=float)
    p.add_argument("--copy_paste", default=0.0, type=float)
    p.add_argument("--close_mosaic", default=10, type=int)

    # ---- 损失权重 ----
    p.add_argument("--box", default=7.5, type=float)
    p.add_argument("--cls", default=0.5, type=float)
    p.add_argument("--dfl", default=1.5, type=float)

    # ---- 输出 ----
    p.add_argument("--project", default=None)
    p.add_argument("--name",    default=None)
    p.add_argument("--exist-ok", action="store_true")
    p.add_argument("--save",     action="store_true", default=True)

    # ---- YAML 配置文件 ----
    p.add_argument("--config", default=None,
                   help="可选 YAML 配置, CLI 优先级最高")

    # ... 还有 20+ 个参数没列 ...
    return p.parse_args()


def main():
    args = parse_args()

    # 加载 YAML 作为默认值
    if args.config:
        with open(args.config) as f:
            yaml_cfg = yaml.safe_load(f) or {}
    else:
        yaml_cfg = {}

    # 合并 (CLI 覆盖 YAML 覆盖 default)
    merged = {**yaml_cfg, **{k: v for k, v in vars(args).items() if v is not None}}
    merged.pop("config", None)

    # 跑
    model = YOLO(merged.pop("model"))
    model.train(**merged)


if __name__ == "__main__":
    main()
```

跑得起来吗? **能跑**. 训练能成功吗? **大概率能**. 那有什么问题?

## 1.2 把它先跑一下

```bash
mkdir -p apps/platform/src/odp_platform/runtime_config
touch apps/platform/src/odp_platform/runtime_config/__init__.py

# 把上面的代码放到一个临时位置, 用 D4 产出的某个数据集试一下
python /tmp/yolo_train_naive.py --data <你的某个 data.yaml> --epochs 3 --batch 4
```

**能跑就行**——但跑通**不等于设计合理**. 跟 D4 阶段 1 同款节奏: 先看它哪儿丑.

## 1.3 🧱 撞墙①: 朴素方案的 4 个伤痛

跑完上面这版, 让我们诚实地数一下它的问题.

### 伤痛①: 字段三处定义, 加一个参数要改 3 处

假设你想加一个新参数 `freeze`(冻结前 N 层):

1. argparse 里加一行: `p.add_argument("--freeze", default=None, type=int)`
2. YAML 模板里加一行: `freeze: null`
3. `model.train()` 接受参数表里查一下: 是不是叫 `freeze`?

**3 处改动 + 1 次查文档**. 漏一处就跑不通——还不一定立刻发现, 可能跑到 train 中间 ultralytics 报\"unknown argument 'freez'\"才知道拼错了.

```
┌─────────────────────────────────────────────┐
│  argparse:   --freeze   default=None        │  ← 真相 A
│  YAML:       freeze: null                   │  ← 真相 B
│  ultralytics 接受参数表里有没有这个名?       │  ← 真相 C
└─────────────────────────────────────────────┘
                  ↓
       三个真相, 任何一个漂移 = bug
```

⚠️ **设计点 (这是 SSoT 在【参数】上失守的典型案例)**: D2 立路径 SSoT, D3 立词汇 SSoT, 这里我们需要**字段 SSoT**——\"一个字段的名字 / 类型 / 默认值 / 帮助文档\"应该只有一份真相. Pydantic 类天生就是为这种场景准备的——`Field(default=..., description=..., examples=...)` 一处定义, 处处复用.

### 伤痛②: 没有验证, 错的输入静默通过

朴素方案信任用户. 看几个真实坑:

```bash
# 用户填了非 32 倍数的 imgsz
python /tmp/yolo_train_naive.py --imgsz 649      # ultralytics 会自动补到 672, 不告诉用户
# → 训练 100 轮, 用户以为自己跑的是 649, 实际是 672

# 用户填了 0 批
python /tmp/yolo_train_naive.py --batch 0        # ultralytics 给个奇怪报错
# → "ZeroDivisionError"——栈里完全看不出是 batch=0 引起的

# 用户拼错 device
python /tmp/yolo_train_naive.py --device cpuu    # PyTorch 报 "expected CUDA device, got cpuu"
# → 用户花 5 分钟才意识到自己拼错了
```

这些都是**\"入口处该拒的\", 不是\"运行到一半才崩的\"**——验证应该发生在数据进配置对象的那一刻, 而不是延迟到 ultralytics 的内部逻辑里.

Pydantic 自带这套机制: `Field(ge=32, ...)`, `@field_validator`——验证规则跟字段定义在同一个地方, 错误信息精确指向哪个字段、哪个值、为什么不合法.

### 伤痛③: 跑完不知道 `lr0=0.001` 是哪儿来的

```bash
python /tmp/yolo_train_naive.py --config /path/to/train.yaml --lr0 0.001 --epochs 200
# 日志: lr0=0.001, epochs=200, batch=16, optimizer=auto, ...
```

跑完看日志, 一片**\"它就是这样\"**——没人告诉你:

- `lr0=0.001` 是 CLI 给的(你刚才敲的)
- `epochs=200` 也是 CLI 给的
- `batch=16` 是 YAML 给的
- `optimizer=auto` 是默认值

三个月后你回看 logs/yolov8n_20260518.log, 想复现这次跑法——\"我当时 CLI 敲了啥? YAML 改过哪几个字段?\" **猜不出来**.

更糟的场景: 实习生说\"师兄, 这个 lr0 不对劲, 我改成 0.01 了\". 你打开 yaml, `lr0: 0.005`——\"他改的是 CLI 还是 yaml? 还是默认值?\" **完全说不清**.

⚠️ **设计点 (溯源是配置系统的灵魂)**: 配置不是\"参数表\", 是\"决策记录\"——每个字段的最终值都该带一条\"我是谁、从哪来、覆盖了谁\"的元数据. **chain 链表 = 配置溯源, 跟 git 提交链是一个思路**.

### 伤痛④: YAML 模板是手维护的, 配置即文档失效

你给学员一份 `train.yaml`:

```yaml
mosaic: 1.0      # ?
mixup: 0.0       # ?
hsv_h: 0.015     # ?
```

学员第一反应: \"`mosaic: 1.0` 是什么? 范围 0-1 还是 0-10? 调到多少合适?\" **没注释, 等于没文档**.

朴素方案下你得**手写注释**:

```yaml
mosaic: 1.0      # Mosaic 增强概率(0-1, 1.0 表示总是开启)
mixup: 0.0       # Mixup 增强概率(0-1, 0 表示禁用)
hsv_h: 0.015     # HSV 色调扰动强度(0-1)
# ... 60 行下来 ...
```

然后过两周加了个新参数, 忘改 YAML 模板——**注释和代码漂移**. 经典.

**根本上**, 这些字段元数据(范围、含义、示例)就应该跟字段本身定义在**同一个地方**, 由代码自动产出 YAML 模板. 这就是 Pydantic `Field` 的 `description` / `examples` / `json_schema_extra` 用武之地.

## 1.4 这版不 commit

⚠️ **设计点 (反面教材代码不进 git)**: 跟 D4 阶段 1 同款纪律——\"演示\"代码不该污染 git history.

```bash
# /tmp/yolo_train_naive.py 别 git add——它在我们文件系统外, 演完就丢
```

> **金句**: **\"代码不止靠'写得对'传达意图——'有没有进 git'本身也是意图的一部分.\"**

## 1.5 朴素方案的伤痛 → D5 的对应设计

朴素方案的伤痛, 都有对应的工业级解法. 把它们对照排一下, 就是 D5 后面 7 个阶段的 roadmap. 4 个核心伤痛朴素方案直接暴露的, 加 3 个 "部署后才感受到必要" 的伤痛 (用户预览困难、复现困难、可观测困难), 一并在设计里解决.

| 伤痛 | D5 对应解法 | 在哪一阶段 |
|---|---|---|
| ① 字段散落三处 | Pydantic `Field` 一次定义 + ClassVar 扩展点 | 阶段 2 |
| ② 没有验证 | `Field(ge=...)` + `@field_validator` + `extra="forbid"` | 阶段 2-3 |
| ③ 没有溯源 | `ConfigMerger` + `ConfigMetadata` 链表 | 阶段 5 |
| ④ YAML 模板手维护 | `ConfigGenerator` 从 Field 反射出 YAML | 阶段 6 |
| ⑤ YAML 不存在时静默生成默认 | fail-fast + 修复指引 | 阶段 4 |
| ⑥ 调参前无法预览合并结果 | `ConfigMerger.preview()` + `build_*_config(dry_run=True)` | 阶段 5 + 7 |
| ⑦ 实验跑完无法复现 | `to_audit_snapshot()` / `from_audit_snapshot()` | 阶段 2 |
| ⑧ 运维渠道无法追踪 | `to_audit_log()` 结构化 JSON, 进 ELK | 阶段 5 |

⚠️ **设计点 (为什么把"扩展性接口"也列进伤痛)**: 朴素方案撞墙撞的是"现在跑不顺"的问题. 但**"现在跑得通 ≠ 部署后跑得稳"**——预览 / 复现 / 审计这三件事在朴素方案里完全缺失, 上线后才会感觉到痛. 一份能用的配置子系统, 必须把这三件事**从一开始就纳入设计**, 而不是 v1.1 再补.

> **金句**: **\"朴素方案不是错, 是伤痛延迟到运行时才爆. 工程化的本质是把痛苦提前到设计阶段——同时把'部署后才痛'的也一并提前."**

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 2: BaseConfig——Pydantic 入场

阶段 2 一次把**配置子系统的骨架**写完: `BaseConfig`——所有训练 / 验证 / 推理模式共享的字段, 带验证、带元数据、带工具方法.

跟 D4 阶段 2 同款思路——**先把骨架立起来, 再阶段 3 起往里塞特定模式的字段**.

## 2.1 选型: 为什么 Pydantic, 不是 dataclass / TypedDict / 纯字典?

> 🤔 **思考题**: D2 用 dataclass 装 `DatasetPipeline` 的参数, D3 / D4 用 `@dataclass(frozen=True)` 装 `DatasetSnapshot`——为什么 D5 突然换 Pydantic?

**答**: 因为 D5 的核心场景跟 D2-D4 不一样.

| 场景 | D2/D3/D4 的 dataclass 够 | D5 需要 Pydantic |
|---|---|---|
| 类型注解 | ✅ | ✅ |
| 默认值 | ✅ | ✅ |
| 字段元数据(description/examples) | ❌ 没有标准位 | ✅ `Field(...)` |
| 运行时验证(类型 / 范围 / 自定义) | ❌ 要自己写 `__post_init__` | ✅ `@field_validator` / `Field(ge=...)` |
| 嵌套验证 + 友好错误信息 | ❌ 错误信息很丑 | ✅ `ValidationError` 自带定位 |
| 从 dict / yaml 反序列化 | ❌ 手动 | ✅ `Model(**data)` |
| 字段反射(动态遍历字段) | ⚠️ `fields()` 但元数据缺 | ✅ `model_fields` 含全部元数据 |

D2-D4 装的是**内部产出**——程序自己生成, 自己消费, 类型基本不会错, 写校验是过度工程. D5 装的是**用户输入**——YAML / CLI 都是不可信源, 必须验证. **Pydantic 是为这场景生的**.

⚠️ **设计点 (不要为了一致性强行 dataclass)**: SSoT 是\"一种问题一个解法\", 不是\"全项目所有数据类都得一样\". D5 的需求跟 D2-D4 不同, 用不同工具是对的——**用错才丢一致性, 不是用对了**.

⚠️ **依赖管理小坑**: Pydantic v2 跟 v1 API 差别大. 本讲义所有代码基于 **Pydantic v2**(`BaseModel` / `model_validator` / `field_validator`). 在 `apps/platform/pyproject.toml` 的 dependencies 里加:

```toml
dependencies = [
    # ... D2-D4 已有 ...
    "pydantic>=2.5,<3",     # ★ D5 新增
    "pyyaml>=6.0",          # ★ D5 新增(loaders.py 用)
]
```

跑 `pip install -e ./apps/platform --force-reinstall --no-deps` 让依赖生效.

> **金句**: **\"工具选型不是 '保持一致', 是 '匹配场景'. 强行一致 = 把锤子用到拧螺丝上.\"**

## 2.2 BaseConfig 装什么? 4 类字段一次列清

不要打开编辑器就开始码. 先列清单——BaseConfig 至少要装哪些字段?

**原则**: BaseConfig 只装**真正训练 / 验证 / 推理通用**的字段. 训练特有(epochs / lr0) → `train.py`; 验证特有(split / conf) → `val.py`. 通用的是哪些?

参考 ultralytics 文档, 整理出 4 类:

```
BaseConfig (共享层)
├── 核心参数:        model, data
├── 输入配置:        batch, imgsz, workers, cache, rect
├── 设备配置:        device, amp
├── 输出配置:        project, name, exist_ok, save
└── 基础设置:        verbose, seed, deterministic
```

15 个字段——少而精, 因为再多就该往子类挪了.

⚠️ **设计点 (划分 BaseConfig vs 子类的判据)**: 一个字段属于 BaseConfig, 当且仅当它满足两条:

1. **训练 / 验证 / 推理都用**——比如 `imgsz`, 三种模式都接受这个参数.
2. **语义在三种模式下基本一致**——比如 `device`, 都是\"哪个设备跑\".

反例: `conf`(置信度阈值)——验证 / 推理用, 训练**不用**. 不放 BaseConfig, 放 val.py / infer.py.

反例: `batch`——三种模式都用, 但**验证时的 batch 跟训练时的 batch 语义不同**(训练算梯度, 验证就是吞吐). 这里我们判断为\"语义足够近\", 放 BaseConfig, 由子类的字段元数据补充各自语境.

⚠️ **设计点 (注意 task 不在 BaseConfig)**: `task`(detect / segment) 我们**故意没放 BaseConfig**, 放在 `train.py` / `val.py` 各自一份. 为什么? 因为不同模式对 task 的处理不一样:

- 训练: task 决定从哪个 ultralytics 模板加载模型
- 验证: task 只用于日志和实验目录组织(`.val()` 会从模型自动推断)
- 推理: 跟验证类似

\"看起来都是 task, 但消费方式不同\"——这种字段**不该放共享层**, 强行共享反而约束子类. 跟 D4 的 \"task_type 三级优先级\" 是同源教训.

## 2.3 字段元数据的 5 个槽位

BaseConfig 的字段不是\"光秃秃的类型注解 + 默认值\". 每个字段都带 5 类元数据, 装在 `Field` 的 `json_schema_extra` 里:

```python
batch: Union[int, float] = Field(
    default=16,
    description="批次大小",
    json_schema_extra={
        "group":   "输入配置",                              # ← 槽位 1
        "examples": [8, 16, 32, -1, 0.7],                  # ← 槽位 2
        "tips": [                                          # ← 槽位 3
            "int: 固定批次大小(如 16)",
            "-1: 自动批次(使用约 60% 显存)",
            "0.0-1.0: 显存利用率(如 0.7 = 70% 显存)",
            "显存不足时建议: 8GB → 8-16, 16GB → 32-64",
        ],
        "yaml_comment": "批次大小(int=固定值, -1=自动, 0-1=显存利用率)",   # ← 槽位 4
        "sensitive": False,                                # ← 槽位 5 (默认 False, 可省略)
    },
)
```

5 个槽位的用途:

| 槽位 | 类型 | 用在哪 |
|---|---|---|
| `group` | str | YAML 模板生成时按这个分章节 |
| `examples` | List | YAML 模板里以\"`# 示例: 8, 16, 32...`\"输出 |
| `tips` | List[str] | YAML 模板里以\"`# 提示:`\"加几条小提示输出 |
| `yaml_comment` | str | YAML 模板里字段上方那一行注释 |
| `sensitive` | bool | True 时该字段在 mask / 报告里显示成 `***` (默认 False, 可省略) |

⚠️ **设计点 (`sensitive` 默认 False, 99% 字段不写)**: 训练配置 75+ 字段里, 真正可能敏感的就 `data`(可能是 S3 URL 含 access_key) / `project`(可能是内部项目代号) 这种少数. 默认 False 让现有字段定义不动, 真有敏感字段时**一行 metadata 启用**. 配套的 `mask_sensitive_dump()` / merger 自动 mask 接口在 2.5 立, 这一节先把元数据槽位留好.

⚠️ **设计点 (为什么不用 description 直接当 yaml_comment?)** Pydantic 的 `description` 字段是\"给程序员看的\"(API 文档、IDE 提示), 写得稍长一点没问题. `yaml_comment` 是\"给最终用户看的\", 一行内必须读懂. **两种受众, 两个字段**:

```python
description="批次大小"                                              # ← 给程序员: 简短一句
yaml_comment="批次大小(int=固定值, -1=自动, 0-1=显存利用率)"          # ← 给用户: 含选项说明
```

⚠️ **设计点 (为什么 examples / tips 是 List 不是 str?)** 因为列表能保留\"分点结构\"——`tips` 在 YAML 里输出为多行 `# - tip1\n# - tip2`, 阅读体验比一坨字符串好. 同时 list 也方便后续拓展成 HTML / JSON 报告里的列表项.

> **金句**: **\"字段元数据的设计就是\"这个字段服务谁\"的提问——每加一个槽位前先问'哪个角色会读这个'.\"**

## 2.4 验证器: Pydantic 的两种武器

BaseConfig 里, 验证分两层:

**层 1**: `Field(ge=..., le=..., gt=...)` 内置约束(数值范围 / 字符串长度)——简单直白, 写在字段定义里.

**层 2**: `@field_validator` / `@model_validator` 自定义验证——复杂规则 / 跨字段.

举几个 BaseConfig 里的例子:

### 例 1: imgsz 不是 32 倍数 → 警告而不是 raise

```python
@field_validator("imgsz")
@classmethod
def _validate_imgsz(cls, v: int) -> int:
    """验证图像尺寸(建议 32 的倍数, 但不强制)"""
    if v % 32 != 0:
        warnings.warn(
            f"imgsz={v} 不是 32 的倍数. "
            f"虽然可以运行, 但建议使用 32 的倍数(如 640, 672, 704)以获得最佳性能.",
            UserWarning,
        )
    return v
```

⚠️ **设计点 (warn vs raise 的判据)**: ultralytics 本身会自动补到 32 倍数——所以 imgsz=649 **能跑**, 只是用户跑的实际不是 649 而是 672. 这种\"能跑但跟预期不一致\"的情况**该警告不该 raise**——raise 会让边缘场景用户骂街(\"我就想跑 640!\"), warn 既提醒了又不挡路.

### 例 2: batch 既能是 int 也能是 float, 语义不一样

```python
@field_validator("batch", mode="before")
@classmethod
def _validate_batch(cls, v: Any) -> Union[int, float]:
    """验证批次大小格式"""
    if isinstance(v, bool):
        raise TypeError("batch 不能是 bool 类型")    # bool 是 int 子类, 单独防一下

    if isinstance(v, int):
        if v == -1:
            return v                                  # 自动批次
        if v <= 0:
            raise ValueError("batch 为 int 时必须为 -1(自动) 或 >= 1(固定值)")
        return v

    # float: 显存利用率
    v_float = float(v)
    if not (0.0 < v_float <= 1.0):
        raise ValueError(
            f"batch 为 float 时必须在 (0, 1] 范围内, 表示显存利用率. "
            f"例如 0.7 表示使用 70% 显存, 当前值: {v_float}"
        )
    return v_float
```

⚠️ **设计点 (为什么单独防 bool?)** Python 里 `bool` 是 `int` 的子类——`isinstance(True, int)` 返回 `True`. 如果不防, 用户写 `batch: true`(YAML 解析成 Python `True`), 走 `isinstance(v, int)` 分支, 然后 `True == -1` 是 False, `True <= 0` 是 False, **静默通过当成 1 用**. 实际语义是\"显存利用率 100%\" 还是 \"批次大小 1\"? 都不该是. 单独 raise 把错往用户脸上糊.

⚠️ **设计点 (为什么 `_validate_batch` 用 `mode=\"before\"`?)** `field_validator` 默认是 `mode=\"after\"`——在 Pydantic 完成类型转换**之后**才跑. 但 `batch` 的字段类型是 `Union[int, float]`, 而 `bool` 是 `int` 的子类: 若让 Pydantic 先按 `Union[int, float]` 处理 `True`, 它很可能已经把 `True` 归一成了 `1`, 等验证器拿到手时 `isinstance(v, bool)` 已经是 `False`——上面那道 bool 守卫**形同虚设**, `batch: true` 又静默变回 `batch=1`. 改成 `mode=\"before\"`, 验证器拿到的就是**用户写进 YAML 的原始值**, `True` 还是 `True`, bool 守卫才真正拦得住. 函数签名也相应改成 `v: Any`——`before` 模式下参数还没规范化, 标 `Union[int, float]` 是假象.

> **判据**: 验证逻辑**依赖原始输入的类型/形态**(这里是\"用户到底写没写 bool\")时, 用 `mode=\"before\"`; 只需在**已规范化的值**上做范围 / 跨字段检查时, 用 `mode=\"after\"`. 例 1 的 `imgsz`、例 3 的跨字段验证都属于后者, 保持默认 `after` 即可.

### 例 3: 跨字段验证 — workers vs batch 的合理性

```python
@model_validator(mode="after")
def _cross_field_validation(self) -> "BaseConfig":
    """跨字段验证"""
    # workers 远大于 batch 是资源浪费(警告不阻止)
    if isinstance(self.batch, int) and self.batch > 0:
        if self.workers > self.batch * 2:
            warnings.warn(
                f"workers={self.workers} 远大于 batch={self.batch}, "
                f"可能造成资源浪费. 建议 workers <= batch * 2",
                UserWarning,
            )

    return self
```

⚠️ **设计点 (`mode="after"` 的含义)** Pydantic v2 的 `model_validator` 有两种 mode:

- `mode="before"`: 在 Pydantic 验证之前跑——拿到的是 raw dict, 字段可能还没转换类型
- `mode="after"`: 在 Pydantic 验证之后跑——拿到的是已验证的实例, 字段都是正确类型

跨字段验证几乎都用 `after`——前面字段已经规范化, 这里安心比较.

⚠️ **设计点 (为什么 batch=-1 / batch=float 时跳过这个检查?)** `batch=-1` 时 `batch * 2 = -2`, `workers > -2` 永远 True, 误报警告. `batch=0.7` 时 `self.batch > 0` 守卫挡掉——float 模式下 workers 跟显存利用率比较没意义.

**写守卫表达式时永远要想边界**——这是 Pydantic 跨字段验证常见的踩坑点.

> **金句**: **\"warn 跟 raise 的区别不是'软硬', 是'谁应该决定如何处理'. 警告 = 我提示你, 你定; raise = 我拒绝继续, 你必须改.\"**

### 例 4: 第三道闸门 — `extra="forbid"` 拒绝拼错的字段名

字段级验证、跨字段验证管的都是\"值对不对\". 还有一类错它们都管不到——**字段名本身拼错了**.

用户在 `train.yaml` 里把 `epochs` 敲成了 `epchs: 300`. Pydantic v2 **默认 `extra=\"ignore\"`**——这个多出来的 `epchs` 会被**静默丢弃**, `epochs` 仍然是默认值 100. 用户以为自己跑了 300 轮, 实际只跑了 100. 这正是阶段 1 \"伤痛②\" 的翻版, 而且更隐蔽: 值没错, 是名字错了, 连 `@field_validator` 都没机会介入.

解法是给 BaseConfig 加一行**模型级配置**:

```python
from pydantic import BaseModel, ConfigDict

class BaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ...
```

`extra=\"forbid\"` 让 Pydantic 一遇到未定义字段就**直接 raise**——`epchs` 进不了配置对象, 用户第一时间就看到 `Extra inputs are not permitted` 并精确指到 `epchs`. 子类 `YOLOTrainConfig` / `YOLOValConfig` 继承这条配置, 不用重复写.

⚠️ **设计点 (为什么 runtime_config 子系统适合 `forbid`?)** `extra=\"forbid\"` 不是哪都该开. 它适合**字段集封闭**的场景——YOLO 的训练 / 验证参数就是 ultralytics 定死的那一批, 不存在\"用户要往配置里塞自定义键\"的合理需求. **字段集封闭 + 输入不可信 = `forbid` 的主场**. 反过来, 如果一个模型本来就允许动态扩展字段, 开 `forbid` 就会误伤. runtime_config 子系统两条都占, 该开.

⚠️ **设计点 (`forbid` 与三源合并的配合)** 阶段 6 的 `ConfigMerger` 会把\"默认值 + YAML + CLI\"合成一个 dict 再 `config_class(**merged)`. 默认值来自 `model_fields`(天然干净), CLI 经 `CLILoader` 过滤, **唯一可能混进脏键的就是手写的 YAML**——而 `forbid` 正好在这最后一道 `config_class(**merged)` 把它拦下. 三源合并器和 `forbid` 是天生一对.

> **金句**: **\"`extra=\"ignore\"` 对'程序内部数据'是宽容, 对'用户手写配置'是纵容——封闭字段集就该用 `forbid`, 把拼写错误挡在配置对象的门外.\"**

## 2.5 工具方法: 配置类要对外提供哪些能力?

光定义字段不够. BaseConfig 至少要对外提供 5 个能力:

```python
# === 给训练框架用 ===
def to_ultralytics_kwargs(self) -> Dict[str, Any]:
    """转换为 Ultralytics 可消费的 kwargs (过滤 None + 移除框架级参数)"""

# === 给 generator / 反射用 ===
def get_field_groups(self) -> Dict[str, List[str]]:
    """按 group 元数据分组 (供 generator 写 YAML 用)"""

def get_field_metadata(self, field_name: str) -> Dict[str, Any]:
    """拿单个字段的全部元数据 (供 generator 写注释用)"""

# === 给实验复现用 ===
def to_audit_snapshot(self) -> Dict[str, Any]:
    """返回可序列化的完整快照 (含类标识 + frozen 时间戳), 实验数据库存它"""

@classmethod
def from_audit_snapshot(cls, snapshot: Dict[str, Any]) -> "BaseConfig":
    """从快照恢复实例 (三个月后能复现训练)"""

# === 给敏感字段 mask 用 ===
def mask_sensitive_dump(self) -> Dict[str, Any]:
    """model_dump() 但 sensitive 字段值替换成 '***' (进日志前调)"""
```

**5 个方法对应 5 类下游受众**——ultralytics 框架、generator 模板生成器、实验数据库、敏感字段 mask 通道. 加上 Pydantic 自带的 `model_dump()` (通用序列化), BaseConfig 一共 6 个对外能力, 各管一摊互不替代.

### `to_ultralytics_kwargs`: 为什么不直接 `model_dump()`?

朴素思路: `model.train(**config.model_dump())`. 不行, 因为:

1. **None 值**: Pydantic 默认会包含 None 字段, 但 ultralytics 看到 `device=None` 可能行为不一致——**显式过滤**.
2. **框架级参数**: 比如 `verbose` 是 D5 框架自己的日志开关, 不该传给 ultralytics(它有自己的 `verbose` 字段, 但语义不一样).

最直白的写法是直接 pop:

```python
def to_ultralytics_kwargs(self) -> Dict[str, Any]:
    d = self.model_dump(exclude_none=True)   # 过滤 None
    d.pop("verbose", None)                    # 框架级参数
    return d
```

但马上有个问题: 验证模式里 `task` 也是框架自己用的(`model.val()` 会从模型权重自动推断 task, 不需要外部传), 所以 `val.py` 也得 pop 掉一个 `task`. 如果用上面这种死写法, `YOLOValConfig` 就只能**override 整个 `to_ultralytics_kwargs` 方法**——基类方法体被复制一遍只为多 pop 一个字段, 子类越多重复越多.

更好的做法: 把\"哪些字段是框架级、不该传给 ultralytics\"抽成一个 **`ClassVar` 集合**, 方法本身只读这个集合; 子类要扩展, 只改这一行变量, 不碰方法体. **D5 正式版采用这个写法**:

```python
from typing import ClassVar

class BaseConfig(BaseModel):
    # 框架级字段: 只在 D5 框架内部使用, 不传给 ultralytics
    FRAMEWORK_ONLY_FIELDS: ClassVar[set[str]] = {"verbose"}

    def to_ultralytics_kwargs(self) -> Dict[str, Any]:
        d = self.model_dump(exclude_none=True)
        for f in self.FRAMEWORK_ONLY_FIELDS:
            d.pop(f, None)
        return d

# val.py 里(阶段 3 会写到)——子类只改一行变量:
class YOLOValConfig(BaseConfig):
    FRAMEWORK_ONLY_FIELDS: ClassVar[set[str]] = BaseConfig.FRAMEWORK_ONLY_FIELDS | {"task"}
```

⚠️ **设计点 (`ClassVar` 不是配置字段)** `FRAMEWORK_ONLY_FIELDS` 用 `ClassVar` 标注后, Pydantic 就**不会**把它当成一个配置字段——它不会出现在 `model_fields` 里, 不会被 `model_dump()` 导出, 也不受上面 `extra=\"forbid\"` 的约束(`forbid` 只管\"传进来的数据\", 不管类属性). 它就是一个普通的类级常量. 子类重新赋值时**再标一次 `ClassVar`** 是稳妥写法, 避免 Pydantic 把无注解的赋值误判.

> **金句**: **\"子类扩展点设计成'改一行数据'还是'重写一个方法', 直接决定这个基类好不好继承——能用数据表达的差异, 别用代码重复表达.\"**

### `get_field_groups`: 反射字段的 group 元数据

```python
def get_field_groups(self) -> Dict[str, List[str]]:
    """获取字段分组. {group_name: [field_names]}"""
    groups: Dict[str, List[str]] = {}
    for field_name, field_info in self.__class__.model_fields.items():
        extra = field_info.json_schema_extra or {}
        group = extra.get("group", "其他") if isinstance(extra, dict) else "其他"
        groups.setdefault(group, []).append(field_name)
    return groups
```

⚠️ **设计点 (`json_schema_extra` 的两种可能类型)** Pydantic v2 允许 `json_schema_extra` 是 dict 或 callable. 我们的约定是 dict, 但要防御性地用 `isinstance(extra, dict)` 守一下——万一未来某个字段写成 callable, 不要直接崩.

### `get_field_metadata`: 拿单字段全部元数据

```python
def get_field_metadata(self, field_name: str) -> Dict[str, Any]:
    """获取字段的完整元数据"""
    if field_name not in self.__class__.model_fields:
        raise ValueError(f"字段 '{field_name}' 不存在")

    field_info = self.__class__.model_fields[field_name]
    metadata: Dict[str, Any] = {
        "description":  field_info.description,
        "default":      field_info.default,
        "examples":     [],
        "tips":         [],
        "yaml_comment": field_info.description,    # 默认 fallback 到 description
        "group":        "其他",
    }
    if isinstance(field_info.json_schema_extra, dict):
        metadata.update(field_info.json_schema_extra)

    return metadata
```

⚠️ **设计点 (默认值 fallback 的链)** `yaml_comment` 没写时 fallback 到 `description`, `description` 也没写就用空字符串——**多层 fallback 让\"漏写元数据\"不会直接挂掉**, 只是模板生成的注释稍弱.

### `to_audit_snapshot` / `from_audit_snapshot`: 实验复现接口

朴素思路: `model_dump()` 不就够了吗? 不够. **复现需要类标识**——三个月后从数据库捞出来一个 dict, 不知道用 `YOLOTrainConfig` 还是 `YOLOValConfig` 反序列化. 快照必须自描述:

```python
def to_audit_snapshot(self) -> Dict[str, Any]:
    """返回可序列化的完整快照, 用于实验复现.

    ★ 跟其他 dump 方法的区别:
       - model_dump():            只有值, 没类标识 → 反序列化时不知用哪个类
       - to_ultralytics_kwargs(): 过滤后的运行参数, 不能恢复完整配置
       - to_audit_snapshot():     值 + 类标识 + 时间戳, 完全可复现
    """
    return {
        "config_class":  self.__class__.__name__,
        "config_module": self.__class__.__module__,
        "frozen_at":     datetime.now().isoformat(timespec="seconds"),
        "values":        self.model_dump(),
    }

@classmethod
def from_audit_snapshot(cls, snapshot: Dict[str, Any]) -> "BaseConfig":
    """从快照恢复, 类名不匹配 raise."""
    expected = cls.__name__
    got = snapshot.get("config_class")
    if got != expected:
        raise ValueError(
            f"快照来自 {got!r}, 不能恢复到 {expected!r}. "
            f"请用 {got}.from_audit_snapshot(snapshot)."
        )
    return cls(**snapshot["values"])
```

⚠️ **设计点 (`from_audit_snapshot` 走完整 Pydantic 验证)** 不是 `__new__` 直接装值, 而是 `cls(**values)`. **复现时也跑一遍验证**——半年后字段定义变了 (比如 `mosaic` 范围从 [0,1] 改成 [0,2]), 老快照会立刻报错. 这比静默接受更安全, 你想复现就得正面面对配置定义的演进.

⚠️ **设计点 (没存 source chain)** 快照只存"最终字段值", 不存"哪个值是 yaml 还是 cli 给的". 复现的需求是"跑出来同样结果", 跟"当初谁配的"无关. 想存 source chain 走 `merger.to_audit_log()` (阶段 5 立), 那是另一个独立的审计产物.

### `mask_sensitive_dump`: 敏感字段的 mask 通道

2.3 的字段元数据立了 `sensitive` 槽位, 这里立配套的 mask 方法:

```python
SENSITIVE_MASK: ClassVar[str] = "***"

def mask_sensitive_dump(self) -> Dict[str, Any]:
    """model_dump() 但 sensitive 字段值替换成 SENSITIVE_MASK.

    用法:
        # 进日志前 mask
        safe = config.mask_sensitive_dump()
        logger.info(f"config: {safe}")

        # 进数据库存原值 (不 mask)
        db.save(config.model_dump())
    """
    dump = self.model_dump()
    for field_name, field_info in self.__class__.model_fields.items():
        extra = field_info.json_schema_extra or {}
        if not isinstance(extra, dict):
            continue
        if not extra.get("sensitive"):
            continue
        if dump.get(field_name) is None:
            continue                              # None 不 mask, 那会误导
        dump[field_name] = self.SENSITIVE_MASK
    return dump

@classmethod
def sensitive_field_names(cls) -> set[str]:
    """返回标了 sensitive=True 的字段名 (供 merger 自动 mask 用)."""
    result: set[str] = set()
    for name, field_info in cls.model_fields.items():
        extra = field_info.json_schema_extra or {}
        if isinstance(extra, dict) and extra.get("sensitive"):
            result.add(name)
    return result
```

⚠️ **设计点 (`SENSITIVE_MASK` 用 ClassVar, 子类可改)** 默认 `"***"` 够用. 子类要 `"<REDACTED>"` / `"[hidden]"` 重新赋一行类属性即可——跟 `FRAMEWORK_ONLY_FIELDS` 同款扩展点设计.

⚠️ **设计点 (None 值的 sensitive 字段不 mask)** `data: None` 是合法默认, 不该 mask 成 `"***"`——那会让用户以为"数据集路径有但被隐藏了". **None 是真实信息, 替换反而误导**.

⚠️ **设计点 (Pydantic 的 `__repr__` 不 mask)** 这是**明确选择不做**的事. `print(config)` / `f"{config}"` 走 Pydantic 默认实现, 会暴露 sensitive 字段原值. 改 `__repr__` 会让 debug / IDE inspect 看不到真实值, 排查异常困难. **mask 是显式调用 `mask_sensitive_dump()` 的事, 不强加给所有打印**——边界划清.

## 2.6 BaseConfig 完整代码

`apps/platform/src/odp_platform/runtime_config/base.py`:

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : base.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统基础模型——BaseConfig
"""运行配置子系统基础模块.

只装 BaseConfig: 所有模式(训练 / 验证 / 推理)共享的字段.
专属字段去 train.py / val.py.

★ 注意: legacy 里的 ProjectConfig 已删除——
  paths.py 才是项目路径的【唯一真相来源】(D2 立的 SSoT 纪律).
  service 层直接 from odp_platform.common.paths import LOGGING_DIR, ... 即可.
"""
from __future__ import annotations

import warnings
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ============================================================
# BaseConfig: 所有模式共享的基础配置
# ============================================================

class BaseConfig(BaseModel):
    """所有模式(训练 / 验证 / 推理)共享的基础配置.

    字段分组:
        - 核心参数: model, data
        - 输入配置: batch, imgsz, workers, cache, rect
        - 设备配置: device, amp
        - 输出配置: project, name, exist_ok, save
        - 基础设置: verbose, seed, deterministic
    """

    # extra="forbid": 拒绝 YAML / CLI 里拼错的字段名(详见 2.4 例 4)
    model_config = ConfigDict(extra="forbid")

    # 框架级字段: 只在 D5 框架内部使用, to_ultralytics_kwargs() 会把它们剔除,
    # 不传给 ultralytics. 子类(如 YOLOValConfig)可在此基础上并入更多字段.
    FRAMEWORK_ONLY_FIELDS: ClassVar[set[str]] = {"verbose"}

    # 敏感字段 mask 时的替代字符串. 子类可重新赋值定制.
    SENSITIVE_MASK: ClassVar[str] = "***"

    model: Optional[str] = Field(
        default=None,
        description="模型文件路径",
        json_schema_extra={
            "group": "核心参数",
            "examples": ["yolo11n.pt", "yolo11s.pt", "path/to/custom.pt"],
            "tips": [
                "支持 .pt 权重文件或 .yaml 配置文件",
                "官方模型: yolo11n/s/m/l/x.pt (n 最快, x 最准)",
                "训练时如未指定, 默认从头训练",
            ],
            "yaml_comment": "模型文件路径(.pt 或 .yaml)",
        },
    )

    data: Optional[str] = Field(
        default=None,
        description="数据集配置文件路径",
        json_schema_extra={
            "group": "核心参数",
            "examples": ["data.yaml", "rsod.yaml", "configs/datasets/safety.yaml"],
            "tips": [
                "YAML 文件定义数据集路径和类别信息",
                "必须包含: path, train, val, names",
                "如果只给数据集名(如 'rsod'), 框架会通过 paths.dataset_yaml_path() 解析",
            ],
            "yaml_comment": "数据集配置文件(D3 odp-transform 产出的那份 yaml)",
        },
    )

    # -------- 输入配置 --------

    batch: Union[int, float] = Field(
        default=16,
        description="批次大小",
        json_schema_extra={
            "group": "输入配置",
            "examples": [8, 16, 32, -1, 0.7],
            "tips": [
                "int: 固定批次大小(如 16)",
                "-1: 自动批次(使用约 60% 显存)",
                "0.0-1.0: 显存利用率(如 0.7 = 70% 显存)",
                "显存不足时建议: 8GB → 8-16, 16GB → 32-64",
            ],
            "yaml_comment": "批次大小(int=固定值, -1=自动, 0-1=显存利用率)",
        },
    )

    imgsz: int = Field(
        default=640,
        ge=32,
        description="输入图像尺寸",
        json_schema_extra={
            "group": "输入配置",
            "examples": [320, 480, 640, 800, 1280],
            "tips": [
                "推荐使用 32 的倍数(640, 672, 704...)",
                "更大尺寸 = 更高精度 + 更多显存 + 更慢速度",
                "工业检测推荐: 640-800",
                "小目标检测推荐: 1280+",
            ],
            "yaml_comment": "输入图像尺寸(像素)",
        },
    )

    workers: int = Field(
        default=8,
        ge=0,
        description="数据加载工作线程数",
        json_schema_extra={
            "group": "输入配置",
            "examples": [0, 4, 8, 16],
            "tips": [
                "多线程加速数据加载",
                "推荐: CPU 核心数的 1-2 倍",
                "Windows 可能需要设为 0",
                "过高会导致内存占用过多",
            ],
            "yaml_comment": "数据加载线程数",
        },
    )

    cache: Union[bool, str] = Field(
        default=False,
        description="数据缓存策略",
        json_schema_extra={
            "group": "输入配置",
            "examples": [False, True, "ram", "disk"],
            "tips": [
                "False: 不缓存(默认)",
                "True/'ram': 缓存到内存(快但占内存)",
                "'disk': 缓存到磁盘(节省内存但慢)",
                "小数据集推荐 ram, 大数据集推荐 disk",
            ],
            "yaml_comment": "数据缓存(False/True/ram/disk)",
        },
    )

    rect: bool = Field(
        default=False,
        description="矩形训练(最小填充)",
        json_schema_extra={
            "group": "输入配置",
            "examples": [False, True],
            "tips": [
                "True: 减少填充, 提升训练速度",
                "推理时自动启用",
                "可能轻微影响精度",
            ],
            "yaml_comment": "是否启用矩形训练",
        },
    )

    # -------- 设备配置 --------

    device: Optional[Union[int, str, List[Union[int, str]]]] = Field(
        default=None,
        description="训练设备",
        json_schema_extra={
            "group": "设备配置",
            "examples": [0, "0", "cpu", "mps", [0, 1], "0,1"],
            "tips": [
                "None: 自动选择(优先 GPU)",
                "int: GPU 编号(0, 1, 2...)",
                "'cpu': 使用 CPU",
                "'mps': Mac M1/M2 GPU",
                "[0,1] 或 '0,1': 多 GPU 训练",
                "-1: 选择最空闲的 GPU",
            ],
            "yaml_comment": "设备选择(0/cpu/mps/[0,1]/0,1)",
        },
    )

    amp: bool = Field(
        default=True,
        description="自动混合精度",
        json_schema_extra={
            "group": "设备配置",
            "examples": [True, False],
            "tips": [
                "True: 使用 FP16 混合精度(快 + 省显存)",
                "False: 使用 FP32 全精度",
                "现代 GPU (20 系+) 强烈推荐开启",
                "CPU 训练时自动禁用",
            ],
            "yaml_comment": "是否启用 AMP(推荐开启)",
        },
    )

    # -------- 输出配置 --------

    project: Optional[str] = Field(
        default=None,
        description="输出项目目录",
        json_schema_extra={
            "group": "输出配置",
            "examples": ["runs/detect", "experiments/safety"],
            "tips": [
                "训练输出的根目录",
                "默认: 由 service 层根据 task 自动拼装(runs/<task>/)",
            ],
            "yaml_comment": "项目输出目录(None=框架自动)",
        },
    )

    name: Optional[str] = Field(
        default=None,
        description="实验名称",
        json_schema_extra={
            "group": "输出配置",
            "examples": ["exp", "safety_v1", "baseline"],
            "tips": [
                "每次运行的子目录名",
                "默认: ultralytics 自动生成 exp, exp2, exp3...",
            ],
            "yaml_comment": "实验名称",
        },
    )

    exist_ok: bool = Field(
        default=False,
        description="允许覆盖已有实验",
        json_schema_extra={
            "group": "输出配置",
            "examples": [False, True],
            "tips": [
                "False: 自动创建新目录(exp2, exp3...)",
                "True: 覆盖已有目录",
                "生产环境建议 False",
            ],
            "yaml_comment": "是否覆盖已有实验目录",
        },
    )

    save: bool = Field(
        default=True,
        description="保存训练检查点",
        json_schema_extra={
            "group": "输出配置",
            "examples": [True, False],
            "tips": [
                "True: 保存 last.pt 和 best.pt",
                "False: 不保存检查点(节省磁盘)",
            ],
            "yaml_comment": "是否保存检查点",
        },
    )

    # -------- 基础设置 --------

    verbose: bool = Field(
        default=True,
        description="详细输出模式",
        json_schema_extra={
            "group": "基础设置",
            "examples": [True, False],
            "tips": [
                "True: 显示详细日志",
                "False: 只显示关键信息",
            ],
            "yaml_comment": "是否显示详细日志",
        },
    )

    seed: int = Field(
        default=0,
        ge=0,
        description="随机种子",
        json_schema_extra={
            "group": "基础设置",
            "examples": [0, 42, 2026],
            "tips": [
                "控制随机性, 确保可复现",
                "相同种子 = 相同结果",
                "建议每个实验使用不同种子",
            ],
            "yaml_comment": "随机种子(可复现性)",
        },
    )

    deterministic: bool = Field(
        default=True,
        description="确定性算法",
        json_schema_extra={
            "group": "基础设置",
            "examples": [True, False],
            "tips": [
                "True: 强制使用确定性算法(完全可复现)",
                "False: 允许非确定性算法(可能更快)",
                "实验对比时必须设为 True",
            ],
            "yaml_comment": "是否强制确定性算法",
        },
    )

    # ============================================================
    # 验证器
    # ============================================================

    @field_validator("imgsz")
    @classmethod
    def _validate_imgsz(cls, v: int) -> int:
        """验证图像尺寸(建议 32 的倍数, 但不强制)"""
        if v % 32 != 0:
            warnings.warn(
                f"imgsz={v} 不是 32 的倍数. "
                f"虽然可以运行, 但建议使用 32 的倍数(如 640, 672, 704)以获得最佳性能.",
                UserWarning,
            )
        return v

    @field_validator("batch", mode="before")
    @classmethod
    def _validate_batch(cls, v: Any) -> Union[int, float]:
        """验证批次大小格式(mode="before": 在类型转换前拿到原始值, 才能拦住 bool)"""
        if isinstance(v, bool):
            raise TypeError("batch 不能是 bool 类型")
        if isinstance(v, int):
            if v == -1:
                return v
            if v <= 0:
                raise ValueError("batch 为 int 时必须为 -1(自动) 或 >= 1(固定值)")
            return v
        v_float = float(v)
        if not (0.0 < v_float <= 1.0):
            raise ValueError(
                f"batch 为 float 时必须在 (0, 1] 范围内, 表示显存利用率. "
                f"当前值: {v_float}"
            )
        return v_float

    @field_validator("device")
    @classmethod
    def _validate_device(cls, v: Any) -> Any:
        """标准化设备参数"""
        if v is None:
            return v
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, (int, list)):
            return v
        raise TypeError(
            f"device 必须是 None, str, int 或 list 类型, "
            f"当前类型: {type(v).__name__}"
        )

    @field_validator("cache")
    @classmethod
    def _validate_cache(cls, v: Union[bool, str]) -> Union[bool, str]:
        """验证缓存参数"""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            v_lower = v.lower()
            if v_lower not in ("ram", "disk"):
                raise ValueError(
                    f"cache 为 str 时必须是 'ram' 或 'disk', 当前值: {v}"
                )
            return v_lower
        raise TypeError(
            f"cache 必须是 bool 或 str 类型, 当前类型: {type(v).__name__}"
        )

    @model_validator(mode="after")
    def _cross_field_validation(self) -> "BaseConfig":
        """跨字段验证"""
        if isinstance(self.batch, int) and self.batch > 0:
            if self.workers > self.batch * 2:
                warnings.warn(
                    f"workers={self.workers} 远大于 batch={self.batch}, "
                    f"可能造成资源浪费. 建议 workers <= batch * 2",
                    UserWarning,
                )
        return self

    # ============================================================
    # 工具方法
    # ============================================================

    def to_ultralytics_kwargs(self) -> Dict[str, Any]:
        """转换为 Ultralytics 训练/验证参数字典.

        - 自动过滤 None 值
        - 剔除 FRAMEWORK_ONLY_FIELDS 中的框架级参数(不传递给 Ultralytics)
        子类(YOLOValConfig)只需扩展 FRAMEWORK_ONLY_FIELDS, 无需 override 本方法.
        """
        d = self.model_dump(exclude_none=True)
        for field_name in self.FRAMEWORK_ONLY_FIELDS:
            d.pop(field_name, None)
        return d

    def get_field_groups(self) -> Dict[str, List[str]]:
        """获取字段分组信息. {group_name: [field_names]}"""
        groups: Dict[str, List[str]] = {}
        for field_name, field_info in self.__class__.model_fields.items():
            extra = field_info.json_schema_extra or {}
            group = extra.get("group", "其他") if isinstance(extra, dict) else "其他"
            groups.setdefault(group, []).append(field_name)
        return groups

    def get_field_metadata(self, field_name: str) -> Dict[str, Any]:
        """获取字段的完整元数据(供 generator 写注释用)"""
        if field_name not in self.__class__.model_fields:
            raise ValueError(f"字段 '{field_name}' 不存在")

        field_info = self.__class__.model_fields[field_name]
        metadata: Dict[str, Any] = {
            "description":  field_info.description,
            "default":      field_info.default,
            "examples":     [],
            "tips":         [],
            "yaml_comment": field_info.description,
            "group":        "其他",
            "sensitive":    False,
        }
        if isinstance(field_info.json_schema_extra, dict):
            metadata.update(field_info.json_schema_extra)
        return metadata

    # ============================================================
    # 实验复现接口 (to_audit_snapshot / from_audit_snapshot)
    # ============================================================

    def to_audit_snapshot(self) -> Dict[str, Any]:
        """返回可序列化的完整快照, 用于实验复现.

        Returns:
            {
                "config_class":  类名 (如 "YOLOTrainConfig"),
                "config_module": 模块路径,
                "frozen_at":     ISO 时间戳,
                "values":        所有字段值,
            }
        """
        return {
            "config_class":  self.__class__.__name__,
            "config_module": self.__class__.__module__,
            "frozen_at":     datetime.now().isoformat(timespec="seconds"),
            "values":        self.model_dump(),
        }

    @classmethod
    def from_audit_snapshot(cls, snapshot: Dict[str, Any]) -> "BaseConfig":
        """从快照恢复配置实例 (走完整 Pydantic 验证).

        Raises:
            ValueError:        快照类名与 cls 不匹配
            ValidationError:   快照值非法 (字段定义可能已演进)
        """
        expected = cls.__name__
        got = snapshot.get("config_class")
        if got != expected:
            raise ValueError(
                f"快照来自配置类 {got!r}, 不能恢复到 {expected!r}. "
                f"请用 {got}.from_audit_snapshot(snapshot)."
            )
        return cls(**snapshot.get("values", {}))

    # ============================================================
    # 敏感字段 mask
    # ============================================================

    def mask_sensitive_dump(self) -> Dict[str, Any]:
        """model_dump() 但 sensitive 字段值替换成 SENSITIVE_MASK.

        进日志 / 报告前调用, 避免敏感数据外泄.
        进数据库存原值时用 model_dump() (不 mask).
        """
        dump = self.model_dump()
        for field_name, field_info in self.__class__.model_fields.items():
            extra = field_info.json_schema_extra or {}
            if not isinstance(extra, dict):
                continue
            if not extra.get("sensitive"):
                continue
            if dump.get(field_name) is None:
                continue                              # None 不 mask, 避免误导
            dump[field_name] = self.SENSITIVE_MASK
        return dump

    @classmethod
    def sensitive_field_names(cls) -> set[str]:
        """返回标了 sensitive=True 的字段名集合 (供 merger 自动 mask 用)."""
        result: set[str] = set()
        for name, field_info in cls.model_fields.items():
            extra = field_info.json_schema_extra or {}
            if isinstance(extra, dict) and extra.get("sensitive"):
                result.add(name)
        return result
```

代码约 480 行, 其中字段定义约 280 行, **逻辑只有 5 个验证器 + 7 个工具方法** (`to_ultralytics_kwargs` / `get_field_groups` / `get_field_metadata` / `to_audit_snapshot` / `from_audit_snapshot` / `mask_sensitive_dump` / `sensitive_field_names`). 字段多但不难, 难的是 2.2 里"确定哪 15 个".

## 2.7 测试: BaseConfig 基础验证

> ⚙️ **前置确认 (D2-D5 通用)**:
>
> 跑下面任何"import odp_platform"的代码之前, 确认 D2 末尾立的 editable install 还在生效:
>
> ```bash
> # 方法 1: 检查包是否装上 (推荐, 最直接)
> python -c "import odp_platform; print(odp_platform.__file__)"
> # 应该打印 .../apps/platform/src/odp_platform/__init__.py
>
> # 方法 2: 检查 entry-point 是否还在
> odp-init --help        # 能跑就说明装好了
> ```
>
> 如果上面任何一条报 `ModuleNotFoundError` 或 `command not found`, 重装一次:
>
> ```bash
> pip install -e ./apps/platform
> ```
>
> **不建议**手设 PYTHONPATH 跑 D5 的测试 —— editable install 更稳定. 后续 3.9 / 4.7 / 5.11 / 6.7 / 7.4 的测试都默认这条前置已经成立, 不再重复.

打开 Python REPL (或者保存为脚本 `test_base_smoke.py` 后 `python test_base_smoke.py`):

```python
from odp_platform.runtime_config.base import BaseConfig

# 1. 默认配置
c = BaseConfig()
print(c.model_dump_json(indent=2))

# 2. 验证错误
try:
    BaseConfig(batch=0)
except Exception as e:
    print(f"✓ 拒绝 batch=0: {e}")

try:
    BaseConfig(batch=True)
except Exception as e:
    print(f"✓ 拒绝 batch=bool: {e}")

try:
    BaseConfig(cache="foobar")
except Exception as e:
    print(f"✓ 拒绝 cache='foobar': {e}")

# 3. 警告
import warnings
with warnings.catch_warnings(record=True) as ws:
    warnings.simplefilter("always")
    BaseConfig(imgsz=649)
    assert any("不是 32 的倍数" in str(w.message) for w in ws)
    print("✓ imgsz=649 触发警告")

# 4. 字段元数据
batch_meta = c.get_field_metadata("batch")
print(f"✓ batch group: {batch_meta['group']}")
print(f"✓ batch tips[0]: {batch_meta['tips'][0]}")

# 5. 字段分组
groups = c.get_field_groups()
for g, fields in groups.items():
    print(f"  {g}: {len(fields)} 个字段")

# 6. 转 ultralytics kwargs
kwargs = c.to_ultralytics_kwargs()
assert "verbose" not in kwargs
print(f"✓ kwargs 不含 verbose, 共 {len(kwargs)} 个参数")

# 7. extra="forbid": 拒绝拼错的字段名
try:
    BaseConfig(epchs=300)          # epochs 拼错成 epchs
except Exception as e:
    print(f"✓ 拒绝未知字段 epchs: {type(e).__name__}")

# 8. mode="before" 让 bool 守卫真正生效
try:
    BaseConfig(batch=True)         # 必须报 batch 不能是 bool, 而不是静默变成 1
except Exception as e:
    assert "bool" in str(e)
    print("✓ batch=True 被 bool 守卫拦下(未静默变成 1)")
```

应该一路 ✓.

## 2.8 git commit

```bash
git add apps/platform/src/odp_platform/runtime_config/base.py
git add apps/platform/src/odp_platform/runtime_config/__init__.py    # 空文件占位
git commit -m "feat(runtime_config): add BaseConfig with field-level metadata

runtime_config/base.py:
  + BaseConfig (Pydantic v2) — 15 fields shared by train/val/infer
    Groups: 核心参数 / 输入配置 / 设备配置 / 输出配置 / 基础设置
  + model_config = ConfigDict(extra='forbid') — reject misspelled keys
  + FRAMEWORK_ONLY_FIELDS (ClassVar) — fields not passed to ultralytics;
    subclasses extend this set instead of overriding to_ultralytics_kwargs()
  + 5 field validators (imgsz / batch / device / cache + cross-field)
  + 3 framework methods:
      - to_ultralytics_kwargs(): filter None + drop FRAMEWORK_ONLY_FIELDS
      - get_field_groups():       reflect group metadata for YAML grouping
      - get_field_metadata():     reflect full metadata for YAML comments

Why Pydantic over dataclass:
  - User-facing input (YAML/CLI) needs runtime validation
  - Field metadata (description/examples/tips/yaml_comment) has standard slot
  - Better error messages with field-level localization

Notes:
  - task NOT in BaseConfig — train/val have different semantics, place per-class
  - _validate_batch uses mode='before' — bool is int subclass; after-mode would
    let Pydantic coerce True->1 before the bool guard runs (silent footgun)
  - extra='forbid' fits closed field sets (ultralytics params are fixed)
  - imgsz validator warns instead of raises (ultralytics auto-rounds to 32×)
"
```

**中文版**:

```bash
git commit -m "feat(runtime_config): 新增 BaseConfig 配置基类与字段级元数据" \
           -m "runtime_config/base.py:" \
           -m "  + BaseConfig (Pydantic v2) —— 训练/验证/推理共享的 15 个字段" \
           -m "    分组: 核心参数 / 输入配置 / 设备配置 / 输出配置 / 基础设置" \
           -m "  + model_config = ConfigDict(extra='forbid') —— 拒绝拼错的字段名" \
           -m "  + FRAMEWORK_ONLY_FIELDS (ClassVar) —— 框架级字段不传给 ultralytics;" \
           -m "    子类只扩展集合, 不 override to_ultralytics_kwargs()" \
           -m "  + 5 个字段验证器 (imgsz / batch / device / cache + 跨字段)" \
           -m "  + 工具方法: to_ultralytics_kwargs / get_field_groups / get_field_metadata" \
           -m "  + 实验复现接口: to_audit_snapshot / from_audit_snapshot" \
           -m "  + 敏感字段 mask: mask_sensitive_dump / sensitive_field_names" \
           -m "为什么选 Pydantic 而不是 dataclass:" \
           -m "  - 配置面向用户输入 (YAML/CLI), 必须有运行时验证" \
           -m "  - 字段元数据 (description/examples/tips/yaml_comment) 有标准槽位" \
           -m "  - ValidationError 自带字段路径定位, 错误信息精确" \
           -m "关键设计:" \
           -m "  - task 故意不放 BaseConfig —— train/val/infer 语义不同, 各自定义" \
           -m "  - _validate_batch 用 mode='before' —— bool 是 int 子类, after 模式" \
           -m "    会让 Pydantic 把 True 强转成 1, bool 守卫形同虚设" \
           -m "  - extra='forbid' 适合封闭字段集 (ultralytics 参数是固定的)" \
           -m "  - imgsz 验证器选 warn 不 raise —— ultralytics 会自动补到 32 的倍数"
```


至此, **基础层立稳——约 420 行代码, 15 个字段 + 5 个验证器 + 3 个工具方法**. 阶段 3 起往里塞训练 / 验证特定的字段.

> **金句**: **\"BaseConfig 的难度不在'15 个字段', 在'确定哪 15 个'——字段定下来, 代码就只剩抄写; 字段选错了, 子类越长越歪.\"**

---
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 3: YOLOTrainConfig + YOLOValConfig——子类登场

阶段 2 立好了 BaseConfig(15 个共享字段). 阶段 3 要做两件事:

1. **YOLOTrainConfig**——往 BaseConfig 里塞 **52 个训练特有字段**, 一次性凑齐 ultralytics `model.train()` 的全部接口.
2. **YOLOValConfig**——比训练简单, 但藏着 D5 的第二次撞墙: `task = "detect_val"` 既当语义又当目录名, **得拆**.

> **金句**: **"基类管共享, 子类管差异——差异不只是'多了几个字段', 还包括'同一个字段在不同模式下意思变了'."**

## 3.1 YOLOTrainConfig: 52 个训练特有字段, 怎么组织

ultralytics 文档列了 60+ 训练参数. 扣掉 BaseConfig 已经装的 15 个共享字段(model / data / batch / imgsz / workers / cache / rect / device / amp / project / name / exist_ok / save / verbose / seed / deterministic), **剩下 52 个全是训练特有**.

52 个字段平铺一坨在源码里没法读. 按"调参时一起调的"原则分组——11 个组:

```
YOLOTrainConfig (训练子类, 继承 BaseConfig)
├── 核心参数:        task, experiment_name              ★ D5 重构点(见 3.2)
├── 训练控制:        epochs, time, patience, resume,
│                    close_mosaic, multi_scale,
│                    fraction, freeze                    (8)
├── 优化器配置:      optimizer, lr0, lrf, momentum,
│                    weight_decay, cos_lr                (6)
├── 学习率预热:      warmup_epochs, warmup_momentum,
│                    warmup_bias_lr                      (3)
├── 损失权重:        box, cls, dfl, pose, kobj, nbs      (6)
├── 数据增强-颜色:   hsv_h, hsv_s, hsv_v, bgr            (4)
├── 数据增强-几何:   degrees, translate, scale, shear,
│                    perspective, flipud, fliplr         (7)
├── 数据增强-拼接:   mosaic, mixup, copy_paste           (3)
├── 验证和输出:      val, plots, save_period             (3)
├── 任务特定:        overlap_mask, mask_ratio, dropout,
│                    copy_paste_mode, auto_augment,
│                    erasing                             (6)
└── 高级设置:        pretrained, single_cls, classes,
                     compile, profile, augmentations     (6)
```

⚠️ **设计点 (分组的判据)**: 一组字段的判据是 **"在同一次调参里被同时改"** ——调优化器时一起改 `lr0 / lrf / momentum / cos_lr`; 调数据增强强度时一起改 `mosaic / mixup / copy_paste`. 用户在 YAML 里翻到这一段, 该看到的相关字段都在眼前. 反过来, `dropout` 是分类任务才用的, 跟检测的 `box loss` 是两个世界, 强行同组反而模糊.

⚠️ **设计点 (为什么不按"调参频率"分?)** 一个合理的备选分组是按"高频调参 / 低频调参"分(`epochs / batch / lr0` 是高频, `weight_decay / nbs` 是低频). 但 **频率因人而异**——给新手看的 yaml 和给老手看的 yaml 应该长一样, 频率不是字段的内禀属性, 语义才是. 按语义分组, 在字段元数据的 `tips` 里写"高频调参时关注 lr0", 才是把信息放对地方.

⚠️ **设计点 (任务特定字段为什么不拆到子类?)** `overlap_mask / mask_ratio / dropout / auto_augment / erasing` 这些字段是分割/分类任务才用的, 检测任务完全不碰. 严格按"用不用"分, 该再拆出 `YOLOSegmentTrainConfig` / `YOLOClassifyTrainConfig`. 但: ultralytics 本身就把这些字段塞在一个 `.train()` 调用里, 拆得太细反而跟上游对不上. 把它们放进同一个类、用一个 "任务特定" 分组提醒用户"这些不是所有人都用"——**配置类的结构应该贴合接口的结构, 不是贴合理论模型的洁癖**.

> 🤔 **思考题**: `pose / kobj` 是 pose 任务的 loss 权重, 我把它们放进了 "损失权重" 组而不是 "任务特定" 组. 为什么?
>
> **答**: `box / cls / dfl / pose / kobj / nbs` 都是 "损失权重", 在源码层面是同一类逻辑(都参与 loss 计算). 它们的分组应该按 **"代码里在做什么"** 分, 而不是按 "我此刻是否在跑 pose" 分. 配置类的分组是 **静态的代码视图**, 不是动态的运行视图.

## 3.2 🧱 撞墙②: task 既当语义又当目录名

legacy `val_model.py` 里有这么一段:

```python
# legacy: 一个 task 字段两件事都干, 看着省事其实病了
task: str = Field(
    default="detect_val",
    description="任务类型/输出目录名",
    json_schema_extra={
        "examples": ["detect_val", "segment_val", "detect", "segment", "pose_val"],
        "tips": ["决定输出目录: runs/{task}/", "可自定义名称, 如 detect_val、segment_test"],
        ...
    },
)
```

跑得起来吗? **能跑**. ultralytics 不在乎你传啥字符串当 `task`——验证时它会从 `.pt` 权重里反推真正的 task. 那有什么问题?

### 问题①: task 不再是 SSoT

D3 立的 `Task = {DETECT, SEGMENT}` 是项目里"任务类型"的唯一真相. 而 legacy 这个字段允许 `"detect_val"`、`"segment_test"`、`"detect"`、`"pose_val"`、`"safety_baseline_v2"`—— **任何字符串**.

一旦放任, 想问"这次跑的是 detect 还是 segment?" **没法机器化回答**, 得字符串匹配("以 `detect` 开头就是检测? 那 `detection_v2` 算吗? `det_v1` 算吗?"). **SSoT 在 task 上直接失守**.

更糟的: D3 的 `data_pipeline` 一路在用 `Task.DETECT` / `Task.SEGMENT` 做条件分发. legacy 这个 task 字段值如果是 `"detect_val"`, `if task == Task.DETECT` 直接 False——逻辑链断了, 用户什么都看不到.

### 问题②: 自定义实验名又被锁死

反过来, 用户想给这次跑取个名字, 比如 `"baseline_v1"` / `"helmet_finetune_lr001"`, 自然语言地标记一下. 用 legacy 的设计就得写 `task = "baseline_v1"`—— **等于把"它是个 detect 任务"这条信息也丢了**, 后面所有靠 task 区分的逻辑都不灵了.

用户最后只能采取一种很别扭的折中: `task = "detect_baseline_v1"`. **字段值变成了"语义 + 实验名拼字符串"**——再后面想从字符串里解析回结构化信息(eg. 要批量列出所有 detect 实验), 就是字符串切片大赛.

### 问题③: 实习生模板复制粘贴的灾难

最致命的是规模化场景: 实习生 A 跑了 `task = "detect"`(标准检测), 实习生 B 复制 A 的 yaml 改了个 `task = "detect_v2"`(其实就是想换个目录名)——两个人一起翻日志, 找一个具体的 mAP, 得用字符串模糊匹配"看 task 是不是以 `detect` 开头". 一个礼拜后实习生 C 进来, 抱怨"为啥我的 `task = "Detect"` 跑不出 detect 的效果?"(大写 D 不在白名单, 但代码没拒).

**根本错误**: 一个字段被强行承担了两个**正交**的职责:
- **职责 A (任务语义)**: 这是哪种 CV 任务? 取值是封闭集合 `{detect, segment}`, 必须严格.
- **职责 B (实验标识)**: 这次跑叫啥名? 取值是开放字符串, 必须自由.

合二为一, 两边都做不好. **拆**.

### 解法: task (SSoT) + experiment_name (实验标识)

```python
# 职责 A: 任务语义 (SSoT, 封闭取值)
task: str = Field(
    default=Task.DETECT,
    description="任务类型(SSoT, 封闭取值)",
    json_schema_extra={
        "group":        "核心参数",
        "examples":     list(Task.all()),
        "tips": [
            "限定取值: " + " / ".join(Task.all()),
            "决定模型加载方式 + 输出目录的一级子目录",
            "想给实验起名? → 用 experiment_name 字段",
        ],
        "yaml_comment": "任务类型(只能是 detect 或 segment)",
    },
)

# 职责 B: 实验标识 (自由字符串)
experiment_name: Optional[str] = Field(
    default=None,
    description="实验名(只用作目录组织, 不影响任务语义)",
    json_schema_extra={
        "group":        "核心参数",
        "examples":     ["baseline", "helmet_v1", "lr001_aug_strong", None],
        "tips": [
            "None: 由 ultralytics 自动生成 exp, exp2, exp3...",
            "自定义: 用作 runs/<task>/<experiment_name>/ 的子目录",
            "推荐命名格式: <模型>_<数据集>_<关键调参>",
        ],
        "yaml_comment": "实验名(目录组织, 不影响语义; None=自动生成)",
    },
)
```

**两个字段, 两个职责, 互不污染**:

```
用户写:        task: detect
              experiment_name: helmet_v1_lr001

D6 service:    保留 task 走任务分发逻辑(SSoT)
              把 experiment_name 翻译成 ultralytics 的 name 参数
              输出目录:  runs/detect/helmet_v1_lr001/
```

⚠️ **设计点 (task 的 validator 是硬墙, 不是软提示)**:

```python
@field_validator("task")
@classmethod
def _validate_task(cls, v: str) -> str:
    if v not in Task.all():
        raise ValueError(
            f"task 必须是 {Task.all()} 之一, 当前值: {v!r}. "
            f"若想给本次实验取名, 请使用 experiment_name 字段."
        )
    return v
```

错误信息里 **直接告诉用户"想取名走 experiment_name"**——配置错误不是"扔一行 ValueError 就完事", 是 "在最贴近错误的地方告诉他下一步怎么走". 用户调一次报错就明白了, 不用查文档.

⚠️ **设计点 (为什么把这两个字段放 "核心参数" 组而不是 "输出配置" 组?)** `task` 和 `experiment_name` 在用户的心理模型里是 **"我先决定跑啥, 再决定起啥名"**——这是开始调参之前就要填的两个空, 跟 model / data 一样是 "门面字段". 放进 "核心参数" 组, 让用户打开 yaml 第一眼就看到. `project / name / exist_ok / save` 是细节, 排后面.

⚠️ **设计点 (BaseConfig 已经有 `name` 字段了, 这里再加 `experiment_name` 不是重复?)** 不是. BaseConfig 的 `name` 字段是 **ultralytics 的原生参数**(对应 `model.train(name=...)`); D5 给用户的 **对外语言** 是 `experiment_name`——更明确、更不容易跟 model name / dataset name 混淆. 但底层传给 ultralytics 时仍走 `name`. 后面 3.7 会讲到, 这俩字段的 "翻译" 由 service 层做, 配置层不直接打通.

> **金句**: **"一个字段同时承担两个职责, 看着省一行代码, 其实埋了所有后续问题的雷.两个职责, 两个字段——这是最便宜的设计原则."**

## 3.3 task 在 train 和 val 模式下的传递差异

`task` 字段在 train 和 val 都有, 但 **传给 ultralytics 的方式不一样**:

| 模式 | task 字段 | 行为 |
|---|---|---|
| **train** | 传给 ultralytics | `model.train(task="detect", ...)`—— 决定加载哪个任务模板 |
| **val** | **不传** | `model.val()` 从 `.pt` 权重自动推断, 多传一个 task 反而可能跟权重冲突 |

这就是 2.5 节我们把 `to_ultralytics_kwargs()` 设计成 **"基类方法读 `FRAMEWORK_ONLY_FIELDS` 集合, 子类只改集合"** 的核心理由——

```python
class YOLOTrainConfig(BaseConfig):
    # train: experiment_name 不传(由 service 层翻译成 name)
    FRAMEWORK_ONLY_FIELDS: ClassVar[set[str]] = (
        BaseConfig.FRAMEWORK_ONLY_FIELDS | {"experiment_name"}
    )

class YOLOValConfig(BaseConfig):
    # val: experiment_name 不传 + task 也不传(从权重推断)
    FRAMEWORK_ONLY_FIELDS: ClassVar[set[str]] = (
        BaseConfig.FRAMEWORK_ONLY_FIELDS | {"experiment_name", "task"}
    )
```

⚠️ **设计点 (子类怎么"扩展" ClassVar 集合)** Pydantic 子类的 `ClassVar` 重新赋值要 **再次显式标注 `ClassVar`**——否则 Pydantic 可能把它误判为字段. 写成 `| {"task"}` 这种集合运算, 还能让阅读者清楚看到 "我比父类多了什么", 而不是 "完全覆盖父类".

⚠️ **设计点 (FRAMEWORK_ONLY_FIELDS 不是 "禁止用户配置", 是 "不传给 ultralytics")** 用户在 YAML 里写 `experiment_name: helmet_v1` 是 **合法的** ——它会进 Pydantic 实例, 会被 service 层读取. 只是 `to_ultralytics_kwargs()` 把它过滤掉, 不传给 `model.train()` 而已. 这俩功能正交: "配置里能写" vs "原样转发给 ultralytics".

## 3.4 YOLOTrainConfig 的字段元数据要怎么写——3 个范例

52 个字段都要写一遍 `Field(default=..., description=..., json_schema_extra={"group", "examples", "tips", "yaml_comment"})`. 一个字段一个字段抄, 不难, 但有 3 类容易写歪的字段, 单独示范.

### 范例 1: epochs ——"调参频率最高的字段"

```python
epochs: int = Field(
    default=100,
    ge=1,
    description="训练总轮数",
    json_schema_extra={
        "group":    "训练控制",
        "examples": [50, 100, 200, 300],
        "tips": [
            "小数据集: 50-100 轮",
            "中等数据集: 100-200 轮",
            "大数据集 / 工业检测: 200-300 轮",
            "过拟合风险时可减少轮数",
        ],
        "yaml_comment": "训练总轮数(epoch)",
    },
)
```

⚠️ **设计点 (tips 不要写废话)** 反例: `tips: ["训练多少轮"]`——这是 description 已经说的, 重复. 正例: 给具体数据集规模的推荐值——这是 **用户调参时真正想知道的**, 但翻 ultralytics 官方文档查不到.

⚠️ **设计点 (ge=1 是必须的)** 没有 `ge=1`, 用户写 `epochs: 0` 不会立即报错, ultralytics 内部会出现什么行为不可知. **能在配置层拦的, 永远在配置层拦**.

### 范例 2: lr0 / lrf ——"两个字段语义耦合"

```python
lr0: float = Field(
    default=0.01, gt=0,
    description="初始学习率",
    json_schema_extra={
        "group":    "优化器配置",
        "examples": [0.001, 0.01, 0.1],
        "tips": [
            "SGD 推荐: 0.01",
            "Adam / AdamW 推荐: 0.001",
            "大 batch 可适当增大",
            "小 batch 需适当减小",
        ],
        "yaml_comment": "初始学习率",
    },
)

lrf: float = Field(
    default=0.01, gt=0,
    description="最终学习率比例",
    json_schema_extra={
        "group":    "优化器配置",
        "examples": [0.01, 0.1, 0.2],
        "tips": [
            "★ 最终学习率 = lr0 × lrf",
            "0.01 表示衰减到初始的 1%",
            "配合余弦退火 cos_lr=true 使用",
            "一般保持默认值即可",
        ],
        "yaml_comment": "最终学习率比例(final_lr = lr0 × lrf)",
    },
)
```

⚠️ **设计点 (字段间的语义耦合写在 tips 里)** `lrf` 的语义是 "相对 `lr0` 的比例", **离开 `lr0` 不可理解**. tips 第一条用 ★ 强调这层关系——`yaml_comment` 里也再说一遍("final_lr = lr0 × lrf"), 用户即使只看注释也能立刻理解.

### 范例 3: freeze ——"既能填 int 也能填 list"

```python
freeze: Optional[Union[int, List[int]]] = Field(
    default=None,
    description="冻结层",
    json_schema_extra={
        "group":    "训练控制",
        "examples": [None, 10, [0, 1, 2, 3]],
        "tips": [
            "None: 不冻结任何层",
            "int N: 冻结前 N 层(常用 10 表示冻结 backbone)",
            "list: 冻结指定层索引",
            "迁移学习场景使用",
        ],
        "yaml_comment": "冻结层(None / int / list)",
    },
)
```

⚠️ **设计点 (Union 类型字段的 examples 要覆盖所有形态)** `examples` 数组里 **三种形态都给一个**(None / int / list), 让用户复制粘贴时直接知道"哦, 写 `[0, 1, 2]` 这种也行". 反例: `examples: [None]`——用户根本不知道还能填 list.

## 3.5 跨字段验证: 2 个真实场景

`@model_validator(mode="after")` 用来做 **2 个或以上字段之间的合理性检查**. YOLOTrainConfig 里有两个明显的场景:

### 场景 1: save_period > 0 但 save = False

```python
@model_validator(mode="after")
def _cross_field_validation(self) -> "YOLOTrainConfig":
    """跨字段验证"""

    # save_period > 0 隐含了"想保存周期性检查点", 但 save=False 又禁了所有保存——矛盾
    if not self.save and self.save_period > 0:
        raise ValueError(
            "save=False 时不应设置 save_period > 0. "
            "如果想关闭检查点保存, save_period 也应设为 -1; "
            "如果想周期性保存, save 必须为 True."
        )

    # close_mosaic 最后 N 轮关闭 mosaic, 但 mosaic 本来就 0 = 关了——空转
    if self.close_mosaic > 0 and self.mosaic == 0.0:
        warnings.warn(
            "mosaic=0.0 但设置了 close_mosaic > 0, "
            "close_mosaic 将不会生效",
            UserWarning,
        )

    return self
```

### 场景 2: 为什么一个 raise 一个 warn?

⚠️ **设计点 (raise vs warn 的判据再深一层)** 阶段 2 我们说过 "warn 是提示, raise 是拒绝". 这里更精细:

- **`save=False` + `save_period>0`**: **用户在表达自相矛盾的意图** ——他到底要不要保存? 配置层无法替他决定, 必须 raise 让他自己澄清.
- **`mosaic=0` + `close_mosaic=10`**: **意图清楚, 只是有冗余配置** ——他想关 mosaic, close_mosaic 怎么写都没影响. warn 一下让他知道这行没用, 但不必挡路.

**判据**: 如果配置组合 **能继续跑且行为确定**, warn; **不能继续跑或行为不确定**, raise. 自相矛盾的语义属于后者.

⚠️ **设计点 (跨字段验证为什么放 `mode="after"`)** `model_validator(mode="after")` 拿到的 `self` 是 **已经验证完单字段的实例** ——`self.save` 已经是 bool, `self.save_period` 已经是 int. 想象一下 `mode="before"`: 拿到的是 raw dict, 你不知道 `save_period` 是不是字符串"-1"还是数字, 跨字段比较毫无意义. **跨字段验证几乎都是 `after`**.

## 3.6 YOLOValConfig: 比 train 简单, 但也有自己的活

验证模式参数比训练少得多, 大约 11 个特有字段:

```
YOLOValConfig (验证子类, 继承 BaseConfig)
├── 核心参数:        task, experiment_name              ★ 跟 train 一样
├── 验证控制:        split, conf, iou, max_det           (4)
├── 评估设置:        half, plots, save_json, save_hybrid (4)
└── 任务特定:        mask_ratio, overlap_mask, dnn       (3)
```

3 个跟 train 不一样的设计点:

### 设计点 A: split 字段限定取值

```python
split: str = Field(
    default="val",
    description="数据集划分",
    json_schema_extra={
        "group":        "验证控制",
        "examples":     ["val", "test", "train"],
        "tips": [
            "val: 使用验证集(默认)",
            "test: 使用测试集(D3 odp-transform 产出的话)",
            "train: 使用训练集(调试用)",
            "对应 data.yaml 里的字段名",
        ],
        "yaml_comment": "数据集划分(val/test/train)",
    },
)

@field_validator("split")
@classmethod
def _validate_split(cls, v: str) -> str:
    valid = {"train", "val", "test"}
    if v not in valid:
        raise ValueError(f"split 必须是 {sorted(valid)} 之一, 当前: {v!r}")
    return v
```

⚠️ **设计点 (validator 用 set 而不是 list)**: `{"train", "val", "test"}` —— set 的 `in` 是 O(1), list 的 `in` 是 O(n). 字段 validator 每次配置都跑一遍, 用 set 是反射性习惯.

### 设计点 B: conf 在 val 和 infer 默认值不一样

```python
conf: Optional[float] = Field(
    default=0.001,
    ge=0.0, le=1.0,
    description="置信度阈值",
    json_schema_extra={
        "group":    "验证控制",
        "examples": [0.001, 0.25, 0.5],
        "tips": [
            "★ 验证时通常设 0.001 (捕获所有预测, 用于计算 mAP)",
            "推理时建议 0.25-0.5 (过滤低置信度)",
            "不影响最终模型, 仅影响评估指标",
        ],
        "yaml_comment": "置信度阈值(验证 0.001; 推理 0.25+)",
    },
)
```

⚠️ **设计点 (同名字段在不同模式下默认值不同, 是合理的)**: BaseConfig 没有 `conf` 字段——这恰恰是 **"不通用的字段不要放共享层"** 的实例. 验证时 `conf=0.001` 是为了不丢任何预测好算 mAP; 推理时 `conf=0.25+` 是为了过滤掉低置信度的检测. **两件事**, 故意让 val 和 infer 各自定义自己的 conf, 默认值差两个数量级.

### 设计点 C: val 的 task 不传给 ultralytics

这是 3.3 已经讲过的, 在 val 的 FRAMEWORK_ONLY_FIELDS 里:

```python
class YOLOValConfig(BaseConfig):
    FRAMEWORK_ONLY_FIELDS: ClassVar[set[str]] = (
        BaseConfig.FRAMEWORK_ONLY_FIELDS | {"experiment_name", "task"}
    )
```

⚠️ **设计点 (val 的 task 字段 "有用但不传")** 既然不传给 ultralytics, 为啥还要这个字段? **三个用途**:
1. **目录组织**: service 层拼 `runs/<task>/<experiment_name>/` 还得知道 task
2. **日志标注**: 日志里写一句 "本次任务: detect", 用户一眼看到
3. **SSoT 校验**: validator 限定到 `Task.all()`, 防止跟 D3 的任务定义漂移

**字段值有用 ≠ 必须传给 ultralytics**. 配置层和外部框架的边界自己画.

## 3.6.5 YOLOInferConfig: 推理子类, 比 val 更进一步

train 跟 val 共享了"模型 + 数据 + 设备 + 输出"这些核心字段, infer 跟它们的关系略不一样——**推理时的"数据"是单张图 / 一段视频 / 一个流, 不是带标注的数据集 yaml**. 这一点决定了 infer 有自己的字段集.

参考 ultralytics `model.predict()`, 推理特有字段约 17 个:

```
YOLOInferConfig (推理子类, 继承 BaseConfig)
├── 核心参数:        task, experiment_name, source            ★ source 必填
├── 推理控制:        conf, iou, max_det, classes, agnostic_nms, augment
├── 视频/流:         vid_stride, stream, stream_buffer
├── 输出控制:        save_txt, save_conf, save_crop, save_frames,
│                    show, show_labels, show_conf, show_boxes, line_width
└── 任务特定:        retina_masks, visualize, embed
```

### 设计点 A: source 是推理的必填字段

train 和 val 的"数据"是 `data` (指向带标注的数据集 yaml), infer 的"数据"是 `source`——一张图、一个视频、一个目录、一个 RTSP 流, 是无标注的原始输入. 两类语义完全不同, **不放共享层**:

```python
source: Optional[Union[str, Path]] = Field(
    default=None,
    description="推理输入源",
    json_schema_extra={
        "group":    "核心参数",
        "examples": [
            "image.jpg",
            "video.mp4",
            "path/to/images/",
            "rtsp://example.com/live.sdp",
            "0",                    # 摄像头索引
            "https://example.com/img.jpg",
        ],
        "tips": [
            "支持: 图像 / 视频 / 目录 / URL / 摄像头索引 / RTSP 流",
            "目录: 自动遍历所有图像文件",
            "0 / '0' / 1: 摄像头编号",
            "None: 必须通过 CLI 传 --source",
        ],
        "yaml_comment": "推理输入源(图/视频/目录/URL/摄像头/流)",
    },
)
```

⚠️ **设计点 (source 为 None 时配置层不 raise)** 看着像"必填字段配置层应该拦下", 实际不是配置层的事. yaml 模板生成时 source 必须能是 `null` (用户拿到模板后填). 真正的"必填检查"是 D8 InferService 在调用 `model.predict()` 前做的——**配置层只管字段值的合法性, 不管字段有没有给**. 这条边界跟 val 的 task 字段同源.

### 设计点 B: conf 默认 0.25, vs val 的 0.001

```python
conf: float = Field(
    default=0.25,                   # ★ vs val 的 0.001
    ge=0.0, le=1.0,
    description="置信度阈值",
    json_schema_extra={
        "group":    "推理控制",
        "examples": [0.1, 0.25, 0.5, 0.7],
        "tips": [
            "★ 推理时 0.25-0.5 (过滤低置信度, 给用户看的)",
            "验证时是 0.001 (捕获所有预测, 算 mAP 用)",
            "工业部署常用 0.5+",
            "调高 = 漏检多但误检少",
        ],
        "yaml_comment": "置信度阈值(推理 0.25+, 验证 0.001)",
    },
)
```

⚠️ **设计点 (同名字段不同默认值是对的)** `conf` 在 val 和 infer 里都有, 默认值差两个数量级——val=0.001, infer=0.25. 这正是 BaseConfig 选型纪律的反向应用: **不通用的字段不该放共享层**, 即使名字一样, 默认值不同就是不通用. 强行放共享层会让"val 默认 0.001 还是 0.25" 永远说不清.

### 设计点 C: FRAMEWORK_ONLY_FIELDS 跟 val 一样

```python
class YOLOInferConfig(BaseConfig):
    FRAMEWORK_ONLY_FIELDS: ClassVar[set[str]] = (
        BaseConfig.FRAMEWORK_ONLY_FIELDS | {"experiment_name", "task"}
    )
```

跟 val 同款理由: `model.predict()` 也从权重自动推断 task, 不接受外部传入. **val 和 infer 的"框架级字段"完全一样, 这意味着它们对 ultralytics 的接口形态是同款**.

### 设计点 D: source 不进 FRAMEWORK_ONLY_FIELDS

`source` 是 `model.predict(source=...)` 的核心参数, **必须传给 ultralytics**. 跟 train 的 `data` / val 的 `data` 同款角色. 不进 framework-only.

### 4 个跨字段验证, 全部 warn 不 raise

推理场景下的"配置奇怪"几乎都能继续跑, 只是某些字段不生效. 跟 val 的 `save vs save_period` 那种"自相矛盾" 不同, 这里都是"意图清晰, 只是有冗余". 全部 warn 不挡路:

```python
@model_validator(mode="after")
def _cross_field_validation(self) -> "YOLOInferConfig":
    # save_conf 必须配套 save_txt
    if self.save_conf and not self.save_txt:
        warnings.warn(
            "save_conf=True 但 save_txt=False, save_conf 不会生效. "
            "若想保存置信度, save_txt 必须为 True.",
            UserWarning,
        )
    # stream_buffer 隐含 stream=True
    if self.stream_buffer and not self.stream:
        warnings.warn(
            "stream_buffer=True 但 stream=False, stream_buffer 不会生效. "
            "stream_buffer 仅在流式推理 (stream=True) 时有意义.",
            UserWarning,
        )
    # retina_masks 仅 segment 任务有效
    if self.retina_masks and self.task != Task.SEGMENT:
        warnings.warn(
            f"retina_masks=True 仅对 segment 任务有效, "
            f"当前 task={self.task!r}, 该字段将被忽略.",
            UserWarning,
        )
    return self
```

> 🤔 **思考题**: `vid_stride` (视频抽帧间隔) 我放进了"视频/流"组, 不是"推理控制"组. 为什么?
>
> **答**: `vid_stride` 只在 source 是视频或流时有意义——给图像传 `vid_stride=5` 完全无效. 它跟 `stream / stream_buffer` 一起是"输入是视频/流"时的子领域. 跟 `conf / iou` 这种"任何推理都用"的字段不同语义. **分组按'什么时候一起出现'分, 不按'都是推理参数'分**.

> **金句**: **"train 和 val 共享数据契约 (data.yaml 指向带标注数据集), infer 走的是'原始输入' 路径 (source 指向图/视频/流). 配置类的字段集恰好反映了这层语义差异——别为了 DRY 抹平掉."**

## 3.7 完整代码: train.py

`apps/platform/src/odp_platform/runtime_config/train.py`:

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : train.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统——YOLO 训练配置类
"""YOLO 训练配置: YOLOTrainConfig.

继承 BaseConfig + 添加 52 个训练特有字段, 全部分 11 个组:
    核心参数 / 训练控制 / 优化器配置 / 学习率预热 / 损失权重 /
    数据增强-颜色 / 数据增强-几何 / 数据增强-拼接 / 验证和输出 /
    任务特定 / 高级设置

★ 跟 legacy 的关键区别:
   1. task / experiment_name 拆分(legacy 一个字段两职责, 见 3.2)
   2. FRAMEWORK_ONLY_FIELDS 用 ClassVar 集合扩展, 不 override 方法
"""
from __future__ import annotations

import warnings
from typing import Any, ClassVar, Dict, List, Optional, Union

from pydantic import Field, field_validator, model_validator

from odp_platform.common.constants import Task
from odp_platform.runtime_config.base import BaseConfig


class YOLOTrainConfig(BaseConfig):
    """YOLO 训练配置: 继承 BaseConfig + 52 个训练特有字段."""

    # ============================================================
    # 框架级字段扩展: experiment_name 不传给 ultralytics
    # (BaseConfig 已经把 verbose 放进去; 这里继续扩)
    # ============================================================
    FRAMEWORK_ONLY_FIELDS: ClassVar[set[str]] = (
        BaseConfig.FRAMEWORK_ONLY_FIELDS | {"experiment_name"}
    )

    # ============================================================
    # 核心参数 (★ D5 重构点: task + experiment_name 拆分)
    # ============================================================

    task: str = Field(
        default=Task.DETECT,
        description="任务类型(SSoT, 封闭取值)",
        json_schema_extra={
            "group":    "核心参数",
            "examples": list(Task.all()),
            "tips": [
                "限定取值: " + " / ".join(Task.all()),
                "决定模型加载方式 + 输出目录的一级子目录",
                "想给实验起名? → 用 experiment_name 字段",
            ],
            "yaml_comment": "任务类型(只能是 detect / segment)",
        },
    )

    experiment_name: Optional[str] = Field(
        default=None,
        description="实验名(只用作目录组织, 不影响任务语义)",
        json_schema_extra={
            "group":    "核心参数",
            "examples": ["baseline", "helmet_v1", "lr001_aug_strong", None],
            "tips": [
                "None: 由 ultralytics 自动生成 exp / exp2 / exp3...",
                "自定义: 用作 runs/<task>/<experiment_name>/ 子目录",
                "推荐命名: <模型>_<数据集>_<关键调参>",
            ],
            "yaml_comment": "实验名(目录组织, 不影响语义; None=自动生成)",
        },
    )

    # ============================================================
    # 训练控制
    # ============================================================

    epochs: int = Field(
        default=100,
        ge=1,
        description="训练总轮数",
        json_schema_extra={
            "group":    "训练控制",
            "examples": [50, 100, 200, 300],
            "tips": [
                "小数据集: 50-100 轮",
                "中等数据集: 100-200 轮",
                "大数据集 / 工业检测: 200-300 轮",
                "过拟合风险时可减少轮数",
            ],
            "yaml_comment": "训练总轮数(epoch)",
        },
    )

    time: Optional[float] = Field(
        default=None,
        gt=0,
        description="最长训练时间(小时)",
        json_schema_extra={
            "group":    "训练控制",
            "examples": [1.0, 2.5, 12.0, 24.0],
            "tips": [
                "限制最长训练时间(小时), 设置后可提前终止",
                "适合有时间限制的场景",
                "None 表示不限制",
            ],
            "yaml_comment": "最长训练时间(小时, None=不限制)",
        },
    )

    patience: int = Field(
        default=100,
        ge=0,
        description="Early Stopping 耐心值",
        json_schema_extra={
            "group":    "训练控制",
            "examples": [50, 100, 150],
            "tips": [
                "多少轮无提升后停止训练",
                "0 表示禁用 Early Stopping",
                "建议设为 epochs 的 30-50%",
            ],
            "yaml_comment": "Early Stopping 耐心值(0=禁用)",
        },
    )

    resume: bool = Field(
        default=False,
        description="恢复训练",
        json_schema_extra={
            "group":    "训练控制",
            "examples": [False, True],
            "tips": [
                "True: 从最近的检查点恢复",
                "False: 从头开始训练",
                "需要已有 last.pt 检查点",
                "恢复时会保留优化器状态",
            ],
            "yaml_comment": "是否从检查点恢复训练",
        },
    )

    close_mosaic: int = Field(
        default=10,
        ge=0,
        description="关闭 Mosaic 的轮数",
        json_schema_extra={
            "group":    "训练控制",
            "examples": [0, 10, 15],
            "tips": [
                "最后 N 轮关闭 mosaic 增强",
                "有助于模型适应真实分布",
                "0 表示不关闭",
                "建议 10-15 轮",
            ],
            "yaml_comment": "最后 N 轮关闭 mosaic(0=不关闭)",
        },
    )

    multi_scale: bool = Field(
        default=False,
        description="多尺度训练",
        json_schema_extra={
            "group":    "训练控制",
            "examples": [False, True],
            "tips": [
                "True: 随机改变输入尺寸(±50%)",
                "提升模型对不同尺度的鲁棒性",
                "会略微增加训练时间",
                "小目标检测时推荐开启",
            ],
            "yaml_comment": "是否启用多尺度训练",
        },
    )

    fraction: float = Field(
        default=1.0,
        gt=0,
        le=1.0,
        description="训练数据使用比例",
        json_schema_extra={
            "group":    "训练控制",
            "examples": [0.1, 0.5, 1.0],
            "tips": [
                "1.0 表示使用全部数据",
                "0.1 表示使用 10% 数据",
                "调试时可设为小值快速验证",
            ],
            "yaml_comment": "训练数据使用比例(0-1)",
        },
    )

    freeze: Optional[Union[int, List[int]]] = Field(
        default=None,
        description="冻结层",
        json_schema_extra={
            "group":    "训练控制",
            "examples": [None, 10, [0, 1, 2, 3]],
            "tips": [
                "None: 不冻结任何层",
                "int N: 冻结前 N 层(常用 10 表示冻结 backbone)",
                "list: 冻结指定层索引",
                "迁移学习场景使用",
            ],
            "yaml_comment": "冻结层(None / int / list)",
        },
    )

    # ============================================================
    # 优化器配置
    # ============================================================

    optimizer: str = Field(
        default="auto",
        description="优化器类型",
        json_schema_extra={
            "group":    "优化器配置",
            "examples": ["auto", "SGD", "Adam", "AdamW", "NAdam", "RAdam"],
            "tips": [
                "auto: 自动选择(推荐)",
                "SGD: 传统随机梯度下降",
                "Adam / AdamW: 自适应学习率",
                "小数据集推荐 AdamW",
            ],
            "yaml_comment": "优化器(auto / SGD / Adam / AdamW)",
        },
    )

    lr0: float = Field(
        default=0.01, gt=0,
        description="初始学习率",
        json_schema_extra={
            "group":    "优化器配置",
            "examples": [0.001, 0.01, 0.1],
            "tips": [
                "SGD 推荐: 0.01",
                "Adam / AdamW 推荐: 0.001",
                "大 batch 可适当增大",
                "小 batch 需适当减小",
            ],
            "yaml_comment": "初始学习率",
        },
    )

    lrf: float = Field(
        default=0.01, gt=0,
        description="最终学习率比例",
        json_schema_extra={
            "group":    "优化器配置",
            "examples": [0.01, 0.1, 0.2],
            "tips": [
                "★ 最终学习率 = lr0 × lrf",
                "0.01 表示衰减到初始的 1%",
                "配合余弦退火 cos_lr=true 使用",
                "一般保持默认值即可",
            ],
            "yaml_comment": "最终学习率比例(final_lr = lr0 × lrf)",
        },
    )

    momentum: float = Field(
        default=0.937, gt=0, lt=1.0,
        description="SGD 动量 / Adam beta1",
        json_schema_extra={
            "group":    "优化器配置",
            "examples": [0.9, 0.937, 0.95],
            "tips": [
                "SGD 动量参数 / Adam 的 beta1",
                "一般保持默认值",
                "增大可提高稳定性",
            ],
            "yaml_comment": "动量参数",
        },
    )

    weight_decay: float = Field(
        default=0.0005, ge=0,
        description="权重衰减(L2 正则化)",
        json_schema_extra={
            "group":    "优化器配置",
            "examples": [0.0, 0.0001, 0.0005, 0.001],
            "tips": [
                "防止过拟合",
                "小数据集可增大(0.001)",
                "大数据集可减小(0.0001)",
                "0 表示不使用正则化",
            ],
            "yaml_comment": "权重衰减(L2 正则)",
        },
    )

    cos_lr: bool = Field(
        default=False,
        description="余弦学习率调度",
        json_schema_extra={
            "group":    "优化器配置",
            "examples": [False, True],
            "tips": [
                "True: 余弦退火",
                "False: 线性退火",
                "长训练周期推荐开启",
            ],
            "yaml_comment": "是否使用余弦学习率调度",
        },
    )

    # ============================================================
    # 学习率预热
    # ============================================================

    warmup_epochs: float = Field(
        default=3.0, ge=0,
        description="预热轮数",
        json_schema_extra={
            "group":    "学习率预热",
            "examples": [0.0, 1.0, 3.0, 5.0],
            "tips": [
                "前 N 轮逐渐增加学习率, 避免初期震荡",
                "3-5 轮通常足够",
                "0 表示禁用预热",
            ],
            "yaml_comment": "学习率预热轮数",
        },
    )

    warmup_momentum: float = Field(
        default=0.8, ge=0, le=1.0,
        description="预热初始动量",
        json_schema_extra={
            "group":    "学习率预热",
            "examples": [0.5, 0.8, 0.9],
            "tips": [
                "预热阶段的初始动量, 逐渐增加到 momentum",
                "一般保持默认值",
            ],
            "yaml_comment": "预热阶段初始动量",
        },
    )

    warmup_bias_lr: float = Field(
        default=0.1, ge=0,
        description="预热 bias 学习率",
        json_schema_extra={
            "group":    "学习率预热",
            "examples": [0.0, 0.1, 0.2],
            "tips": [
                "预热阶段 bias 层的学习率",
                "通常设为 lr0 的 10 倍",
                "一般保持默认值",
            ],
            "yaml_comment": "预热阶段 bias 学习率",
        },
    )

    # ============================================================
    # 损失权重
    # ============================================================

    box: float = Field(
        default=7.5, ge=0,
        description="Box Loss 权重",
        json_schema_extra={
            "group":    "损失权重",
            "examples": [5.0, 7.5, 10.0],
            "tips": ["边界框回归损失权重", "定位不准时可增大"],
            "yaml_comment": "Box Loss 权重",
        },
    )

    cls: float = Field(
        default=0.5, ge=0,
        description="Cls Loss 权重",
        json_schema_extra={
            "group":    "损失权重",
            "examples": [0.3, 0.5, 1.0],
            "tips": ["分类损失权重", "类别混淆严重时可增大"],
            "yaml_comment": "Cls Loss 权重",
        },
    )

    dfl: float = Field(
        default=1.5, ge=0,
        description="DFL Loss 权重",
        json_schema_extra={
            "group":    "损失权重",
            "examples": [1.0, 1.5, 2.0],
            "tips": ["Distribution Focal Loss 权重", "改善边界框质量"],
            "yaml_comment": "DFL Loss 权重",
        },
    )

    pose: float = Field(
        default=12.0, ge=0,
        description="Pose Loss 权重(姿态任务)",
        json_schema_extra={
            "group":    "损失权重",
            "examples": [10.0, 12.0, 15.0],
            "tips": ["仅姿态估计任务", "检测任务时不生效"],
            "yaml_comment": "Pose Loss 权重(仅姿态任务)",
        },
    )

    kobj: float = Field(
        default=2.0, ge=0,
        description="Keypoint Obj Loss 权重(姿态任务)",
        json_schema_extra={
            "group":    "损失权重",
            "examples": [1.0, 2.0, 3.0],
            "tips": ["仅姿态估计任务", "关键点置信度损失"],
            "yaml_comment": "Keypoint Obj Loss 权重",
        },
    )

    nbs: int = Field(
        default=64, ge=1,
        description="标称批次大小",
        json_schema_extra={
            "group":    "损失权重",
            "examples": [16, 32, 64],
            "tips": ["用于损失归一化", "与实际 batch 可以不同", "一般保持默认值 64"],
            "yaml_comment": "标称批次大小(损失归一化)",
        },
    )

    # ============================================================
    # 数据增强 - 颜色
    # ============================================================

    hsv_h: float = Field(
        default=0.015, ge=0.0, le=1.0,
        description="色调扰动",
        json_schema_extra={
            "group":    "数据增强-颜色",
            "examples": [0.0, 0.015, 0.05],
            "tips": ["HSV 色调扰动幅度", "0 表示禁用", "光照变化大时可增大"],
            "yaml_comment": "色调扰动(0-1)",
        },
    )

    hsv_s: float = Field(
        default=0.7, ge=0.0, le=1.0,
        description="饱和度扰动",
        json_schema_extra={
            "group":    "数据增强-颜色",
            "examples": [0.0, 0.5, 0.7],
            "tips": ["HSV 饱和度扰动幅度", "0.7 为中等增强"],
            "yaml_comment": "饱和度扰动(0-1)",
        },
    )

    hsv_v: float = Field(
        default=0.4, ge=0.0, le=1.0,
        description="亮度扰动",
        json_schema_extra={
            "group":    "数据增强-颜色",
            "examples": [0.0, 0.3, 0.4],
            "tips": ["HSV 亮度扰动幅度", "明暗变化大时可增大"],
            "yaml_comment": "亮度扰动(0-1)",
        },
    )

    bgr: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="BGR 通道翻转概率",
        json_schema_extra={
            "group":    "数据增强-颜色",
            "examples": [0.0, 0.1, 0.5],
            "tips": ["RGB ↔ BGR 随机翻转", "增强颜色鲁棒性", "一般不需要开启"],
            "yaml_comment": "BGR 通道翻转概率(0-1)",
        },
    )

    # ============================================================
    # 数据增强 - 几何
    # ============================================================

    degrees: float = Field(
        default=0.0, ge=0.0, le=180.0,
        description="随机旋转角度",
        json_schema_extra={
            "group":    "数据增强-几何",
            "examples": [0.0, 10.0, 30.0],
            "tips": ["随机旋转最大角度", "物体方向多样时可增大", "建议 10-30 度"],
            "yaml_comment": "随机旋转角度(0-180)",
        },
    )

    translate: float = Field(
        default=0.1, ge=0.0, le=1.0,
        description="随机平移比例",
        json_schema_extra={
            "group":    "数据增强-几何",
            "examples": [0.0, 0.1, 0.2],
            "tips": ["图像平移的最大比例", "0.1 表示最多平移 10%"],
            "yaml_comment": "随机平移比例(0-1)",
        },
    )

    scale: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="随机缩放增益",
        json_schema_extra={
            "group":    "数据增强-几何",
            "examples": [0.0, 0.3, 0.5],
            "tips": ["图像缩放增益范围", "0.5 表示 0.5-1.5 倍缩放"],
            "yaml_comment": "随机缩放增益(0-1)",
        },
    )

    shear: float = Field(
        default=0.0, ge=-180.0, le=180.0,
        description="随机错切角度",
        json_schema_extra={
            "group":    "数据增强-几何",
            "examples": [0.0, 2.0, 5.0],
            "tips": ["图像错切变换角度", "一般不需要太大", "建议 0-5 度"],
            "yaml_comment": "随机错切角度(-180到180)",
        },
    )

    perspective: float = Field(
        default=0.0, ge=0.0, le=0.001,
        description="随机透视变换",
        json_schema_extra={
            "group":    "数据增强-几何",
            "examples": [0.0, 0.0001, 0.0005],
            "tips": ["透视变换幅度", "0 表示禁用", "一般保持较小值"],
            "yaml_comment": "透视变换幅度(0-0.001)",
        },
    )

    flipud: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="上下翻转概率",
        json_schema_extra={
            "group":    "数据增强-几何",
            "examples": [0.0, 0.5],
            "tips": ["物体上下对称时可开启", "大多数情况保持 0"],
            "yaml_comment": "上下翻转概率(0-1)",
        },
    )

    fliplr: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="左右翻转概率",
        json_schema_extra={
            "group":    "数据增强-几何",
            "examples": [0.0, 0.5, 1.0],
            "tips": ["物体左右对称时推荐开启", "常用的数据增强手段"],
            "yaml_comment": "左右翻转概率(0-1)",
        },
    )

    # ============================================================
    # 数据增强 - 拼接混合
    # ============================================================

    mosaic: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Mosaic 增强概率",
        json_schema_extra={
            "group":    "数据增强-拼接",
            "examples": [0.0, 0.5, 1.0],
            "tips": [
                "4 张图拼成一张",
                "1.0 表示总是使用",
                "增强小目标检测",
                "训练后期自动关闭(close_mosaic)",
            ],
            "yaml_comment": "Mosaic 增强概率(0-1)",
        },
    )

    mixup: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="MixUp 增强概率",
        json_schema_extra={
            "group":    "数据增强-拼接",
            "examples": [0.0, 0.1, 0.15],
            "tips": ["两张图混合", "0.1-0.15 为合理范围", "可提升泛化能力"],
            "yaml_comment": "MixUp 增强概率(0-1)",
        },
    )

    copy_paste: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Copy-Paste 增强概率(分割)",
        json_schema_extra={
            "group":    "数据增强-拼接",
            "examples": [0.0, 0.1, 0.5],
            "tips": ["仅实例分割任务使用", "复制粘贴实例到其他图像"],
            "yaml_comment": "Copy-Paste 概率(仅分割, 0-1)",
        },
    )

    # ============================================================
    # 验证和输出
    # ============================================================

    val: bool = Field(
        default=True,
        description="训练期间验证",
        json_schema_extra={
            "group":    "验证和输出",
            "examples": [True, False],
            "tips": [
                "True: 每轮后在验证集上评估",
                "False: 不验证(快速调试用)",
                "正式训练必须开启",
            ],
            "yaml_comment": "是否在训练期间验证",
        },
    )

    plots: bool = Field(
        default=True,
        description="生成训练曲线图",
        json_schema_extra={
            "group":    "验证和输出",
            "examples": [False, True],
            "tips": ["生成损失曲线、mAP 曲线等", "保存在输出目录"],
            "yaml_comment": "是否生成训练可视化图",
        },
    )

    save_period: int = Field(
        default=-1,
        description="检查点保存周期",
        json_schema_extra={
            "group":    "验证和输出",
            "examples": [-1, 10, 20, 50],
            "tips": [
                "-1: 只保存 last.pt 和 best.pt",
                "> 0: 每 N 轮保存一次检查点",
                "长时间训练推荐开启",
            ],
            "yaml_comment": "检查点保存周期(-1=禁用)",
        },
    )

    # ============================================================
    # 任务特定
    # ============================================================

    overlap_mask: bool = Field(
        default=True,
        description="合并重叠 Mask(分割)",
        json_schema_extra={
            "group":    "任务特定",
            "examples": [True, False],
            "tips": ["仅实例分割任务使用", "True: 合并重叠 mask"],
            "yaml_comment": "是否合并重叠 mask(仅分割)",
        },
    )

    mask_ratio: int = Field(
        default=4, ge=1,
        description="Mask 下采样率(分割)",
        json_schema_extra={
            "group":    "任务特定",
            "examples": [2, 4, 8],
            "tips": ["仅实例分割任务使用", "mask 下采样倍数"],
            "yaml_comment": "Mask 下采样率(仅分割)",
        },
    )

    dropout: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Dropout 比例(分类)",
        json_schema_extra={
            "group":    "任务特定",
            "examples": [0.0, 0.2, 0.5],
            "tips": ["仅分类任务使用", "防止过拟合"],
            "yaml_comment": "Dropout 比例(仅分类, 0-1)",
        },
    )

    copy_paste_mode: str = Field(
        default="flip",
        description="Copy-Paste 模式(分割)",
        json_schema_extra={
            "group":    "任务特定",
            "examples": ["flip", "mixup"],
            "tips": ["仅分割任务", "flip: 翻转模式", "mixup: 混合模式"],
            "yaml_comment": "Copy-Paste 模式(flip / mixup, 仅分割)",
        },
    )

    auto_augment: str = Field(
        default="randaugment",
        description="自动增强策略(分类)",
        json_schema_extra={
            "group":    "任务特定",
            "examples": ["randaugment", "autoaugment", "augmix"],
            "tips": ["仅分类任务"],
            "yaml_comment": "自动增强策略(仅分类)",
        },
    )

    erasing: float = Field(
        default=0.4, ge=0.0, le=0.9,
        description="随机擦除概率(分类)",
        json_schema_extra={
            "group":    "任务特定",
            "examples": [0.0, 0.2, 0.4],
            "tips": ["仅分类任务", "随机擦除图像区域"],
            "yaml_comment": "随机擦除概率(仅分类, 0-0.9)",
        },
    )

    # ============================================================
    # 高级设置
    # ============================================================

    pretrained: Union[bool, str] = Field(
        default=True,
        description="预训练权重",
        json_schema_extra={
            "group":    "高级设置",
            "examples": [True, False, "path/to/weights.pt"],
            "tips": [
                "True: 使用官方预训练权重",
                "False: 从头训练",
                "str: 自定义权重路径",
                "小数据集强烈推荐使用预训练",
            ],
            "yaml_comment": "预训练权重(True / False / path)",
        },
    )

    single_cls: bool = Field(
        default=False,
        description="单类训练模式",
        json_schema_extra={
            "group":    "高级设置",
            "examples": [False, True],
            "tips": ["True: 将多类数据集视为单类", "特殊场景使用"],
            "yaml_comment": "是否单类训练",
        },
    )

    classes: Optional[List[int]] = Field(
        default=None,
        description="训练指定类别",
        json_schema_extra={
            "group":    "高级设置",
            "examples": [None, [0], [0, 1, 2]],
            "tips": ["None: 训练所有类别", "list: 只训练指定类别 ID"],
            "yaml_comment": "训练指定类别(None / [0,1,2])",
        },
    )

    compile: Union[bool, str] = Field(
        default=False,
        description="模型编译(PyTorch 2.0+)",
        json_schema_extra={
            "group":    "高级设置",
            "examples": [False, True, "default"],
            "tips": ["PyTorch 2.0+ 支持", "首次编译会较慢"],
            "yaml_comment": "是否编译模型(PyTorch 2.0+)",
        },
    )

    profile: bool = Field(
        default=False,
        description="速度分析",
        json_schema_extra={
            "group":    "高级设置",
            "examples": [False, True],
            "tips": ["ONNX / TensorRT 速度分析", "训练时一般不需要"],
            "yaml_comment": "是否进行速度分析",
        },
    )

    augmentations: Optional[List[Any]] = Field(
        default=None,
        description="自定义增强(Albumentations)",
        json_schema_extra={
            "group":    "高级设置",
            "examples": [None],
            "tips": ["None: 使用默认增强", "list: 自定义 Albumentations 变换"],
            "yaml_comment": "自定义增强(高级用户)",
        },
    )

    # ============================================================
    # 验证器
    # ============================================================

    @field_validator("task")
    @classmethod
    def _validate_task(cls, v: str) -> str:
        """task 必须在 Task SSoT 范围内(拒绝 'detect_v1' / 'pose' 等)"""
        if v not in Task.all():
            raise ValueError(
                f"task 必须是 {sorted(Task.all())} 之一, 当前值: {v!r}. "
                f"若想给本次实验取名, 请使用 experiment_name 字段."
            )
        return v

    @field_validator("copy_paste_mode")
    @classmethod
    def _validate_copy_paste_mode(cls, v: str) -> str:
        if v not in {"flip", "mixup"}:
            raise ValueError(f"copy_paste_mode 必须是 'flip' 或 'mixup', 当前: {v!r}")
        return v

    @field_validator("compile")
    @classmethod
    def _validate_compile(cls, v: Union[bool, str]) -> Union[bool, str]:
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def _cross_field_validation(self) -> "YOLOTrainConfig":
        """跨字段验证: save / save_period / mosaic / close_mosaic 的合理性"""

        # save=False 时不应再设置 save_period > 0 — 矛盾意图
        if not self.save and self.save_period > 0:
            raise ValueError(
                "save=False 时不应设置 save_period > 0. "
                "如果想关闭检查点保存, save_period 也应设为 -1; "
                "如果想周期性保存, save 必须为 True."
            )

        # close_mosaic 在 mosaic=0 时无效 — 冗余但不阻塞
        if self.close_mosaic > 0 and self.mosaic == 0.0:
            warnings.warn(
                "mosaic=0.0 但设置了 close_mosaic > 0, "
                "close_mosaic 将不会生效.",
                UserWarning,
            )

        return self
```

完整代码约 580 行——但其中约 500 行是字段定义和元数据 ("一字段一长块"). **真正的 "逻辑" 只有 4 个 validator**——大头还是把 ultralytics 文档翻译成 Pydantic Field. 这一阶段的工作量在 "把所有字段都摆对地方", 不在 "写代码很难".

## 3.7.5 完整代码: infer.py

`apps/platform/src/odp_platform/runtime_config/infer.py`:

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : infer.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统——YOLO 推理配置类
"""YOLO 推理配置: YOLOInferConfig.

继承 BaseConfig + 添加 17 个推理特有字段, 分 5 组:
    核心参数 / 推理控制 / 视频流 / 输出控制 / 任务特定

★ 跟 val 的关键区别:
   1. source 字段 (推理输入: 图/视频/目录/URL/摄像头) —— val 没有
   2. conf 默认 0.25 —— val 默认 0.001 (语义不同)
   3. 视频流字段 (vid_stride, stream, stream_buffer)
   4. 输出可视化字段 (show_labels, line_width 等)
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing  import Any, ClassVar, List, Optional, Union

from pydantic import Field, field_validator, model_validator

from odp_platform.common.constants     import Task
from odp_platform.runtime_config.base import BaseConfig


class YOLOInferConfig(BaseConfig):
    """YOLO 推理配置: 继承 BaseConfig + 17 个推理特有字段."""

    # ============================================================
    # 框架级字段扩展: 跟 val 同款 — experiment_name + task 不传给 ultralytics
    # ============================================================
    FRAMEWORK_ONLY_FIELDS: ClassVar[set[str]] = (
        BaseConfig.FRAMEWORK_ONLY_FIELDS | {"experiment_name", "task"}
    )

    # ============================================================
    # 核心参数 (task / experiment_name / source)
    # ============================================================

    task: str = Field(
        default=Task.DETECT,
        description="任务类型(SSoT, 封闭取值)",
        json_schema_extra={
            "group":    "核心参数",
            "examples": list(Task.all()),
            "tips": [
                "限定取值: " + " / ".join(Task.all()),
                "推理时从模型权重自动推断, 此处仅用于日志和目录组织",
                "想给实验起名? → 用 experiment_name 字段",
            ],
            "yaml_comment": "任务类型(只能是 detect / segment)",
        },
    )

    experiment_name: Optional[str] = Field(
        default=None,
        description="实验名(目录组织, 不影响推理结果)",
        json_schema_extra={
            "group":    "核心参数",
            "examples": ["helmet_demo", "video_test", "rtsp_stream_v1", None],
            "tips": [
                "None: 由 ultralytics 自动生成 predict, predict2, ...",
                "自定义: 用作 runs/<task>/<experiment_name>/ 子目录",
            ],
            "yaml_comment": "实验名(None=自动生成)",
        },
    )

    source: Optional[Union[str, Path]] = Field(
        default=None,
        description="推理输入源",
        json_schema_extra={
            "group":    "核心参数",
            "examples": [
                "image.jpg",
                "video.mp4",
                "path/to/images/",
                "rtsp://example.com/live.sdp",
                "0",
                "https://example.com/img.jpg",
            ],
            "tips": [
                "支持: 图像 / 视频 / 目录 / URL / 摄像头索引 / RTSP 流",
                "目录: 自动遍历所有图像文件",
                "0 / '0' / 1: 摄像头编号",
                "None: 必须通过 CLI 传 --source (运行时)",
            ],
            "yaml_comment": "推理输入源(图/视频/目录/URL/摄像头/流)",
        },
    )

    # ============================================================
    # 推理控制
    # ============================================================

    conf: float = Field(
        default=0.25,                   # ★ vs val 的 0.001
        ge=0.0, le=1.0,
        description="置信度阈值",
        json_schema_extra={
            "group":    "推理控制",
            "examples": [0.1, 0.25, 0.5, 0.7],
            "tips": [
                "★ 推理时 0.25-0.5 (过滤低置信度, 给用户看的)",
                "验证时是 0.001 (捕获所有预测, 算 mAP 用)",
                "工业部署常用 0.5+",
                "调高 = 漏检多但误检少",
            ],
            "yaml_comment": "置信度阈值(推理 0.25+, 验证 0.001)",
        },
    )

    iou: float = Field(
        default=0.7,
        ge=0.0, le=1.0,
        description="NMS IoU 阈值",
        json_schema_extra={
            "group":    "推理控制",
            "examples": [0.5, 0.7, 0.45],
            "tips": [
                "NMS 时重叠框去重的 IoU 阈值",
                "调高 = 保留更多重叠框",
                "调低 = 抑制更激进",
                "工业 0.5-0.7 较常用",
            ],
            "yaml_comment": "NMS IoU 阈值",
        },
    )

    max_det: int = Field(
        default=300,
        ge=1,
        description="单图最大检测数",
        json_schema_extra={
            "group":    "推理控制",
            "examples": [100, 300, 1000],
            "tips": [
                "单张图最多保留多少个检测框",
                "密集场景 (人群计数) 调大到 1000+",
                "稀疏场景 50-100 即可",
            ],
            "yaml_comment": "单图最大检测数",
        },
    )

    classes: Optional[List[int]] = Field(
        default=None,
        description="只检测指定类别",
        json_schema_extra={
            "group":    "推理控制",
            "examples": [None, [0], [0, 1, 2]],
            "tips": [
                "None: 检测所有类别",
                "list[int]: 只保留指定类别 ID 的检测结果",
                "类别 ID 由 data.yaml 的 names 决定",
            ],
            "yaml_comment": "只检测的类别 ID 列表(None=全部)",
        },
    )

    agnostic_nms: bool = Field(
        default=False,
        description="类别无关 NMS",
        json_schema_extra={
            "group":    "推理控制",
            "examples": [False, True],
            "tips": [
                "True: 不同类别之间也做 NMS",
                "False: 同类内 NMS, 不同类保留",
                "类别相互排斥时 (一个目标只属于一类) 开 True",
            ],
            "yaml_comment": "是否类别无关 NMS",
        },
    )

    augment: bool = Field(
        default=False,
        description="测试时增强 (TTA)",
        json_schema_extra={
            "group":    "推理控制",
            "examples": [False, True],
            "tips": [
                "True: 多尺度+翻转推理后融合, 精度↑速度↓",
                "False: 单次推理",
                "对比赛/打榜场景适用, 工业部署一般 False",
            ],
            "yaml_comment": "是否启用 TTA 测试时增强",
        },
    )

    # ============================================================
    # 视频/流
    # ============================================================

    vid_stride: int = Field(
        default=1,
        ge=1,
        description="视频抽帧间隔",
        json_schema_extra={
            "group":    "视频流",
            "examples": [1, 2, 5],
            "tips": [
                "每 N 帧推理一次",
                "1: 处理每一帧(默认)",
                "5: 每 5 帧推理一次(加速)",
                "仅对视频/流有效, 图像无视此参数",
            ],
            "yaml_comment": "视频抽帧间隔(每 N 帧推理一次)",
        },
    )

    stream: bool = Field(
        default=False,
        description="流式推理",
        json_schema_extra={
            "group":    "视频流",
            "examples": [False, True],
            "tips": [
                "True: 返回 generator (适合长视频/流, 内存友好)",
                "False: 返回 list (一次性出结果, 适合短视频/单图)",
                "实时摄像头 / RTSP 必须 True",
            ],
            "yaml_comment": "是否流式推理(长视频/实时流必须 True)",
        },
    )

    stream_buffer: bool = Field(
        default=False,
        description="流缓冲(防止丢帧)",
        json_schema_extra={
            "group":    "视频流",
            "examples": [False, True],
            "tips": [
                "True: 缓存所有帧, 慢但不丢",
                "False: 实时丢弃旧帧, 快但可能漏",
                "实时性要求高 → False; 离线分析 → True",
            ],
            "yaml_comment": "是否缓存所有帧(防丢帧但延迟↑)",
        },
    )

    # ============================================================
    # 输出控制
    # ============================================================

    save_txt: bool = Field(
        default=False,
        description="保存预测为 txt",
        json_schema_extra={
            "group":    "输出控制",
            "examples": [False, True],
            "tips": [
                "True: 输出 YOLO 格式 txt (每张图一份)",
                "用于后续半自动标注 / 二次审查",
            ],
            "yaml_comment": "是否保存预测结果为 txt",
        },
    )

    save_conf: bool = Field(
        default=False,
        description="txt 里包含置信度",
        json_schema_extra={
            "group":    "输出控制",
            "examples": [False, True],
            "tips": [
                "True: txt 行追加置信度 (cls x y w h conf)",
                "False: 标准 YOLO 格式 (cls x y w h)",
                "需要 save_txt=True 配套",
            ],
            "yaml_comment": "txt 中是否包含 conf",
        },
    )

    save_crop: bool = Field(
        default=False,
        description="裁剪检测框保存",
        json_schema_extra={
            "group":    "输出控制",
            "examples": [False, True],
            "tips": [
                "True: 把每个检测框抠出来单独存图",
                "用于人脸库 / 物体库构建",
            ],
            "yaml_comment": "是否裁剪检测框另存",
        },
    )

    save_frames: bool = Field(
        default=False,
        description="保存视频每一帧",
        json_schema_extra={
            "group":    "输出控制",
            "examples": [False, True],
            "tips": [
                "True: 视频推理时, 每一帧另存为图像",
                "False: 只输出标注视频",
                "调试 / 抽样审查用",
            ],
            "yaml_comment": "是否保存视频每一帧(仅 source 为视频时)",
        },
    )

    show: bool = Field(
        default=False,
        description="实时显示推理结果",
        json_schema_extra={
            "group":    "输出控制",
            "examples": [False, True],
            "tips": [
                "True: 弹窗实时显示 (需要 GUI)",
                "服务器/Docker 环境必须 False",
                "调试时用, 生产环境关",
            ],
            "yaml_comment": "是否弹窗显示(服务器环境必须 False)",
        },
    )

    show_labels: bool = Field(
        default=True,
        description="可视化是否带类别标签",
        json_schema_extra={
            "group":    "输出控制",
            "examples": [True, False],
            "tips": [
                "True: 检测框上方写类别名",
                "False: 只画框, 适合给非技术人员看",
            ],
            "yaml_comment": "可视化是否带类别标签",
        },
    )

    show_conf: bool = Field(
        default=True,
        description="可视化是否带置信度",
        json_schema_extra={
            "group":    "输出控制",
            "examples": [True, False],
            "tips": [
                "True: 类别名后追加 (0.87)",
                "False: 只显示类别名",
            ],
            "yaml_comment": "可视化是否带置信度",
        },
    )

    show_boxes: bool = Field(
        default=True,
        description="可视化是否画框",
        json_schema_extra={
            "group":    "输出控制",
            "examples": [True, False],
            "tips": [
                "True: 画矩形框 + 标签",
                "False: 只画标签, 不画框 (segment 任务有时用)",
            ],
            "yaml_comment": "可视化是否画框",
        },
    )

    line_width: Optional[int] = Field(
        default=None,
        ge=1,
        description="可视化线宽",
        json_schema_extra={
            "group":    "输出控制",
            "examples": [None, 2, 3, 5],
            "tips": [
                "None: 自动 (根据图像大小)",
                "int: 固定像素宽度",
                "大图建议 3-5, 小图 1-2",
            ],
            "yaml_comment": "可视化线宽(像素, None=自动)",
        },
    )

    # ============================================================
    # 任务特定
    # ============================================================

    retina_masks: bool = Field(
        default=False,
        description="高分辨率分割 mask",
        json_schema_extra={
            "group":    "任务特定",
            "examples": [False, True],
            "tips": [
                "仅 segment 任务: True 输出原图分辨率 mask",
                "False: 输出推理分辨率 mask (节省内存)",
                "detect 任务忽略此字段",
            ],
            "yaml_comment": "分割任务: 是否输出原图分辨率 mask",
        },
    )

    visualize: bool = Field(
        default=False,
        description="保存特征图可视化",
        json_schema_extra={
            "group":    "任务特定",
            "examples": [False, True],
            "tips": [
                "True: 保存模型各层的特征图",
                "调试 / 论文用",
                "会占大量磁盘, 生产环境关",
            ],
            "yaml_comment": "是否保存特征图(调试用)",
        },
    )

    embed: Optional[List[int]] = Field(
        default=None,
        description="提取指定层 embedding",
        json_schema_extra={
            "group":    "任务特定",
            "examples": [None, [10], [10, 20]],
            "tips": [
                "None: 不提取",
                "list[int]: 提取指定层索引的特征向量",
                "用于相似度检索 / 特征聚类",
            ],
            "yaml_comment": "提取指定层 embedding(None=不提取)",
        },
    )

    # ============================================================
    # 验证器
    # ============================================================

    @field_validator("task")
    @classmethod
    def _validate_task(cls, v: str) -> str:
        """task SSoT — 严格限定到 Task.all()"""
        if v not in Task.all():
            raise ValueError(
                f"task 必须是 {Task.all()} 之一, 当前值: {v!r}. "
                f"若想给本次实验取名, 请使用 experiment_name 字段."
            )
        return v

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: Any) -> Any:
        """source 类型标准化."""
        if v is None:
            return v
        if isinstance(v, (str, Path)):
            return str(v)
        if isinstance(v, int):
            # 摄像头索引整数: 转字符串保留 (跟 ultralytics 习惯一致)
            return str(v)
        raise TypeError(
            f"source 必须是 str / Path / int (摄像头索引) 或 None, "
            f"当前类型: {type(v).__name__}"
        )

    @model_validator(mode="after")
    def _cross_field_validation(self) -> "YOLOInferConfig":
        """跨字段验证 (全部 warn, 推理场景的'奇怪'都能跑)."""
        # save_conf 必须配套 save_txt
        if self.save_conf and not self.save_txt:
            warnings.warn(
                "save_conf=True 但 save_txt=False, save_conf 不会生效. "
                "若想保存置信度, save_txt 必须为 True.",
                UserWarning,
            )

        # stream_buffer 隐含 stream=True
        if self.stream_buffer and not self.stream:
            warnings.warn(
                "stream_buffer=True 但 stream=False, stream_buffer 不会生效. "
                "stream_buffer 仅在流式推理 (stream=True) 时有意义.",
                UserWarning,
            )

        # retina_masks 仅 segment 任务有效
        if self.retina_masks and self.task != Task.SEGMENT:
            warnings.warn(
                f"retina_masks=True 仅对 segment 任务有效, "
                f"当前 task={self.task!r}, 该字段将被忽略.",
                UserWarning,
            )

        return self
```

约 380 行代码, 17 个推理字段 + 3 个验证器 + 1 个跨字段验证. **比 val 字段更多, 但比 train 简单——推理场景的"输出怎么呈现"字段多, "怎么学习"字段没有**.

⚠️ **设计点 (4 个跨字段 warn 没一个 raise)**: 推理场景下的"配置奇怪"几乎都能继续跑, 只是某些字段不生效. 跟 val 的 `save vs save_period` 那种"自相矛盾" 不同, 这里都是 "意图清晰, 只是有冗余". 全部 warn 不挡路.

> **金句**: **"配置类的字段集决定了 ultralytics 接口的可见面——train 看到学习过程, val 看到指标计算, infer 看到结果呈现. 用同一份 BaseConfig 把三种视角粘到一起, 又在子类里各管各的差异——这是 D5 子类设计的核心.")**

## 3.8 完整代码: val.py

`apps/platform/src/odp_platform/runtime_config/val.py`:

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : val.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统——YOLO 验证配置类
"""YOLO 验证配置: YOLOValConfig.

继承 BaseConfig + 添加 11 个验证特有字段, 分 4 组:
    核心参数 / 验证控制 / 评估设置 / 任务特定

★ 跟 train 一致的设计:
   - task + experiment_name 拆分
   - extra='forbid' 拒绝拼错的字段名
   - 验证器走 field_validator / model_validator

★ 跟 train 不一致的地方:
   - val 模式下 task 不传给 ultralytics(从权重推断), FRAMEWORK_ONLY_FIELDS 多一个 task
   - conf 默认 0.001 (跟推理的 0.25 差两个数量级, 见 3.6 设计点 B)
"""
from __future__ import annotations

import warnings
from typing import ClassVar, Optional

from pydantic import Field, field_validator, model_validator

from odp_platform.common.constants import Task
from odp_platform.runtime_config.base import BaseConfig


class YOLOValConfig(BaseConfig):
    """YOLO 验证配置: 继承 BaseConfig + 11 个验证特有字段."""

    # ============================================================
    # 框架级字段扩展:
    #   - experiment_name 不传给 ultralytics
    #   - task 不传给 ultralytics(model.val() 从权重推断)
    # ============================================================
    FRAMEWORK_ONLY_FIELDS: ClassVar[set[str]] = (
        BaseConfig.FRAMEWORK_ONLY_FIELDS | {"experiment_name", "task"}
    )

    # ============================================================
    # 核心参数 (★ 跟 train 共享 task + experiment_name 设计)
    # ============================================================

    task: str = Field(
        default=Task.DETECT,
        description="任务类型(SSoT)",
        json_schema_extra={
            "group":    "核心参数",
            "examples": list(Task.all()),
            "tips": [
                "限定取值: " + " / ".join(Task.all()),
                "决定输出目录的一级子目录",
                "val 模式下不传给 ultralytics(从权重自动推断)",
            ],
            "yaml_comment": "任务类型(只能是 detect / segment)",
        },
    )

    experiment_name: Optional[str] = Field(
        default=None,
        description="实验名(只用作目录组织)",
        json_schema_extra={
            "group":    "核心参数",
            "examples": ["val_baseline", "val_helmet_v1", None],
            "tips": [
                "None: 由 ultralytics 自动生成 val / val2 / val3...",
                "自定义: 用作 runs/<task>/<experiment_name>/ 子目录",
            ],
            "yaml_comment": "实验名(目录组织, None=自动生成)",
        },
    )

    # ============================================================
    # 验证控制
    # ============================================================

    split: str = Field(
        default="val",
        description="数据集划分",
        json_schema_extra={
            "group":    "验证控制",
            "examples": ["val", "test", "train"],
            "tips": [
                "val: 使用验证集(默认)",
                "test: 使用测试集",
                "train: 使用训练集(调试用)",
                "对应 data.yaml 里的字段名",
            ],
            "yaml_comment": "数据集划分(val / test / train)",
        },
    )

    conf: Optional[float] = Field(
        default=0.001,
        ge=0.0, le=1.0,
        description="置信度阈值",
        json_schema_extra={
            "group":    "验证控制",
            "examples": [0.001, 0.25, 0.5],
            "tips": [
                "★ 验证时通常设 0.001 (捕获所有预测, 用于计算 mAP)",
                "推理时建议 0.25-0.5 (过滤低置信度)",
                "不影响最终模型, 仅影响评估指标",
            ],
            "yaml_comment": "置信度阈值(验证 0.001; 推理 0.25+)",
        },
    )

    iou: float = Field(
        default=0.6,
        ge=0.0, le=1.0,
        description="NMS IoU 阈值",
        json_schema_extra={
            "group":    "验证控制",
            "examples": [0.5, 0.6, 0.7],
            "tips": [
                "NMS(非极大值抑制) IoU 阈值",
                "COCO 标准: 0.6",
                "密集目标场景可提高到 0.7",
            ],
            "yaml_comment": "NMS IoU 阈值",
        },
    )

    max_det: int = Field(
        default=300, ge=1,
        description="每张图最大检测数",
        json_schema_extra={
            "group":    "验证控制",
            "examples": [100, 300, 1000],
            "tips": [
                "每张图像最多保留的检测框数量",
                "COCO 默认: 300",
                "密集目标场景可增加",
            ],
            "yaml_comment": "每张图最大检测数",
        },
    )

    # ============================================================
    # 评估设置
    # ============================================================

    half: bool = Field(
        default=True,
        description="半精度推理",
        json_schema_extra={
            "group":    "评估设置",
            "examples": [True, False],
            "tips": [
                "True: 使用 FP16 半精度(快 + 省显存)",
                "False: 使用 FP32 全精度",
                "现代 GPU 推荐开启",
                "CPU 验证时自动禁用",
            ],
            "yaml_comment": "是否使用半精度推理",
        },
    )

    plots: bool = Field(
        default=True,
        description="生成评估图表",
        json_schema_extra={
            "group":    "评估设置",
            "examples": [True, False],
            "tips": [
                "True: 生成混淆矩阵、PR 曲线等",
                "False: 不生成图表",
                "批量验证时可关闭以加速",
            ],
            "yaml_comment": "是否生成评估图表",
        },
    )

    save_json: bool = Field(
        default=True,
        description="保存 COCO JSON 结果",
        json_schema_extra={
            "group":    "评估设置",
            "examples": [False, True],
            "tips": [
                "True: 保存 COCO 格式的预测结果",
                "False: 不保存 JSON",
                "用于 COCO 官方评估工具",
                "提交比赛时需要开启",
            ],
            "yaml_comment": "是否保存 COCO JSON 格式结果",
        },
    )

    save_hybrid: bool = Field(
        default=False,
        description="保存混合标签",
        json_schema_extra={
            "group":    "评估设置",
            "examples": [False, True],
            "tips": ["True: 保存混合标签(预测 + 真实)", "False: 不保存", "调试和分析用"],
            "yaml_comment": "是否保存混合标签",
        },
    )

    # ============================================================
    # 任务特定
    # ============================================================

    mask_ratio: int = Field(
        default=4, ge=1,
        description="掩码下采样比例(分割)",
        json_schema_extra={
            "group":    "任务特定",
            "examples": [1, 2, 4],
            "tips": ["仅实例分割任务", "掩码相对原图的下采样倍数"],
            "yaml_comment": "掩码下采样比例(仅分割)",
        },
    )

    overlap_mask: bool = Field(
        default=True,
        description="重叠掩码(分割)",
        json_schema_extra={
            "group":    "任务特定",
            "examples": [True, False],
            "tips": ["仅实例分割任务", "True: 允许掩码重叠"],
            "yaml_comment": "是否允许掩码重叠(仅分割)",
        },
    )

    dnn: bool = Field(
        default=False,
        description="使用 OpenCV DNN",
        json_schema_extra={
            "group":    "任务特定",
            "examples": [False, True],
            "tips": [
                "True: 使用 OpenCV DNN 后端",
                "False: 使用 PyTorch(默认)",
                "DNN 适合边缘设备部署",
            ],
            "yaml_comment": "是否使用 OpenCV DNN 后端",
        },
    )

    # ============================================================
    # 验证器
    # ============================================================

    @field_validator("task")
    @classmethod
    def _validate_task(cls, v: str) -> str:
        """task 必须在 Task SSoT 范围内"""
        if v not in Task.all():
            raise ValueError(
                f"task 必须是 {sorted(Task.all())} 之一, 当前值: {v!r}. "
                f"若想给本次实验取名, 请使用 experiment_name 字段."
            )
        return v

    @field_validator("split")
    @classmethod
    def _validate_split(cls, v: str) -> str:
        """split 必须是 train / val / test"""
        valid = {"train", "val", "test"}
        if v not in valid:
            raise ValueError(f"split 必须是 {sorted(valid)} 之一, 当前: {v!r}")
        return v

    @model_validator(mode="after")
    def _cross_field_validation(self) -> "YOLOValConfig":
        """跨字段验证: segment 专属参数在 detect 任务下警告."""
        if self.task != Task.SEGMENT:
            # 用户在非 segment 任务下改了 segment 专属字段, 提醒一下
            offenders = []
            if self.mask_ratio != 4:
                offenders.append(f"mask_ratio={self.mask_ratio}")
            if self.overlap_mask is False:
                offenders.append(f"overlap_mask={self.overlap_mask}")

            if offenders:
                warnings.warn(
                    f"{' / '.join(offenders)} 仅对 segment 任务有效, "
                    f"当前 task={self.task!r}, 这些值将被忽略.",
                    UserWarning,
                )
        return self
```

val.py 约 240 行——比 train.py 短得多, 但 task / experiment_name 的对称设计完整保留. SSoT 跟 train 共用同一个 `Task.all()`, 错误信息也复用同一个模式.

⚠️ **设计点 (segment 守卫为什么用 `self.task != Task.SEGMENT` 不用字符串包含)**: SSoT 在 validator 里的硬保证. `task` 字段经过 `_validate_task` 后只可能是 `Task.all()` 里的值, 直接 `==` 比较语义清晰. **legacy 代码常见 `"segment" not in self.task` 这种字符串模糊匹配是因为旧 `task` 是开放字符串**——D5 拆完 task / experiment_name 后, 守卫规则应当跟字段语义一起对齐.

⚠️ **设计点 (`offenders` 列表, 不是分别 warn 多次)** 跨字段验证的常见反模式是逐字段独立 warn——`mask_ratio` 偏离 warn 一次, `overlap_mask` 偏离 warn 一次, 用户看到两条警告. **合并成一条警告含多个字段, 既减少日志噪声, 又让用户一眼看到"我在 segment 上改错了几处"**.

⚠️ **设计点 (为什么 task / experiment_name 在 train 和 val 完全重复定义, 没抽到 BaseConfig)** 看着重复, 但**有意为之**:
1. **不通用**——推理模式(infer)未来可能不需要 `task` 字段(直接从权重加载, 不参与目录组织). 放 BaseConfig 等于强加约束.
2. **元数据不同**——train 的 `experiment_name` 推荐命名是 `<model>_<dataset>_<key_param>`; val 的是 `val_<model_version>`. tips 里写的指导语自然不一样.
3. **行为不同**——train 的 task **传给** ultralytics; val 的 task **不传**. 同一字段两种命运, 抽不到一起.

**抽共同点不是机械的代码去重, 是语义去重**——语义不一样的字段, 看起来代码相同也别抽.

## 3.9 测试: train + val + infer 配置类

打开 Python REPL:

```python
from odp_platform.runtime_config.train import YOLOTrainConfig
from odp_platform.runtime_config.val   import YOLOValConfig
from odp_platform.common.constants     import Task

# ============================================================
# 1. 默认配置
# ============================================================
tc = YOLOTrainConfig()
print(f"✓ train.task           = {tc.task!r}")            # 'detect'
print(f"✓ train.experiment_name = {tc.experiment_name}")   # None
print(f"✓ train.epochs         = {tc.epochs}")            # 100
print(f"✓ train.optimizer      = {tc.optimizer!r}")        # 'auto'

vc = YOLOValConfig()
print(f"✓ val.task             = {vc.task!r}")            # 'detect'
print(f"✓ val.split            = {vc.split!r}")            # 'val'
print(f"✓ val.conf             = {vc.conf}")              # 0.001

# ============================================================
# 2. task 字段限定到 Task.all()
# ============================================================
try:
    YOLOTrainConfig(task="detect_v2")
except Exception as e:
    print(f"✓ 拒绝 task='detect_v2': {str(e)[:80]}")

try:
    YOLOValConfig(task="Detection")     # 大写 D 也拒
except Exception as e:
    print(f"✓ 拒绝 task='Detection': {str(e)[:80]}")

# 合法值通过
for t in Task.all():
    YOLOTrainConfig(task=t)
print(f"✓ 所有 Task.all() 值都接受: {sorted(Task.all())}")

# ============================================================
# 3. experiment_name 自由字符串
# ============================================================
tc = YOLOTrainConfig(experiment_name="helmet_v1_lr001")
print(f"✓ experiment_name 接受自由字符串: {tc.experiment_name!r}")

# ============================================================
# 4. FRAMEWORK_ONLY_FIELDS 在 train / val 不一样
# ============================================================
print(f"✓ train.FRAMEWORK_ONLY_FIELDS = {YOLOTrainConfig.FRAMEWORK_ONLY_FIELDS}")
# {'verbose', 'experiment_name'}
print(f"✓ val.FRAMEWORK_ONLY_FIELDS   = {YOLOValConfig.FRAMEWORK_ONLY_FIELDS}")
# {'verbose', 'experiment_name', 'task'}

# ============================================================
# 5. to_ultralytics_kwargs 的过滤
# ============================================================
tc = YOLOTrainConfig(task="detect", experiment_name="exp1", epochs=50)
kw = tc.to_ultralytics_kwargs()
assert "task"            in kw, "train 的 task 必须传"
assert "experiment_name" not in kw, "experiment_name 不传"
assert "verbose"         not in kw
print(f"✓ train kwargs 包含 task, 不含 experiment_name / verbose")

vc = YOLOValConfig(task="detect", experiment_name="vexp", split="test")
kw = vc.to_ultralytics_kwargs()
assert "task"            not in kw, "val 的 task 不传(从权重推断)"
assert "experiment_name" not in kw
assert "split"           in kw, "split 必须传"
print(f"✓ val kwargs 不含 task / experiment_name, 含 split")

# ============================================================
# 6. 跨字段验证
# ============================================================
# 矛盾意图: save=False + save_period>0 — 应该 raise
try:
    YOLOTrainConfig(save=False, save_period=10)
except Exception as e:
    print(f"✓ 拒绝 save=False + save_period>0: {str(e)[:80]}")

# 冗余配置: mosaic=0 + close_mosaic=10 — 应该 warn 不 raise
import warnings
with warnings.catch_warnings(record=True) as ws:
    warnings.simplefilter("always")
    YOLOTrainConfig(mosaic=0.0, close_mosaic=10)
    assert any("close_mosaic 将不会生效" in str(w.message) for w in ws)
    print("✓ mosaic=0 + close_mosaic=10 触发警告(不阻塞)")

# ============================================================
# 7. extra='forbid' 从基类继承到子类
# ============================================================
try:
    YOLOTrainConfig(epchs=300)   # epochs 拼错
except Exception as e:
    print(f"✓ 拒绝拼错字段 epchs: {type(e).__name__}")

# ============================================================
# 8. split 限定取值
# ============================================================
try:
    YOLOValConfig(split="testing")     # 应该是 'test'
except Exception as e:
    print(f"✓ 拒绝 split='testing': {str(e)[:80]}")

# ============================================================
# 9. 字段分组完整性
# ============================================================
groups = tc.get_field_groups()
expected_train = {
    "核心参数", "训练控制", "优化器配置", "学习率预热",
    "损失权重", "数据增强-颜色", "数据增强-几何", "数据增强-拼接",
    "验证和输出", "任务特定", "高级设置",
    # BaseConfig 的:
    "输入配置", "设备配置", "输出配置", "基础设置",
}
assert expected_train <= set(groups.keys()), \
    f"缺失分组: {expected_train - set(groups.keys())}"
print(f"✓ train 字段分组完整: {len(groups)} 个分组")
# ============================================================
# infer: YOLOInferConfig (★ D5 推理闭环测试)
# ============================================================
from odp_platform.runtime_config.infer import YOLOInferConfig

# 默认配置
c_infer = YOLOInferConfig()
assert c_infer.task == Task.DETECT
assert c_infer.conf == 0.25                   # ★ vs val 默认 0.001
assert c_infer.source is None
assert c_infer.iou == 0.7
print(f"✓ YOLOInferConfig 默认: conf={c_infer.conf}, iou={c_infer.iou}")

# task 验证跟 train/val 同款
try:
    YOLOInferConfig(task="detect_v2")
except Exception as e:
    assert "experiment_name" in str(e)
    print("✓ infer task 拒绝非法值, 错误信息指引 experiment_name")

# source 类型标准化
c1 = YOLOInferConfig(source="image.jpg")
assert c1.source == "image.jpg"
c2 = YOLOInferConfig(source=0)           # 摄像头索引
assert c2.source == "0"
print("✓ source 接受 str / int (摄像头索引)")

# FRAMEWORK_ONLY_FIELDS 跟 val 同款
assert "task" in YOLOInferConfig.FRAMEWORK_ONLY_FIELDS
assert "experiment_name" in YOLOInferConfig.FRAMEWORK_ONLY_FIELDS
kw_infer = c1.to_ultralytics_kwargs()
assert "task" not in kw_infer, "infer 的 task 不传给 ultralytics"
assert "source" in kw_infer, "source 必须传给 ultralytics"
print("✓ to_ultralytics_kwargs: 含 source, 不含 task")

# 跨字段警告: save_conf 无 save_txt
import warnings
with warnings.catch_warnings(record=True) as ws:
    warnings.simplefilter("always")
    YOLOInferConfig(save_conf=True, save_txt=False)
    assert any("save_conf=True 但 save_txt=False" in str(w.message) for w in ws)
print("✓ save_conf 无 save_txt 触发警告")

# 跨字段警告: retina_masks 在 detect 任务下
with warnings.catch_warnings(record=True) as ws:
    warnings.simplefilter("always")
    YOLOInferConfig(retina_masks=True, task=Task.DETECT)
    assert any("retina_masks=True 仅对 segment" in str(w.message) for w in ws)
print("✓ retina_masks 在 detect 任务下触发警告")

print("\n--- 阶段 3 测试通过 ---")
```

应该全部 ✓.

## 3.10 git commit

```bash
git add apps/platform/src/odp_platform/runtime_config/train.py
git add apps/platform/src/odp_platform/runtime_config/val.py
git commit -m "feat(runtime_config): add YOLOTrainConfig + YOLOValConfig with task/experiment_name split

runtime_config/train.py:
  + YOLOTrainConfig — extends BaseConfig with 52 training-specific fields
    Groups: 训练控制 / 优化器配置 / 学习率预热 / 损失权重 /
            数据增强-颜色 / 数据增强-几何 / 数据增强-拼接 /
            验证和输出 / 任务特定 / 高级设置
  + FRAMEWORK_ONLY_FIELDS extended with 'experiment_name'
  + 4 validators: task (SSoT) / copy_paste_mode / compile / cross-field
    cross-field validator handles:
      - save=False + save_period>0  → raise (contradictory intent)
      - mosaic=0 + close_mosaic>0   → warn  (redundant but harmless)

runtime_config/val.py:
  + YOLOValConfig — extends BaseConfig with 11 validation-specific fields
    Groups: 验证控制 / 评估设置 / 任务特定
  + FRAMEWORK_ONLY_FIELDS extended with 'experiment_name' AND 'task'
    (val.task is for output dir organization only; ultralytics infers
     the task from .pt weights, so we don't pass it)
  + 2 validators: task (SSoT) / split (train|val|test)

Key design — task / experiment_name split:
  legacy had task='detect_val' doing two jobs at once:
    1. semantic (SSoT: which CV task?)
    2. directory name (experiment identifier)
  When users wanted to name their experiments, they had to overload
  task='detect_baseline_v1', losing the SSoT meaning entirely.

  D5 splits this into two fields:
    - task: closed set {detect, segment}, validated against Task.all()
    - experiment_name: free-form string, only used by service layer
      for directory composition: runs/<task>/<experiment_name>/

  Both fields are in the '核心参数' group so users see them first
  when opening the generated YAML.

Notes:
  - task / experiment_name are duplicated in train.py and val.py
    intentionally — same name, different ultralytics-passing behavior:
      train.task: passed to model.train(task=...)
      val.task:   NOT passed (model.val() infers from weights)
  - copy_paste_mode/auto_augment defaults match ultralytics — not all
    fields apply to all tasks, but the field set mirrors the upstream
    API (config layer should reflect interface, not theory).
"
```

**中文版**:

```bash
git commit -m "feat(runtime_config): 新增 YOLOTrainConfig 和 YOLOValConfig 配置类" \
           -m "拆 task 和 experiment_name (★ D5 撞墙②的拆解):" \
           -m "  legacy 一个 task 字段同时承担两个正交职责:" \
           -m "    - 任务语义 (detect/segment, 应为 SSoT 封闭取值)" \
           -m "    - 实验标识 (用户给本次跑取的名字, 应为自由字符串)" \
           -m "  D5 拆为两个字段, validator 错误信息显式指引下一步." \
           -m "runtime_config/train.py:" \
           -m "  + YOLOTrainConfig —— 继承 BaseConfig + 52 个训练特有字段" \
           -m "    分 11 个组 (训练控制 / 优化器 / 学习率预热 / 损失权重 /" \
           -m "      数据增强-颜色 / 数据增强-几何 / 数据增强-拼接 /" \
           -m "      验证和输出 / 任务特定 / 高级设置)" \
           -m "  + task 验证器引用 D3 立的 Task.all() (SSoT 闭环)" \
           -m "  + 跨字段验证: save=False + save_period>0 直接 raise (矛盾)" \
           -m "                mosaic=0 + close_mosaic>0 warn (冗余但能跑)" \
           -m "  + FRAMEWORK_ONLY_FIELDS 扩展: 加 'experiment_name'" \
           -m "runtime_config/val.py:" \
           -m "  + YOLOValConfig —— 继承 BaseConfig + 11 个验证特有字段" \
           -m "    分组: 验证控制 / 评估设置 / 任务特定" \
           -m "  + split 字段限定 {train, val, test}" \
           -m "  + FRAMEWORK_ONLY_FIELDS 扩展: 加 'experiment_name' + 'task'" \
           -m "    (val 模式 ultralytics 从权重推断 task, 不接受外部传入)" \
           -m "  + 跨字段验证: segment 专属字段在 detect 任务下警告" \
           -m "关键设计:" \
           -m "  - 子类扩展用 ClassVar 集合运算 ('| {新字段}'), 不 override 方法" \
           -m "  - 字段分组按'调参时一起改'分, 不按'调参频率'分" \
           -m "  - val 的 conf 默认 0.001 (vs 推理时的 0.25+), 不通用字段就放子类"
```


至此, **训练 / 验证两套配置类完整就位**——共约 800 行代码, 63 个字段(15 共享 + 52 训练 + 11 验证, 其中 task/experiment_name 各算一次), 6 个验证器. 阶段 4 起处理 "配置如何从外部进入".

> **金句**: **"配置类的扩展点设计成 'ClassVar 集合 + 字段元数据', 子类就只用做加法; 设计成 '方法 override', 子类就开始重复祖宗代码. 数据驱动 vs 方法驱动, 直接决定基类好不好继承."**

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 3.11 git commit (infer)

YOLOInferConfig 是独立的一个文件, 单独一个 commit:

```bash
git add apps/platform/src/odp_platform/runtime_config/infer.py
git commit -m "feat(runtime_config): add YOLOInferConfig with source-required field" \
           -m "runtime_config/infer.py:" \
           -m "  + YOLOInferConfig — inherits BaseConfig + 17 inference-specific fields" \
           -m "    Groups: 核心参数 / 推理控制 / 视频流 / 输出控制 / 任务特定" \
           -m "  + source field (str | Path | int as camera index)" \
           -m "    Not in FRAMEWORK_ONLY_FIELDS — must be passed to model.predict()" \
           -m "  + conf default 0.25 (vs val's 0.001) — semantic difference" \
           -m "    val: low conf to capture all preds for mAP" \
           -m "    infer: higher conf to filter low-confidence predictions" \
           -m "  + FRAMEWORK_ONLY_FIELDS matches val: includes 'experiment_name', 'task'" \
           -m "    (model.predict() infers task from weights, same as model.val())" \
           -m "  + Cross-field warns (4 cases, all warn no raise):" \
           -m "    - save_conf=True needs save_txt=True" \
           -m "    - stream_buffer=True needs stream=True" \
           -m "    - retina_masks=True only effective on segment task" \
           -m "Why source is required-but-not-raised in config layer:" \
           -m "  YAML template generation needs source=null to be valid." \
           -m "  'Required at runtime' is service-layer concern (D8 InferService)," \
           -m "  config layer only validates value legality, not value presence."
```

中文版:

```bash
git commit -m "feat(runtime_config): 新增 YOLOInferConfig 推理配置类" \
           -m "runtime_config/infer.py:" \
           -m "  + YOLOInferConfig — 继承 BaseConfig + 17 个推理特有字段" \
           -m "    分组: 核心参数 / 推理控制 / 视频流 / 输出控制 / 任务特定" \
           -m "  + source 字段 (str | Path | int 摄像头索引)" \
           -m "    不在 FRAMEWORK_ONLY_FIELDS 里 —— 必须传给 model.predict()" \
           -m "  + conf 默认 0.25 (vs val 的 0.001) —— 语义差异:" \
           -m "    val: 低 conf 捕获所有预测算 mAP" \
           -m "    infer: 高 conf 过滤低置信度结果" \
           -m "  + FRAMEWORK_ONLY_FIELDS 跟 val 一致: 含 experiment_name + task" \
           -m "    (model.predict() 跟 model.val() 一样从权重推断 task)" \
           -m "  + 4 个跨字段警告 (全是 warn, 没有 raise):" \
           -m "    - save_conf=True 需要 save_txt=True" \
           -m "    - stream_buffer=True 需要 stream=True" \
           -m "    - retina_masks=True 仅 segment 任务生效" \
           -m "为什么 source 在配置层不做必填校验:" \
           -m "  YAML 模板生成时 source=null 必须合法 (让用户拿到模板后填)." \
           -m "  '运行时必填' 是 service 层 (D8) 的事," \
           -m "  配置层只管值合法性, 不管值有没有给."
```

⚠️ **设计点 (为什么 infer 单独一个 commit 而不是合并到 train/val commit)**: infer 的字段集跟 train/val 关联度低 (除了继承 BaseConfig). 单独一个 commit 让 git history 清楚地展示"配置子系统三个模式分三次稳定下来", 任何时候 git blame 都能定位到引入某个字段的原始上下文.

---
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 4: YAMLLoader + CLILoader——配置从外部进入

阶段 2-3 立好了配置类(BaseConfig + train + val), 但它们的 `__init__` 还是 `YOLOTrainConfig(epochs=100, ...)` 这种硬编码——**用户没法用**. 真实场景, 配置来自两个外部源:

1. **YAML 文件**——`configs/runtime/train.yaml`, 用户长期编辑保存
2. **CLI 参数**——`odp-train --epochs 200`, 临时覆盖

阶段 4 的目标: 写两个 **Loader**, 把这两类输入加载成统一的 dict, **不验证、不合并**——验证留给 Pydantic, 合并留给阶段 5 的 Merger.

> **金句**: **"Loader 的职责是 '把外部数据装进 dict', 不是 '把它们变成对的'——单一职责的边界要画清楚."**

## 4.1 为什么 Loader 不做验证、也不做合并?

朴素思路: 写一个大函数 `load_train_config()`, 同时 (a) 读 YAML, (b) 读 CLI, (c) 合并, (d) 验证. 一步到位看着方便, 实际上把 **4 个独立职责** 拧在一起, 任何一个出错都不知道是谁的锅.

D5 的分工:

```
        外部数据         单一职责模块             目的
─────────────────────────────────────────────────────────
configs/runtime/         YAMLLoader              加载 + fail-fast 错误
  train.yaml             (4.2 - 4.5)            (返回 dict, 不验证字段值)

CLI argparse             CLILoader               过滤 + 映射
  --epochs 200           (4.6)                  (返回 dict, 不验证字段值)

      ↓ 两个 dict ↓

ConfigMerger             Merger 阶段 5           合并 + 溯源
                                                (按优先级合, 记录每个值的来源)

      ↓ 一个 dict ↓

YOLOTrainConfig          Pydantic 验证           验证 + 类型转换
(阶段 2-3 已立)                                  (raise ValidationError)
```

每一层做完自己的事就交出去, **错误的责任永远精确**——YAML 格式坏了, YAMLLoader 报; 字段值非法, Pydantic 报; 来源说不清, Merger 报. 不会出现"它就是不工作"这种黑盒.

⚠️ **设计点 (Loader 不验证字段值, 但要验证文件格式)** 这俩不矛盾. "字段值合不合法" 是配置语义层面的问题 (`epochs=0` 该不该)——Pydantic 管. "YAML 顶层是不是 dict / 文件能不能解析" 是文件结构层面的问题——Loader 管. **结构 vs 语义, 两条线**.

## 4.2 YAMLLoader: 看似简单, 4 个细节都得想

```python
class YAMLLoader:
    """加载单个 YAML 配置文件, 返回 dict."""

    def __init__(self, config_dir: Optional[Union[str, Path]] = None):
        self.config_dir = Path(config_dir) if config_dir else None

    def load(self, filename: Union[str, Path]) -> Dict[str, Any]:
        ...
```

API 简到没朋友, 但 `load()` 的实现要想清楚 **4 件事**:

### 细节①: 路径解析——相对 or 绝对?

用户调用可能写:
- `loader.load("train.yaml")`——文件名, 期望从 `config_dir` 找
- `loader.load("configs/runtime/train.yaml")`——相对路径
- `loader.load("/abs/path/to/train.yaml")`——绝对路径

```python
def _resolve_path(self, filename: Union[str, Path]) -> Path:
    path = Path(filename)
    if path.is_absolute():
        return path
    if self.config_dir:
        return (self.config_dir / path).resolve()
    return path.resolve()
```

⚠️ **设计点 (`is_absolute()` 必须先判)** Windows 路径如 `C:\foo\bar.yaml`, Python `Path` 的 `is_absolute()` 是 True. 不先判, `self.config_dir / path` 在 Windows 上结果是 `C:\foo\bar.yaml`(Python `/` 操作符在第二个操作数是绝对路径时直接返回第二个), 看起来 "刚好对", 但 Linux 上行为不同——遇到 `/abs/path/file.yaml` 时 config_dir 也会被丢弃, 你以为 "都对了", 实际上是不同平台不同分支跑出来的对.

**判路径绝不绝对永远先判, 别靠 `/` 操作符的"凑巧表现"**.

### 细节②: 编码——UTF-8 与系统默认的 fallback

YAML 里中文很常见(咱们 yaml_comment 全是中文). 但用户也可能给 Windows 系统默认 GBK 编码保存的文件.

```python
try:
    content = filepath.read_text(encoding="utf-8")
except UnicodeDecodeError:
    logger.warning(f"UTF-8 解码失败, 尝试系统默认编码: {filepath}")
    content = filepath.read_text()
```

⚠️ **设计点 (默认 UTF-8 + 失败 fallback, 不是反过来)** 反例: 默认用系统编码读, 失败再试 UTF-8. Windows 用户传过来的 UTF-8 文件可能被 GBK 当成乱码 **不报错也不抛**(GBK 容错性差), 你拿到一堆乱码字符串当 yaml 解析, 出来一个崩烂的 dict, 排查极难. 反过来 UTF-8 严格, GBK 中文几乎必报 UnicodeDecodeError——**先严后宽, 错误才会暴露在合理的层**.

### 细节③: 解析失败 → fail-fast, 不返回空

```python
try:
    data = yaml.safe_load(content)
except yaml.YAMLError as e:
    raise ValueError(
        f"YAML 格式错误: {filepath}\n"
        f"原始错误: {e}\n"
        f"提示: 检查缩进、引号匹配、冒号后是否有空格."
    ) from e
```

⚠️ **设计点 (YAML 解析失败一定 raise)** 反例: `except: return {}`. 这样 yaml 里写错的 `epochs: 200\nbatch:\t16`(tab 缩进非法)被当成 "没填", 默认值 100 + 16 偷偷上场——用户 **以为自己跑了 batch=16, 实际跑了默认值**. 等同于阶段 1 伤痛② 的隐藏版本, **解析错误必须当面 raise**.

`raise ... from e` 保留原 exception chain, traceback 里能看到底层 `yaml.YAMLError` 具体抱怨什么(行号、列号), 用户改 yaml 时有线索.

### 细节④: 顶层不是 dict——立刻 raise

```python
if data is None:
    return {}     # 空文件合法, 等同于 "全用默认值"

if not isinstance(data, dict):
    raise ValueError(
        f"YAML 顶层必须是字典, 当前是 {type(data).__name__}: {filepath}\n"
        f"内容预览: {str(data)[:100]}"
    )
```

⚠️ **设计点 (空文件返回 `{}`, 不 raise)** YAML 解析空文件返回 `None`. 用户故意留空 yaml(等价于 "全用默认") 是合理的——返回 `{}` 让默认值跑流程. 但如果不是空、是个 list 或 string, 就是结构性错误——必须 raise.

⚠️ **设计点 (`_drop_none` 过滤 yaml 的 null)**:

```python
def _drop_none(d: Mapping[str, Any]) -> Dict[str, Any]:
    """过滤 None 值, 保留 False / 0 / '' 等显式值"""
    return {k: v for k, v in d.items() if v is not None}
```

YAML 里允许 `epochs: null`(等同于 Python `None`). 在我们的语义里, "写了 null" 等同于 "没写"——后面的合并阶段, None 不该参与覆盖默认值. **过滤掉 None, 让默认值有机会生效**.

但 **`False` / `0` / `""` 必须保留**——这些是 **显式值**, 是用户有意识填的 "假". 反例: `lambda d: {k: v for k, v in d.items() if v}` ——把 `cache: false` / `epochs: 0` 也一起过滤了, 完全错了语义.

## 4.3 🧱 撞墙③: YAML 文件不存在该怎么办?

写到这里, 还有一个最容易踩的坑——**用户第一次跑, 还没生成 yaml 文件**, `configs/runtime/train.yaml` 根本不存在.

```python
loader = YAMLLoader(config_dir=RUNTIME_CONFIGS_DIR)
cfg = loader.load("train.yaml")    # 文件不存在的话呢?
```

可能的方案:

| 方案 | 行为 | 优点 | 缺点 |
|---|---|---|---|
| A. 自动生成默认模板 | 检测不存在 → 调 ConfigGenerator 写一份 → 返回空 dict 让默认值跑 | 用户什么都不用做 | **静默** —— 用户不知道有 yaml 已经生成 |
| B. 返回空 dict | 当文件存在但空文件处理, 默认值跑 | 简单 | 用户 **以为自己改的 yaml 在生效**, 实际从来没读到——最危险 |
| C. raise + 修复指引 | 报错告诉用户跑哪条命令生成模板 | 不会误以为 | 第一次稍麻烦 |

**legacy 选了方案 A**——`training/service.py` 里写的:

```python
# legacy: 自动生成 + 提示用户编辑后再跑
if not yaml_path.exists():
    print(f"配置文件不存在, 自动生成: {yaml_path}")
    self.generator.generate(...)
    print(f"✓ 已生成默认配置文件, 请根据需要修改后重新运行")
```

这个方案 **看着贴心其实埋雷**:

### legacy 方案 A 的两个真实场景

**场景 1: CI 流水线**:
- CI 镜像没把 `configs/runtime/train.yaml` 打进去
- 你跑 `odp-train --epochs 200` 想在 CI 里跑训练
- legacy 方案: 检测到文件没有 → 静默生成默认 yaml → 用默认值开跑
- 你 CI 跑 5 小时, 训练结果出来一看: epochs 是 100 (默认值), 不是你 CLI 指定的 200—— **CLI 优先级被默认值偷走的话另说, 但是 "你以为有 yaml, 实际是个新生成的默认 yaml" 这件事 CI 不会告诉你**
- 排查 30 分钟才发现

**场景 2: 改名拼错**:
- 你想改 `configs/runtime/train.yaml`, 不小心拷成了 `train_.yaml`(末尾下划线)
- 你跑 `odp-train --config train.yaml`(原始名)
- legacy 方案: 找 `train.yaml`, 不存在 → 立马生成一份新的, 你精心调过的 `train_.yaml` 跟实际跑的 yaml 不是同一份
- 你纳闷 "为啥我的 batch=32 不生效?", 因为你跑的是刚生成的默认 `batch=16` 的那份

**两个场景的共同点**: **"文件不存在"这个事实被静默处理掉了**——用户以为有, 实际没有. 这就是阶段 1 的伤痛②(没有验证 → 错误静默)在文件层面的翻版.

### D5 的方案: fail-fast + 修复指引

```python
if not filepath.exists():
    raise FileNotFoundError(
        f"YAML 配置文件不存在: {filepath}\n\n"
        f"请先生成默认配置模板:\n"
        f"  odp-gen-config {filepath.stem}\n\n"
        f"生成后编辑该文件再重新运行."
    )
```

3 件事一起做:
1. **raise**——文件不存在是异常情况, 必须停下
2. **告诉用户准确路径**——`filepath` 是绝对路径, 一眼看到去哪找
3. **给修复指引**——告诉用户 **下一条命令该跑啥**(不是 "你自己想办法生成")

⚠️ **设计点 (fail-fast 的报错必须带修复指引, 否则就是耍流氓)** 一条好的 fail-fast 报错 = "出了啥事" + "为啥不行" + "怎么修". 三个都有, 用户 5 秒理解; 缺一个, 用户就要查文档. **报错就是给下一个用户写的最后一份文档**, 写得清不清楚直接决定他骂不骂街.

⚠️ **设计点 (那 legacy 的"自动生成模板"功能就废了?)** 不废, 只是分开做. `odp-gen-config train` 这条命令(阶段 6)显式让用户生成模板, 但 **不再隐式在 loader 里偷偷生成**. **显式 vs 隐式, 这是关键**:

- 显式: 用户主动跑了 generator → 知道发生了什么 → 看到模板路径 → 心里有数
- 隐式: 用户什么都没做, 但 yaml 突然出现了 → 不知道 → 跑出来不对

**自动化是好的, 隐式自动化是糟糕的**.

> **金句**: **"`return {}` 和 `raise` 的差别看着只是 5 个字符, 实际上是 'CI 跑 5 小时然后骂街' 和 '5 秒看到报错改命令' 的差别. fail-fast 不是脾气, 是体谅."**

## 4.4 YAMLLoader 完整代码

`apps/platform/src/odp_platform/runtime_config/loaders.py` 第一部分:

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : loaders.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统——配置加载器
"""配置加载器: 从不同来源加载配置(不负责验证和合并).

- YAMLLoader: 加载 YAML 配置文件, 文件不存在 → fail-fast + 修复指引
- CLILoader:  加载命令行参数, 过滤控制字段 + 支持参数名映射

★ 设计原则: Loader 只把外部数据装进 dict, 不验证字段值, 不合并.
   - 字段值验证 → Pydantic (阶段 2-3 已立)
   - 多源合并   → ConfigMerger (阶段 5)
"""
from __future__ import annotations

import logging
from argparse import Namespace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

import yaml

logger = logging.getLogger(__name__)


# ============================================================
# 工具函数
# ============================================================

def _drop_none(d: Mapping[str, Any]) -> Dict[str, Any]:
    """过滤 None 值, 保留 False / 0 / '' 等显式值.

    YAML 的 null 等同于 "没写" — 在后续合并阶段, None 不该参与覆盖,
    应该让下层(默认值)有机会跑出来.

    但 False / 0 / '' 是用户显式填的 "假", 必须保留 —
    不要写成 `{k: v for k, v in d.items() if v}`(经典 falsy 误伤).
    """
    return {k: v for k, v in d.items() if v is not None}


# ============================================================
# YAMLLoader
# ============================================================

class YAMLLoader:
    """加载 YAML 配置文件 → dict.

    ★ 4 件事:
        1. 路径解析: 绝对 / 相对 / 文件名 都接受
        2. 编码: 默认 UTF-8, 失败 fallback 系统默认
        3. 解析: 失败 fail-fast (raise + 原 exception chain)
        4. 不存在: fail-fast + 修复指引

    使用示例:
        from odp_platform.common.paths import RUNTIME_CONFIGS_DIR
        loader = YAMLLoader(config_dir=RUNTIME_CONFIGS_DIR)
        cfg = loader.load("train.yaml")          # 文件名(从 config_dir 找)
        cfg = loader.load("/abs/path.yaml")      # 绝对路径
    """

    def __init__(self, config_dir: Optional[Union[str, Path]] = None):
        """
        Args:
            config_dir: 配置文件目录, 用于解析相对路径.
                       None 时相对路径基于当前目录.
        """
        self.config_dir = Path(config_dir) if config_dir else None

    def load(self, filename: Union[str, Path]) -> Dict[str, Any]:
        """加载 YAML 配置文件.

        Args:
            filename: 文件名或路径(相对 / 绝对)

        Returns:
            配置字典. 空文件返回 {} (合法, 等同 "全用默认值").

        Raises:
            FileNotFoundError: 文件不存在(带修复指引)
            ValueError:        YAML 格式错误 / 顶层不是 dict
        """
        # 1. 解析路径
        filepath = self._resolve_path(filename)

        # 2. 文件不存在 → fail-fast + 修复指引(★ 撞墙③)
        if not filepath.exists():
            raise FileNotFoundError(
                f"YAML 配置文件不存在: {filepath}\n\n"
                f"请先生成默认配置模板:\n"
                f"  odp-gen-config {filepath.stem}\n\n"
                f"生成后编辑该文件再重新运行."
            )

        # 3. 读文件(默认 UTF-8, 失败 fallback)
        try:
            content = filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logger.warning(f"UTF-8 解码失败, 尝试系统默认编码: {filepath}")
            content = filepath.read_text()

        # 4. 空文件 → 返回 {}, 等同 "全用默认值"
        if not content.strip():
            logger.debug(f"YAML 文件为空: {filepath}")
            return {}

        # 5. 解析 YAML — 失败 fail-fast, 保留 exception chain
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise ValueError(
                f"YAML 格式错误: {filepath}\n"
                f"原始错误: {e}\n"
                f"提示: 检查缩进、引号匹配、冒号后是否有空格."
            ) from e

        # 6. 顶层结构检查
        if data is None:
            return {}     # YAML 显式 null, 等同空文件

        if not isinstance(data, dict):
            raise ValueError(
                f"YAML 顶层必须是字典, 当前是 {type(data).__name__}: {filepath}\n"
                f"内容预览: {str(data)[:100]}"
            )

        # 7. 过滤 None 值(保留 False / 0 / '')
        return _drop_none(data)

    def _resolve_path(self, filename: Union[str, Path]) -> Path:
        """解析文件路径(★ 绝对路径必须先判, 详见 4.2 细节①)"""
        path = Path(filename)

        if path.is_absolute():
            return path

        if self.config_dir:
            return (self.config_dir / path).resolve()

        return path.resolve()
```

## 4.5 CLILoader: 比 YAML 简单, 但 4 个坑

CLILoader 把 `argparse.Namespace` 或 dict 转成统一字典, 但有 4 个细节:

### 坑①: 排除控制字段

argparse 里通常有几个 "不是配置, 是控制" 的字段, 比如:

- `--help` (布尔, 触发后程序立刻退, 不该进配置)
- `--config` / `--cfg` / `--yaml_path` (指定 yaml 文件路径, 它是 loader 的 "输入", 不是配置内容)
- `--debug` / `--version` (控制日志 / 输出版本号, 跟训练参数无关)

这些字段如果不排除, 会进配置 dict, 然后 Pydantic 验证时报"字段不存在"——但根本不该传到 Pydantic.

```python
DEFAULT_EXCLUDE = {
    "help",
    "config", "cfg", "yaml_path",
    "debug",
    "version",
}
```

### 坑②: 私有字段排除(`_xxx`)

argparse 自定义 action 偶尔会在 namespace 里塞 `_xxx` 前缀的字段. 一律排除:

```python
if key.startswith("_"):
    continue
```

### 坑③: None 值过滤

argparse 没传的可选参数默认值是 None. 不过滤的话, `cli_config["epochs"] = None` 进合并器, 会被当作 "用户显式给了 None", 把 yaml 里的 `epochs: 100` 给覆盖回 None——错的.

```python
if filter_none and value is None:
    continue
```

⚠️ **设计点 (filter_none 暴露成参数, 不写死)** 99% 场景 filter_none=True. 但偶尔需要 "用户显式传 --device None 表示用 CPU 默认", 这时关掉过滤. **暴露成参数, 不写死**, 留余地.

### 坑④: 参数名映射

有时 CLI 命名 不等于 Pydantic 字段名:

```bash
odp-train --learning-rate 0.001     # CLI 习惯用 --learning-rate
                                     # Pydantic 字段叫 lr0(对齐 ultralytics)
```

需要一个映射表:

```python
loader = CLILoader(mapping={"learning_rate": "lr0"})
```

注意 argparse 把 `--learning-rate` 转成 namespace 属性时已经把 `-` 改成 `_`, 所以映射表的 key 是 `learning_rate`.

⚠️ **设计点 (mapping 不该写死在 CLILoader 里)** 不同 CLI 入口(odp-train / odp-val)的 mapping 可能不同——比如 odp-val 里 `--checkpoint` 映射到 `model`. **CLILoader 不知道也不应该知道这些**, 让上层 CLI 入口告诉它. **通用工具不内置业务知识**, 这是 D2 立的纪律.

## 4.6 CLILoader 完整代码

继续 `loaders.py` 第二部分:

```python
# ============================================================
# CLILoader
# ============================================================

class CLILoader:
    """加载命令行参数 → dict.

    功能:
        - 接受 argparse.Namespace 或 dict
        - 排除控制字段(help / config / cfg / yaml_path / debug / version)
        - 排除私有字段(_xxx)
        - 过滤 None 值(默认; 可关)
        - 支持参数名映射(CLI 名 → Pydantic 字段名)

    使用示例:
        loader = CLILoader()
        cfg = loader.load(args)                  # args 是 argparse.Namespace

        # 自定义排除 + 映射:
        loader = CLILoader(
            exclude=["my_flag"],
            mapping={"learning_rate": "lr0"},
        )
    """

    # 默认排除的控制字段(不该进配置 dict)
    DEFAULT_EXCLUDE: set[str] = {
        "help",
        "config", "cfg", "yaml_path",       # yaml 路径是 loader 的输入
        "debug",
        "version",
    }

    def __init__(
        self,
        exclude: Optional[List[str]] = None,
        mapping: Optional[Dict[str, str]] = None,
    ):
        """
        Args:
            exclude: 额外排除的字段列表(并入 DEFAULT_EXCLUDE)
            mapping: 参数名映射, {CLI 名: Pydantic 字段名}
        """
        self.exclude = self.DEFAULT_EXCLUDE | set(exclude or [])
        self.mapping = mapping or {}

    def load(
        self,
        args: Optional[Union[Namespace, Dict[str, Any]]] = None,
        filter_none: bool = True,
    ) -> Dict[str, Any]:
        """加载命令行参数.

        Args:
            args:        argparse.Namespace 或 dict.
                         None 表示没传 CLI, 返回 {}.
            filter_none: 是否过滤 None 值(默认 True, 99% 场景)

        Returns:
            配置字典.

        Raises:
            TypeError: args 不是 Namespace 或 dict
        """
        if args is None:
            return {}

        # 转字典
        if isinstance(args, Namespace):
            raw = vars(args)
        elif isinstance(args, dict):
            raw = args
        else:
            raise TypeError(
                f"args 必须是 argparse.Namespace 或 dict, "
                f"当前是 {type(args).__name__}"
            )

        # 过滤 + 映射
        result: Dict[str, Any] = {}
        for key, value in raw.items():
            # 排除控制字段 + 私有字段
            if key in self.exclude or key.startswith("_"):
                continue

            # 过滤 None
            if filter_none and value is None:
                continue

            # 参数名映射
            mapped_key = self.mapping.get(key, key)
            result[mapped_key] = value

        return result


# ============================================================
# 便捷函数: 一次性加载所有源
# ============================================================

def load_all_sources(
    yaml_path: Optional[Union[str, Path]] = None,
    yaml_dir: Optional[Union[str, Path]] = None,
    cli_args: Optional[Union[Namespace, Dict[str, Any]]] = None,
    cli_exclude: Optional[List[str]] = None,
    cli_mapping: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """一次性加载所有配置源 → {'yaml': ..., 'cli': ...}

    给上层(service 层 / Merger)的便捷入口, 不做合并.

    Args:
        yaml_path:    YAML 文件名或路径(None 跳过加载 yaml)
        yaml_dir:     YAML 文件目录(用于解析相对路径)
        cli_args:     命令行参数
        cli_exclude:  CLI 额外排除字段
        cli_mapping:  CLI 参数名映射

    Returns:
        {"yaml": {...}, "cli": {...}}

    使用示例:
        sources = load_all_sources(
            yaml_path="train.yaml",
            yaml_dir=RUNTIME_CONFIGS_DIR,
            cli_args=args,
        )
        merger.merge(YOLOTrainConfig, sources=[
            (ConfigSource.YAML, sources["yaml"]),
            (ConfigSource.CLI,  sources["cli"]),
        ])
    """
    yaml_config: Dict[str, Any] = {}
    if yaml_path:
        loader = YAMLLoader(config_dir=yaml_dir)
        yaml_config = loader.load(yaml_path)

    cli_loader = CLILoader(exclude=cli_exclude, mapping=cli_mapping)
    cli_config = cli_loader.load(cli_args)

    return {"yaml": yaml_config, "cli": cli_config}
```

⚠️ **设计点 (`load_all_sources` 是便捷函数, 不是必须)** Loader 各自能用就行——这函数只是减少上层重复代码. 阶段 5 / 6 的 Merger / Generator 都可以单独构造 Loader. **便捷函数不是封装层, 是糖**.

## 4.7 测试: YAMLLoader + CLILoader

打开 Python REPL:

```python
import tempfile
from pathlib  import Path
from argparse import Namespace

from odp_platform.runtime_config.loaders import (
    YAMLLoader, CLILoader, load_all_sources, _drop_none,
)

# ============================================================
# 1. _drop_none 保留显式 False / 0 / '' (★ 经典坑)
# ============================================================
filtered = _drop_none({
    "epochs":  100,
    "amp":     False,        # 显式 False, 必须保留
    "fraction": 0.0,         # 显式 0, 必须保留
    "name":    "",           # 显式空字符串, 必须保留
    "device":  None,         # None, 应该过滤
})
assert filtered == {"epochs": 100, "amp": False, "fraction": 0.0, "name": ""}
print("✓ _drop_none 保留 False / 0 / '', 过滤 None")

# ============================================================
# 2. YAMLLoader.load — 正常文件
# ============================================================
temp_dir = Path(tempfile.gettempdir())
ok = temp_dir / "ok.yaml"
ok.write_text("""
# 测试配置
model: yolo11n.pt
data: rsod.yaml
epochs: 100
batch: 16
lr0: 0.01
""", encoding="utf-8")

loader = YAMLLoader()
cfg = loader.load(ok)
print(f"✓ 正常 yaml 加载: {len(cfg)} 个字段")
assert cfg["epochs"] == 100 and cfg["lr0"] == 0.01

# ============================================================
# 3. YAMLLoader.load — 文件不存在 → fail-fast (★ 撞墙③)
# ============================================================
try:
    loader.load(temp_dir / "not_exist.yaml")
except FileNotFoundError as e:
    msg = str(e)
    assert "请先生成默认配置模板" in msg, "修复指引必须在错误信息里"
    assert "odp-gen-config" in msg
    print(f"✓ 文件不存在 fail-fast, 含修复指引")

# ============================================================
# 4. YAMLLoader.load — 空文件 / 显式 null 都返回 {}
# ============================================================
empty = temp_dir / "empty.yaml"
empty.write_text("", encoding="utf-8")
assert loader.load(empty) == {}

null_top = temp_dir / "null.yaml"
null_top.write_text("# 只有注释\n", encoding="utf-8")
assert loader.load(null_top) == {}
print("✓ 空文件 / 全注释 yaml 返回 {} (合法)")

# ============================================================
# 5. YAMLLoader.load — YAML 格式错误 → fail-fast
# ============================================================
bad = temp_dir / "bad.yaml"
bad.write_text("epochs: 100\n\tbatch: 16\n", encoding="utf-8")  # tab 缩进非法
try:
    loader.load(bad)
except ValueError as e:
    msg = str(e)
    assert "YAML 格式错误" in msg
    assert "检查缩进" in msg
    print(f"✓ YAML 格式错误 fail-fast, 带提示")

# ============================================================
# 6. YAMLLoader.load — 顶层不是 dict → fail-fast
# ============================================================
list_top = temp_dir / "list.yaml"
list_top.write_text("- 1\n- 2\n- 3\n", encoding="utf-8")
try:
    loader.load(list_top)
except ValueError as e:
    assert "顶层必须是字典" in str(e)
    print(f"✓ 顶层是 list 时 fail-fast")

# ============================================================
# 7. YAMLLoader._resolve_path — 绝对路径优先
# ============================================================
loader_with_dir = YAMLLoader(config_dir="/should/be/ignored")
# 绝对路径应该不受 config_dir 影响
assert loader_with_dir._resolve_path(ok).resolve() == ok.resolve()
print("✓ 绝对路径无视 config_dir")

# ============================================================
# 8. YAMLLoader — 过滤 yaml 里的 null, 保留 false / 0
# ============================================================
mixed = temp_dir / "mixed.yaml"
mixed.write_text("""
epochs: 100
device: null
amp: false
fraction: 0.0
""", encoding="utf-8")
cfg = loader.load(mixed)
assert "device" not in cfg, "yaml null 应该被过滤"
assert cfg["amp"] is False, "yaml false 必须保留"
assert cfg["fraction"] == 0.0, "yaml 0 必须保留"
print("✓ yaml null → 过滤; false / 0 → 保留")

# ============================================================
# 9. CLILoader — argparse.Namespace
# ============================================================
args = Namespace(
    model="yolo11n.pt",
    epochs=200,
    batch=32,
    config="train.yaml",        # 应该被排除(控制字段)
    help=False,                  # 应该被排除
    debug=True,                  # 应该被排除
    lr0=None,                    # 应该被过滤(None)
    _internal="hidden",          # 应该被排除(私有)
)
cli_loader = CLILoader()
cfg = cli_loader.load(args)
assert cfg == {"model": "yolo11n.pt", "epochs": 200, "batch": 32}
print(f"✓ CLILoader 排除控制字段、私有字段、None: {cfg}")

# ============================================================
# 10. CLILoader — 自定义排除
# ============================================================
args2 = Namespace(model="x.pt", epochs=10, my_flag=True)
cli_loader2 = CLILoader(exclude=["my_flag"])
cfg = cli_loader2.load(args2)
assert "my_flag" not in cfg
print(f"✓ CLILoader 自定义排除生效")

# ============================================================
# 11. CLILoader — 参数名映射
# ============================================================
args3 = Namespace(learning_rate=0.001)
cli_loader3 = CLILoader(mapping={"learning_rate": "lr0"})
cfg = cli_loader3.load(args3)
assert cfg == {"lr0": 0.001}
print(f"✓ CLILoader 参数名映射: learning_rate → lr0")

# ============================================================
# 12. CLILoader — args=None 返回 {}
# ============================================================
assert cli_loader.load(None) == {}
print("✓ CLILoader.load(None) → {}")

# ============================================================
# 13. CLILoader — 错误类型 fail-fast
# ============================================================
try:
    cli_loader.load("not a Namespace")
except TypeError as e:
    print(f"✓ CLILoader 拒绝非 Namespace/dict 输入")

# ============================================================
# 14. load_all_sources — 一次性
# ============================================================
sources = load_all_sources(
    yaml_path=ok,
    cli_args=Namespace(epochs=200, batch=32),
)
assert sources["yaml"]["epochs"] == 100
assert sources["cli"]["epochs"]  == 200
print(f"✓ load_all_sources: yaml + cli 两个 dict 各自独立")

# 清理临时文件
for f in [ok, empty, null_top, bad, list_top, mixed]:
    f.unlink(missing_ok=True)

print("\n--- 阶段 4 测试通过 ---")
```

应该全 ✓.

## 4.8 关于 fail-fast 报错信息的一个细节

阶段 4 的报错信息我特意都写得比较啰嗦, 这是 D5 一个隐性的纪律——**runtime_config 子系统的报错都是写给"明天的用户"看的, 不是写给"今天的开发"看的**.

比较一下两种写法:

```python
# 写法 A: 极简
raise FileNotFoundError(filepath)

# 写法 B: 含修复指引
raise FileNotFoundError(
    f"YAML 配置文件不存在: {filepath}\n\n"
    f"请先生成默认配置模板:\n"
    f"  odp-gen-config {filepath.stem}\n\n"
    f"生成后编辑该文件再重新运行."
)
```

A 的 traceback 上下文足够给当前开发自己定位; B 的报错信息把 "下一步该跑什么命令" 写进去, 用户复制粘贴报错的最后一行就解决了.

⚠️ **设计点 (报错信息也是 API)** 你的报错信息会被用户复制到搜索引擎、贴给同事问、出现在 CI 日志里——它跟函数签名一样, 是 **接口的一部分**. 把它写好的边际成本几乎为零, 但用户的体验差距巨大. **错误信息的可读性是工程素质**, 跟代码本身一样重要.

> **金句**: **"好的报错信息不是'技术上正确', 是'让下一个看到它的人知道接下来该怎么做'. 配置系统的报错尤其如此——用户离代码远, 离 yaml 近, 错误信息就是他和你之间唯一的对话."**

## 4.9 git commit

```bash
git add apps/platform/src/odp_platform/runtime_config/loaders.py
git commit -m "feat(runtime_config): add YAMLLoader + CLILoader with fail-fast

runtime_config/loaders.py:
  + YAMLLoader.load() — load YAML config file → dict
      - Path resolution: absolute / relative / filename (relative to config_dir)
      - Encoding: UTF-8 default, fallback to system encoding
      - Empty/null top → return {} (legal: 'use all defaults')
      - YAML parse error → raise ValueError with chain (raise ... from e)
      - Top not dict → raise ValueError with content preview
      - ★ File not found → raise FileNotFoundError with fix command:
          'odp-gen-config <stem>'
  + CLILoader.load() — argparse.Namespace | dict → filtered dict
      - DEFAULT_EXCLUDE: help / config / cfg / yaml_path / debug / version
      - Filter None values (configurable)
      - Filter private fields (_xxx)
      - Optional name mapping (CLI name → Pydantic field name)
  + load_all_sources() — convenience to call both loaders at once
  + _drop_none() — preserve False / 0 / '' (NOT a falsy filter)

Key design — why fail-fast on missing YAML:
  legacy auto-generated a default template silently when file was missing.
  This created two real failure modes:
    1. CI: ran 5 hours with wrong defaults, no signal that yaml was new
    2. Typo: 'train.yaml' vs 'train_.yaml' — the carefully tuned file
       was never read; a freshly generated one ran instead
  D5: raise FileNotFoundError with explicit fix command. Users see the
  problem in 5 seconds, copy-paste the command, edit the file, rerun.
  Auto-generation still exists — but only when explicitly invoked
  (阶段 6: python -m ...generator), never implicitly inside loaders.

Notes:
  - YAMLLoader doesn't validate field values (Pydantic's job)
  - CLILoader doesn't merge with YAML (Merger's job, stage 5)
  - Loader responsibility: external data → typed dict; nothing more.
  - _drop_none uses 'is not None' explicitly to avoid the classic
    'if v' falsy-trap (would silently drop amp=False, fraction=0.0).
"
```

**中文版**:

```bash
git commit -m "feat(runtime_config): 新增 YAMLLoader 和 CLILoader, 文件不存在时 fail-fast" \
           -m "runtime_config/loaders.py:" \
           -m "  + YAMLLoader —— 加载 YAML 配置文件 → dict" \
           -m "    路径解析: 绝对 / 相对 / 文件名 全接受" \
           -m "    编码: 默认 UTF-8, 失败 fallback 系统默认" \
           -m "    解析失败: 立即 raise, 保留 exception chain" \
           -m "    文件不存在: ★ fail-fast + 修复指引 (D5 撞墙③)" \
           -m "  + CLILoader —— 加载 argparse.Namespace 或 dict → dict" \
           -m "    过滤控制字段 (--config / --help 等)" \
           -m "    支持参数名映射 (CLI 名 → Pydantic 字段名)" \
           -m "    自动过滤 None (None ≠ 显式值)" \
           -m "  + load_all_sources 便捷函数 —— 一次加载所有源" \
           -m "为什么 fail-fast 而不是自动生成默认模板:" \
           -m "  legacy 行为: 文件不存在 → 静默生成默认 yaml → 用默认值开跑" \
           -m "  问题:" \
           -m "    - CI 场景: 训练 5 小时, 跑的是默认值不是用户预期" \
           -m "    - 改名拼错: 改了 train_.yaml, 跑的是新生成的 train.yaml" \
           -m "  D5 方案: raise FileNotFoundError + 告诉用户运行哪条命令生成" \
           -m "  显式 vs 隐式 —— 自动化是好的, 隐式自动化是糟糕的." \
           -m "关键设计:" \
           -m "  - Loader 不验证字段值 (留给 Pydantic), 不合并 (留给 Merger)" \
           -m "  - 报错信息 = '出了啥事' + '为啥不行' + '怎么修' 三件套" \
           -m "  - 路径判断 is_absolute() 必须先判, 别靠 '/' 操作符的凑巧行为"
```


至此, **配置可以从外部进入了**——YAML 文件 → dict, CLI args → dict. 但两个 dict 各自孤立, 还需要按优先级合并、还需要溯源——阶段 5 干这事.

> **金句**: **"读 YAML 和读 CLI 看着 5 行代码, 把 4 个细节(路径 / 编码 / 空文件 / 不存在)都想清楚就是一篇讲义. 工程的难度不在'写出来', 在'每一处的边界都想清楚'."**

---
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 5: ConfigMerger——三源合并 + 链表式溯源

阶段 4 的两个 Loader 各自把 YAML / CLI 装进 dict, 还差最后一步——**按优先级合并到一起, 喂给 Pydantic 配置类**. 加上阶段 1 伤痛③ 提到的"跑完不知道某个值是哪儿来的"问题, 这一阶段我们要解决两件事:

1. **优先级合并**: CLI > YAML > DEFAULT, 高优先级覆盖低优先级.
2. **配置溯源**: 每个最终生效的字段值, 必须能追溯到"我是谁、从哪儿来、覆盖了谁".

> **金句**: **"配置不是'参数表', 是'决策记录'——三个月后你回看, 它得能告诉你这个 `lr0=0.001` 当时是谁决定的、覆盖了谁."**

## 5.1 朴素合并: 一行 dict 解包能搞定吗?

最朴素的合并思路:

```python
defaults  = {"epochs": 100, "batch": 16, "lr0": 0.01}
yaml_cfg  = {"epochs": 200,             "lr0": 0.001}
cli_cfg   = {"epochs": 50}

merged = {**defaults, **yaml_cfg, **cli_cfg}
# → {"epochs": 50, "batch": 16, "lr0": 0.001}
```

一行解包. 后写的覆盖先写的, **数值上正确**. 那能用吗?

> 🤔 **思考题**: 这个 `merged` dict 能解决阶段 1 伤痛③ 吗? 三个月后你回看日志看到 `lr0=0.001`, 能告诉我是谁给的吗?
>
> **答**: 不能. `merged` 是个扁平 dict, 信息只剩"最后赢的那个值", 谁覆盖了谁、原值是啥、来源是谁——全丢. 朴素合并把 **信息熵全压缩了**.

这就是为什么要单独写一个 ConfigMerger, 而不是 5 行 dict 解包. **合并的过程要留痕迹**.

## 5.2 配置溯源: 平铺标记 vs 链表式

要追溯每个字段的来源, 最直观的设计:**每个字段配一个 `source` 标记**:

```python
# 平铺方案: 一字段一个 source
sources = {
    "epochs": "CLI",         # 50 是 CLI 给的
    "batch":  "DEFAULT",     # 16 是默认值
    "lr0":    "YAML",        # 0.001 是 YAML 给的
}
```

够吗? 看一个场景:

**场景**: 用户跑 `odp-train --epochs 50`, 想知道——

> "为啥我 yaml 里写了 `epochs: 200` 没生效?"

平铺方案能回答: `epochs` 的来源是 CLI(值 50). 但回答不了: **"在 CLI 覆盖之前, 它是 YAML 给的 200 还是默认值 100?"** 这一段历史被吃掉了.

更糟的场景: 实习生说 "我把 yaml 改成 `epochs: 200` 了, 为啥跑出来是 50?" 你要回答 "你 CLI 里加了 `--epochs 50`, 覆盖掉了你 yaml 的 200, 不是 yaml 没生效". 平铺方案给不出 "覆盖链", 你只能反复说"你看下你 CLI 敲了啥".

**链表式溯源** 解决这个问题——每个字段记完整的 **覆盖链**:

```
epochs 的覆盖链:
    50 (CLI) ← 200 (YAML) ← 100 (DEFAULT)
       ↑          ↑              ↑
    当前赢的     被覆盖了        最初的默认
```

回答 "为啥我 yaml 没生效?" 一行就行: **"你的 yaml 给了 200, 但被 CLI 的 50 覆盖了."**

⚠️ **设计点 (为啥是链表不是 list?)** 看着 "链表" 比 "list" 复杂, 但语义上更准: 每次覆盖都是一个 "事件", 事件指向 "上一个事件". 这就是 **git commit 链** 的思路——你不会写一个 `commits = [c1, c2, c3]` list, 你写 `c3.parent = c2; c2.parent = c1`. 链表的 **"指向上一个"** 跟 "覆盖了谁" 在语义上完全对齐.

```python
@dataclass
class ConfigMetadata:
    key:             str                                   # 字段名
    value:           Any                                   # 当前值
    source:          Union[ConfigSource, str]              # 来源 (枚举或自定义字符串)
    timestamp:       datetime                              # 记录时间
    overridden_from: Optional[ConfigMetadata] = None       # ★ 指向被覆盖的上一个

    @property
    def source_label(self) -> str:
        """统一拿 source 的字符串展示 (枚举走 .value, 字符串原样)."""
        if isinstance(self.source, ConfigSource):
            return self.source.value
        return self.source
```

⚠️ **设计点 (timestamp 有啥用?)** 调试场景: 看溯源链 `50(CLI, 10:32:01) ← 200(YAML, 10:31:58) ← 100(DEFAULT, 10:31:58)`, 时间间隔暗示了 "YAML 加载 → CLI 覆盖" 这个过程几乎瞬间发生. 等以后真有需要"什么时候被改的"的场景(比如多进程 / 多线程合并), timestamp 已经在那等着. **加一个字段几乎免费, 删掉它的时候再删**.

⚠️ **设计点 (`source` 类型为什么是 `Union[ConfigSource, str]`?)** 5.4 sources list 接口允许用户传任意字符串作为自定义 source 标识 (例如 `"ENV"`). 这里 source 字段也跟着放宽——既能装枚举值, 又能装字符串. `source_label` property 统一拿展示名, 后续报告 / 审计代码不用每次判断类型.

> **金句**: **"链表 = 时间机器. 一份字段值 + 一根链表, 'lr0 是谁决定的'这种问题永远 30 秒解决."**

## 5.3 ConfigSource: 优先级是枚举不是字符串

```python
class ConfigSource(str, Enum):
    """配置来源 (内置 3 档, 按优先级从低到高)."""
    DEFAULT = "DEFAULT"
    YAML    = "YAML"
    CLI     = "CLI"
```

⚠️ **设计点 (为什么继承 `str, Enum`?)** `class ConfigSource(str, Enum)` 让枚举值本身就是字符串, 既能用 `ConfigSource.CLI` 严格匹配, 又能直接打印成 `"CLI"`. **比纯 Enum 友好得多**.

⚠️ **设计点 (优先级在枚举里没有显式编号)** 看不到 `DEFAULT = 1, YAML = 2, CLI = 3` 这种 int 值. **故意的**——优先级 **由 sources list 的列表顺序决定**, 不由数字大小决定. 调用 merger 时:

```python
config = merger.merge(
    YOLOTrainConfig,
    sources=[
        (ConfigSource.YAML, yaml_dict),
        (ConfigSource.CLI,  cli_dict),       # CLI 在 list 里靠后 = 优先级高
    ],
)
```

**list 里谁后写, 谁优先级高**. 调用方想换顺序自由, 想插新档源只需在 list 里加一项, merger 一行不动. 数字优先级反而让人查 "ENV=4 是高还是低于 CLI=3" 这种无谓的事.

⚠️ **设计点 (枚举只装内置 3 档, 自定义源走字符串)** 部署后会想加的源:
- 环境变量 (`ODP_TRAIN_EPOCHS=300`)
- etcd / consul / k8s configmap
- 实验中央配置服务

每加一档都改 `ConfigSource` 枚举? 不行——这就违反开闭原则了. D5 让 `ConfigSource` 装核心 3 档, **用户加新源时直接用字符串**:

```python
config = merger.merge(
    YOLOTrainConfig,
    sources=[
        (ConfigSource.YAML, yaml_dict),
        ("ENV",             env_dict),        # ★ 字符串作为自定义 source 标识
        (ConfigSource.CLI,  cli_dict),
    ],
)
```

这是 sources list 接口的"扩展点":**枚举装核心, 字符串装扩展**, 跟 Python `Path` 接受 `str | PathLike` 是同款设计取舍.

> **金句**: **"优先级是 sources list 顺序的产物, 不是数据字段. 把它写在数据里, 就要应付'优先级倒置怎么办'的人造问题."**

## 5.4 ConfigMerger: sources list 接口

ConfigMerger 的对外接口设计要解决两件事:
1. **三源合并的核心机制** —— DEFAULT / YAML / CLI 按优先级合一份 dict
2. **未来加新源的扩展性** —— 部署后会想接 ENV / etcd / k8s configmap, 接口不能让"加新源"变成改 merger 源码

D5 一次到位选 **sources list 接口**——所有源装一个有序 list, 顺序 = 优先级:

```python
class ConfigMerger:
    """三源合并 + 链表式溯源 (sources list 接口, 支持任意源)."""

    def __init__(self, track_sources: bool = True):
        self.track_sources = track_sources
        self._metadata: Dict[str, ConfigMetadata] = {}
        self._overridden_keys: List[str] = []
        self._last_config_class: Optional[Type[BaseModel]] = None    # 供 mask / audit 用

    def merge(
        self,
        config_class: Type[T],
        *,
        sources: Optional[List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]]] = None,
    ) -> T:
        """合并多个配置源, 返回 Pydantic 实例.

        Args:
            sources: [(source_id, dict), ...] 顺序 = 优先级 (从低到高).
                     source_id 可以是 ConfigSource 枚举值, 也可以是任意字符串
                     (用于扩展自定义源, 不必扩 enum).
                     DEFAULT 源自动注入到列表最前, 不需要手动传.

        Returns:
            验证后的 Pydantic 配置实例.
        """
        merged = self._do_merge(config_class, sources)

        try:
            return config_class(**merged)
        except ValidationError as e:
            if self.track_sources:
                self._enhance_validation_error(e)
            raise
```

⚠️ **设计点 (为什么不是 `merge(config_class, *, yaml_config, cli_config)`)** 朴素思路是把"两个源的名字"写死在签名里, 看着教学清楚. **但这违反开闭原则**——加第三档源 (环境变量 / etcd) 就得改签名, 改一处碰所有调用方. sources list 把这个口子一次性堵死: 数量无上限, 顺序由调用方决定. 这跟 D3 / D4 的"开闭原则在子系统里的体现"是一脉相承的.

⚠️ **设计点 (为什么允许 source_id 是字符串)** 严格类型派会说"应该扩 `ConfigSource` 枚举". 但每加一个第三方源都让用户提 PR 改 enum 是反 plugin 的——**让 enum 装核心 3 个 (DEFAULT/YAML/CLI 已经够), 字符串装扩展, 边界清晰**. 跟 Python `Path` 接受 `str | PathLike` 是同款设计取舍.

⚠️ **设计点 (`_last_config_class` 保存最近一次 merge 的类)** 不是为了 merge 本身, 是为了 5.7 的报告类接口要查 `sensitive_field_names()` / mask sensitive 字段值. **把"刚 merge 的是哪个类"记住, 后续报告才能自动 mask**——细节实现, 但接口设计是早确定的.

整体 `merge()` 就这么多, 主要复杂度在 `_do_merge` 和 `_apply_source` 里:

```python
def _do_merge(
    self,
    config_class: Type[BaseModel],
    sources: Optional[List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]]],
) -> Dict[str, Any]:
    """合并 + 维护溯源, 返回 dict, 不实例化."""
    self._metadata.clear()
    self._overridden_keys.clear()
    self._last_config_class = config_class

    # DEFAULT 源永远自动注入到最前 (反射自 Pydantic, 走 SSoT)
    defaults = self._extract_defaults(config_class)
    all_sources: List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]] = [
        (ConfigSource.DEFAULT, defaults),
    ]
    all_sources.extend(sources or [])

    merged: Dict[str, Any] = {}
    for source, cfg in all_sources:
        self._apply_source(merged, dict(cfg or {}), source)

    return merged

def _apply_source(
    self,
    merged: Dict[str, Any],
    config: Mapping[str, Any],
    source: Union[ConfigSource, str],
) -> None:
    """应用一个配置源到合并结果. 同时维护 ConfigMetadata 链表."""
    for key, value in config.items():
        # None 表示"没提供", 不覆盖
        if value is None:
            continue

        # 记录覆盖事件
        if key in merged and self.track_sources:
            self._overridden_keys.append(key)

        # 更新值
        merged[key] = value

        # 维护溯源链表
        if self.track_sources:
            prev_meta = self._metadata.get(key)
            self._metadata[key] = ConfigMetadata(
                key=key,
                value=value,
                source=source,
                timestamp=datetime.now(),
                overridden_from=prev_meta,         # ★ 链表精髓
            )
```

⚠️ **设计点 (None 不参与覆盖)** 这跟 `_drop_none` 是同源逻辑——某个源给了 None 等同于 "没给", 不覆盖. 但 **`False / 0 / ""` 必须覆盖**——这是显式值. 这一行 `if value is None: continue` 跟阶段 4 的过滤函数遥相呼应——**整套系统对 None 的语义保持一致**.

⚠️ **设计点 (DEFAULT 源自动注入, 调用方不需要传)** 默认值是从 Pydantic 反射来的, 调用方传 sources 时不应该手动加 `(DEFAULT, defaults)`——容易写错, 也违反 SSoT (默认值已经在 Pydantic 字段里). merger 内部自动注入, 调用方只关心 YAML / CLI 这种"外部源".

⚠️ **设计点 (链表是怎么"长"出来的?)** 三次 `_apply_source` 跑下来, 假设字段 `epochs`:

```
第 1 次 (DEFAULT):
  merged["epochs"] = 100
  _metadata["epochs"] = {value=100, source=DEFAULT, overridden_from=None}

第 2 次 (YAML, 假设 yaml 给了 200):
  prev_meta = _metadata.get("epochs")  # 拿到 DEFAULT 那个
  _metadata["epochs"] = {value=200, source=YAML, overridden_from=prev_meta}
                                                 ↑ 指向 DEFAULT 那个

第 3 次 (CLI, 假设 cli 给了 50):
  prev_meta = _metadata.get("epochs")  # 拿到 YAML 那个
  _metadata["epochs"] = {value=50, source=CLI, overridden_from=prev_meta}
                                                ↑ 指向 YAML 那个 → 再指向 DEFAULT
```

最后 `_metadata["epochs"].chain()` 一路顺着 `overridden_from` 走, 就能拿到完整 `[CLI, YAML, DEFAULT]` 历史. **本质上和 git commit 的祖父链没区别**.

⚠️ **设计点 (默认值是从 Pydantic 反射出来的, 不是单独维护)**:

```python
@staticmethod
def _extract_defaults(config_class: Type[BaseModel]) -> Dict[str, Any]:
    """从 Pydantic 模型 model_fields 反射默认值"""
    defaults = {}
    for name, field in config_class.model_fields.items():
        if field.default is not None:
            defaults[name] = field.default
    return defaults
```

**为什么不单独维护一份默认字典?** 因为 `BaseConfig` / `YOLOTrainConfig` 里 `Field(default=...)` 已经是默认值的唯一真相源(SSoT 的第三层). 重复维护一份默认 dict, 改字段时永远忘了同步——SSoT 立即破. **能反射出来的, 永远反射, 别复制**.

⚠️ **设计点 (`if field.default is not None` 也是有讲究的)** Pydantic 的 `Optional[str] = Field(default=None)` 字段, 默认值是 None. 这种 None 不该进 merger 的默认 dict——前面 `_apply_source` 又会因为 `value is None: continue` 跳过它. **过滤一次就行, 别让 None 在系统里多走一步**.

## 5.5 ConfigMetadata.chain() —— 链表展开

链表是数据结构, 看链需要 **遍历方法**:

```python
@dataclass
class ConfigMetadata:
    key:             str
    value:           Any
    source:          Union[ConfigSource, str]              # 内置枚举或自定义字符串
    timestamp:       datetime
    overridden_from: Optional["ConfigMetadata"] = None

    @property
    def source_label(self) -> str:
        """统一拿 source 字符串展示."""
        if isinstance(self.source, ConfigSource):
            return self.source.value
        return self.source

    def chain(self) -> List["ConfigMetadata"]:
        """顺着 overridden_from 链表, 返回从当前到根的完整历史"""
        result = [self]
        current = self.overridden_from
        while current:
            result.append(current)
            current = current.overridden_from
        return result

    def chain_str(self) -> str:
        """格式化覆盖链: '50(CLI) ← 200(YAML) ← 100(DEFAULT)'"""
        parts = [f"{m.value}({m.source_label})" for m in self.chain()]
        return " ← ".join(parts)
```

⚠️ **设计点 (`←` 还是 `→`?)** 选 `←` 不是 `→`. 为啥? **当前值在左**——读 `50 ← 200 ← 100` 从左到右就是 "现在生效 50, 之前是 200, 最初是 100", **符合人的阅读习惯**(从结果倒推原因). 如果用 `→`, 变成 `100 → 200 → 50`, 阅读时得先看到尾巴才知道当前值, 是反过来的.

⚠️ **设计点 (`chain()` 返回 list 而不是 generator)** 链表长度通常很小 (3-5 档源), 没必要 lazy. **小数据量、固定上界, 直接 list 比 generator 阅读体验好**.

⚠️ **设计点 (`source_label` 而不是 `source.value`)** `source` 字段类型是 `Union[ConfigSource, str]`——枚举走 `.value`, 字符串原样. 不统一封装, 每个调用点都得 `isinstance` 判断. `source_label` property 把这层细节封掉, 后续报告 / 审计代码可以无脑 `m.source_label`.

## 5.6 ValidationError 增强: 把溯源信息塞进错误里

合并完, `config_class(**merged)` 走 Pydantic 验证. 验证失败时, Pydantic 抛 `ValidationError`——但默认的错误信息只告诉你 **"哪个字段值不对"**, 不告诉你 **"这个值是从哪个源来的"**.

想象一下: 你跑 `odp-train --batch 0`, Pydantic 报错:

```
ValidationError: 1 validation error for YOLOTrainConfig
batch
  batch 为 int 时必须为 -1(自动) 或 >= 1(固定值)
```

够吗? 缺一段: **"这个 batch=0 是 CLI 给的 还是 YAML 给的?"** 你得自己回去翻 yaml 文件 + 自己敲过的命令——但其实 Merger 早就知道了!

```python
def _enhance_validation_error(self, error: ValidationError) -> None:
    """把溯源信息(chain_str)塞进 Pydantic 错误消息"""
    for err in error.errors():
        loc = err.get("loc", ())
        if not loc:
            continue

        key = loc[0]
        if not isinstance(key, str):
            continue

        meta = self._metadata.get(key)
        if not meta:
            continue

        msg = err.get("msg", "")
        err["msg"] = f"{msg} [来源: {meta.chain_str()}]"
```

增强后:

```
ValidationError: 1 validation error for YOLOTrainConfig
batch
  batch 为 int 时必须为 -1(自动) 或 >= 1(固定值) [来源: 0(CLI) ← 16(DEFAULT)]
```

一行就够了——用户立刻知道 "0 是我自己 CLI 敲的, 不是 yaml 也不是默认". 复制粘贴报错的最后一行就能向同事描述清楚.

⚠️ **设计点 (修改 `err["msg"]` 而不是抛新 exception)** Pydantic 的 ValidationError 看着 immutable, 但内部 `error.errors()` 返回的是可变 list of dict. 改 dict 的 `msg` 字段, Pydantic 之后 `__str__()` 时会拿到新消息. **修改原 exception 比抛新 exception 好**: 保留 traceback、保留所有原有上下文, 只是 **加了一段更精确的描述**.

⚠️ **设计点 (`loc[0]` 拿字段名, 但不一定 100% 安全)** 简单字段 `loc=('batch',)`, `loc[0]` 是 `'batch'`. 但嵌套 Pydantic 模型 `loc=('outer', 'inner')`, `loc[0]` 是 `'outer'`. 我们当前 YOLOTrainConfig 没有嵌套模型, 顶层字段足够, 但 `if not isinstance(key, str): continue` 是一道防线——以后真加了嵌套模型, 这里不至于挂.

## 5.7 配置报告: 给用户看的两张表

链表式溯源在背后建好了, 但用户看不到. ConfigMerger 还得对外提供两个 **报告方法**, 都做两件加固:
1. **自动 mask sensitive 字段** —— 跟 BaseConfig 的 sensitive 元数据打通, 进日志的报告不会泄漏敏感值
2. **支持自定义 source label** —— sources list 接口允许传字符串 source, 报告里也要正确分组

### 报告 1: source_report —— "最终生效的配置, 按来源分组"

```python
def get_source_report(self) -> str:
    """生成配置来源报告——按 source 分组列出最终生效的字段."""
    if not self.track_sources:
        return "配置溯源未启用"

    lines = ["=" * 70, "配置来源报告".center(70), "=" * 70]

    # 按 source_label 分桶 (兼容枚举 + 字符串)
    by_source: Dict[str, List[str]] = {}
    for key, meta in self._metadata.items():
        by_source.setdefault(meta.source_label, []).append(key)

    # 内置 source 在前 (CLI/YAML/DEFAULT 优先级序), 自定义 source 在后字母序
    builtin_order = [s.value for s in
                     [ConfigSource.CLI, ConfigSource.YAML, ConfigSource.DEFAULT]]
    ordered = [s for s in builtin_order if s in by_source]
    custom  = sorted(s for s in by_source if s not in builtin_order)
    all_labels = ordered + custom

    for label in all_labels:
        keys = sorted(by_source[label])
        lines.append(f"\n{label} ({len(keys)} 项)")
        lines.append("-" * 70)
        if not keys:
            lines.append("  (无)")
        else:
            for key in keys:
                value = self._display_value(key, self._metadata[key].value)
                lines.append(f"  {key} = {value}")
    return "\n".join(lines)


def _is_sensitive(self, key: str) -> bool:
    """判断字段是否标了 sensitive=True."""
    if self._last_config_class is None:
        return False
    if not hasattr(self._last_config_class, "sensitive_field_names"):
        return False
    return key in self._last_config_class.sensitive_field_names()


def _display_value(self, key: str, value: Any) -> Any:
    """获取展示值——sensitive 字段自动 mask."""
    if value is None:
        return value
    if self._is_sensitive(key):
        mask = getattr(self._last_config_class, "SENSITIVE_MASK", "***")
        return mask
    return value
```

输出长这样:

```
======================================================================
                            配置来源报告
======================================================================

CLI (2 项)
----------------------------------------------------------------------
  batch = 32
  epochs = 200

YAML (3 项)
----------------------------------------------------------------------
  data = configs/datasets/safety_helmet.yaml
  lr0 = 0.001
  model = yolo11n.pt

ENV (1 项)                            ← ★ 自定义 source 在内置之后, 字母序
----------------------------------------------------------------------
  workers = 16

DEFAULT (58 项)
----------------------------------------------------------------------
  amp = True
  bgr = 0.0
  ...
```

⚠️ **设计点 (按来源分组, 不是按字段名分组)** 这张表是给 **"调参视角"** 看的——用户最关心 "我这次实际改了啥(CLI/YAML), 哪些是默认值". 按来源分组让 "改过的字段" 集中在上半部分, **一眼能看完**. 反过来按字段名字母序排, 改过的字段跟没改过的混在一起, 视觉上找不出重点.

⚠️ **设计点 (自定义 source 在内置之后)** `("ENV", ...)` / `("etcd", ...)` 这类自定义 source 排在 CLI/YAML/DEFAULT 之后, 按字母序. 让用户一眼分辨"内置 vs 扩展", 报告结构有可预测的稳定性.

⚠️ **设计点 (`_display_value` 跟 mask 解耦)** mask 逻辑封到 `_display_value`, 后面 `get_conflict_report` 跟 `to_audit_log` 都复用同一套. **mask 一处实现, 三处共用——加新报告时不会忘.**

### 报告 2: conflict_report —— "哪些字段被覆盖过"

```python
def get_conflict_report(self) -> str:
    """生成覆盖报告——展示哪些字段被高优先级覆盖了."""
    if not self.track_sources:
        return "配置溯源未启用"

    # 去重 (同一字段可能被覆盖多次, 但只展示一遍)
    overridden = list(dict.fromkeys(self._overridden_keys))   # 去重保序

    lines = ["=" * 70, "配置覆盖报告".center(70), "=" * 70]
    lines.append(f"\n共 {len(overridden)} 项配置被覆盖\n")

    if not overridden:
        lines.append("  (无)")
        return "\n".join(lines)

    for key in sorted(overridden):
        meta = self._metadata.get(key)
        if not meta:
            continue
        chain = meta.chain()
        if len(chain) <= 1:
            continue
        # 只显示最近一次覆盖 (简洁起见)
        newest, previous = chain[0], chain[1]
        new_val = self._display_value(key, newest.value)
        old_val = self._display_value(key, previous.value)
        lines.append(
            f"  {key}: {old_val} ({previous.source_label}) "
            f"→ {new_val} ({newest.source_label})"
        )

    return "\n".join(lines)
```

输出:

```
======================================================================
                            配置覆盖报告
======================================================================

共 3 项配置被覆盖

  batch: 16 (DEFAULT) → 32 (CLI)
  epochs: 100 (DEFAULT) → 200 (CLI)
  lr0: 0.01 (DEFAULT) → 0.001 (YAML)
```

⚠️ **设计点 (`conflict_report` 只显示最近一次覆盖, 不显示完整链)** 报告输出取 "最近一次覆盖" 已经够用——用户最关心的是 "我有意识改了什么, 实际生效了什么". 完整链表保留在 `_metadata`, 想看的时候用 `merger.get_metadata("epochs").chain_str()` 自己取.

⚠️ **设计点 (`_display_value` 在这里同样自动 mask)** 跟 `get_source_report` 用同一套 mask 逻辑——sensitive 字段不会在这张报告里泄漏旧值或新值. 一处实现, 两处共用.

> **金句**: **"数据结构和报告视图是两层. 链表完整存底, 报告按场景投影——数据丰富不等于报告复杂."**

## 5.8 dry-run 预览: `preview()` 方法

`merge()` 一调下去就 Pydantic 验证, **用户没法"先看一眼合并结果再决定改不改"**. 解决这个伤痛 (阶段 1 列的伤痛⑥), ConfigMerger 加一个**预览**入口:

```python
def preview(
    self,
    config_class: Type[BaseModel],
    *,
    sources: Optional[List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Dry-run: 跑合并 + 维护溯源, 但不实例化配置类 (不验证).

    用法:
        merger = ConfigMerger()
        merged = merger.preview(YOLOTrainConfig, sources=[...])
        print(merger.get_source_report())     # 用户先看再决定
        # 觉得 OK 后, 用 merger.merge(...) 真跑

    Returns:
        合并后的原始 dict (未经 Pydantic 验证, 可能含非法值).
    """
    return self._do_merge(config_class, sources)
```

⚠️ **设计点 (为什么单独叫 `preview()`, 不是给 `merge()` 加 `validate=False` 参数)** 一个方法签名能讲清的事尽量不要靠开关参数表达. `merge()` 返回类型是 `T` (验证后的 Pydantic 实例), `preview()` 返回 `Dict[str, Any]` (未验证的 dict)——**返回类型不同, 方法名不同, mypy 能精确推断**.

⚠️ **设计点 (`preview()` 跳过验证还是怎么了)** 跳过. 用户可能故意配错来测试 ("我把 batch 改成 -1 看看溯源怎么显示"), 也可能想看一个不完整的配置 ("我先看 yaml 默认值长啥样"). preview 的语义是"合并完给我看, 别问值合不合法"——验证是 `merge()` 的责任.

⚠️ **设计点 (用户如何调用)** 调用方一般不直接调 `merger.preview()`. 阶段 7 的 `build_train_config(dry_run=True)` 会包装这一层——`dry_run=True` 时 merger 走 preview, `dry_run=False` 时 merger 走 merge. **底层方法 + 顶层便捷参数, 用户体验干净**.

> **金句**: **"dry-run 不是 '半成品调用', 是 '决定之前看一眼'. 配置系统给用户 5 秒思考的余地, 比训练 5 小时之后再后悔便宜得多."**

## 5.9 结构化审计日志: `to_audit_log()`

`get_source_report` / `get_conflict_report` 给人读的字符串, 进不了 ELK / Prometheus / 数据库 schema. `to_audit_snapshot` (BaseConfig 阶段 2 立的) 是字段值快照, 进数据库存档. **还差一档**: 运维 / SRE 想往 ELK 推一行 JSON, 追踪"D6 这次部署 merger 解析了什么、改了哪些字段"——这两个用途, 字符串报告太长不能索引, 完整快照又太大且含敏感字段值.

ConfigMerger 加 `to_audit_log()` 解决阶段 1 列的伤痛⑧:

```python
def to_audit_log(self) -> Dict[str, Any]:
    """生成结构化审计日志 (一行 JSON, 给 ELK / 数据库用).

    跟其他两个产物的边界:
        - get_source_report / get_conflict_report: 给人看的字符串
        - to_audit_snapshot (BaseConfig): 字段值快照, 进数据库
        - to_audit_log (本方法):          元信息字典, 进 ELK

    Returns:
        {
            "merger_completed_at":  "2026-05-20T14:32:15",
            "track_sources":        true,
            "fields_count_total":   75,
            "fields_by_source": {
                "CLI":     ["batch", "epochs"],
                "YAML":    ["data", "lr0", "model"],
                "DEFAULT": [... 其余字段 ...],
            },
            "overridden_count":     3,
            "overridden_fields":    ["batch", "epochs", "lr0"],
        }
    """
    if not self.track_sources:
        return {
            "merger_completed_at": datetime.now().isoformat(timespec="seconds"),
            "track_sources":       False,
        }

    # 按 source_label 分桶, 字段名排序保证幂等
    by_source: Dict[str, List[str]] = {}
    for key, meta in self._metadata.items():
        by_source.setdefault(meta.source_label, []).append(key)
    by_source = {k: sorted(v) for k, v in by_source.items()}

    overridden = sorted(set(self._overridden_keys))

    return {
        "merger_completed_at": datetime.now().isoformat(timespec="seconds"),
        "track_sources":       True,
        "fields_count_total":  len(self._metadata),
        "fields_by_source":    by_source,
        "overridden_count":    len(overridden),
        "overridden_fields":   overridden,
    }
```

⚠️ **设计点 (审计日志不含字段值, 只含字段名)** 为啥不把 `epochs=200` 这种值也存? 两个理由:
1. **敏感字段**: `data` 字段可能含 S3 URL 凭证, 进日志风险大. 一旦审计日志要传值, 就得在每个字段上做 mask 判断 → 跟 mask 通道耦合. **保持审计日志只存"哪些字段从哪儿来"的元信息, 不存值**——值的快照是 `to_audit_snapshot()` 的事, 两个产物各管一摊.
2. **数据规模**: ELK 索引每行 size 越小越好. 75 字段全部带值 vs 只带字段名, 一行差几 KB, 跑半年差 GB.

⚠️ **设计点 (字段名 `sorted()` 排序)** 同一份配置跑两次, 审计日志 `fields_by_source["CLI"]` 顺序应该一样——给 ELK 做 diff 时不至于因为 dict 顺序差异误判. **幂等性是审计日志的硬要求**.

⚠️ **设计点 (`merger_completed_at` 字段名)** 不叫 `timestamp`, 不叫 `time`——叫得**专门**, 避免跟 `ConfigMetadata.timestamp` (单字段记录时间) 在 ELK 索引里混淆. 字段名是 ELK schema 的一部分, 起名要"无歧义可索引".

### 三个产物的边界 (回顾)

| 方法 | 输出类型 | 受众 | 落点 |
|---|---|---|---|
| `get_source_report()` / `get_conflict_report()` | `str` (多行带边框) | 开发者 / 用户 | 终端打印 |
| `to_audit_snapshot()` (BaseConfig 2.5) | `dict` (字段值快照, 含类标识) | 实验复现系统 | 数据库 / JSON 文件 |
| `to_audit_log()` (本节) | `dict` (元信息, 无字段值) | 运维 / SRE | `logger.info(json.dumps(...))` → ELK |

**三个产物各管一摊, 不互相替代**. 一份配置完成 merge 后, D6 service 同时调三个: 终端打报告给操作员看, 进数据库存快照备复现, 写一行 JSON 进 ELK 给 SRE 追踪.

```python
# D6 TrainService.run() 大致用法
config, merger = build_train_config(yaml_path=..., cli_args=args)

logger.info("\n" + merger.get_source_report())                  # 终端报告
self.db.save_experiment(config.to_audit_snapshot())             # 数据库存档
logger.info(f"audit={json.dumps(merger.to_audit_log())}")       # ELK 审计
model.train(**config.to_ultralytics_kwargs())                   # 正式跑训练
```

> **金句**: **"给人看的报告和给机器吃的日志, 是配置系统两条互相独立的产线. 把一个产物硬塞给两种受众的努力, 永远两边都不讨好."**

## 5.10 完整代码: merger.py

`apps/platform/src/odp_platform/runtime_config/merger.py`:

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : merger.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统——配置合并器 (sources list + 链表式溯源)
"""配置合并器: 按优先级合并多个配置源 + 配置溯源追踪.

★ 四个核心:
   1. sources list 接口:  任意源数量, source_id 接受枚举或字符串(扩展点)
   2. 链表式溯源:         ConfigMetadata.overridden_from 指向被覆盖的上一个
   3. 错误信息增强:       Pydantic ValidationError 加 "[来源: ...]" 后缀
   4. 三个产物:           get_source_report (人) / to_audit_log (机器) /
                          ValidationError 增强 (错误)

★ 跟 阶段 4 的 Loader 衔接:
   Loader 产出独立的 dict, Merger 把它们组装进 sources list +
   Pydantic 模型默认值 合并 + 验证 → Pydantic 实例
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple, Type, TypeVar, Union

from pydantic import BaseModel, ValidationError


# ============================================================
# 配置来源枚举 (内置 3 档, 自定义源走字符串)
# ============================================================

class ConfigSource(str, Enum):
    """配置来源 (内置 3 档). 自定义源直接用字符串, 不必扩 enum."""
    DEFAULT = "DEFAULT"
    YAML    = "YAML"
    CLI     = "CLI"


# ============================================================
# 配置元数据: 链表节点
# ============================================================

@dataclass
class ConfigMetadata:
    """单个字段的溯源信息.

    Attributes:
        key:             字段名
        value:           当前值
        source:          配置来源 (ConfigSource 枚举 或 自定义字符串)
        timestamp:       记录时间 (每次覆盖更新)
        overridden_from: ★ 指向被覆盖的上一个 ConfigMetadata, 形成链表
    """
    key:             str
    value:           Any
    source:          Union[ConfigSource, str]
    timestamp:       datetime
    overridden_from: Optional["ConfigMetadata"] = None

    @property
    def source_label(self) -> str:
        """统一拿 source 的字符串展示 (枚举走 .value, 字符串原样)."""
        if isinstance(self.source, ConfigSource):
            return self.source.value
        return self.source

    def chain(self) -> List["ConfigMetadata"]:
        """顺着 overridden_from 遍历, 返回从当前到根的历史链.

        例: 链表为 CLI ← YAML ← DEFAULT, chain() 返回 [CLI, YAML, DEFAULT]
        """
        result = [self]
        current = self.overridden_from
        while current:
            result.append(current)
            current = current.overridden_from
        return result

    def chain_str(self) -> str:
        """格式化覆盖链: '50(CLI) ← 200(YAML) ← 100(DEFAULT)'.

        '←' 从左到右读: 当前 ← 上一个 ← 更早, 符合"从结果倒推原因"的阅读习惯.
        """
        parts = [f"{m.value}({m.source_label})" for m in self.chain()]
        return " ← ".join(parts)


# ============================================================
# 配置合并器
# ============================================================

T = TypeVar("T", bound=BaseModel)


class ConfigMerger:
    """sources list 接口的三源 (及更多) 合并 + 链表式溯源.

    优先级由 sources list 顺序决定 (后面的覆盖前面的). DEFAULT 自动注入到最前.

    使用示例 (内置 yaml/cli):
        merger = ConfigMerger()
        config = merger.merge(
            YOLOTrainConfig,
            sources=[
                (ConfigSource.YAML, yaml_dict),
                (ConfigSource.CLI,  cli_dict),
            ],
        )

    使用示例 (自定义 ENV 源, 不扩 enum):
        config = merger.merge(
            YOLOTrainConfig,
            sources=[
                (ConfigSource.YAML, yaml_dict),
                ("ENV",             env_dict),       # ★ 字符串作为 source 标识
                (ConfigSource.CLI,  cli_dict),
            ],
        )

    使用示例 (dry-run 预览):
        merged_dict = merger.preview(YOLOTrainConfig, sources=[...])
        print(merger.get_source_report())     # 用户先看再决定

    三个产物:
        get_source_report() / get_conflict_report() — 给人看的字符串
        to_audit_log() — 给 ELK / 数据库的结构化 dict
        (BaseConfig.to_audit_snapshot() — 字段值快照, 在 base.py)
    """

    def __init__(self, track_sources: bool = True):
        """
        Args:
            track_sources: 是否追踪配置来源 (关掉只合并不溯源, 稍快)
        """
        self.track_sources = track_sources
        self._metadata: Dict[str, ConfigMetadata] = {}
        self._overridden_keys: List[str] = []
        self._last_config_class: Optional[Type[BaseModel]] = None    # 给 mask / audit 用

    # ============================================================
    # 公开接口
    # ============================================================

    def merge(
        self,
        config_class: Type[T],
        *,
        sources: Optional[List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]]] = None,
    ) -> T:
        """合并多个配置源 + Pydantic 验证, 返回实例.

        Args:
            config_class: Pydantic 配置类 (YOLOTrainConfig 等)
            sources:      [(source_id, dict), ...] 顺序 = 优先级 (低 → 高).
                          DEFAULT 自动注入到最前, 不需要手动传.

        Returns:
            验证后的 Pydantic 配置实例

        Raises:
            ValidationError: 字段值非法 (错误信息已增强, 含来源链)
        """
        merged = self._do_merge(config_class, sources)

        try:
            return config_class(**merged)
        except ValidationError as e:
            if self.track_sources:
                self._enhance_validation_error(e)
            raise

    def preview(
        self,
        config_class: Type[BaseModel],
        *,
        sources: Optional[List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """Dry-run: 跑合并 + 维护溯源, 但不实例化配置类 (跳验证).

        用法:
            merged = merger.preview(YOLOTrainConfig, sources=[...])
            print(merger.get_source_report())     # 用户先看再决定

        Returns:
            合并后的原始 dict (未经验证, 可能含非法值).
        """
        return self._do_merge(config_class, sources)

    def get_metadata(self, key: str) -> Optional[ConfigMetadata]:
        """获取某字段的最新 ConfigMetadata (可顺 .overridden_from 拉链)."""
        return self._metadata.get(key)

    # ============================================================
    # 报告接口 (给人看)
    # ============================================================

    def get_source_report(self) -> str:
        """配置来源报告——按 source 分组列出最终生效的字段值.

        sensitive 字段自动 mask 成 SENSITIVE_MASK (跟 BaseConfig 联动).
        """
        if not self.track_sources:
            return "配置溯源未启用"

        lines = ["=" * 70, "配置来源报告".center(70), "=" * 70]

        # 按 source_label 分桶 (兼容枚举 + 字符串)
        by_source: Dict[str, List[str]] = {}
        for key, meta in self._metadata.items():
            by_source.setdefault(meta.source_label, []).append(key)

        # 内置 source 在前 (CLI/YAML/DEFAULT 优先级序), 自定义 source 字母序在后
        builtin_order = [s.value for s in
                         [ConfigSource.CLI, ConfigSource.YAML, ConfigSource.DEFAULT]]
        ordered = [s for s in builtin_order if s in by_source]
        custom  = sorted(s for s in by_source if s not in builtin_order)
        all_labels = ordered + custom

        for label in all_labels:
            keys = sorted(by_source[label])
            lines.append(f"\n{label} ({len(keys)} 项)")
            lines.append("-" * 70)
            if not keys:
                lines.append("  (无)")
            else:
                for key in keys:
                    value = self._display_value(key, self._metadata[key].value)
                    lines.append(f"  {key} = {value}")
        return "\n".join(lines)

    def get_conflict_report(self) -> str:
        """配置覆盖报告——列出被高优先级覆盖的字段.

        sensitive 字段值 (新旧两处) 都自动 mask.
        """
        if not self.track_sources:
            return "配置溯源未启用"

        overridden = list(dict.fromkeys(self._overridden_keys))   # 去重保序

        lines = ["=" * 70, "配置覆盖报告".center(70), "=" * 70]
        lines.append(f"\n共 {len(overridden)} 项配置被覆盖\n")

        if not overridden:
            lines.append("  (无)")
            return "\n".join(lines)

        for key in sorted(overridden):
            meta = self._metadata.get(key)
            if not meta:
                continue
            chain = meta.chain()
            if len(chain) <= 1:
                continue
            newest, previous = chain[0], chain[1]
            new_val = self._display_value(key, newest.value)
            old_val = self._display_value(key, previous.value)
            lines.append(
                f"  {key}: {old_val} ({previous.source_label}) "
                f"→ {new_val} ({newest.source_label})"
            )
        return "\n".join(lines)

    def to_audit_log(self) -> Dict[str, Any]:
        """结构化审计日志 (一行 JSON, 给 ELK / 数据库用).

        只装"哪些字段从哪儿来"的元信息, 不装字段值 (避免敏感数据进 ELK).
        字段值快照走 BaseConfig.to_audit_snapshot().

        Returns:
            {
                "merger_completed_at":  "2026-05-20T14:32:15",
                "track_sources":        true,
                "fields_count_total":   75,
                "fields_by_source":     {"CLI": [...], "YAML": [...], "DEFAULT": [...]},
                "overridden_count":     3,
                "overridden_fields":    ["batch", "epochs", "lr0"],
            }
        """
        if not self.track_sources:
            return {
                "merger_completed_at": datetime.now().isoformat(timespec="seconds"),
                "track_sources":       False,
            }

        # 按 source_label 分桶, 字段名排序保证幂等
        by_source: Dict[str, List[str]] = {}
        for key, meta in self._metadata.items():
            by_source.setdefault(meta.source_label, []).append(key)
        by_source = {k: sorted(v) for k, v in by_source.items()}

        overridden = sorted(set(self._overridden_keys))

        return {
            "merger_completed_at": datetime.now().isoformat(timespec="seconds"),
            "track_sources":       True,
            "fields_count_total":  len(self._metadata),
            "fields_by_source":    by_source,
            "overridden_count":    len(overridden),
            "overridden_fields":   overridden,
        }

    # ============================================================
    # 内部方法
    # ============================================================

    def _do_merge(
        self,
        config_class: Type[BaseModel],
        sources: Optional[List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]]],
    ) -> Dict[str, Any]:
        """合并 + 维护溯源, 返回 dict, 不实例化."""
        self._metadata.clear()
        self._overridden_keys.clear()
        self._last_config_class = config_class

        # DEFAULT 源永远自动注入到最前
        defaults = self._extract_defaults(config_class)
        all_sources: List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]] = [
            (ConfigSource.DEFAULT, defaults),
        ]
        all_sources.extend(sources or [])

        merged: Dict[str, Any] = {}
        for source, cfg in all_sources:
            self._apply_source(merged, dict(cfg or {}), source)

        return merged

    def _apply_source(
        self,
        merged: Dict[str, Any],
        config: Mapping[str, Any],
        source: Union[ConfigSource, str],
    ) -> None:
        """应用一个配置源到合并结果. 同时维护溯源链表."""
        for key, value in config.items():
            # None 等同于 "没给", 不覆盖 (跟 Loader 的 _drop_none 同源)
            if value is None:
                continue

            # 记录覆盖事件
            if key in merged and self.track_sources:
                self._overridden_keys.append(key)

            # 更新值
            merged[key] = value

            # 维护溯源链表: 新节点的 overridden_from 指向上一个节点
            if self.track_sources:
                prev_meta = self._metadata.get(key)
                self._metadata[key] = ConfigMetadata(
                    key=key,
                    value=value,
                    source=source,
                    timestamp=datetime.now(),
                    overridden_from=prev_meta,
                )

    @staticmethod
    def _extract_defaults(config_class: Type[BaseModel]) -> Dict[str, Any]:
        """从 Pydantic 模型反射默认值 (SSoT: Field(default=...) 是唯一真相)."""
        defaults = {}
        for name, field in config_class.model_fields.items():
            if field.default is not None:        # None 默认值不进合并 (让 Pydantic 自己处理)
                defaults[name] = field.default
        return defaults

    def _enhance_validation_error(self, error: ValidationError) -> None:
        """把溯源链塞进 ValidationError 的 msg 后缀."""
        for err in error.errors():
            loc = err.get("loc", ())
            if not loc:
                continue
            key = loc[0]
            if not isinstance(key, str):
                continue       # 嵌套模型 loc 可能是 int, 跳过
            meta = self._metadata.get(key)
            if not meta:
                continue
            msg = err.get("msg", "")
            err["msg"] = f"{msg} [来源: {meta.chain_str()}]"

    # ============================================================
    # 敏感字段 mask (跟 BaseConfig 的 sensitive 元数据联动)
    # ============================================================

    def _is_sensitive(self, key: str) -> bool:
        """判断字段是否标了 sensitive=True."""
        if self._last_config_class is None:
            return False
        if not hasattr(self._last_config_class, "sensitive_field_names"):
            return False
        return key in self._last_config_class.sensitive_field_names()

    def _display_value(self, key: str, value: Any) -> Any:
        """获取展示值 (sensitive 字段自动 mask 成 SENSITIVE_MASK)."""
        if value is None:
            return value
        if self._is_sensitive(key):
            return getattr(self._last_config_class, "SENSITIVE_MASK", "***")
        return value
```

代码约 320 行——比原版多约 90 行, 多出来的是: `preview()` (dry-run)、`to_audit_log()` (结构化审计)、`_is_sensitive` / `_display_value` (mask 通道)、source_id 接受字符串扩展. **核心合并算法仍然是 `_apply_source` 那 20 行不变, 周边接口体现工程素质**.

## 5.11 测试: ConfigMerger 9 组覆盖

> 💡 **前置确认见 2.7** —— 如果 `from odp_platform.runtime_config.merger import ...` 报 `ModuleNotFoundError`, 重跑 `pip install -e ./apps/platform`.

打开 Python REPL (或保存为脚本运行):

```python
from pydantic import ValidationError

from odp_platform.runtime_config.merger import ConfigMerger, ConfigSource
from odp_platform.runtime_config.train  import YOLOTrainConfig

# ============================================================
# 1. 基本三源合并 — 优先级 CLI > YAML > DEFAULT
# ============================================================
merger = ConfigMerger(track_sources=True)

yaml_cfg = {
    "model": "yolo11n.pt",
    "data":  "configs/datasets/rsod.yaml",
    "epochs": 200,
    "lr0":   0.005,
    "batch": 16,
}
cli_cfg = {
    "epochs": 50,        # CLI 覆盖 YAML 的 200
    "batch":  32,        # CLI 覆盖 YAML 的 16
}

config = merger.merge(
    YOLOTrainConfig,
    sources=[
        (ConfigSource.YAML, yaml_cfg),
        (ConfigSource.CLI,  cli_cfg),
    ],
)

assert config.epochs == 50,     "CLI 必须覆盖 YAML"
assert config.batch  == 32,     "CLI 必须覆盖 YAML"
assert config.lr0    == 0.005,  "YAML 必须覆盖默认 0.01"
assert config.optimizer == "auto", "未指定的字段走默认值"
print(f"✓ 三源合并: epochs={config.epochs}, batch={config.batch}, lr0={config.lr0}")

# ============================================================
# 2. 单字段溯源 — chain_str
# ============================================================
meta = merger.get_metadata("epochs")
assert meta is not None
assert meta.value           == 50
assert meta.source          == ConfigSource.CLI
assert meta.overridden_from.value      == 200
assert meta.overridden_from.source     == ConfigSource.YAML
assert meta.overridden_from.overridden_from.value  == 100
assert meta.overridden_from.overridden_from.source == ConfigSource.DEFAULT
print(f"✓ epochs 链: {meta.chain_str()}")
# → '50(CLI) ← 200(YAML) ← 100(DEFAULT)'

# ============================================================
# 3. None 值不参与覆盖
# ============================================================
merger2 = ConfigMerger(track_sources=True)
config2 = merger2.merge(
    YOLOTrainConfig,
    sources=[
        (ConfigSource.YAML, {"epochs": 200, "lr0": None}),    # lr0=None 不应覆盖
        (ConfigSource.CLI,  {"batch": None}),                   # batch=None 不应覆盖
    ],
)
assert config2.lr0   == 0.01,    "None 不能覆盖默认 0.01"
assert config2.batch == 16,      "None 不能覆盖默认 16"
print(f"✓ None 不参与覆盖: lr0={config2.lr0}, batch={config2.batch}")

# ============================================================
# 4. False / 0 / '' 必须参与覆盖
# ============================================================
merger3 = ConfigMerger(track_sources=True)
config3 = merger3.merge(YOLOTrainConfig, sources=[
            (ConfigSource.YAML, {"amp": False, "fraction": 1.0}),
            (ConfigSource.CLI,  {"resume": False}),
        ])
# 注意: amp 默认是 True, yaml 给 False 必须生效
assert config3.amp is False, "显式 False 必须覆盖默认 True"
print(f"✓ 显式 False 覆盖默认 True: amp={config3.amp}")

# ============================================================
# 5. source_report — 按来源分组
# ============================================================
report = merger.get_source_report()
print(report)
assert "CLI (2 项)" in report
assert "YAML (3 项)" in report
assert "epochs = 50"  in report
assert "lr0 = 0.005"  in report

# ============================================================
# 6. conflict_report — 列出被覆盖的字段
# ============================================================
report = merger.get_conflict_report()
print(report)
assert "共 3 项配置被覆盖" in report                              # ★ lr0 也算被覆盖 (DEFAULT→YAML)
assert "epochs: 200 (YAML) → 50 (CLI)" in report
assert "batch: 16 (YAML) → 32 (CLI)"   in report
assert "lr0: 0.01 (DEFAULT) → 0.005 (YAML)" in report             # ★ CLI 没改 lr0, 但 YAML 已经覆盖了 DEFAULT

# ============================================================
# 7. ValidationError 增强 — 错误信息含 chain
# ============================================================
merger4 = ConfigMerger(track_sources=True)
try:
    merger4.merge(
        YOLOTrainConfig,
        sources=[
            (ConfigSource.YAML, {"epochs": 100}),
            (ConfigSource.CLI,  {"batch": 0}),      # 非法值
        ],
    )
except ValidationError as e:
    msg = str(e)
    print(f"\n--- 增强后的错误信息 ---\n{msg}\n")
    # 关键: 错误信息里必须含来源链
    assert "[来源:" in msg
    assert "0(CLI)" in msg
    assert "DEFAULT" in msg
    print("✓ ValidationError 含来源链 [来源: 0(CLI) ← 16(DEFAULT)]")

# ============================================================
# 8. track_sources=False — 报告不可用但合并能跑
# ============================================================
merger5 = ConfigMerger(track_sources=False)
config5 = merger5.merge(YOLOTrainConfig, sources=[(ConfigSource.YAML, {"epochs": 50})])
assert config5.epochs == 50
assert merger5.get_source_report() == "配置溯源未启用"
print(f"✓ track_sources=False 时合并仍工作, 报告关闭")

# ============================================================
# 9. 重复调用 merge — 状态正确重置
# ============================================================
merger6 = ConfigMerger(track_sources=True)
merger6.merge(YOLOTrainConfig, sources=[(ConfigSource.CLI, {"epochs": 999})])
merger6.merge(YOLOTrainConfig, sources=[(ConfigSource.CLI, {"batch": 8})])   # 第二次合并
# 第二次合并不应该有 epochs 的 metadata
meta_epochs = merger6.get_metadata("epochs")
assert meta_epochs.source == ConfigSource.DEFAULT, "重置状态后 epochs 应回到 DEFAULT"
print("✓ 重复 merge 状态正确重置")

print("\n--- 阶段 5 测试通过 ---")
```

应该全部 ✓.

⚠️ **设计点 (为什么 `lr0` 也算"被覆盖"?)** `lr0` 在 CLI 里没改, 但 YAML 已经把它从 DEFAULT 的 0.01 改成了 0.005——这是一次"覆盖事件". `conflict_report` 显示的是 **"最近一次覆盖"**, 所以 `lr0` 显示 `DEFAULT → YAML`, 跟 `batch / epochs` 显示 `YAML → CLI` 形成对比. 这恰恰证明了链表式溯源的价值: 同一个 conflict_report 能看到不同字段在不同源之间的覆盖路径.

反过来 `model / data` 不算覆盖, 是因为它们的默认值是 None, `_extract_defaults` 跳过 None (默认值阶段不进 `merged`), YAML 第一次把它们填进 `merged` 时, `key in merged` 是 False, 不触发覆盖事件. **None 在系统里始终保持"等同于未提供"的语义, 阶段 4 的 `_drop_none` / 阶段 5 的 `_extract_defaults` / `_apply_source` 三处共同维护**.

## 5.12 git commit

```bash
git add apps/platform/src/odp_platform/runtime_config/merger.py
git commit -m "feat(runtime_config): add ConfigMerger with source tracking

runtime_config/merger.py:
  + ConfigSource (str, Enum) — DEFAULT / YAML / CLI
    priority is determined by call order, not numeric value
  + ConfigMetadata (dataclass) — chain-style metadata node
    key / value / source / timestamp / overridden_from (→ prev node)
    .chain()      — walk overridden_from to root
    .chain_str()  — '50(CLI) ← 200(YAML) ← 100(DEFAULT)'
  + ConfigMerger:
      .merge(config_class, *, yaml_config, cli_config) → BaseModel instance
        - extracts defaults from model_fields via reflection (SSoT)
        - applies sources in order: DEFAULT < YAML < CLI
        - None values are skipped (preserves False / 0 / '')
        - on ValidationError: enhance err['msg'] with source chain
      .get_metadata(key)        → ConfigMetadata | None
      .get_source_report()      → by-source grouped listing
      .get_conflict_report()    → overridden fields with one-step chain

Key design — why a linked list, not a flat source tag:
  Flat: sources = {'epochs': 'CLI'}
    Can't answer 'before CLI overrode it, was it YAML or DEFAULT?'

  Chain: epochs.metadata.overridden_from → YAML → DEFAULT
    Same shape as git commit history. Reading '50 ← 200 ← 100'
    walks from current value backwards in time — natural for
    'why did my YAML setting not take effect?' debugging.

Key design — None is 'unset', False/0/'' are explicit:
  _apply_source filters None but keeps False / 0 / ''. Same rule
  as YAMLLoader._drop_none in stage 4. Whole system treats None
  as 'no opinion'; explicit falsy values as 'I chose this'.

Key design — defaults via reflection, not duplicated:
  _extract_defaults walks model_fields. Pydantic's Field(default=...)
  is the SSoT for defaults — duplicating a dict would drift the
  first time someone adds a field. Reflect, don't copy.

Notes:
  - timestamp not used today but cheap to keep; lets future
    multi-thread/multi-process scenarios trace the order of writes.
  - get_conflict_report shows one-step (newest <- previous) only;
    full chain available via get_metadata(key).chain_str() when needed.
  - _enhance_validation_error mutates err['msg'] in-place (Pydantic
    errors() returns a mutable list of dicts), preserving traceback
    and other context rather than raising a new exception.
"
```

**中文版**:

```bash
git commit -m "feat(runtime_config): 新增 ConfigMerger 三源合并器与链表式溯源" \
           -m "runtime_config/merger.py:" \
           -m "  + ConfigSource 枚举 (DEFAULT/YAML/CLI), 继承 str+Enum" \
           -m "  + ConfigMetadata dataclass —— 字段溯源链表节点" \
           -m "    key + value + source + timestamp + overridden_from 指针" \
           -m "    chain() / chain_str() 顺指针展开完整覆盖历史" \
           -m "  + ConfigMerger.merge(cls, *, sources=[...]) —— sources list 接口" \
           -m "    源数量无上限, 顺序 = 优先级 (从低到高)" \
           -m "    source_id 接受 ConfigSource 枚举或任意字符串 (扩展自定义源)" \
           -m "    DEFAULT 源自动从 Pydantic model_fields 反射注入" \
           -m "  + ConfigMerger.preview() —— dry-run, 不验证 (用户先看再决定)" \
           -m "  + _enhance_validation_error —— ValidationError 注入溯源链" \
           -m "    错误信息从 'batch 不能是 0' 变成 'batch 不能是 0 [来源: 0(CLI) ← 16(DEFAULT)]'" \
           -m "  + 三个独立审计产物 (各管一摊互不替代):" \
           -m "    - get_source_report() —— 给开发者看的字符串报告" \
           -m "    - get_conflict_report() —— 列出被覆盖的字段及覆盖路径" \
           -m "    - to_audit_log() —— 给 ELK 推的结构化 JSON (不含字段值)" \
           -m "  + 报告自动 mask sensitive 字段 (跟 BaseConfig 的 sensitive 元数据打通)" \
           -m "为什么是链表而不是 list 或 平铺 source 标记:" \
           -m "  平铺方案只能回答'谁赢了', 答不了'被谁覆盖了原值是啥'." \
           -m "  链表 (overridden_from 指针) = git commit 链的思路," \
           -m "  能完整回放 '为什么 lr0 是 0.001 而不是 yaml 写的 0.005'." \
           -m "为什么 sources list 接口而不是 (yaml=, cli=) 关键字:" \
           -m "  关键字参数把'两个源'写死在签名里, 加 ENV/etcd 源就要改签名." \
           -m "  sources list 让源数量、顺序、命名都给调用方决定 —— 开闭原则." \
           -m "关键设计:" \
           -m "  - None 不参与覆盖 (跟 _drop_none 同源逻辑, 保 False/0/'' 显式值)" \
           -m "  - 默认值反射自 Pydantic, 不单独维护一份 (SSoT)" \
           -m "  - 链表展示用 ← 而不是 → —— 当前值在左, 符合人阅读习惯"
```


至此, **配置可以从外部进入 + 按优先级合并 + 完整溯源**——三源合并器立稳, 阶段 6 来解决最后一个伤痛: **YAML 模板手维护**.

> **金句**: **"溯源不是'锦上添花'功能, 是配置系统的灵魂. 没有它, 配置就只是个'最后值赢家表', 没有它, 你三个月后回不去现场."**

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 6: ConfigGenerator——反射式 YAML 模板生成

四个伤痛, 现在还差最后一个—— **YAML 模板手维护** (阶段 1 伤痛④). 这一阶段我们写 `ConfigGenerator`, 把阶段 2-3 写的字段元数据 **反射成 YAML 模板**, 顺手提供一个 `python -m` 入口让用户能直接生成.

> **金句**: **"字段元数据写在源码里, YAML 模板从源码反射出来——一次定义, 两处复用. 这才是 SSoT 在配置系统里的最终形态."**

## 6.1 ConfigGenerator 的输入和输出

输入: 一个 Pydantic 配置类(YOLOTrainConfig / YOLOValConfig).

输出: 一个 YAML 文件, 长这样:

```yaml
#==============================================================================
# YOLO 训练配置
# 自动生成时间: 2026-05-20 14:32:15
#==============================================================================


#------------------------------------------------------------------------------
# 核心参数
#------------------------------------------------------------------------------

# 任务类型(只能是 detect / segment)
# 示例: detect, segment
# 提示:
#   - 限定取值: detect / segment
#   - 决定模型加载方式 + 输出目录的一级子目录
#   - 想给实验起名? → 用 experiment_name 字段
task: detect

# 实验名(目录组织, 不影响语义; None=自动生成)
# 示例: baseline, helmet_v1, lr001_aug_strong, None
# 提示:
#   - None: 由 ultralytics 自动生成 exp / exp2 / exp3...
#   - 自定义: 用作 runs/<task>/<experiment_name>/ 子目录
#   - 推荐命名: <模型>_<数据集>_<关键调参>
experiment_name: null

# 模型文件路径(.pt 或 .yaml)
# 示例: yolo11n.pt, yolo11s.pt, path/to/custom.pt
# 提示:
#   - 支持 .pt 权重文件或 .yaml 配置文件
#   - 官方模型: yolo11n/s/m/l/x.pt (n 最快, x 最准)
#   - 训练时如未指定, 默认从头训练
model: null

# ... (此后还有 10 个分组, 全部按 group 顺序排列) ...


#==============================================================================
# 常见问题
#==============================================================================
#
# Q: 如何修改配置?
# A: 直接编辑对应参数的值, 保存后重新运行即可
#
# Q: 命令行参数会覆盖配置文件吗?
# A: 是的, 命令行参数优先级最高: CLI > YAML > DEFAULT
#
# Q: 如何恢复默认配置?
# A: 删除此文件, 程序会自动报错并提示重新生成
#
#==============================================================================
```

注意几点:
1. **按 group 分章节**——`核心参数` / `训练控制` / `优化器配置` ... 跟阶段 2 立的 `get_field_groups()` 一一对应
2. **每个字段三段注释**——`yaml_comment`、`示例`、`提示` 一目了然
3. **文件头有元信息**——标题、生成时间
4. **文件尾有 FAQ**——回答最常问的三个问题(怎么改、CLI 优先级、怎么恢复默认)

## 6.2 反射: 把字段元数据变成 YAML 行

ConfigGenerator 的核心循环就 3 步:

```python
for group_name, field_names in config.get_field_groups().items():
    # 1. 写分组标题
    lines.append(f"#------------------------\n# {group_name}\n#------------------------")

    # 2. 每个字段一段
    for field_name in field_names:
        metadata = config.get_field_metadata(field_name)
        lines.append(f"# {metadata['yaml_comment']}")
        lines.append(f"# 示例: {', '.join(metadata['examples'])}")
        lines.append(f"# 提示:")
        for tip in metadata['tips']:
            lines.append(f"#   - {tip}")

        # 3. 字段值(默认值, 用户可改)
        value = getattr(config, field_name)
        lines.append(f"{field_name}: {format_value(value)}")
```

阶段 2 写的 `get_field_groups()` / `get_field_metadata()` 这俩工具方法, **就是为这里准备的**. 两边对应起来:

```
BaseConfig (阶段 2)                       ConfigGenerator (阶段 6)
─────────────────────────────────────────────────────────
field 上 Field(json_schema_extra={...})   ← 反射 ─ get_field_metadata()
group 元数据                                ← 反射 ─ get_field_groups()
default 值                                  ← 反射 ─ getattr(default_instance, ...)
```

⚠️ **设计点 (Generator 不该改 Pydantic 模型, 只反射)** ConfigGenerator 只 **读** Pydantic 模型的 `model_fields` 和 `__class__.model_fields`, 不修改、不依赖具体子类. **这就是为什么阶段 2 把 `get_field_groups()` / `get_field_metadata()` 放进 BaseConfig 作为通用工具方法**——任何子类都自动支持模板生成, 不用 Generator 知道它们的具体字段.

## 6.3 YAML 值格式化: 4 种类型 4 种写法

字段值要写进 YAML, 得按 YAML 语法格式化. 不同 Python 类型对应不同 YAML 写法:

| Python 值 | YAML 写法 | 备注 |
|---|---|---|
| `None` | `null` | YAML 标准 |
| `True / False` | `true / false` | YAML 小写 |
| `0.01` / `100` | `0.01 / 100` | 数字直写 |
| `"detect"` | `detect` 或 `"detect"` | 含特殊字符时加引号 |
| `[1, 2, 3]` | `[1, 2, 3]` | 短列表行内格式 |
| `[]` | `[]` | 空列表 |
| `{}` | `{}` | 空字典 |

```python
def _format_value(self, value: Any) -> str:
    if value is None:
        return "null"

    if isinstance(value, bool):                       # ★ 必须在 int 之前!
        return "true" if value else "false"

    if isinstance(value, str):
        # 含 YAML 特殊字符时加引号
        if any(c in value for c in [":", "#", "[", "]", "{", "}"]):
            return f'"{value}"'
        return value

    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        items = ", ".join(str(v) for v in value)
        return f"[{items}]"

    if isinstance(value, dict):
        # 顶层值是 dict 的情况我们不支持(没有这种字段), 留个空占位
        return "{}"

    return str(value)
```

⚠️ **设计点 (bool 必须在 int 之前判)** 经典坑——`isinstance(True, int) == True`. 如果你写 `if isinstance(value, int): return str(value)` 在 bool 之前, `True` 会被格式化成 `"True"`(Python 大写, 不是 YAML 小写). **bool 必须先判**, 跟 BaseConfig 的 `_validate_batch` 同款教训.

⚠️ **设计点 (字符串含特殊字符加引号)** YAML 里 `name: detect:val` 不加引号会被解析成嵌套 dict(`{"name": {"detect": "val"}}`). 含 `: # [ ] { }` 任何一个都要加引号. 这是个保守的过滤——其实 YAML 规则更复杂(以 `-` 开头要小心、空格也要小心), 但 **配置系统的 default 值都是开发者写的, 不会出现这种边缘情况**, 这层保守过滤够用.

⚠️ **设计点 (空列表 / 空字典处理)** Python 的 `[]` / `{}` 在 YAML 里都得显式写出来(不写就是 `null`). Generator 给了显式输出.

## 6.4 文件已存在的安全策略 (默认不覆盖 + 覆盖时自动备份)

用户跑两次生成:

```bash
odp-gen-config train     # 第一次
# 编辑 yaml, 调好了
odp-gen-config train     # 第二次, 不小心又跑了
```

D5 给两道防线:
1. **第一道**: 默认 `overwrite=False`, 文件已存在直接跳过生成
2. **第二道**: 用户显式 `--overwrite`, **覆盖前自动备份原文件** 成 `<name>.yaml.bak.<时间戳>`

两道闸门齐了——默认不覆盖 + 真要覆盖也留底.

```python
import shutil
from datetime import datetime

def generate(
    self,
    config_class: Type[BaseModel],
    output_path: Union[str, Path],
    *,
    overwrite: bool = False,
    backup:    bool = True,          # ★ 覆盖前是否备份 (默认 True)
    title:     Optional[str] = None,
) -> bool:
    output_path = Path(output_path)

    # 第一道防线: 文件存在且不允许覆盖 → 跳过
    if output_path.exists() and not overwrite:
        logger.info(f"配置文件已存在, 跳过生成: {output_path}")
        return False        # 返回 False 表示"没生成"

    # 第二道防线: 覆盖前备份
    if output_path.exists() and backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = output_path.with_name(
            f"{output_path.name}.bak.{stamp}"
        )
        shutil.copy2(output_path, backup_path)        # copy2 保留 metadata
        logger.warning(                                # ★ 走 logger 渠道 (系统行为)
            f"覆盖前已备份原配置: {backup_path}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = self._generate_yaml(config_class, title)
    output_path.write_text(content, encoding="utf-8")
    logger.info(f"配置文件已生成: {output_path}")
    return True
```

⚠️ **设计点 (默认 `overwrite=False`, 显式才覆盖)** 安全的默认值——**默认不破坏现有文件**. 用户真想覆盖, 显式 `--overwrite` 标志, **强制让破坏性操作走显式入口**. 这是 D2 立的 `odp-reset` 同款纪律: 危险动作要确认.

⚠️ **设计点 (默认 `backup=True`, `--no-backup` 显式关掉)**: 跟 `overwrite=False` 同款"默认安全 + 显式关掉"纪律. 用户跑 `--overwrite` 时, 默认就备份了——除非他**显式说**"我不要备份" (`--no-backup`).

⚠️ **设计点 (备份用 `logger.warning` 而不是 `warnings.warn`)** 备份是 **系统行为** (不是用户输入有问题), 走 logger 渠道. 规矩 B 的应用——把"用户配置质量"和"系统行为"的渠道严格分开.

⚠️ **设计点 (备份命名带秒级时间戳)** `%Y%m%d_%H%M%S` 一秒一个, 极端场景同秒内两次覆盖会让第二次备份盖掉第一次. **追加进程 ID 不值得 (徒增复杂度), 一秒两次的真实场景概率几乎为零, 接受这个边界**.

⚠️ **设计点 (返回 True/False 而不是抛异常)** 文件已存在不是 "错误"——是合法的常态. 让 caller (可能是用户的批量脚本) 根据返回值决定下一步, 比强制 catch 异常体验好. **"不该生成" 跟 "生成失败" 是两件事**, 用返回值表达前者, 异常表达后者.

> **金句**: **"`overwrite=False` 是第一道闸门, 备份是第二道. 任何会改变用户磁盘的操作都该有两道——一道挡掉无心之错, 一道留住有心之失."**

## 6.5 双入口(odp-gen-config / python -m): 子命令名 → 配置类映射

我们希望用户跑:

```bash
# ★ 主推: entry-point CLI(装包后可用)
odp-gen-config train                       # → 生成 train.yaml
odp-gen-config val                         # → 生成 val.yaml
odp-gen-config infer                       # → 生成 infer.yaml
odp-gen-config --help                      # 看帮助
odp-gen-config train --overwrite           # 强制覆盖(默认会自动备份)
odp-gen-config train --overwrite --no-backup  # 强制覆盖且不备份(谨慎)
odp-gen-config train -o my_train.yaml      # 自定义路径

# 备胎: python -m 入口(装包前可用, 调试 import 链时更直接)
python -m odp_platform.runtime_config.generator train
```

**两条命令完全等价**——entry-point 在 `pyproject.toml` 直接绑到 `runtime_config.generator:main`(详见 §0.5.4 规矩 D), `python -m` 走 `if __name__ == "__main__"` 块也调 `main()`, **两个入口共享同一份 argparse 逻辑**.

`python -m <module>` 这种用法要求模块包含 `__main__` 块:

```python
def main():
    parser = argparse.ArgumentParser(
        prog="odp-gen-config",
        description="生成 YOLO 运行配置 YAML 模板",
    )
    parser.add_argument(
        "name",
        choices=["train", "val", "infer"],            # ★ 加 infer
        help="要生成的配置名 (train / val / infer)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="输出路径 (默认: configs/runtime/<name>.yaml)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已有文件 (默认不覆盖)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="覆盖时不备份原文件 (默认会备份成 <name>.yaml.bak.<时间戳>)",
    )
    args = parser.parse_args()

    # name → config class 映射 (★ 加新模式 = 加一行)
    CONFIG_CLASS_MAP = {
        "train": (YOLOTrainConfig, "YOLO 训练配置"),
        "val":   (YOLOValConfig,   "YOLO 验证配置"),
        "infer": (YOLOInferConfig, "YOLO 推理配置"),     # ★ infer 闭环
    }
    config_class, title = CONFIG_CLASS_MAP[args.name]

    # 输出路径
    output_path = args.output or runtime_config_path(args.name)

    # 生成
    gen = ConfigGenerator()
    success = gen.generate(
        config_class,
        output_path,
        overwrite=args.overwrite,
        backup=not args.no_backup,
        title=title,
    )

    if success:
        print(f"✓ 已生成: {output_path}")
    else:
        print(
            f"- 文件已存在, 未覆盖 (避免覆盖你已编辑的配置).\n"
            f"  路径: {output_path}\n"
            f"  如需重新生成, 加 --overwrite (覆盖前会自动备份)"
        )


if __name__ == "__main__":
    main()
```

⚠️ **设计点 (`CONFIG_CLASS_MAP` 是个常量字典, 不是 if-elif)** 看着简单, 但 **加新模式就是加一行**(以后 D8 推理 → 加 `"infer": (YOLOInferConfig, "推理配置")`). 用 if-elif 会越长越乱, 而且容易漏 elif 分支. **数据结构表达"枚举到值的映射", 比 if-elif 更接近问题本身**.

⚠️ **设计点 (`choices=["train", "val"]` 限定 argparse 的值)** argparse 自带 `choices`, 用户敲 `python -m ...generator infer` 会立刻被 argparse 拒, 不用我们自己写验证. **能用 argparse 自带的, 不要自己造**.

⚠️ **设计点 (默认输出路径用 `runtime_config_path()`)** 阶段 0 立的 path helper 在这儿派上用场——`runtime_config_path("train")` → `<APP_DIR>/configs/runtime/train.yaml`. **没自己拼路径**, 走 SSoT.

## 6.6 完整代码: generator.py

`apps/platform/src/odp_platform/runtime_config/generator.py`:

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : generator.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统——YAML 模板生成器
"""配置文件生成器: 从 Pydantic 配置类反射生成 YAML 模板.

★ 设计核心:
   1. 反射, 不重复——所有元数据从 BaseConfig 的 get_field_groups() /
      get_field_metadata() 来, 不在 Generator 里维护一份字段表.
   2. 安全, 双闸门——默认 overwrite=False; 真覆盖时自动备份原文件.
   3. CLI 入口——主推 odp-gen-config <name> (pyproject.toml entry-point),
                 备胎 python -m odp_platform.runtime_config.generator <name>.

用法:
    # 程序调用:
    from odp_platform.runtime_config.generator import ConfigGenerator
    from odp_platform.runtime_config.train      import YOLOTrainConfig
    gen = ConfigGenerator()
    gen.generate(YOLOTrainConfig, "train.yaml", overwrite=False)

    # CLI:
    odp-gen-config train
    odp-gen-config val --overwrite                # 覆盖前自动备份
    odp-gen-config train --overwrite --no-backup  # 显式关掉备份
    odp-gen-config train -o /tmp/my_train.yaml
"""
from __future__ import annotations

import argparse
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Type, Union

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ============================================================
# ConfigGenerator
# ============================================================

class ConfigGenerator:
    """从 Pydantic 配置类反射生成 YAML 模板.

    使用阶段 2 立的 get_field_groups() / get_field_metadata() 反射元数据.
    """

    def __init__(self, indent: int = 2):
        """
        Args:
            indent: YAML 缩进空格数 (目前只用于嵌套结构, 当前简化未启用)
        """
        self.indent = indent

    # ============================================================
    # 公开接口
    # ============================================================

    def generate(
        self,
        config_class: Type[BaseModel],
        output_path: Union[str, Path],
        *,
        overwrite: bool = False,
        backup:    bool = True,
        title:     Optional[str] = None,
    ) -> bool:
        """生成配置文件.

        Args:
            config_class: Pydantic 配置类 (BaseConfig 的子类)
            output_path:  输出文件路径
            overwrite:    是否覆盖已有文件 (默认 False, 安全)
            backup:       覆盖前是否备份原文件 (默认 True).
                          仅在 overwrite=True 且 文件存在 时生效.
                          备份命名: <name>.yaml.bak.<YYYYMMDD_HHMMSS>
            title:        配置文件标题 (默认用类名)

        Returns:
            True  — 已生成
            False — 文件已存在且 overwrite=False, 未生成 (★ 不是错误)
        """
        output_path = Path(output_path)

        # 第一道防线: 不覆盖
        if output_path.exists() and not overwrite:
            logger.info(f"配置文件已存在, 跳过生成: {output_path}")
            return False

        # 第二道防线: 覆盖前备份
        if output_path.exists() and backup:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = output_path.with_name(
                f"{output_path.name}.bak.{stamp}"
            )
            shutil.copy2(output_path, backup_path)        # copy2 保留 metadata
            logger.warning(f"覆盖前已备份原配置: {backup_path}")

        # 创建父目录 (不存在的话)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 生成 YAML 内容
        content = self._generate_yaml(config_class, title)

        # 写入文件
        output_path.write_text(content, encoding="utf-8")
        logger.info(f"配置文件已生成: {output_path}")
        return True

    # ============================================================
    # 内部方法 — YAML 内容生成
    # ============================================================

    def _generate_yaml(
        self,
        config_class: Type[BaseModel],
        title: Optional[str] = None,
    ) -> str:
        """生成完整 YAML 内容(头部 + 字段分组 + 尾部 FAQ)"""
        lines: List[str] = []

        # 文件头部
        lines.append("#" + "=" * 78)
        lines.append(f"# {title or config_class.__name__}")
        lines.append(f"# 自动生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("#" + "=" * 78)
        lines.append("")

        # 创建默认实例(用于反射 group 信息和默认值)
        config = config_class()

        # 按分组生成字段
        groups = config.get_field_groups()
        for group_name, field_names in groups.items():
            lines.append("")
            lines.append("#" + "-" * 78)
            lines.append(f"# {group_name}")
            lines.append("#" + "-" * 78)
            lines.append("")
            for field_name in field_names:
                lines.extend(self._generate_field(config, field_name))
                lines.append("")        # 字段间空行

        # 文件尾部 — 常见问题 FAQ
        lines.append("")
        lines.append("#" + "=" * 78)
        lines.append("# 常见问题")
        lines.append("#" + "=" * 78)
        lines.append("#")
        lines.append("# Q: 如何修改配置?")
        lines.append("# A: 直接编辑对应参数的值, 保存后重新运行即可")
        lines.append("#")
        lines.append("# Q: 命令行参数会覆盖配置文件吗?")
        lines.append("# A: 是的, 命令行参数优先级最高: CLI > YAML > DEFAULT")
        lines.append("#")
        lines.append("# Q: 如何恢复默认配置?")
        lines.append("# A: 删除此文件, 程序会自动报错并提示重新生成")
        lines.append("#")
        lines.append("# Q: 如何用新版默认值重新生成此模板?")
        lines.append("# A: 跑 'odp-gen-config <name> --overwrite' (会自动备份原文件)")
        lines.append("#    备胎(装包前可用): python -m odp_platform.runtime_config.generator <name> --overwrite")
        lines.append("#")
        lines.append("#" + "=" * 78)

        return "\n".join(lines)

    def _generate_field(
        self,
        config: BaseModel,
        field_name: str,
    ) -> List[str]:
        """生成单个字段的 YAML 内容(含注释 + 值)"""
        lines: List[str] = []

        # 取字段元数据
        metadata = config.get_field_metadata(field_name)

        # 主注释 (yaml_comment, fallback 到 description)
        yaml_comment = metadata.get("yaml_comment") or metadata.get("description")
        if yaml_comment:
            lines.append(f"# {yaml_comment}")

        # 示例 (最多 5 个, 太多反而花眼)
        examples = metadata.get("examples", [])
        if examples:
            examples_str = ", ".join(str(e) for e in examples[:5])
            lines.append(f"# 示例: {examples_str}")

        # 提示 (一行一条)
        tips = metadata.get("tips", [])
        if tips:
            lines.append("# 提示:")
            for tip in tips:
                lines.append(f"#   - {tip}")

        # 字段值(默认值)
        value = getattr(config, field_name)
        yaml_value = self._format_value(value)
        lines.append(f"{field_name}: {yaml_value}")

        return lines

    # ============================================================
    # 内部方法 — YAML 值格式化
    # ============================================================

    def _format_value(self, value: Any) -> str:
        """格式化 Python 值为 YAML 字符串.

        ★ 顺序很重要: bool 必须在 int 之前判(bool 是 int 子类).
        """
        if value is None:
            return "null"

        if isinstance(value, bool):       # ★ 必须在 int / 数字判断之前
            return "true" if value else "false"

        if isinstance(value, str):
            # 含 YAML 特殊字符时加引号
            if any(c in value for c in [":", "#", "[", "]", "{", "}"]):
                return f'"{value}"'
            return value

        if isinstance(value, (list, tuple)):
            if not value:
                return "[]"
            items = ", ".join(str(v) for v in value)
            return f"[{items}]"

        if isinstance(value, dict):
            # 当前没有顶层 dict 字段, 简化处理
            return "{}"

        # 数字 / 其他类型
        return str(value)


# ============================================================
# python -m 入口
# ============================================================

def main():
    """命令行入口: odp-gen-config <name>  (也支持 python -m odp_platform.runtime_config.generator <name>)"""
    # 延迟导入: 避免 generator 被 import 时拉一堆依赖
    from odp_platform.common.paths           import runtime_config_path
    from odp_platform.runtime_config.train   import YOLOTrainConfig
    from odp_platform.runtime_config.val     import YOLOValConfig
    from odp_platform.runtime_config.infer   import YOLOInferConfig   # ★ infer 闭环

    parser = argparse.ArgumentParser(
        prog="odp-gen-config",
        description="从 Pydantic 配置类反射生成 YOLO 运行配置 YAML 模板",
    )
    parser.add_argument(
        "name",
        choices=["train", "val", "infer"],            # ★ 加 infer
        help="要生成的配置名 (train / val / infer)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="输出路径 (默认: configs/runtime/<name>.yaml)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已有文件 (默认不覆盖, 保护用户编辑过的 yaml)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="覆盖时不备份原文件 (默认会备份成 <name>.yaml.bak.<时间戳>)",
    )
    args = parser.parse_args()

    # name → (config_class, title) 映射 (★ 数据驱动, 加新模式只加一行)
    CONFIG_CLASS_MAP = {
        "train": (YOLOTrainConfig, "YOLO 训练配置"),
        "val":   (YOLOValConfig,   "YOLO 验证配置"),
        "infer": (YOLOInferConfig, "YOLO 推理配置"),     # ★ infer 闭环
    }
    config_class, title = CONFIG_CLASS_MAP[args.name]

    # 输出路径默认走 paths.py 的 helper (走 SSoT, 不自拼)
    output_path = args.output or runtime_config_path(args.name)

    # 生成
    gen = ConfigGenerator()
    success = gen.generate(
        config_class,
        output_path,
        overwrite=args.overwrite,
        backup=not args.no_backup,
        title=title,
    )

    if success:
        print(f"✓ 已生成: {output_path}")
    else:
        print(
            f"- 文件已存在, 未覆盖 (避免覆盖你已编辑的配置).\n"
            f"  路径: {output_path}\n"
            f"  如需重新生成, 加 --overwrite (覆盖前会自动备份)"
        )


if __name__ == "__main__":
    main()
```

代码约 270 行——生成器本身 200 行, `main()` 入口 70 行. 核心算法只有 `_generate_yaml` 那 40 行循环, 剩下都是元数据格式化和 CLI 入口.

## 6.7 端到端测试: 生成 → 加载 → 合并

跟阶段 4 / 5 不一样, 阶段 6 测试要验证 **整个 runtime_config 子系统串起来能跑**——生成模板, 把它当输入加载, 合并 CLI, 走 Pydantic 验证.

> 💡 **前置确认见 2.7** —— editable install 必须生效. 6.7 测试涉及 generator / loaders / merger 多模块串联, 如果其中任何 import 失败, 检查环境.

```python
import tempfile
from pathlib import Path
from pydantic import ValidationError

from odp_platform.runtime_config.generator import ConfigGenerator
from odp_platform.runtime_config.train     import YOLOTrainConfig
from odp_platform.runtime_config.val       import YOLOValConfig
from odp_platform.runtime_config.infer     import YOLOInferConfig      # ★ infer 闭环
from odp_platform.runtime_config.loaders   import YAMLLoader
from odp_platform.runtime_config.merger    import ConfigMerger, ConfigSource   # ★ ConfigSource 漏写补上

# ============================================================
# 1. ConfigGenerator.generate — 基本生成
# ============================================================
temp_dir = Path(tempfile.gettempdir()) / "odp_d5_test"
temp_dir.mkdir(parents=True, exist_ok=True)
train_yaml = temp_dir / "train.yaml"
if train_yaml.exists():
    train_yaml.unlink()

gen = ConfigGenerator()
ok = gen.generate(YOLOTrainConfig, train_yaml, overwrite=False, title="YOLO 训练配置")
assert ok is True
assert train_yaml.exists()
print(f"✓ 生成 train.yaml: {train_yaml}")
print(f"  文件大小: {train_yaml.stat().st_size} 字节")

# ============================================================
# 2. 生成的 yaml 内容包含 group 标题
# ============================================================
content = train_yaml.read_text(encoding="utf-8")

# 必须包含所有 11 个 group + 5 个 base group
required_groups = [
    "核心参数", "训练控制", "优化器配置", "学习率预热",
    "损失权重", "数据增强-颜色", "数据增强-几何",
    "数据增强-拼接", "验证和输出", "任务特定", "高级设置",
    "输入配置", "设备配置", "输出配置", "基础设置",
]
for g in required_groups:
    assert g in content, f"缺失分组: {g}"
print(f"✓ 所有 {len(required_groups)} 个分组都在 yaml 里")

# ============================================================
# 3. 生成的 yaml 包含三段注释 (yaml_comment / 示例 / 提示)
# ============================================================
# 拿 epochs 字段一段做样本检查
assert "# 训练总轮数(epoch)" in content
assert "# 示例: 50, 100, 200, 300" in content
assert "# 提示:" in content
assert "#   - 小数据集: 50-100 轮" in content
assert "epochs: 100" in content
print("✓ epochs 字段三段注释 + 默认值齐全")

# ============================================================
# 4. 生成的 yaml 头部 + 尾部 FAQ
# ============================================================
assert "自动生成时间:" in content
assert "YOLO 训练配置" in content
assert "Q: 如何修改配置?" in content
assert "CLI > YAML > DEFAULT" in content
print("✓ 头部时间戳 + 尾部 FAQ 完整")

# ============================================================
# 5. _format_value 各类型测试
# ============================================================
fmt = gen._format_value

assert fmt(None)       == "null"
assert fmt(True)       == "true"           # ★ bool 必须在 int 前
assert fmt(False)      == "false"
assert fmt(100)        == "100"
assert fmt(0.01)       == "0.01"
assert fmt("detect")   == "detect"
assert fmt("a:b")      == '"a:b"'          # 含 : → 加引号
assert fmt([])         == "[]"
assert fmt([1, 2, 3])  == "[1, 2, 3]"
assert fmt({})         == "{}"
print("✓ _format_value 7 种类型都正确")

# ============================================================
# 6. overwrite=False 不覆盖已有文件
# ============================================================
content_before = train_yaml.read_text(encoding="utf-8")
import time
time.sleep(0.1)        # 让 timestamp 不同
ok2 = gen.generate(YOLOTrainConfig, train_yaml, overwrite=False)
assert ok2 is False, "已存在的文件不该被覆盖"
content_after = train_yaml.read_text(encoding="utf-8")
assert content_before == content_after, "文件内容不该变化"
print("✓ overwrite=False 保护已有文件")

# ============================================================
# 7. overwrite=True 强制覆盖
# ============================================================
ok3 = gen.generate(YOLOTrainConfig, train_yaml, overwrite=True)
assert ok3 is True
content_after = train_yaml.read_text(encoding="utf-8")
print("✓ overwrite=True 强制覆盖")

# ============================================================
# 8. 生成 val.yaml 也跑得通
# ============================================================
val_yaml = temp_dir / "val.yaml"
if val_yaml.exists():
    val_yaml.unlink()
ok4 = gen.generate(YOLOValConfig, val_yaml, title="YOLO 验证配置")
assert ok4 is True
val_content = val_yaml.read_text(encoding="utf-8")
assert "验证控制" in val_content
assert "split: val" in val_content
assert "conf: 0.001" in val_content       # val 默认 conf
print("✓ val.yaml 生成且包含 val 特有字段")

# ============================================================
# 9. ★ 端到端: 生成 → 编辑(模拟) → 加载 → 合并 → Pydantic
# ============================================================
# 模拟用户编辑 train.yaml: 改了几个字段
edited = train_yaml.read_text(encoding="utf-8")
edited = edited.replace("epochs: 100", "epochs: 200")
edited = edited.replace("lr0: 0.01",   "lr0: 0.001")
edited = edited.replace("model: null", "model: yolo11n.pt")
train_yaml.write_text(edited, encoding="utf-8")

# 加载 yaml
yaml_loader = YAMLLoader()
yaml_cfg = yaml_loader.load(train_yaml)
assert yaml_cfg["epochs"] == 200
assert yaml_cfg["lr0"]    == 0.001
assert yaml_cfg["model"]  == "yolo11n.pt"
print(f"✓ YAMLLoader 加载生成的 yaml 成功")

# 合并 + Pydantic 验证
merger = ConfigMerger(track_sources=True)
config = merger.merge(
    YOLOTrainConfig,
    sources=[
        (ConfigSource.YAML, yaml_cfg),
        (ConfigSource.CLI,  {"batch": 32}),
    ],
)
assert config.epochs == 200             # YAML
assert config.lr0    == 0.001           # YAML
assert config.batch  == 32              # CLI
assert config.optimizer == "auto"       # DEFAULT
print(f"✓ 端到端: epochs={config.epochs} (YAML), batch={config.batch} (CLI)")

# 溯源链
meta = merger.get_metadata("epochs")
assert "200(YAML)" in meta.chain_str()
assert "100(DEFAULT)" in meta.chain_str()
print(f"✓ epochs 溯源链: {meta.chain_str()}")

# ============================================================
# 10. python -m 入口的烟测(用 subprocess)
# ============================================================
import subprocess
import sys

cli_temp = temp_dir / "cli_train.yaml"
if cli_temp.exists():
    cli_temp.unlink()

result = subprocess.run(
    [sys.executable, "-m", "odp_platform.runtime_config.generator",
     "train", "-o", str(cli_temp), "--overwrite"],
    capture_output=True, text=True,
)
assert result.returncode == 0, f"python -m 入口报错: {result.stderr}"
assert cli_temp.exists()
assert "✓ 已生成" in result.stdout
print(f"✓ python -m 入口生成: {cli_temp.name}")

# 再跑一次, 不带 --overwrite, 应该提示文件已存在
result2 = subprocess.run(
    [sys.executable, "-m", "odp_platform.runtime_config.generator",
     "train", "-o", str(cli_temp)],
    capture_output=True, text=True,
)
assert result2.returncode == 0
assert "文件已存在" in result2.stdout
assert "--overwrite" in result2.stdout
print("✓ python -m 入口不覆盖 + 提示 --overwrite")

# 错误的 name 应该被 argparse choices 拒
result3 = subprocess.run(
    [sys.executable, "-m", "odp_platform.runtime_config.generator", "notexist"],
    capture_output=True, text=True,
)
assert result3.returncode != 0
assert "invalid choice" in result3.stderr or "notexist" in result3.stderr
print("✓ python -m 入口拒绝非法 name (argparse choices)")

# ============================================================
# 11. infer.yaml 也跑得通
# ============================================================
infer_yaml = temp_dir / "infer.yaml"
if infer_yaml.exists():
    infer_yaml.unlink()
ok5 = gen.generate(YOLOInferConfig, infer_yaml, title="YOLO 推理配置")
assert ok5 is True
infer_content = infer_yaml.read_text(encoding="utf-8")
assert "推理控制" in infer_content
assert "视频流" in infer_content
assert "source: null" in infer_content
assert "conf: 0.25" in infer_content       # ★ 推理默认 0.25, 不同于 val 的 0.001
print("✓ infer.yaml 生成且包含 infer 特有字段")

# 清理
import shutil
shutil.rmtree(temp_dir, ignore_errors=True)
print("\n--- 阶段 6 端到端测试通过 ---")
```

应该全部 ✓. **这套测试跑完, runtime_config 子系统的所有部分都串起来工作了**——生成、加载、合并、验证, 全流程贯通.

## 6.8 真正跑一次: 生成 + 编辑 + 加载

进 shell 试试(主推 entry-point 命令):

```bash
# 1. 生成 train.yaml
odp-gen-config train
# 输出:
#   ✓ 已生成: /path/to/apps/platform/configs/runtime/train.yaml
#
# 备胎(装包前可用): python -m odp_platform.runtime_config.generator train

# 2. 看看生成的文件长啥样
head -50 apps/platform/configs/runtime/train.yaml
```

应该看到:

```yaml
#==============================================================================
# YOLO 训练配置
# 自动生成时间: 2026-05-20 14:32:15
#==============================================================================


#------------------------------------------------------------------------------
# 核心参数
#------------------------------------------------------------------------------

# 任务类型(只能是 detect / segment)
# 示例: detect, segment
# 提示:
#   - 限定取值: detect / segment
#   - 决定模型加载方式 + 输出目录的一级子目录
#   - 想给实验起名? → 用 experiment_name 字段
task: detect

# 实验名(目录组织, 不影响语义; None=自动生成)
# 示例: baseline, helmet_v1, lr001_aug_strong, None
# 提示:
#   - None: 由 ultralytics 自动生成 exp / exp2 / exp3...
#   - 自定义: 用作 runs/<task>/<experiment_name>/ 子目录
#   - 推荐命名: <模型>_<数据集>_<关键调参>
experiment_name: null
...
```

```bash
# 3. 第二次跑(不带 --overwrite)
odp-gen-config train
# 输出:
#   - 文件已存在, 未覆盖(避免覆盖你已编辑的配置).
#     路径: ...
#     如需重新生成, 加 --overwrite

# 4. 也生成一份 val.yaml
odp-gen-config val
#   ✓ 已生成: /path/to/apps/platform/configs/runtime/val.yaml
```

⚠️ **设计点 (这俩 yaml 应该提交进 git)** 跟 `configs/datasets/` 一样, **生成的运行配置 yaml 是项目的"实验可复现性"的一部分**, 应该跟着代码一起进 git. 不在 git 里, 别人 clone 完不知道你训练用的啥参数. **目录的 git 策略和文件生成策略要对齐**.

⚠️ **设计点 (用户改完 yaml 是不是要重新生成?)** **不需要**. yaml 是用户拥有的, 改完直接保存. 只有当 **添加了新字段** 时(将来阶段 7+ 重构 Pydantic 模型), 用户可能想看新字段的元数据——这时再 `--overwrite` 重新生成一份, 把自己的改动 merge 回去. 这是文档化里要重点强调的工作流, ADR-005 写到.

> **金句**: **"生成器不是'帮用户写 yaml', 是'让源码里的字段元数据可见'. 用户编辑的是 yaml, 但他实际接触到的是源码里的设计."**

## 6.9 git commit

```bash
git add apps/platform/src/odp_platform/runtime_config/generator.py
git commit -m "feat(runtime_config): add ConfigGenerator + dual CLI entry (odp-gen-config / python -m)

runtime_config/generator.py:
  + ConfigGenerator:
      .generate(config_class, output_path, *, overwrite, title) → bool
        Returns True if generated, False if file exists and overwrite=False.
        Reflects all metadata from BaseConfig.get_field_groups() and
        BaseConfig.get_field_metadata() — no duplication of field info.
      ._generate_yaml(config_class, title)   — full YAML composition
      ._generate_field(config, field_name)   — single field with 3 comments
      ._format_value(value)                  — Python → YAML conversion

  + main() — argparse-based CLI entry, invokable via:
      odp-gen-config train                       (★ primary, entry-point)
      odp-gen-config val --overwrite
      odp-gen-config train -o /tmp/my_train.yaml
      python -m odp_platform.runtime_config.generator train   (fallback)
    CONFIG_CLASS_MAP (data-driven): {name → (class, title)}
    output defaults to runtime_config_path(name) — uses paths.py SSoT.

Output format per field:
  # <yaml_comment>
  # 示例: <examples, capped at 5>
  # 提示:
  #   - <tip 1>
  #   - <tip 2>
  <field_name>: <default_value>

Plus file header (title + timestamp) and footer (FAQ).
Sections grouped by Field's json_schema_extra['group'] —
order follows Python dict insertion order, which matches the
order fields appear in BaseConfig/TrainConfig/ValConfig source.

Key design — safety policy:
  Default overwrite=False. Returns False (not raise) when file
  exists — 'file exists' is a normal state, not an error. Users
  must pass --overwrite explicitly to destroy their hand-edited yaml.

Key design — reflection over duplication:
  Generator never lists fields. It only walks get_field_groups()
  and get_field_metadata(). Add a new field to YOLOTrainConfig,
  generator picks it up automatically next time.

Key design — bool MUST be checked before int in _format_value:
  bool is a subclass of int in Python. Without the order guard,
  True would format as 'True' (Python) instead of 'true' (YAML).
  Same class of footgun as BaseConfig._validate_batch in stage 2.

Notes:
  - Generated YAML files SHOULD be committed to git — they're part
    of experiment reproducibility, just like configs/datasets/*.yaml.
  - String values containing : # [ ] { } get quoted defensively.
    Other YAML special chars (leading -, leading space) not handled
    because no default values trigger them. Tighten if it becomes
    a real footgun.
  - argparse choices=['train', 'val'] rejects unknown names at the
    CLI layer (no need for custom validation).
"
```

**中文版**:

```bash
git commit -m "feat(runtime_config): 新增 ConfigGenerator 模板生成器与双入口 CLI (odp-gen-config / python -m)" \
           -m "runtime_config/generator.py:" \
           -m "  + ConfigGenerator.generate(cls, path, *, overwrite, backup, title)" \
           -m "    从 Pydantic 字段元数据反射生成带注释的 YAML 模板" \
           -m "    按 group 分章节, 每字段三段注释 (yaml_comment / 示例 / 提示)" \
           -m "    文件头加生成时间, 文件尾加 FAQ" \
           -m "  + 安全策略双闸门:" \
           -m "    第一道: 默认 overwrite=False, 文件已存在直接跳过" \
           -m "    第二道: --overwrite 覆盖前自动备份成 <name>.yaml.bak.<时间戳>" \
           -m "    --no-backup 显式关掉备份" \
           -m "  + 双入口 CLI: 主推 odp-gen-config <name>, 备胎 python -m ...generator <name>" \
           -m "    name = train / val / infer (CONFIG_CLASS_MAP 注册, 三模式全支持)" \
           -m "  + pyproject.toml 直接绑 odp-gen-config = runtime_config.generator:main" \
           -m "    (不立 cli/generate_config.py 薄包装 — generator 自带 main 即可)" \
           -m "为什么生成器从源码反射而不是手写模板:" \
           -m "  legacy 模板是手维护的, 加新字段时常忘改注释 → 文档跟代码漂移." \
           -m "  D5 把字段元数据 (description/examples/tips/yaml_comment) 写在源码里," \
           -m "  yaml 模板从源码反射出来 —— 一次定义, 两处复用, 永不漂移." \
           -m "关键设计:" \
           -m "  - _format_value 把 bool 判断放在 int 之前 (经典坑: bool 是 int 子类)" \
           -m "  - 字符串含 YAML 特殊字符 (: # [ ] { }) 自动加引号" \
           -m "  - CONFIG_CLASS_MAP 用 dict 注册, 加新模式 = 加一行映射 (开闭原则)" \
           -m "  - argparse choices 限制 name 取值, 不用自己写验证" \
           -m "  - 跟 D2.5 odp-reset 同款纪律: 危险动作要确认 + 留底"
```


至此, **所有 4 个伤痛都被解决了**:

| 伤痛 | 解法 | 阶段 |
|---|---|---|
| ① 字段散落三处 | Pydantic `Field` 一次定义 + ClassVar 扩展 | 2 / 3 |
| ② 没有验证 | `Field(ge=...)` + `@field_validator` + `extra='forbid'` | 2 / 3 |
| ③ 没有溯源 | `ConfigMerger` + `ConfigMetadata` 链表 | 5 |
| ④ YAML 模板手维护 | `ConfigGenerator` 从 Field 反射 | 6 |
| ⑤ D5 特有: YAML 不存在 | fail-fast + 修复指引 | 4 |

第 3 部分要做的: **公共 API + 单元测试 + ADR**, 把这套子系统封进一个干净的对外面板, 交给 D6 TrainService 调用.

> **金句**: **"反射式生成是'源码即文档'的极致——你写的不是 yaml 注释, 你写的是字段元数据; yaml 注释只是它的一份投影."**

---
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 7: `__init__.py`——对外面板

阶段 2-6 把 5 个模块写得整整齐齐, 但 D6 (service 层) 要 import 时, 应该写哪一行?

```python
# 方案 A: import 每一个具体模块
from odp_platform.runtime_config.train       import YOLOTrainConfig
from odp_platform.runtime_config.loaders     import YAMLLoader, CLILoader
from odp_platform.runtime_config.merger      import ConfigMerger, ConfigSource
from odp_platform.runtime_config.generator   import ConfigGenerator

# 方案 B: 统一从子系统根 import
from odp_platform.runtime_config import (
    YOLOTrainConfig, YAMLLoader, CLILoader,
    ConfigMerger, ConfigSource, ConfigGenerator,
)
```

方案 B 更自然——这就是 `__init__.py` 的工作.

但 `__init__.py` 不只是 "再写一遍 import 重导出". 它是 **子系统对外的面板**——决定外界看到什么, 看不到什么. 一个写得糟糕的 `__init__.py` 会让 "我以为是内部细节的东西" 被外界 import, 然后想改的时候动不了——**API 是一旦发布就有兼容压力的**.

> **金句**: **"`__init__.py` 不是 '把所有公开符号 import 一遍', 是 '明确告诉外界:这是我支持你用的, 其余你别碰'. 它是子系统的合同."**

## 7.1 公开什么 / 不公开什么

`runtime_config/` 里所有模块加起来有几十个函数和类. 不是每个都该出现在 `__init__.py` 里. 判据:

| 符号 | 公开? | 理由 |
|---|---|---|
| `BaseConfig` | ✅ | 未来扩展用户可能继承 |
| `YOLOTrainConfig`, `YOLOValConfig`, `YOLOInferConfig` | ✅ | service 层主体 (D6 训练 / D7 验证 / D8 推理) |
| `YAMLLoader`, `CLILoader` | ✅ | 上层组装时按需 import |
| `load_all_sources` | ✅ | 便捷函数, 减少上层重复代码 |
| `ConfigMerger`, `ConfigSource`, `ConfigMetadata` | ✅ | 溯源接口对外 |
| `ConfigGenerator` | ✅ | service 层也可能调(自动生成模板) |
| `_drop_none` | ❌ | 内部工具, 名字带 `_` 就是 "别 import" |
| `_CONFIG_REGISTRY` | ❌ | generator 内部注册表, 别人不该 patch |
| `build_train_config` / `build_val_config` / `build_infer_config` | ✅ | **一键 build 便捷函数** — 7.2 介绍 |

⚠️ **设计点 (用 `_` 前缀表达 "私有", Python 没有强制私有)** Python 没有真正的 private, 只有约定. `_drop_none` 在 `loaders.py` 里写, 外界 **能** import 但 **不该** import. **约定就是合同**——前缀下划线的符号就当成 "随时可能改没", 调用者自负风险.

⚠️ **设计点 (`__all__` 同时是 "import * 白名单" 和 "公开文档")**:
```python
__all__ = ["BaseConfig", "YOLOTrainConfig", ...]
```
两个作用:
1. `from xxx import *` 时只导出 `__all__` 列表里的
2. **更重要的**: IDE / Sphinx / pdoc 等工具读 `__all__` 生成文档, **它就是子系统的公开 API 清单**

凡是不在 `__all__` 里的, 都不算公开 API——这给了我们改它的自由.

## 7.2 便捷函数: `build_train_config` / `build_val_config`

阶段 4 的 `load_all_sources` 把 YAML + CLI 加载封到一起, 阶段 5 的 ConfigMerger 用 sources list 接口合并. 整条流水线 D6 service 层最常用的形态是:

```python
# 流水线 (5 步)
loader_yaml   = YAMLLoader(config_dir=RUNTIME_CONFIGS_DIR)
yaml_config   = loader_yaml.load("train.yaml")        # 1. YAML

loader_cli    = CLILoader(exclude=["my_flag"])
cli_config    = loader_cli.load(args)                  # 2. CLI

sources_list  = []                                     # 3. 拼 sources
if yaml_config:
    sources_list.append((ConfigSource.YAML, yaml_config))
if cli_config:
    sources_list.append((ConfigSource.CLI, cli_config))

merger        = ConfigMerger(track_sources=True)
config        = merger.merge(                          # 4. Merge
    YOLOTrainConfig,
    sources=sources_list,
)
# 5. 用 config + merger 接着干活
```

D6 每个 service 都要写这 5 步? 不优雅. 给一个一键 build 的函数:

```python
def build_train_config(
    yaml_path:     Optional[Union[str, Path]] = "train.yaml",
    cli_args:      Optional[Union[Namespace, Dict[str, Any]]] = None,
    *,
    yaml_dir:      Optional[Union[str, Path]] = None,
    cli_exclude:   Optional[list[str]]        = None,
    cli_mapping:   Optional[dict[str, str]]   = None,
    extra_sources: Optional[list[tuple[Union[ConfigSource, str], Mapping[str, Any]]]] = None,
    track_sources: bool = True,
    dry_run:       bool = False,
) -> tuple[Optional[YOLOTrainConfig], ConfigMerger]:
    """一键完成: YAML 加载 + CLI 加载 + 三源合并.

    Args:
        yaml_path:     YAML 文件名/路径. None 跳过 YAML.
        cli_args:      argparse.Namespace 或 dict. None 跳过 CLI.
        yaml_dir:      YAML 目录, 默认 RUNTIME_CONFIGS_DIR.
        cli_exclude:   CLI 额外排除字段.
        cli_mapping:   CLI 参数名映射.
        extra_sources: 额外配置源, 插在 YAML 和 CLI 之间.
                       例: [("ENV", env_dict)] 让环境变量优先级低于 CLI 高于 YAML.
        track_sources: 是否追踪溯源.
        dry_run:       True = 只合并不验证, 返回 (None, merger), 调 merger.get_source_report() 看.
                       False = 正常合并 + 验证, 返回 (config, merger).

    Returns:
        正常模式: (validated_config, merger)
        dry_run:  (None, merger)
    """
    from odp_platform.common.paths import RUNTIME_CONFIGS_DIR

    # 1. 加载各源
    sources = load_all_sources(
        yaml_path   = yaml_path,
        yaml_dir    = yaml_dir or RUNTIME_CONFIGS_DIR,
        cli_args    = cli_args,
        cli_exclude = cli_exclude,
        cli_mapping = cli_mapping,
    )

    # 2. 拼 sources list, 顺序: YAML < extra_sources < CLI
    sources_list: list[tuple[Union[ConfigSource, str], Mapping[str, Any]]] = []
    if sources["yaml"]:
        sources_list.append((ConfigSource.YAML, sources["yaml"]))
    if extra_sources:
        sources_list.extend(extra_sources)
    if sources["cli"]:
        sources_list.append((ConfigSource.CLI, sources["cli"]))

    # 3. 合并 (dry_run 走 preview, 否则走 merge)
    merger = ConfigMerger(track_sources=track_sources)
    if dry_run:
        merger.preview(YOLOTrainConfig, sources=sources_list)
        return None, merger
    config = merger.merge(YOLOTrainConfig, sources=sources_list)
    return config, merger
```

⚠️ **设计点 (返回 tuple 而不是只返回 config)**: D6 service 层不只用 `config`, 还要打来源报告(`merger.get_source_report()`)、查溯源链(`merger.get_metadata(...)`)、推审计日志(`merger.to_audit_log()`). 返回 `(config, merger)` 让两者都拿在手里. **多返回一个 merger 的成本是 0, 但缺它就要重新跑流水线**.

⚠️ **设计点 (`yaml_path` 默认值是 "train.yaml")** 不是 None. 90% 的 D6 调用是 "从默认目录加载默认文件名"——直接给个合理默认, 上层一行代码 `cfg, m = build_train_config()` 就跑通. 显式传 `yaml_path=None` 才是 "跳过 yaml, 只用 CLI + DEFAULT".

⚠️ **设计点 (`extra_sources` 插在 YAML 和 CLI 之间)** 默认顺序——CLI 优先级永远最高 (用户当场敲的参数最权威). 中间档给 "环境变量 / etcd / 实验中央配置服务" 这类介于 "长期定下来的 YAML" 和 "临时覆盖的 CLI" 之间的源. **调用方想换顺序? 直接调 `ConfigMerger.merge()`, 别走 `build_*` 便捷函数**——便捷函数应该让 80% 场景一行解决, 不应该把所有自由度都暴露出来.

⚠️ **设计点 (`dry_run=True` 返回 `(None, merger)` 而不是 `(merged_dict, merger)`)** 返回类型保持 `tuple[..., ConfigMerger]`, 只是第一项变 None. 调用方习惯写 `config, merger = build_train_config(...)`, dry-run 时 `config is None` 一眼能判, 不需要解构两套返回值. **类型对称, 即使 dry_run 时第一位是 None 也比换返回签名好**.

⚠️ **设计点 (`build_train_config` 和 `build_val_config` 是两个函数, 不是一个带参数)**:

```python
# 反例: 一个函数靠参数切换
def build_config(mode: str, ...) -> ...:
    cls = {"train": YOLOTrainConfig, "val": YOLOValConfig}[mode]
    ...

# 正例: 两个独立函数
def build_train_config(...) -> tuple[Optional[YOLOTrainConfig], ConfigMerger]: ...
def build_val_config  (...) -> tuple[Optional[YOLOValConfig],   ConfigMerger]: ...
```

返回类型不同, 用 mode 参数会让返回值变成 `Union[YOLOTrainConfig, YOLOValConfig]`——D6 调用方拿到要 `assert isinstance(...)` 才能让 mypy 知道类型. **两个函数, 各自类型清晰, 更好用**.

⚠️ **设计点 (`*,` 强制后面的参数走关键字)** `*` 之后的参数(`yaml_dir`、`cli_exclude`、`extra_sources`、`dry_run` 等)必须用关键字传, 不能位置传. 防止未来加新参数时调用方位置错乱. 这是 Python 3 的强制关键字参数语法.

> **金句**: **"便捷函数的设计要求 '80% 场景一行解决 + 20% 高级用法留口子'. 一行解决用默认值, 留口子靠 extra_sources / dry_run 这种关键字参数."**

## 7.3 完整代码: `__init__.py`

`apps/platform/src/odp_platform/runtime_config/__init__.py`:

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : __init__.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : runtime_config 子系统对外公共 API
"""runtime_config — YOLO 训练 / 验证配置子系统.

公共 API:

  配置类:
      BaseConfig, YOLOTrainConfig, YOLOValConfig

  加载器(外部数据 → dict):
      YAMLLoader, CLILoader, load_all_sources

  合并器(三源合并 + 溯源):
      ConfigMerger, ConfigSource, ConfigMetadata

  生成器(Pydantic → YAML 模板):
      ConfigGenerator

  一键 build:
      build_train_config, build_val_config

不公开:
  - _drop_none / _CONFIG_REGISTRY 等内部工具
  - 不在 __all__ 里的所有符号都是内部细节, 可能在小版本变化

典型用法 (在 D6 service 层):

    from odp_platform.runtime_config import build_train_config

    config, merger = build_train_config(
        yaml_path = "train.yaml",
        cli_args  = args,         # argparse.Namespace
    )

    # 主线: 用 config 跑训练
    model.train(**config.to_ultralytics_kwargs())

    # 副线: 打来源报告 / 查单字段溯源
    print(merger.get_source_report())
    print(merger.get_metadata("lr0").chain_str())
"""
from __future__ import annotations

from argparse import Namespace
from pathlib  import Path
from typing   import Any, Dict, List, Mapping, Optional, Tuple, Union

# 配置类
from odp_platform.runtime_config.base   import BaseConfig
from odp_platform.runtime_config.train  import YOLOTrainConfig
from odp_platform.runtime_config.val    import YOLOValConfig
from odp_platform.runtime_config.infer  import YOLOInferConfig   # ★ infer 闭环

# 加载器
from odp_platform.runtime_config.loaders import (
    YAMLLoader,
    CLILoader,
    load_all_sources,
)

# 合并器
from odp_platform.runtime_config.merger import (
    ConfigMerger,
    ConfigSource,
    ConfigMetadata,
)

# 生成器
from odp_platform.runtime_config.generator import ConfigGenerator


# ============================================================
# 一键 build 便捷函数
# ============================================================

def build_train_config(
    yaml_path: Optional[Union[str, Path]] = "train.yaml",
    cli_args:  Optional[Union[Namespace, Dict[str, Any]]] = None,
    *,
    yaml_dir:      Optional[Union[str, Path]] = None,
    cli_exclude:   Optional[List[str]]        = None,
    cli_mapping:   Optional[Dict[str, str]]   = None,
    extra_sources: Optional[List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]]] = None,
    track_sources: bool = True,
    dry_run:       bool = False,
) -> Tuple[Optional[YOLOTrainConfig], ConfigMerger]:
    """一键完成 train 配置流水线: YAML + CLI (+ 自定义源) → 合并 → 验证.

    Args:
        yaml_path:     YAML 文件名 / 路径. None 跳过 yaml 加载.
                      默认 "train.yaml" (从 yaml_dir 找).
        cli_args:      argparse.Namespace 或 dict. None 跳过 CLI 加载.
        yaml_dir:      YAML 目录, 默认 paths.RUNTIME_CONFIGS_DIR.
        cli_exclude:   CLI 额外排除字段 (并入 CLILoader.DEFAULT_EXCLUDE).
        cli_mapping:   CLI 参数名映射 (CLI 名 → Pydantic 字段名).
        extra_sources: 额外配置源 [(source_id, dict), ...],
                       插入到 YAML 和 CLI 之间. 例: 环境变量 / etcd.
                       想换顺序? 直接调 ConfigMerger.merge().
        track_sources: 是否追踪溯源 (默认 True).
        dry_run:       True = 只合并不验证, 返回 (None, merger).
                       False = 正常合并 + 验证, 返回 (config, merger).

    Returns:
        正常模式: (validated_config, merger)
        dry_run:  (None, merger)         # config=None, merger 内有完整溯源

    Raises:
        FileNotFoundError: YAML 文件不存在 (带修复指引)
        ValidationError:   Pydantic 字段验证失败 (已注入溯源链), dry_run=True 时不 raise
    """
    # 延迟 import 避免循环依赖 + 让 paths.py 改动不击穿这里
    from odp_platform.common.paths import RUNTIME_CONFIGS_DIR

    # 1. 加载各源
    sources = load_all_sources(
        yaml_path   = yaml_path,
        yaml_dir    = yaml_dir or RUNTIME_CONFIGS_DIR,
        cli_args    = cli_args,
        cli_exclude = cli_exclude,
        cli_mapping = cli_mapping,
    )

    # 2. 拼 sources list, 顺序: YAML < extra_sources < CLI
    sources_list: List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]] = []
    if sources["yaml"]:
        sources_list.append((ConfigSource.YAML, sources["yaml"]))
    if extra_sources:
        sources_list.extend(extra_sources)
    if sources["cli"]:
        sources_list.append((ConfigSource.CLI, sources["cli"]))

    # 3. 合并 (dry_run 走 preview, 否则走 merge)
    merger = ConfigMerger(track_sources=track_sources)
    if dry_run:
        merger.preview(YOLOTrainConfig, sources=sources_list)
        return None, merger
    config = merger.merge(YOLOTrainConfig, sources=sources_list)
    return config, merger


def build_val_config(
    yaml_path: Optional[Union[str, Path]] = "val.yaml",
    cli_args:  Optional[Union[Namespace, Dict[str, Any]]] = None,
    *,
    yaml_dir:      Optional[Union[str, Path]] = None,
    cli_exclude:   Optional[List[str]]        = None,
    cli_mapping:   Optional[Dict[str, str]]   = None,
    extra_sources: Optional[List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]]] = None,
    track_sources: bool = True,
    dry_run:       bool = False,
) -> Tuple[Optional[YOLOValConfig], ConfigMerger]:
    """一键完成 val 配置流水线: YAML + CLI (+ 自定义源) → 合并 → 验证.

    参数语义和返回值结构与 build_train_config 完全一致, 仅类型不同.
    """
    from odp_platform.common.paths import RUNTIME_CONFIGS_DIR

    sources = load_all_sources(
        yaml_path   = yaml_path,
        yaml_dir    = yaml_dir or RUNTIME_CONFIGS_DIR,
        cli_args    = cli_args,
        cli_exclude = cli_exclude,
        cli_mapping = cli_mapping,
    )

    sources_list: List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]] = []
    if sources["yaml"]:
        sources_list.append((ConfigSource.YAML, sources["yaml"]))
    if extra_sources:
        sources_list.extend(extra_sources)
    if sources["cli"]:
        sources_list.append((ConfigSource.CLI, sources["cli"]))

    merger = ConfigMerger(track_sources=track_sources)
    if dry_run:
        merger.preview(YOLOValConfig, sources=sources_list)
        return None, merger
    config = merger.merge(YOLOValConfig, sources=sources_list)
    return config, merger


def build_infer_config(
    yaml_path: Optional[Union[str, Path]] = "infer.yaml",
    cli_args:  Optional[Union[Namespace, Dict[str, Any]]] = None,
    *,
    yaml_dir:      Optional[Union[str, Path]] = None,
    cli_exclude:   Optional[List[str]]        = None,
    cli_mapping:   Optional[Dict[str, str]]   = None,
    extra_sources: Optional[List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]]] = None,
    track_sources: bool = True,
    dry_run:       bool = False,
) -> Tuple[Optional[YOLOInferConfig], ConfigMerger]:
    """一键完成 infer 配置流水线: YAML + CLI (+ 自定义源) → 合并 → 验证.

    参数语义和返回值结构与 build_train_config 完全一致, 仅类型不同.

    典型用法 (D8 InferService):
        # source 通过 CLI 当场传, 不写进 yaml
        config, merger = build_infer_config(
            yaml_path="infer.yaml",
            cli_args={"source": "video.mp4"},
        )
        model.predict(**config.to_ultralytics_kwargs())
    """
    from odp_platform.common.paths import RUNTIME_CONFIGS_DIR

    sources = load_all_sources(
        yaml_path   = yaml_path,
        yaml_dir    = yaml_dir or RUNTIME_CONFIGS_DIR,
        cli_args    = cli_args,
        cli_exclude = cli_exclude,
        cli_mapping = cli_mapping,
    )

    sources_list: List[Tuple[Union[ConfigSource, str], Mapping[str, Any]]] = []
    if sources["yaml"]:
        sources_list.append((ConfigSource.YAML, sources["yaml"]))
    if extra_sources:
        sources_list.extend(extra_sources)
    if sources["cli"]:
        sources_list.append((ConfigSource.CLI, sources["cli"]))

    merger = ConfigMerger(track_sources=track_sources)
    if dry_run:
        merger.preview(YOLOInferConfig, sources=sources_list)
        return None, merger
    config = merger.merge(YOLOInferConfig, sources=sources_list)
    return config, merger


# ============================================================
# 公开 API 清单 (★ 唯一真相)
# ============================================================

__all__ = [
    # 配置类
    "BaseConfig",
    "YOLOTrainConfig",
    "YOLOValConfig",
    "YOLOInferConfig",          # ★ infer 闭环

    # 加载器
    "YAMLLoader",
    "CLILoader",
    "load_all_sources",

    # 合并器
    "ConfigMerger",
    "ConfigSource",
    "ConfigMetadata",

    # 生成器
    "ConfigGenerator",

    # 一键 build
    "build_train_config",
    "build_val_config",
    "build_infer_config",        # ★ infer 闭环
]
```

约 220 行——其中函数实现 120 行 (3 个 build_*), 其他都是 docstring 和 imports. **极简, 但表达清晰: 子系统对外有 14 个公开符号 (train/val/infer 三模式都齐了), 内部有几十个细节**.

## 7.4 测试: 公共 API 完整性

```python
import inspect
import odp_platform.runtime_config as rc

# ============================================================
# 1. __all__ 里的每个符号都能 import 到
# ============================================================
for name in rc.__all__:
    assert hasattr(rc, name), f"__all__ 声明了 {name} 但模块没有"
    obj = getattr(rc, name)
    assert obj is not None
assert len(rc.__all__) == 14, f"D5 公开 API 应为 14 个 (含 infer), 当前 {len(rc.__all__)}"
print(f"✓ __all__ 完整性: {len(rc.__all__)} 个符号 (含 infer 闭环)")

# 确认 infer 相关符号都在
assert "YOLOInferConfig" in rc.__all__
assert "build_infer_config" in rc.__all__
print("✓ infer 子系统公开 API 完整")

# ============================================================
# 2. 关键类的身份
# ============================================================
from odp_platform.runtime_config.train import YOLOTrainConfig as _TC
assert rc.YOLOTrainConfig is _TC, "__init__ 应该是 re-export, 不是 copy"

from odp_platform.runtime_config.merger import ConfigSource as _CS
assert rc.ConfigSource is _CS
print("✓ 公开符号是 re-export 而不是 copy")

# ============================================================
# 3. build_train_config 完整流水线
# ============================================================
from argparse  import Namespace
from pathlib   import Path
import tempfile

temp_dir = Path(tempfile.mkdtemp(prefix="odp_init_test_"))
yaml_file = temp_dir / "train.yaml"
yaml_file.write_text("""
model: yolo11n.pt
data: rsod.yaml
epochs: 200
lr0: 0.005
""", encoding="utf-8")

config, merger = rc.build_train_config(
    yaml_path=yaml_file.name,
    yaml_dir=temp_dir,
    cli_args=Namespace(epochs=300, batch=32),
)

# config 验证通过
assert isinstance(config, rc.YOLOTrainConfig)
assert config.epochs == 300              # CLI 覆盖
assert config.batch  == 32               # CLI
assert config.lr0    == 0.005            # YAML
assert config.model  == "yolo11n.pt"     # YAML

# merger 持有溯源
assert isinstance(merger, rc.ConfigMerger)
meta = merger.get_metadata("epochs")
assert meta is not None
assert meta.source == rc.ConfigSource.CLI
assert "300(CLI) ← 200(YAML) ← 100(DEFAULT)" == meta.chain_str()
print(f"✓ build_train_config 完整流水线: {meta.chain_str()}")

# 报告能跑
report = merger.get_source_report()
assert "CLI" in report and "YAML" in report
print("✓ merger 报告方法在")

# ============================================================
# 4. build_val_config 类似
# ============================================================
val_yaml = temp_dir / "val.yaml"
val_yaml.write_text("split: test\nconf: 0.5\n", encoding="utf-8")

val_config, val_merger = rc.build_val_config(
    yaml_path=val_yaml.name,
    yaml_dir=temp_dir,
    cli_args=Namespace(iou=0.7, model="best.pt", data="rsod.yaml"),
)
assert isinstance(val_config, rc.YOLOValConfig)
assert val_config.split == "test"
assert val_config.conf  == 0.5
assert val_config.iou   == 0.7
print(f"✓ build_val_config: split={val_config.split}, iou={val_config.iou}")

# ============================================================
# 5. yaml_path=None 跳过 YAML 加载
# ============================================================
config2, merger2 = rc.build_train_config(
    yaml_path=None,
    cli_args=Namespace(model="x.pt", data="y.yaml", epochs=50),
)
assert config2.epochs == 50
# 应该没有 YAML 来源
yaml_keys = [k for k, m in merger2._metadata.items() if m.source == rc.ConfigSource.YAML]
assert len(yaml_keys) == 0
print("✓ yaml_path=None 跳过 YAML 加载")

# ============================================================
# 6. 私有符号不在 __all__
# ============================================================
# 这些是内部实现, 不应该出现在公开 API
private_symbols = ["_drop_none", "_CONFIG_REGISTRY"]
for sym in private_symbols:
    assert sym not in rc.__all__, f"私有符号 {sym} 不应该在 __all__"
print(f"✓ 私有符号未泄漏到公开 API")

# ============================================================
# 7. 公开符号都有 docstring (★ API 必须自我文档化)
# ============================================================
no_doc = []
for name in rc.__all__:
    obj = getattr(rc, name)
    if not (inspect.getdoc(obj) or "").strip():
        no_doc.append(name)
assert not no_doc, f"以下公开符号缺 docstring: {no_doc}"
print(f"✓ 所有 {len(rc.__all__)} 个公开符号都有 docstring")

# 清理
import shutil
shutil.rmtree(temp_dir)

print("\n--- 阶段 7 测试通过 ---")
```

⚠️ **设计点 (测试 7 强制公开符号有 docstring)** **API 必须自我文档化**——`help(rc.build_train_config)` 跑出来如果是空, 用户就要查源码、查讲义、查 Slack. 把 "docstring 不为空" 列入测试, 让漏写 docstring 的 PR 直接挂掉. **测试不只测行为, 也能测纪律**.

## 7.5 git commit

```bash
git add apps/platform/src/odp_platform/runtime_config/__init__.py
git commit -m "feat(runtime_config): add public API in __init__.py

runtime_config/__init__.py:
  + Re-exports of 10 public symbols across base/train/val/loaders/
    merger/generator modules.
  + build_train_config() — 1-call pipeline:
      YAML load → CLI load → 3-source merge → Pydantic validation
      Returns (config, merger): caller gets both validated config and
      the source-tracking merger.
  + build_val_config()   — same for validation flow.
  + __all__ explicitly lists the 12 supported symbols.

Key design — what gets exported:
  Public:
    - Config classes: BaseConfig, YOLOTrainConfig, YOLOValConfig
    - Loaders:        YAMLLoader, CLILoader, load_all_sources
    - Merger:         ConfigMerger, ConfigSource, ConfigMetadata
    - Generator:      ConfigGenerator
    - Build helpers:  build_train_config, build_val_config
  Internal (NOT exported):
    - _drop_none, _CONFIG_REGISTRY — module-private utilities.
      Underscore prefix is the convention; not in __all__ means
      'subject to breaking changes without notice'.

  __all__ serves dual purpose:
    1. Controls 'from X import *' behavior
    2. Documents the supported public API surface for IDEs/Sphinx
    Anything not in __all__ is internal and may change anytime.

Key design — build_train_config / build_val_config are separate functions:
  Considered: build_config(mode='train'|'val', ...).
  Rejected because return type would be Union[YOLOTrainConfig, YOLOValConfig],
  forcing callers to assert isinstance for type narrowing.
  Two functions = two clean types = better callsite ergonomics.

  Returns tuple[config, merger] not just config:
  - D6 services need both — config for ultralytics call, merger for
    source reports and traceability logging.
  - Returning the merger costs nothing; constructing a new one to
    'just get the report' would re-run the entire pipeline.

  yaml_path defaults to 'train.yaml' / 'val.yaml':
  - 90% of calls are 'load default from default dir'
  - Explicit yaml_path=None for 'skip YAML, use CLI+DEFAULT only'
  - * forces yaml_dir/cli_exclude/cli_mapping as keyword-only args
    to prevent future positional-arg confusion.
"
```

**中文版**:

```bash
git commit -m "feat(runtime_config): 新增子系统对外公共 API 与一键 build 便捷函数" \
           -m "runtime_config/__init__.py:" \
           -m "  + __all__ —— 14 个公开符号 (子系统对外合同):" \
           -m "    配置类: BaseConfig, YOLOTrainConfig, YOLOValConfig, YOLOInferConfig" \
           -m "    加载器: YAMLLoader, CLILoader, load_all_sources" \
           -m "    合并器: ConfigMerger, ConfigSource, ConfigMetadata" \
           -m "    生成器: ConfigGenerator" \
           -m "    便捷函数: build_train_config, build_val_config, build_infer_config" \
           -m "  + build_train_config / build_val_config / build_infer_config:" \
           -m "    一键完成 YAML 加载 + CLI 加载 + 三源合并 + Pydantic 验证" \
           -m "    返回 (config, merger) tuple, 让 D6/D7/D8 service 一行调用就拿到一切" \
           -m "为什么把 build_* 做成三个函数而不是一个 build_config(mode):" \
           -m "  返回类型不同 (YOLOTrainConfig vs YOLOValConfig vs YOLOInferConfig)," \
           -m "  mode 参数会让返回类型变成 Union, service 层拿到要 isinstance 才能让 mypy 通过." \
           -m "  三个函数, 各自类型清晰." \
           -m "为什么把 _drop_none / _CONFIG_REGISTRY 不放进 __all__:" \
           -m "  Python 没有强制 private, 但 _ 前缀 + 不进 __all__ = 合同上的私有." \
           -m "  外界 import 这些符号自负风险, 我们保留改它们的自由." \
           -m "关键设计:" \
           -m "  - extra_sources 关键字让下游灵活插入 ENV/etcd/k8s 源" \
           -m "  - dry_run=True 返回 (None, merger), 调用方先看 source_report 再决定" \
           -m "  - 80% 场景一行解决, 20% 高级用法走关键字参数 —— 便捷函数的设计原则"
```


> **金句**: **"`__init__.py` 是子系统跟外界签的合同——明确公开什么、明确隐藏什么. 写好了, 上层调用一行 import 就跑; 写歪了, 内部细节满天飞, 想改的时候哪里都动不了."**

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 8: 单元测试——让 D5 进 CI

前面 7 个阶段每个都附了 REPL 测试. REPL 跑得通 ≠ 进 CI——REPL 是手动跑、人盯结果, CI 要的是 **机器跑、机器判断**. 阶段 8 把 REPL 测试 **规范化成 pytest 测试套件**, 进 CI, 每次 push 自动跑.

## 8.1 为什么 D5 就要写单元测试, 不留给 D6?

诱惑性的偷懒方案: "等 D6 service 层接进来, 跑通端到端就够了, 不用单元测试". 三个理由这么干会后悔:

### 理由 1: 端到端测试不能定位错误

D6 service 跑训练失败, 端到端只能告诉你 "model.train() 报错". 是 BaseConfig 字段验证错了? merger 链表写歪了? 还是 loader 把 None 加进去了? **端到端测试不告诉你错在哪一环**.

单元测试相反: `test_merger_chain` 红了就是 merger 链表的事, `test_yaml_loader_fail_fast` 红了就是 loader 报错信息的事. **测试粒度 = 错误粒度**.

### 理由 2: 重构时的安全网

D5 写完了, 没毛病. 三个月后突然要给 BaseConfig 加个新字段, 改 `model_config` 让它更严格——改完, **怎么知道没改坏什么**? 没单元测试就只能祈祷 D6 端到端能跑过.

有单元测试的话, `pytest tests/runtime_config/` 跑一遍, 60 个测试全绿——**心里有底**. 重构带来的不安, 是单元测试覆盖率换来的安心.

### 理由 3: 测试本身是文档

```python
def test_yaml_loader_fail_fast_with_repair_command(tmp_path):
    """文件不存在时, FileNotFoundError 消息必须含 'odp-gen-config' 修复命令"""
    loader = YAMLLoader()
    with pytest.raises(FileNotFoundError) as exc_info:
        loader.load(tmp_path / "not_exist.yaml")
    msg = str(exc_info.value)
    assert "odp-gen-config" in msg
```

这个测试用 14 行说清楚了 **"YAMLLoader 在文件不存在时的行为契约"** ——比写 14 行 docstring 还清楚, 因为测试 **能被执行**, 不会跟代码漂移.

> **金句**: **"单元测试不是 '写完代码后加的负担', 是 '让代码可改、可读、可推理' 的基础设施. 不写测试, 三个月后你自己都不敢动这份代码."**

⚠️ **设计点 (D5 测试覆盖什么, 不覆盖什么)** D5 测试 **不覆盖 ultralytics 的实际行为**——`model.train()` 真跑起来有没有问题, 留给 D6. D5 只测 "**配置层的契约**" ——字段验证、加载、合并、溯源、生成. **测试范围 = 模块的责任范围**, 跨边界的事归边界外测.

## 8.2 测试目录结构

```
apps/platform/tests/
├── runtime_config/
│   ├── __init__.py
│   ├── conftest.py          ← 共享 fixture
│   ├── test_base.py         ← BaseConfig 行为
│   ├── test_train_val.py    ← YOLOTrainConfig + YOLOValConfig
│   ├── test_infer.py        ← YOLOInferConfig (★ infer 闭环)
│   ├── test_loaders.py      ← YAMLLoader + CLILoader
│   ├── test_merger.py       ← ConfigMerger + 溯源
│   ├── test_generator.py    ← ConfigGenerator
│   └── test_public_api.py   ← __init__.py 完整性 + build_* 流水线
```

8 个文件, 大致 100+ 测试用例. 跟 7 个模块的对应关系一目了然.

⚠️ **设计点 (test 文件按模块拆, 不按"功能"拆)** 备选方案: `test_validation.py`(测所有跨模块的字段验证)、`test_yaml.py`(测所有跟 yaml 相关的)... 这种 "按功能" 拆法的问题是 **跟代码结构对不上**——改一个模块要去多个测试文件里找相关测试. 按模块拆, **改 `merger.py` 时一定看 `test_merger.py`**, 文件名指向直接.

## 8.3 `conftest.py`: 共享 fixture

`tests/runtime_config/conftest.py`:

```python
"""runtime_config 测试共享 fixture."""
from __future__ import annotations

from pathlib import Path
from typing  import Callable

import pytest


@pytest.fixture
def write_yaml(tmp_path: Path) -> Callable[..., Path]:
    """生成临时 yaml 文件.

    用法:
        def test_xxx(write_yaml):
            f = write_yaml("epochs: 100\\nbatch: 16", name="train.yaml")
            ...
    """
    def _make(content: str, name: str = "test.yaml") -> Path:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path
    return _make


@pytest.fixture
def yaml_dir(tmp_path: Path) -> Path:
    """提供一个空的 yaml 目录."""
    d = tmp_path / "configs"
    d.mkdir()
    return d


@pytest.fixture
def minimal_train_yaml(write_yaml) -> Path:
    """一份最小的 train yaml — 测合并 / 加载场景常用."""
    return write_yaml("""
model: yolo11n.pt
data: rsod.yaml
epochs: 200
batch: 32
lr0: 0.005
""", name="train.yaml")
```

⚠️ **设计点 (`tmp_path` 是 pytest 内置 fixture)** pytest 提供 `tmp_path` 自动创建临时目录, 每个测试用例独立, 测完自动清. **不要用 `tempfile.mkdtemp`** 自己管理——容易忘清理, 测试间还可能串扰. 善用 pytest 内置 fixture.

⚠️ **设计点 (`write_yaml` 返回一个函数而不是 path)** Fixture 返回函数(俗称 "factory fixture")让单个测试可以多次调用——一个测试想准备 3 个 yaml 文件? 在测试内 `write_yaml(...)` 调 3 次. 比 fixture 返回单个 path 灵活得多.

## 8.4 `test_base.py`: BaseConfig 行为

```python
"""BaseConfig 行为契约测试."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from odp_platform.runtime_config.base import BaseConfig


# ============================================================
# 不能直接实例化 BaseConfig (抽象基类语义)
# ============================================================

class _ConcreteTestConfig(BaseConfig):
    """测试用最小子类."""
    pass


def test_base_config_default_values():
    """BaseConfig 子类默认值应正确."""
    c = _ConcreteTestConfig()
    assert c.batch     == 16
    assert c.imgsz     == 640
    assert c.workers   == 8
    assert c.cache     is False
    assert c.device    is None
    assert c.amp       is True
    assert c.verbose   is True


def test_base_config_extra_forbid():
    """extra='forbid' 拒绝拼错的字段名."""
    with pytest.raises(ValidationError) as exc_info:
        _ConcreteTestConfig(epchs=300)         # epochs 拼错
    assert "epchs" in str(exc_info.value)


def test_base_config_framework_only_fields_default():
    """BaseConfig 默认 FRAMEWORK_ONLY_FIELDS 只有 verbose."""
    assert BaseConfig.FRAMEWORK_ONLY_FIELDS == {"verbose"}


def test_to_ultralytics_kwargs_drops_framework_fields():
    """to_ultralytics_kwargs 过滤 FRAMEWORK_ONLY_FIELDS."""
    c = _ConcreteTestConfig(verbose=False)
    kw = c.to_ultralytics_kwargs()
    assert "verbose" not in kw, "verbose 不应该传给 ultralytics"


def test_to_ultralytics_kwargs_drops_none():
    """to_ultralytics_kwargs 过滤 None 值."""
    c = _ConcreteTestConfig()
    kw = c.to_ultralytics_kwargs()
    assert "device" not in kw, "默认 None 的字段不应该出现"


def test_to_ultralytics_kwargs_keeps_false_and_zero():
    """to_ultralytics_kwargs 必须保留 False / 0 / '' 等显式值."""
    c = _ConcreteTestConfig(cache=False, amp=False)
    kw = c.to_ultralytics_kwargs()
    assert kw["cache"] is False
    assert kw["amp"]   is False


def test_get_field_groups():
    """get_field_groups 返回有序的分组字典."""
    c = _ConcreteTestConfig()
    groups = c.get_field_groups()
    # 至少 BaseConfig 自己的 4 个组在
    expected = {"核心参数", "输入配置", "设备配置", "输出配置", "基础设置"}
    assert expected <= set(groups.keys())


def test_get_field_metadata_complete():
    """每个字段都有完整的 group/examples/tips/yaml_comment 4 个槽位."""
    c = _ConcreteTestConfig()
    for field_name in c.model_fields:
        metadata = c.get_field_metadata(field_name)
        # description 必填
        assert metadata.get("description"), f"{field_name} 缺 description"
        # 至少有一个用户向元数据(说明 SSoT 思路落到位)
        has_user_meta = any([
            metadata.get("group"),
            metadata.get("examples"),
            metadata.get("yaml_comment"),
        ])
        assert has_user_meta, f"{field_name} 缺用户向元数据"
```

⚠️ **设计点 (`_ConcreteTestConfig` 这种内部类)** 不能直接测 `BaseConfig`(它的字段在外界没意义), 又不想用 `YOLOTrainConfig`(会引入 train.py 的耦合). 写一个最小的子类 `_ConcreteTestConfig`, 跟测试同文件——**只为测 BaseConfig 自己的行为**, 跟生产代码完全无关.

⚠️ **设计点 (`test_get_field_metadata_complete` 用 for 遍历所有字段)** 这种 "对每个字段跑同一个断言" 的测试比 "手写每个字段的测试" 更鲁棒——加新字段时自动覆盖. 但缺点是失败时报 "某个字段缺元数据", 不会精确告诉是哪个. 折中: 写两类测试, 一类遍历(覆盖完整性), 一类精确(覆盖关键字段).

### 8.4.x BaseConfig 扩展性接口

`test_base.py` 末尾追加 audit_snapshot / mask_sensitive_dump 的测试 (在内部 fixture 类上跑, 不污染真实 train/val):

```python
class _SensitiveTestConfig(BaseConfig):
    """用于测试 sensitive 字段处理的最小内部 fixture."""
    api_key: Optional[str] = Field(
        default=None,
        description="API 密钥示例 (测试用)",
        json_schema_extra={"group": "核心参数", "sensitive": True},
    )
    public_param: int = Field(
        default=10,
        description="普通参数 (测试用)",
        json_schema_extra={"group": "核心参数", "sensitive": False},
    )


# ============================================================
# 实验复现 audit_snapshot
# ============================================================

def test_audit_snapshot_roundtrip():
    """to_audit_snapshot → from_audit_snapshot 应完全恢复."""
    config = _ConcreteTestConfig(value=42, name="hello")
    snapshot = config.to_audit_snapshot()

    assert snapshot["config_class"]  == "_ConcreteTestConfig"
    assert snapshot["config_module"] == _ConcreteTestConfig.__module__
    assert "frozen_at" in snapshot
    assert snapshot["values"]["value"] == 42

    restored = _ConcreteTestConfig.from_audit_snapshot(snapshot)
    assert restored.value == 42
    assert restored.name == "hello"


def test_audit_snapshot_wrong_class_raises():
    """用错类恢复快照应报错."""
    config = _ConcreteTestConfig(value=1)
    snapshot = config.to_audit_snapshot()

    with pytest.raises(ValueError, match="不能恢复"):
        _SensitiveTestConfig.from_audit_snapshot(snapshot)


def test_audit_snapshot_json_serializable():
    """快照必须可 json.dumps (实验数据库通常 JSON 列存)."""
    import json
    config = _ConcreteTestConfig(value=42)
    snapshot = config.to_audit_snapshot()
    text = json.dumps(snapshot, ensure_ascii=False)
    restored = json.loads(text)
    assert restored["values"]["value"] == 42


# ============================================================
# 敏感字段 mask
# ============================================================

def test_mask_sensitive_dump_masks_marked_fields():
    c = _SensitiveTestConfig(api_key="super_secret_123", public_param=42)
    masked = c.mask_sensitive_dump()
    assert masked["api_key"] == "***"
    assert masked["public_param"] == 42         # 没标 sensitive 不动


def test_mask_sensitive_dump_keeps_none():
    """None 值的 sensitive 字段不应 mask 成 '***'."""
    c = _SensitiveTestConfig(api_key=None)
    masked = c.mask_sensitive_dump()
    assert masked["api_key"] is None


def test_sensitive_field_names_reflects_correctly():
    assert _SensitiveTestConfig.sensitive_field_names() == {"api_key"}


def test_custom_sensitive_mask_via_classvar():
    """子类改 SENSITIVE_MASK 应生效."""
    class _RedactedConfig(_SensitiveTestConfig):
        SENSITIVE_MASK: ClassVar[str] = "<REDACTED>"

    c = _RedactedConfig(api_key="x")
    assert c.mask_sensitive_dump()["api_key"] == "<REDACTED>"
```

⚠️ **设计点 (`_SensitiveTestConfig` 也是 fixture 内部类)** 跟 `_ConcreteTestConfig` 同款——只为测 sensitive 机制, 不引入真实 train/val 字段污染. 真实生产配置如果将来真要标 sensitive, 测试就在那时加.

## 8.5 `test_train_val.py`: 子类配置

```python
"""YOLOTrainConfig + YOLOValConfig 行为契约."""
from __future__ import annotations

import warnings
import pytest
from pydantic import ValidationError

from odp_platform.common.constants     import Task
from odp_platform.runtime_config.train import YOLOTrainConfig
from odp_platform.runtime_config.val   import YOLOValConfig


# ============================================================
# task / experiment_name 拆分 (★ 撞墙②的核心)
# ============================================================

class TestTaskExperimentNameSplit:
    """task = SSoT 语义; experiment_name = 实验标识 — 必须正交."""

    def test_task_defaults_to_detect(self):
        assert YOLOTrainConfig().task == Task.DETECT
        assert YOLOValConfig().task   == Task.DETECT

    @pytest.mark.parametrize("invalid_task", [
        "detect_v2",         # legacy 把任务名塞进 task 的典型
        "Detection",         # 大小写错
        "DETECT",            # 全大写
        "detect_baseline",   # 想拼实验名进去
        "",                  # 空串
        "pose",              # 不在 Task.all() 里
    ])
    def test_train_task_rejects_invalid(self, invalid_task):
        with pytest.raises(ValidationError) as exc_info:
            YOLOTrainConfig(task=invalid_task)
        msg = str(exc_info.value)
        # ★ 错误信息必须指引 → experiment_name
        assert "experiment_name" in msg, \
            f"task 报错应指引用 experiment_name; 实际: {msg}"

    @pytest.mark.parametrize("invalid_task", [
        "detect_v2", "Detection", "segmentation",
    ])
    def test_val_task_rejects_invalid(self, invalid_task):
        with pytest.raises(ValidationError):
            YOLOValConfig(task=invalid_task)

    @pytest.mark.parametrize("name", [
        "baseline", "helmet_v1", "lr001_aug_strong",
        "exp-2024-05", "model_v3.1",
    ])
    def test_experiment_name_accepts_free_string(self, name):
        c = YOLOTrainConfig(experiment_name=name)
        assert c.experiment_name == name

    def test_experiment_name_can_be_none(self):
        c = YOLOTrainConfig()
        assert c.experiment_name is None


# ============================================================
# FRAMEWORK_ONLY_FIELDS 在 train vs val 不同
# ============================================================

class TestFrameworkOnlyFields:
    """train 的 task 传给 ultralytics; val 的 task 不传."""

    def test_train_passes_task_to_ultralytics(self):
        c = YOLOTrainConfig(task="detect", experiment_name="exp1")
        kw = c.to_ultralytics_kwargs()
        assert "task" in kw, "train.task 必须传给 ultralytics"
        assert kw["task"] == "detect"
        assert "experiment_name" not in kw, "experiment_name 不传"

    def test_val_does_not_pass_task(self):
        c = YOLOValConfig(task="detect", experiment_name="vexp")
        kw = c.to_ultralytics_kwargs()
        assert "task" not in kw, \
            "val.task 不传给 ultralytics (model.val() 从权重推断)"
        assert "experiment_name" not in kw


# ============================================================
# 跨字段验证
# ============================================================

class TestCrossFieldValidation:
    def test_save_false_with_save_period_raises(self):
        """save=False + save_period>0 矛盾, 必须 raise."""
        with pytest.raises(ValidationError) as exc_info:
            YOLOTrainConfig(save=False, save_period=10)
        assert "save_period" in str(exc_info.value)

    def test_mosaic_zero_with_close_mosaic_warns(self):
        """mosaic=0 + close_mosaic>0 冗余, 应该 warn 不 raise."""
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            YOLOTrainConfig(mosaic=0.0, close_mosaic=10)
            assert any(
                "close_mosaic 将不会生效" in str(w.message)
                for w in ws
            ), "应该触发 close_mosaic 不生效警告"

    def test_save_false_and_save_period_minus_one_ok(self):
        """save=False + save_period=-1 一致, 应该通过."""
        c = YOLOTrainConfig(save=False, save_period=-1)
        assert c.save is False and c.save_period == -1


# ============================================================
# val 特有字段
# ============================================================

class TestValSpecific:
    def test_split_default(self):
        assert YOLOValConfig().split == "val"

    @pytest.mark.parametrize("invalid", ["testing", "VAL", "validate", ""])
    def test_split_rejects_invalid(self, invalid):
        with pytest.raises(ValidationError):
            YOLOValConfig(split=invalid)

    @pytest.mark.parametrize("valid", ["train", "val", "test"])
    def test_split_accepts_valid(self, valid):
        c = YOLOValConfig(split=valid)
        assert c.split == valid

    def test_conf_default_low_for_mAP(self):
        """验证模式 conf 默认 0.001 (差推理两个数量级)."""
        assert YOLOValConfig().conf == 0.001


# ============================================================
# extra='forbid' 从 BaseConfig 继承到子类
# ============================================================

def test_train_extra_forbid_inherited():
    with pytest.raises(ValidationError):
        YOLOTrainConfig(epchs=300)        # 拼错

def test_val_extra_forbid_inherited():
    with pytest.raises(ValidationError):
        YOLOValConfig(spilt="val")        # 拼错


# ============================================================
# 完整字段分组
# ============================================================

EXPECTED_TRAIN_GROUPS = {
    "核心参数", "输入配置", "设备配置", "输出配置", "基础设置",
    "训练控制", "优化器配置", "学习率预热", "损失权重",
    "数据增强-颜色", "数据增强-几何", "数据增强-拼接",
    "验证和输出", "任务特定", "高级设置",
}

def test_train_field_groups_complete():
    groups = set(YOLOTrainConfig().get_field_groups().keys())
    missing = EXPECTED_TRAIN_GROUPS - groups
    assert not missing, f"train 缺分组: {missing}"
```

⚠️ **设计点 (用 `class TestXxx` 把相关测试分组)** pytest 自动发现 `Test` 开头的 class. 用 class 分组让 `pytest -v` 输出有层级:
```
test_train_val.py::TestTaskExperimentNameSplit::test_task_defaults_to_detect    PASSED
test_train_val.py::TestTaskExperimentNameSplit::test_train_task_rejects_invalid PASSED
```
比一坨平级函数更易扫描. 但 class 里 **不要写 `setUp/tearDown`**——用 fixture 替代, 更 pytest-y.

⚠️ **设计点 (`@pytest.mark.parametrize` 把 6 个 case 合并)** 反例: 写 6 个 `def test_task_rejects_detect_v2(...)`, `def test_task_rejects_DETECTION(...)`. parametrize 让 6 个 case 复用同一个函数体, 失败时 pytest 输出告诉你具体哪个参数失败. **测试代码也讲 DRY**.

### 8.5.x val segment 字段跨字段守卫

```python
# === val: segment 专属字段在 detect 任务下应警告 ===
@pytest.mark.parametrize("mask_ratio,overlap_mask,should_warn", [
    (4, True,  False),     # 全默认, 不警告
    (2, True,  True),      # mask_ratio 偏离, 警告
    (4, False, True),      # overlap_mask 偏离, 警告
    (2, False, True),      # 两个都偏离, 合并成一条警告
])
def test_val_segment_only_fields_warn_on_detect(mask_ratio, overlap_mask, should_warn):
    """detect 任务下改 segment 专属字段应触发 UserWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        YOLOValConfig(
            task=Task.DETECT,
            mask_ratio=mask_ratio,
            overlap_mask=overlap_mask,
        )

    seg_warnings = [w for w in caught if "segment 任务有效" in str(w.message)]
    if should_warn:
        assert len(seg_warnings) == 1, "应该正好一条合并警告"
    else:
        assert not seg_warnings


def test_val_segment_task_no_warn():
    """segment 任务下改 segment 字段不应警告."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        YOLOValConfig(
            task=Task.SEGMENT,
            mask_ratio=2,
            overlap_mask=False,
        )
    assert not [w for w in caught if "segment 任务有效" in str(w.message)]
```

⚠️ **设计点 (4 个 parametrize case 覆盖 segment 守卫完整真值表)**: 两个 segment 专属字段, 每个有"默认"和"偏离"两种状态——2 × 2 = 4 个组合. parametrize 一次列全, 后续真有人改守卫规则, 4 行 case 比 4 个独立函数维护轻得多.

## 8.5.5 `test_infer.py`: 推理子类配置 (★ D5 推理闭环)

```python
"""YOLOInferConfig 行为契约."""
from __future__ import annotations

import warnings
import pytest
from pydantic import ValidationError

from odp_platform.common.constants     import Task
from odp_platform.runtime_config.infer import YOLOInferConfig


# ============================================================
# source 字段行为
# ============================================================

class TestInferSource:
    """source — 推理特有, 跟 train/val 的 data 字段并列"""

    def test_source_default_none(self):
        assert YOLOInferConfig().source is None

    def test_source_str(self):
        c = YOLOInferConfig(source="image.jpg")
        assert c.source == "image.jpg"

    def test_source_int_camera_index(self):
        """摄像头索引 int 应标准化为 str."""
        c = YOLOInferConfig(source=0)
        assert c.source == "0"

    def test_source_rejects_invalid_type(self):
        with pytest.raises((ValidationError, TypeError)):
            YOLOInferConfig(source=[1, 2, 3])

    def test_source_in_ultralytics_kwargs(self):
        """source 必须传给 ultralytics."""
        c = YOLOInferConfig(source="x.jpg")
        kw = c.to_ultralytics_kwargs()
        assert kw.get("source") == "x.jpg"


# ============================================================
# conf 默认值与 val 不同 (语义差异)
# ============================================================

def test_infer_conf_default_differs_from_val():
    """infer 默认 conf=0.25, 不同于 val 的 0.001."""
    assert YOLOInferConfig().conf == 0.25


def test_infer_conf_range():
    """conf 必须在 [0, 1] 范围."""
    with pytest.raises(ValidationError):
        YOLOInferConfig(conf=1.5)
    with pytest.raises(ValidationError):
        YOLOInferConfig(conf=-0.1)


# ============================================================
# FRAMEWORK_ONLY_FIELDS 同 val
# ============================================================

def test_framework_only_fields_match_val():
    assert YOLOInferConfig.FRAMEWORK_ONLY_FIELDS == (
        {"verbose", "experiment_name", "task"}
    )


def test_task_not_in_ultralytics_kwargs():
    c = YOLOInferConfig(source="x.jpg", task=Task.DETECT)
    kw = c.to_ultralytics_kwargs()
    assert "task" not in kw
    assert "experiment_name" not in kw


# ============================================================
# task SSoT (跟 train/val 同款规则)
# ============================================================

@pytest.mark.parametrize("invalid_task", [
    "detect_v2",
    "Detection",
    "predict",       # 推理时容易写的错值, 但还是要拒
    "infer",         # 同上
])
def test_infer_task_rejects_invalid(invalid_task):
    with pytest.raises(ValidationError) as exc_info:
        YOLOInferConfig(task=invalid_task)
    # 错误信息必须指引 experiment_name 字段
    assert "experiment_name" in str(exc_info.value)


# ============================================================
# 跨字段警告 (4 个场景全 warn 不 raise)
# ============================================================

class TestInferCrossFieldWarnings:
    def test_save_conf_without_save_txt_warns(self):
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            YOLOInferConfig(save_conf=True, save_txt=False)
            assert any(
                "save_conf=True 但 save_txt=False" in str(w.message)
                for w in ws
            )

    def test_save_conf_with_save_txt_silent(self):
        """save_conf=True 且 save_txt=True 不应该警告."""
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            YOLOInferConfig(save_conf=True, save_txt=True)
            assert not any(
                "save_conf=True 但 save_txt=False" in str(w.message)
                for w in ws
            )

    def test_stream_buffer_without_stream_warns(self):
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            YOLOInferConfig(stream_buffer=True, stream=False)
            assert any(
                "stream_buffer=True 但 stream=False" in str(w.message)
                for w in ws
            )

    def test_retina_masks_in_detect_task_warns(self):
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            YOLOInferConfig(retina_masks=True, task=Task.DETECT)
            assert any(
                "retina_masks=True 仅对 segment" in str(w.message)
                for w in ws
            )

    def test_retina_masks_in_segment_task_silent(self):
        """segment 任务下 retina_masks=True 不应该警告."""
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            YOLOInferConfig(retina_masks=True, task=Task.SEGMENT)
            assert not any(
                "retina_masks=True 仅对 segment" in str(w.message)
                for w in ws
            )


# ============================================================
# 字段分组 (★ 反射出 yaml 模板的基础)
# ============================================================

def test_infer_field_groups():
    """infer 字段分组完整."""
    c = YOLOInferConfig()
    groups = c.get_field_groups()
    expected = {
        "核心参数", "推理控制", "视频流", "输出控制", "任务特定",
        # BaseConfig 继承的组
        "输入配置", "设备配置", "输出配置", "基础设置",
    }
    assert expected <= set(groups.keys()), \
        f"缺失分组: {expected - set(groups.keys())}"


# ============================================================
# audit_snapshot 也得支持 (实验复现关键)
# ============================================================

def test_infer_audit_snapshot_roundtrip():
    c = YOLOInferConfig(source="video.mp4", conf=0.5)
    snapshot = c.to_audit_snapshot()
    assert snapshot["config_class"] == "YOLOInferConfig"
    restored = YOLOInferConfig.from_audit_snapshot(snapshot)
    assert restored.source == "video.mp4"
    assert restored.conf == 0.5
```

⚠️ **设计点 (test_infer 比 test_train_val 更简洁)**: infer 比 train 少了 52 个特有字段, 跨字段验证只有 3 个 warn (vs train 的 raise + warn 混合). 测试规模相对小, 不需要单独的"task 拆分专题"测试类——直接参数化几个非法 task 值断言一遍就够.

> **金句**: **"测试规模 = 字段集复杂度. infer 简单, 测试也简单——不为了'跟 train/val 测试条数一样'强行多写."**

## 8.6 `test_loaders.py`: YAMLLoader + CLILoader

```python
"""YAMLLoader + CLILoader + _drop_none 行为契约."""
from __future__ import annotations

from argparse import Namespace
from pathlib  import Path

import pytest

from odp_platform.runtime_config.loaders import (
    YAMLLoader, CLILoader, load_all_sources, _drop_none,
)


# ============================================================
# _drop_none — 经典 falsy 坑测试
# ============================================================

class TestDropNone:
    def test_drops_none(self):
        result = _drop_none({"a": None, "b": 1})
        assert result == {"b": 1}

    def test_keeps_false(self):
        """★ 经典坑: 不能写成 `if v`, 那样会过滤 False."""
        result = _drop_none({"flag": False})
        assert result == {"flag": False}

    def test_keeps_zero(self):
        result = _drop_none({"count": 0, "ratio": 0.0})
        assert result == {"count": 0, "ratio": 0.0}

    def test_keeps_empty_string(self):
        result = _drop_none({"name": ""})
        assert result == {"name": ""}

    def test_keeps_empty_list(self):
        result = _drop_none({"items": []})
        assert result == {"items": []}


# ============================================================
# YAMLLoader 正常路径
# ============================================================

class TestYAMLLoaderHappy:
    def test_load_normal_yaml(self, minimal_train_yaml):
        loader = YAMLLoader()
        cfg = loader.load(minimal_train_yaml)
        assert cfg["epochs"]  == 200
        assert cfg["batch"]   == 32
        assert cfg["lr0"]     == 0.005
        assert cfg["model"]   == "yolo11n.pt"

    def test_load_empty_file_returns_dict(self, write_yaml):
        loader = YAMLLoader()
        f = write_yaml("", name="empty.yaml")
        assert loader.load(f) == {}

    def test_load_all_comments_returns_dict(self, write_yaml):
        loader = YAMLLoader()
        f = write_yaml("# only comment\n# nothing else\n", name="comments.yaml")
        assert loader.load(f) == {}

    def test_load_filters_yaml_null(self, write_yaml):
        """yaml 的 null → 过滤; false / 0 → 保留."""
        f = write_yaml(
            "device: null\namp: false\nfraction: 0.0\n",
            name="null.yaml",
        )
        cfg = YAMLLoader().load(f)
        assert "device" not in cfg
        assert cfg["amp"] is False
        assert cfg["fraction"] == 0.0


# ============================================================
# YAMLLoader fail-fast 路径 — ★ 撞墙③
# ============================================================

class TestYAMLLoaderFailFast:
    def test_file_not_exists_raises_with_repair_command(self, tmp_path):
        """文件不存在 → FileNotFoundError + 'odp-gen-config' 修复指引."""
        loader = YAMLLoader()
        target = tmp_path / "not_exist.yaml"
        with pytest.raises(FileNotFoundError) as exc_info:
            loader.load(target)
        msg = str(exc_info.value)
        assert "请先生成默认配置模板" in msg
        assert "odp-gen-config" in msg
        assert "not_exist" in msg, "修复指引应含模板名"

    def test_yaml_format_error(self, write_yaml):
        """yaml 格式错误 → ValueError, 含原始错误链."""
        f = write_yaml("epochs: 100\n\tbatch: 16\n", name="bad.yaml")
        loader = YAMLLoader()
        with pytest.raises(ValueError) as exc_info:
            loader.load(f)
        msg = str(exc_info.value)
        assert "YAML 格式错误" in msg
        assert "检查缩进" in msg
        assert exc_info.value.__cause__ is not None, "应保留 exception chain"

    def test_top_level_not_dict(self, write_yaml):
        f = write_yaml("- 1\n- 2\n- 3\n", name="list.yaml")
        with pytest.raises(ValueError) as exc_info:
            YAMLLoader().load(f)
        assert "顶层必须是字典" in str(exc_info.value)


# ============================================================
# YAMLLoader 路径解析
# ============================================================

class TestYAMLLoaderPathResolution:
    def test_absolute_path_ignores_config_dir(self, write_yaml, tmp_path):
        """绝对路径无视 config_dir."""
        f = write_yaml("epochs: 50", name="train.yaml")
        loader = YAMLLoader(config_dir="/should/be/ignored")
        assert loader._resolve_path(f).resolve() == f.resolve()

    def test_relative_path_uses_config_dir(self, write_yaml, tmp_path):
        f = write_yaml("epochs: 50", name="train.yaml")
        loader = YAMLLoader(config_dir=tmp_path)
        cfg = loader.load("train.yaml")     # 文件名 → 从 tmp_path 找
        assert cfg["epochs"] == 50

    def test_no_config_dir_uses_cwd(self, tmp_path, monkeypatch):
        """没有 config_dir → 基于当前目录."""
        f = tmp_path / "x.yaml"
        f.write_text("epochs: 7", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        loader = YAMLLoader()
        cfg = loader.load("x.yaml")
        assert cfg["epochs"] == 7


# ============================================================
# CLILoader
# ============================================================

class TestCLILoader:
    def test_namespace_basic(self):
        args = Namespace(model="x.pt", epochs=200, batch=32)
        cfg = CLILoader().load(args)
        assert cfg == {"model": "x.pt", "epochs": 200, "batch": 32}

    def test_default_excludes_control_fields(self):
        args = Namespace(
            model="x.pt", epochs=10,
            help=False, config="train.yaml",
            cfg="abc", yaml_path="def",
            debug=True, version="1.0",
        )
        cfg = CLILoader().load(args)
        for control_field in ["help", "config", "cfg", "yaml_path", "debug", "version"]:
            assert control_field not in cfg, f"{control_field} 应被默认排除"
        assert cfg == {"model": "x.pt", "epochs": 10}

    def test_excludes_private_fields(self):
        args = Namespace(model="x.pt", _internal="hide", _debug=True)
        cfg = CLILoader().load(args)
        assert cfg == {"model": "x.pt"}

    def test_filter_none_default(self):
        args = Namespace(model="x.pt", lr0=None, batch=16)
        cfg = CLILoader().load(args)
        assert "lr0" not in cfg
        assert cfg["batch"] == 16

    def test_filter_none_disabled(self):
        args = Namespace(model="x.pt", device=None)
        cfg = CLILoader().load(args, filter_none=False)
        assert "device" in cfg and cfg["device"] is None

    def test_custom_exclude(self):
        args = Namespace(model="x.pt", my_flag=True)
        cfg = CLILoader(exclude=["my_flag"]).load(args)
        assert "my_flag" not in cfg

    def test_name_mapping(self):
        """CLI 名 (learning_rate) → Pydantic 字段名 (lr0)."""
        args = Namespace(learning_rate=0.001, model="x.pt")
        cfg = CLILoader(mapping={"learning_rate": "lr0"}).load(args)
        assert cfg == {"lr0": 0.001, "model": "x.pt"}

    def test_args_none_returns_empty(self):
        assert CLILoader().load(None) == {}

    def test_dict_input(self):
        cfg = CLILoader().load({"epochs": 50})
        assert cfg == {"epochs": 50}

    def test_wrong_type_raises(self):
        with pytest.raises(TypeError):
            CLILoader().load("not a Namespace")


# ============================================================
# load_all_sources
# ============================================================

class TestLoadAllSources:
    def test_loads_both_sources(self, minimal_train_yaml):
        sources = load_all_sources(
            yaml_path=minimal_train_yaml.name,
            yaml_dir=minimal_train_yaml.parent,
            cli_args=Namespace(epochs=999, batch=64),
        )
        assert sources["yaml"]["epochs"] == 200
        assert sources["cli"]["epochs"]  == 999

    def test_no_yaml_path_skips_yaml(self):
        sources = load_all_sources(
            yaml_path=None,
            cli_args=Namespace(epochs=10),
        )
        assert sources["yaml"] == {}
        assert sources["cli"]["epochs"] == 10
```

## 8.7 `test_merger.py`: 链表溯源核心

```python
"""ConfigMerger + ConfigMetadata 链表溯源."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from odp_platform.runtime_config.train  import YOLOTrainConfig
from odp_platform.runtime_config.merger import (
    ConfigMerger, ConfigSource, ConfigMetadata,
)


# ============================================================
# 优先级: CLI > YAML > DEFAULT
# ============================================================

class TestPriority:
    def test_cli_overrides_yaml(self):
        m = ConfigMerger()
        c = m.merge(YOLOTrainConfig, sources=[
            (ConfigSource.YAML, {"epochs": 200}),
            (ConfigSource.CLI,  {"epochs": 300}),
        ])
        assert c.epochs == 300

    def test_yaml_overrides_default(self):
        m = ConfigMerger()
        c = m.merge(YOLOTrainConfig, sources=[(ConfigSource.YAML, {"epochs": 50})])
        assert c.epochs == 50

    def test_default_falls_through(self):
        m = ConfigMerger()
        c = m.merge(YOLOTrainConfig)
        assert c.epochs == 100       # BaseConfig default

    def test_partial_overrides(self):
        m = ConfigMerger()
        c = m.merge(YOLOTrainConfig, sources=[
            (ConfigSource.YAML, {"epochs": 200, "batch": 32, "lr0": 0.005}),
            (ConfigSource.CLI,  {"epochs": 300}),
        ])
        assert c.epochs == 300        # CLI
        assert c.batch  == 32         # YAML
        assert c.lr0    == 0.005      # YAML
        assert c.workers == 8         # DEFAULT


# ============================================================
# 链表溯源
# ============================================================

class TestChain:
    def test_three_layer_chain(self):
        m = ConfigMerger()
        m.merge(YOLOTrainConfig, sources=[
            (ConfigSource.YAML, {"epochs": 200}),
            (ConfigSource.CLI,  {"epochs": 300}),
        ])
        meta = m.get_metadata("epochs")
        chain = meta.chain()
        assert len(chain) == 3, "3 层链: CLI ← YAML ← DEFAULT"
        # 顺序: 当前 → 上一版 → 上上版
        assert chain[0].value == 300 and chain[0].source == ConfigSource.CLI
        assert chain[1].value == 200 and chain[1].source == ConfigSource.YAML
        assert chain[2].value == 100 and chain[2].source == ConfigSource.DEFAULT

    def test_two_layer_chain(self):
        m = ConfigMerger()
        m.merge(YOLOTrainConfig, sources=[(ConfigSource.YAML, {"epochs": 200})])
        chain = m.get_metadata("epochs").chain()
        assert len(chain) == 2
        assert chain[0].source == ConfigSource.YAML
        assert chain[1].source == ConfigSource.DEFAULT

    def test_one_layer_chain_for_untouched_default(self):
        m = ConfigMerger()
        m.merge(YOLOTrainConfig)
        chain = m.get_metadata("epochs").chain()
        assert len(chain) == 1
        assert chain[0].source == ConfigSource.DEFAULT

    def test_chain_str_format(self):
        m = ConfigMerger()
        m.merge(YOLOTrainConfig, sources=[
            (ConfigSource.YAML, {"lr0": 0.005}),
            (ConfigSource.CLI,  {"lr0": 0.001}),
        ])
        meta = m.get_metadata("lr0")
        assert meta.chain_str() == "0.001(CLI) ← 0.005(YAML) ← 0.01(DEFAULT)"


# ============================================================
# 报告
# ============================================================

class TestReports:
    def test_source_report_groups_by_source(self):
        m = ConfigMerger()
        m.merge(YOLOTrainConfig, sources=[
            (ConfigSource.YAML, {"epochs": 200, "batch": 32}),
            (ConfigSource.CLI,  {"lr0": 0.001}),
        ])
        report = m.get_source_report()
        assert "CLI (1 项)"  in report
        assert "YAML (2 项)" in report
        assert "DEFAULT"     in report

    def test_conflict_report_shows_full_chain(self):
        m = ConfigMerger()
        m.merge(YOLOTrainConfig, sources=[
            (ConfigSource.YAML, {"epochs": 200, "lr0": 0.005}),
            (ConfigSource.CLI,  {"epochs": 300}),
        ])
        report = m.get_conflict_report()
        # epochs 完整链: 100 → 200 → 300
        assert "100 (DEFAULT) → 200 (YAML) → 300 (CLI)" in report
        # lr0 链: 0.01 → 0.005
        assert "0.01 (DEFAULT) → 0.005 (YAML)" in report


# ============================================================
# ValidationError 增强
# ============================================================

class TestValidationErrorEnhancement:
    def test_msg_contains_source_chain(self):
        """ValidationError.errors() msg 含 [来源: chain]."""
        m = ConfigMerger()
        with pytest.raises(ValidationError) as exc_info:
            m.merge(YOLOTrainConfig, sources=[(ConfigSource.YAML, {"epochs": -5})])
        errs = exc_info.value.errors()
        epochs_err = next(e for e in errs if e["loc"] == ("epochs",))
        assert "来源" in epochs_err["msg"]
        assert "-5(YAML)" in epochs_err["msg"]
        assert "100(DEFAULT)" in epochs_err["msg"]

    def test_track_sources_false_no_enhancement(self):
        """track_sources=False 时不增强错误信息."""
        m = ConfigMerger(track_sources=False)
        with pytest.raises(ValidationError) as exc_info:
            m.merge(YOLOTrainConfig, sources=[(ConfigSource.YAML, {"epochs": -5})])
        errs = exc_info.value.errors()
        epochs_err = next(e for e in errs if e["loc"] == ("epochs",))
        assert "来源" not in epochs_err["msg"]


# ============================================================
# 边界
# ============================================================

class TestEdgeCases:
    def test_none_does_not_override(self):
        """None 不参与覆盖 (Loader 已过滤, Merger 再防御)."""
        m = ConfigMerger()
        c = m.merge(YOLOTrainConfig, sources=[
            (ConfigSource.YAML, {"epochs": 50}),
            (ConfigSource.CLI,  {"epochs": None}),
        ])
        assert c.epochs == 50

    def test_merger_reusable(self):
        """同一个 merger 实例可以多次 merge, 状态不串台."""
        m = ConfigMerger()

        c1 = m.merge(YOLOTrainConfig, sources=[(ConfigSource.YAML, {"epochs": 100})])
        assert m.get_metadata("epochs").value == 100

        c2 = m.merge(YOLOTrainConfig, sources=[(ConfigSource.CLI, {"epochs": 200})])
        # 第二次合并应该重置, 第一次的痕迹不该残留
        assert m.get_metadata("epochs").value  == 200
        assert m.get_metadata("epochs").source == ConfigSource.CLI
        # 第二次 chain 应该是 200(CLI) ← 100(DEFAULT), 不含 100(YAML)
        chain = m.get_metadata("epochs").chain()
        assert all(meta.source != ConfigSource.YAML for meta in chain)

    def test_track_sources_disabled(self):
        m = ConfigMerger(track_sources=False)
        c = m.merge(YOLOTrainConfig, sources=[(ConfigSource.YAML, {"epochs": 77})])
        assert c.epochs == 77
        assert m.get_metadata("epochs") is None
        assert "未启用" in m.get_source_report()
```

## 8.8 `test_generator.py` + `test_public_api.py`

```python
# test_generator.py
"""ConfigGenerator: YAML 模板生成."""
from __future__ import annotations

from pathlib import Path

import pytest

from odp_platform.runtime_config.generator import ConfigGenerator
from odp_platform.runtime_config.train     import YOLOTrainConfig
from odp_platform.runtime_config.val       import YOLOValConfig
from odp_platform.runtime_config.loaders   import YAMLLoader


class TestFormatValue:
    def setup_method(self):
        self.g = ConfigGenerator()

    def test_none(self):
        assert self.g._format_value(None) == "null"

    @pytest.mark.parametrize("val,expected", [
        (True,  "true"),
        (False, "false"),    # ★ bool 必须在 int 之前判
    ])
    def test_bool(self, val, expected):
        assert self.g._format_value(val) == expected

    @pytest.mark.parametrize("val,expected", [
        (16,    "16"),
        (-1,    "-1"),
        (0.001, "0.001"),
    ])
    def test_numbers(self, val, expected):
        assert self.g._format_value(val) == expected

    @pytest.mark.parametrize("val,expected", [
        ("yolo.pt", "yolo.pt"),       # 普通字符串无引号
        ("a:b",    '"a:b"'),          # 含 ':' 加引号
        ("#tag",   '"#tag"'),         # 含 '#'
        ("[x]",    '"[x]"'),          # 含 '['
    ])
    def test_strings(self, val, expected):
        assert self.g._format_value(val) == expected

    def test_lists(self):
        assert self.g._format_value([1, 2, 3]) == "[1, 2, 3]"
        assert self.g._format_value([])        == "[]"
        assert self.g._format_value([True, False]) == "[true, false]"


class TestGenerate:
    def test_basic_generation(self, tmp_path):
        g = ConfigGenerator()
        out = tmp_path / "train.yaml"
        assert g.generate(YOLOTrainConfig, out, overwrite=True) is True
        assert out.exists()

        content = out.read_text(encoding="utf-8")
        # 头部
        assert "自动生成时间" in content
        assert "odp-gen-config" in content        # ★ FAQ 含"如何重新生成"指引
        # 分组
        for group in ["核心参数", "训练控制", "优化器配置", "高级设置"]:
            assert f"# {group}" in content
        # 关键字段
        for field in ["task", "experiment_name", "epochs", "lr0"]:
            assert f"{field}:" in content
        # 注释格式
        assert "# 示例: " in content
        assert "# 提示:"  in content
        # FAQ
        assert "CLI > YAML > DEFAULT" in content

    def test_generated_yaml_roundtrips(self, tmp_path):
        """★ 关键: 生成的 YAML 必须能被 YAMLLoader 完整解析回来."""
        out = tmp_path / "train.yaml"
        ConfigGenerator().generate(YOLOTrainConfig, out, overwrite=True)

        parsed = YAMLLoader().load(out)
        # 默认值都对应得上
        assert parsed["epochs"]    == 100
        assert parsed["batch"]     == 16
        assert parsed["amp"]       is True       # bool 保持 bool
        assert parsed["task"]      == "detect"

    def test_default_no_overwrite(self, tmp_path):
        out = tmp_path / "train.yaml"
        g = ConfigGenerator()
        g.generate(YOLOTrainConfig, out, overwrite=True)

        # 用户改 yaml
        original = out.read_text(encoding="utf-8")
        modified = original.replace("epochs: 100", "epochs: 999")
        out.write_text(modified, encoding="utf-8")

        # 再生成 — 不该覆盖
        assert g.generate(YOLOTrainConfig, out) is False
        assert "epochs: 999" in out.read_text(encoding="utf-8")

    def test_overwrite_true_overrides(self, tmp_path):
        out = tmp_path / "train.yaml"
        out.write_text("epochs: 999\n", encoding="utf-8")
        ConfigGenerator().generate(YOLOTrainConfig, out, overwrite=True)
        assert "epochs: 100" in out.read_text(encoding="utf-8")

    def test_val_generation(self, tmp_path):
        out = tmp_path / "val.yaml"
        ConfigGenerator().generate(YOLOValConfig, out, overwrite=True, title="YOLO 验证配置")
        content = out.read_text(encoding="utf-8")
        assert "split: val"      in content
        assert "conf: 0.001"     in content
        assert "iou: 0.6"        in content
        assert "save_json: true" in content

    def test_creates_parent_dir(self, tmp_path):
        nested = tmp_path / "deep" / "subdir" / "train.yaml"
        assert ConfigGenerator().generate(YOLOTrainConfig, nested, overwrite=True) is True
        assert nested.exists()


class TestGuessShortName:
    def test_train(self):
        g = ConfigGenerator()
        assert g._guess_short_name(YOLOTrainConfig) == "train"
        assert g._guess_short_name(YOLOValConfig)   == "val"
```

```python
# test_public_api.py
"""__init__.py 公共 API + build_* 流水线."""
from __future__ import annotations

import inspect

from argparse import Namespace
import pytest

import odp_platform.runtime_config as rc


class TestPublicAPISurface:
    """公开 API 表面契约."""

    def test_all_symbols_importable(self):
        for name in rc.__all__:
            assert hasattr(rc, name), f"__all__ 声明了 {name} 但模块没有"
            obj = getattr(rc, name)
            assert obj is not None

    def test_all_symbols_have_docstring(self):
        """API 必须自我文档化."""
        missing = []
        for name in rc.__all__:
            obj = getattr(rc, name)
            if not (inspect.getdoc(obj) or "").strip():
                missing.append(name)
        assert not missing, f"以下公开符号缺 docstring: {missing}"

    def test_no_private_in_all(self):
        for name in rc.__all__:
            assert not name.startswith("_"), \
                f"私有符号 {name} 不应该在 __all__"

    def test_reexports_not_copies(self):
        """公开符号是 re-export, 不是 copy."""
        from odp_platform.runtime_config.train  import YOLOTrainConfig as _TC
        from odp_platform.runtime_config.merger import ConfigSource    as _CS
        assert rc.YOLOTrainConfig is _TC
        assert rc.ConfigSource    is _CS


class TestBuildTrainConfig:
    def test_full_pipeline(self, minimal_train_yaml):
        config, merger = rc.build_train_config(
            yaml_path=minimal_train_yaml.name,
            yaml_dir=minimal_train_yaml.parent,
            cli_args=Namespace(epochs=300, batch=64),
        )
        assert isinstance(config, rc.YOLOTrainConfig)
        assert config.epochs == 300
        assert config.batch  == 64
        assert config.lr0    == 0.005

    def test_returns_merger_with_traceability(self, minimal_train_yaml):
        config, merger = rc.build_train_config(
            yaml_path=minimal_train_yaml.name,
            yaml_dir=minimal_train_yaml.parent,
            cli_args=Namespace(epochs=300),
        )
        assert isinstance(merger, rc.ConfigMerger)
        meta = merger.get_metadata("epochs")
        assert meta.source == rc.ConfigSource.CLI
        assert "300(CLI) ← 200(YAML) ← 100(DEFAULT)" == meta.chain_str()

    def test_yaml_path_none_skips_yaml(self):
        config, merger = rc.build_train_config(
            yaml_path=None,
            cli_args=Namespace(model="x.pt", data="y.yaml", epochs=50),
        )
        assert config.epochs == 50
        yaml_keys = [
            k for k, m in merger._metadata.items()
            if m.source == rc.ConfigSource.YAML
        ]
        assert yaml_keys == []

    def test_track_sources_false(self):
        config, merger = rc.build_train_config(
            yaml_path=None,
            cli_args=Namespace(model="x.pt", data="y.yaml", epochs=50),
            track_sources=False,
        )
        assert config.epochs == 50
        assert merger.get_metadata("epochs") is None


class TestBuildValConfig:
    def test_full_pipeline(self, write_yaml):
        f = write_yaml("split: test\nconf: 0.5\n", name="val.yaml")
        config, merger = rc.build_val_config(
            yaml_path=f.name,
            yaml_dir=f.parent,
            cli_args=Namespace(iou=0.7),
        )
        assert isinstance(config, rc.YOLOValConfig)
        assert config.split == "test"
        assert config.conf  == 0.5
        assert config.iou   == 0.7
```

## 8.9 pyproject.toml / pytest 配置

`apps/platform/pyproject.toml` 加测试配置:

```toml
[tool.pytest.ini_options]
testpaths     = ["tests"]
python_files  = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "-v",
    "--strict-markers",
    "--tb=short",
]
filterwarnings = [
    # 我们自己用 warnings.warn 的提示, 测试里要能捕获
    "default::UserWarning",
]
```

⚠️ **设计点 (`--strict-markers`)** 防止拼错 mark 名字静默失败. 写 `@pytest.mark.slo`(typo, 应该是 `slow`)在没有 `--strict-markers` 时会被默默接受、永远不跑——`--strict-markers` 让没注册的 mark 立刻报错.

⚠️ **设计点 (`addopts = ["-v"]` 默认就 verbose)** 让本地 `pytest` 跟 CI `pytest` 行为完全一致——没有 "CI 输出我看不到的细节" 这种调试障碍.

## 8.10 跑一遍 pytest

```bash
cd apps/platform
pytest tests/runtime_config/ -v

# 期望输出:
# tests/runtime_config/test_base.py::test_base_config_default_values PASSED
# tests/runtime_config/test_base.py::test_base_config_extra_forbid PASSED
# tests/runtime_config/test_base.py::test_to_ultralytics_kwargs_drops_framework_fields PASSED
# ... 
# tests/runtime_config/test_train_val.py::TestTaskExperimentNameSplit::test_task_defaults_to_detect PASSED
# tests/runtime_config/test_train_val.py::TestTaskExperimentNameSplit::test_train_task_rejects_invalid[detect_v2] PASSED
# tests/runtime_config/test_train_val.py::TestTaskExperimentNameSplit::test_train_task_rejects_invalid[Detection] PASSED
# ... 

# ===== 75 passed in 1.43s =====
```

⚠️ **设计点 (测试速度)** 单元测试目标 **< 5 秒跑完整套**——超过这个值开发者就会开始 "等会儿再跑". D5 这套全部是内存操作 + tmp_path 文件 IO, 实际跑下来 1-2 秒. 文件 IO 集中的测试用 `tmp_path` (pytest 在 RAM 上可能用 tmpfs), 速度有保证.

## 8.11 git commit

```bash
git add apps/platform/tests/runtime_config/
git add apps/platform/pyproject.toml
git commit -m "test(runtime_config): add unit tests for D5 subsystem

tests/runtime_config/:
  + conftest.py       — shared fixtures (write_yaml, yaml_dir, minimal_train_yaml)
  + test_base.py      — BaseConfig contracts (8 tests)
  + test_train_val.py — YOLOTrainConfig/YOLOValConfig (25 tests, mostly parametrized)
  + test_loaders.py   — YAMLLoader/CLILoader (20 tests)
  + test_merger.py    — ConfigMerger + linked-list traceability (15 tests)
  + test_generator.py — ConfigGenerator (~12 tests)
  + test_public_api.py — __init__.py + build_* helpers (~10 tests)

pyproject.toml:
  + [tool.pytest.ini_options]
      testpaths, python_files/classes/functions discovery rules,
      --strict-markers (typo'd marks → error, not silent skip),
      filterwarnings to surface our UserWarning() emissions.

Total: ~90 test cases, ~1.5s wall-clock.

Key design — what's tested:
  - Field contracts: defaults, validators, extra='forbid'
  - Cross-field: save/save_period (raise), mosaic/close_mosaic (warn)
  - task/experiment_name split: error message must point to experiment_name
  - FRAMEWORK_ONLY_FIELDS: train.task IN kwargs; val.task NOT in kwargs
  - YAMLLoader fail-fast: error includes 'python -m ...generator' repair hint
  - YAMLLoader edge cases: empty file, all-comments, yaml null, list at top
  - CLILoader: control field exclusion, private field exclusion,
               None filtering, name mapping
  - Merger priority: CLI > YAML > DEFAULT
  - Merger chain: 1/2/3-layer chains correctly formed
  - Merger reusable: state cleared on each merge() call
  - ValidationError enhancement: errors() msg contains [来源: chain]
  - Generator roundtrip: YAML output parses back via YAMLLoader
  - Generator safety: default overwrite=False protects user edits
  - Public API: all __all__ symbols importable + docstring'd
  - build_*_config: full pipeline integration

Key design — what's NOT tested (deferred to D6):
  - Actual ultralytics model.train() / model.val() runs
  - Logging integration with D2 logging_utils
  - End-to-end CLI entry point (odp-train will get its own tests)
"
```

**中文版**:

```bash
git commit -m "test(runtime_config): 新增 pytest 单元测试套件 (~100 用例)" \
           -m "apps/platform/tests/runtime_config/:" \
           -m "  + conftest.py —— 共享 fixture (write_yaml / yaml_dir / minimal_train_yaml)" \
           -m "  + test_base.py —— BaseConfig 行为契约" \
           -m "    extra='forbid' 拒绝拼错字段名" \
           -m "    to_ultralytics_kwargs 过滤 framework-only 字段" \
           -m "    audit_snapshot 往返恢复 + JSON 可序列化" \
           -m "    mask_sensitive_dump 标记的字段被替换" \
           -m "  + test_train_val.py —— YOLOTrainConfig + YOLOValConfig" \
           -m "    task/experiment_name 拆分 (核心契约)" \
           -m "    跨字段验证 (save vs save_period 矛盾 raise; mosaic vs close_mosaic 冗余 warn)" \
           -m "    val 的 task 不传给 ultralytics" \
           -m "  + test_infer.py —— YOLOInferConfig (★ 推理闭环)" \
           -m "    source 类型标准化 (str/Path/int 摄像头索引)" \
           -m "    conf 默认 0.25 vs val 0.001" \
           -m "    4 个跨字段警告全部 warn 不 raise" \
           -m "  + test_loaders.py —— YAMLLoader + CLILoader" \
           -m "    文件不存在的 FileNotFoundError 含 python -m generator 修复命令 (硬断言)" \
           -m "    YAML 格式错的 ValueError 含提示" \
           -m "    UTF-8 + GBK fallback" \
           -m "    None 值过滤但保留 False/0/''" \
           -m "  + test_merger.py —— ConfigMerger 链表溯源核心" \
           -m "    sources list 接口 (枚举 + 自定义字符串源)" \
           -m "    优先级 CLI > extra > YAML > DEFAULT" \
           -m "    chain_str 输出 ← 链" \
           -m "    ValidationError 增强含 [来源: ...] 子串" \
           -m "  + test_generator.py + test_public_api.py" \
           -m "    模板生成各类型格式化" \
           -m "    overwrite=False 不破坏 + overwrite=True 自动备份" \
           -m "    __all__ 14 个符号完整性 + build_* 端到端" \
           -m "pyproject.toml: pytest 配置加 [tool.pytest.ini_options]" \
           -m "为什么 D5 就写单元测试, 不留给 D6:" \
           -m "  端到端测试不能定位错误 (model.train() 报错说不清是哪一环)" \
           -m "  重构需要安全网 (改一行 BaseConfig 不会改坏什么)" \
           -m "  测试本身是文档 (能被执行的契约, 不跟代码漂移)" \
           -m "  D5 测试只测'配置层契约', 不测 ultralytics 实际行为 (那是 D6 的事)"
```


> **金句**: **"单元测试是写给三个月后的自己的——那时候你忘了为什么 task validator 要带 'experiment_name' 那段提示, 但测试用 6 个 parametrize case 把这件事钉死. 测试 = 行为契约的可执行版."**

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 9: ADR-005——把"为什么"沉淀下来

8 个阶段把 runtime_config **怎么做** 讲清楚了, 还差一份文档讲 **为什么这么做**.

ADR (Architecture Decision Record) 不是教程, 不是 API 文档, 是 **决策的考古记录**——记下当时面临的问题、考虑过的方案、最终选择的理由. 半年后回看, "为什么不用 Hydra?" 这种问题就有处可查, 不会变成口头传承.

> **金句**: **"代码记录'我们怎么做了'; 测试记录'我们承诺了什么行为'; ADR 记录'我们为什么这么做'——三者缺一不可."**

## 9.1 ADR-005 完整内容

`docs/architecture/ADR-005-runtime_config-subsystem.md`:

```markdown
# ADR-005: runtime_config 子系统设计

| 字段 | 值 |
|---|---|
| 状态 | Accepted |
| 日期 | 2026-05-20 |
| 决策者 | 雨霓同学 + ODPlatform team |
| 上游依赖 | ADR-001 (路径 SSoT), ADR-002 (词汇 SSoT) |
| 下游影响 | D6 (TrainService / ValService), 后续 InferService |

---

## 1. 背景

D5 之前, legacy 代码把 "训练 / 验证的配置" 分散在三处:

- `legacy/config/`        — 8 个 Pydantic 模型文件 (YOLOTrainConfig 等)
- `legacy/training/`      — TrainService 直接实例化 + 用 YAML 工具
- `legacy/evaluation/`    — ValService 同上模式 + 大量重复代码

字段共有 60+ 个, 训练特有 50 个、验证特有 11 个、共享约 15 个. legacy 没有共享基类, 字段定义在多个文件里漂移. 三类问题:

### 问题 1: 字段散乱 + 无共享层

`model / data / batch / imgsz` 这种 "训练和验证都用" 的字段在 train 和 val 各自的类里定义两遍, 改一个字段(比如想给 `batch` 加新校验) 就要找两处, 容易漂移. 已经出现过 train 的 batch validator 跟 val 的不一致的 bug.

### 问题 2: 字段元数据缺失, YAML 模板手维护

legacy YAML 模板是手写的——用户拿到 yaml 不知道 "epochs 默认多少"、"lr0 的合理范围"、"task 能填啥". 文档跟代码漂移, 实习生改 yaml 时全靠猜 + 跑起来报错.

### 问题 3: task 字段过载

```python
# legacy
task: str = "detect_val"     # 既是 SSoT 又是目录名
```

`task` 字段同时承担:
1. 任务语义(detect / segment, SSoT)
2. 输出目录名(runs/{task}/...)
3. 实验标识(用户想给跑这一次起个名)

三件事挤一个字段, 任何一个都做不好. 详见 lecture 阶段 3 撞墙②.

### 问题 4: 配置来源不可追溯

`epochs=200` 跑出来不收敛, 用户想问 "这个 200 是 yaml 写的还是 CLI 传的", legacy 答不出来——只记最终值, 不记由来.

### 问题 5: YAML 不存在时静默生成

legacy `service.py` 检测到 yaml 不存在时, 自动生成默认模板继续跑. CI 场景下 5 小时训练用了默认值而不是用户预期值, 完全没信号. 详见 lecture 阶段 4 撞墙③.

---

## 2. 决策

把配置子系统重构为独立的 `runtime_config/` 包, 划分 6 个职责模块, 加 1 个公共 API 文件:

```
runtime_config/
├── __init__.py    — 对外公共 API (12 个符号)
├── base.py        — BaseConfig (15 个共享字段 + 元数据 SSoT + 7 个工具方法)
├── train.py       — YOLOTrainConfig (52 个训练特有字段)
├── val.py         — YOLOValConfig (11 个验证特有字段)
├── loaders.py     — YAMLLoader + CLILoader (外部数据 → dict)
├── merger.py      — ConfigMerger (sources list 合并 + 链表式溯源 + 3 个审计产物)
└── generator.py   — ConfigGenerator (Pydantic → YAML 模板, 默认不覆盖 + 覆盖时备份)
```

### 2.1 核心设计选择

**选择 A: Pydantic v2 + 字段级元数据 (5 槽位)**

每个字段 `Field(default=..., description=..., json_schema_extra={"group", "examples", "tips", "yaml_comment", "sensitive"})`. 5 个元数据槽位:
- `group`        — 字段分组 (决定 yaml 模板里出现在哪一段)
- `examples`     — 典型取值
- `tips`         — 多条调参建议
- `yaml_comment` — yaml 注释里的一行说明 (用户向)
- `sensitive`    — 是否敏感字段, True 时 mask 接口自动替换成 `"***"` (默认 False, 可省略)

字段定义和文档表达 **来自同一个真相**, 任何字段改动同时改注释, 不漂移.

**选择 B: ClassVar 集合扩展, 不 override 方法**

`FRAMEWORK_ONLY_FIELDS: ClassVar[set[str]]` 控制 "哪些字段不传给 ultralytics". `SENSITIVE_MASK: ClassVar[str] = "***"` 控制敏感字段的 mask 字符串. 子类靠 **扩展集合 / 重新赋值类常量** 而不是 override 方法来定制行为. 加新框架字段时, 只动一行集合, 不动方法体. 数据驱动 > 方法驱动.

**选择 C: task / experiment_name 拆分**

用两个字段表达两个正交职责:
- `task`: 封闭取值 `{detect, segment}` (SSoT 语义), 严格 validator
- `experiment_name`: 自由字符串 (实验标识), 进 FRAMEWORK_ONLY_FIELDS, 由 service 层翻译成 ultralytics 的 `name`

`task` validator 的错误信息显式指引 → "若想取名请用 experiment_name", 用户调一次报错就明白. val_model 的跨字段验证 (segment 专属字段在 detect 任务下警告) 直接用 `self.task != Task.SEGMENT` 严格相等, 不用 legacy 那种 `"segment" not in self.task` 字符串模糊匹配——SSoT 在 validator 里硬保证. 详见 lecture 阶段 3.

**选择 D: sources list 接口 + 链表式溯源**

`ConfigMerger.merge(cls, *, sources=[(source_id, dict), ...])`——源数量无上限, 顺序 = 优先级 (从低到高), source_id 接受 `ConfigSource` 枚举或任意字符串. 内置 3 档枚举 (DEFAULT/YAML/CLI) 装核心场景, 字符串装自定义源 (ENV / etcd / k8s configmap) 的扩展点. DEFAULT 源 merger 自动注入到最前.

`ConfigMetadata.overridden_from` 指针保留完整覆盖历史, `chain_str` 输出 `"0.001(CLI) ← 0.005(YAML) ← 0.01(DEFAULT)"`. 不只记最终值, 让 PR review / 论文复现等场景能精确追溯 "为什么是这个值".

**选择 E: 三个审计产物 (人 / DB / ELK)**

merge 完产出三个独立产物, 受众不同, 各管一摊互不替代:

| 产物 | 输出类型 | 受众 | 落点 |
|---|---|---|---|
| `merger.get_source_report()` / `get_conflict_report()` | str (带边框) | 开发者 / 用户 | 终端 |
| `config.to_audit_snapshot()` | dict (含类标识 + 完整字段值) | 实验复现系统 | 数据库 |
| `merger.to_audit_log()` | dict (字段名 + 来源 + 数量, 无字段值) | 运维 / SRE | ELK (json.dumps) |

字符串报告自动 mask sensitive 字段, audit_log 不含字段值天然规避敏感数据泄漏.

**选择 F: dry-run 预览 + 自动备份**

两道纵深防御:
- `build_*_config(dry_run=True)` → 跳过 Pydantic 验证, 调用方先看 source_report 再决定. 底层是 `ConfigMerger.preview()`.
- `ConfigGenerator.generate(overwrite=True, backup=True)` → 默认覆盖前自动备份成 `<name>.yaml.bak.<YYYYMMDD_HHMMSS>`. `--no-backup` 显式关掉.

跟 D2.5 `odp-reset` 的 "危险动作要确认" 同款纪律.

**选择 G: YAML 不存在 → fail-fast + 修复指引**

不再静默生成模板. 错误信息直接告诉用户跑哪条命令 (主推 `odp-gen-config <name>`, 备胎 `python -m odp_platform.runtime_config.generator <name>`). 由阶段 6 的 ConfigGenerator + main 入口实现, 形成闭环.

**选择 H: 字段验证留给 Pydantic, 不在 Loader / Merger 里写**

每层只做一件事:
- Loader 只把外部数据装进 dict (不验证字段值)
- Merger 只按 sources list 顺序合 + 维护溯源 (不验证字段值)
- Pydantic 拿到合并后的 dict 才做字段验证

错误责任永远精确——格式错 = Loader 责任, 值非法 = Pydantic 责任, 来源说不清 = Merger 责任.

### 2.2 公开 API (`__all__`)

14 个符号 (含 infer 闭环):

| 类别 | 符号 | 用途 |
|---|---|---|
| 配置类 | `BaseConfig`, `YOLOTrainConfig`, `YOLOValConfig`, `YOLOInferConfig` | 字段定义 + 验证 + 7 个工具方法 |
| 加载器 | `YAMLLoader`, `CLILoader`, `load_all_sources` | 外部数据 → dict |
| 合并器 | `ConfigMerger`, `ConfigSource`, `ConfigMetadata` | sources list 合并 + 链表溯源 + 3 个审计产物 |
| 生成器 | `ConfigGenerator` | Pydantic → YAML 模板, 含覆盖备份 |
| 便捷函数 | `build_train_config`, `build_val_config`, `build_infer_config` | 一键流水线, 含 dry_run / extra_sources |

D6/D7/D8 service 层各自靠 `build_train_config` / `build_val_config` / `build_infer_config` 一行调用就拿到 `(config, merger)`. dry-run / 加自定义源 / 推审计日志都靠这三个函数的关键字参数表达, **公共 API 控制在 14 个符号, 但能力覆盖 train/val/infer 三模式**.

### 2.3 4 条工程规矩 (CI 守门)

D5 子系统范围内的硬纪律, 不靠"开发者自觉":

| 规矩 | 强制工具 |
|---|---|
| paths.py 是路径唯一真相, 禁硬编码 | pre-commit grep hook |
| `warnings.warn` (用户输入) vs `logger` (系统行为) 严格分离 | code review + pytest catch_warnings/caplog |
| 类型注解统一 PEP 585/604 + `from __future__ import annotations` | ruff `select=["UP"]` |
| CLI 双通道入口 (`python -m ...` + entry-point 短命令) | pyproject.toml `[project.scripts]` |

立得早, 加固成本低. 等子系统跑了半年才回头加这些约束, 改一处碰七处.

---

## 3. 不选择的方案

### 方案 A: Hydra

[Hydra](https://hydra.cc/) 是 Facebook AI Research 出的配置框架, 支持组合配置、CLI 覆盖、多次运行实验等. **不选的理由**:

1. **学习曲线陡峭** — Hydra 的 `@hydra.main` 装饰器模式跟 ODPlatform 既有的 click-based CLI 风格冲突, 引入意味着所有入口要改.
2. **过度抽象** — Hydra 解决的核心问题(实验组合 + sweep)我们暂时不需要, 它带来的复杂性不匹配当前规模.
3. **黑盒程度高** — Hydra 的配置组合机制嵌入很深, 一旦报错排查靠 Hydra 文档. 我们目前的 6 模块自己实现, 报错都在自家代码里, 调试可控.

未来如果需要 sweep / multi-run, 可以在 ODPlatform 之上加一层 Hydra wrapper, 不破坏现有架构.

### 方案 B: dataclasses + argparse 直转

```python
@dataclass
class YOLOTrainConfig:
    epochs: int = 100
    ...

config = YOLOTrainConfig(**vars(args))
```

**不选的理由**:

1. **验证能力不足** — dataclass 没有内置的字段验证(范围、枚举、cross-field 都没有). 自己写一套等于重发明 Pydantic.
2. **元数据机制薄弱** — dataclass 的 `field(metadata={...})` 是字典, 没有 schema 化. 反射出 yaml 模板时要写一堆胶水.
3. **错误信息差** — TypeError 而不是 Pydantic 那种带字段路径、带类型提示的 ValidationError.

### 方案 C: OmegaConf

[OmegaConf](https://omegaconf.readthedocs.io/) 是 Hydra 底层用的配置库, 支持插值、merge、struct mode 等. **不选的理由**:

1. **不强类型** — OmegaConf 主打 "灵活", 字段类型靠运行时打补丁, 跟 ODPlatform "Pydantic v2 全链路强类型" 的纪律冲突.
2. **没有字段级元数据** — 我们需要每字段写 `tips` / `examples`, OmegaConf 的 yaml 注释要在文件层面手维护, 又回到了 legacy 的漂移问题.

### 方案 D: 把 D5 留作 D6 的内部细节, 不抽独立子系统

"反正只有 train 和 val 两个 service 在用, 干嘛单独抽个 runtime_config?" 这种偷懒思路的问题是:

1. **infer service 后续要加**, 那时再抽是双倍工作 + 已有 service 要改.
2. **配置层独立测试不可能** — 跟 service 揉一起, 单元测试只能跑端到端.
3. **复用边界模糊** — 未来如果 D2/D3 也想用 BaseConfig 风格的元数据反射, 没有干净的入口.

抽独立子系统的成本是 4 个文件(`base/train/val/__init__`), 收益是 D6 / D7 / 测试 / 文档 / 复用 全部清晰. 性价比明显.

---

## 4. 后果

### 4.1 好处

- **字段元数据 SSoT** — 加新字段一次写, 模板 / 文档 / 验证 全部跟上, 不漂移
- **配置溯源** — 跑训练时能精确回答 "这个值是谁给的", 排查时间从分钟级降到秒级
- **YAML 自我文档化** — 用户打开生成的 yaml 第一眼就明白每个字段, 不查外部文档
- **配置 / Service 解耦** — D6 service 层只关心业务编排, 不掺杂配置加载细节
- **可单测** — 6 个模块各自单测, ~90 个测试用例, ~1.5s 跑完, 进 CI
- **可扩展** — 未来加 `YOLOInferConfig` 只用新建一个文件 + 注册到 `_CONFIG_REGISTRY`, 不动 base / loaders / merger / generator

### 4.2 坏处 / 风险

- **Pydantic v2 学习成本** — 团队成员需要熟悉 Field / json_schema_extra / model_validator. 我们用讲义 + 注释 + ADR 三重保险, 缓解学习曲线.
- **链表式 metadata 对新人略复杂** — `overridden_from` 指针的概念不是每个人都熟. 用 lecture 阶段 5 的 "git commit chain" 比喻帮助理解.
- **60+ 字段元数据维护成本** — 加新字段或改 ultralytics 上游字段要更新元数据. 通过 unit test (`test_get_field_metadata_complete`) 强制每个字段至少要有用户向元数据, 防止漏写.
- **Pydantic v2 ValidationError 不可变** — 我们的 `_enhance_validation_error` 修改的是副本, 上层必须主动 catch + 读 `.errors()`. 这是 v2 设计限制, 不是 bug, 但需要在 lecture / 注释里反复说明.

### 4.3 性能影响

- 配置加载 + 合并 + 验证总耗时 < 50ms (D5 实测). Pydantic v2 是 Rust 实现的核心, 比 v1 快很多, 不构成训练流水线的瓶颈.
- 链表式 metadata 内存开销 = O(字段数 × 源数) ≈ 200 个 dataclass 实例 ≈ 几 KB. 忽略不计.

---

## 5. 关键文件位置

```
apps/platform/src/odp_platform/runtime_config/
├── __init__.py           ← 公共 API (14 个符号 + 3 个 build_* 函数)
├── base.py               ← BaseConfig (15 共享字段 + 元数据 + 工具方法)
├── train.py              ← YOLOTrainConfig (52 训练字段)
├── val.py                ← YOLOValConfig (11 验证字段)
├── infer.py              ← YOLOInferConfig (17 推理字段 + source)   ★ 推理闭环
├── loaders.py            ← YAMLLoader + CLILoader (fail-fast)
├── merger.py             ← ConfigMerger + ConfigMetadata 链表
└── generator.py          ← ConfigGenerator + python -m 入口 (支持 train/val/infer)

apps/platform/tests/runtime_config/
├── conftest.py           ← 共享 fixture
├── test_base.py          ← BaseConfig 行为
├── test_train_val.py     ← train/val 字段验证(含 task/experiment_name 拆分)
├── test_infer.py         ← YOLOInferConfig (source/conf/跨字段警告)   ★ 推理闭环
├── test_loaders.py       ← yaml/cli loader (含 fail-fast 修复指引断言)
├── test_merger.py        ← 三源优先级 + 链表 + 错误增强
├── test_generator.py     ← YAML 模板生成 + 不覆盖契约
└── test_public_api.py    ← __init__.py + build_* 流水线

apps/platform/configs/runtime/            ← yaml 实际存放位置
                                            (paths.RUNTIME_CONFIGS_DIR)
└── (train.yaml / val.yaml / infer.yaml — 由 generator 生成, 用户编辑)

docs/architecture/
└── ADR-005-runtime_config-subsystem.md   ← 本文件
```

---

## 6. 跟其他 ADR 的关系

- **ADR-001 (路径 SSoT)**: runtime_config 复用 `paths.runtime_config_path()` 解析 yaml 文件路径. 阶段 0 加的 `RUNTIME_CONFIGS_DIR` 是 ADR-001 的扩展.
- **ADR-002 (词汇 SSoT)**: `task` 字段的 validator 引用 `Task.all()` (D3 立的 SSoT), 不接受 Task 之外的取值. ADR-002 跟 ADR-005 在 task 字段上闭环.
- **未来 ADR (D6/D7/D8)**: TrainService / ValService / InferService 设计文档应当引用本 ADR, 明确各 service 层只通过 `build_*_config` 入口, 不直接构造 Pydantic 类或调用 Loader. D5 已经为三种 service 都准备好了对应的 build 函数.

---

## 7. 后续工作

- [x] **D5 阶段 3.6.5 / 3.7.5 / 3.11 已完成**: `YOLOInferConfig` + `build_infer_config` + 单元测试
- [ ] D6: TrainService 接入 `build_train_config`
- [ ] D7: ValService 接入 `build_val_config`
- [ ] D8: InferService 接入 `build_infer_config`
- [ ] 后续: 给 `ConfigMerger` 加 ProfileSource (例如 `dev.yaml` / `prod.yaml` 层级)
- [ ] 后续: 给 `ConfigGenerator` 加 schema export (JSON Schema, 供前端配置 UI)

---

## 8. 修订记录

| 日期 | 修订 | 作者 |
|---|---|---|
| 2026-05-20 | 初版, 9 个阶段实施完毕 | 雨霓同学 |
| 2026-05-21 | 加 YOLOInferConfig + build_infer_config + test_infer.py, 三模式 train/val/infer 完整闭环 (10 个 commit) | 雨霓同学 |
⚠️ **设计点 (ADR 一定有 "不选择的方案" 一节)** 这一节比 "决策" 一节还重要——半年后如果有人提议 "我们应该用 Hydra", 这节直接回答了 "我们考虑过, 不合适的理由是 X / Y / Z". 没有这节, 同样的讨论会反复发生.

⚠️ **设计点 (后果章节要写"坏处和风险")** 把缺点写出来不是 "唱衰自己", 是诚实的工程文化. 半年后撞到 "Pydantic 学习曲线" 问题时, ADR 已经预料到——团队不会以为这是个突发 bug, 而知道这是已经承担的代价.

⚠️ **设计点 (跟其他 ADR 的关系一节)** 显式记下 ADR 之间的引用关系. ADR-005 引用 ADR-001/002, 那么改 ADR-001(路径)时就知道要 review ADR-005. **文档之间的依赖也是 SSoT 的一部分**.

## 9 git commit

```bash
git add docs/architecture/ADR-005-runtime_config-subsystem.md
git commit -m "docs(runtime_config): add ADR-005 documenting subsystem design

docs/architecture/ADR-005-runtime_config-subsystem.md:
  + Background — 5 problems with legacy config layer
      1. fields scattered, no shared base
      2. yaml templates hand-maintained, doc drift
      3. task field overloaded (semantic + dir name + experiment id)
      4. no source traceability ('which source set this value?')
      5. silent yaml auto-generation hides CI failures
  + Decision — 6-module subsystem with explicit responsibilities:
      base / train / val / loaders / merger / generator + __init__
  + Core design choices (A-F):
      A. Pydantic v2 + 4-slot field metadata (group/examples/tips/yaml_comment)
      B. ClassVar set extension over method override
      C. task/experiment_name split (semantic vs identifier)
      D. linked-list source traceability (CLI > YAML > DEFAULT)
      E. fail-fast on missing yaml + repair-command in error msg
      F. validation stays in Pydantic; loader/merger do their own thing
  + Considered & rejected alternatives:
      - Hydra (overkill, learning curve, hides errors)
      - dataclasses + argparse (no validation, weak metadata)
      - OmegaConf (no strong typing, no field-level metadata)
      - Keep config inline with services (testability, reuse, extension)
  + Consequences:
      Pros — SSoT, traceability, self-doc yaml, decoupled, testable
      Cons — Pydantic learning curve, linked-list complexity for newcomers,
             ~60 fields metadata maintenance, v2 ValidationError immutable
  + File locations — code + tests + this ADR
  + Cross-ADR refs: ADR-001 (path SSoT), ADR-002 (vocabulary SSoT)
  + Follow-up work: D6 services, InferConfig, ProfileSource, JSON schema export

Key design — ADR captures 'why', not 'how':
  Lecture/code/tests already document 'how things work'.
  This ADR is the archaeological record of *decisions* — half a year
  from now, when someone asks 'why not Hydra?', this document answers
  without relying on tribal knowledge.

  The 'rejected alternatives' section is more valuable than 'decision'
  itself — it prevents the same debate from recurring.
"
```

**中文版**:

```bash
git commit -m "docs(runtime_config): 新增 ADR-005, 记录子系统设计决策" \
           -m "docs/architecture/ADR-005-runtime_config-subsystem.md:" \
           -m "  + 背景 —— legacy 配置层的 5 个问题:" \
           -m "    1. 字段散乱, 无共享层 (train/val 两份, 字段定义漂移)" \
           -m "    2. YAML 模板手维护, 注释跟代码漂移" \
           -m "    3. task 字段过载 (语义 + 目录名 + 实验标识三事挤一字段)" \
           -m "    4. 配置来源不可追溯 ('200 是 yaml 还是 cli?')" \
           -m "    5. YAML 不存在时静默自动生成 (CI 失败信号丢失)" \
           -m "  + 决策 —— 7 模块子系统, 每个单一职责:" \
           -m "    base / train / val / infer / loaders / merger / generator + __init__" \
           -m "  + 8 个核心设计选择 (A-H), 每个都说清'为什么是这样':" \
           -m "    A. Pydantic v2 + 5 槽位字段元数据 (含 sensitive)" \
           -m "    B. ClassVar 集合扩展, 不 override 方法" \
           -m "    C. task / experiment_name 拆分 (train/val/infer 三类都生效)" \
           -m "    D. sources list 接口 + 链表式溯源" \
           -m "    E. 三个独立审计产物 (人/DB/ELK)" \
           -m "    F. dry-run 预览 + 自动备份" \
           -m "    G. YAML 不存在 fail-fast + 修复指引" \
           -m "    H. 字段验证留给 Pydantic, Loader/Merger 不掺和" \
           -m "  + 不选择的方案 (Hydra/dataclass/OmegaConf/不抽独立子系统), 各自理由" \
           -m "  + 后果 —— 好处 / 坏处 / 风险 / 性能影响全列出" \
           -m "  + 跟其他 ADR 的关系 (引用 ADR-001 路径 SSoT, ADR-002 词汇 SSoT)" \
           -m "  + 后续工作 (D6/D7/D8 接入 / ProfileSource / JSON schema)" \
           -m "  + 修订记录 (后续改动追加到表里)" \
           -m "关键设计 —— ADR 记录'为什么', 不是'怎么做':" \
           -m "  讲义 / 代码 / 测试已经讲清'怎么做了'." \
           -m "  ADR 是决策的考古记录 —— 半年后有人问'为啥不用 Hydra'" \
           -m "  时, 这份文档替我们回答, 不靠口头传承." \
           -m "  '不选择的方案'一节比'决策'一节还重要 —— 防止同样的讨论反复发生."
```


---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 收尾——D5 回看

整个 D5 重构跑完了, 9 个 commit, ~3000 行代码 + ~1500 行测试 + 1 份 ADR + 这份讲义本身. 回过头看, 几个关键的事情:

## 三次撞墙, 三次拆解

| 撞墙 | 现象 | 拆解 |
|---|---|---|
| ① | 60+ 字段散乱无共享层 | BaseConfig(15 共享字段) + ClassVar 扩展点 |
| ② | `task` 既当语义又当目录名 | 拆 `task` (SSoT) + `experiment_name` (标识) |
| ③ | YAML 不存在时静默生成 | fail-fast + 修复指引 + 显式 generator 命令 |

每一面墙都不是凭空想出来的——都是 legacy 真实跑过、踩过坑、付过代价的. **D5 重构的 80% 价值, 在于把这三处隐性的坑显式化、可解释化、可教学化**.

这三次撞墙是 train/val/**infer** 三个配置类共同消化的——同一组设计原则统一应用到三种模式, 是 D5 的"复用红利". 加 infer 时几乎没遇到新问题——撞墙的痛在前面已经付过了.

## 三个 SSoT 的会合

D5 是 ODPlatform 第一个 **多个 SSoT 在同一处汇合** 的子系统:

- **路径 SSoT (D2 / ADR-001)**: `paths.RUNTIME_CONFIGS_DIR` / `runtime_config_path("train")`
- **词汇 SSoT (D3 / ADR-002)**: `Task.all()` 决定 `task` 字段合法取值
- **字段元数据 SSoT (D5 本身)**: 每字段 4 个槽位, 生成 yaml / 模板 / 文档都引用同一份

3 个 SSoT 不打架——`task` 字段的 validator 引用 D3 的 `Task.all()`, generator 输出的 yaml 写进 `paths.runtime_config_path("train")` 路径, 字段元数据自己管自己的展示. **SSoT 的合奏靠的是边界清晰, 不是强行统一**.

## 7 个模块, 单一职责

```
base.py     — 共享字段 + 元数据基础设施
train.py    — 训练特有字段
val.py      — 验证特有字段
infer.py    — 推理特有字段 + source 输入源     ★ 推理闭环
loaders.py  — 外部数据进入(yaml + cli)
merger.py   — 多源合并 + 链表溯源
generator.py — Pydantic → yaml 模板
```

任何一个模块改, 其他模块不动. Pydantic v2 升级? 改 base.py 一处. ultralytics 出新字段? train.py / val.py / infer.py 任意一处加 Field. 错误信息要中文化? generator.py 改 FAQ. **职责分得清, 改的勇气就有**.

## 数据驱动 > 方法驱动

D5 多处用到这个原则:

- `FRAMEWORK_ONLY_FIELDS: ClassVar[set[str]]` — 子类改集合不改方法
- `_CONFIG_REGISTRY: Dict[str, ...]` — 加新模板加注册项不改 main
- 字段元数据 `json_schema_extra` — 加注释加字典 entry 不改 generator

**数据驱动的扩展点用加法表达, 方法驱动的扩展点用 override 表达——加法天然不冲突, override 容易彼此撞车**.

## 报错信息是 API

D5 几乎每处 raise 都写了详细的错误信息:

- `task` validator → "若想给本次实验取名, 请使用 experiment_name 字段"
- YAMLLoader 不存在 → "请先生成默认配置模板: odp-gen-config <name>"
- YAMLLoader 格式错 → "提示: 检查缩进、引号匹配、冒号后是否有空格"
- ConfigMerger 增强 ValidationError → `[来源: 0.001(CLI) ← 0.005(YAML)]`

每条都告诉用户 **"下一步该做什么"** ——不只是 "出了错". **报错信息是子系统的最后一份文档, 也是用户最常看到的那份**.

## 给 D6 / D7 / D8 的接口承诺

D5 给三个 service 层都铺好了同一行 import + 同一行调用:

```python
# D6: 训练
from odp_platform.runtime_config import build_train_config
config, merger = build_train_config(yaml_path="train.yaml", cli_args=args)
model.train(**config.to_ultralytics_kwargs())

# D7: 验证
from odp_platform.runtime_config import build_val_config
config, merger = build_val_config(yaml_path="val.yaml", cli_args=args)
model.val(**config.to_ultralytics_kwargs())

# D8: 推理 (D5 顺手准备好了, source 通过 CLI 当场传)
from odp_platform.runtime_config import build_infer_config
config, merger = build_infer_config(
    yaml_path="infer.yaml",
    cli_args={"source": "video.mp4"},
)
model.predict(**config.to_ultralytics_kwargs())
```

三种模式同款 API + 同款返回值结构 (`(config, merger)` tuple). service 层都不用碰 yaml / cli / 合并细节, 也不用关心 task 怎么拆 / source 怎么标准化——**这是 D5 给 D6/D7/D8 的统一抽象红利**.

> **金句**: **"一个子系统建得好不好, 看它给下游留了多简单的 import. D5 给 D6/D7/D8 都留了 1 行 import + 1 行调用——这就是配置子系统的工业级标准."**

## 下一站: D6

```
✅ D2: common/ (paths, logging, constants)
✅ D3: data_pipeline/ (downloader, converter, splitter)
✅ D4: data_validation/ (validators + CLI)
✅ D5: runtime_config/ (本讲义) — train/val/infer 三模式全闭环
⬜ D6: training/    (TrainService, 接 build_train_config + 跑 model.train)
⬜ D7: evaluation/  (ValService, 接 build_val_config + 跑 model.val)
⬜ D8: inference/   (InferService, 接 build_infer_config + 跑 model.predict)
⬜ D9: model_management/ (权重发布 + 版本管理)
```

D6 的工作量比 D5 小很多——配置层立好了, service 层只是 "拿 config 跑训练 + 处理 logging + 处理输出目录". 但 D6 也有它自己的撞墙等着——比如 ultralytics 的 callback 机制怎么接入我们的 D2 logging? 输出目录冲突时怎么处理? trainer 中途 OOM 时配置怎么回收? 留给 D6 讲义.

> **金句**: **"做工程不是 '一次写完最完美的设计', 是 '每一阶段都让下一阶段过得更轻松'. D5 给 D6 减负, 就是 D5 这阶段的全部意义."**

---

D5 完结. 谢谢同学们读完——下次见.

---

## 📝 v2 变更日志(2026-05-23)

本次更新围绕 `odp-gen-config` entry-point 命令的全面对齐, 不动核心实现, 只调命令优先级与文档表述. 详细变动:

### 入口排序对齐(主推 `odp-gen-config`, `python -m` 降为备胎)

- §1 起点终点段: 工作流示例从 `python -m ...` 改成 `odp-gen-config train`(备胎注释保留)
- §0.5.4 「规矩 D」: 双入口对照表顺序对调, `odp-gen-config` 列第一(原文已经规定"两种都要支持", 这版只是把"主推"调到前面)
- §6.4 安全策略示例: 第一次/第二次跑都用 `odp-gen-config train`
- §6.5 章节标题: "`python -m` 入口" → "双入口(odp-gen-config / python -m): 子命令名 → 配置类映射"
- §6.5 命令清单: `odp-gen-config train/val/infer/--help/--overwrite/-o` 排第一组, `python -m` 作为备胎单列
- §6.6 generator.py 模块 docstring: CLI 入口说明排序对齐
- §6.8 真正跑一次: 4 处用户命令全部改成 `odp-gen-config`
- §9.1 ADR-005 「选择 G」: fail-fast 修复指引的主推命令调整

### 报错信息修复指引(代码内字符串)

- `loaders.py` YAMLLoader 文件不存在 raise 信息: `python -m odp_platform.runtime_config.generator <stem>` → `odp-gen-config <stem>` (短一倍, 跟其他 odp-* 命令同款)
- §4.8 报错信息细节示例同步更新
- §4.9 commit message 的 "fix command" 描述同步

### 测试断言跟随代码

- `test_loaders.py` `TestYAMLLoaderFailFast`: 断言改为 `assert "odp-gen-config" in msg`
- §8.1 教学用断言示例同步
- `test_generator.py` `TestGenerate.test_basic_generation`: 断言改为 `assert "odp-gen-config" in content`(对应下一条)

### Bug 修(顺手)

- §6.6 generator.py `_generate_yaml` FAQ 部分新增一条 Q&A:
  - **Q: 如何用新版默认值重新生成此模板?**
  - **A: 跑 `odp-gen-config <name> --overwrite` (会自动备份原文件)**
- 这个修复让原讲义 v1 里 `test_generator` 那条断言"生成的 YAML 里应该有重新生成命令"真的成立——原 v1 的断言是讲义 bug

### commit message 改述

- 阶段 6 commit subject: `feat(runtime_config): add ConfigGenerator + python -m entry` → `feat(runtime_config): add ConfigGenerator + dual CLI entry (odp-gen-config / python -m)`
- 中文版 commit body 同步: 体现"双入口共享 generator.main, 不立 cli/ 薄包装"

### 收尾段对齐

- §"报错信息是 API" 那段示例从 `"请先生成默认配置模板: python -m ..."` 改成 `"请先生成默认配置模板: odp-gen-config <name>"`

### 不变的部分

- §6.6 generator.py 完整代码(除 FAQ 新增的两行 lines.append 外, 实现不动)
- 三模式 build_* 公共 API 签名
- merger / loader / Pydantic 验证策略
- 阶段 7-9 测试覆盖结构
- ADR-005 主体决策(只在"选择 G"小段调了表述)

### 配套文档

- 交接文档同步升级到 **v1.3**(主要纠正一处: entry-point 直接绑 `runtime_config.generator:main`, **不需要** `cli/generate_config.py` 薄包装——这是讲义 §0.5.4 规矩 D 已经定了的)
- D5 功能清单同步升级到 **v1.2**

