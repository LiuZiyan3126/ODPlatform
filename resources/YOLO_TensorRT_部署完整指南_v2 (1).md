# YOLO → TensorRT 部署完整指南（v2.1 · 重构扩充 + 实测更新版）

> 从 PyTorch 训练模型到生产级推理引擎的完整技术解析。
> **本版相对 v1 的改动**：① 新增"版本兼容性与 FP16 导出失败的真相"专章（基于真实踩坑确诊，第 5 章）；
> ② INT8 量化补成**可落地的校准实战**（含数据对齐、校准器完整代码、精度复核，第 9 章）；
> ③ 新增"接入推理流水线"（含 trtexec 裸引擎的元数据封装脚本，第 11 章）；④ 全文修正若干会误导人的说法，补上真实测量结论。
> **v2.1 增量**：⑤ 确认 TRT 11 把 FP16/INT8 移出 `BuilderFlag`，**升级 ultralytics + `nvidia-modelopt` 后 FP16 已成功导出，
> 摄像头 loop ~78 → 80+**（第 5.5 节）；⑥ 新增"动态 batch 上限 + 矩形推理 384×640"报错章节（第 8.5 节）。

---

## 📌 本文针对的真实环境（贯穿全文的例子）

| 项 | 值 |
|---|---|
| GPU | NVIDIA **RTX 3070 Ti Laptop**（Ampere，SM 8.6，8 GB 显存） |
| 系统 | Windows 11 |
| CUDA / PyTorch | CUDA 13.0 / torch 2.12 |
| **TensorRT** | **11.0.0.114**（很新，是后面 FP16 翻车的根因） |
| ultralytics | 8.4.60 |
| 模型 | `yolov8n`（3.0M 参数，8.1 GFLOPs），640×640，PPE 安全检测（头盔/反光衣/人） |

> ⚠️ 一句先行的诚实话：**对这个又小又快的模型，TensorRT 的提速主要来自"消除每次调用的固定开销"（算子融合），
> 而不是 FP16/INT8 的算力节省**——我们实测 FP16 在它身上几乎没提速（第 5、9 章详述）。
> 而且摄像头被硬件锁在 90 FPS，TensorRT 的目标是把 loop 顶到接近 90，不是无限快。**先打光/锁曝光稳住捕获，再谈引擎优化。**
>
> ✅ **实测战果（2026-06-15 更新）**：升级 ultralytics + 装 `nvidia-modelopt` 后 FP16 引擎已能成功导出；
> 把 `.engine` 接入摄像头后，**loop 从原来的 ~78 提升到 80+，明显向 90 的硬件天花板靠拢**。
> 这份提升来自 **TensorRT 引擎本身的去开销**——与 FP16 关系不大（FP32 引擎同样能拿到，见第 5.5 节）。

---

## 目录

