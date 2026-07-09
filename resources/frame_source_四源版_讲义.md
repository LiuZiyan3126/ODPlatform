# frame_source: 统一帧输入源抽象层(四源版)

> **模块定位**: 一个能整包拷走的独立基础设施——把**摄像头 / 视频 / 图片 / 图片文件夹**这四种最常见的输入源, 封装成同一套接口, 让上层(YOLO 检测、美化、任何逐帧处理)只关心 `for frame in source: ...`, 不再操心摄像头后端协商、双线程采集、跳帧逻辑这些杂事。
>
> **核心叙事**: 工程化推理面对的输入是【动态原始流】——一张图、一个目录、一段 mp4、一个 USB 摄像头、一路 RTSP。而 `ultralytics` 的 `model.predict(source=...)` 是个黑盒: 帧间插不进逻辑、摄像头跑不满帧率、采集与显示解不开耦、实际帧率你也看不到。撞够墙之后, 我们把"出帧"这件事从推理逻辑里剥出来, 抽成一个三层结构的 `frame_source` 子模块(`core / sources / wrappers` + 一个 `factory`)。**这一版只做最常见的四种源**, 刻意不碰深度相机、不做插件化——把"一帧 = 一张 BGR 图"这个朴素而真实的共识吃干榨净, 做到简单、可控、可拷走。
>
> **几面真撞墙**(本模块的设计全是被这几面墙逼出来的, 不是凭空"架构"出来的):
> 1. **`model.predict` 是黑盒** → 帧间插不进自己的逻辑(写库 / 叠水印 / 报警)、摄像头逼不到高帧率、采集和显示解不开耦 → 推出**统一的、可控的 `FrameSource` 协议**。
> 2. **摄像头"我设了"≠"它生效了"** → `set()` 分辨率/帧率只是请求, 驱动可能不理你; 而且 MSMF 后端下参数顺序错了高帧率直接失效 → 推出 **CameraSource 的后端协商 + 参数验证**(三条撞墙记录写进代码)。
> 3. **串行循环里, 采集速度 = 最慢环节的速度** → `imshow`+`waitKey`、推理一慢, 90fps 摄像头被拖到 60 以下 → 推出 **ThreadedSource**: 采集放后台线程, 主循环拿最新帧。
> 4. **视频跳帧用 `read()` 太慢** → `read()` 每帧都做 YUV→BGR 转换 + ndarray 分配 → 推出 **stride 用 `cap.grab()`**: 只解码不转换, 快 3~5 倍。
> 5. **重新 `open()` 同一对象, 居然读不到帧** → 上一版三个源的 `open()` 只重建底层句柄、漏了复位位置计数, 于是"重新 open 重头迭代"这条路是坏的 → 本版**在每个源的 `open()` 里复位位置状态**, 把这个坑修掉(详见 §3 撞墙记录)。
>
> **建议时长**: 4-5 课时(只立三层抽象 + 四个常见源 + 两个 wrapper + 一个 if/elif 工厂; 比那种还要拆多模态/做插件化的版本短, 但"为什么这么分层、为什么 stride 在协议层、为什么工厂用 if/elif 而不是注册表"这几个判断, 一个都不省)。
>
> **设计原则**: frame_source 立志"脱离本平台也能活"——它只解决"出帧"这一件事, 不碰推理、不碰宿主配置体系、不碰宿主日志。核心外部依赖只有 `opencv-python` / `numpy` / `pydantic>=2.0` / `Python>=3.10`。一句话: **`cp -r frame_source/ 你的项目/` 就能跑**。

---

## 📌 跨平台说明

普通 `python` / `pip` / `git` 命令跨平台一致, 不重复。Windows 用户**推荐 Git Bash**, 绝大多数命令跟 Linux 走。

**但有一个平台差异绕不开: 摄像头后端**。Windows 走 MSMF / DSHOW, Linux 走 V4L2, 高帧率参数协商在不同后端上行为不同。这是 `CameraSource` 必须显式处理的事, 到摄像头那节(§3.3)会专门讲。这里先提个醒: **本模块的"撞墙"有一半是平台特定的摄像头行为撞出来的**, 图片/视频那两个源反而平淡——因为它们不碰硬件。

---

## 文档使用说明

本文的产物有三类: **代码**、**对代码的解释**、以及 **一套能复现整个模块的构建顺序**。

- **完整代码**: 每个文件都是终态, 可直接复制粘贴(已含本版的 `open()` 复位修复, 见 §2.3 / §3 撞墙记录)。
- **⚠️ 设计点框**: 容易写错或容易选错的地方提前告诉你。
- **🧱 撞墙时刻**: 某个设计决策是被哪个具体问题逼出来的——亲手撞一遍, 才不会觉得"过度设计"。
- **🤔 思考题**: 给你 30 秒, 想完再往下看。
- **shell / git**: 测试、运行、提交。

**强烈建议跟着自己敲一遍**, 尤其是摄像头那节(§3.3)和工厂那节(§5)。本模块的核心价值不在"代码长什么样", 在几个判断: 为什么要把"出帧"抽成协议、为什么 `seek`/`stride` 是协议方法而不是 wrapper、为什么四个固定的源用 if/elif 派发而不是搞注册表。这些判断不亲手过一遍, 看到这一堆文件会觉得"不就是包了下 cv2 吗"——其实每一处都是某面墙逼出来的。

---

## 本篇挑战: 为什么需要 frame_source

### 第一层挑战: 为什么不能直接 `model.predict(source=...)`

推理看似只差一行:

```python
from ultralytics import YOLO
model = YOLO("best.pt")
model.predict(source="0", show=True)    # 摄像头实时推理, 一行
```

这一行**真能跑**。但它是个黑盒: 你没法在每一帧之间插自己的逻辑(写数据库 / 叠自定义水印 / 触发报警), 没法把摄像头逼到 90fps, 没法把"采集"和"推理显示"解耦, 没法知道实际帧率到底多少。工程化推理需要的所有控制点, 黑盒里一个都伸不进去。

原因在于: **训练的输入是 `data.yaml` 指向的静态标注数据集**, ultralytics 抽象得很完善; 而**推理的输入是动态原始流**——一张图、一个目录、一段 mp4、一个 USB 摄像头、一路 RTSP。每一种的打开方式、参数协商、帧率特性、资源释放都不一样。一个 `source=` 参数想吃下所有这些, 结果就是"能跑但不可控"。

解法: 把"输入源 + 出帧"从推理逻辑里剥出来, 抽成一个统一的、可控的、能整包拷走的 `frame_source`。让推理循环长成这个**四种源通用**的样子:

```python
with create_frame_source(source) as src:   # ← 上下文管理器: 自动 open/close, 不漏资源
    for frame in src:                       # ← 迭代器: 统一的"逐帧"语义, 源耗尽自动停
        results = model(frame.image)        # ← frame.image 恒为 BGR ndarray, 换源不用改
```

`source` 是 `"0"` 还是 `"x.mp4"` 还是 `"./imgs/"`, 这三行一个字都不用动。这就是目标。

### 第二层挑战: 把"出帧"抽出来之后, 它内部该怎么分层

一旦决定"出帧"独立成模块, 紧接着的问题是: 摄像头要协商后端、视频要按帧号跳转、图片文件夹要处理一堆杂七杂八的后缀、实时推理还想让采集别被推理拖慢……这些需求糊在一起会很乱。所以模块内部再分三层(下面 §0.3 详述):

- **`core`**: 定义"什么是一帧"(数据类型)、"摄像头怎么配"(配置)、"所有源长什么样"(抽象协议)。是契约层。
- **`sources`**: 四个具体源(摄像头/视频/图片/文件夹)各自实现协议。是干活层。
- **`wrappers`**: 套在任意源外面的正交增强(后台采集 / 异步接口)。跟具体源解耦。

加上一个 `factory` 把"一个字符串"翻译成"对应的源"。整个模块就这点东西。

---

## 起点与终点

**起点**: 一个空的子目录, 推理脚本里还在直接 `cv2.VideoCapture` + 一堆 if 判断"这是图还是视频还是摄像头"。

**终点**: 一个自给自足、可整包拷走的 `frame_source/`:

```
frame_source/
├── __init__.py             (公共 API re-export)
├── README.md               (可拷走模块的身份证)
├── core/
│   ├── __init__.py
│   ├── types.py            (数据类型: SourceType / FrameInfo / Frame —— 一帧就是一张 BGR 图)
│   ├── config.py           (CameraConfig —— 只有摄像头需要配置)
│   └── base.py             (FrameSource 抽象协议; 含本版 open() 复位契约)
├── sources/
│   ├── __init__.py
│   ├── camera.py           (CameraSource —— 跨平台 + 后端协商 + 参数验证; 含 open 复位)
│   ├── video.py            (VideoSource —— seek 跳转 + grab 跳采; 含 open 复位)
│   └── image.py            (ImageSource + ImageFolderSource; 含 open 复位)
├── wrappers/
│   ├── __init__.py
│   ├── threaded.py         (ThreadedSource —— 后台线程采集, 解决"消费拖垮采集")
│   └── aio.py              (AsyncSource —— 给 async 调用方)
└── factory.py              (create_frame_source / threaded / async —— if/elif 直白派发)
```

终态用一个 `run()` 通吃四类源, 循环体一行不改:

```python
# 一行起, source 字符串通吃 4 类输入:
#   "0"=摄像头  "x.mp4"/"rtsp://..."=视频流  "x.jpg"=图  "./imgs/"=文件夹
def run(model, source: str):
    with create_frame_source(source) as src:
        for frame in src:
            results = model(frame.image)
            ...   # 你的后处理: 写库 / 叠框 / 报警, 想插哪插哪
```

⚠️ **设计点 (这一版刻意"不做什么")**: 我们**不引入多模态 Frame**(四种源每帧都只产一张 BGR 图, `Frame` 只装 `image` + `info` 就够)、**不做源注册表/插件机制**(四种源是固定的, if/elif 派发一目了然)、**不碰深度相机**。这些"不做"是有意的——一个模块的复杂度应该跟它的需求匹配, 给四个永不变的源套插件框架, 是用"框架的复杂度"换"并不需要的扩展性"。如果哪天真要支持"第三方在不改源码的前提下接入自定义相机"或"一帧多模态(RGBD)", 那才是该上注册表/多模态契约的时候——但那是另一个故事, 不在本模块范围内。

## 全部 git commit (终态)

```bash
# 自底向上, 一层一个原子提交; 全部 scope=frame_source, 便于 git log -- frame_source/ 单独看演进
git commit -m "feat(frame_source): core 层 —— 数据类型 + 摄像头配置 + 抽象协议"
git commit -m "feat(frame_source): sources 层 —— 摄像头/视频/图片/文件夹四个源(open 复位)"
git commit -m "feat(frame_source): wrappers 层 —— ThreadedSource 后台采集 + AsyncSource 异步接口"
git commit -m "feat(frame_source): factory 收口 —— if/elif 自动识别 + 三个便捷工厂 + 包入口"
git commit -m "test(frame_source): 自测脚本, 四源端到端 + wrapper + 复位 + 错误处理"
git commit -m "docs(frame_source): 实训讲义 + ADR"
```

**6 次提交, 自底向上**: 先立契约(core)→ 写四个源(sources)→ 加两个正交 wrapper → 工厂收口 + 包入口 → 自测 → 文档。注意全部是 `frame_source` scope: 这是个独立模块, 它的提交历史应该能单独 `git log -- frame_source/` 看出一条完整演进线。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 0: 立规矩

写代码之前先把"这个模块对外什么样、内部怎么切"定下来, 后面每个文件都照着这几条走。

## 0.1 模块边界: 零依赖宿主, 可整包拷走

第一条规矩最硬: **frame_source 不准 import 宿主项目的任何东西**。它只解决"出帧", 不碰推理、不碰宿主的配置体系、不碰宿主的日志封装。这样它才能 `cp -r` 到任何项目里活下来。

```bash
# 验证: frame_source 一行都不能 import 宿主项目(假设宿主顶层包叫 odplatform)
grep -rn "import odplatform\|from odplatform" frame_source/ --include="*.py"
# 期望: 0 输出。有输出就说明漏了依赖, 拷走就会崩。
```

> 这条规矩有个具体代价: 图片/视频的扩展名集合(`.jpg`/`.mp4`...)宿主项目可能也有一份, 但 frame_source **不准**去引用宿主那份, 必须自己存一份(见 §2.1 `IMAGE_EXTENSIONS`)。内容重叠是巧合, 不是依赖——这是"自给自足"的必要代价。

## 0.2 四条工程规矩

后面所有文件都遵守这四条, 先记下来:

- **规矩 A(协议统一)**: 所有源都实现同一个 `FrameSource` 协议(`open/read/close` + `seek`/`set_stride` + 上下文管理器 + 迭代器)。调用方永远只跟协议打交道, 不关心背后是摄像头还是文件。
- **规矩 B(fail-fast)**: 路径不存在、格式不支持、配置字段拼错——**当场报错, 报错带可读信息**, 别静默吞掉留个空对象让人后面 debug。
- **规矩 C(资源不漏)**: 每个源都支持上下文管理器, `with` 退出必关。摄像头/视频的句柄绝不能泄漏。
- **规矩 D(自有 SSoT)**: 扩展名等常量自己存一份, 不引用宿主(见 0.1)。

## 0.3 三层结构 + 收口

模块内部切三层, 依赖方向严格单向(下层不知道上层存在):

```
        ┌─────────────────────────────────────────────┐
            factory.py   把字符串翻译成具体源(if/elif)
        └─────────────────────────────────────────────┘
                    │依赖
        ┌───────────┴───────────┬─────────────────────┐
          wrappers/              sources/
          后台采集 / 异步          摄像头/视频/图片/文件夹
        └───────────┬───────────┴─────────────────────┘
                    │都依赖
        ┌───────────┴─────────────────────────────────┐
            core/   types(一帧是什么) + config + base(协议)
        └─────────────────────────────────────────────┘
```

- `core` 谁都不依赖(除了 numpy/pydantic), 是地基。
- `sources` 依赖 `core`(实现 base 的协议、返回 types 的数据类型)。
- `wrappers` 依赖 `core`(只认 `FrameSource` 协议), **不依赖任何具体源**——这是它能"对四个源一视同仁"的关键。
- `factory` 依赖以上全部, 是唯一知道"有哪几种源"的地方。

**构建顺序就按这个依赖图自底向上**: core → sources → wrappers → factory。下面每个阶段对应一层。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 1: 朴素方案的墙(前传速览)

在写"正确版本"之前, 先看看"不分层、直接糊"会撞成什么样——这样你才信后面那套结构不是过度设计。

假设你不抽象, 推理脚本里直接写:

```python
import cv2
src = "0"   # 或 "x.mp4" 或 "./imgs/"
if src.isdigit():
    cap = cv2.VideoCapture(int(src))
    while True:
        ret, img = cap.read()
        if not ret: break
        results = model(img)
        cv2.imshow("x", img); cv2.waitKey(1)
    cap.release()
elif src.endswith(".mp4"):
    cap = cv2.VideoCapture(src)
    ...   # 跟上面几乎一样, 又抄一遍
elif os.path.isdir(src):
    for fn in os.listdir(src):   # 后缀大小写? 排序? 坏图?
        img = cv2.imread(os.path.join(src, fn))
        ...
```

这段"能跑", 但你很快会撞上一连串墙:

