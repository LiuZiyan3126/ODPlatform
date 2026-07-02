# ODPlatform 项目重置工具（reset_project）

# 产品需求文档（PRD）

| 文档编号 | ODP-PRD-2026-003 |
| --- | --- |
| 文档名称 | ODPlatform 项目重置工具 产品需求文档 |
| 产品 / 项目 | ODPlatform（通用目标检测开发平台） |
| 所属里程碑 | V1.0 — D2.5 阶段 |
| 文档版本 | v1.0 |
| 文档状态 | 已评审（Approved） |
| 密级 | 内部公开 |
| 作者（Owner） | 雨霓（Platform Team） |
| 评审人 | 架构组 / QA 组 / 平台组负责人 |
| 评审日期 | 2026-05-11 |
| 生效日期 | 2026-05-11 |
| 文档语言 | 简体中文 |

---

## 修订记录（Change Log）

| 版本 | 日期 | 修订人 | 修订内容 | 评审人 |
| --- | --- | --- | --- | --- |
| v0.1 | 2026-05-06 | 雨霓 | 初稿，列出基本功能与安全机制需求 | — |
| v0.5 | 2026-05-08 | 雨霓 | 补充审计追踪、跨平台、NFR、验收标准章节 | 架构组（initial） |
| v0.9 | 2026-05-10 | 雨霓 | 评审反馈修订：补充 RTM、META_LOGGING_DIR 设计约束、双层防护规则 | 架构组、QA |
| **v1.0** | **2026-05-11** | **雨霓** | **正式评审通过，进入开发执行阶段** | **架构组 / QA / 平台组** |

> **变更管理说明**：本文档生效后，任何范围变更须走 CR（Change Request）流程，由 Owner 提交、架构组评审、对应 QA Lead 二次确认后方可合入主干。次要文字勘误可由 Owner 直接修订并在本表登记，不需要重新评审。

---

## 目录

1. 引言
2. 产品概述
3. 范围说明
4. 干系人与用户角色
5. 功能需求（Functional Requirements）
6. 非功能需求（Non-Functional Requirements）
7. 系统约束与设计原则
8. 验收标准与 Definition of Done
9. 项目里程碑与交付计划
10. 风险评估与应对
11. 需求追踪矩阵（RTM）
12. 附录

---

# 1. 引言

## 1.1 文档目的

本文档面向 ODPlatform 项目 D2.5 阶段（项目重置工具）开发周期，给出：

- 本期需要交付的**功能边界**（做什么、不做什么）
- 各功能项的**输入、输出、处理逻辑、异常处理**
- **非功能需求**（安全性、性能、可移植性等）
- **验收标准**与**测试覆盖要求**
- **风险与依赖**

本文档是后续设计文档（HLD/LLD）、开发任务拆解、测试用例编写的**唯一权威输入**。开发人员、测试人员、Reviewer 在出现需求理解分歧时，**以本文档为准**。

## 1.2 阅读对象

| 角色 | 阅读重点 |
| --- | --- |
| 产品负责人 / PM | 第 1–4 章（背景、范围、用户场景） |
| 架构师 | 第 5–7 章（功能、非功能、设计约束） |
| 开发工程师 | 第 5–8 章（功能详述、验收标准） |
| 测试工程师 | 第 5、6、8、11 章（功能、NFR、AC、RTM） |
| 运维 / DevOps | 第 6.5、7、9 章（部署、可移植、里程碑） |
| 安全 / 数据治理 | 第 5.5、6.7、10 章（安全机制、风险） |
| 新人 / 后续接手者 | 全文 |

## 1.3 术语与缩略语

| 术语 | 含义 |
| --- | --- |
| ODPlatform | 通用目标检测开发平台（本产品） |
| init_project | D2 阶段交付的项目初始化工具，本期工具的**反向操作**对象 |
| reset_project | 本期交付的项目重置工具 |
| Workspace | 仓库根目录 |
| ROOT_DIR / APP_DIR | 工作区根 / 当前 app 根（继承自 D2） |
| LOGGING_DIR | 端私有运行时日志目录（`APP_DIR / "logging"`，继承自 D2） |
| META_LOGGING_DIR | 元工具日志目录（`APP_DIR / "meta_logging"`，本期新增） |
| Allowlist | 允许清单：明确列出可被删除的目录 |
| Denylist | 禁止清单：兜底列出绝不可删除的目录 |
| Dry-run | 预演模式：仅展示将要执行的操作，不真正执行 |
| Audit Trail | 审计追踪：可回溯的操作记录 |
| Self-reference Bug | 自指 bug：工具运行时引用了自己的运行环境（如日志目录），可能导致工具删除自己的运行依赖 |
| Two-layer Defense | 双层防护：Allowlist + Denylist 的协同防护机制 |
| ADR | 架构决策记录（Architecture Decision Record） |
| RTM | 需求追踪矩阵（Requirements Traceability Matrix） |
| FR / NFR | 功能需求 / 非功能需求 |
| AC | 验收标准（Acceptance Criteria） |
| DoD | 完成定义（Definition of Done） |
| MTTR | 平均故障恢复时间 |
| CR | 变更请求（Change Request） |

## 1.4 参考文档

| 编号 | 文档 | 关系 |
| --- | --- | --- |
| REF-01 | 《ODPlatform 通用工具层与项目初始化系统 PRD》（D2，ODP-PRD-2026-002） | 上游：本期工具是 D2 init_project 的反向操作 |
| REF-02 | 《ODPlatform 目录设计推导讲义》（D1） | 目录架构来源 |
| REF-03 | ADR-001 采用 Monorepo + apps/ 布局 | 架构决策依据 |
| REF-04 | ADR-002 reset_project 双层防护与默认安全设计（本期产出） | 关键决策记录 |
| REF-05 | POSIX `unlink(2)` 与 Windows 文件锁语义 | 跨平台行为差异依据 |
| REF-06 | `git clean(1)` / `terraform plan` / `kubectl --dry-run` 设计参考 | 业界 dry-run 设计惯例 |
| REF-07 | Conventional Commits 1.0.0 | git commit 规范 |
| REF-08 | 公司《Python 开发规范 v3.2》 | 内部编码规范 |
| REF-09 | 公司《数据资产分级与删除规范 v1.5》 | 内部数据治理规范 |
| REF-10 | 公司《代码评审指南 v2.0》 | Code Review 流程 |

---

# 2. 产品概述

## 2.1 产品定位

reset_project 是 ODPlatform 平台的**运维侧工具**，用于安全、可控、可追溯地清理 init_project 创建的运行时产物，使工作区回到接近 `git clone` 后的状态。它是 init_project 的**反向操作**，与 init_project 共同构成 ODPlatform 的"环境生命周期管理"闭环。

## 2.2 业务背景与问题陈述

D2 阶段交付了 init_project 工具，解决了"环境搭建"问题，但"环境清理"仍依赖手工操作，存在以下落地痛点：

1. **手工清理高风险**：开发者需手动执行 `rm -rf` 系列命令，命令拼写错误或路径漏写可能误删 git 目录、原始数据、预训练权重，造成不可逆损失。
2. **清理不彻底**：开发者凭记忆删除，常遗漏部分目录，导致下次 init_project 报"目录已存在"或残留脏数据干扰新一轮实验。
3. **清理无审计**：手工 `rm` 后无任何记录，事故发生时无法回溯"是谁、何时、删了什么"。
4. **CI / 自动化困难**：CI 环境每轮跑前需要清理工作区，但缺少标准化、非交互的清理命令；脚本化 `rm` 方案脆弱、跨平台不一致。
5. **教学场景反复重置成本高**：D2 等课程要求学员"再跑一次 init_project 看效果"，每次都需手工清理；30 人规模下累计耗时显著。
6. **跨平台差异**：手工清理在 Windows（PowerShell `Remove-Item`）与 Linux/macOS（bash `rm`）下命令不同，开发者反复切换易错。

## 2.3 产品目标（Product Goals）

D2.5 阶段需达成下列业务与工程目标：

| 编号 | 目标 | 衡量指标 |
| --- | --- | --- |
| G1 | **默认安全**：误操作概率为零；任何破坏性动作必须经显式确认 | 无显式 `--yes` 参数时**绝不**执行删除 |
| G2 | **双层防护**：白名单 + 黑名单协同，单一防线失效不导致灾难 | Code Review 检查点；恶意构造的目录列表也无法删除受保护目录 |
| G3 | **审计可追溯**：每次执行均落盘可机读的审计记录 | 每次执行生成独立审计日志，含执行者、时间、环境、目标列表、结果 |
| G4 | **CI 友好**：支持完全无人值守的自动化清理 | 单条命令完成清理，退出码标准化 |
| G5 | **跨平台一致**：三端开发体验一致 | Linux / macOS / Windows 三端均通过完整验收用例 |
| G6 | **自指安全**：工具运行不依赖自己的删除目标 | 工具自身的运行日志写入 META_LOGGING_DIR，与业务 LOGGING_DIR 物理隔离 |
| G7 | **进度可见**：长任务可视化反馈，用户不困惑 | 大于 1GiB 的目录给出预警；逐目录进度提示 |

## 2.4 非目标（Non-Goals）

为避免范围蔓延，以下事项**明确不属于** D2.5 阶段交付内容：

- 撤销（undo）已执行的删除 → **不支持**（删除即不可逆，由用户备份兜底）
- 远程 / 网络存储清理（S3、MinIO 等）→ **后续版本**
- 选择性清理（只清某一目录或按时间过滤）→ **V1.1+**
- 清理操作的图形界面 / Web UI → **V1.1+**
- 跨工作区（多仓库）批量清理 → **不在产品范围内**
- 与配置管理系统的联动（如清理后重置配置）→ D3-D4 配置系统稳定后再评估
- 清理后的自动 git 提交 / push → 不做；交由用户决定

## 2.5 产品价值

| 维度 | 价值 |
| --- | --- |
| **安全** | 消除手工 `rm -rf` 误删风险；为团队提供"删除操作的标准答案"，杜绝因路径笔误造成的不可逆事故 |
| **效率** | 单条命令替代多步手工清理；30 人团队累计节省 ≥ 80 工时/季度 |
| **合规** | 审计日志满足公司《数据资产分级与删除规范 v1.5》对"删除操作可追溯"的要求 |
| **CI 集成** | 与 CI 工具开箱即用，加速训练流水线的迭代周期 |
| **工程文化** | 提供"默认安全 + 双层防护 + 审计追踪"的完整范本，可复用到平台其他危险操作工具的设计中 |