1. [引言：为什么需要模型转换](#1)
2. [模型的生命周期](#2)
3. [核心概念：三种模型格式（含 .engine 文件头结构）](#3)
4. [数值精度：FP32 / FP16 / INT8](#4)
5. [★ 版本兼容性与 FP16 导出失败的真相](#5)
6. [TensorRT 深度解析](#6)
7. [两种转换路径：YOLO export vs trtexec](#7)
8. [动态批次 vs 静态批次（含你踩的那个报错）](#8)
9. [★ INT8 量化与校准（数据对齐）完整实战](#9)
10. [转换实战：完整命令详解（TRT 10/11 语法已更新）](#10)
11. [★ 接入推理流水线（含 trtexec 引擎元数据封装）](#11)
12. [常见问题与排错](#12)
13. [总结与最佳实践](#13)
- [附录 A：术语表](#a) ／ [附录 B：快速命令参考](#b)

---

<a id="1"></a>
## 1. 引言：为什么需要模型转换

训练得到的 `.pt` 在**训练环境**里好用，但**部署环境**有四个老问题：速度慢、依赖重、精度过剩、硬件没吃满。
模型转换的本质是：**把"适合训练的表示"换成"适合推理的表示"**。

```
┌─────────────────┐   转换    ┌─────────────────┐
│  训练模型 .pt    │ ───────► │  推理引擎 .engine │
│  灵活/可调试      │          │  快/轻/硬件优化   │
│  FP32            │          │  FP16/INT8       │
└─────────────────┘          └─────────────────┘
```

**但要破除一个误区**（v1 没讲清）：对小模型，转换的最大收益不一定是"算得更快"，而是**去掉框架开销**——
PyTorch/ultralytics 每次 `model()` 调用都有 kernel 启动、同步、构造结果对象的固定成本（我们在摄像头 batch=1 上实测约 8 ms）。
TensorRT 把整张图编译成融合内核 + 精简执行计划，**这部分开销大幅下降**，这才是实时单帧场景的主要提速来源。

---

<a id="2"></a>
## 2. 模型的生命周期

```
训练 Training ──► 导出 Export ──► 优化 Optimization ──► 部署 Deployment
  .pt              .onnx           .engine(TRT)          推理服务/边缘设备
                   .torchscript    .xml(OpenVINO)
                                   .mlmodel(CoreML)
```

| 阶段 | 目标 | 关注点 | 工具 |
|---|---|---|---|
| 训练 | 学最优参数 | 收敛/泛化 | PyTorch |
| 导出 | 格式转换 | 兼容/完整 | torch.onnx, `yolo export` |
| 优化 | 性能提升 | 速度/显存/精度 | TensorRT, trtexec |
| 部署 | 实际运行 | 稳定/延迟/吞吐 | 你的 ODPlatform 流水线 |

---

<a id="3"></a>
## 3. 核心概念：三种模型格式

### 3.1 `.pt`（PyTorch 原生）
序列化的 Python 对象，含模型结构 + 权重（+ 可选优化器状态/训练元信息）。
不适合直接部署：依赖 Python/PyTorch、动态图每次重建、无硬件优化、体积含冗余。

### 3.2 `.onnx`（跨框架中间格式）
开放标准，用**计算图**（节点=算子，初始化器=权重）描述模型，是 PyTorch→TensorRT 的桥梁。
你导出时的日志已经印过：`input "images" (1,3,640,640)`，`output "output0" (1,9,8400)`
（9 = 4 bbox + 5 个类；8400 = 80²+40²+20² 个候选框）。

> 价值：跨框架兼容、标准化算子、工具丰富（Netron 可视化、onnxslim 精简）。**ONNX 这一步通常最稳**——
> 你那次失败也是**ONNX 成功、卡在 ONNX→engine 的 FP16 环节**。所以 ONNX 往往是排错的"安全中转站"。

### 3.3 `.engine`（TensorRT 执行计划）—— 含一个你必须知道的文件头结构

`.engine` 是 TensorRT 针对**特定 GPU + 特定配置**生成的高度优化二进制。但有个关键细节 v1 没讲：

**ultralytics 导出的 `.engine` 并不是"纯引擎"，它在最前面加了一段元数据头：**

```
┌────────────┬─────────────────────┬───────────────────────────────┐
│ 4 字节长度  │  元数据 JSON         │     序列化的 TensorRT 引擎      │
│ (小端)     │ names/imgsz/task/... │     (真正的 engine 字节)        │
└────────────┴─────────────────────┴───────────────────────────────┘
```

`YOLO("xxx.engine")` 加载时**先读这 4 字节拿到元数据长度 → 读 JSON 拿到类别名/imgsz/task → 再反序列化后面的引擎**。
**这就是为什么 trtexec 直接产出的"裸引擎"（没有这段头）用 `YOLO()` 加载会崩**——第 11 章给你封装脚本补上它。

#### 为什么 Engine 不能跨 GPU / 跨 TRT 版本
内核代码是针对特定 SM 架构编译的、内存分配按特定显存优化、并行策略按特定核心数设计。
所以 **RTX 3070 Ti 上构建的引擎，换到别的架构（甚至别的 TRT 版本）就用不了，必须在目标机重建**。

---

<a id="4"></a>
## 4. 数值精度：FP32 / FP16 / INT8

### 4.1 存储格式（IEEE 754）
```
FP32  [S|exp 8|mantissa 23]  4字节  ~7位有效数字  ±3.4e38
FP16  [S|exp 5|mantissa 10]  2字节  ~3位有效数字  ±65504
INT8  [S|value 7]            1字节  无小数        -128~127
```

### 4.2 对比

| 特性 | FP32 | FP16 | INT8 |
|---|---|---|---|
| 大小 | 4B | 2B | 1B |
| 范围 | ±3.4e38 | ±65504 | -128~127 |
| 精度 | ~7位 | ~3位 | 整数 |
| 典型加速(理论) | 1× | ~2× | ~4× |
| 是否需校准 | 否 | 否 | **是（数据对齐）** |

### 4.3 为什么推理能用低精度
训练要累积微小梯度（`w -= lr·∂L/∂w`，FP16 会丢掉关键小量 → 不收敛）。
推理是纯前向，最终还要过 argmax/阈值，**微小数值差异通常不改变分类/检测结果**。

### 4.4 Tensor Core
现代 NVIDIA GPU 有 Tensor Core，对 FP16/INT8 的矩阵乘加有专用加速（理论上 FP16 ~2×、INT8 ~4× 于 FP32）。
**但"理论加速"只在算力受限时兑现**——小模型/小输入往往是启动/带宽受限，FP16 看不到那 2×（见第 5、9 章实测）。

### 4.5 精度选择指南（已按真实经验修订）

| 场景 | 推荐 | 备注 |
|---|---|---|
| 目标检测 YOLO（大模型/大图/服务端批量） | FP16 | 有意义 |
| **目标检测 YOLO（小模型如 n，且瓶颈在预处理/调用开销）** | **FP32 引擎即可** | FP16 提升可忽略，别为它折腾版本 |
| 图像分类 | INT8 | 容忍度高 |
| **安全检测（漏检后果严重，如本项目 PPE）** | **FP16；INT8 须严格复核召回率** | INT8 漏检头盔代价大 |
| 边缘设备/极致吞吐 | INT8 | 需校准 + 验收 |

---

<a id="5"></a>
## 5. ★ 版本兼容性与 FP16 导出失败的真相

> 这是 v1 完全缺失、而你**实地确诊**的一章。核心结论：**你的 FP16 导不出来，不是用法错，是 ultralytics 8.4.60 没适配 TensorRT 11 的 API。**

### 5.1 你遇到的真实报错

```
TensorRT: building FP16 engine as ...best.engine
ERROR TensorRT: export failure: type object 'tensorrt_bindings.tensorrt.BuilderFlag' has no attribute 'FP16'
  ...
  File ".../ultralytics/utils/export/engine.py", line 284, in onnx2engine
    config.set_flag(trt.BuilderFlag.FP16)
AttributeError: type object 'tensorrt_bindings.tensorrt.BuilderFlag' has no attribute 'FP16'
```

### 5.2 根因分析

```
┌───────────────────────────────────────────────────────────────────────┐
│  ultralytics 8.4.60 的导出代码                调用                      │
│  config.set_flag(trt.BuilderFlag.FP16) ───────────►  TensorRT 11 Python API │
│         （沿用旧版枚举路径）                          BuilderFlag 已重组/改名 │
│                                                       → 该属性不在原位置  │
│  结果：AttributeError，FP16 这条代码路径直接炸                            │
└───────────────────────────────────────────────────────────────────────┘
```

- **本质**：TensorRT 大版本（8 → 10 → 11）多次重构 Python 绑定，`BuilderFlag` 等枚举的位置/暴露方式变了；
  ultralytics 这个版本的导出器还按老 API 写，于是在**设 FP16 标志**这一步崩了。
- **关键观察 ①**：**FP16 和 INT8 这条"设标志"的路径都坏了**（第 5.5 节用 `dir()` 确认这两个枚举确实已从 `BuilderFlag` 移除）。
  **FP32 导出不设这个标志，所以正常**——你那次 `batch=32`（没加 `half`）的引擎**确实成功构建了**，
  报错是发生在**推理时的形状不匹配**（见第 8 章），不是构建失败。
- **关键观察 ②**：**trtexec 是 C++ 二进制，不走这段 python 绑定**，所以 `trtexec --fp16` **能用**——
  这是 trtexec 在你这套环境下的真优势。

### 5.3 三条绕法（按推荐顺序，已用实测标注）

| 方案 | 命令/做法 | 适用 / 实测 |
|---|---|---|
| **① 直接导 FP32 引擎** | `yolo export ... format=engine imgsz=640 batch=1`（去掉 `half`） | **首选**。对小模型 FP16 本就没用，FP32 引擎照样去掉调用开销；这条在原版 ultralytics 上就能成 |
| **② 升级 ultralytics（+ nvidia-modelopt）** | `pip install -U ultralytics`；首次导出时它会提示再装 `nvidia-modelopt[onnx]>=0.44` | **✅ 已验证可行**。装好后 `half=True` 能成功导出 FP16 引擎（本项目就是这么导出来的） |
| ③ 用 trtexec 的 `--fp16` | 见第 7、10 章（绕开 python 绑定 bug） | 不想升级、又要 FP16 时；trtexec 是 C++ 二进制不碰那段坏代码 |

### 5.4 一个必须诚实交代的实测结论

我们在 1080p 视频上用 ultralytics 跑过 `half` 开/关对比（同模型、同 imgsz）：

```
开 half：推理 1.77~1.84 ms      不开 half：推理 1.53~1.79 ms（甚至更低）
模型整帧(预+推+后)：开 ~5.1 ms   不开 ~4.8~5.0 ms
```

**结论：FP16 在这个 yolov8n@640 上没有可测量的提速。** 原因：模型太小，前向只有 ~1.7 ms，
**瓶颈已转移到预处理（1080p 缩到 640，约 2.2 ms，比推理还大）**。FP16 省的是算力，对一个不再是瓶颈的环节无能为力。

> 给你和学生的话：**FP16 不是这个模型的银弹。** 别为了点不亮的 FP16 去和版本死磕；
> 摄像头的真正提速来自 TensorRT 的"去开销"（FP32 引擎即得），以及第一位的——**把光打好、把捕获稳在 90**。

### 5.5 ★ 更新（实测确认）：TRT 11 把 FP16/INT8 移出了 `BuilderFlag`，升级 ultralytics 后已能导出

我们后来在这台机器上验证了根因，并跑通了 FP16 导出，过程值得记下来：

**第 1 步：确认 `BuilderFlag` 里到底有什么**
```bash
python -c "import tensorrt as trt; print([x for x in dir(trt.BuilderFlag)])"
# 输出（节选）: ['DEBUG','DIRECT_IO','REFIT','SPARSE_WEIGHTS','STRICT_NANS',
#               'STRIP_PLAN','TF32','VERSION_COMPATIBLE','WEIGHT_STREAMING', ...]
```
- 有 `TF32`、`SPARSE_WEIGHTS`、`STRIP_PLAN` 这些，**却唯独没有 `FP16` 和 `INT8`**。
- 这不是"FP16 不被支持"（3070 Ti 的 Tensor Core 跑 FP16 飞快），而是 **TensorRT 10/11 重构了精度模型**：
  精度不再用 `set_flag(BuilderFlag.FP16)` 这种布尔开关粗暴表达，而是转向**强类型网络（strongly-typed）**
  与 **NVIDIA Model Optimizer（`nvidia-modelopt`）** 这套更细的精度/量化体系。
- 所以旧 ultralytics 那行 `config.set_flag(trt.BuilderFlag.FP16)` 在这版本必然 `AttributeError`。

**第 2 步：升级 ultralytics，按提示装 modelopt**
```bash
pip install -U ultralytics
# 首次导出时它会自动提示并安装:
#   Ultralytics requirement ['nvidia-modelopt[onnx]>=0.44'] not found, attempting AutoUpdate...
```
新版 ultralytics 适配了 TRT 11 的新精度 API（并用 modelopt 处理量化），于是 `half=True` 这条路就通了。

**第 3 步：FP16 引擎成功导出 + 接入摄像头**
导出成功后日志会出现 `Loaded engine size: 8 MiB`、`TensorRT-managed allocation ...`，说明引擎已构建并加载。
接入摄像头后 **loop 从 ~78 升到 80+**（向 90 天花板靠拢）。

> 再次强调那条诚实结论：**这 80+ 的提升来自 TensorRT 引擎的去开销，不是 FP16。** FP32 引擎同样能拿到。
> FP16 能导出来是好事（教学价值 + 省一点显存），但**别把它当成涨点的原因**。

**对手写脚本的影响**：第 9.5 节那个纯 Python 校准脚本里用的 `trt.BuilderFlag.INT8 / FP16`，
在你这台 TRT 11 上**同样会 `AttributeError`**（它们已不在枚举里）。所以**在 TRT 11 上做 INT8，
请走第 9.6 节的 ultralytics 路径**（升级 + modelopt 后即可）；那个手写脚本适用于 TRT 8.x–10.x。

---

<a id="6"></a>
## 6. TensorRT 深度解析

### 6.1 构建流程
```
ONNX ─► [Builder]  解析 → 优化(层融合/精度/内核选择/内存) → 序列化 ─► .engine
```

### 6.2 四大优化技术

**① 层融合（Layer Fusion）** —— 最关键，直接关系到"去开销"
```
优化前: Conv → BN → ReLU → ...   每层都读写显存(7 次显存操作)
优化后: [Conv+BN+ReLU 融合]       数据留在寄存器/共享内存(2 次显存操作)
收益: 省显存带宽 + 省 kernel launch + 增数据复用
```
> 这正是 TensorRT 帮你摄像头(batch=1)的核心：把几十个小算子融成少数大内核，**每次调用的固定开销大降**。

**② 混合精度** —— 自动把可降精度的层降到 FP16/INT8，对数值敏感层（Softmax/Reduce）保 FP32，边界自动插转换。

**③ 内核自动调优** —— 同一个卷积有多种实现（implicit_gemm / winograd / cudnn…），构建时**实测计时选最快**。
这解释了：构建慢（真在跑 benchmark）、引擎不能跨 GPU（不同 GPU 最优内核不同）、同 GPU 加载快。

**④ 内存优化** —— 中间结果显存复用、按需分配、workspace 控制（更大 workspace 允许更激进但更耗内存的内核）。

### 6.3 兼容性矩阵（务必牢记）
```
TensorRT 版本必须匹配   ✗ 8.6 构建的不能在 8.5/10/11 跑
GPU 计算能力(SM)必须匹配 ✗ SM 8.6(30系) 的不能在 SM 8.9(40系) 跑
最佳实践：在目标部署硬件上构建引擎
```

---

<a id="7"></a>
## 7. 两种转换路径：YOLO export vs trtexec

```
路径 A (YOLO 直接导出):  best.pt ──yolo export format=engine──► best.engine   一步到位, 自带元数据
路径 B (ONNX + trtexec): best.pt ──format=onnx──► best.onnx ──trtexec──► best.engine  控制更细, 但产物是"裸引擎"
```

| 方面 | YOLO export | trtexec |
|---|---|---|
| 易用性 | ★★★★★ 一条命令 | ★★★☆☆ 两步 + 参数多 |
| 控制粒度 | ★★☆☆☆ | ★★★★★ |
| 绕开 ultralytics 的 TRT11 bug | ✗（FP16 就是死在这） | **✓（含 `--fp16` 可用）** |
| 工具获取 | `pip install` 即可 | **trtexec.exe 不在 pip 里**，要 TensorRT 完整 zip |
| 产物能否 `YOLO()` 直接加载 | **✓ 自带元数据头** | **✗ 裸引擎，需补元数据（第 11 章）** |
| INT8 校准 | `int8=True data=yaml`（TRT11 升级后可用） | 需先有校准 cache（第 9 章） |

> 选择建议（针对你）：**FP32 引擎能用就走 YOLO export**（`batch=1` 给摄像头）；只有当它确实构建失败、
> 或你要 FP16/精细控制/INT8 时，才上 trtexec——并记得补元数据。

---

<a id="8"></a>
## 8. 动态批次 vs 静态批次（含你踩的那个报错）

### 8.1 概念
- **静态批次**：构建时把 batch 固定（如 1）。运行时**必须正好那个数**，多一张少一张都报错。性能最优、灵活性差。
- **动态批次**：构建时给范围（min/opt/max）。运行时 batch 在范围内任意。灵活、略有开销。

### 8.2 你遇到的报错就是"静态批次"铁律的现场

```
你导出: yolo export ... format=engine batch=32     ← 没开 dynamic → 静态, 烤死成"只吃 32"
你推理: 报 input size (1,3,640,640) not equal to max model size (32,3,640,640)
```
- 注意是 **"not equal to"** 而不是 ">"：静态引擎**只认 32**，不是"上限 32"。
- 它在 **warmup** 阶段就炸了——ultralytics 加载后先用**一张图(batch=1)** 热身，1 ≠ 32 → 断言失败。
- 就算 warmup 过了也跑不动：你的流水线喂变长 batch（视频最后一批不满 32；摄像头被强制 batch=1）。

### 8.3 正确做法

```bash
# 摄像头(实时, batch 恒为 1): 导静态 batch=1 —— 最简单, 也是 TRT 该发力处
yolo export model=best.pt format=engine imgsz=640 batch=1 device=0

# 视频/服务端要变 batch: 必须 dynamic
yolo export model=best.pt format=engine imgsz=640 batch=32 dynamic=True device=0
```
`dynamic=True` 后引擎接受 batch 1~32：warmup 的 1 能过、满批 32 能过、最后不满批也能过。

### 8.4 Optimization Profile（trtexec 动态形状的三点）
```
--minShapes=images:1x3x640x640    最小
--optShapes=images:8x3x640x640    最优(TRT 在此点最深度优化, 设成最常用 batch)
--maxShapes=images:64x3x640x640   最大(运行时不能超过)
```

### 8.5 ★ 升级 ultralytics 后遇到的新报错：动态 batch 的"上限规则" + 矩形推理 384×640

FP16 能导出后，第一次跑动态引擎又撞了一个**新**错误（很典型，记下来）：

```
你导出: yolo export ... format=engine half=True dynamic=True batch=16 ...   ← 动态上限 = 16
你推理: --batch 32 (或配置成 32)

报错: Set dimension [32,3,384,640] for tensor images does not satisfy any optimization profiles.
      Valid range for profile 0: [1,3,32,32]..[16,3,1280,1280]
随后: IndexError: list index out of range
```

两个要点：

1. **动态 batch 也有上限，且"导出上限 ≥ 推理 batch"**。
   `dynamic=True batch=16` 表示引擎的动态范围**最大 batch 是 16**；推理喂 32 → `32 > 16` → 被拒。
   > 规则：**`yolo export` 在 `dynamic=True` 下，`batch=N` 是"最大 batch"，运行时 batch 不能超过它。**
   > 想跑 32，导出就得 `batch=32`（或更大）。

2. **那个 `384×640` 是"矩形推理(rectangular inference)"**，不是 bug。
   ultralytics 对 16:9 视频按长边 640 缩放，高变成 384（`640×9/16≈360→对齐到 384`）。
   本例的尺寸范围 `32×32..1280×1280` 其实**覆盖**了 384×640，**所以尺寸不是这次拦路虎，batch=32 超界才是**。

3. **`IndexError: list index out of range` 是连锁反应**：`setInputShape` 失败 → 这批没产出结果 →
   ultralytics 拿空的 `self.results[i]` 写 speed → 越界崩。**根在第 1 点，不是独立 bug。**

**修法**：让导出上限覆盖推理 batch（视频要 32 就导 ≥32）：
```bash
# 视频跑 batch=32: 导出上限给到 32
yolo export model=best.pt format=engine imgsz=640 dynamic=True batch=32 half=True device=0
```
> 摄像头不受此坑影响——它恒为 batch=1，**导静态 `batch=1` 最省心**（也是 TRT 该发力处）。
> 另外小提醒：命令里 `half=True` 别像那次写两遍，无害但多余。

---

<a id="9"></a>
## 9. ★ INT8 量化与校准（数据对齐）完整实战

> 这是你点名要补的重点。**INT8 ≠ 加个 `--int8` 那么简单**——它必须先用**和部署分布一致**的数据做"校准"，否则精度崩。

### 9.1 为什么 INT8 必须校准

INT8 只有 256 个台阶。要把每个张量的 FP32 取值范围映射到 `[-127, 127]`，得先知道这个张量**实际的数值分布**：

```
量化:   q = round(x / scale)              scale = 该张量的代表性最大幅值 / 127
反量化: x' ≈ q × scale                    (有量化误差)
```

`scale`（缩放因子）选得好不好，**完全取决于你喂的校准数据是否代表真实分布**。
这就是 **"数据对齐"**：校准集必须对齐部署时会看到的数据。

### 9.2 校准数据怎么选（数据对齐的核心，最容易被做错）

| 要求 | 说明（以本项目 PPE 为例） |
|---|---|
| **代表性 ⭐** | 来自**部署现场同一台相机、同样光照/角度/场景**。用网图或别的数据校准 = 量错 |
| **覆盖多样性** | 白天/夜晚、逆光、戴/不戴头盔、远/近、人多/人少、各类别都要有 |
| **数量** | 一般 **100~1000 张**（几百张常见）。**代表性比数量更重要**，盲目堆量无益 |
| **预处理一字不差 ⭐⭐** | 校准时的 letterbox/缩放/`/255`/BGR→RGB/CHW/FP32 **必须和推理完全相同**，否则统计的范围是错的 |
| **不要用训练增强** | 校准用**干净的推理式预处理**，别套 mosaic/翻转等训练增强 |
| 标签 | **不需要标签**，校准只用输入图 |

> 一句话：**校准集 = 推理时真实输入的一个小而全的缩影，且预处理与推理逐像素一致。** 这是 INT8 成败的命门。

### 9.3 校准算法（TensorRT 校准器类型）

| 校准器 | 原理 | 何时用 |
|---|---|---|
| **`IInt8EntropyCalibrator2`** | KL 散度，最小化信息损失 | **CNN/检测首选（YOLO 用它）** |
| `IInt8MinMaxCalibrator` | 直接取 min/max | 部分 Transformer/NLP |
| `IInt8LegacyCalibrator` | 旧版 | 基本不用 |

权重量化 TensorRT 自动做（通常 per-channel 更准）；**激活量化靠你喂的校准数据统计 per-tensor 范围**。

### 9.4 校准流程总览
```
代表性校准图(几百张) ─► 按推理预处理喂入 ─► 跑 FP32 前向, 逐层记录激活分布
                                              ─► 用熵法算每张量最优 scale
                                              ─► 写入校准缓存(calib.cache)
                                              ─► 用 scale 构建 INT8 引擎
```
缓存可复用：下次构建相同网络可直接读 cache 跳过校准。

### 9.5 实战路径 A：Python 自定义校准器（适用 TRT 8.x–10.x）

> ⚠️ **版本提醒（重要）**：下面这个手写脚本用的是 `trt.BuilderFlag.INT8 / FP16`——
> 这两个枚举在你的 **TensorRT 11 上已被移除**（第 5.5 节用 `dir(trt.BuilderFlag)` 已确认）。
> 所以**本路径适用于 TRT 8.x–10.x**；在你这台 **TRT 11 上做 INT8，请直接走第 9.6 节的 ultralytics 路径**
> （升级 + `nvidia-modelopt` 后已可用）。这个脚本仍保留，因为它在绝大多数 TRT 8–10 部署里是最稳、最可控的做法，教学价值也高。
>
> 之所以要自己写校准器（而非用 trtexec）：trtexec **不会读图做校准**（它只能 `--calib` 读现成 cache），
> 所以"从一批图片生成校准"这件事必须由 Python 校准器完成。

**第 1 步：写校准器（读校准图夹，按推理预处理喂数据）**

```python
# int8_calibrator.py
import os, glob
import numpy as np
import cv2
import tensorrt as trt
import pycuda.driver as cuda
import pycuda.autoinit   # 自动初始化 CUDA 上下文

def letterbox(img, size=640, color=(114, 114, 114)):
    """与推理一致的等比缩放 + 填充(YOLO 标准 letterbox)。务必和你流水线里的预处理一致!"""
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), color, dtype=np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top:top + nh, left:left + nw] = resized
    return canvas

class YOLOEntropyCalibrator(trt.IInt8EntropyCalibrator2):
    """读校准图夹, 按【与推理完全一致】的预处理喂给 TensorRT 统计激活范围。"""
    def __init__(self, calib_dir, cache_file="calib.cache",
                 imgsz=640, batch=8, max_images=512):
        super().__init__()
        self.cache_file = cache_file
        self.imgsz, self.batch = imgsz, batch
        exts = ("*.jpg", "*.jpeg", "*.png", "*.bmp")
        files = []
        for e in exts:
            files += glob.glob(os.path.join(calib_dir, "**", e), recursive=True)
        assert files, f"校准夹里没图片: {calib_dir}"
        self.files = files[:max_images]
        self.idx = 0
        # 预分配一个 batch 的 GPU 缓冲(FP32)
        self.nbytes = batch * 3 * imgsz * imgsz * np.dtype(np.float32).itemsize
        self.device_input = cuda.mem_alloc(self.nbytes)
        print(f"[Calib] 校准图 {len(self.files)} 张, batch={batch}, imgsz={imgsz}")

    def get_batch_size(self):
        return self.batch

    def _preprocess(self, path):
        # ★★ 必须与推理预处理逐像素一致: letterbox → BGR2RGB → /255 → CHW → FP32
        img = cv2.imread(path)
        img = letterbox(img, self.imgsz)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        img = img.transpose(2, 0, 1)            # HWC → CHW
        return np.ascontiguousarray(img)

    def get_batch(self, names):
        if self.idx + self.batch > len(self.files):
            return None                          # 数据用完 → 返回 None 结束校准
        batch_np = np.ascontiguousarray(
            np.stack([self._preprocess(f)
                      for f in self.files[self.idx:self.idx + self.batch]])
        )
        cuda.memcpy_htod(self.device_input, batch_np)
        self.idx += self.batch
        return [int(self.device_input)]          # 返回设备指针列表

    def read_calibration_cache(self):
        if os.path.exists(self.cache_file):
            with open(self.cache_file, "rb") as f:
                return f.read()
        return None

    def write_calibration_cache(self, cache):
        with open(self.cache_file, "wb") as f:
            f.write(cache)
```

**第 2 步：用校准器构建 INT8 引擎**

```python
# build_int8.py
import tensorrt as trt
from int8_calibrator import YOLOEntropyCalibrator

ONNX   = "train3-20251223-112728-yolov8n-best.onnx"   # 先 yolo export format=onnx 得到
ENGINE = "best_int8.engine"
IMGSZ, BATCH = 640, 8

logger  = trt.Logger(trt.Logger.INFO)
builder = trt.Builder(logger)

# 注意: TRT 10+ 默认 explicit batch, create_network() 即可;
#       老版本(8.x)要传 1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
network = builder.create_network()
parser  = trt.OnnxParser(network, logger)
with open(ONNX, "rb") as f:
    assert parser.parse(f.read()), "ONNX 解析失败"

config = builder.create_builder_config()
config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 4 << 30)   # 4GB workspace

# ★ 开 INT8 + 挂校准器。建议同时开 FP16 让"不量化的层"走 FP16(混合精度)
#   ⚠️ TRT 11 已移除 BuilderFlag.INT8/FP16(见第 5.5 节)! 下面两行在 TRT 11 上会 AttributeError,
#      仅适用 TRT 8.x-10.x。TRT 11 做 INT8 请走 9.6 的 ultralytics 路径(升级 + nvidia-modelopt)。
#   先确认本版本枚举: python -c "import tensorrt as trt; print([x for x in dir(trt.BuilderFlag)])"
config.set_flag(trt.BuilderFlag.INT8)
config.set_flag(trt.BuilderFlag.FP16)
config.int8_calibrator = YOLOEntropyCalibrator(
    calib_dir="calib_images", cache_file="calib.cache", imgsz=IMGSZ, batch=BATCH
)

# 静态 batch 最省事(INT8 推荐静态)。要动态还需 set_calibration_profile, 见 9.7
serialized = builder.build_serialized_network(network, config)
assert serialized is not None, "INT8 引擎构建失败"
with open(ENGINE, "wb") as f:
    f.write(serialized)
print(f"OK -> {ENGINE}")
```

> 依赖：`pip install pycuda`（或用 `cuda-python`）。构建出来的是**裸引擎**，要接你的 `YOLO()` 流水线
> 仍需第 11 章的元数据封装。

### 9.6 实战路径 B：ultralytics 一条命令（★ TRT 11 上的推荐路径）

```bash
yolo export model=best.pt format=engine int8=True data=your_data.yaml imgsz=640 batch=1 device=0
```
ultralytics 会用 `data.yaml` 里的验证/训练集自动做校准并构建 INT8 引擎，且**自带元数据**（省去第 11 章封装）。

> **为什么这是 TRT 11 上的推荐路径**：你已经为了 FP16 升级了 ultralytics 并装了 `nvidia-modelopt`——
> 而 modelopt 正是 NVIDIA 新的量化工具，新版 ultralytics 的 INT8 导出就走它，**适配了 TRT 11 的新精度 API**，
> 不会再撞 `BuilderFlag` 那个坑。所以在你这台机器上，**INT8 走这条比手写脚本（路径 A）省心得多**。
>
> **仍要记住**：`data.yaml` 的校准集必须满足第 9.2 节的"数据对齐"（来自现场、覆盖多样性、预处理一致），
> 否则 ultralytics 帮你自动校准，喂的也是错数据 → 量出错引擎。校准集质量是你的责任，工具只负责流程。

### 9.7 实战路径 C：trtexec + 现成 cache
trtexec **不会读图校准**，只能加载已有 cache：
```bash
# 先用路径 A 跑出 calib.cache, 然后:
trtexec --onnx=best.onnx --saveEngine=best_int8.engine --int8 --calib=calib.cache \
        --minShapes=images:1x3x640x640 --optShapes=images:8x3x640x640 --maxShapes=images:32x3x640x640 \
        --memPoolSize=workspace:4096
```
> 单独 `trtexec --int8`（无 cache、无校准）会用默认/随机动态范围 → **精度基本不可用**，别这么干。

### 9.8 ★ INT8 后必须做的精度复核（安全场景的红线）

INT8 可能掉精度，而你这是**安全检测——漏检一个没戴头盔的人后果严重**。所以**构建完不算完，必须复核**：

```
在【真实现场】的留出测试集上, 对比 FP16/FP32 与 INT8:
  • mAP 掉多少?
  • 更关键: 各类别的【召回率 recall】掉多少? (漏检 = 召回下降)
  • 头盔/反光衣这类小目标的召回有没有明显下降?
判据: 召回明显下降 → 不要用 INT8, 退回 FP16/FP32。
缓解: 把对量化敏感的层(如检测头)标记保持 FP16/FP32(混合精度), 或扩充/校正校准集再来一次。
```

### 9.9 INT8 小结
1. 必须**校准**，而校准的命门是**数据对齐**（代表性 + 预处理逐像素一致）。
2. 选路径：**TRT 11 → 走 ultralytics（路径 B，已随 FP16 升级一并打通）**；**TRT 8–10 → 可用手写 `IInt8EntropyCalibrator2`（路径 A）**。trtexec 只能读现成 cache（路径 C）。
3. **安全场景务必复核召回率**，宁可不用 INT8。对 yolov8n 这种小模型，FP32/FP16 引擎通常已经够快——**别为 INT8 的那点速度赌上漏检风险。**

---

<a id="10"></a>
## 10. 转换实战：完整命令详解（TRT 10/11 语法已更新）

### 10.1 YOLO export 参数
```bash
yolo export model=best.pt format=engine imgsz=640 batch=1 dynamic=False device=0 workspace=4
```
| 参数 | 含义 | 备注 |
|---|---|---|
| `format=engine` | 输出 TensorRT 引擎 | 也可 `onnx`/`torchscript` |
| `imgsz=640` | 输入尺寸 | **推理时必须一致** |
| `half=True` | FP16 | 旧 ultralytics 在 TRT11 会报 `BuilderFlag.FP16`；**升级 ultralytics + 装 `nvidia-modelopt` 后已可用**（见第 5.5 节）。注意小模型 FP16 提升有限 |
| `batch=1` | 批大小 | 摄像头用 1；要变 batch 配 `dynamic=True` |
| `dynamic=True` | 动态形状 | 视频/服务端变 batch 必须开 |
| `int8=True data=...` | INT8 | 需校准集；TRT11 上可能也坏 |
| `workspace=4` | 构建内存 (GB) | ultralytics 这里单位是 **GB** |

### 10.2 trtexec 参数（注意 TRT 10/11 的 workspace 写法变了）
```bash
trtexec --onnx=best.onnx --saveEngine=best.engine \
        --memPoolSize=workspace:4096 \           # ★ TRT8.5+ 起用这个, 单位 MiB; --workspace 已弃用
        --fp16 \                                  # trtexec 的 --fp16 能用, 绕开 ultralytics bug
        --minShapes=images:1x3x640x640 \
        --optShapes=images:8x3x640x640 \
        --maxShapes=images:64x3x640x640
```
| 参数 | 含义 |
|---|---|
| `--onnx` / `--saveEngine` / `--loadEngine` | 输入 ONNX / 存引擎 / 加载引擎测速 |
| `--fp16` / `--int8` / `--best` | 精度（`--int8` 需 `--calib=cache`；`--best` 自动选最快） |
| `--memPoolSize=workspace:N` | 构建内存 (MiB)，**替代旧 `--workspace`** |
| `--minShapes/--optShapes/--maxShapes` | 动态形状三点（输入名是 `images`） |
| `--calib=cache` | 加载 INT8 校准缓存 |
| `--iterations` / `--warmUp` | 测速迭代次数 / 预热(ms) |
| `--verbose` | 详细日志 |

```bash
# 纯测速(对比引擎吞吐)
trtexec --loadEngine=best.engine --shapes=images:1x3x640x640 --warmUp=500 --iterations=200
```

---

<a id="11"></a>
## 11. ★ 接入推理流水线（含 trtexec 引擎元数据封装）

### 11.1 YOLO export 出来的引擎：零改代码
你的 `service.py` 用 `YOLO(str(model_path))` 加载、`model(images, **kwargs)` 推理，**原生认 `.engine`**：
```bash
# 把 .engine 放进 models/checkpoints/, 然后:
odp-infer --source 0 --model best.engine --imgsz 640 --warmup 30 --show --no-save
```
- `--imgsz` 必须与导出一致；摄像头 batch 被强制 1，正好配静态 batch=1 引擎；`_FrameProcessor` 一行不用改。

### 11.2 trtexec / Python 自建的"裸引擎"：先补元数据头

裸引擎没有第 3.3 节那段元数据头，`YOLO()` 加载会崩。跑一次下面脚本补上：

```python
# wrap_trt_engine.py —— 给裸引擎补 ultralytics 元数据头, 使 YOLO() 能加载
import json
from ultralytics import YOLO

PT    = "train3-20251223-112728-yolov8n-best.pt"          # 原始权重(取 names/stride/task)
RAW   = "best_int8.engine"                                # trtexec/Python 产出的裸引擎
OUT   = "train3-20251223-112728-yolov8n-best.engine"      # 给 pipeline 用的最终引擎
IMGSZ, BATCH = 640, 1     # 与导出一致(动态则填 optShapes 的 batch)

m = YOLO(PT)
stride = int(max(m.model.stride)) if hasattr(m.model, "stride") else 32
meta = {
    "description": f"wrapped engine from {PT}", "author": "odp",
    "stride": stride, "task": m.task, "batch": BATCH,
    "imgsz": [IMGSZ, IMGSZ], "names": m.names,
}
engine_bytes = open(RAW, "rb").read()
with open(OUT, "wb") as t:
    blob = json.dumps(meta).encode("utf-8")
    t.write(len(blob).to_bytes(4, "little", signed=True))   # 4 字节长度头
    t.write(blob)                                           # 元数据 JSON
    t.write(engine_bytes)                                  # 原始引擎
print(f"OK -> {OUT}  names={list(m.names.values())}")
```
之后这个 `.engine` 就和 ultralytics 自导的一样，`--model best.engine` 直接用。

### 11.3 基准对比（验证到底值不值）
用 `--warmup 30` 各跑一次 `.pt` 与 `.engine`，比这两行：
```
模型 speed(ms): 预处理 x | 推理 y | 后处理 z     ← 看 y 降没降
帧率(FPS): ... | loop L | ...                     ← 摄像头 loop 有没有往 90 涨
```
**顺序铁律**：先用锁曝光/加光把**捕获**稳在 90，再看 TensorRT 的单帧提速——捕获才 72 时 loop 涨不动。

---

<a id="12"></a>
## 12. 常见问题与排错

| 现象 | 原因 / 处理 |
|---|---|
| `BuilderFlag has no attribute 'FP16'`（ultralytics 导出时） | **TRT 10/11 把 FP16/INT8 移出了 `BuilderFlag`**，旧 ultralytics 用旧 API 调用。**升级 ultralytics + 装 `nvidia-modelopt[onnx]>=0.44`**（推荐）/ 改导 FP32 / 用 trtexec `--fp16`（第 5.5 章） |
| `... does not satisfy any optimization profiles. Valid range ... [1,...]..[16,...]` | **动态 batch 超上限**：`dynamic=True batch=16` 导出 → 推理喂的 batch 不能 >16。导出 `batch` 给到 ≥ 推理 batch（第 8.5 章） |
| 动态引擎报错后紧跟 `IndexError: list index out of range`（在 `self.results[i].speed`） | 连锁反应：上面 `setInputShape` 失败 → 该批无结果 → ultralytics 写 speed 越界。**根因是 batch 超界，不是独立 bug** |
| 推理尺寸是 `384×640` 而非 `640×640` | ultralytics 对 16:9 视频做**矩形推理**（长边 640，高 384），正常现象；只要引擎动态尺寸范围覆盖它即可（第 8.5 章） |
| `nvidia-modelopt not found, attempting AutoUpdate` | 新版 ultralytics 用 modelopt 做精度/量化。让它自动装，或 `pip install nvidia-modelopt[onnx]` |
| `input size (1,...) not equal to max model size (32,...)` | **静态**引擎烤死了 batch。摄像头导 `batch=1`；变 batch 用 `dynamic=True`（第 8 章） |
| 找不到 `trtexec` 命令 | 不在 pip。下 TensorRT 完整 zip，用 `bin\trtexec.exe`，加 PATH |
| `YOLO()` 加载 trtexec 引擎就崩 / 无 names | 裸引擎缺元数据头，跑 `wrap_trt_engine.py`（第 11.2 节） |
| `--workspace` 报未知参数 | TRT8.5+ 改成 `--memPoolSize=workspace:4096`（MiB） |
| INT8 精度明显下降 | 校准数据没对齐 / 预处理不一致 / 检测头对量化敏感。复核召回，必要时混合精度或退回 FP16 |
| 构建 OOM | 减 batch / 减 workspace / 走 trtexec 两步法 / 关其它占显存程序 |
| 换台机器引擎用不了 | 引擎绑 GPU+TRT 版本，**在目标机重建** |
| 推理结果和 PyTorch 不一致 | 八成是**预处理不一致**（BGR/RGB、归一化、letterbox）；其次 NMS/阈值；FP16 微差正常 |
| 性能没达预期 | 先看瓶颈在哪（预处理? 数据拷贝? 后处理在 CPU?）；小模型别指望 FP16 那 2× |

---

<a id="13"></a>
## 13. 总结与最佳实践

### 13.1 知识点回顾
1. 格式：`.pt`(训练) → `.onnx`(中转/排错安全点) → `.engine`(部署，**含元数据头**)。
2. 精度：FP32 稳、FP16 平衡（**但小模型可能无感**）、INT8 极致（**须校准 + 复核**）。
3. TRT 优化：层融合（去开销的关键）、内核调优、内存优化、混合精度。
4. 两路径：YOLO export 省心、trtexec 可控且能绕开版本 bug（但裸引擎要补元数据）。
5. 批次：静态最快但烤死；动态灵活；**摄像头 batch=1，视频 dynamic**。
6. **版本**：TRT11 + 旧 ultralytics → FP16/INT8 导出会炸；FP32 或升级或 trtexec。

### 13.2 给本项目的落地路线（按优先级，已用实测更新）
```
1) 先把【光/曝光】解决, 捕获稳在 90              ← 当前真瓶颈, 性价比最高
2) 导引擎接入摄像头, 测 loop                      ← ✅ 已做: loop 从 ~78 → 80+, 向 90 靠拢
   (FP32 静态 batch=1 最省心; FP16 升级 ultralytics+modelopt 后也能导, 但提升来自引擎去开销而非 FP16)
3) 视频要批处理: dynamic=True 且导出 batch ≥ 推理 batch  ← 别再撞 batch 超上限(第 8.5)
4) INT8 仅在确有吞吐压力时考虑: TRT11 走 ultralytics int8=True data=...,
   且必须数据对齐 + 复核召回 ← 安全场景慎用, 小模型通常 FP16/FP32 已够
```

### 13.3 性能对比参考（⚠️ 仅大模型/服务端典型值，**你的小模型实测会平很多**）
| 格式 | 精度 | 相对 PyTorch FP32（典型） | 对 yolov8n@640 的真实情况 |
|---|---|---|---|
| TensorRT | FP32 | ~2× | 主要靠去调用开销（**摄像头 loop ~78→80+ 实测**） |
| TensorRT | FP16 | ~4× | 升级后已能导出，但**实测几乎无感**（瓶颈在预处理）；收益其实来自引擎本身 |
| TensorRT | INT8 | ~5–6× | TRT11 走 ultralytics；需校准 + 数据对齐；安全场景慎用 |

> 别把别人 GPU 上的倍数当成你的预期——**一切以你 RTX 3070 Ti 上 `--warmup 30` 的实测为准。**

---

<a id="a"></a>
## 附录 A：术语表

| 术语 | 全称 | 说明 |
|---|---|---|
| FP32/FP16/INT8 | 32/16位浮点、8位整数 | 数值精度 |
| ONNX | Open Neural Network Exchange | 跨框架中间格式 |
| TensorRT / Engine | - | NVIDIA 推理优化器 / 优化后的执行计划 |
| SM | Streaming Multiprocessor | GPU 流式多处理器（决定引擎兼容性） |
| Layer Fusion | - | 层融合，减少显存访问与调用开销 |
| PTQ / QAT | 训练后量化 / 量化感知训练 | INT8 走 PTQ（静态校准） |
| Calibration | 校准 | INT8 用代表性数据统计激活范围算 scale |
| Calibrator | `IInt8EntropyCalibrator2` 等 | 校准器，喂数据 + 写缓存 |
| Optimization Profile | - | 动态形状的 min/opt/max 配置 |
| NMS | Non-Maximum Suppression | 非极大值抑制 |
| BuilderFlag | - | TRT 构建标志（FP16/INT8 等；**跨版本可能改名**） |

<a id="b"></a>
## 附录 B：快速命令参考

```bash
# ── 导出 ONNX(排错安全点 / 给 trtexec) ──
yolo export model=best.pt format=onnx imgsz=640 dynamic=True

# ── YOLO 直接导引擎 ──
# 摄像头(FP32 静态 batch=1, 你这套能成):
yolo export model=best.pt format=engine imgsz=640 batch=1 device=0
# 视频(动态 batch, 上限需 ≥ 推理 batch):
yolo export model=best.pt format=engine imgsz=640 batch=32 dynamic=True device=0
# FP16: 升级 ultralytics + 装 nvidia-modelopt 后, 加 half=True 即可(旧版在 TRT11 会报 BuilderFlag.FP16)

# ── trtexec(从 TensorRT zip 的 bin/ 取; --fp16 可用) ──
trtexec --onnx=best.onnx --saveEngine=best.engine --memPoolSize=workspace:4096 --fp16 \
        --minShapes=images:1x3x640x640 --optShapes=images:8x3x640x640 --maxShapes=images:64x3x640x640

# ── INT8(先 Python 校准器跑出 calib.cache, 再 trtexec --calib) ──
python build_int8.py            # 见第 9.5 节, 产出 best_int8.engine + calib.cache
python wrap_trt_engine.py       # 第 11.2 节, 给裸引擎补元数据头

# ── 接入流水线 ──
odp-infer --source 0 --model best.engine --imgsz 640 --warmup 30 --show --no-save

# ── 环境/调试 ──
nvidia-smi
python -c "import tensorrt as trt; print(trt.__version__)"
python -c "import tensorrt as trt; print([x for x in dir(trt.BuilderFlag)])"   # 查本版本标志名
python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"
```

---

**文档版本**：v2.1（重构扩充 + 实测更新）
**适用环境**：YOLOv8 / TensorRT 8.x–11.x（含 TRT 11 精度 API 变更与兼容性坑）/ Windows·Linux
**v2.1 更新（2026-06-15）**：① 确认 TRT 11 把 FP16/INT8 移出 `BuilderFlag`，**升级 ultralytics + 装 `nvidia-modelopt` 后 FP16 导出已打通**；
② 摄像头接入引擎后 **loop ~78 → 80+** 实测记录；③ 新增"动态 batch 上限规则 + 矩形推理 384×640"报错章节（第 8.5）；
④ INT8 在 TRT 11 改推 ultralytics 路径，手写校准脚本标注为 TRT 8–10 适用。
**与 v1 的关系**：在 v1 基础上确诊并补全了版本兼容性、INT8 校准（数据对齐）、流水线接入，并以真实测量修正了 FP16 的预期。