| # | 撞墙 | 朴素写法的问题 | 本模块的解法 |
|---|---|---|---|
| ① | 摄像头参数不生效 | `cap.set(分辨率)` 设了不管用, 高帧率上不去 | CameraSource: 后端选择 + 参数顺序 + read 一帧触发协商(§3.3) |
| ② | 采集被拖慢 | `imshow`/推理一慢, 采集帧率被拖垮 | ThreadedSource: 采集放后台线程(§4.1) |
| ③ | 视频跳帧慢 | 想 3 倍速, `read()` 后扔掉, 白白解码 | VideoSource stride 用 `grab()`(§3.2) |
| ④ | 文件夹一堆坑 | 后缀大小写、排序不稳、坏图崩整个循环 | ImageFolderSource: `suffix.lower()` 过滤 + 排序 + 跳坏图(§3.1) |
| ⑤ | 视频 FPS 缺失 | 元数据没 fps, `seek(秒)` 算错帧号还不报警 | VideoSource: fps 缺失明确 warning + 回退(§3.2) |
| ⑥ | 重新跑一遍要重建 | 同一个 `cap` 重新跑, 状态乱, 帧号续着加 | 各源 `open()` 复位位置状态(§3 撞墙 C, 本版修复) |
| ⑦ | 资源泄漏 | 异常路径上忘了 `release()` | 上下文管理器, `with` 退出必关(规矩 C) |
| ⑧ | 调用方被细节淹没 | 推理脚本里全是 cv2 细节, 看不见业务 | 统一 `for frame in src` 协议, 细节全藏进源里 |

**这八面墙, 就是后面每一处设计的理由**。下面正式开工, 自底向上一层层来。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 2: core 层 —— 数据类型 / 配置 / 抽象协议

core 立三个文件: `types.py`(数据类型)、`config.py`(摄像头配置)、`base.py`(抽象基类, 协议层)。它们是后面一切的契约——sources 要实现 base 的协议、返回 types 的数据类型, wrappers 要包装 base 的协议。所以**先把契约钉死**。

## 2.1 `core/types.py` —— 一帧就是一张 BGR 图

🤔 **思考题(30 秒)**: 一帧数据该用什么类型表示? 直接传 `np.ndarray`(那张图)行不行?

**答**: 不行, 信息不够。下游不光要"图", 还要"这是第几帧""总共多少帧""哪个文件""多大尺寸""时间戳"——这些**元数据**得跟着图一起走。所以定义一个 `Frame` = `image`(图) + `info`(元数据 `FrameInfo`)。

但也别走另一个极端: 给 `Frame` 塞一堆乱七八糟的字段。四种常见源每帧都**只产一张 BGR 图**, 所以 `Frame` 只需要 `image` + `info` 两个字段, 干净利落, 不做"杂物袋"。

### 设计点

⚠️ **设计点 (frame_index 是源帧号, 不是采样序号)**: `FrameInfo.frame_index` 是**源帧号**——普通迭代是 0,1,2,3...; `stride=N` 跳采下是 0, N, 2N...(保留原始帧号, 不是 0,1,2 重新数)。这样设计是因为 `timestamp = frame_index / fps` 才算得对, 改成连续序号会让 N 倍速视频的时间戳错乱; 而且下游做帧标注、回放对照都需要"对应原视频的第几帧"。需要连续序号的, 自己 `enumerate` 一行的事。

⚠️ **设计点 (timestamp 语义按源不同, 故意不统一)**: 摄像头的 timestamp 是墙钟时间(自 open 起的秒数), 视频是媒体时间(在视频里的位置 = frame_index/fps), 图片恒为 0.0(没时间概念)。强行统一反而失真——这是"诚实地保留差异", 在 docstring 里写清楚比假装一致更好。

⚠️ **设计点 (规矩 D: 扩展名自己存)**: `IMAGE_EXTENSIONS` / `VIDEO_EXTENSIONS` 是本模块的自有 SSoT, 不引用宿主项目的同名常量。用 `frozenset` 是因为它不可变(防误改)且有 set 的 O(1) 查找。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : types.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : 核心数据类型 (SourceType / FrameInfo / Frame)
"""
frame_source 核心数据类型定义。

本模块只支持四种最常见的输入源:摄像头 / 视频 / 图片 / 图片文件夹。它们的共同点
是——**一帧就是一张 BGR 图**。所以 Frame 只需要装一张 image 加一份元数据, 不引入
任何多模态/副流的复杂度。

模块独立性原则(规矩 D):
    IMAGE_EXTENSIONS / VIDEO_EXTENSIONS 是 frame_source 的自有 SSoT(单一事实来源),
    与宿主项目同名常量内容重叠是巧合, 不是约束。本模块不引用任何外部基础设施常量,
    保证整包可拷贝至其他项目。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np


class SourceType(str, Enum):
    """输入源类型枚举(继承 str 便于序列化与日志)。"""
    CAMERA       = "camera"
    VIDEO        = "video"
    IMAGE        = "image"
    IMAGE_FOLDER = "image_folder"


# ── 模块自有 SSoT(frozenset 兼顾不可变 + set 语义)─────────────
IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff",
})
VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    ".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm",
})


@dataclass(frozen=True)
class FrameInfo:
    """
    帧元数据(不可变值对象)。

    所有输入源都返回 width/height, 供下游计算字体大小/缩放/输出尺寸等。

    ⚠️ 关于 frame_index 与 stride 的关系:
        frame_index 是**源帧号**, 不是"调用方收到的第几帧"。
        - 普通迭代(stride=1):  0, 1, 2, 3, ...
        - stride=N 跳采下:     0, N, 2N, 3N, ...(保留原始帧号)

        这样设计的理由:
          1. timestamp = frame_index / fps 才正确,
             改成连续序号会让 N 倍速视频的时间戳错乱;
          2. 下游做帧标注、回放对照都需要"对应原视频的第几帧";
          3. 需要连续序号的调用方自行 enumerate, 一行代码的事。

    关于 timestamp 字段的语义差异(已知不一致, 故意保留):
        - CameraSource:                    墙钟时间(自 open 起经过的秒数)
        - VideoSource:                     媒体时间(frame_index / fps, 即在视频里的位置)
        - ImageSource / ImageFolderSource: 0.0(无时间概念)
    """
    # 图像尺寸(所有源都有)
    width: int
    height: int

    # 源信息
    source_type: SourceType
    source_path: str

    # 序列信息
    frame_index: int = 0
    total_frames: Optional[int] = None

    # 时间信息(摄像头 / 视频)
    timestamp: float = 0.0
    fps: Optional[float] = None

    # 文件名(所有源都填充; 摄像头填 'camera:<id>' 占位)
    filename: Optional[str] = None

    @property
    def resolution(self) -> tuple[int, int]:
        """分辨率 (width, height)。"""
        return (self.width, self.height)


@dataclass
class Frame:
    """
    帧数据(统一返回类型)。

    Attributes:
        image: BGR 格式 ndarray(OpenCV 标准)。
               默认零拷贝传递, 调用方需持久保存时自行 .copy()。
        info : 帧元数据

    设计说明:
        Frame 刻意只有 image + info 两个字段, 不做"杂物袋"。四种常见源每帧都只产一张
        BGR 图, 这个契约就够了。下游统一 `frame.image` 拿图、`frame.info.*` 拿元数据,
        换任何一种源, 消费代码一行不用改——这正是抽象的意义。
    """
    image: np.ndarray
    info: FrameInfo

    # ── 便捷属性(少写一层 .info)──
    @property
    def resolution(self) -> tuple[int, int]:
        return self.info.resolution

    @property
    def width(self) -> int:
        return self.info.width

    @property
    def height(self) -> int:
        return self.info.height
```

🤔 **思考题(30 秒)**: `Frame.image` 注释说"默认零拷贝传递, 需持久保存自行 .copy()"。为什么不干脆每次都 copy 一份, 省得调用方踩坑?

**答**: 因为**性能**。视频实时推理一秒几十帧, 每帧无脑 copy 一张 1080p 图是可观的开销, 而绝大多数调用方拿到 `frame.image` 当场喂给模型就用完了, 根本不需要副本。所以默认零拷贝(快), 只在"要跨帧保留这张图"(比如存进列表攒一批)时让调用方自己 copy。把"省内存的常态"设成默认、"要副本的特例"交给调用方显式表达, 是对的取舍。(注意: 单张图片源 `ImageSource` 是个例外, 它 `read()` 时主动 copy 了一份——见 §3.1 的理由。)

## 2.2 `core/config.py` —— 只有摄像头需要配置

🤔 **思考题(30 秒)**: 视频、图片、文件夹要不要也来个 `VideoConfig` / `ImageConfig`?

**答**: 不需要。视频/图片/文件夹的"配置"就是一个路径字符串, 没有需要校验的参数。只有摄像头有一堆硬件参数(分辨率、帧率、后端、编码)需要在打开前设定并校验, 所以**只有一个 `CameraConfig`**。不为了"对称美"硬造空配置类——没有需求的抽象就是负担。

### 设计点

⚠️ **设计点 (用 Pydantic 而非 dataclass)**: `CameraConfig` 用 Pydantic v2 而不是普通 dataclass, 图的是**校验**: `width` 必须 `>0 且 ≤7680`、`backend` 只能是那四个字符串之一。`extra="forbid"` 让你把 `backend` 拼成 `backe nd` 时**当场 raise**, 而不是默默忽略你的设置然后纳闷"为什么没生效"(这正是规矩 B fail-fast 在配置层的落地)。

⚠️ **设计点 (Literal 锁取值)**: `backend` / `codec` 用 `Literal[...]` 而非裸 `str`, 拼写错误第一时间被 Pydantic 拦下, 连 IDE 都能自动补全合法值。

⚠️ **设计点 (不可冻结)**: 没设 `frozen`, 因为工厂要用 `model_copy(update={"camera_id": ...})` 生成副本替换设备号(见 §5)。但配了 `validate_assignment=True`, 后续赋值也走校验, 不留口子。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : config.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : 摄像头硬件/采集配置 (Pydantic v2)
"""
源配置(基于 Pydantic v2 BaseModel, 不继承宿主项目内部配置基类)。

四种常见源里, 只有摄像头有一堆需要校验的硬件/采集参数(分辨率、帧率、后端、编码),
所以这里只有一个 CameraConfig。视频/图片/文件夹的"配置"就是一个路径, 不需要配置类。

设计原则:
    - 配置层不绑 logger: 验证失败直接 raise ValidationError, 由调用方决定记录方式
    - 字段封闭取值用 Literal, 拼写错误第一时间被 Pydantic 拦下
    - 不可冻结: factory 需要 model_copy(update=...) 替换 camera_id 等
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CameraBackend = Literal["auto", "msmf", "dshow", "v4l2"]
CameraCodec   = Literal["MJPG", "YUYV", "H264", "MP4V"]


class CameraConfig(BaseModel):
    """
    cv2 摄像头配置(Pydantic v2)。

    示例:
        config = CameraConfig()                                  # 默认
        config = CameraConfig(width=1280, height=720, fps=90, backend="msmf")

    字段说明:
        camera_id : OpenCV 设备 ID(≥ 0)
        width/height/fps : 请求值(实际生效以 set+get 协商结果为准)
        backend   : auto(系统自选) / msmf(Win 高帧率) / dshow(Win 兼容) / v4l2(Linux)
        codec     : FOURCC 编码, 高帧率必须 MJPG
    """

    model_config = ConfigDict(
        extra="forbid",              # 拼错字段名第一时间拦下
        validate_assignment=True,    # 后续赋值也走验证
    )

    camera_id: int = Field(default=0,    ge=0,            description="OpenCV 设备 ID")
    width:     int = Field(default=1280, gt=0, le=7680,   description="请求分辨率宽")
    height:    int = Field(default=720,  gt=0, le=4320,   description="请求分辨率高")
    fps:       int = Field(default=30,   gt=0, le=1000,   description="请求帧率")

    backend: CameraBackend = Field(default="auto", description="摄像头后端")
    codec:   CameraCodec   = Field(default="MJPG", description="FOURCC 编码")

    def get_resolution(self) -> tuple[int, int, int]:
        """返回 (width, height, fps) 三元组。"""
        return (self.width, self.height, self.fps)