---

# 3. 范围说明

## 3.1 本期交付范围（In Scope）

### 3.1.1 代码模块

| 模块 | 路径 | 说明 |
| --- | --- | --- |
| 路径管理扩展 | `apps/platform/src/odp_platform/common/paths.py` | 新增 `get_dirs_to_reset()`、`PROTECTED_DIRS`、`is_protected()`、`META_LOGGING_DIR` |
| 重置 CLI | `apps/platform/src/odp_platform/cli/reset_project.py` | 主入口、参数解析、删除流程、确认机制、进度展示 |
| 审计上下文 | `apps/platform/src/odp_platform/common/audit_utils.py` | `_audit_context()` 采集与序列化 |
| 开发期入口 | `scripts/reset_project.py` | 不依赖 pip install 的开发期调用入口 |

### 3.1.2 工程化产物

| 产物 | 路径 | 说明 |
| --- | --- | --- |
| 子项目配置更新 | `apps/platform/pyproject.toml` | 新增 `odp-reset` console script |
| 工作区配置 | `pyproject.toml` | 无变更（继承 D2） |

### 3.1.3 文档产物

| 产物 | 路径 | 说明 |
| --- | --- | --- |
| 架构决策 | `docs/architecture/ADR-002-reset-safety-design.md` | reset_project 安全设计决策记录 |
| 运维手册 | `docs/ops/reset-project-runbook.md` | 运维操作指引、常见场景示例 |
| 模块 README | `apps/platform/src/odp_platform/cli/README.md` 更新 | 增补 reset 子命令说明 |

### 3.1.4 CLI 命令

- `odp-reset`（pip install 后注册的 console_script）

## 3.2 不在范围内（Out of Scope）

| 事项 | 原因 / 后续计划 |
| --- | --- |
| 撤销 / undo 已删除内容 | 删除是不可逆操作；用户备份与 git 兜底 |
| 选择性 / 部分清理（按目录、按时间） | V1.1+ 视实际需求评估 |
| 清理远程存储 | 后续版本 |
| 图形界面 / Web UI | V1.1+ |
| 与配置管理联动 | 等待 D3-D4 完成 |
| 自动备份功能 | 不在产品定位内；建议用户使用 git 或外部备份方案 |
| 单元测试代码补全（init_project 的 D2 遗留部分）| 与本期同期交付，但作为独立任务跟踪，不计入本 PRD 验收 |

## 3.3 上下游依赖

```
┌──────────────────────────┐
│ D2: init_project + common │  ← 上游输入（已完成）
│ paths.py / logging_utils  │
└─────────────┬────────────┘
              ▼
┌──────────────────────────┐
│ D2.5 (本期)               │
│ reset_project + 审计上下文│
└─────────────┬────────────┘
              ▼
   ┌──────────┴───────────┬─────────────┐
   ▼                      ▼             ▼
┌───────────┐       ┌──────────┐  ┌──────────┐
│ D3-D4     │       │ D5-D9    │  │ V1.1+    │
│ config    │       │ 业务子系统│  │ 多端     │
└───────────┘       └──────────┘  └──────────┘
```

**外部依赖**：

| 依赖 | 类型 | 版本 | 备注 |
| --- | --- | --- | --- |
| Python | 运行时 | ≥ 3.10 | 继承 D2 约束 |
| 标准库 `argparse` | 运行时 | 内置 | CLI 参数解析 |
| 标准库 `shutil` | 运行时 | 内置 | 目录递归删除 |
| 标准库 `pathlib` | 运行时 | 内置 | 路径运算 |
| `colorlog` | 运行时 | ≥ 6.7.0 | 复用 D2 的 logging_utils |

**继承自 D2 的内部依赖**：

| 依赖 | 用途 |
| --- | --- |
| `paths.ROOT_DIR` / `APP_DIR` | 路径锚点 |
| `logging_utils.get_logger` | 日志创建（本期日志写入 META_LOGGING_DIR） |
| `system_utils.get_basic_device_info` | 审计上下文环境快照采集 |
| `string_utils.format_table_row` / `pad_to_width` | 进度与汇总表格输出 |

**开发依赖**：继承 D2，无新增。

---

# 4. 干系人与用户角色

## 4.1 项目干系人（RACI 矩阵简版）

| 干系人 | 职责 | R | A | C | I |
| --- | --- | :-: | :-: | :-: | :-: |
| 产品 Owner（雨霓） | 需求定义、文档维护、范围把控 | ● | ● | | |
| 架构组 | 安全设计评审、ADR-002 审定 | | ● | ● | |
| 开发工程师 | 编码实现 | ● | | ● | |
| QA 工程师 | 测试用例设计、安全场景验收 | ● | | ● | ● |
| 安全 / 数据治理 | 数据删除合规审查 | | | ● | ● |
| Code Reviewer（资深工程师） | 代码评审 | | | ● | |
| 平台 / DevOps | CI 集成支持 | | | ● | ● |
| 终端用户（算法工程师） | 试用反馈 | | | | ● |

> R = Responsible，A = Accountable，C = Consulted，I = Informed

## 4.2 用户角色（User Personas）

### 角色 A：算法工程师（核心用户）

- **背景**：日常进行多轮训练实验，频繁需要清理上一轮实验产物。
- **关注点**：操作简单；不会误删原始数据；执行进度可见。
- **痛点**：手工 `rm -rf` 怕打错路径；不记得上次到底建了哪些目录。

### 角色 B：CI / DevOps 工程师

- **背景**：维护训练流水线，每次新任务前需自动清理工作区。
- **关注点**：完全无人值守；退出码可判定；输出可机读。
- **痛点**：现有清理脚本跨平台不一致；失败时无法快速定位。

### 角色 C：研究员 / 实习生（次要用户）

- **背景**：刚入职，对 Linux 命令不熟悉。
- **关注点**：误操作有兜底；提示清晰；不会一不小心毁了工作区。
- **痛点**：怕用错命令；看到红色错误信息容易慌。

### 角色 D：平台维护者 / 安全审计员

- **背景**：对工具的危险操作行为负责，需要事后审计能力。
- **关注点**：每次执行有可追溯记录；操作者身份与环境可识别；删除范围可还原。
- **痛点**：手工 `rm` 后无任何记录，事故定位困难。

## 4.3 典型使用场景（User Story）

### US-01 算法工程师快速清理实验产物

> **作为**算法工程师，**我希望**在一次实验结束后通过单条命令清理所有运行时产物（runs、checkpoints、logging 等），**以便**立即开始下一轮实验，且不必担心误删原始数据或代码。

**主流程**：

1. `cd ODPlatform`
2. `odp-reset`  ← 默认 dry-run，先看会删什么
3. 确认无误后 `odp-reset --yes`，输入 `RESET` 二次确认
4. 等待删除完成，查看进度与汇总
5. 进入下一轮实验

**预期成果**：清理范围明确、可预览；二次确认杜绝误操作；原始数据与预训练权重不受影响。

### US-02 CI 自动化清理

> **作为** CI 工程师，**我希望**在训练流水线的 setup 阶段以无交互方式清理工作区，**以便**保证每个任务从干净环境开始。

**主流程**：

1. CI 流水线进入 setup 步骤
2. 执行 `odp-reset --yes --force`
3. 检查退出码：0 = 成功，非 0 = 失败并立即终止流水线
4. 进入下一个步骤

**预期成果**：完全无交互；退出码标准化；输出含可解析的成功/失败计数。

### US-03 新人误操作防护

> **作为**入职第一周的研究员，**我希望**即使在不理解命令的情况下随手执行 `odp-reset`，**也不会**对项目造成任何破坏，**以便**安全地学习平台。

**预期成果**：默认 dry-run 不删除任何东西；危险参数 `--yes` 必须显式给出；二次确认需要打字 `RESET`，杜绝惯性回车。

### US-04 安全审计追溯

> **作为**平台安全审计员，**我希望**每次 `odp-reset` 的执行都留下完整记录（执行者、时间、机器、目标列表、结果），**以便**事故发生时可以快速定位责任与影响范围。

**预期成果**：每次执行落盘独立审计日志至 META_LOGGING_DIR；日志含完整上下文；日志文件名含时间戳便于检索。

### US-05 跨平台开发协作

> **作为**使用 Windows 的开发者，**我希望**与 Linux/macOS 同事使用同一条 `odp-reset` 命令，**以便**避免维护两套清理脚本。

**预期成果**：命令在三端表现一致；Windows 只读文件可正常清理；输出格式统一。

---

# 5. 功能需求（Functional Requirements）

## 5.1 需求编号规则

需求编号格式：`FR-<模块代号>-<序号>`

| 模块代号 | 模块 |
| --- | --- |
| PATH | 路径管理扩展（paths.py） |
| CLI | 重置命令行入口（reset_project.py） |
| SAFE | 安全机制（确认、防护、模式） |
| AUDIT | 审计追踪 |
| PKG | 工程化打包 |
| DOC | 文档产物 |

每条需求按以下结构描述：

- **需求 ID** + **优先级**（P0 必须 / P1 重要 / P2 期望）
- **关联用户故事**
- **需求描述**
- **输入 / 输出**
- **处理规则**
- **异常处理**
- **验收标准**

---

## 5.2 路径管理扩展（paths.py）

### FR-PATH-101 待重置目录列表函数 [P0]

- **关联场景**：US-01、US-02
- **需求描述**：在 `paths.py` 提供 `get_dirs_to_reset() -> list[Path]` 函数，返回全部允许被 reset 工具删除的运行时目录列表（白名单）。
- **输出**：`list[Path]`。
- **返回值组成**：仅包含运行时产物目录，**不**包含任何代码、文档、配置、原始数据、预训练权重目录。本期清单：

| 路径常量 | 路径 |
| --- | --- |
| `RUNS_DIR` | `ROOT_DIR / "runs"` |
| `CHECKPOINTS_DIR` | `ROOT_DIR / "models" / "checkpoints"` |
| `LOGGING_DIR` | `APP_DIR / "logging"` |
| `TRAIN_DIR` | `ROOT_DIR / "data" / "train"` |
| `VAL_DIR` | `ROOT_DIR / "data" / "val"` |
| `TEST_DIR` | `ROOT_DIR / "data" / "test"` |

- **设计约束**：
  - 该函数是 reset_project 的**唯一目录数据源**（Single Source of Truth）。
  - 列表内严禁包含 `RAW_DATA_DIR`、`PRETRAINED_MODELS_DIR`、`DOCS_DIR`、`SCRIPTS_DIR`、任何代码目录。
  - 调整白名单仅修改本函数，不修改任何调用方。