```

## 2.3 `core/base.py` —— 抽象协议(整个模块的骨架)

这是 core 里最重要的文件: 定义 `FrameSource` 抽象基类, 规定所有源(以及 wrapper)长什么样。把它钉死了, 后面四个源只是"填空", wrapper 只是"套壳"。

协议包含五组东西:
- **三个抽象方法**: `open()` / `read()` / `close()` —— 子类必须实现。
- **`seek`**(一次性跳转): 基类默认"不支持"(返回 False + warning), 能跳的源(视频/文件夹)覆盖它。
- **`set_stride`**(持续跳采): 基类登记 `_stride` 意图, 真正跳帧由子类在 `read()` 里实现。
- **上下文管理器**: `__enter__` 调 `open()`、`__exit__` 调 `close()` —— 落实规矩 C(资源不漏)。
- **迭代器**: `__next__` 调 `read()`, 拿到 None 就 `StopIteration` —— 落实"统一逐帧"语义。

### 关于 stride 为什么在协议层, 而不是做成一个 wrapper

这是个值得想清楚的设计判断。"跳采"完全可以写成一个 `StrideWrapper` 套在源外面, 为什么把它放进协议(基类的 `set_stride` + 子类 `read()` 里实现)?

1. **语义同族**: `set_stride` 跟 `seek` 是一类东西——都是"源对自己出帧行为的控制原语"。放一起更内聚。
2. **性能要求(最关键)**: 每个源能用**自己最快的跳帧手段**。VideoSource 用 `cap.grab()` 跳过 YUV→BGR 转换; ImageFolderSource 直接跳数组索引、零 IO。而一个通用 wrapper 只能"`read()` 一帧再扔掉", 白白解码/读盘——把性能全浪费了。
3. **生命周期**: `set_stride()` 能在迭代过程中动态切换(跑到第 100 帧突然改成 5 倍速), wrapper 难做到这么灵活。

⚠️ **设计点 (`__exit__` 返回 False 不吞异常)**: 上下文管理器 `__exit__` 返回 `False`——意思是"我清理完资源, 但异常该往上抛还是往上抛, 我不吞"。如果返回 True 就把 `with` 块里的异常吃掉了, 调用方还以为一切正常。资源清理和异常传播是两件事, `close()` 负责清理, 异常照样传出去。

### 关于"重新 open 能否重头迭代"的契约(本版要兑现的承诺)

基类 docstring 写明一条契约: **同一 source 对象迭代一次即耗尽(标准迭代器协议); 需要重头迭代, 重新 `open()` 或重新创建对象都可以。** 注意协议层在这里只**声明**契约, **兑现**它是各源 `open()` 的责任——`open()` 必须把自己的位置状态(帧号 / 读取计数 / 当前索引)清零, 否则"重新 open 重头来"就是一句空话。这正是本版要修的坑(§3 撞墙 C): 协议层的代码一个字不用改, 改的是各源 `open()` 的实现。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : base.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : FrameSource 抽象基类 — 统一所有输入源的协议
"""
帧源抽象基类。定义所有输入源(摄像头/视频/图片/包装器)共享的协议:

    open / read / close
      + seek           (一次性跳转, 子类按能力覆盖)
      + set_stride     (持续跳采, 子类按能力在 read() 内实现)
      + 上下文管理器
      + 迭代器

帧位置控制原语(同族, 协议层):
    seek(frame=N)      一次性跳到第 N 帧
    seek(time_sec=T)   一次性跳到 T 秒
    set_stride(N)      之后每 N 帧产出 1 帧, 直到再次调用

为什么 stride 是协议方法而不是 wrapper:
    1. 语义同族 — 跟 seek 一样是"源对自身行为的控制原语"
    2. 性能要求 — 每个源能用自己最快的跳帧手段:
       VideoSource 用 cap.grab() 跳过 YUV→BGR 转换;
       ImageFolderSource 直接跳索引, 零 IO;
       wrapper 路径只能 read-and-discard, 浪费完整解码。
    3. 生命周期 — set_stride() 可在迭代过程中动态切换。

子类实现 stride 的模板(在 read() 开头加 4 行):
    def read(self):
        # stride>1 且非首帧: 用本源最快的方式跳过 stride-1 帧
        if self._stride > 1 and self._frame_index > 0:
            if not self._fast_skip(self._stride - 1):
                return None
        ...原有读帧逻辑...

    其中 _fast_skip 是私有方法, 各源自己写, 不入协议。
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Iterator, Optional

from .types import Frame, SourceType


logger = logging.getLogger(__name__)


class FrameSource(ABC):
    """
    帧源抽象基类。

    标准用法:
        with SomeSource(...) as source:
            for frame in source:
                process(frame.image)
                print(frame.width, frame.height)

    跳帧(seek, 一次性):
        source.seek(frame=100)      # 跳到第 100 帧
        source.seek(time_sec=3.5)   # 跳到 3.5 秒

    跳采(stride, 持续):
        source.set_stride(3)        # 之后每 3 帧产出 1 帧
        source.set_stride(1)        # 恢复逐帧

    注意:
        同一 source 对象只能迭代一次(标准迭代器协议)。
        需要重头迭代请重新 open() 或重新创建对象。
    """

    def __init__(self, source_path: str):
        self.source_path  = source_path
        self._frame_index = 0
        self._stride      = 1     # 默认透传; >1 时每 stride 帧产出 1 帧
        self._start_time  = time.time()

    # ── 子类必须实现 ────────────────────────────────────────
    @abstractmethod
    def open(self) -> bool:
        """打开输入源,返回是否成功"""

    @abstractmethod
    def read(self) -> Optional[Frame]:
        """
        读取一帧,源耗尽时返回 None。

        实现 stride 的源(VideoSource / ImageFolderSource)在本方法开头
        做"跳过 stride-1 帧"动作; 不实现 stride 的源(CameraSource /
        ImageSource)忽略 self._stride 即可。
        """

    @abstractmethod
    def close(self) -> None:
        """关闭输入源,释放资源"""

    @abstractmethod
    def get_source_type(self) -> SourceType:
        """返回输入源类型"""

    # ── seek 协议(默认不支持,子类按需覆盖)─────────────────
    def seek(
        self,
        frame: Optional[int] = None,
        time_sec: Optional[float] = None,   # 参数名 time_sec 避免与 time 模块冲突
    ) -> bool:
        """
        跳转到指定位置(基类默认不支持)。

        Args:
            frame:    目标帧号(从 0 开始)
            time_sec: 目标时间(秒)

        Returns:
            是否成功
        """
        logger.warning(f"{self.__class__.__name__} 不支持 seek 操作")
        return False

    @property
    def seekable(self) -> bool:
        """是否支持 seek,子类覆盖返回 True"""
        return False

    # ── stride 协议(持续跳采)──────────────────────────────
    def set_stride(self, stride: int) -> None:
        """
        设置跳采步长。stride=1 透传(默认), stride=N 每 N 帧产出 1 帧。

        基类只登记意图(self._stride), 实际跳帧由子类在 read() 内实现。
        不支持/不适用跳帧的源(摄像头、单图)应覆盖本方法,
        给出警告或忽略。

        Args:
            stride: ≥1 的整数。
        Raises:
            ValueError: stride < 1
        """
        if stride < 1:
            raise ValueError(f"stride 必须 ≥ 1, 收到: {stride}")
        self._stride = stride
        if stride > 1:
            logger.debug(f"{self.__class__.__name__}: stride 设为 {stride}")

    @property
    def stride(self) -> int:
        """当前跳采步长(1 表示透传)"""
        return self._stride

    # ── 上下文管理器协议 ────────────────────────────────────
    def __enter__(self) -> "FrameSource":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False  # 不吞异常

    # ── 迭代器协议 ──────────────────────────────────────────
    def __iter__(self) -> Iterator[Frame]:
        return self

    def __next__(self) -> Frame:
        frame = self.read()
        if frame is None:
            raise StopIteration
        return frame
```

🤔 **思考题(30 秒)**: `__enter__` 里调了 `self.open()` 但**没检查返回值**(open 返回 False 时 with 块照样进去了)。这是 bug 吗?

**答**: 这是个**有意的取舍, 但确实是边界粗糙处**, 诚实地说它可以更严。当前设计下, 如果 `open()` 返回 False(摄像头没打开), `with` 块照样进入, 然后第一次 `read()` 返回 None, `for` 循环立刻 `StopIteration`——**循环体一次都不执行, 优雅空跑**。不会崩, 但用户可能困惑"为什么啥也没发生"。更严的做法是 `__enter__` 里 `if not self.open(): raise RuntimeError(...)`。这里选择不抛, 是把"源打不开"也当成"源耗尽"的一种(都通过 read 返回 None 表达), 让调用方用统一方式处理。你接手时如果想让它更严, 加那行 raise 也完全合理。

## 2.4 `core/__init__.py` —— core 子包入口

把 core 的三个文件对外 re-export, 让上层 `from ..core import FrameSource, Frame, CameraConfig` 一行拿到, 不用关心它们具体在哪个文件。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : __init__.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : core 子包入口 — 核心类型与抽象
"""core 子包:抽象基类、数据类型、配置定义。"""
from __future__ import annotations

from .types  import (
    SourceType, FrameInfo, Frame,
    IMAGE_EXTENSIONS, VIDEO_EXTENSIONS,
)
from .config import CameraConfig, CameraBackend, CameraCodec
from .base   import FrameSource

__all__ = [
    "SourceType",
    "FrameInfo",
    "Frame",
    "IMAGE_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "CameraConfig",
    "CameraBackend",
    "CameraCodec",
    "FrameSource",
]
```

## 2.5 git commit (core 层)

```bash
git add frame_source/core/
git commit -m "feat(frame_source): core 层 —— 数据类型 + 摄像头配置 + 抽象协议

- types.py: Frame(image+info, 单张 BGR)/ FrameInfo / SourceType(四种)/ 自有扩展名 SSoT
- config.py: CameraConfig(Pydantic v2, extra=forbid 校验)
- base.py: FrameSource 抽象协议(open/read/close + seek + set_stride + 上下文 + 迭代器)
          明确'重新 open 即重头迭代, 各源 open() 负责复位'契约"
```

契约钉死了。下一阶段填四个源。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 3: sources 层 —— 四个具体源

四种源、三个文件: `image.py`(里面两个类: 单图 + 文件夹)、`video.py`、`camera.py`。每个都实现 §2.3 的 `FrameSource` 协议。

本阶段会同时兑现 §2.3 那条契约——也就是本版要修的坑: 三个源的 `open()` 都要"复位位置状态", 让"重新 open 同一对象"能干净重头迭代。先从最能暴露这个坑的图片源讲起。

## 3.1 `image.py` —— ImageSource + ImageFolderSource

单张图片和图片文件夹放一个文件, 因为它们都基于"读图"。

🧱 **撞墙 C(本版修复): 重新 open 同一对象, 居然读不到帧**

先看这个坑, 因为它在图片源上最直观。基类 docstring 承诺"重新 open 能重头迭代"。但如果 `open()` 只是"重新加载图片 / 重新扫描文件夹", 却**不复位读取计数**, 就会这样:

```python
s = ImageSource("a.jpg")
s.open(); list(s)        # 读到 1 帧 ✓, 此时 _read_count = 1
s.close()
s.open(); list(s)        # ✗ 读到 0 帧! _read_count 还停在 1, read() 一上来就 return None

f = ImageFolderSource("./imgs")
f.open(); list(f)        # 读到 10 帧 ✓, 此时 _current_index = 10
f.close()
f.open(); list(f)        # ✗ 读到 0 帧! _current_index 还停在 10, 已经"在末尾"了
```

**根因**: `open()` 重建了"数据"(图 / 文件列表), 却没复位"读到哪了"这个**位置状态**。**修法极简: 在每个源的 `open()` 开头(或加载成功后)把自己的位置计数清零**——`ImageSource` 清 `_read_count`、`ImageFolderSource` 清 `_current_index`。这正好兑现了 §2.3 的契约: 协议层声明"重新 open 能重头来", 而兑现它是各源 `open()` 的责任。

⚠️ **设计点 (stride 不复位)**: 注意复位的是**位置状态**(读到哪了), 不是 **stride**(每隔几帧取一帧)。stride 是用户配置的"行为", 应该跨 open 保留——你设了 3 倍速, 重新 open 还该是 3 倍速。所以 `open()` 只清位置、不动 `_stride`。

### 三个工程细节(写进代码注释)

⚠️ **设计点 (文件夹用 suffix.lower() 过滤, 不用 glob)**: 列图片用 `f.suffix.lower() in IMAGE_EXTENSIONS` 过滤, 而不是 `glob("*.jpg")`。因为 Linux 文件系统上真实存在 `.JPG` / `.Jpeg` / `.PNG` 这种混合大小写后缀, glob 一种写法漏一片, 列两遍(`*.jpg` + `*.JPG`)又丑又不全。`suffix.lower()` 一次干净覆盖。

⚠️ **设计点 (排序 + 跳坏图)**: 文件列表 `sorted()` 保证遍历顺序稳定(否则两次运行顺序可能不同); `read()` 里 `imread` 返回 None(坏图/非图)就 `warning` 一句跳过, **不让一张坏图崩掉整个循环**(规矩 B 的温柔版: 单帧失败可恢复, 就别让它牵连全局)。

⚠️ **设计点 (单图 read 一次就耗尽 + 主动 copy)**: `ImageSource.read()` 第二次调用返回 None(符合迭代器"耗尽即停")。而且它 `return Frame(image=self._image.copy(), ...)` 主动 copy 了一份——单图源整个生命周期就持有这一张图, 如果零拷贝传出去被下游 `cv2.rectangle` 之类原地改了, 会污染这唯一的副本。单图只读一次, copy 的开销可忽略, 换来安全。

⚠️ **设计点 (文件夹 stride 零 IO)**: `ImageFolderSource` 的 stride 直接跳 `_current_index`(`+= stride-1`), **跳过的图连 `cv2.imread` 都不调**。从 10000 张里每 10 张取 1 张, 只 imread 约 1000 张, 省掉 9000 次磁盘读。这是 wrapper 路径(read 一张再扔)绝对做不到的。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : image.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : 单张图片 / 图片文件夹输入源
"""图片输入源(单张 + 文件夹两种形态)。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from ..core.base  import FrameSource
from ..core.types import Frame, FrameInfo, IMAGE_EXTENSIONS, SourceType


logger = logging.getLogger(__name__)


class ImageSource(FrameSource):
    """
    单张图片输入源。

    read() 只返回一次,第二次调用返回 None,符合迭代器"耗尽即停"语义。

    stride 说明:
        单图源只有一帧, stride 无意义, 静默忽略。

    示例:
        with ImageSource("test.jpg") as img:
            frame = img.read()
            print(f"尺寸: {frame.width}x{frame.height}")
    """

    def __init__(self, image_path: str):
        super().__init__(image_path)
        self._image: Optional[np.ndarray] = None
        self._read_count = 0
        self._filename = Path(image_path).name

    def open(self) -> bool:
        # ── 复位读取计数: 让"重新 open 同一对象"能再次读到那一帧 ──
        # 不复位的话, 重开后 _read_count 仍 >0, read() 会直接返回 None(读到 0 帧)。
        self._read_count = 0

        self._image = cv2.imread(self.source_path)
        if self._image is None:
            logger.error(f"无法读取图片: {self.source_path}")
            return False
        h, w = self._image.shape[:2]
        logger.info(f"图片已加载: {self._filename} ({w}x{h})")
        return True

    def read(self) -> Optional[Frame]:
        # 单图源 stride 无意义, 忽略 self._stride
        if self._image is None or self._read_count > 0:
            return None

        h, w = self._image.shape[:2]
        info = FrameInfo(
            width=w, height=h,
            source_type=SourceType.IMAGE,
            source_path=self.source_path,
            frame_index=0, total_frames=1,
            filename=self._filename,
        )
        self._read_count += 1
        # 单图源 .copy() 防止外部修改影响后续(虽然 read 只回一次,但保留语义安全)
        return Frame(image=self._image.copy(), info=info)

    def close(self) -> None:
        self._image = None

    def get_source_type(self) -> SourceType:
        return SourceType.IMAGE


class ImageFolderSource(FrameSource):
    """
    图片文件夹输入源。

    注意: 文件夹内每张图片尺寸可能不同,请始终用 frame.width / frame.height
         获取当前帧的实际尺寸,不要假设统一。

    stride 实现:
        直接跳前进索引 self._current_index, **跳过的图片连 cv2.imread 都不会
        调用**, 磁盘 IO 也省掉。stride=10 时, 10000 张图只 imread 约 1000 张。
        这是 wrapper 路径绝对做不到的优化 — wrapper 只能 read 一张再丢弃。

    示例:
        with ImageFolderSource("./images") as folder:
            for frame in folder:
                print(f"{frame.info.filename}: {frame.width}x{frame.height}")

        # 跳帧
        with ImageFolderSource("./images") as folder:
            folder.seek(frame=10)
            frame = folder.read()

        # 训练集采样
        with ImageFolderSource("./images") as folder:
            folder.set_stride(10)   # 每 10 张采 1 张
            for frame in folder:
                ...
    """

    def __init__(self, folder_path: str):
        super().__init__(folder_path)
        self._image_files: List[Path] = []
        self._current_index = 0

    def open(self) -> bool:
        # ── 复位索引: 让"重新 open 同一对象"能从头遍历 ──
        # 不复位的话, 重开后 _current_index 仍停在上次的末尾, read() 直接读到 0 帧。
        self._current_index = 0

        folder = Path(self.source_path)
        if not folder.is_dir():
            logger.error(f"不是有效文件夹: {self.source_path}")
            return False

        # ── 撞墙记录: 用 suffix.lower() 过滤而不是 glob("*.jpg")+glob("*.JPG") ──
        # 处理 .Jpg / .jPeG 等混合大小写后缀(Linux 文件系统上真实存在)。
        self._image_files = sorted([
            f for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        ])

        if not self._image_files:
            logger.error(f"文件夹中没有支持的图片: {self.source_path}")
            return False

        logger.info(f"文件夹已加载: {folder.name} ({len(self._image_files)} 张)")
        return True

    def read(self) -> Optional[Frame]:
        """读取下一张图片,跳过无法解码的坏图。stride>1 时直接跳索引。"""
        # ── stride 跳采(非首读时, 前进 stride-1 步, 零 IO)──
        # 不在首读跳: 让 stride=N 的输出是 0, N, 2N, ... 而不是 N, 2N, ...
        if self._stride > 1 and self._current_index > 0:
            self._current_index += (self._stride - 1)

        while self._current_index < len(self._image_files):
            image_path = self._image_files[self._current_index]
            image = cv2.imread(str(image_path))

            if image is None:
                logger.warning(f"无法读取,已跳过: {image_path.name}")
                self._current_index += 1
                continue

            h, w = image.shape[:2]
            info = FrameInfo(
                width=w, height=h,
                source_type=SourceType.IMAGE_FOLDER,
                source_path=self.source_path,
                frame_index=self._current_index,
                total_frames=len(self._image_files),
                filename=image_path.name,
            )
            self._current_index += 1
            return Frame(image=image, info=info)

        return None  # 所有图片遍历完毕

    def seek(
        self,
        frame: Optional[int] = None,
        time_sec: Optional[float] = None,
    ) -> bool:
        """
        跳转到指定图片索引。

        Args:
            frame:    目标图片索引(从 0 开始)
            time_sec: 图片文件夹无时间概念,传入会 warning 并返回 False
        """
        if time_sec is not None:
            logger.warning("图片文件夹不支持按时间跳转,请使用 frame 参数")
            return False
        if frame is None:
            logger.error("必须指定 frame 参数")
            return False

        total = len(self._image_files)
        target = max(0, min(frame, total - 1)) if total > 0 else 0
        self._current_index = target
        logger.debug(f"图片文件夹跳转到索引 {target}")
        return True

    @property
    def seekable(self) -> bool:
        return True

    def close(self) -> None:
        self._image_files = []
        logger.info("文件夹已关闭")

    def get_source_type(self) -> SourceType:
        return SourceType.IMAGE_FOLDER
```

## 3.2 `video.py` —— VideoSource(grab 跳采 + seek 跳转)

视频源比图片多两样: `seek`(按帧号/时间一次性跳转)和高性能 stride。它也是网络流(rtsp/http)的承载体——cv2.VideoCapture 吃 URL 和吃文件路径是一样的, 所以工厂把网络流也路由到这里。

🧱 **撞墙 D: 视频 3 倍速预览, 用 `read()` 丢帧太慢**

想 3 倍速预览, 朴素写法是 `read()` 三帧、用第三帧、扔前两帧。但 OpenCV 的视频管线大致是:

```
demuxer → decoder → YUV → BGR 颜色空间转换 → ndarray 分配 → 返回
```

`read()` 走完整条; 而最贵的是后两步(YUV→BGR 转换 + ndarray 分配)。被你扔掉的那两帧, 白白付了这两步的钱。

**解法**: 用 `cap.grab()` 跳过中间帧。`grab()` 只走到 decoder, **不做 YUV→BGR 和 ndarray 分配**。所以 stride 实现成 `grab() ×(stride-1) + read() ×1`: 中间帧只解码不转换, 在 1080p H.264 上比全 read 快 3~5 倍。

⚠️ **设计点 (stride 用 grab 不用 seek)**: 为什么不用 `cap.set(POS_FRAMES, N)` 直接跳? 因为 `set` 会被解码器**对齐到最近的关键帧**, 落点不精确——`seek(frame=10)` 实际可能停在第 6 帧附近。stride 要的是"精确每隔 N 帧", 所以用 `grab()` 逐帧步进(精确到帧), 不用 seek。代价是比 seek 慢一点, 但仍远比全 read 快。(这也是下面 seek 那条坑的来源。)

🧱 **撞墙 E: 视频没有 fps 元数据, `seek(秒)` 算错帧号还不吭声**

有些视频(尤其转码过的、网络流)拿不到 fps 元数据, `cap.get(CAP_PROP_FPS)` 返回 0。如果静默当 0 用, `seek(time_sec=T)` 要靠 `T * fps` 算目标帧号, 直接算出 0 或炸——而调用方一无所知。

**解法**: open 时检查 fps, 缺失就**回退到 30 并打一条明确 warning**, 告诉调用方"seek(秒) 结果可能不准"。不静默, 是规矩 B。

⚠️ **设计点 (本版修复: open 复位 frame_index)**: 同 §3.1 撞墙 C, `VideoSource.open()` 开头补 `self._frame_index = 0`。否则重新 open 后, cap 从头解码、但帧号却从上次的尾号续着加(读完 30 帧重开, 第一帧报 frame_index=30), 画面和帧号对不上。

⚠️ **设计点 (seek 与 stride 正交)**: `seek` 后会同步 `_frame_index`, 之后的 stride 跳帧从新位置之后再算。两者互不打架。`seek` 还做了边界夹紧(目标帧号夹到 `[0, total-1]`)和"frame/time_sec 只能给一个"的校验。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : video.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : 视频文件输入源(支持 seek 按帧号/时间跳转 + stride 跳采)
"""
视频文件输入源。

性能要点 — stride 用 cap.grab() 而非 cap.read():
    OpenCV 的视频管线大致是:
        demuxer → decoder → YUV → BGR 颜色空间转换 → ndarray 分配 → 返回
    其中 YUV→BGR 转换和 ndarray 分配是最贵的两步。
    cap.read() 走完整路径; cap.grab() 只走到 decoder, 不做后两步。

    在 1080p H.264 上, grab() 大约比 read() 快 3~5 倍。stride=10 时:
        read 路径: 解码 10 帧 + 10 次完整后处理 ≈ 慢
        grab 路径: 解码 10 帧 + 1 次完整后处理   ≈ 快很多

    本类的 stride 实现用 grab() ×(stride-1) + read() ×1 的组合, 拿到性能。

性能要点 — seek 在低 GOP 视频上不精确:
    cap.set(CAP_PROP_POS_FRAMES, N) 会被解码器对齐到最近的关键帧, 落点
    不精确。stride 跳帧场景对精度敏感, 因此实现上**只用 grab 不用 seek** ——
    grab() 是逐帧步进, 精确到帧。代价是相对 seek 慢一些, 但仍远比 read 快。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import cv2

from ..core.base  import FrameSource
from ..core.types import Frame, FrameInfo, SourceType


logger = logging.getLogger(__name__)


class VideoSource(FrameSource):
    """
    视频文件输入源,支持按帧号/时间跳转 + 持续跳采。

    示例:
        # 普通迭代
        with VideoSource("test.mp4") as video:
            for frame in video:
                print(f"帧 {frame.info.frame_index}/{frame.info.total_frames}")
                print(f"尺寸: {frame.width}x{frame.height}")

        # seek 跳转
        with VideoSource("test.mp4") as video:
            video.seek(frame=100)        # 跳到第 100 帧
            video.seek(time_sec=3.5)     # 跳到 3.5 秒
            frame = video.read()

        # stride 3 倍速预览(grab 跳帧, 比 read 快 3-5 倍)
        with VideoSource("test.mp4") as video:
            video.set_stride(3)
            for frame in video:
                ...  # frame_index = 0, 3, 6, 9, ...
    """

    def __init__(self, video_path: str):
        super().__init__(video_path)
        self._cap: Optional[cv2.VideoCapture] = None
        self._width        = 0
        self._height       = 0
        self._fps          = 0.0
        self._total_frames = 0
        self._filename     = Path(video_path).name

    def open(self) -> bool:
        # ── 复位位置状态: 让"重新 open 同一对象"能真正重头迭代 ──
        # 不复位的话, 重开后 frame_index 会从上次的尾号继续累加, 而 cap 已从头
        # 解码, 报出来的帧号与实际画面对不上。
        self._frame_index = 0

        self._cap = cv2.VideoCapture(self.source_path)
        if not self._cap.isOpened():
            logger.error(f"无法打开视频: {self.source_path}")
            return False

        self._width        = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height       = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # ── 撞墙记录: FPS 元数据缺失时不静默回退,明确 warning ──
        # 否则 seek(time_sec=...) 会用错误 fps 计算帧号,调用方一无所知。
        raw_fps = self._cap.get(cv2.CAP_PROP_FPS)
        if not raw_fps or raw_fps <= 0:
            logger.warning(
                f"视频 '{self._filename}' FPS 元数据缺失或为 0,"
                f"已回退到默认值 30fps。seek(time_sec=...) 结果可能不准确。"
            )
            self._fps = 30.0
        else:
            self._fps = raw_fps

        logger.info(f"视频已打开: {self._filename}")
        logger.info(f"  分辨率: {self._width}x{self._height} @ {self._fps:.1f}fps")
        logger.info(f"  总帧数: {self._total_frames}")
        return True

    def read(self) -> Optional[Frame]:
        if self._cap is None:
            return None

        # ── stride 跳帧(非首帧时, 用 grab 跳过 stride-1 帧)──
        # grab() 只走到解码器, 不做 YUV→BGR 转换和 ndarray 分配,
        # 在 1080p H.264 上比完整 read() 快 3~5 倍。
        if self._stride > 1 and self._frame_index > 0:
            for _ in range(self._stride - 1):
                if not self._cap.grab():
                    return None     # 源耗尽
                self._frame_index += 1

        ret, image = self._cap.read()
        if not ret:
            return None

        info = FrameInfo(
            width=self._width,
            height=self._height,
            source_type=SourceType.VIDEO,
            source_path=self.source_path,
            frame_index=self._frame_index,
            total_frames=self._total_frames,
            timestamp=self._frame_index / self._fps if self._fps > 0 else 0.0,
            fps=self._fps,
            filename=self._filename,
        )
        self._frame_index += 1
        return Frame(image=image, info=info)

    def seek(
        self,
        frame: Optional[int] = None,
        time_sec: Optional[float] = None,
    ) -> bool:
        """
        跳转到指定位置。

        Args:
            frame:    目标帧号(从 0 开始)
            time_sec: 目标时间(秒)

        注:
            seek 与 stride 正交 — seek 后下一次 read() 视为"新起点",
            stride 的跳帧从那个位置之后再开始(因为 _frame_index 会被同步)。
        """
        if self._cap is None:
            logger.error("视频未打开,无法 seek")
            return False

        # frame 和 time_sec 必须且只能指定一个
        if (frame is None) == (time_sec is None):
            logger.error("frame 和 time_sec 必须且只能指定一个")
            return False

        target = int(time_sec * self._fps) if time_sec is not None else int(frame)
        # 边界夹紧,防越界
        target = max(0, target)
        if self._total_frames > 0:
            target = min(target, self._total_frames - 1)

        ok = self._cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        if ok:
            self._frame_index = target
            logger.debug(f"视频跳转到帧 {target}")
        else:
            logger.warning(f"视频跳转失败:目标帧 {target}")
        return ok

    @property
    def seekable(self) -> bool:
        return True

    @property
    def duration(self) -> float:
        """视频时长(秒);元数据不全时返回 0.0"""
        if self._fps > 0 and self._total_frames > 0:
            return self._total_frames / self._fps
        return 0.0

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("视频已关闭")

    def get_source_type(self) -> SourceType:
        return SourceType.VIDEO
```

🤔 **思考题(30 秒)**: stride 跳帧时, 为什么要判断 `self._frame_index > 0` 才跳(首帧不跳)?

**答**: 为了让 `stride=N` 的输出是 `0, N, 2N, ...` 而不是 `N, 2N, ...`。如果首次 read 就先跳 N-1 帧, 第一帧拿到的就是第 N 帧了, 丢了第 0 帧。判断"非首帧才跳", 保证序列从 0 开始, 跟"帧号 = 源帧号"的约定一致。

## 3.3 `camera.py` —— CameraSource(本模块最硬的一块)

摄像头是四个源里唯一碰硬件的, 也是撞墙最密集的。它要处理跨平台后端、参数协商、"设了不生效"的验证。**这三条撞墙记录是真金白银踩出来的, 改动前务必先理解**。

🧱 **撞墙 F①: MSMF 后端必须在创建 VideoCapture 之前设环境变量**

Windows 的 MSMF 后端会自动插入一个"硬件色彩转换"滤镜(HW Transforms), 它会让帧率掉 20~30%。关掉它要设环境变量 `OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS=0`, 而且**必须在 `cv2.VideoCapture(...)` 创建之前设**, 创建之后再设就晚了, 不生效。

🧱 **撞墙 F②: 参数设置顺序必须是 宽高 → FOURCC → FPS**

顺序错了高帧率请求会被驱动重新协商时覆盖, 完全失效。正确顺序背后的逻辑:
1. **先设分辨率**: 驱动据此筛选可用的"媒体类型"列表;
2. **再设 FOURCC**(如 MJPG): 从上一步筛出的列表里选编码格式;
3. **最后设 FPS**: 格式锁定后才约束帧率。

倒过来设, 等于在格式还没定时就要帧率, 驱动一协商就把你的设置冲了。

🧱 **撞墙 F③: `set()` 是请求不是命令, 必须 read 一帧触发协商再 get 读回真实值**

`cap.set(分辨率)` 只是"登记意图", 驱动要到**第一次 `read()`** 时才真正跟摄像头硬件协商、锁定格式。所以 open 流程里必须: set 完 → **read 一帧触发协商** → 再 `get` 读回**实际生效**的分辨率/帧率。少了那次 read, 你 get 到的还是"请求值"而非"实际值"。

⚠️ **设计点 ("我设了"≠"它生效了", 要验证并 warning)**: 读回实际值后, 跟请求值比对, 不一致就 warning(分辨率不符 / 帧率低于请求的 90%)。摄像头/驱动经常不支持你要的档位, 它会默默给你个最接近的——不验证不告警, 你就以为自己跑在 90fps, 实际是 30。

⚠️ **设计点 (摄像头不支持 stride)**: `CameraSource` 覆盖 `set_stride`, 对 `stride>1` 给 warning 并强制锁回 1。理由: 摄像头硬件按固有 fps 产帧, `read` 后扔掉既不省采集开销, 又会让"latest 缓冲"里的"最新帧"反而更旧, 加大延迟。实时降频请用 ThreadedSource 的 latest 缓冲 + 主循环按节奏拉(§4.1), 比 stride 优雅。

⚠️ **设计点 (本版修复: open 复位)**: open 末尾补 `self._frame_index = 0`(连同已有的 `self._start_time = time.time()`), 让重新 open 后帧号和 timestamp 都从 0 起。对实时流这主要是计数一致性, 但跟其它源保持同一套"重新 open 即重头"的语义。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : camera.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : 摄像头输入源 — 跨平台 + 后端协商 + 参数验证
"""
摄像头输入源。

工程要点(均为撞墙记录,改动前请先理解):
    1. MSMF 后端必须在 cv2.VideoCapture 创建之前设置环境变量
       OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS=0,否则帧率下降 20-30%
    2. 参数设置顺序必须是: 宽高 → FOURCC → FPS,
       否则 MSMF 下高帧率请求会被驱动重新协商时覆盖,完全失效
    3. set() 是请求不是命令,必须 read 一帧触发驱动协商,再 get 读回真实值

stride 说明:
    摄像头硬件按固有 fps 产帧, 跳帧不省采集开销, 反而徒增延迟。
    实时降频请用 ThreadedSource 的 latest 缓冲 + 主循环按节奏拉,
    比 stride 更优雅。本类覆盖 set_stride 给出 warning 并强制忽略。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import cv2

from ..core.base   import FrameSource
from ..core.config import CameraConfig
from ..core.types  import Frame, FrameInfo, SourceType


logger = logging.getLogger(__name__)