- **异常处理**：函数本身不应抛异常；返回值类型严格为 `list[Path]`。
- **验收标准**：
  - AC-1：返回值类型为 `list[Path]`，长度等于 6（本期清单）。
  - AC-2：列表内路径均为 `ROOT_DIR` 或 `APP_DIR` 下的合法子路径。
  - AC-3：列表内**不**包含 `RAW_DATA_DIR`、`PRETRAINED_MODELS_DIR` 及任何 git-tracked 目录。

### FR-PATH-102 受保护目录清单 [P0]

- **关联场景**：US-03、US-04
- **需求描述**：在 `paths.py` 定义 `PROTECTED_DIRS: tuple[Path, ...]` 常量，作为兜底黑名单，列出**绝不允许**被删除的目录。
- **必备条目**：

| 类别 | 条目 |
| --- | --- |
| 工作区根 | `ROOT_DIR` 本身 |
| 版本控制 | `ROOT_DIR / ".git"` |
| 代码 | `ROOT_DIR / "apps"` |
| 工程基础设施 | `ROOT_DIR / "scripts"`、`ROOT_DIR / "docs"` |
| 原始数据 | `ROOT_DIR / "data" / "raw"` |
| 预训练权重 | `ROOT_DIR / "models" / "pretrained"` |
| 工作区标记 | `ROOT_DIR / ".odp-workspace"` |
| 端私有配置 | `APP_DIR / "configs"` |
| 元日志 | `APP_DIR / "meta_logging"` |

- **设计约束**：
  - 该常量为**只读**，禁止运行时修改。
  - 类型为 `tuple` 而非 `list`，强调不可变。
  - 必须涵盖 git-tracked 目录、所有用户高价值数据、工具自身运行依赖。
- **验收标准**：
  - AC-1：常量类型为 `tuple[Path, ...]`。
  - AC-2：上表 9 项全部存在。
  - AC-3：与 `get_dirs_to_reset()` 返回的任意路径**不**重合。

### FR-PATH-103 受保护判定函数 [P0]

- **关联场景**：US-03
- **需求描述**：提供 `is_protected(path: Path) -> bool` 函数，判定给定路径是否属于受保护范围。
- **输入**：`Path` 实例。
- **输出**：`bool`。
- **判定规则**：以下任一条件成立即视为受保护：
  1. `path` 等于 `PROTECTED_DIRS` 中任一条目；
  2. `path` 是 `PROTECTED_DIRS` 中任一条目的**子路径**（使用 `Path.is_relative_to()` 判定）；
  3. `path` 不在 `ROOT_DIR` 之内（防止越界删除工作区外内容）。
- **异常处理**：输入非 `Path` 类型时抛 `TypeError`。
- **验收标准**：
  - AC-1：`is_protected(ROOT_DIR / ".git")` 返回 `True`。
  - AC-2：`is_protected(ROOT_DIR / ".git" / "objects")` 返回 `True`（子路径判定）。
  - AC-3：`is_protected(ROOT_DIR / "data" / "raw" / "dataset_a")` 返回 `True`。
  - AC-4：`is_protected(ROOT_DIR / "runs")` 返回 `False`。
  - AC-5：`is_protected(Path("/tmp/somewhere"))` 返回 `True`（越界保护）。

### FR-PATH-104 元日志目录常量 [P0]

- **关联场景**：US-04
- **需求描述**：在 `paths.py` 新增 `META_LOGGING_DIR` 常量，取值 `APP_DIR / "meta_logging"`，专用于元工具（如 reset_project 本身）日志，与业务日志 `LOGGING_DIR` 物理隔离。
- **设计依据**：
  - reset_project 的删除目标包含 `LOGGING_DIR`；若 reset 自身日志写入 `LOGGING_DIR`，会形成自指——工具一边写日志、一边删自己的日志目录，引发跨平台一致性问题（POSIX 上孤儿 inode、Windows 上文件锁错误）。
  - 引入独立的 `META_LOGGING_DIR` 隔离工具自身日志，从根本上杜绝自指。
- **设计约束**：
  - `META_LOGGING_DIR` 必须列入 `PROTECTED_DIRS`（FR-PATH-102 已涵盖）。
  - `META_LOGGING_DIR` 不得列入 `get_dirs_to_reset()`（FR-PATH-101 已禁止）。
- **验收标准**：
  - AC-1：常量取值等于 `APP_DIR / "meta_logging"`。
  - AC-2：`is_protected(META_LOGGING_DIR)` 返回 `True`。
  - AC-3：`META_LOGGING_DIR` 不在 `get_dirs_to_reset()` 返回值内。

---

## 5.3 重置 CLI 主流程（reset_project.py）

### FR-CLI-001 主入口函数 [P0]

- **关联场景**：US-01、US-02
- **需求描述**：在 `apps/platform/src/odp_platform/cli/reset_project.py` 提供 `main() -> int` 函数，作为 CLI 主入口；解析命令行参数并调度执行流程；返回进程退出码。
- **执行步骤**：
  1. 通过 `argparse` 解析 `sys.argv`，得到 `yes / force / dry_run` 三个布尔参数。
  2. 调用 `reset_project(yes, force, dry_run)` 执行业务流程。
  3. 根据业务执行结果返回退出码（FR-CLI-007）。
- **接口契约**：
  - `main` 必须可作为 `pyproject.toml` 中 `console_scripts` 的入口。
  - `main` 必须能被 `python -m odp_platform.cli.reset_project` 触发。
- **验收标准**：
  - AC-1：`odp-reset --help` 输出参数说明，进程退出码 0。
  - AC-2：`odp-reset` 默认进入 dry-run 模式，不执行删除。
  - AC-3：`odp-reset --yes` 进入交互删除流程。
  - AC-4：`odp-reset --yes --force` 进入无交互删除流程。

### FR-CLI-002 业务函数 [P0]

- **关联场景**：US-01、US-02
- **需求描述**：提供 `reset_project(yes: bool = False, force: bool = False, dry_run: bool = False) -> int` 业务函数，承载实际的删除流程。
- **入参语义**：

| 参数 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `yes` | `bool` | `False` | 是否真正执行删除（默认仅 dry-run） |
| `force` | `bool` | `False` | 是否跳过交互确认（仅在 `yes=True` 时有效） |
| `dry_run` | `bool` | `False` | 显式声明 dry-run；与 `yes` 互斥时优先 |

- **执行步骤**：
  1. 创建工具自身 logger，写入 `META_LOGGING_DIR / "reset_project"`。
  2. 采集审计上下文（FR-AUDIT-001）。
  3. 调用 `paths.get_dirs_to_reset()` 取得删除清单。
  4. 对清单内每一项执行 `is_protected()` 复核（FR-SAFE-002）。
  5. 扫描每个目录，统计文件数与总字节数（FR-CLI-003）。
  6. 输出删除计划表格（FR-CLI-004）。
  7. 决策分支（FR-SAFE-001、FR-SAFE-003）：
     - `dry_run=True` 或 `yes=False`：仅打印计划，结束。
     - `yes=True` 且 `force=False`：进入交互确认（FR-SAFE-003），用户输入 `RESET` 才继续。
     - `yes=True` 且 `force=True`：跳过交互，直接执行。
  8. 对清单内每一项执行删除（FR-CLI-005）。
  9. 输出汇总（FR-CLI-006）。
  10. 返回退出码（FR-CLI-007）。
- **设计约束**：函数必须为**纯函数**——所有参数显式传入，不读取 `sys.argv`、不读取环境变量。便于测试与作为库被其他工具调用。
- **验收标准**：
  - AC-1：函数签名与默认值符合上表。
  - AC-2：可在 Python 解释器中以 `from odp_platform.cli.reset_project import reset_project; reset_project(yes=True, force=True)` 直接调用。
  - AC-3：函数返回值为 `int`，符合 FR-CLI-007 退出码定义。

### FR-CLI-003 目标目录扫描 [P0]

- **关联场景**：US-01
- **需求描述**：删除前对每个目标目录执行扫描，统计文件数与总字节数，用于"删除计划"展示。
- **处理规则**：
  - 仅统计目录内的文件，递归全部子目录。
  - 不存在的目录视为"0 文件 0 字节"，不报错。
  - 字节数采用 1024 进制（KiB / MiB / GiB），由 `system_utils._format_size` 格式化。
- **异常处理**：扫描过程中遇到权限错误或符号链接异常，记录 WARNING 但不中断流程（视为未知大小，标注 `?`）。
- **验收标准**：
  - AC-1：扫描结果与目录实际文件数一致（误差 < 1%，因符号链接等）。
  - AC-2：不存在目录返回 (0, 0)。
  - AC-3：单个目录大于 1GiB 时，扫描耗时 ≤ 5 秒（NFR-PERF 联动）。

### FR-CLI-004 删除计划展示 [P0]

- **关联场景**：US-01、US-03
- **需求描述**：扫描完成后输出表格化的"删除计划"，包含每个目录的相对路径、文件数、字节数，以及合计行。
- **格式要求**：
  - 使用 `string_utils.format_table_row` 与 `format_table_separator` 输出，列宽固定。
  - 表头分两段：dry-run 时为 `📋 [DRY-RUN] 计划如下（未实际删除）`；真实执行前为 `⚠️ 即将删除以下目录`。
  - 表格下方明确列出**不会被触碰**的目录（`data/raw/`、`models/pretrained/`、所有 git-tracked 目录）。
- **验收标准**：
  - AC-1：表格各列对齐（含 CJK 字符），与 D2 风格一致。
  - AC-2：dry-run 表头与真实执行表头明显区分（图标与措辞）。
  - AC-3：合计行准确反映清单内全部目录的总文件数与总字节数。

### FR-CLI-005 实际删除执行 [P0]

- **关联场景**：US-01、US-02
- **需求描述**：对清单内每个目录执行 `shutil.rmtree`，并按顺序输出进度。
- **处理规则**：
  - 删除前打印 `[i/N] 删除 <relative_path> (<size>, <count> 个文件)`。
  - 大于 1GiB 的目录额外打印 `——这可能需要一会...`（WARNING 级）。
  - 删除成功打印 `[i/N] ✅ 已删除: <relative_path>`。
  - 删除失败打印 `[i/N] ❌ 删除失败 <relative_path>: <error>`，**不**中断后续目录的删除（best-effort）。
  - 使用 `shutil.rmtree(path, onerror=_on_rm_error)`；`_on_rm_error` 处理 Windows 只读文件（chmod +w 后重试一次）。