class CameraSource(FrameSource):
    """
    摄像头输入源,支持指定分辨率/帧率/后端/编码。

    示例:
        # 默认配置
        config = CameraConfig()
        with CameraSource(config) as cam:
            for frame in cam:
                process(frame.image)

        # 高帧率(Windows MSMF + MJPG)
        config = CameraConfig(width=1280, height=720, fps=90, backend="msmf")
        with CameraSource(config) as cam:
            for frame in cam:
                process(frame.image)
    """

    def __init__(self, config: CameraConfig):
        super().__init__(str(config.camera_id))
        self.config = config
        self._cap: Optional[cv2.VideoCapture] = None
        self._width  = 0
        self._height = 0
        self._fps    = 0.0

    def open(self) -> bool:
        # ── 撞墙记录 ①: MSMF 必须在 VideoCapture 之前设置环境变量 ──
        # 该环境变量关闭 MSMF 自动插入的硬件色彩转换滤镜(HW Transforms),
        # 否则会导致帧率下降 20~30%。必须在初始化前设置才生效。
        if self.config.backend == "msmf":
            os.environ["OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"] = "0"

        self._cap = cv2.VideoCapture(self.config.camera_id, self._get_backend())

        if not self._cap.isOpened():
            logger.error(f"无法打开摄像头 {self.config.camera_id}")
            return False

        # ── 撞墙记录 ②: 参数设置顺序 宽高 → FOURCC → FPS ──
        # 正确顺序:
        #   1. 先设分辨率:驱动据此筛选可用的媒体类型列表
        #   2. 再设 FOURCC:从上一步的列表中选择编码格式(MJPG)
        #   3. 最后设 FPS:格式锁定后才约束帧率
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.config.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.config.codec))
        self._cap.set(cv2.CAP_PROP_FPS, self.config.fps)

        # ── 撞墙记录 ③: MSMF/DSHOW 懒初始化,必须 read 一帧触发协商 ──
        # set() 只是登记意图,驱动在第一次 read() 时才真正与摄像头硬件
        # 协商并锁定格式。没有这次 read(),下面的 get() 读回的是"请求值"
        # 而非"实际值"。
        ret, _ = self._cap.read()
        if not ret:
            logger.warning("格式协商触发帧读取失败,实际参数可能不准确")

        # 读回实际生效的参数
        self._width  = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._fps    = self._cap.get(cv2.CAP_PROP_FPS)

        # ── "我设了" ≠ "它生效了":验证差异并 warning ──
        if self._width != self.config.width or self._height != self.config.height:
            logger.warning(
                f"分辨率未完全生效:期望 {self.config.width}x{self.config.height},"
                f"实际 {self._width}x{self._height}"
            )
        if self._fps < self.config.fps * 0.9:    # 允许 10% 误差
            logger.warning(
                f"帧率未完全生效:期望 {self.config.fps}fps,"
                f"实际标称 {self._fps:.1f}fps"
            )

        logger.info(
            f"摄像头已打开 (backend={self.config.backend}, codec={self.config.codec})"
        )
        logger.info(
            f"  目标: {self.config.width}x{self.config.height} @ {self.config.fps}fps"
        )
        logger.info(
            f"  实际: {self._width}x{self._height} @ {self._fps:.1f}fps"
        )
        # 同步起始时间, 让 timestamp = 0 对应"open 完成", 而不是对象构造
        self._start_time = time.time()
        self._frame_index = 0       # 复位: 重新 open 即重头计数(timestamp 也从 0 起)
        return True

    def _get_backend(self) -> int:
        """将配置字符串映射为 OpenCV 后端常量(Pydantic 已保证不会传非法值)"""
        backends = {
            "auto":  cv2.CAP_ANY,
            "msmf":  cv2.CAP_MSMF,
            "dshow": cv2.CAP_DSHOW,
            "v4l2":  cv2.CAP_V4L2,
        }
        return backends[self.config.backend]

    def read(self) -> Optional[Frame]:
        # 摄像头不支持 stride 跳帧(见类 docstring), 直接读最新一帧
        if self._cap is None:
            return None

        ret, image = self._cap.read()
        if not ret:
            return None

        info = FrameInfo(
            width=self._width,
            height=self._height,
            source_type=SourceType.CAMERA,
            source_path=self.source_path,
            frame_index=self._frame_index,
            timestamp=time.time() - self._start_time,
            fps=self._fps,
            filename=f"camera:{self.config.camera_id}",
        )
        self._frame_index += 1
        return Frame(image=image, info=info)

    def set_stride(self, stride: int) -> None:
        """
        摄像头不支持 stride 跳帧。

        理由: 摄像头硬件按固有 fps 产帧, read-and-discard 既不省采集开销,
        又会让"latest 缓冲" 拿到的"最新一帧" 反而是更旧的一帧, 加大端到端
        延迟。实时降频请用 ThreadedSource 的 latest 缓冲 + 主循环按节奏拉。

        本方法不 raise(保持与统一接口兼容), 但若 stride>1 会 warning
        并强制锁回 1。
        """
        if stride != 1:
            logger.warning(
                "摄像头不支持 stride 跳帧(硬件按固有 fps 产帧, 跳帧无收益)。"
                "实时降频请使用 ThreadedSource 的 latest 缓冲 + 主循环按节奏拉。"
                f" 收到的 stride={stride} 已忽略。"
            )
        # 强制锁回 1, 不沿用基类的"登记任意整数"语义
        self._stride = 1

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("摄像头已关闭")

    def get_source_type(self) -> SourceType:
        return SourceType.CAMERA
```

## 3.4 `sources/__init__.py`

把四个源类(三个文件)对外 re-export。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : __init__.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : sources 子包入口 — 具体输入源实现
"""sources 子包:摄像头/视频/图片/图片文件夹的具体实现。"""
from __future__ import annotations

from .camera import CameraSource
from .video  import VideoSource
from .image  import ImageSource, ImageFolderSource

__all__ = [
    "CameraSource",
    "VideoSource",
    "ImageSource",
    "ImageFolderSource",
]
```

## 3.5 git commit (sources 层)

```bash
git add frame_source/sources/
git commit -m "feat(frame_source): sources 层 —— 四个源(摄像头/视频/图片/文件夹)

- image.py: ImageSource(单图) + ImageFolderSource(文件夹, 零 IO stride + 跳坏图)
- video.py: VideoSource(seek 跳转 + grab 跳采 + fps 缺失告警), 兼作网络流承载
- camera.py: CameraSource(MSMF 环境变量 / 参数顺序 / read 触发协商 三条撞墙 + 参数验证)
- fix: 三个源的 open() 复位位置状态(read_count/current_index/frame_index),
       修'重新 open 同一对象读不到帧'; stride 作为配置项跨 open 保留"
```

四个源齐了。但现在它们各自为政: 用 CameraSource 要先 new 一个 CameraConfig, 用视频要 new VideoSource……调用方还得自己判断"这字符串是图还是视频还是摄像头"。下一阶段先加两个正交 wrapper, 再用工厂把这些都收口成"一个字符串进、一个源出"。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 4: wrappers 层 —— 两个正交装饰器

wrappers 不是"第五种源", 而是"套在任意源外面的增强"。它们只依赖 `FrameSource` 协议、不依赖任何具体源——所以对四个源一视同仁, 写一次, 四个源全受益。这就是 §0.3 强调"wrappers 不依赖具体源"的回报。

## 4.1 `threaded.py` —— ThreadedSource(后台采集)

🧱 **撞墙 G(就是前传的撞墙②): 串行循环里, 采集速度 = 最慢环节的速度**

朴素的串行循环是 `read → 推理 → imshow → waitKey → 下一轮`。这条链上**任何一个环节慢, 整体就慢**: `imshow`+`waitKey` 本身就能把 90fps 摄像头拖到 60 以下, 推理更狠。采集和消费被焊死在一个循环里, 互相拖累。

**解法**: 后台开一个 daemon 线程**专职采集**(不停 `inner.read()`), 主线程从一个缓冲队列拿帧。采集和消费速度解耦——消费再慢, 也不回压采集端。

⚠️ **设计点 (latest vs bounded 两种缓冲)**: `latest` = 队列容量 1, 满了丢最旧——实时推理首选, 因为"实时系统里旧帧无价值, 宁丢勿堆, 永远处理最新画面"。`bounded` = 容量 N, 满了也丢最旧——业务想尽量少丢中间帧时用。

⚠️ **设计点 (诚实说: bounded 不是真背压)**: 必须说清楚——`bounded` 满了**照样丢最旧帧**, 它只能"降低丢帧率", 不能"根除丢帧"。它不是那种"满了就阻塞采集端"的真背压。所以**"一帧都不能丢"的离线处理, 不要用线程化**, 直接用同步 `create_frame_source` 逐帧迭代(文件源本来就不需要后台采集)。把这点写在 docstring 里, 别让人误以为 bounded 能保证不丢。

⚠️ **设计点 (warmup 预热)**: `warmup_frames=N` 丢弃开头 N 帧。MSMF 摄像头启动期 fps 不稳, 头几十帧曝光/帧率都在抖, 丢掉它们让下游从稳定状态开始。

⚠️ **设计点 (EOS 哨兵 + 超时只警告一次)**: 采集线程发现 inner 耗尽, 往队列 push 一个 `_EOS` 哨兵对象, 让消费端的 `read()` 能优雅停下(而不是永久阻塞等下一帧)。读取超时的 warning 只打一次(`_timeout_logged` 标志), 静默源不刷屏。

⚠️ **设计点 (seekable=False)**: 线程化采集的"实时流"语义和 seek 冲突(你 seek 的瞬间后台线程还在往前跑), 所以 ThreadedSource 明确 `seekable=False`。需要 seek 请直接用 inner 源, 不要包装。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : threaded.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : ThreadedSource — 把任何 FrameSource 包成后台线程采集
"""
线程化采集包装器。

解决讲义撞墙⑥(显示/推理阻塞采集):
    串行循环里,采集速度 = 最慢环节的速度。imshow + waitKey 会把
    高帧率摄像头(90fps)拖到 60fps 以下,推理更甚。

做法:
    后台 daemon 线程持续 inner.read(),主线程从缓冲拿最新帧 —
    速度解耦,慢消费不再回压采集端。

stride 与 ThreadedSource 的关系:
    set_stride() 透传给 inner, 由 inner 自己实现最快的跳帧。
    后台采集线程拿到的就是 stride 后的帧, 缓冲里也是。
    典型组合: 视频 stride=3 + 后台采集, 让"边解码边推理"也跑出倍速。
"""
from __future__ import annotations

import logging
import threading
from queue import Empty, Full, Queue
from typing import Literal, Optional

from ..core.base  import FrameSource
from ..core.types import Frame, SourceType


logger = logging.getLogger(__name__)


BufferStrategy = Literal["latest", "bounded"]


class ThreadedSource(FrameSource):
    """
    把任何 FrameSource 包成"后台线程采集 + 缓冲消费"的形态。

    缓冲策略:
        "latest"  — 队列容量 1,满则丢最旧。实时推理首选,
                    符合"实时系统旧帧无价值,宁丢勿堆"原则。
        "bounded" — 队列容量 buffer_size,满则丢最旧。
                    业务需要尽量不丢中间帧时用(注意:只能降低丢帧率不能根除)。

    所有权:
        被包装的 inner 所有权完全交给 ThreadedSource —— 不要在外部
        read()/seek() 它,否则线程安全无保证。
        例外: set_stride() 是协议方法, 通过本类的 set_stride 透传调用是安全的。

    示例:
        # 实时推理(默认 latest 缓冲)
        with ThreadedSource(CameraSource(cfg)) as src:
            for frame in src:
                results = model(frame.image)

        # 摄像头预热前 30 帧(MSMF 后端启动期 fps 不稳)
        with ThreadedSource(CameraSource(cfg), warmup_frames=30) as src:
            for frame in src:
                ...

        # bounded 缓冲(允许积压 10 帧)
        with ThreadedSource(VideoSource("x.mp4"), buffer="bounded", buffer_size=10) as src:
            for frame in src:
                ...

        # 视频后台采集 + stride 跳采(组合)
        with ThreadedSource(VideoSource("x.mp4")) as src:
            src.set_stride(3)   # 透传给 inner, 后台采集就按 grab 跳帧
            for frame in src:
                ...
    """

    # 哨兵对象:采集线程发现 inner 耗尽时 push 这个,让 read() 知道源结束
    _EOS = object()

    def __init__(
        self,
        inner: FrameSource,
        buffer: BufferStrategy = "latest",
        buffer_size: int = 1,
        warmup_frames: int = 0,
        read_timeout: float = 5.0,
    ):
        # ── 参数验证(fail-fast)──
        if buffer not in ("latest", "bounded"):
            raise ValueError(
                f"buffer 取值必须是 'latest' 或 'bounded',收到: {buffer!r}"
            )
        if buffer_size < 1:
            raise ValueError(f"buffer_size 必须 ≥ 1,收到: {buffer_size}")
        if warmup_frames < 0:
            raise ValueError(f"warmup_frames 必须 ≥ 0,收到: {warmup_frames}")
        if read_timeout <= 0:
            raise ValueError(f"read_timeout 必须 > 0,收到: {read_timeout}")

        super().__init__(inner.source_path)
        self._inner = inner
        self._buffer_strategy = buffer
        # latest 等价于 maxsize=1,统一用 Queue 实现简化代码
        self._capacity = 1 if buffer == "latest" else buffer_size
        self._warmup_frames = warmup_frames
        self._read_timeout = read_timeout

        self._queue: Optional[Queue] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._eos = False    # 调用方视角:源已耗尽
        self._timeout_logged = False    # 超时只 warn 一次, 防日志刷屏

    def open(self) -> bool:
        """打开 inner source 并启动采集线程"""
        if not self._inner.open():
            return False

        self._queue = Queue(maxsize=self._capacity)
        self._stop_event.clear()
        self._eos = False
        self._timeout_logged = False

        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name=f"ThreadedSource-{self._inner.__class__.__name__}",
            daemon=True,
        )
        self._capture_thread.start()
        logger.info(
            f"采集线程已启动 (buffer={self._buffer_strategy}, "
            f"capacity={self._capacity}, warmup_frames={self._warmup_frames})"
        )
        return True

    # ── 后台采集循环 ────────────────────────────────────────
    def _capture_loop(self) -> None:
        """后台线程主体:不停 read inner,push 到缓冲,直到 stop 或源耗尽"""
        warmup_left = self._warmup_frames
        try:
            while not self._stop_event.is_set():
                frame = self._inner.read()

                if frame is None:
                    # 源耗尽 → push EOS sentinel,让 read() 端能优雅停下
                    self._push(self._EOS)
                    logger.debug("采集线程: inner source 耗尽")
                    return

                # 预热阶段:丢弃前 N 帧(不入队)
                if warmup_left > 0:
                    warmup_left -= 1
                    if warmup_left == 0:
                        logger.debug(f"采集线程: 预热完成({self._warmup_frames} 帧)")
                    continue

                self._push(frame)
        except Exception as e:
            # 采集线程异常不能让调用方永久 hang,push EOS 优雅退出
            logger.error(f"采集线程异常: {e}", exc_info=True)
            self._push(self._EOS)

    def _push(self, item) -> None:
        """
        统一 push:满则丢最旧再放新(实现"宁丢勿堆")。
        latest = maxsize=1 的特例,bounded = maxsize=N。
        """
        try:
            self._queue.put_nowait(item)
        except Full:
            # 满 → 丢最旧 → 重试放新
            try:
                self._queue.get_nowait()
            except Empty:
                pass    # 极罕见的竞态:刚才满,转头空了
            try:
                self._queue.put_nowait(item)
            except Full:
                # 极罕见双重竞态,放弃这一帧(下一帧很快来,实时场景无影响)
                logger.debug("采集线程: 双重 Full 竞态, 丢弃当前帧")

    # ── FrameSource 协议实现 ────────────────────────────────
    def read(self) -> Optional[Frame]:
        """从缓冲拿一帧(阻塞带超时)"""
        if self._eos or self._queue is None:
            return None

        try:
            item = self._queue.get(timeout=self._read_timeout)
        except Empty:
            # 超时 warning 只打一次, 长时间静默源不刷屏
            if not self._timeout_logged:
                logger.warning(
                    f"采集超时:{self._read_timeout}s 内无新帧抵达缓冲"
                    f"(后续超时静默, 直到再次有帧到达)"
                )
                self._timeout_logged = True
            return None

        # 拿到帧 → 复位 timeout flag, 让下次超时能再次告警
        self._timeout_logged = False

        if item is self._EOS:
            self._eos = True
            return None
        return item

    def set_stride(self, stride: int) -> None:
        """
        透传给 inner; 采集线程会按新 stride 取帧。

        典型用法: 视频后台采集 + stride 跳采, 实现"边解码边推理"的倍速。
        摄像头场景: inner(CameraSource) 自己会 warning 并忽略 stride>1。
        """
        self._inner.set_stride(stride)
        # 与 inner 保持同步, 让外部 .stride 查询返回真实值
        self._stride = self._inner.stride

    def close(self) -> None:
        """停止采集线程,关闭 inner source(幂等)"""
        self._stop_event.set()

        if self._capture_thread is not None and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
            if self._capture_thread.is_alive():
                logger.warning(
                    "采集线程未在 2 秒内退出(可能 inner.read() 阻塞中)"
                )
        self._capture_thread = None

        self._inner.close()
        logger.info("采集线程已停止,inner source 已关闭")

    def get_source_type(self) -> SourceType:
        """透传 inner 的类型,调用方看不出在用包装器"""
        return self._inner.get_source_type()

    @property
    def seekable(self) -> bool:
        # 线程化采集的"实时流"语义与 seek 冲突,明确不支持。
        # 需要 seek 的场景请直接用 inner source,不要包装。
        return False

    # ── 透传属性(诊断用,不要直接调 inner.read()/seek())──
    @property
    def inner(self) -> FrameSource:
        """访问被包装的 source(调试用)"""
        return self._inner
```

## 4.2 `aio.py` —— AsyncSource(给 async 调用方)

🧱 **撞墙 H: 在 asyncio 里直接调 cv2 的阻塞 read(), 噎死整个 event loop**

web 服务、异步推理 pipeline 是 async 的。但 OpenCV 的 `read()` 是阻塞的 C 调用, 在 event loop 里直接 `await` 不了、直接调又会**卡住整个 loop**(所有其它协程都得等它)。

**解法**: 用 `asyncio.to_thread()` 把阻塞的 `read()`/`open()`/`close()` 扔到默认线程池, event loop 不被噎住。

⚠️ **设计点 (AsyncSource 不继承 FrameSource)**: 它**不**继承 `FrameSource`——因为 async 方法签名(`async def read`)和同步协议(`def read`)不兼容, 强行继承会破坏里氏替换(LSP)。它通过 `inner` 属性持有内部源, 在协议层面与 FrameSource"等位"但不"is-a"。这是个干净的边界判断: 形似不等于同类, 该分就分。

⚠️ **设计点 (AsyncSource 本身不提供并行, 要并行就嵌 ThreadedSource)**: `to_thread` 只是让"阻塞调用 async 友好", 并不让"采集与消费并行"。需要真正的采集/推理并行时, 把 ThreadedSource 嵌在里面: `AsyncSource(ThreadedSource(CameraSource(cfg)))`——外层给 async 协议, 内层让采集后台跑, 两层职责正交, 组合即可。这正是"正交设计"的好处: 两个 wrapper 能叠加, 因为它们各管一件事。

⚠️ **设计点 (set_stride 不走 to_thread)**: `set_stride` 是轻量同步方法(只设个字段), 直接透传给 inner, 不需要 `await`。只有真正阻塞的 IO(open/read/close)才扔线程池。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : aio.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : AsyncSource — 给 async 调用方的接口包装
"""
异步接口包装器。

⚠️ 实现说明(重要):
    OpenCV 的 read() 是阻塞 C 调用,在 asyncio event loop 里直接调用
    会噎死整个 loop。本类通过 asyncio.to_thread() 把阻塞调用扔到默认
    线程池,保证 event loop 流畅 — 但这意味着 AsyncSource 本身只
    提供 "async 友好的协议",不提供"采集与消费并行"。

    需要真正的"采集/推理并行"时,把 ThreadedSource 嵌在内部:

        async with AsyncSource(ThreadedSource(CameraSource(cfg))) as src:
            async for frame in src:
                await async_process(frame.image)

    外层提供 async 协议给调用方,内层 ThreadedSource 让采集后台跑 —
    两层职责正交,组合即可。

stride 说明:
    set_stride 是轻量同步方法(只设置一个字段), 不需要 to_thread。
    直接透传给 inner 即可, 由 inner 的 read() 自己实现跳帧。
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from ..core.base  import FrameSource
from ..core.types import Frame


logger = logging.getLogger(__name__)


class AsyncSource:
    """
    把任何 FrameSource 包成 async 接口。

    注意:本类不继承 FrameSource —— async 协议与同步协议的方法签名
    不兼容(同步 def vs async def),强行继承会破坏 LSP。它通过
    `inner` 属性持有内部源,在协议层面与 FrameSource"等位",不"is-a"。

    示例:
        # 基础:async 接口,内部仍然单线程阻塞采集(适合视频/图片)
        async with AsyncSource(create_frame_source("video.mp4")) as src:
            async for frame in src:
                await async_process(frame.image)

        # 推荐:async 接口 + 后台线程采集(摄像头实时推理)
        async with AsyncSource(ThreadedSource(CameraSource(cfg))) as src:
            async for frame in src:
                await async_process(frame.image)

        # async + stride 跳采
        async with AsyncSource(create_frame_source("x.mp4")) as src:
            src.set_stride(3)
            async for frame in src:
                await async_process(frame.image)
    """

    def __init__(self, inner: FrameSource):
        self._inner = inner

    # ── async 版 FrameSource 协议 ───────────────────────────
    async def open(self) -> bool:
        return await asyncio.to_thread(self._inner.open)

    async def read(self) -> Optional[Frame]:
        return await asyncio.to_thread(self._inner.read)

    async def close(self) -> None:
        await asyncio.to_thread(self._inner.close)

    async def seek(
        self,
        frame: Optional[int] = None,
        time_sec: Optional[float] = None,
    ) -> bool:
        return await asyncio.to_thread(self._inner.seek, frame, time_sec)

    def set_stride(self, stride: int) -> None:
        """
        设置跳采步长。轻量同步方法, 不走 to_thread。

        调用方可以同步调用, 不需要 await。
        """
        self._inner.set_stride(stride)

    @property
    def stride(self) -> int:
        return self._inner.stride

    @property
    def seekable(self) -> bool:
        return self._inner.seekable

    @property
    def source_path(self) -> str:
        return self._inner.source_path

    @property
    def inner(self) -> FrameSource:
        """访问被包装的源(诊断用)"""
        return self._inner

    # ── async 上下文管理器协议 ───────────────────────────────
    async def __aenter__(self) -> "AsyncSource":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        await self.close()
        return False  # 不吞异常

    # ── async 迭代器协议 ─────────────────────────────────────
    def __aiter__(self) -> AsyncIterator[Frame]:
        return self

    async def __anext__(self) -> Frame:
        frame = await self.read()
        if frame is None:
            raise StopAsyncIteration
        return frame
```

## 4.3 `wrappers/__init__.py`

re-export 两个 wrapper。注意 docstring 里点明: **stride 不在 wrappers**——它是"源对自身行为的控制原语", 跟 seek 同族, 属于协议层(§2.3 讲过为什么)。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : __init__.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : wrappers 子包入口 — 正交扩展层(线程化 / 异步)
"""
wrappers 子包:套在任何 FrameSource 外面的性能/接口扩展层。

不属于任何一种"输入源",而是"输入源的装饰器" —— 跟具体源正交。

注: 跳采(stride)不在 wrappers, 因为它是"源对自身行为的控制原语",
    跟 seek 同族, 属于协议层。详见 core/base.py 的 set_stride。
"""
from __future__ import annotations

from .threaded import ThreadedSource, BufferStrategy
from .aio      import AsyncSource

__all__ = [
    "ThreadedSource",
    "BufferStrategy",
    "AsyncSource",
]
```

## 4.4 git commit (wrappers 层)

```bash
git add frame_source/wrappers/
git commit -m "feat(frame_source): wrappers 层 —— ThreadedSource + AsyncSource

- threaded.py: 后台线程采集, latest/bounded 缓冲, warmup 预热, EOS 哨兵;
              诚实标注 bounded 非真背压
- aio.py: asyncio.to_thread 把阻塞 read 扔线程池, 不噎 event loop;
          不继承 FrameSource(签名不兼容, 避免破坏 LSP)
- 两者只依赖 FrameSource 协议, 对四个源一视同仁"
```

两个 wrapper 和四个源都齐了, 但还散着。下一阶段用工厂把它们收口成统一入口。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 5: factory 收口 + 包入口 + README

最后一层: 把"一个 source 字符串"翻译成"对应的源", 让调用方一行 `create_frame_source("0")` 拿到能用的源, 不用自己 new、不用自己判断类型。

## 5.1 `factory.py` —— if/elif 直白派发

🤔 **思考题(30 秒, 重要)**: 工厂要根据字符串分派到四个源。你会用一套"注册表 + matcher"的可插拔机制, 还是直白的 if/elif?

**答**: 这一版选 **if/elif**, 而且这是个**经过权衡的、正确的选择**, 不是偷懒。

理由是: 本模块的源类型是**固定的四种**, 明确不打算做"第三方在不改源码的前提下接入新源"。在这个前提下——

- **if/elif 的全部规则一目了然**: "数字→摄像头、rtsp/http→视频流、目录→文件夹、视频后缀→视频、图片后缀→图片", 一段话讲完, 谁都能三秒看懂。判定逻辑全摆在眼前, 没有任何间接层。
- **注册表是用"框架复杂度"换"用不到的扩展性"**: 给四个永不变的分支套一层"注册 spec + 优先级 + matcher/builder 分离"的机制, 引入了一堆理解成本(优先级怎么定? matcher 能不能抛? 注册时机?), 却没换来任何实际好处——因为根本没有"第三方加源"这个需求。这就是**过度设计**。

> **一个判断原则**: 抽象的复杂度应该跟需求的复杂度匹配。需求是"固定四种源", 那么 if/elif 就是匹配的解; 需求若变成"任意第三方可插拔 + 一帧多模态(比如要接 RGBD 深度相机)", 那才轮到注册表和多模态契约登场。**在没有那个需求时就上那套机制, 是负债不是资产。** 反过来, 真有那个需求了还硬用 if/elif, 才是该被批评的。设计没有银弹, 只有匹配。

⚠️ **设计点 (识别逻辑收一处, 三个工厂复用)**: 把"字符串→源"的识别全放在私有的 `_build_source` 一处, `create_frame_source` / `create_threaded_source` / `create_async_source` 三个工厂都调它, 不重复抄三遍识别逻辑。改识别规则只改一处。

⚠️ **设计点 (识别顺序: 从最明确到最宽泛)**: 先判数字(最明确)→ 再判网络流 scheme → 最后才当本地路径(最宽泛, 含 fail-fast 报错)。顺序错了, 比如把"路径"判在前面, `"0"` 可能被当成文件名去找。

⚠️ **设计点 (CameraConfig 用副本)**: 工厂拿到调用方传的 `camera_config` 后, 用 `model_copy(update={"camera_id": ...})` 生成副本再塞设备号, **不污染调用方的原对象**(Pydantic v2 模型默认可变, 直接改会改到人家的)。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : factory.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : 工厂 — 自动识别输入源 + 三个便捷入口(create_frame_source / threaded / async)
"""
工厂:把"一个 source 字符串"翻译成"对应的 FrameSource 实例"。

为什么这里是直白的 if/elif, 而不是搞一套注册表/插件机制?
    因为本模块的源类型是**固定的四种**(摄像头/视频/图片/文件夹), 不打算做可插拔。
    给四个永远不变的分支套一层注册表, 是用"框架的复杂度"换"并不需要的扩展性",
    属于过度设计。一段读起来一目了然的 if/elif, 在这里就是最合适的结构:
    判定规则全在眼前, 谁都能三秒看懂"什么字符串走哪个源"。

    (反过来说: 如果哪天真要支持"第三方在不改本模块的前提下接入自定义相机", 那才是
     该引入源注册表/开闭原则的时候——但那是另一个故事了, 不在本模块范围内。)

向后说明:
    识别规则——数字=摄像头、rtsp/rtmp/http=网络视频流、路径=视频/图片/文件夹——
    都集中在 _build_source 一处, 三个工厂复用它, 不重复。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .core.base   import FrameSource
from .core.config import CameraConfig
from .core.types  import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

from .sources.camera import CameraSource
from .sources.video  import VideoSource
from .sources.image  import ImageFolderSource, ImageSource
from .wrappers.threaded import BufferStrategy, ThreadedSource
from .wrappers.aio      import AsyncSource

logger = logging.getLogger(__name__)


# rtsp/rtmp/http(s) 这类网络流, cv2.VideoCapture 能直接吃 URL, 当作视频流走 VideoSource
_STREAM_SCHEMES = ("rtsp://", "rtmp://", "http://", "https://")


def _build_source(
    source: str,
    camera_config: Optional[CameraConfig],
    options: dict[str, Any],
) -> FrameSource:
    """把 source 字符串识别成具体的 FrameSource(未 open)。

    识别顺序(从最明确到最宽泛):
        1. 纯数字          → 摄像头(设备号)
        2. rtsp/rtmp/http  → 网络视频流(VideoSource 吃 URL)
        3. 本地路径:
             目录          → 图片文件夹
             视频后缀      → 视频文件
             图片后缀      → 单张图片
             其它          → fail-fast 报错

    Raises:
        ValueError: 路径不存在 / 不支持的格式 / 无法识别。
    """
    # 1) 数字 → 摄像头
    if source.isdigit():
        camera_id = int(source)
        cfg = camera_config or CameraConfig()
        # Pydantic v2 副本, 不污染调用方传入的原对象
        cfg = cfg.model_copy(update={"camera_id": camera_id})
        return CameraSource(cfg)

    # 2) 网络流 → VideoSource(cv2 直接吃 URL)
    if source.lower().startswith(_STREAM_SCHEMES):
        return VideoSource(source)

    # 3) 本地路径 → 视频 / 图片 / 文件夹
    path = Path(source)
    if not path.exists():
        raise ValueError(f"路径不存在: {source}")

    if path.is_dir():
        return ImageFolderSource(source)

    ext = path.suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return VideoSource(source)
    if ext in IMAGE_EXTENSIONS:
        return ImageSource(source)

    raise ValueError(
        f"不支持的文件格式: '{ext}'\n"
        f"  支持的视频格式: {sorted(VIDEO_EXTENSIONS)}\n"
        f"  支持的图片格式: {sorted(IMAGE_EXTENSIONS)}"
    )


def create_frame_source(
    source: str,
    camera_config: Optional[CameraConfig] = None,
    *,
    stride: int = 1,
    **options: Any,
) -> FrameSource:
    """
    自动识别输入源类型, 返回对应的 FrameSource 实例(未 open)。

    Args:
        source: 输入源标识
            - "0", "1" ...        → cv2 摄像头(设备 ID)
            - "rtsp://..."        → 网络视频流
            - "video.mp4"         → 视频文件
            - "image.jpg"         → 单张图片
            - "./images/"         → 图片文件夹
        camera_config: cv2 摄像头配置(仅 source 为数字摄像头时生效)
        stride: 跳采步长(关键字参数, ≥1, 默认 1)

    Returns:
        FrameSource 实例(未 open, 请配合 with 或手动 open() 使用)

    Raises:
        ValueError: 无法识别 / 路径不存在 / 格式不支持 / stride < 1

    Examples:
        src = create_frame_source("0")                         # 摄像头
        src = create_frame_source("test.mp4", stride=3)        # 视频 3 倍速
        src = create_frame_source("./images", stride=10)       # 文件夹采样
    """
    if stride < 1:
        raise ValueError(f"stride 必须 ≥ 1, 收到: {stride}")
    inner = _build_source(source, camera_config, options)
    if stride > 1:
        inner.set_stride(stride)
    return inner


def create_threaded_source(
    source: str,
    camera_config: Optional[CameraConfig] = None,
    *,
    stride: int = 1,
    buffer: BufferStrategy = "latest",
    buffer_size: int = 1,
    warmup_frames: int = 0,
    read_timeout: float = 5.0,
    **options: Any,
) -> ThreadedSource:
    """便捷工厂:自动识别 + 线程化包装。**实时推理场景首选**。

    采集放后台线程, 消费端从缓冲拿最新帧 —— 慢消费不回压采集端。

    Examples:
        with create_threaded_source("0", warmup_frames=30) as src:
            for frame in src:
                results = model(frame.image)
    """
    if stride < 1:
        raise ValueError(f"stride 必须 ≥ 1, 收到: {stride}")
    inner = _build_source(source, camera_config, options)
    if stride > 1:
        inner.set_stride(stride)
    return ThreadedSource(
        inner,
        buffer=buffer,
        buffer_size=buffer_size,
        warmup_frames=warmup_frames,
        read_timeout=read_timeout,
    )


def create_async_source(
    source: str,
    camera_config: Optional[CameraConfig] = None,
    *,
    stride: int = 1,
    threaded: bool = True,
    buffer: BufferStrategy = "latest",
    buffer_size: int = 1,
    warmup_frames: int = 0,
    read_timeout: float = 5.0,
    **options: Any,
) -> AsyncSource:
    """便捷工厂:自动识别 +(可选线程化)+ async 接口包装。

    给 async 调用方使用(web 服务 / 异步推理 pipeline 等)。

    Examples:
        async with create_async_source("0", warmup_frames=30) as src:
            async for frame in src:
                await async_process(frame.image)
    """
    if stride < 1:
        raise ValueError(f"stride 必须 ≥ 1, 收到: {stride}")
    inner: FrameSource = _build_source(source, camera_config, options)
    if stride > 1:
        inner.set_stride(stride)

    if threaded:
        inner = ThreadedSource(
            inner,
            buffer=buffer,
            buffer_size=buffer_size,
            warmup_frames=warmup_frames,
            read_timeout=read_timeout,
        )
    return AsyncSource(inner)
```