- **异常处理**：单个目录删除失败时记录 ERROR 日志，加入失败列表，继续处理下一个目录。
- **验收标准**：
  - AC-1：进度输出顺序与 `get_dirs_to_reset()` 顺序一致。
  - AC-2：单个目录失败不影响其他目录的删除。
  - AC-3：Windows 上含只读文件的目录可正常删除（onerror 回调生效）。

### FR-CLI-006 执行汇总 [P0]

- **关联场景**：US-01、US-02、US-04
- **需求描述**：删除流程结束后输出汇总信息：成功数、失败数、失败明细。
- **输出内容**：
  ```
  ======================================================================
  完成: 成功 N 个,失败 M 个
    - <relative_path>: <error_message>   （仅 M > 0 时列出）
  ```
- **验收标准**：
  - AC-1：成功 / 失败计数与实际操作一致。
  - AC-2：失败明细按"路径: 错误信息"格式逐行列出。

### FR-CLI-007 退出码规范 [P0]

- **关联场景**：US-02
- **需求描述**：进程退出码必须按下表标准化，便于 CI 等自动化场景判定。

| 场景 | 退出码 |
| --- | --- |
| dry-run 完成（默认或显式 `--dry-run`） | 0 |
| 用户取消确认（输入非 `RESET`） | 0 |
| 真实删除全部成功 | 0 |
| 真实删除部分失败 | 1 |
| 真实删除全部失败 | 2 |
| 参数错误（argparse 报错） | 2（argparse 默认） |
| 未捕获异常 | 1 |

- **验收标准**：
  - AC-1：表内场景在 bash 中通过 `echo $?` 检查均符合。
  - AC-2：CI 配置中 `failure_threshold=1` 可正确捕获部分失败场景。

---

## 5.4 命令行参数与模式

### FR-CLI-008 命令行参数定义 [P0]

- **关联场景**：US-01、US-02
- **需求描述**：通过 `argparse` 提供以下命令行参数。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--yes` | flag | False | 真正执行删除（默认是 dry-run） |
| `--force` | flag | False | 跳过交互式确认（仅当 `--yes` 时有效） |
| `--dry-run` | flag | False | 显式声明 dry-run（默认行为也是 dry-run，但显式更可读） |
| `-h` / `--help` | flag | — | 输出参数说明 |

- **设计约束**：
  - **不**提供 `--no-yes`、`--non-interactive` 等冗余别名，避免歧义。
  - 帮助信息（`--help`）须明确写出"默认 dry-run，必须 `--yes` 才删除"。
- **验收标准**：
  - AC-1：`odp-reset --help` 输出含上述全部参数与默认行为说明。
  - AC-2：未知参数报错并退出码 2。

### FR-CLI-009 参数冲突处理 [P1]

- **关联场景**：US-03
- **需求描述**：当 `--dry-run` 与 `--yes` 同时给出时，**以 `--dry-run` 为准**（更安全），并在日志中给出 WARNING 提示。
- **处理规则**：
  - 检测到冲突时打印 `⚠️ 同时给了 --dry-run 和 --yes，以 --dry-run 为准（只打印不删除）`。
  - **不**因冲突而退出；继续执行 dry-run 流程。
- **验收标准**：
  - AC-1：`odp-reset --dry-run --yes` 输出 WARNING 后仅执行 dry-run，退出码 0。
  - AC-2：`--force` 与 `--dry-run` 同时给出时，`--force` 被忽略（force 仅对真实删除有效）。

### FR-CLI-010 三种调用方式并存 [P1]

| 方式 | 命令 | 适用场景 |
| --- | --- | --- |
| 1. Console script | `odp-reset` | 安装后；推荐生产 |
| 2. 模块路径 | `python -m odp_platform.cli.reset_project` | 已安装；临时调试 |
| 3. 仓库根脚本 | `python scripts/reset_project.py` | 未安装；开发期、CI |

- **验收标准**：三种方式产出相同（仅日志路径绝对值差异）。

### FR-CLI-011 开发期入口脚本 [P1]

- **关联场景**：US-02
- **需求描述**：在 `scripts/reset_project.py` 提供开发期入口，使开发者**无需** `pip install` 即可运行。
- **实现要点**：
  - 通过 `Path(__file__).resolve().parent.parent` 定位仓库根。
  - 将 `apps/platform/src` 注入 `sys.path[0]`。
  - **必须**导入 `main`，调用 `sys.exit(main())`，**不得**调用 `reset_project()`（业务函数），否则将绕过 argparse，导致命令行参数失效。
- **设计约束**：入口脚本保持极薄（不超过 12 行有效代码），仅做路径注入与转发，不写任何业务逻辑。
- **验收标准**：
  - AC-1：未安装包的全新环境下，`python scripts/reset_project.py --yes --force` 能正常执行删除流程。
  - AC-2：脚本正确转发命令行参数，`--yes` 等 flag 在业务流程中生效。

---

## 5.5 安全机制

### FR-SAFE-001 默认安全（Safe by Default）[P0]

- **关联场景**：US-01、US-03
- **需求描述**：在用户未显式给出 `--yes` 时，工具**绝不**执行任何删除操作；默认行为为 dry-run（仅扫描与展示计划）。
- **设计依据**：参考 `git clean -n`、`terraform plan`、`kubectl --dry-run` 等业界惯例；任何破坏性工具的默认行为应是只读 / 预演。
- **验收标准**：
  - AC-1：`odp-reset` 不带任何参数时，目录全部保留。
  - AC-2：dry-run 完成后，文件系统状态与执行前完全一致。
  - AC-3：dry-run 输出末尾必须包含提示 `💡 这是 dry-run（默认行为）。要真正执行删除，请加 --yes:`。

### FR-SAFE-002 双层防护（Two-layer Defense）[P0]

- **关联场景**：US-03、US-04
- **需求描述**：删除流程必须执行**两层独立防护**校验，任一层失效不导致灾难。
- **第一层（Allowlist）**：删除清单仅来自 `paths.get_dirs_to_reset()`。
- **第二层（Denylist）**：对清单内每一项**再次**调用 `paths.is_protected()` 复核；若返回 `True`，立即中止整个流程并报错（不仅仅是跳过该项）。
- **设计依据**：假设第一层（白名单）因人为误操作或代码 bug 引入了受保护目录，第二层（黑名单）必须能拦截。"安全应当显式，而非推断"（safety should be explicit, not inferred）。
- **异常处理**：第二层校验失败必须以非零退出码终止，错误日志须明确指出"哪个路径触发了哪条保护规则"。
- **验收标准**：
  - AC-1：模拟在 `get_dirs_to_reset()` 中混入 `ROOT_DIR / ".git"`，运行 `odp-reset --yes --force` 必须立即中止，退出码 ≥ 1。
  - AC-2：错误日志包含被拦截的路径与"触发了 PROTECTED_DIRS 校验"的明确说明。
  - AC-3：第二层拦截发生时，**任何**目录均未被删除（fail-fast，不允许部分删除）。

### FR-SAFE-003 交互式二次确认 [P0]

- **关联场景**：US-01、US-03
- **需求描述**：在 `--yes` 模式且 `--force` 未给出时，必须进入交互式确认；用户须**精确输入大写** `RESET` 才继续，其他任何输入（含小写 `reset`、空字符串、`y` / `yes`）均视为取消。
- **格式要求**：
  - 提示信息使用**裸 `print`**，与彩色 logger 风格**刻意不一致**——用风格硬切打断用户的"扫日志惯性"，强制注意力切换为"主动决策"模式。
  - 提示文本必须包含：将要删除的目录数量、不可撤销提示、精确输入要求。
- **示例提示**：
  ```
  ======================================================================
  ⚠️  你正要删除 N 个目录的内容。这个操作不可撤销。
  ⚠️  如果确认,请精确输入大写的 'RESET'(其他任何输入都会取消):
  ======================================================================
  > 
  ```
- **取消行为**：用户取消时，输出 `❌ 用户取消,未执行删除`（WARNING 级），退出码 0。
- **异常处理**：用户在确认提示阶段触发 `Ctrl+C`（KeyboardInterrupt），视为取消，输出取消信息后退出码 0。
- **验收标准**：
  - AC-1：输入 `RESET` 进入删除流程。
  - AC-2：输入 `reset` / `yes` / `y` / 空字符串均视为取消。
  - AC-3：`Ctrl+C` 视为取消，无 traceback 暴露。
  - AC-4：取消后文件系统状态未变。

### FR-SAFE-004 force 模式跳过交互 [P0]

- **关联场景**：US-02
- **需求描述**：`--yes --force` 同时给出时跳过 FR-SAFE-003 的交互确认，直接进入删除流程。
- **设计意图**：CI / 自动化场景需要无人值守。
- **设计约束**：
  - `--force` **不能**单独使用；单独 `--force`（无 `--yes`）等同于无任何破坏性参数，仍走 dry-run。
  - 帮助信息必须明确说明 `--force` 仅在 `--yes` 同时给出时生效。
- **验收标准**：
  - AC-1：`odp-reset --force`（无 `--yes`）进入 dry-run，不删除。
  - AC-2：`odp-reset --yes --force` 跳过提示直接删除。

### FR-SAFE-005 部分删除策略 [P0]

- **关联场景**：US-02、US-04
- **需求描述**：明确两种"删除中失败"的处理策略：
  - **第二层防护拦截**（FR-SAFE-002）：fail-fast，整体中止，**任何目录都不删**。
  - **执行期 IO 失败**（如权限不足、文件被占用）：best-effort，单目录失败不中断后续，最终汇总报告。
- **设计依据**：
  - 第二层防护拦截属于"配置错误"，部分执行会留下"模糊状态"——必须停止；
  - 执行期 IO 失败属于"环境问题"，跳过失败的目录、完成可完成的部分，是 CI 友好的常见做法（参考 `rm -f`、`make -k`）。
- **验收标准**：
  - AC-1：模拟某目录权限拒绝，其他目录仍能删除完成；汇总报告中失败目录单独列出。
  - AC-2：FR-SAFE-002 触发时，文件系统未发生任何写操作。

---

## 5.6 进度反馈与展示

### FR-CLI-012 大目录预警 [P1]

- **关联场景**：US-01
- **需求描述**：删除单个目录前，若其总字节数 ≥ 1GiB，必须以 WARNING 级输出 `——这可能需要一会...` 提示。
- **目的**：消除用户在长任务时的"是不是卡死了"焦虑。
- **验收标准**：
  - AC-1：`runs/` 含 ≥ 2GiB 测试数据时，删除前出现 WARNING 提示。
  - AC-2：≤ 1GiB 的目录无该提示。

### FR-CLI-013 逐目录进度计数 [P1]

- **关联场景**：US-01
- **需求描述**：每个目录的删除前后输出 `[i/N]` 计数前缀（i 为当前序号，N 为清单总数）。
- **验收标准**：
  - AC-1：6 个目录的清单输出 `[1/6]` 至 `[6/6]`，无重复无跳号。

### FR-CLI-014 dry-run 与真实执行的视觉区分 [P1]

- **关联场景**：US-01、US-03
- **需求描述**：dry-run 与真实执行的输出必须有明显视觉差异，避免误判。
- **格式要求**：
  - dry-run 表头：`📋 [DRY-RUN] 计划如下（未实际删除）`。
  - 真实执行表头：`⚠️ 即将删除以下目录`。
  - dry-run 末尾必须有"如何真正执行"的提示行（含完整命令示例）。
- **验收标准**：
  - AC-1：肉眼对比两种输出可在 1 秒内区分。

---

## 5.7 日志与审计

### FR-AUDIT-001 审计上下文采集 [P0]

- **关联场景**：US-04
- **需求描述**：在 `apps/platform/src/odp_platform/common/audit_utils.py` 提供 `_audit_context() -> dict` 函数，每次执行时采集并返回结构化的审计上下文字典。
- **采集字段**：

| 字段 | 来源 |
| --- | --- |
| `timestamp` | UTC 时间，ISO 8601 格式 |
| `tool_name` | 固定 `"reset_project"` |
| `tool_version` | 从 `odp_platform._version.__version__` 读取 |
| `user` | `getpass.getuser()`（失败时降级 `"unknown"`） |
| `hostname` | `socket.gethostname()` |
| `cwd` | `Path.cwd()` 字符串形式 |
| `root_dir` | `paths.ROOT_DIR` 字符串形式 |
| `argv` | `sys.argv` 列表 |
| `os_info` | 操作系统名与版本 |
| `python_version` | Python 版本 |
| `git_commit` | 当前 HEAD commit hash（失败时 `"unknown"`） |

- **依赖处理**：
  - `git_commit` 通过 `subprocess.run(["git", "rev-parse", "HEAD"])` 采集；环境无 git 时降级为 `"unknown"`，**不**抛异常。
  - 复用 D2 的 `system_utils.get_basic_device_info` 的部分输出，避免重复采集。
- **设计约束**：
  - 函数命名为 `_audit_context`（前缀下划线表示模块内部 helper），但通过 reset_project.py 的统一序列化入口对外暴露内容。
  - 函数本身**不**写任何文件；仅返回 dict。
- **验收标准**：
  - AC-1：返回 dict 包含上表全部字段。
  - AC-2：`git_commit` 在无 git 环境下为 `"unknown"`，函数不抛异常。
  - AC-3：函数耗时 ≤ 500ms（NFR-PERF 联动）。

### FR-AUDIT-002 审计日志落盘 [P0]

- **关联场景**：US-04
- **需求描述**：每次 `reset_project` 执行（含 dry-run）必须在 `META_LOGGING_DIR / "reset_project"` 下落盘一份独立审计日志。
- **格式要求**：
  - 日志文件命名：`reset-project_<YYYYMMDD-HHMMSS-fff>_<pid>.log`。
  - 日志内容含两段：
    1. **审计上下文**（FR-AUDIT-001 的 dict，JSON 序列化，单独一行带 `[AUDIT]` 前缀）；
    2. **运行记录**（标准 logger 输出，含每个目录的扫描、决策、删除结果）。
  - 文件编码 UTF-8，不含 ANSI 颜色码。
- **设计约束**：
  - 日志文件路径**绝不**位于 `LOGGING_DIR` 内（受 FR-PATH-104 保证）。
  - 日志文件保留时长由运维侧规范决定，本期不实现自动轮转（参考 D2 NFR-OBS-003）。
- **验收标准**：
  - AC-1：每次执行生成独立日志文件，文件名时间戳与 PID 唯一。
  - AC-2：日志首行包含 `[AUDIT]` 前缀的 JSON 上下文。
  - AC-3：日志可机读（grep / jq 友好）。
  - AC-4：删除流程中即使 `LOGGING_DIR` 被删，本审计日志保持完整可读。

### FR-AUDIT-003 logger 隔离 [P0]

- **关联场景**：US-04
- **需求描述**：reset_project 的 logger **必须**通过 `get_logger(base_path=META_LOGGING_DIR, log_type="reset_project", ...)` 创建；**禁止**使用 `LOGGING_DIR`。
- **设计依据**：见 FR-PATH-104。
- **验收标准**：Code Review 检查 `cli/reset_project.py` 内所有 `get_logger` 调用，`base_path` 参数必须为 `META_LOGGING_DIR`。

---

## 5.8 跨平台支持

### FR-CLI-015 Windows 只读文件处理 [P0]

- **关联场景**：US-05
- **需求描述**：`shutil.rmtree` 在 Windows 上遇到只读文件会抛 `PermissionError`；本工具必须通过 `onerror` 回调处理：尝试 `os.chmod(path, stat.S_IWRITE)` 后重试一次，仍失败则记录 ERROR。
- **实现要点**：
  - 提供 `_on_rm_error(func, path, exc_info)` 回调函数。
  - 仅对 `PermissionError` 与 Windows `WinError 5`（拒绝访问）尝试 chmod；其他错误直接传播。
- **验收标准**：
  - AC-1：在 Windows 上构造含只读文件的目录，`odp-reset --yes --force` 可正常删除。
  - AC-2：在 Linux/macOS 上回调路径不被触发（无负面影响）。

### FR-CLI-016 跨平台路径输出 [P1]

- **关联场景**：US-05
- **需求描述**：所有日志中的路径输出使用 `Path.relative_to(ROOT_DIR)` 转换为相对路径；分隔符跟随平台原生格式（Windows `\`、POSIX `/`），不强制统一。
- **理由**：跟随平台原生格式更符合用户在该平台的复制粘贴习惯。
- **验收标准**：在三端日志中路径分隔符均为该平台原生格式。

### FR-CLI-017 终端编码兼容 [P1]

- **关联场景**：US-05
- **需求描述**：所有控制台输出（含 emoji 与 CJK 字符）必须在以下终端正常显示：
  - Linux：bash / zsh
  - macOS：zsh / bash
  - Windows：PowerShell 7+ / Windows Terminal / Git Bash
- **实现约束**：
  - 不依赖任何 ANSI 高级序列（仅基础颜色码，由 colorlog 处理跨平台兼容）。
  - 不输出 BOM。
- **验收标准**：三端 emoji（✅ ❌ ⚠️ 📋 💡）均能渲染。

---

## 5.9 工程化打包扩展

### FR-PKG-101 console_script 注册 [P0]

- **关联场景**：US-01
- **需求描述**：在 `apps/platform/pyproject.toml` 的 `[project.scripts]` 段注册 `odp-reset`：

```toml
[project.scripts]
odp-init = "odp_platform.cli.init_project:initialize_project"
odp-reset = "odp_platform.cli.reset_project:main"
```

- **设计约束**：入口必须指向 `main`（CLI 入口），**不得**指向 `reset_project`（业务函数），否则会绕过 argparse。
- **验收标准**：
  - AC-1：`pip install -e ./apps/platform` 后，`odp-reset` 命令可在 PATH 中找到。
  - AC-2：`odp-reset --help` 输出参数说明。
  - AC-3：`which odp-reset` / `where odp-reset`（Windows）能定位到入口脚本。

### FR-PKG-102 依赖声明 [P1]

- **关联场景**：—
- **需求描述**：本期不引入任何新业务依赖；`pyproject.toml` 的 `dependencies` 段无新增条目。
- **理由**：reset 工具仅使用标准库（argparse / shutil / pathlib / stat / os）+ 已有的 colorlog。
- **验收标准**：`pyproject.toml` `dependencies` 段与 D2 完成时一致。

---

## 5.10 文档产物

### FR-DOC-101 ADR-002 安全设计决策记录 [P0]

- **路径**：`docs/architecture/ADR-002-reset-safety-design.md`
- **必备章节**：状态、决策日期、背景（手工 `rm` 的痛点）、备选方案（仅 dry-run / 仅黑名单 / 双层防护）、决定（双层防护 + 默认 dry-run + 二次确认）、理由、后果（正面 / 负面 / 中性）、撤销条件、参考资料（业界 dry-run 设计）。
- **设计意图**：保留"为什么这样设计"的化石记录，避免后续接手者削弱安全机制。

### FR-DOC-102 运维手册 [P0]

- **路径**：`docs/ops/reset-project-runbook.md`
- **必备章节**：
  - 工具用途与适用场景
  - 三种调用方式（console script / 模块路径 / 开发期入口）
  - 命令参数详细说明
  - 常见使用场景（首次清理、CI 集成、紧急恢复）
  - 审计日志查阅方法
  - 故障排查（常见错误与处置）
- **目标读者**：算法工程师、CI 工程师、运维。

### FR-DOC-103 CLI 模块 README 更新 [P1]

- **路径**：`apps/platform/src/odp_platform/cli/README.md`
- **更新内容**：在原 init_project 说明下增补 reset_project 子命令简介与参考链接（指向 ADR-002 与运维手册）。

### FR-DOC-104 Conventional Commits 规范 [P1]

- **要求**：本期所有 git commit 必须符合 Conventional Commits 1.0.0 规范，前缀使用 `feat`、`fix`、`chore`、`refactor`、`docs`、`test`、`style`。
- **目标 commit 数**：约 5–7 次（参见 9.1 节里程碑）。
- **commit message body**：对引入新概念或重要决策的 commit，body 须解释"为什么这么做"；对带有已知 bug 的中间版本，body 须显式标注 `KNOWN ISSUE` 段。

---

# 6. 非功能需求（Non-Functional Requirements）

## 6.1 性能需求（Performance）

| 编号 | 需求 | 指标 | 测量方法 |
| --- | --- | --- | --- |
| NFR-PERF-001 | dry-run 全流程总耗时（不含目录扫描） | ≤ 500 毫秒 | `@time_it` |
| NFR-PERF-002 | 目录扫描耗时（单目录 ≤ 5GiB） | ≤ 5 秒 | `@time_it` |
| NFR-PERF-003 | 实际删除耗时（5GiB 数据） | ≤ 90 秒（typical SSD） | 手工计时 + 日志 |
| NFR-PERF-004 | 审计上下文采集耗时 | ≤ 500 毫秒 | pytest benchmark |
| NFR-PERF-005 | logger 首次创建耗时 | ≤ 200 毫秒 | pytest benchmark |

> typical 硬件参考：Intel i5 / AMD Ryzen 5 同档 CPU，16GB 内存，SSD 存储。

## 6.2 可移植性（Portability）

| 编号 | 需求 |
| --- | --- |
| NFR-PORT-001 | 支持 Linux（Ubuntu 20.04+ / CentOS 7+）、macOS（12+）、Windows 10/11 |
| NFR-PORT-002 | 所有路径运算必须使用 `pathlib.Path`，禁止裸字符串拼接路径 |
| NFR-PORT-003 | 文件编码统一为 UTF-8；不依赖系统默认编码 |
| NFR-PORT-004 | 不依赖任何特定 shell 内置命令；不调用 `rm` / `Remove-Item` 等 shell 命令完成删除 |
| NFR-PORT-005 | 终端彩色输出与 emoji 在 Windows 10+ 默认终端、Windows Terminal、PowerShell 7+、macOS Terminal、Linux 主流终端均可正常显示 |

## 6.3 可维护性（Maintainability）

| 编号 | 需求 |
| --- | --- |
| NFR-MAINT-001 | 所有公共函数必须有 docstring，含 Args / Returns / Raises 三段（如适用） |
| NFR-MAINT-002 | 类型标注覆盖率 100%（公共函数签名） |
| NFR-MAINT-003 | 单文件代码行数 ≤ 500 行；超出须拆分 |
| NFR-MAINT-004 | 单函数行数 ≤ 60 行；超出须拆分 |
| NFR-MAINT-005 | 圈复杂度 ≤ 10（ruff `C901`） |
| NFR-MAINT-006 | 入口脚本（`scripts/reset_project.py`）保持极薄，不写业务逻辑 |
| NFR-MAINT-007 | 重要安全设计决策须有 ADR；任何对默认安全机制的弱化（如默认改为非 dry-run）必须经架构组评审 |

## 6.4 可扩展性（Scalability / Extensibility）

| 编号 | 需求 |
| --- | --- |
| NFR-EXT-001 | 调整删除范围仅需修改 `paths.get_dirs_to_reset()` 一个函数 |
| NFR-EXT-002 | 调整保护清单仅需修改 `paths.PROTECTED_DIRS` 一个常量 |
| NFR-EXT-003 | `_audit_context` 设计支持未来增加新字段而不破坏旧日志兼容性 |
| NFR-EXT-004 | reset_project 业务函数（FR-CLI-002）可作为库被其他工具调用，不依赖 CLI 上下文 |

## 6.5 可测试性（Testability）

| 编号 | 需求 |
| --- | --- |
| NFR-TEST-001 | 所有 cli 与 audit_utils 模块单元测试覆盖率 ≥ 80%（核心路径 100%） |
| NFR-TEST-002 | `reset_project` 业务函数为纯函数（参数显式传入），便于参数化测试 |
| NFR-TEST-003 | 二次确认的输入流可通过 stdin 注入，便于自动化测试 |
| NFR-TEST-004 | 删除流程关键步骤（扫描、决策、执行、汇总）可分别测试 |
| NFR-TEST-005 | 必须提供针对"双层防护"的强对抗测试用例（人为构造非法清单，验证拦截行为） |

## 6.6 兼容性（Compatibility）

| 编号 | 需求 |
| --- | --- |
| NFR-COMPAT-001 | Python 版本：≥ 3.10，≤ 3.12 |
| NFR-COMPAT-002 | 与 D2 已交付的 paths.py / logging_utils 完全兼容；本期对 paths.py 仅做"新增"，不修改原有常量 |
| NFR-COMPAT-003 | 与未来引入的 CI 工具（GitHub Actions / GitLab CI）兼容（退出码标准化） |

## 6.7 安全性（Security）

| 编号 | 需求 |
| --- | --- |
| NFR-SEC-001 | 默认行为为 dry-run，确保用户不会意外触发破坏性操作 |
| NFR-SEC-002 | 双层防护机制不可被命令行参数绕过（即不存在 `--unsafe` / `--skip-protection` 等开关） |
| NFR-SEC-003 | 不输出敏感信息到日志（如 API key、密码、token、家目录绝对路径中的用户名脱敏可选） |
| NFR-SEC-004 | 审计日志写入路径受 PROTECTED_DIRS 保护，工具自身无法删除审计记录 |
| NFR-SEC-005 | 不引入已知 CVE 的依赖版本 |

## 6.8 可观测性（Observability）

| 编号 | 需求 |
| --- | --- |
| NFR-OBS-001 | 所有关键决策点（dry-run 决策、双层防护拦截、用户取消、删除失败）必须有结构化日志 |
| NFR-OBS-002 | 审计日志文件命名包含时间戳与 PID，便于按时间归档与并发场景区分 |
| NFR-OBS-003 | 审计日志须保留至少 90 天（运维侧规范，长于业务日志的 30 天） |
| NFR-OBS-004 | 退出码与日志末尾汇总信息必须一致，便于上游脚本同时通过任一方式判定结果 |

## 6.9 文档质量（Documentation）

| 编号 | 需求 |
| --- | --- |
| NFR-DOC-001 | 每个公共模块开头有 `@FileName` / `@Function` 注释块（继承 D2 规范） |
| NFR-DOC-002 | ADR-002 完整覆盖安全设计决策的备选方案与权衡 |
| NFR-DOC-003 | 运维手册含至少 3 个完整使用场景示例（含命令、预期输出、故障处置） |
| NFR-DOC-004 | `git log` 自解释（每次 commit 均可单独阅读理解） |

---

# 7. 系统约束与设计原则

## 7.1 技术栈约束

| 项 | 选型 | 理由 |
| --- | --- | --- |
| 语言 | Python 3.10+ | 继承 D2，语法特性一致 |
| CLI 框架 | 标准库 `argparse` | 标准库优先；本期参数简单，无需 click / typer |
| 文件操作 | 标准库 `shutil` + `pathlib` | 标准库优先；跨平台一致 |
| 日志 | 复用 D2 `logging_utils` | 不重复造轮子 |
| 审计上下文序列化 | 标准库 `json` | 机读友好；零依赖 |

## 7.2 设计原则

| 原则 | 含义 |
| --- | --- |
| **Safe by default** | 默认行为是只读 / 预演；破坏性操作必须显式确认 |
| **Two-layer defense** | 安全机制必须分层独立，单一防线失效不导致灾难 |
| **Explicit over implicit** | 安全规则必须显式写明（如 PROTECTED_DIRS 列出每一项），不通过启发式推断 |
| **Single Source of Truth** | 删除范围只在 `get_dirs_to_reset()` 定义；保护范围只在 `PROTECTED_DIRS` 定义 |
| **Fail-fast for ambiguity** | 安全防护被触发时立即中止，禁止部分执行 |
| **Best-effort for IO errors** | 执行期 IO 失败时尽可能完成可完成的部分，并完整报告失败 |
| **Audit before action** | 审计上下文采集发生在任何破坏性动作之前 |
| **No self-reference** | 工具运行不依赖自己的删除目标（META_LOGGING_DIR 隔离） |
| **Visual interrupt for irreversible** | 不可逆操作的确认提示必须在视觉上突兀，打断用户的扫读惯性 |

## 7.3 编码规范

继承公司《Python 开发规范 v3.2》（REF-08）与 D2 的编码约定，本期重点强调：

| 规则 | 要求 |
| --- | --- |
| 命名 | 模块 / 函数 snake_case；常量 UPPER_SNAKE_CASE |
| Import 顺序 | 标准库 → 第三方 → 本地（ruff isort 自动） |
| 路径操作 | 仅使用 `pathlib.Path` |
| 异常处理 | 不裸 catch `except:`；`except Exception` 仅在边界层使用 |
| Magic Number | 避免；提取为常量（如 `LARGE_DIR_THRESHOLD = 1 * 1024**3`） |
| 注释语言 | 中文 / 英文均可，单文件内保持一致 |

## 7.4 git 提交规范

- 遵循 Conventional Commits 1.0.0。
- 每次 commit 限定为一个"完整的、可工作的状态"。
- commit message body 必须解释"为什么"；对带有已知 bug 的中间版本，必须显式标注 `KNOWN ISSUE` 段（含影响范围、平台差异、修复计划）。

## 7.5 依赖管理原则

- 本期不新增业务依赖。
- 引入新依赖前评估"30 行标准库代码可否替代"。

---

# 8. 验收标准与 Definition of Done

## 8.1 总体验收准则

本期交付通过 = 同时满足以下全部条件：

1. **功能完整**：第 5 章所有 P0 需求 100% 实现并通过 AC；P1 需求 ≥ 90%；P2 需求 ≥ 50%。
2. **NFR 达标**：第 6 章所有指标可测量验证，无 P0 NFR 项不达标；尤其是 NFR-SEC 全部满足。
3. **代码质量**：ruff 与 mypy 在工作区根执行均无 error；warning 数量 ≤ 5 且经 Code Reviewer 评估可接受。
4. **文档齐备**：5.10 节列出的文档产物全部交付；ADR-002 经架构组签字。
5. **跨平台验证**：在 Linux、macOS、Windows 至少各 1 台机器上完整跑通验收用例。
6. **安全场景全覆盖**：8.2 节 AT-101 至 AT-107 七项安全验收用例全部通过。
7. **Code Review 通过**：至少 1 位资深工程师 + 1 位安全 / 数据治理代表签字。

## 8.2 关键验收用例（Acceptance Test Cases）

### AT-101 默认 dry-run（覆盖 G1、FR-SAFE-001、US-03）

```bash
# 步骤
cd ODPlatform
mkdir -p runs/exp_test && touch runs/exp_test/checkpoint.pt
odp-reset
ls runs/exp_test/checkpoint.pt    # 应仍存在
```

**通过标准**：
- 控制台输出 `📋 [DRY-RUN] 计划如下（未实际删除）` 表头
- 文件系统状态完全未变
- 末尾输出 `💡 这是 dry-run...` 提示

### AT-102 双层防护拦截（覆盖 G2、FR-SAFE-002）

构造测试代码注入：模拟 `get_dirs_to_reset()` 返回值含 `ROOT_DIR / ".git"`，运行 `odp-reset --yes --force`。

**通过标准**：
- 进程立即退出，退出码 ≥ 1
- ERROR 日志包含被拦截的路径与"触发了 PROTECTED_DIRS 校验"说明
- 文件系统未发生任何写操作（`.git` 目录完整保留）

### AT-103 二次确认机制（覆盖 FR-SAFE-003、US-03）

```bash
echo "yes" | odp-reset --yes        # 小写 yes，应取消
echo "RESET" | odp-reset --yes      # 精确大写，应执行
```

**通过标准**：
- 第一次：未删除，退出码 0，输出 `❌ 用户取消`
- 第二次：进入删除流程

### AT-104 force 模式（覆盖 FR-SAFE-004、US-02）

```bash
odp-reset --yes --force
```

**通过标准**：无任何交互提示，直接进入删除流程，CI 友好。

### AT-105 审计日志落盘（覆盖 G3、FR-AUDIT-002、US-04）

```bash
odp-reset
ls apps/platform/meta_logging/reset_project/   # 应至少 1 个新文件
cat apps/platform/meta_logging/reset_project/reset-project_*.log | head -1
# 首行应含 [AUDIT] 前缀的 JSON 上下文
```

**通过标准**：
- 文件存在
- 首行 JSON 含全部 FR-AUDIT-001 字段
- 即使 dry-run 也生成审计日志

### AT-106 跨平台一致性（覆盖 NFR-PORT、US-05）

在三种 OS 上分别执行 AT-101、AT-103、AT-104：
- Ubuntu 22.04（bash）
- macOS 14（zsh）
- Windows 11（PowerShell + Git Bash）

**通过标准**：三端行为一致；输出仅时间戳、绝对路径、路径分隔符不同；Windows 含只读文件目录可正常删除。

### AT-107 退出码规范（覆盖 FR-CLI-007、US-02）

```bash
odp-reset; echo $?                          # 0
odp-reset --yes; echo "y" | xargs ...       # 用户取消，0
odp-reset --yes --force; echo $?            # 全部成功 0；部分失败 1；全部失败 2
odp-reset --invalid-flag; echo $?           # 2（argparse 报错）
```

**通过标准**：所有场景退出码符合 FR-CLI-007 表格定义。

### AT-108 大目录预警（覆盖 FR-CLI-012）

构造 `runs/` 目录含 ≥ 2GiB 测试数据，运行 `odp-reset --yes --force`。

**通过标准**：删除该目录前出现 WARNING 级 `——这可能需要一会...` 提示。

### AT-109 自指安全（覆盖 G6、FR-PATH-104、FR-AUDIT-003）

```bash
odp-reset --yes --force
ls apps/platform/meta_logging/reset_project/   # 审计日志完整存在
ls apps/platform/logging/                       # 业务日志目录已被清空
```

**通过标准**：
- `LOGGING_DIR` 被成功清理（视为业务运行时产物）
- `META_LOGGING_DIR` 完整保留（受保护）
- 审计日志从开始到结束完整、未截断

## 8.3 Definition of Done（每个需求）

单条需求"完成"的统一定义：

- [x] 代码实现完成
- [x] 类型标注完整
- [x] docstring 完整
- [x] 通过 ruff / mypy 静态检查
- [x] 至少 1 位 Reviewer 通过 Code Review
- [x] 关联 AC 在本地复测通过
- [x] PR 描述与 commit message 符合规范
- [x] 相关文档（README / ADR / RTM）已同步更新

## 8.4 Definition of Done（整体里程碑）

整个 D2.5 阶段"完成"的统一定义：

- [x] 8.1 节七项总体准则全部满足
- [x] 8.2 节九个 AT 测试用例全部通过
- [x] git commit 形成预期的提交历史，且每条 commit 满足 FR-DOC-104
- [x] 在三种 OS 上均完成 AT-101 / AT-103 / AT-104 验证
- [x] PRD、HLD、ADR-002、运维手册、测试报告五份文档归档
- [x] 安全 / 数据治理代表对 NFR-SEC 各项无异议
- [x] 阶段评审会议通过

---

# 9. 项目里程碑与交付计划

## 9.1 阶段划分

| 里程碑 | 时间 | 交付物 | 责任人 |
| --- | --- | --- | --- |
| M1：需求评审 | T+0 | 本 PRD v1.0 评审通过 | Owner |
| M2：详细设计 | T+1 ~ T+2 | HLD + ADR-002 草案 | 架构组 |
| M3：开发实施（阶段一） | T+3 ~ T+4 | paths.py 扩展（FR-PATH-101 ~ 104） + audit_utils 模块 | Dev |
| M4：开发实施（阶段二） | T+5 ~ T+7 | reset_project CLI 主流程 + 安全机制 + 进度展示 | Dev |
| M5：跨平台与工程化 | T+8 | console_script 注册 + Windows 适配 + 三端联调 | Dev |
| M6：文档完善 | T+9 | ADR-002 终稿 + 运维手册 + CLI README 更新 | Owner + Dev |
| M7：QA 验收 | T+10 ~ T+11 | 验收测试报告（含安全场景报告） | QA + 安全 |
| M8：阶段评审 | T+12 | 阶段评审会议、归档 | Owner |
| **M9：上线发布** | **T+13** | **合入主干，对全员可用** | **Owner + 平台组** |

> T = 项目启动日；具体日期以项目计划表为准。

## 9.2 交付清单（Deliverables）

| 类别 | 交付物 | 路径 / 形式 |
| --- | --- | --- |
| 代码 | paths.py 扩展 | `apps/platform/src/odp_platform/common/paths.py`（增量） |
| 代码 | reset_project CLI | `apps/platform/src/odp_platform/cli/reset_project.py` |
| 代码 | 审计上下文 | `apps/platform/src/odp_platform/common/audit_utils.py` |
| 代码 | 开发期入口 | `scripts/reset_project.py` |
| 配置 | pyproject.toml 更新 | `apps/platform/pyproject.toml`（新增 `odp-reset` script） |
| 文档 | PRD（本文档） | `docs/srs/PRD-ODPlatform-Reset-D2_5-v1.0.md` |
| 文档 | ADR | `docs/architecture/ADR-002-reset-safety-design.md` |
| 文档 | 运维手册 | `docs/ops/reset-project-runbook.md` |
| 文档 | CLI README 更新 | `apps/platform/src/odp_platform/cli/README.md` |
| 文档 | 验收测试报告 | `docs/qa/D2_5-acceptance-report.md`（QA 出具） |

---

# 10. 风险评估与应对

| 编号 | 风险描述 | 概率 | 影响 | 等级 | 应对措施 | 责任人 |
| --- | --- | :-: | :-: | :-: | --- | --- |
| R-01 | 用户误以为默认行为是删除，意外执行破坏性操作 | 低 | 高 | **高** | 默认 dry-run + 末尾必有 `💡 这是 dry-run` 提示；`--yes` 必须显式给出；运维手册置顶强调 | Owner |
| R-02 | 删除清单（白名单）配置错误，包含 git 目录或受保护数据 | 中 | 极高 | **高** | 双层防护机制（FR-SAFE-002）；强对抗测试 AT-102；Code Review 检查清单 | Dev、Reviewer |
| R-03 | 审计日志因 LOGGING_DIR 被删而丢失关键信息 | 中 | 高 | **高** | META_LOGGING_DIR 物理隔离（FR-PATH-104）；AT-109 验证 | Dev |
| R-04 | Windows 文件锁导致删除部分失败，用户误判为工具 bug | 高 | 中 | **高** | onerror 回调 chmod 重试（FR-CLI-015）；运维手册故障排查段说明 Windows 文件占用情形 | Dev、文档 |
| R-05 | CI 集成时退出码不一致，导致流水线判定错误 | 中 | 中 | 中 | 退出码规范化（FR-CLI-007）；AT-107 验证；运维手册示例覆盖 CI 场景 | Dev、QA |
| R-06 | 二次确认机制被某些 IDE 终端吞掉输入，导致用户无法确认 | 低 | 中 | 低 | 文档说明 `--force` 替代方案；Code Review 时检查 `input()` 调用未使用任何 readline 增强 | Dev |
| R-07 | 大目录扫描耗时长，用户误以为卡死 | 中 | 低 | 低 | 大目录预警（FR-CLI-012）；NFR-PERF-002 限定扫描耗时上限 | Dev |
| R-08 | `_audit_context` 采集时 git 不可用导致流程中断 | 低 | 中 | 低 | 软依赖处理（采集失败降级为 `"unknown"`）；FR-AUDIT-001 AC-2 验证 | Dev |
| R-09 | 用户在 dry-run 后误以为已完成清理 | 低 | 中 | 低 | dry-run 表头使用 `[DRY-RUN]` 显式标识（FR-CLI-014）；末尾提示如何真正执行 | Owner、文档 |
| R-10 | 跨平台测试覆盖不足，某些 Windows 边缘情况未发现 | 中 | 中 | 中 | AT-106 强制三端验证；招募 Windows 用户参与 QA | QA |
| R-11 | 删除清单变更（FR-PATH-101）后调用方未同步，造成漏删 / 多删 | 低 | 中 | 中 | Single Source of Truth 设计：调用方必须经 `get_dirs_to_reset()`；ruff 自定义规则禁止其他来源（V1.1 引入） | Reviewer |
| R-12 | 后续维护者在不理解设计意图时弱化默认安全机制（如默认改为非 dry-run） | 低 | 极高 | 中 | ADR-002 显式记录决策；NFR-MAINT-007 要求弱化必须经架构组评审 | 架构组 |

> **等级说明**：高 = 必须立即应对，中 = 跟踪并定期回顾，低 = 接受。

---

# 11. 需求追踪矩阵（RTM）

> RTM 用于将 **需求 → 设计 → 实现 → 测试** 串成一条可追溯链路。Code Review、阶段评审、变更影响分析均依赖此表。

| 需求 ID | 需求摘要 | 优先级 | 关联场景 | 设计文档 | 实现位置 | 验收用例 |
| --- | --- | --- | --- | --- | --- | --- |
| FR-PATH-101 | 待重置目录列表函数 | P0 | US-01、US-02 | HLD §3.1 | paths.py `get_dirs_to_reset` | AT-101 |
| FR-PATH-102 | 受保护目录清单 | P0 | US-03、US-04 | HLD §3.2 | paths.py `PROTECTED_DIRS` | AT-102 |
| FR-PATH-103 | 受保护判定函数 | P0 | US-03 | HLD §3.3 | paths.py `is_protected` | AT-102、单元测试 |
| FR-PATH-104 | 元日志目录常量 | P0 | US-04 | HLD §3.4 | paths.py `META_LOGGING_DIR` | AT-105、AT-109 |
| FR-CLI-001 | 主入口函数 | P0 | US-01、US-02 | HLD §4.1 | cli/reset_project.py `main` | AT-101、AT-104 |
| FR-CLI-002 | 业务函数 | P0 | US-01、US-02 | HLD §4.2 | cli/reset_project.py `reset_project` | AT-101、AT-104 |
| FR-CLI-003 | 目标目录扫描 | P0 | US-01 | HLD §4.3 | cli/reset_project.py `_scan_dir` | AT-101、AT-108 |
| FR-CLI-004 | 删除计划展示 | P0 | US-01、US-03 | HLD §4.4 | cli/reset_project.py `_print_plan` | AT-101 |
| FR-CLI-005 | 实际删除执行 | P0 | US-01、US-02 | HLD §4.5 | cli/reset_project.py `_execute_deletion` | AT-104、AT-106 |
| FR-CLI-006 | 执行汇总 | P0 | US-01、US-02、US-04 | HLD §4.6 | cli/reset_project.py `_print_summary` | AT-104、AT-105 |
| FR-CLI-007 | 退出码规范 | P0 | US-02 | HLD §4.7 | cli/reset_project.py `main` | AT-107 |
| FR-CLI-008 | 命令行参数定义 | P0 | US-01、US-02 | HLD §5.1 | cli/reset_project.py `_build_parser` | AT-101、AT-104 |
| FR-CLI-009 | 参数冲突处理 | P1 | US-03 | HLD §5.2 | cli/reset_project.py `reset_project` | 单元测试 |
| FR-CLI-010 | 三种调用方式 | P1 | US-01 | HLD §5.3 | 多入口注册 | AT-101、人工 |
| FR-CLI-011 | 开发期入口脚本 | P1 | US-02 | HLD §5.4 | scripts/reset_project.py | AT-101 |
| FR-CLI-012 | 大目录预警 | P1 | US-01 | HLD §6.1 | cli/reset_project.py `_print_plan` | AT-108 |
| FR-CLI-013 | 逐目录进度计数 | P1 | US-01 | HLD §6.2 | cli/reset_project.py `_execute_deletion` | AT-104 |
| FR-CLI-014 | dry-run 视觉区分 | P1 | US-01、US-03 | HLD §6.3 | cli/reset_project.py `_print_plan` | AT-101、AT-104 |
| FR-CLI-015 | Windows 只读处理 | P0 | US-05 | HLD §7.1 | cli/reset_project.py `_on_rm_error` | AT-106 |
| FR-CLI-016 | 跨平台路径输出 | P1 | US-05 | HLD §7.2 | cli/reset_project.py | AT-106 |
| FR-CLI-017 | 终端编码兼容 | P1 | US-05 | HLD §7.3 | cli/reset_project.py | AT-106 |
| FR-SAFE-001 | 默认安全 | P0 | US-01、US-03 | HLD §8.1 | cli/reset_project.py `reset_project` | AT-101 |
| FR-SAFE-002 | 双层防护 | P0 | US-03、US-04 | HLD §8.2 | cli/reset_project.py + paths.is_protected | AT-102 |
| FR-SAFE-003 | 二次确认 | P0 | US-01、US-03 | HLD §8.3 | cli/reset_project.py `_confirm` | AT-103 |
| FR-SAFE-004 | force 跳过交互 | P0 | US-02 | HLD §8.4 | cli/reset_project.py `reset_project` | AT-104 |
| FR-SAFE-005 | 部分删除策略 | P0 | US-02、US-04 | HLD §8.5 | cli/reset_project.py `_execute_deletion` | AT-104、AT-106 |
| FR-AUDIT-001 | 审计上下文采集 | P0 | US-04 | HLD §9.1 | common/audit_utils.py `_audit_context` | AT-105 |
| FR-AUDIT-002 | 审计日志落盘 | P0 | US-04 | HLD §9.2 | cli/reset_project.py + audit_utils | AT-105、AT-109 |
| FR-AUDIT-003 | logger 隔离 | P0 | US-04 | HLD §9.3 | cli/reset_project.py | AT-109、Code Review |
| FR-PKG-101 | console_script 注册 | P0 | US-01 | HLD §10.1 | apps/platform/pyproject.toml | AT-101 |
| FR-PKG-102 | 依赖声明 | P1 | — | HLD §10.2 | apps/platform/pyproject.toml | Code Review |
| FR-DOC-101 | ADR-002 | P0 | US-04 | HLD §11.1 | docs/architecture/ADR-002-*.md | 架构评审 |
| FR-DOC-102 | 运维手册 | P0 | US-01、US-02 | HLD §11.2 | docs/ops/reset-project-runbook.md | 文档评审 |
| FR-DOC-103 | CLI README 更新 | P1 | — | HLD §11.3 | apps/platform/src/odp_platform/cli/README.md | 文档评审 |
| FR-DOC-104 | Conventional Commits | P1 | — | HLD §11.4 | git log | 阶段评审 |

> HLD（High Level Design）由架构组在 M2 里程碑产出，本 PRD 仅引用其章节号占位。

---

# 12. 附录

## 附录 A：双层防护机制示意

```
                         用户调用 reset_project(yes=True, force=True)
                                          │
                                          ▼
             ┌────────────────────────────────────────────────┐
             │ 第一层（Allowlist）                              │
             │ targets = paths.get_dirs_to_reset()             │
             │ —— 仅允许此函数定义的目录进入候选清单            │
             └─────────────────────┬──────────────────────────┘
                                   │
                                   ▼
             ┌────────────────────────────────────────────────┐
             │ 第二层（Denylist 复核）                          │
             │ for t in targets:                               │
             │     if paths.is_protected(t):                   │
             │         abort(exit_code=2)                      │
             │ —— 任一目录命中保护清单立即整体中止              │
             └─────────────────────┬──────────────────────────┘
                                   │
                                   ▼
                          实际执行删除流程