## 5.2 `frame_source/__init__.py` —— 公共 API

包入口, 把所有该对外的符号 re-export 到顶层, 让调用方 `from frame_source import create_frame_source, CameraConfig, Frame` 一行拿全, 不用记每个东西在哪个子模块。`__all__` 显式列出公共 API, 既是文档也防 `import *` 漏带或多带。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : __init__.py
# @Author    : 雨霓同学
# @Project   : ODPlatform / frame_source
# @Function  : 包入口 — 公共 API re-export
"""
frame_source — 统一帧输入源抽象层

为 YOLO 等目标检测系统提供统一的输入源接口, 支持四种最常见的源:
    - 摄像头(可配置分辨率/帧率/后端/编码)
    - 视频文件 / 网络视频流(支持 seek 跳帧 + stride 跳采)
    - 单张图片
    - 图片文件夹(支持 seek + stride)

它们的共同点是"一帧 = 一张 BGR 图", 所以 Frame 只装一张 image + 一份元数据,
推理脚本统一 `for frame in src: model(frame.image)`, 换任何一种源, 循环体不用改。

三层结构:
    core     —— 数据类型(types) / 配置(config) / 抽象协议(base)
    sources  —— 四个具体源(camera / video / image / image_folder)
    wrappers —— 两个正交装饰器(ThreadedSource 后台采集 / AsyncSource 异步接口),
                只依赖 FrameSource 协议, 对四个源一视同仁

────────────────────────────────────────────────────────────────────
设计原则:本模块刻意保持自给自足, 可整包拷贝到任何 Python 项目使用。
  核心外部依赖: opencv-python、numpy、pydantic>=2.0、Python>=3.10
────────────────────────────────────────────────────────────────────

快速使用:

    # 1) 同步 — 标准迭代器(摄像头/视频/图片/文件夹通吃)
    from frame_source import create_frame_source
    with create_frame_source("0") as src:
        for frame in src:
            process(frame.image)

    # 2) 线程化 — 实时推理(摄像头满速, 采集不被推理拖慢)
    from frame_source import create_threaded_source
    with create_threaded_source("0", warmup_frames=30) as src:
        for frame in src:
            results = model(frame.image)

    # 3) 异步 — 给 async 调用方(web 服务等)
    from frame_source import create_async_source
    async with create_async_source("0") as src:
        async for frame in src:
            await async_process(frame.image)
"""
from __future__ import annotations

# ── 类型与抽象 ────────────────────────────────────────────────
from .core.types  import (
    SourceType, FrameInfo, Frame,
    IMAGE_EXTENSIONS, VIDEO_EXTENSIONS,
)
from .core.config import (
    CameraConfig, CameraBackend, CameraCodec,
)
from .core.base   import FrameSource

# ── 具体源实现 ────────────────────────────────────────────────
from .sources.camera import CameraSource
from .sources.video  import VideoSource
from .sources.image  import ImageSource, ImageFolderSource

# ── 包装器(扩展层)────────────────────────────────────────────
from .wrappers.threaded import ThreadedSource, BufferStrategy
from .wrappers.aio      import AsyncSource

# ── 工厂(推荐入口)────────────────────────────────────────────
from .factory import (
    create_frame_source,
    create_threaded_source,
    create_async_source,
)


__version__ = "1.0.0"
__author__  = "雨霓同学"


__all__ = [
    # 版本元数据
    "__version__",
    "__author__",
    # 类型与抽象
    "SourceType",
    "FrameInfo",
    "Frame",
    "FrameSource",
    "IMAGE_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    # 配置
    "CameraConfig",
    "CameraBackend",
    "CameraCodec",
    # 具体源
    "CameraSource",
    "VideoSource",
    "ImageSource",
    "ImageFolderSource",
    # 包装器
    "ThreadedSource",
    "BufferStrategy",
    "AsyncSource",
    # 工厂(推荐使用)
    "create_frame_source",
    "create_threaded_source",
    "create_async_source",
]
```

## 5.3 `README.md` —— 可拷走模块的身份证

模块要能"拷到别的项目就能用", 就得有一份自带的 README 说清依赖、上手、识别规则。它是这个独立模块的身份证。

```markdown
# frame_source
统一帧输入源抽象层 —— 把"摄像头/视频/图片/文件夹"封装成同一套接口。
## 依赖
opencv-python / numpy / pydantic>=2.0 / Python>=3.10
## 30 秒上手
    from frame_source import create_frame_source
    with create_frame_source("0") as src:    # 0=摄像头 / x.mp4=视频 / x.jpg=图 / ./dir=文件夹
        for frame in src:
            results = model(frame.image)
## 拷走
    cp -r frame_source/ 你的项目/
```

(完整 README 见包内 `frame_source/README.md`。)

## 5.4 端到端验证: 一个 run() 通吃四类源

```python
# verify.py(演示用, 不进 git)
from frame_source import create_frame_source

def run(model, source: str):
    """同一个 run, 喂不同的源, 循环体一行不改。"""
    with create_frame_source(source) as src:
        for frame in src:
            results = model(frame.image)      # frame.image 恒为 BGR
            print(f"{source}: 帧 {frame.info.frame_index}, {frame.width}x{frame.height}")

# 四类源, 同一个 run:
run(model, "0")              # 摄像头
run(model, "test.mp4")       # 视频(rtsp://... 也走这条)
run(model, "photo.jpg")      # 单图
run(model, "./images/")      # 文件夹
# 重头再跑一遍? 直接再 run 一次即可——每次 create 新对象, open 复位干净
run(model, "test.mp4")
```

## 5.5 git commit (factory + 包入口)

```bash
git add frame_source/factory.py frame_source/__init__.py frame_source/README.md
git commit -m "feat(frame_source): factory 收口 —— if/elif 自动识别 + 三个便捷工厂 + 包入口

- factory.py: _build_source 一处识别(数字/网络流/路径), 三工厂复用; 刻意用 if/elif 不用注册表
- __init__.py: 公共 API re-export + __all__
- README.md: 可拷走模块的身份证"
```

模块功能闭合了。下一阶段把这些承诺钉成自测, 防回归。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 6: 自测 —— 把每条承诺钉成回归测试

模块写完不等于写对。前面每一面墙、每一个设计点, 都是一条"我承诺它现在是对的"。自测就是把这些承诺变成可重跑的检查, 防止以后改动悄悄破坏它们。

## 6.1 自测覆盖的承诺

这份自测合成了真实资源(30 帧视频 / 单图 / 10 张图的文件夹)跑端到端, 共 29 项, 覆盖:

1. **公共 API 表面**: 四源 + 工厂 + wrapper 都导出; 且**确认深度相机/注册表符号已彻底移除**(`OrbbecGeminiSource`/`register_source`/`SourceRegistry`/`list_sources` 都不存在); `SourceType` 只有四种。
2. **单模态 Frame**: `frame.image` 是 BGR 主图、便捷属性 `width/height` 正常; 且**确认不再有 `aux`/`depth` 等多模态字段**。
3. **工厂识别路由**: 数字→Camera、rtsp/http→Video、`.mp4`→Video、`.jpg`→Image、目录→Folder。
4. **四种源端到端**: 单图 1 帧、视频 30 帧、文件夹 10 帧。
5. **seek / stride**: 视频 `seek(frame=10)`、`seek(time_sec=0.5)`、视频/文件夹 `stride=3` 帧号 [0,3,6,9]。
6. **wrapper 白送**: ThreadedSource 包文件夹(用 bounded 大缓冲数帧, 避免 latest 丢帧)。
7. **AsyncSource**: `async for` 异步迭代(用 `threaded=False` 保证计数确定)。
8. **CameraConfig fail-fast**: 拼错字段当场 raise。
9. **重新 open 复位(本版修复)**: Video/Image/Folder 重开后帧数恢复、首帧 frame_index 归 0。
10. **stride 跨 open 保留**: 重开后 stride 仍生效(配置项不被复位)。
11. **迭代器单次性**: 同一对象第二遍迭代为 0 帧。
12. **错误处理**: 路径不存在 / 不支持的格式 都 `ValueError` fail-fast。

⚠️ **设计点 (自测脚本路径自适应)**: 脚本开头 `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`——把"脚本自己所在目录"加入搜索路径, 这样无论从哪里运行、整包拷到哪, `import frame_source` 都能找到, 不写死绝对路径。

### 完整代码

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""frame_source 验证脚本(四源版)—— 证明四种源 + wrapper + 复位修复都能跑。"""
import sys, os, tempfile, asyncio
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import frame_source as fs
from frame_source import (
    create_frame_source, create_threaded_source, create_async_source,
    Frame, FrameInfo, SourceType, CameraConfig,
    VideoSource, ImageSource, ImageFolderSource, CameraSource,
    ThreadedSource, AsyncSource, FrameSource,
)

PASS, FAIL = [], []
def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK' if cond else 'XX'}] {name}")

print(f"\n== frame_source v{fs.__version__}(四源版)==")

tmp = tempfile.mkdtemp()
# 合成资源: 30 帧视频(像素值=帧号)、单图、文件夹(10 张)
vp = os.path.join(tmp, "test.mp4")
vw = cv2.VideoWriter(vp, cv2.VideoWriter_fourcc(*"mp4v"), 30, (64, 48))
for i in range(30):
    vw.write(np.full((48, 64, 3), i, np.uint8))
vw.release()
single = os.path.join(tmp, "a.jpg"); cv2.imwrite(single, np.random.randint(0,255,(32,48,3),np.uint8))
folder = tempfile.mkdtemp()
for i in range(10):
    cv2.imwrite(os.path.join(folder, f"img_{i:02d}.png"), np.zeros((16,16,3),np.uint8))

# ── 1. 公共 API 齐全, 且不含深度/注册表符号 ──
print("\n[1] 公共 API 表面:")
check("四源 + 工厂 + wrapper 都导出",
      all(hasattr(fs, n) for n in
          ["CameraSource","VideoSource","ImageSource","ImageFolderSource",
           "create_frame_source","create_threaded_source","create_async_source",
           "ThreadedSource","AsyncSource","CameraConfig"]))
check("已彻底移除深度相机/注册表符号",
      not any(hasattr(fs, n) for n in
          ["OrbbecGeminiSource","OrbbecConfig","CameraIntrinsics",
           "register_source","get_registry","SourceRegistry","list_sources"]))
check("SourceType 只有四种",
      {t.value for t in SourceType} == {"camera","video","image","image_folder"})

# ── 2. Frame 是单模态(只有 image + info)──
print("\n[2] 单模态 Frame:")
f = Frame(image=np.zeros((4,6,3),np.uint8),
          info=FrameInfo(width=6,height=4,source_type=SourceType.IMAGE,source_path="x.jpg"))
check("frame.image 是 BGR 主图", f.image.shape == (4,6,3))
check("frame.width/height 便捷属性", f.width==6 and f.height==4)
check("Frame 不再有 aux/depth 等多模态字段",
      not any(hasattr(f, a) for a in ["aux","depth","has_depth","modalities"]))

# ── 3. 工厂识别路由(不真正 open 摄像头/网络流)──
print("\n[3] 工厂识别路由:")
check("数字 → CameraSource", isinstance(create_frame_source("0"), CameraSource))
check("rtsp:// → VideoSource", isinstance(create_frame_source("rtsp://1.2.3.4/s"), VideoSource))
check("http:// → VideoSource", isinstance(create_frame_source("http://x/y.m3u8"), VideoSource))
check(".mp4 路径 → VideoSource", isinstance(create_frame_source(vp), VideoSource))
check(".jpg 路径 → ImageSource", isinstance(create_frame_source(single), ImageSource))
check("目录 → ImageFolderSource", isinstance(create_frame_source(folder), ImageFolderSource))

# ── 4. 既有源端到端 ──
print("\n[4] 四种源端到端:")
with create_frame_source(single) as src:
    frames = list(src)
check("单图源读到 1 帧", len(frames)==1 and frames[0].width==48)

with create_frame_source(vp) as src:
    n = sum(1 for _ in src)
check(f"视频读到 {n} 帧(应=30)", n==30)

with create_frame_source(folder) as src:
    fns = [fr.info.filename for fr in src]
check(f"文件夹读到 {len(fns)} 帧(应=10)", len(fns)==10)

# ── 5. seek + stride ──
print("\n[5] seek / stride:")
with VideoSource(vp) as v:
    v.seek(frame=10); fr = v.read()
check("视频 seek(frame=10) 后 frame_index=10", fr.info.frame_index==10)
with VideoSource(vp) as v:
    v.seek(time_sec=0.5); fr = v.read()
check("视频 seek(time_sec=0.5) → frame_index≈15", fr.info.frame_index==15)
with create_frame_source(vp, stride=3) as v:
    idxs = [fr.info.frame_index for fr in v]
check(f"视频 stride=3 帧号 {idxs[:4]}...", idxs[:4]==[0,3,6,9])
with create_frame_source(folder, stride=3) as v:
    idxs = [fr.info.frame_index for fr in v]
check(f"文件夹 stride=3 帧号 {idxs}", idxs==[0,3,6,9])

# ── 6. wrapper 对任意源白送 ──
print("\n[6] wrapper 白送(ThreadedSource 包文件夹):")
got = 0
with create_threaded_source(folder, buffer="bounded", buffer_size=64) as src:
    for _ in src: got += 1
check(f"线程化采集读到 {got} 帧(应=10)", got==10)

# ── 7. AsyncSource ──
print("\n[7] AsyncSource 异步迭代:")
async def run_async():
    cnt = 0
    # threaded=False: 纯异步包装, 不经 latest 缓冲, 计数确定。
    # (默认 threaded=True 的 latest 缓冲会按设计丢帧, 不适合用来数帧数。)
    async with create_async_source(vp, stride=5, threaded=False) as src:
        async for _ in src: cnt += 1
    return cnt
check("async for 读到帧(stride=5, 应=6)", asyncio.run(run_async())==6)

# ── 8. CameraConfig fail-fast ──
print("\n[8] CameraConfig fail-fast:")
try:
    CameraConfig(widht=1280)   # 故意拼错
    check("拼错字段应被拦下", False)
except Exception:
    check("拼错字段当场 raise(extra=forbid)", True)

# ── 9. 重新 open 复位(本版修复)──
print("\n[9] 重新 open 复位(修复验证):")
def reopen(name, make, expect_n):
    s = make(); s.open(); n1 = sum(1 for _ in s); s.close()
    s.open(); fr2 = list(s); s.close()
    ok = (n1==expect_n) and (len(fr2)==expect_n) and (fr2[0].info.frame_index==0)
    check(f"{name}: 重开后 {len(fr2)} 帧, 首帧 frame_index={fr2[0].info.frame_index if fr2 else None}", ok)
reopen("VideoSource", lambda: VideoSource(vp), 30)
reopen("ImageSource", lambda: ImageSource(single), 1)
reopen("ImageFolderSource", lambda: ImageFolderSource(folder), 10)

# ── 10. stride 跨 open 保留(配置项, 不该被复位)──
print("\n[10] stride 跨 open 保留:")
v = VideoSource(vp); v.open(); v.set_stride(3); list(v); v.close()
v.open(); idxs=[fr.info.frame_index for fr in v][:4]; v.close()
check(f"重开后 stride 仍生效 {idxs}", idxs==[0,3,6,9])

# ── 11. 迭代器单次性 ──
print("\n[11] 迭代器单次性:")
with create_frame_source(vp) as v:
    a=len(list(v)); b=len(list(v))
check(f"第一遍 {a} / 第二遍 {b}(第二遍应=0)", a==30 and b==0)

# ── 12. 错误处理 ──
print("\n[12] 错误处理(fail-fast):")
bad_ext = os.path.join(tmp, "x.xyz"); open(bad_ext,"w").close()
for bad, kw in [("/no/such/path.mp4","路径不存在"), (bad_ext,"不支持的文件格式")]:
    try:
        create_frame_source(bad); check(f"{bad} 未报错(意外)", False)
    except ValueError as e:
        check(f"{os.path.basename(bad)} → ValueError ✓", kw in str(e))

# ── 汇总 ──
print(f"\n== 结果: {len(PASS)} 通过, {len(FAIL)} 失败 ==")
if FAIL:
    print("失败项:", FAIL); sys.exit(1)
print("全部通过 ✅")
```

## 6.2 跑一遍

```bash
$ python3 frame_source_selftest.py
```

输出:

```text

== frame_source v1.0.0(四源版)==

[1] 公共 API 表面:
  [OK] 四源 + 工厂 + wrapper 都导出
  [OK] 已彻底移除深度相机/注册表符号
  [OK] SourceType 只有四种

[2] 单模态 Frame:
  [OK] frame.image 是 BGR 主图
  [OK] frame.width/height 便捷属性
  [OK] Frame 不再有 aux/depth 等多模态字段

[3] 工厂识别路由:
  [OK] 数字 → CameraSource
  [OK] rtsp:// → VideoSource
  [OK] http:// → VideoSource
  [OK] .mp4 路径 → VideoSource
  [OK] .jpg 路径 → ImageSource
  [OK] 目录 → ImageFolderSource

[4] 四种源端到端:
  [OK] 单图源读到 1 帧
  [OK] 视频读到 30 帧(应=30)
  [OK] 文件夹读到 10 帧(应=10)

[5] seek / stride:
  [OK] 视频 seek(frame=10) 后 frame_index=10
  [OK] 视频 seek(time_sec=0.5) → frame_index≈15
  [OK] 视频 stride=3 帧号 [0, 3, 6, 9]...
  [OK] 文件夹 stride=3 帧号 [0, 3, 6, 9]

[6] wrapper 白送(ThreadedSource 包文件夹):
  [OK] 线程化采集读到 10 帧(应=10)

[7] AsyncSource 异步迭代:
  [OK] async for 读到帧(stride=5, 应=6)

[8] CameraConfig fail-fast:
  [OK] 拼错字段当场 raise(extra=forbid)

[9] 重新 open 复位(修复验证):
  [OK] VideoSource: 重开后 30 帧, 首帧 frame_index=0
  [OK] ImageSource: 重开后 1 帧, 首帧 frame_index=0
  [OK] ImageFolderSource: 重开后 10 帧, 首帧 frame_index=0

[10] stride 跨 open 保留:
  [OK] 重开后 stride 仍生效 [0, 3, 6, 9]

[11] 迭代器单次性:
  [OK] 第一遍 30 / 第二遍 0(第二遍应=0)

[12] 错误处理(fail-fast):
  [OK] path.mp4 → ValueError ✓
  [OK] x.xyz → ValueError ✓

== 结果: 29 通过, 0 失败 ==
全部通过 ✅
```

29 项全过。注意第 [1]、[2] 组专门**反向验证**深度相机和注册表确实被移除了——这一版不是"留着不用", 是"根本不存在", 把它钉进测试, 防止以后误加回来。

## 6.3 git commit (自测)

```bash
git add frame_source_selftest.py
git commit -m "test(frame_source): 自测脚本 —— 四源端到端 + wrapper + 复位 + 错误处理(29 项)

- 覆盖四源识别/端到端、seek/stride、threaded/aio、CameraConfig fail-fast
- 反向断言深度相机/注册表符号已移除、Frame 为单模态
- 验证 open 复位修复 + stride 跨 open 保留
- 路径自适应, 整包拷到任何位置可直接跑"
```

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 7: ADR —— 把"为什么这么设计"沉淀下来

ADR(Architecture Decision Record)记录一个关键设计决策的来龙去脉, 让以后接手的人(包括半年后的你自己)看得懂"当初为什么这么选"。

```text
# ADR: frame_source —— 四源 / 单模态 / if-elif 工厂

## 1. 背景

推理系统的输入是动态原始流(摄像头/视频/图片/文件夹/网络流)。直接用
ultralytics 的 model.predict(source=...) 是黑盒, 帧间插不进逻辑、摄像头跑不满、
采集与显示解不开耦。需要把"出帧"抽成独立、可控、可整包拷走的模块。

本模块的需求边界明确:**只支持四种最常见的源**(摄像头/视频/图片/图片文件夹),
不涉及深度相机等多模态设备, 也不需要"第三方在不改源码的前提下接入新源"。

## 2. 决策

### 2.1 三层结构 + 协议统一
core(类型/配置/协议)→ sources(四个具体源)→ wrappers(线程化/异步), 外加
factory 收口。所有源实现同一个 FrameSource 协议(open/read/close + seek +
set_stride + 上下文 + 迭代器), 调用方只跟协议打交道。

### 2.2 单模态 Frame
Frame = image(一张 BGR 图) + info(元数据)。四种源每帧都只产一张图, 不引入
aux 副流字典、不引入多模态契约。下游统一 frame.image 拿图。

### 2.3 工厂用 if/elif, 不用注册表
源类型固定四种, 识别逻辑(数字/网络流/路径)用直白的 if/elif 集中在 _build_source
一处, 不引入"注册 spec + matcher/builder + 优先级"的可插拔机制。

### 2.4 seek/stride 是协议方法, 不是 wrapper
两者是"源对自身出帧行为的控制原语", 与 seek 同族; 且每个源能用自己最快的跳帧
手段(视频 grab 跳过 YUV→BGR、文件夹跳索引零 IO), 通用 wrapper 做不到。

### 2.5 wrappers 正交于具体源
ThreadedSource / AsyncSource 只依赖 FrameSource 协议, 不依赖任何具体源, 对四个源
一视同仁。

## 3. 不选择的方案

- **多模态 Frame(image + aux 字典)**: 四种源没有"一帧多流"的需求, 引入 aux 是
  给不存在的需求加复杂度。【若未来要接 RGBD 深度相机, 再升多模态】
- **源注册表 / 插件机制**: 四种源固定不变, 注册表是用框架复杂度换用不到的扩展性,
  属过度设计。【若未来要支持第三方可插拔加源, 再引入注册表】
- **stride 做成 wrapper**: 会丢失各源的高性能跳帧手段(grab / 跳索引), 退化成
  read-and-discard, 浪费完整解码。
- **__enter__ 里 open 失败即 raise**: 当前选择不抛, 把"打不开"也当"耗尽"统一处理。
  这是可辩护的取舍, 但边界偏宽松, 已在 docstring 注明。

## 4. 后果

正面:
+ 调用方一个 for frame in src 通吃四类源, 换源不改循环体。
+ 模块零依赖宿主, cp -r 即可拷走复用。
+ 复杂度跟需求匹配: 没有用不到的抽象, 读起来一目了然。
+ 加 wrapper(线程化/异步)对四个源白送, 一次实现处处受益。

负面 / 已知边界:
- bounded 缓冲不是真背压(满了仍丢最旧), 离线"一帧不丢"场景应用同步迭代。
- seek 在压缩视频上对齐到关键帧, 落点不精确(已注明)。
- 不支持深度相机 / 多模态 / 第三方插件——这是有意的范围限定, 不是缺陷。
  需要时按 §3 的"不选择的方案"对应升级。

## 5. 关键文件位置

frame_source/
  core/{types,config,base}.py   类型 / 配置 / 协议
  sources/{image,video,camera}.py  四个源(image 含单图+文件夹两类)
  wrappers/{threaded,aio}.py    两个正交装饰器
  factory.py                    if/elif 识别 + 三工厂

## 6. 修订记录

- v1.0.0: 四源版首版。三层结构 + 四源 + 单模态 Frame + if/elif 工厂 +
          ThreadedSource/AsyncSource; open() 复位位置状态(修"重新 open 读不到帧")。
```

🤔 **思考题(30 秒)**: ADR 的"不选择的方案"为什么比"决策"还值得写?

**答**: 因为半年后接手的人, 最容易冒出来的念头恰恰是"这里为什么不做成可插拔的注册表? 是不是作者没想到?"。把"想过, 但因为需求是固定四种、所以故意没做, 真要做的话是另一个触发条件"白纸黑字写下来, 能挡住绝大多数"好心的过度重构"。**ADR 的价值一半在记录选了什么, 一半在记录想过却没选什么、以及什么条件下该重新考虑。**

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 回看

## 几面墙, 一条主线

| 墙 | 现象 | 解法 | 落在哪 |
|---|---|---|---|
| 黑盒 | model.predict 帧间插不进逻辑 | 统一 FrameSource 协议 | core/base |
| 摄像头不生效 | set 了分辨率/帧率不管用 | 后端协商 + 参数顺序 + read 触发 + 验证 | sources/camera |
| 采集被拖慢 | 串行循环里消费拖垮采集 | ThreadedSource 后台采集 | wrappers/threaded |
| 跳帧慢 | 视频 read 后扔帧, 白解码 | stride 用 grab() | sources/video |
| 文件夹坑 | 后缀大小写 / 坏图 / 顺序 | suffix.lower + sorted + 跳坏图 | sources/image |
| fps 缺失 | seek(秒) 算错还不吭声 | 缺失回退 + 明确 warning | sources/video |
| 重新 open 读不到帧 | open 不复位位置状态 | 各源 open() 清位置计数 | sources/* (本版修复) |
| 异步噎住 | 阻塞 read 卡死 event loop | asyncio.to_thread | wrappers/aio |

一条主线: **每一处设计都对应一面具体的墙, 没有一处是"为了架构而架构"**。这正是这一版的气质——复杂度严格跟着需求走。

## 抽象成功的终极考核: run() 函数体

```python
def run(model, source):
    with create_frame_source(source) as src:
        for frame in src:
            results = model(frame.image)
            ...
```

把 `source` 从 `"0"` 换成 `"x.mp4"` 换成 `"./imgs/"` 换成 `"rtsp://..."`, **这个函数体一个字都不用改**。摄像头的后端协商、视频的 grab 跳采、文件夹的跳坏图、网络流的 URL 解析——全藏在源里, 调用方看不见也不用管。这就是抽象做到位的样子: 把差异关进盒子, 对外只露一个统一的"逐帧"接口。

## 模块清单与单一职责

| 模块 | 职责一句话 | 可拷走? |
|---|---|---|
| `core/types`   | 数据类型(Frame = 一张 BGR 图 + 元数据) | ✓ |
| `core/config`  | 摄像头配置(Pydantic 校验) | ✓ |
| `core/base`    | 抽象协议(统一所有源的接口) | ✓ |
| `sources/image`  | 单图 + 图片文件夹 | ✓ |
| `sources/video`  | 视频文件 / 网络流(seek + grab 跳采) | ✓ |
| `sources/camera` | 摄像头(跨平台 + 后端协商 + 参数验证) | ✓ |
| `wrappers/threaded` | 后台线程采集(解耦采集与消费) | ✓ |
| `wrappers/aio`      | 异步接口(给 async 调用方) | ✓ |
| `factory`      | if/elif 识别 + 三个便捷工厂 | ✓ |

全列 ✓: 整个模块零依赖宿主, `cp -r` 就能走。**没有 orbbec 行、没有 registry 行**——这一版的清单就该这么干净。

## 三个讲点(带走这三句就够)

1. **抽象复杂度要匹配需求复杂度。** 同样是"根据字符串造对象", 需求是"固定四种源"就该用 if/elif(规则一目了然), 需求是"任意第三方可插拔"才该上注册表。在没有那个需求时硬上注册表/多模态, 是负债不是资产; 真有那个需求了还硬用 if/elif, 才该被批评。设计没有银弹, 只有匹配——这一版选 if/elif、选单模态 Frame, 正是因为需求只到这儿。

2. **协议层定契约, 实现层兑现契约。** `base.py` 声明"重新 open 能重头迭代", 但真正复位位置状态是各源 `open()` 的责任——上一版就是漏了这步实现, 让契约成了空话(撞墙 C)。`seek`/`stride` 也一样: 协议层留方法, 各源用自己最快的方式兑现(视频 grab、文件夹跳索引)。看到一个抽象方法, 要追问"谁来兑现、兑现得对不对"。

3. **正交设计的复利。** wrapper 只依赖协议、不依赖具体源, 所以线程化/异步对四个源白送, 而且两个 wrapper 还能叠加(`AsyncSource(ThreadedSource(...))`)。一个对的接缝, 能在你加源、加增强时连本带利地省事——前提是当初没把增强焊死在某个具体源上。

---

# 全篇收官

frame_source(四源版)闭合:

- **core 层**: Frame(一张 BGR 图 + 元数据, 单模态)、CameraConfig(只有摄像头要配)、FrameSource 抽象协议(含"重新 open 即重头"契约)。
- **sources 层**: 四种源三个文件——单图/文件夹(零 IO stride + 跳坏图)、视频/网络流(seek + grab 跳采 + fps 告警)、摄像头(后端协商 + 参数验证三坑); 三个源 `open()` 复位位置状态。
- **wrappers 层**: ThreadedSource(后台采集, bounded 非真背压已注明)+ AsyncSource(to_thread 不噎 loop, 不继承 FrameSource), 对四个源白送。
- **factory**: if/elif 识别(数字/网络流/路径)+ 三个便捷工厂, 刻意不上注册表。
- **修复**: 重新 open 复位位置状态, 自测 29 项全过。

一句话: **调用方一个 `for frame in src` 通吃摄像头/视频/图片/文件夹四类源、换源不改循环体; 模块零依赖宿主、`cp -r` 即可复用; 而它的全部克制——单模态、if/elif、不碰深度相机——都不是省事, 是让复杂度严格匹配"只做这四种常见源"的需求。**

> **末尾金句**: **"好的抽象不在于预留了多少没用上的扩展点, 而在于它解决的每一处都对应一面真撞过的墙, 且没有一行是为了'将来也许用得上'而提前背上的债。这一版的价值, 就藏在那张'没有 registry 行、没有 orbbec 行'的清单里——克制本身, 也是一种设计能力。"**