```

**核心原则**：两层防护必须**逻辑独立**——白名单通过"仅枚举安全的"实现保护，黑名单通过"显式禁止危险的"实现保护，两者使用不同维度的判定，互为冗余。

## 附录 B：退出码与典型场景对照表

| 退出码 | 场景 | 上游脚本通常处置 |
| --- | --- | --- |
| 0 | dry-run 完成 | 无操作 |
| 0 | 用户取消 | 提示用户重试 |
| 0 | 真实删除全部成功 | 进入下一步 |
| 1 | 真实删除部分失败 | 检查日志，决定是否重试或人工介入 |
| 2 | 真实删除全部失败 / 双层防护触发 / 参数错误 | 立即终止流水线，人工介入 |

## 附录 C：审计日志格式示例

```
[AUDIT] {"timestamp":"2026-05-11T03:48:59Z","tool_name":"reset_project","tool_version":"0.1.0","user":"alice","hostname":"ml-workstation-12","cwd":"/home/alice/ODPlatform","root_dir":"/home/alice/ODPlatform","argv":["reset_project.py","--yes","--force"],"os_info":"Linux-5.15.0","python_version":"3.10.12","git_commit":"abc1234"}
2026-05-11 03:48:59 [INFO    ] reset_project.py         :229  │ ============================== 项目重置工具 ==============================
2026-05-11 03:48:59 [INFO    ] reset_project.py         :230  │ 项目根目录: /home/alice/ODPlatform
... (后续运行记录)
```

## 附录 D：保护机制与允许清单对比

| 维度 | Allowlist (`get_dirs_to_reset`) | Denylist (`PROTECTED_DIRS`) |
| --- | --- | --- |
| 角色 | 主动定义可删除范围 | 被动定义不可删除范围 |
| 触发时机 | 流程开始时枚举 | 每个目标删除前复核 |
| 失败行为 | 列表为空时无操作 | 命中即整体中止 |
| 维护频率 | 偶尔（新增运行时目录时） | 极少（仅当目录架构调整） |
| 修改门槛 | Code Review | Code Review + 架构组评审 |

## 附录 E：Conventional Commits 类型对照表

| 类型 | 用途 | 示例 |
| --- | --- | --- |
| `feat` | 新功能 | `feat(common): add reset target list + protection mechanism in paths.py` |
| `feat` | 新功能 | `feat(cli): add reset_project.py with dry-run + confirmation + progress` |
| `fix` | bug 修复 | `fix(cli): forward sys.argv via main() in scripts entry` |
| `chore` | 杂事（配置 / 依赖） | `chore: register odp-reset console script in pyproject.toml` |
| `refactor` | 重构（行为不变） | `refactor(cli): extract _on_rm_error into module-level helper` |
| `docs` | 文档 | `docs: add ADR-002 documenting reset safety design` |
| `test` | 测试 | `test(cli): add adversarial test for two-layer defense` |

## 附录 F：术语补充

- **Single Source of Truth (SSoT)**：单一权威数据源原则。本 PRD 中体现为：删除范围只定义于 `get_dirs_to_reset()`、保护范围只定义于 `PROTECTED_DIRS`。
- **Fail-fast**：错误尽早暴露原则。安全防护被触发时立即整体中止，避免部分执行造成的"模糊状态"。
- **Best-effort**：尽力而为原则。执行期 IO 失败时跳过失败项，完成可完成的部分，并完整报告失败列表（参考 `make -k`）。
- **Safe by default**：默认安全原则。危险操作的默认行为应是只读 / 预演，需显式确认才能执行。
- **Visual interrupt for irreversible actions**：不可逆操作的视觉打断原则。确认提示在视觉上必须与日常输出明显不同，强制用户从扫读模式切换为决策模式。

## 附录 G：本 PRD 与 D2 PRD 的衔接

| D2.5 章节 | 衔接 D2 章节 |
| --- | --- |
| 5.2 paths.py 扩展 | D2 5.2 paths.py |
| 5.7 logger 隔离 | D2 5.3 logging_utils（FR-LOG-003 端私有约束） |
| 5.4 命令行参数 | D2 5.7 init_project（FR-INIT-006 三种调用方式约定） |
| 5.10 文档产物 | D2 5.9 文档与版本控制产物 |
| 7.2 设计原则 | D2 附录 E 术语补充（"safe by default"在 D2 阶段未完整覆盖，本期完整体现） |

---

## 文档结束

| 文档负责人签字 | | 日期 | |
| --- | --- | --- | --- |
| 产品 Owner | 雨霓 | 2026-05-11 | |
| 架构组负责人 | | | |
| QA 负责人 | | | |
| 安全 / 数据治理代表 | | | |
| 平台组负责人 | | | |

**— 本 PRD 终止于此 —**
