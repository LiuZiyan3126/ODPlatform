---
# ODPlatform D8: 推理子系统(inference)

> 这一章把 D5 的配置、D2 的日志、frame_source 的帧、visualization 的画**装配**成一个能跑的实时推理服务,既能从命令行 `odp-infer` 拉起,也能被桌面 GUI / Web 后端 / 异步任务调用 — **同一套引擎,多种前端**。
>
> 核心是一条四级多线程流水线 + 三个让前端能"插进来"的接缝(sink / hooks / cancel)。本文不是"多线程教程",是"**D8 推理子系统怎么从零搭起来**" — 包括为什么先搭朴素单线程版试错、为什么后来要拆成多线程、每个文件怎么演化、接缝怎么留、最后怎么装成 CLI + 桌面端能跑。

---

## 📌 跨平台命令说明

| 操作 | Windows (PowerShell) | macOS / Linux |
|---|---|---|
| 设环境变量 | `$env:PYTHONPATH = "apps/platform"` | `export PYTHONPATH=apps/platform` |
| 跑 CLI | `odp-infer --source 0` | `odp-infer --source 0` |
| 跑桌面端 | `python apps\desktop\main.py` | `python apps/desktop/main.py` |
| 退出推理窗口(CLI) | 按 `q` 或 `Esc` | 同左 |
| 暂停 / 恢复(CLI) | 按 `空格` | 同左 |

下面正文里命令都用 Unix 风格,Win 同学替换即可。

---

## 文档使用说明

读这份文档的两种姿势:

**姿势 A: 顺读**(推荐第一次看)。从阶段 0 一路到阶段 12,每个阶段末尾都有完整代码、能直接复制粘贴落到对应路径下,顺读完成后你就有一个能跑的 `odp-infer` + 能跑的桌面 demo。

**姿势 B: 跳读**(已经在维护这套代码,只想查某段细节)。直接到对应阶段:

- 配置那一半为什么这么切? → 阶段 4
- 5 维 FPS 各自啥口径? → 阶段 5
- `OutputSink` 为什么是 ABC,默认实现长什么样? → 阶段 6
- 多线程的退出顺序为什么是那样? → 阶段 7.9
- `_FrameProcessor` 为什么不加锁? → 阶段 8.7
- `predict()` 的 3 个 keyword-only 新参数是干嘛的? → 阶段 8.3
- `--threaded` 参数现在还有用吗? → 阶段 9.4
- 桌面端怎么显示推理画面? → 阶段 11

---

## 上一节回顾 + 本节挑战

D5 给我们留下了:`build_infer_config(yaml_path, cli_args) -> (YOLOInferConfig, ConfigMerger)`。一行进去,出来是验证过的 pydantic 模型 + 完整的字段溯源链。

D2 给我们留下了:`get_logger(base_path, log_type, log_level)`,把 console + file 两个 handler 装到 `odp_platform` 根 logger 上。

`frame_source/` 给我们留下了:`create_frame_source(source) -> FrameSource`,统一的 `for frame in src` 迭代器,`frame.image` 是 BGR ndarray。

`visualization/` 给我们留下了:`BeautifyVisualizer(labels=...).draw(image, detections)`,返回画了圆角框 + 中英文标签的图。

D8 的挑战:**把它们装配成一个生产可用的实时推理服务**,要求:

1. **CLI**:`odp-infer --source 0` 拉起摄像头实时推理,按 `q` 退出、`空格` 暂停。
2. **文件源**:`odp-infer --source demo.mp4` 跑视频文件,跑完自动退出,结果存盘成 mp4。`odp-infer --source ./images/` 跑文件夹,每张图存一份带框的 jpg。
3. **性能**:摄像头要跑出 **60+ FPS**(不能因为加了显示就掉到 20FPS — 这是我们立这个项目的核心动力)。
4. **完整性**:视频源存盘要**完整、不掉帧**(跟实时显示的诉求冲突,要解决)。
5. **健壮**:推理崩了**不能影响外层进程** — service 永远返回 `InferResult`,异常进 `error` 字段。
6. **可审计**:跑完留一份审计快照 `odp_audit.json`,记录这次推理用了什么模型、什么配置、跑了多少帧、多少 FPS、字段哪儿来的。
7. ★ **多前端可复用**:桌面端、Web 后端、Celery 异步任务**都能调同一个 `InferService`**,但**推理子系统不依赖 PyQt / FastAPI / Celery 任何一个**。

第 7 条是 D8 的新约束 — 也是这一章相比传统"单 CLI 推理服务"要多花精力的地方。我们用三个**接缝**(sink / hooks / cancel)解决,详见阶段 6。

---

## 起点与终点

**起点**:你有一台带摄像头的电脑、装好了 ultralytics、能 `python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')"` 跑通。`frame_source/` 和 `visualization/` 已经存在并能 import。D5 的 `build_infer_config` 已经能调通。

**终点**:8 个新文件 + 1 份手写 yaml + 1 个 CLI 入口 + 1 个桌面 demo,加起来约 1671 行代码:

```
apps/platform/src/odp_platform/inference/        ★ 本章新建 (推理引擎, 业务无关)
├── __init__.py             45   行   ← 对外面板
├── pipeline_config.py     134   行   ← 帧源+美化 yaml 解析
├── overlay.py             183   行   ← Metrics + HUD 绘制
├── cancel.py               52   行   ← ★ 接缝1: CancelToken (取消信号)
├── hooks.py                99   行   ← ★ 接缝2: InferHooks (生命周期回调)
├── sinks.py               146   行   ← ★ 接缝3: OutputSink (输出适配)
├── pipeline.py            486   行   ← 四级多线程流水线 (核心)
└── service.py             526   行   ← InferService 装配 + 异常兜底

apps/platform/src/odp_platform/cli/
└── infer.py              ~180   行   ← odp-infer CLI 入口

configs/runtime/
└── infer_pipeline.yaml    ~50   行   ← 手写 yaml (D5 生成不了嵌套结构)

apps/desktop/                                     ★ 本章新建 (桌面 demo)
├── qt_sink.py              ~75  行   ← OutputSink → Qt 信号桥
├── infer_worker.py        ~120  行   ← QObject + moveToThread 跑 InferService
└── main.py                ~260  行   ← MainWindow 主入口
```

跑起来:

```bash
# CLI 路径
odp-infer --source 0 --show         # 摄像头实时显示
odp-infer --source demo.mp4         # 视频 + 默认存盘
odp-infer --source ./images/        # 图片文件夹

# 桌面 GUI 路径 (同样的引擎, 不同的前端)
python apps/desktop/main.py
```

---

## D8 跟其他子系统的关系图

```
┌──────────────────────────────────────────────────────────────────────┐
│   D2 logging_utils         D5 runtime_config        D6 training       │
│   ├ get_logger             ├ build_infer_config     ├ TrainService    │
│   └ FileHandler            └ YOLOInferConfig        └ TrainResult     │
│           │                         │                       │         │
│           ▼                         ▼                       │         │
│   ┌────────────────────────────────────────────┐            │         │
│   │   D8 inference (本章)                       │            │         │
│   │   ┌──────────────────────────────────┐    │  并列, 不依赖│         │
│   │   │ InferService                     │    │◄───────────┘         │
│   │   │   ├─ ThreadedPipeline (4线程)     │    │                      │
│   │   │   ├─ _FrameProcessor              │    │                      │
│   │   │   │                                │    │                      │
│   │   │   │  ★ 接缝(对外暴露)              │    │                      │
│   │   │   ├─ OutputSink   ← 输出去哪儿     │    │                      │
│   │   │   ├─ InferHooks   ← 进度/事件      │    │                      │
│   │   │   └─ CancelToken  ← 谁来叫停       │    │                      │
│   │   └──────────────────────────────────┘    │                      │
│   │             ▲           ▲                  │                      │
│   └─────────────┼───────────┼──────────────────┘                      │
│                 │           │                                          │
│        ┌────────┴───┐  ┌────┴───────────┐                             │
│        │frame_source│  │ visualization  │  ← 当前章节预设已知          │
│        └────────────┘  └────────────────┘                             │
│                                                                        │
│    ┌─ 业务前端(消费接缝, 各自独立, 推理子系统对它们一无所知)─┐         │
│    │                                                              │   │
│    │   apps/cli/infer.py     LocalFileSink + 终端日志             │   │
│    │   apps/desktop/         QtSignalSink + QThread + QLabel      │   │
│    │   apps/web-backend/     WebSocketSink + Celery + Redis       │   │
│    │                                                              │   │
│    └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

D8 的边界承诺(grep 守门):

```bash
# inference 包内 0 输出, 跟训练完全解耦:
grep -r "from odp_platform.training" apps/platform/src/odp_platform/inference/

# inference 包内 0 输出, 不依赖任何前端框架:
grep -rE "import PyQt|import PySide|from fastapi|import celery" \
     apps/platform/src/odp_platform/inference/
```

两条命令都返回空 → D8 的边界稳了。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 0: 立规矩 — 推理跟训练的 3 个关键差异

跟 D6 训练子系统比起来,推理子系统**不是镜像复制** — 表面架构相似(都是 Service + ResultDataclass),但底层有 3 个根本不同。**先把这 3 点放清楚,后面的设计选择就都顺理成章了**。

## 0.1 差异①: 训练是"一次跑完",推理是"持续吐帧"

| | 训练 (D6) | 推理 (D8) |
|---|---|---|
| 调用方式 | `model.train(...)` 阻塞跑到结束 | 帧源逐帧给图, 持续跑 |
| 时间尺度 | 小时级 | 单帧毫秒级, 整次任意长 |
| 反馈频率 | 每个 epoch 一条日志 | 每帧一次绘制 |
| 中断成本 | 高(丢一个 epoch) | 低(丢当前帧) |
| 用户交互 | 几乎没有 | 实时按键(暂停/退出),或 GUI 点 Stop |
| 谁调用 | 一般只有 CLI | CLI + 桌面 + Web + 异步任务都可能调 |

**这决定了:**

- 推理不能用 `model.predict(source=...)` 那种 ultralytics 自带的"一行跑完" — 那样 ultralytics 完全接管循环、我们插不进暂停 / 实时美化 / 多源切换 / **业务回调** / **程序化取消**。**推理必须自己写主循环**。
- 推理需要"流式"思维:**生产者-消费者模型 + 缓冲队列**。
- 推理需要**生命周期事件**(开始/每帧/进度/结束/出错),业务方按需订阅。这就是阶段 6 的 `InferHooks` 接缝。
- 推理需要**程序化取消**(GUI 点 Stop / WebSocket 断开 / 任务被 revoke),不能只靠键盘按键。这就是阶段 6 的 `CancelToken` 接缝。

## 0.2 差异②: 训练只摸 GPU,推理同时摸 GPU + 摄像头 + GUI + 磁盘

训练 100% 算力都在 GPU 上,CPU 只跑一个 dataloader、显示一条进度条 — 单线程就够。

推理需要**同时**:

- **从摄像头驱动拿帧**(I/O,在另一个 OS 进程)
- **GPU 推理**
- **CPU 画框 + 写中文字**
- **OpenCV 刷 GUI 事件循环**
- **磁盘写 mp4 / jpg**

5 件事都不轻,串成一条循环 = 整条链上最慢的环节决定整体速度。**这就是为什么 D8 必须上多线程,而 D6 不用**。阶段 1-3 会详细展开。

## 0.3 差异③: D5 配置不够用,推理还需要"帧源 + 美化"那一半

D5 的 `YOLOInferConfig` 是 YOLO 官方 predict 参数的 pydantic 化:`conf` / `iou` / `imgsz` / `max_det` / `classes` / ...,所有字段都是**扁平**的 key:value。

但帧源参数和美化参数天然是**嵌套**的:

```yaml
frame_source:
  camera:           # ← 嵌套一层: source 是摄像头时才用
    width: 1280
    height: 720
    fps: 90
visualization:
  label_mapping:    # ← 嵌套一层: 字典
    person: 人员
  color_mapping:    # ← 嵌套一层: 字典里嵌列表
    person: [0, 255, 0]
  style:            # ← 又一层
    text_color: [255, 255, 255]
```

塞进 D5 的扁平模型不优雅,扩展 D5 反射器去支持嵌套又破坏"配置系统只能加、不能改"的承诺。**D8 决定自己另起一份 `infer_pipeline.yaml`**(手写),专门装这一半。两份 yaml 互不打架(详见阶段 4)。

---

## 0.4 立 4 条 D8 的纪律

借鉴 D5 的"4 条工程规矩",D8 自己再立 4 条:

### 纪律 A: pipeline 永不抛、service 永不抛

任何深层异常(模型加载失败、源打不开、单帧绘制崩、磁盘满)**都不能让 `service.predict()` 抛出去**。所有异常必须在 `service.py` 顶层 try/except 兜住,打包成 `InferResult.error`。CLI 层根据 `result.success` 决定退出码。

→ 见阶段 8.8 的实现。

### 纪律 B: handler 唯一装配点 — CLI

D2 的 `get_logger` 留了规矩:**业务模块只发声,handler 由 CLI 唯一装配**。D8 全程遵守:

- `service.py` / `pipeline.py` / `overlay.py` / `sinks.py` / `hooks.py` / `cancel.py` 只有 `logger = logging.getLogger(__name__)` + `logger.info(...)`
- 装 console + file handler 的代码**只在** `cli/infer.py` 里出现一次

为什么? 因为 service 是个可被外部调用的库函数(`infer_yolo(...)`),装 handler 是 CLI 的事,库不应该污染调用方的 logging 配置。桌面端有自己的 logging(`logging.basicConfig` 在 `main.py` 里),Web 端有自己的(Uvicorn 接管),**library 不挑事**。

### 纪律 C: 主线程不碰 GUI

`cv2.imshow` / `cv2.waitKey` / `cv2.pollKey` **只允许在 `_Display` 线程里调**。主线程一旦碰 GUI,整个性能优势瞬间归零(为什么? 阶段 1.5 会用数字说明)。

→ 见阶段 7.6 的实现。

### 纪律 D: ★ 业务无感知的接缝 — apps/platform 不依赖任何前端框架

`apps/platform/src/odp_platform/inference/` 这个目录是**推理引擎本身**,它的职责是"接帧、推理、画框、给结果"。**它不应该知道**:

- 谁在显示画面(可能是 `cv2.imshow`,可能是 Qt QLabel,可能是 WebSocket 帧推送)
- 谁在保存结果(可能是本地 mp4,可能是 S3,可能是数据库 BLOB)
- 谁在叫它停(可能是 `q` 键,可能是 GUI 按钮,可能是 Celery `task.revoke()`)
- 谁要进度反馈(可能是终端日志,可能是 GUI 进度条,可能是 WebSocket push)

所以推理引擎对外只暴露三个**抽象接缝**:

| 接缝 | 干什么 | 默认实现 | 业务方实现 |
|---|---|---|---|
| **`OutputSink`** ABC | "annotated 帧给我,我决定送哪儿" | `LocalFileSink`(写本地)、`NullSink`(丢弃) | `QtSignalSink`(发 Qt 信号)、`WebSocketSink`(WS 推流)、`S3Sink`(对象存储) |
| **`InferHooks`** dataclass | "我推理到 X 阶段了,你要不要做点啥" | 全空回调(零开销) | GUI 进度条更新、WebSocket push、Celery state 更新 |
| **`CancelToken`** | "你给我一个信号,我看到就优雅退出" | `None`(只能等帧源耗尽) | GUI Stop 按钮、WS 断线、Celery revoke 都可以 `cancel()` |

**grep 守门**:

```bash
grep -rE "import PyQt|import PySide|from fastapi|import celery" \
     apps/platform/src/odp_platform/inference/
# → 必须 0 输出
```

这条纪律比 A/B/C 更"软"(它的违反不会立刻让程序崩),但**违反它会让整个项目慢慢腐化**:今天为了一个桌面 demo 在 inference 里 `import PySide6`,明天 Web 后端要 `import fastapi`,后天异步任务要 `import celery`,半年后 inference 模块依赖一坨前端 lib,Docker 镜像膨胀 5 倍、单测跑不动、想换 GUI 框架要改推理代码 — 这就是"业务前端污染推理引擎"的滑坡。

→ 见阶段 6 的实现。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 1: 朴素单线程版 — 立基线, 顺便撞 3 堵墙

## 1.1 任务设定: 一次实时推理至少要做 4 件事

抛开任何工程考虑,一段最简单的实时 YOLO 推理脚本至少做这些:

```
[1] 拿一帧图        ← 帧源
[2] 喂模型推理      ← ultralytics
[3] 画结果         ← 美化绘制(或 result.plot())
[4] 显示+读键      ← cv2.imshow + cv2.waitKey
```

四件事串成一个 `while` 循环就是"单线程基线"。

## 1.2 完整代码 (`/tmp/infer_naive.py`)

放 `/tmp/` 是因为这版只用于演示撞墙,**不进 git 仓库**。

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# 朴素单线程 YOLO 推理 - 立基线用, 不要 commit
"""
4 步: 读帧 → 推理 → 画 → 显示
"""
import time
import cv2
from ultralytics import YOLO

from odp_platform.frame_source import create_frame_source
from odp_platform.visualization import BeautifyVisualizer


def main():
    model = YOLO("yolo11n.pt")
    class_names = list(model.names.values())
    viz = BeautifyVisualizer(labels=class_names)

    # 计时统计
    n_frames = 0
    t_read = t_infer = t_draw = t_show = 0.0
    t_start = time.perf_counter()

    with create_frame_source("0") as src:        # "0"=摄像头, 或换 "demo.mp4"
        for frame in src:
            # ---- [1] 帧已经在 for 里拿到, 这里计时是为了演示 ----
            t0 = time.perf_counter()
            t_read += time.perf_counter() - t0   # 实际读帧耗时在 src.__next__ 里

            # ---- [2] 推理 ----
            t0 = time.perf_counter()
            result = model(frame.image, verbose=False)[0]
            t_infer += time.perf_counter() - t0

            # ---- [3] 美化 ----
            t0 = time.perf_counter()
            boxes = result.boxes
            n = len(boxes) if boxes is not None else 0
            if n:
                labels = [model.names[i] for i in boxes.cls.int().cpu().tolist()]
                dets = BeautifyVisualizer.from_yolo_results(
                    boxes=boxes.xyxy.cpu().numpy(),
                    confidences=boxes.conf.cpu().numpy(),
                    labels=labels,
                )
            else:
                dets = []
            annotated = viz.draw(frame.image, dets)
            t_draw += time.perf_counter() - t0

            # ---- [4] 显示 + 读键 ----
            t0 = time.perf_counter()
            cv2.imshow("infer-naive", annotated)
            key = cv2.waitKey(1) & 0xFF
            t_show += time.perf_counter() - t0

            n_frames += 1
            if key == ord("q"):
                break

    cv2.destroyAllWindows()

    # ---- 打报告 ----
    total = time.perf_counter() - t_start
    print(f"\n=== 跑了 {n_frames} 帧, 总耗时 {total:.1f}s, 平均 {n_frames/total:.1f} FPS ===")
    print(f"推理: {t_infer/n_frames*1000:.1f} ms/帧")
    print(f"绘制: {t_draw/n_frames*1000:.1f} ms/帧")
    print(f"显示: {t_show/n_frames*1000:.1f} ms/帧 (含 waitKey 阻塞)")


if __name__ == "__main__":
    main()
```

## 1.3 跑一下

```bash
$ python /tmp/infer_naive.py
# (推理窗口弹出, 跑 30 秒后按 q)

=== 跑了 760 帧, 总耗时 30.1s, 平均 25.2 FPS ===
推理: 14.2 ms/帧
绘制: 4.1 ms/帧
显示: 7.5 ms/帧 (含 waitKey 阻塞)
```

(实测笔记本 + RTX 3060 + 720p USB 摄像头 + yolo11n。你的硬件不同数字会变,但**相对量级**稳定。)

把"读帧"那段也用更精确的方式测出来(改 `frame_source/sources/camera.py` 里加 timer):差不多 13~15 ms/帧。

合一下:

```
读帧 14 ms + 推理 14 ms + 绘制 4 ms + 显示 8 ms = 40 ms ≈ 25 FPS
```

跟上面 25.2 FPS 对得上。

## 1.4 🧱 撞墙①: 串行链条 — 摄像头 60 FPS 被拖到 25 FPS

我用的这台摄像头规格表写着 720p@60fps。在 OBS 里直接拉它能稳定跑 60 fps。

但在我的脚本里只有 25 fps。**21 ms 的"非推理"时间(读帧 14 + 绘制 4 + 显示 8 - 5 ms 重叠 ≈ 21)硬生生把帧率从 60+ 压到 25**。

这就是**串行链条的致命病**:

```
[读帧 14ms]─[推理 14ms]─[绘制 4ms]─[显示 8ms]─[读帧 14ms]─[推理 14ms]─...
└─────────────────── 40 ms / frame ────────────────────┘
```

每一段都**必须**等前一段做完。摄像头实际给帧的速率 = 整条链消费速率 = 25 fps。摄像头驱动有缓冲,但缓冲会被消费速率反压;消费 25 fps 久了摄像头实际也只送 25 fps,**新帧到达消费端时已经"老"了几十毫秒**。

**为什么这个病在单线程结构下无解?** 因为 Python 的 `for` 循环本质就是 `__next__` 一帧 → 处理一帧 → `__next__` 下一帧。**没有并行的余地**。

## 1.5 🧱 撞墙②: `cv2.waitKey(1)` 不是真的 1ms

新手最容易踩的坑。表上写"`waitKey(delay_ms)`",直觉以为 `waitKey(1)` = 睡 1ms。**错**。

实际 `waitKey(1)` 是:

> **最多睡到 1 ms 或直到收到按键事件,期间必须刷一次 OS 的 GUI 事件循环。**

刷 GUI 事件循环这件事在不同平台代价不同:

- Windows + GDI:3~8 ms
- Linux + X11:2~6 ms
- macOS + Cocoa:**5~20 ms**(Cocoa 主循环必须切线程,代价最大)

你设的 `waitKey(1)` 不是 1ms,是"至少 1ms + 平台 GUI 刷新成本"。**实测我那台机器上单次 7.5 ms** — 占了整个单帧时间的 20%。

**关键洞察**:`waitKey` 不可避免(没它就读不到按键),但**它不应该在跑推理的那个线程里** — 这就是纪律 C(主线程不碰 GUI)的来源。

## 1.6 🧱 撞墙③: GPU 60% 时间是闲的

复习上面的数字:推理 14ms,总耗时 40ms。**也就是说 GPU 有 (40-14)/40 = 65% 的时间没事干**,只是因为主线程在读帧、画框、显示。

你花一万块买的 GPU,有 65% 的时间在打瞌睡。

如果能让"读帧"和"画框"在 GPU 推理的同时干 — GPU 利用率上去、整体吞吐拉升、摄像头能跑到接近 60 fps。**这就是把单线程拆成多线程的核心动力**。

## 1.7 这版不 commit

```bash
# /tmp/infer_naive.py 别 git add —— 它在我们文件系统外, 演完就丢
```

朴素方案就是用来撞墙的,撞完即丢。正式代码从阶段 4 开始落 git。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 2: 单线程 → 多线程 — 概念关 + GIL 关

撞完三堵墙,大方向已经定了:**必须把任务拆成多个并行单元**。但具体上多线程还是多进程? Python 那个臭名昭著的 GIL 不是会让多线程没用吗? 这一节专门把这两个疑问消掉。

## 2.1 什么是单线程? 什么是多线程?

回到最朴素的定义:

- **进程 (Process)**:一个跑起来的程序实例。每个进程有自己独立的内存空间。
- **线程 (Thread)**:进程里的一个执行流。**同一进程里所有线程共享内存**。
- **单线程**:一个进程只有一个执行流, 整个程序 = 一条 `主线程`。
- **多线程**:一个进程开多个执行流, 它们**理论上**能在多个 CPU 核心上**同时**跑。

阶段 1 的朴素脚本是单线程 — 整个 `for` 循环只有"主线程"一条。

多线程的思路是:**把 `for` 循环里的 4 件事拆给不同线程,各自跑**。

```
单线程:
  主线程  ──[读]──[推]──[画]──[显]──[读]──[推]──[画]──[显]──...

多线程(理想):
  reader线程  ──[读][读][读][读][读][读][读][读][读][读][读]──...
  主线程             ──[推]──[推]──[推]──[推]──[推]──[推]──...
  renderer线程               ──[画]──[画]──[画]──[画]──[画]──...
  display线程                       ──[显][显][显][显][显][显]──...
                              └ 4 件事真正并行 ┘
```

**理论上**,如果完美并行,整条流水线的吞吐 = max(读, 推, 画, 显) = 14 ms = **71 FPS**。

但 — Python 的 GIL 让"理论"打折。

## 2.2 GIL 是什么? 为什么大家说 Python 多线程没用?

**GIL** = Global Interpreter Lock = 全局解释器锁。

CPython(我们最常用的 Python 实现)有个设计:**任何 Python 字节码同一时刻只能被一个线程执行**。即使你开 8 个线程在 8 核 CPU 上,**纯 Python 代码的实际并行度依然 = 1**。

**所以下面这段经典案例,4 个线程做计算密集型任务,跟单线程速度一样:**

```python
import threading

def cpu_heavy():
    s = 0
    for i in range(10**7):
        s += i * i
    return s

# 单线程
cpu_heavy()             # 假设 2.0 秒

# 4 线程
threads = [threading.Thread(target=cpu_heavy) for _ in range(4)]
for t in threads: t.start()
for t in threads: t.join()
# 总耗时 ≈ 8.0 秒, 不是 2.0 秒 — GIL 让它们排队执行
```

这就是"Python 多线程没用"那句话的来源。**但这句话只对一半**。

## 2.3 GIL 锁的是 Python 字节码,不锁 C 扩展

GIL 还有个**关键例外**:

> **当某段代码进了 C 扩展并主动 release 了 GIL,这段时间其他 Python 线程就能在另一个核上真并行跑。**

回头看 D8 推理这条链上的所有"重活":

| 活 | 谁干 | 进 C 扩展? | 释放 GIL? |
|---|---|---|---|
| 摄像头/视频解码 | OpenCV `cv2.VideoCapture.read()` | ✓ | ✓ |
| YOLO 推理(GPU) | PyTorch / CUDA 算子 | ✓ | ✓ |
| Numpy 张量操作 | numpy C 实现 | ✓ | ✓ |
| `cv2.rectangle` / `cv2.putText` | OpenCV | ✓ | ✓ |
| PIL 文本渲染 | Pillow C 实现 | ✓ | ✓ |
| `cv2.imshow` / `cv2.waitKey` | OpenCV GUI 后端 | ✓ | ✓ |
| `q.put()` / `q.get()` (阻塞时) | CPython queue 模块 | ✓ | ✓ |

**所有重活全部都释放 GIL**。这就是 D8 推理多线程能真并行的**物理基础**。

换句话说:阶段 1 的朴素 cpu_heavy 是"纯 Python 算术",GIL 卡死;D8 推理是"C 扩展跑算力 + Python 跑胶水",GIL 不挡道。

## 2.4 多线程 vs 多进程 — 为什么这场景选多线程

理论上多进程更彻底(每个进程独立 GIL,纯 Python 也能并行)。为什么 D8 选多线程?

| 维度 | 多线程 | 多进程 |
|---|---|---|
| 并行度(本场景) | ✓ 全 C 扩展, 跟多进程一样 | ✓ |
| 帧传递 | ✓ 共享内存零拷贝 | ✗ 必须序列化 / 走共享内存(复杂) |
| 模型加载 | ✓ 一份模型多线程共用 | ✗ 每进程一份, 显存 ×N |
| GUI 窗口 | ✓ imshow 在同进程, 自然工作 | ✗ 跨进程 GUI 是地狱 |
| 异常传播 | ✓ 直接 raise 到主线程 | ✗ 进程间异常要专门 pickle |
| 调试 | ✓ pdb 一键搞定 | ✗ 多进程调试要 attach |

**4 件事重要、其中 3 件多进程做不好:帧传递、显存、GUI**。多线程是这个场景里唯一合理的选择。

## 2.5 一句口诀, 带走

> **Python 多线程能不能加速,看你的瓶颈是不是在释放 GIL 的 C 扩展里。**
>
> **是 → 上多线程,实测能并行。**
>
> **不是(纯 Python 循环计算) → 多线程没用,上多进程或换 Cython/Numba。**

D8 推理 = 全是 C 扩展 = 多线程稳赢。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 3: 流水线规划 — 4 个决策决定流水线形状

知道"该上多线程"之后,真正的难点开始:**沿什么轴切?谁拿主线程?线程间怎么传?谁能从外面插进来?** 这四个决策**做错了,多线程反而比单线程慢 + 没法服务多前端**。

## 3.1 决策一: 按"职责"切, 不按"数据"切

两种切法都能写:

### 朴素方案 A: 按数据切(数据并行)

开 N 个线程,每个线程**完整跑一帧**(读+推+画+显)。

```python
# 伪代码 — 看着合理, 实际是灾难
def worker():
    while running:
        frame = read_one()
        result = model(frame)
        annotated = draw(frame, result)
        show(annotated)

threads = [Thread(target=worker) for _ in range(4)]
```

**为什么不行?**

1. **GPU 只有一块**。N 个线程都 `model(...)`,ultralytics 内部对模型 forward 是同步阻塞 GPU 的 — N 个线程 = N 个排队 = 等于退化成单线程,还多了线程切换开销。
2. **GUI 只有一个窗口**。`cv2.imshow` 必须从同一个线程刷,N 个线程同时刷 = 要么崩要么乱。
3. **帧序乱了**。摄像头是按时间顺序给帧的,N 个 worker 谁先跑完显示谁,**画面会回退**。

### 决策方案 B: 按职责切(流水线并行)

把四件事拆成**独立工种**,每个工种一个线程,帧像零件一样过流水线。

```
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│ reader   │→│  推理     │→│ renderer │→│  display  │
│ 1 个线程  │  │ 1 个线程  │  │ 1 个线程  │  │ 1 个线程  │
└──────────┘  └──────────┘  └──────────┘  └──────────┘
   I/O           GPU           CPU          GUI
```

**优点齐活:**

- GPU 那条线只有 1 个线程在用 → 不抢资源
- GUI 那条线只有 1 个线程在刷 → 不闪不崩
- 帧按顺序流过 → 显示顺序正确
- 每条线**专注一件事** → 性能可测、bug 可定位

**这就是阶段 1 那张"理想多线程"图的真正实现**。

## 3.2 决策二: GPU 那条线必须挂在主线程

四条线里推理这一条,我们**必须**让它跑在**主线程**。

**为什么?**

1. **CUDA / PyTorch 对调用线程有隐含假设**。CUDA stream / pinned memory / 异常栈追踪在主线程里行为最一致。子线程里碰 CUDA 偶发的非确定性 bug 很难查。
2. **Python 的信号(`Ctrl+C` / `KeyboardInterrupt`)只送主线程**。推理在主线程意味着 `Ctrl+C` 能直接打断推理循环;在子线程里跑推理,`Ctrl+C` 来了主线程在 sleep,没意义。
3. **调试体验**。`pdb` / IDE 断点在主线程最自然。

**所以分工是:**

```
主线程       ← 推理(model forward) + 派发 + 周期触发 hooks
reader 线程  ← I/O
renderer 线程← CPU 画框 + 写盘 + 每帧触发 hooks
display 线程 ← GUI imshow + 读键 (CLI 模式; 桌面模式跳过)
```

reader / renderer / display 都是 `daemon=True` 的子线程,主线程退它们自动跟着死。

**桌面端的一点不同**:桌面 GUI 模式下 `display` 线程不启动(GUI 自己刷 QLabel,不需要 cv2.imshow)。但**主线程仍然挂 GPU 那条线** — 桌面端把 `InferService.predict()` 整个塞进一个 `QThread` 跑,从 InferService 的视角看,它自己就是"主线程"。Qt 的 `QThread` 是真线程,CUDA 跨线程在这个层面是 OK 的(只要同一个 model 实例不被多线程并发调,就没问题)。详见阶段 11。

## 3.3 决策三: 线程间用 `queue.Queue` + 哨兵对象

线程间传东西,Python 标准库 `queue.Queue` 已经处理好了所有麻烦事:

- **线程安全**(内部用锁)
- 支持 `maxsize` 限容量(防止生产者跑飞内存爆炸)
- `put(timeout=...)` / `get(timeout=...)` 防止永久阻塞
- `put_nowait` / `get_nowait` 配合 `Full` / `Empty` 异常,能写"满了就丢"的策略

**哨兵对象**用来传递"流结束"信号:

```python
_SENTINEL = object()    # 全局唯一对象, is 比较, 不会跟正常数据冲突

# 生产端发现源耗尽时:
q.put(_SENTINEL)

# 消费端:
item = q.get()
if item is _SENTINEL:
    break    # 不再有数据, 我也该退了
```

哨兵的优雅之处:它**沿着流水线一路传下去** — reader 看到源耗尽 → 把哨兵放进 in_q;renderer 拿到哨兵 → 把哨兵转发到 out_q;display 拿到哨兵 → 自己也准备退出。**整条流水线优雅退出靠这一个对象,不需要复杂的关停通信**。

**为什么不用 `Event`?** `Event` 是无序的、即时生效的 — 一旦 set,所有等它的线程立刻醒来,**会把还没渲染完的帧落下**。`_SENTINEL` 走队列 = 排在它前面的帧一定先处理完。**这就是哨兵相对 Event 的关键优势:顺序保证**。

那"程序化取消"用什么? — 用 `Event` 也行,但我们封装成 `CancelToken`(语义更清晰),且**只用作"主线程要不要继续取下一批"的查询信号**,不掺合到队列里。已经在队列里排队的帧仍然要被处理完(纪律 A:不能丢数据)。详见阶段 6.3 + 7.9。

## 3.4 ★ 决策四: 接缝隔离 — 让推理引擎不知道谁在消费

到这里前 3 个决策都是"传统多线程流水线"的常识。第 4 个决策是 D8 区别于"老式 yolo_server"的关键 — **让同一套推理引擎能服务 CLI / 桌面 / Web / 异步任务**。

### 反例:把消费方写死在 pipeline 里

老式做法,在 `_Renderer` 线程里直接写:

```python
# ❌ 反例: 把"消费方"写死
class _Renderer(Thread):
    def run(self):
        for item in self._in_q:
            annotated = self._proc.draw(...)
            cv2.imwrite(self._out_dir / f"{idx}.jpg", annotated)   # 直接写本地
            cv2.imshow("preview", annotated)                        # 直接 imshow
```

**问题立刻浮现**:

- 桌面端不要 `cv2.imshow`,要 Qt 信号 → 改 `_Renderer`
- Web 端不要本地文件,要 WebSocket push → 又改 `_Renderer`
- Celery 异步任务不要任何输出 (只要统计) → 又改 `_Renderer`

`_Renderer` 变成大杂烩 + 一堆 `if mode == "cli" elif mode == "qt"`,推理引擎跟前端"长在一起"。这违反**纪律 D**。

### 正解:三个抽象接缝, 默认实现等价老式行为

D8 把"消费方能定制的三个维度"抽出来:

| 维度 | 接缝 | 在哪里调用 |
|---|---|---|
| **输出去哪儿** | `OutputSink` (open/write/close) | `_Renderer` 拿到 annotated 后 `sink.write(frame, annotated)` |
| **进度/事件** | `InferHooks` (4 个回调) | 主线程派发完 → `hooks.fire_progress`;renderer 画完 → `hooks.fire_frame` |
| **要不要停** | `CancelToken` (cancel/is_cancelled) | 主线程取批前 / 派发后 各一个查询点 |

`InferService.predict()` 的签名变成:

```python
def predict(
    self,
    yaml_path=None, pipeline_yaml=None, cli_args=None,
    *,
    beautify=True, rename_log=True, threaded=False,
    warmup_frames=0, window_name="odp-infer", show_info=True,
    # ★ 三个接缝, 全部 keyword-only, 默认 None
    output_sink: OutputSink | None = None,
    hooks: InferHooks | None = None,
    cancel_token: CancelToken | None = None,
) -> InferResult:
```

**关键纪律**:

- **三个新参数都是 `keyword-only` + `Optional[None]`**。CLI 调用 `service.predict(yaml_path=...)` 一行不改,**完全等价于不传** → CLI 行为零变化。
- **不传 sink** → service 内部根据 `want_save` 自动选 `LocalFileSink`(等价老式 `cv2.imwrite`)或 `NullSink`。
- **不传 hooks** → service 内部用 `InferHooks()` 空回调兜底,`fire_*` 内部 short-circuit,零开销。
- **不传 cancel_token** → 主循环里的 `is_cancelled` 查询直接 `return False`,零开销。

**消费方的具体实现**:

- **CLI**:`output_sink=LocalFileSink()`, `hooks=InferHooks()`(空), `cancel_token=None` — 跟改造前完全一样。
- **桌面**:`output_sink=QtSignalSink()`(主线程接收 Qt 信号), `hooks=InferHooks(on_progress=...)`(更新进度条), `cancel_token=CancelToken()`(GUI Stop 按钮调 `cancel()`)。
- **Web**:`output_sink=WebSocketSink(ws)`, `hooks=InferHooks(on_progress=push_to_redis)`, `cancel_token` 跟 WS 断线绑定。
- **Celery**:`output_sink=NullSink()`(只要统计), `hooks=InferHooks(on_progress=update_task_state)`, `cancel_token` 跟 `task.is_revoked()` 轮询绑定。

四种用法,**同一个 `InferService.predict()` 函数,推理代码 0 行改动**。这就是接缝隔离的威力。

> 📦 grep 验证: `apps/platform/src/odp_platform/inference/` 内部不能有任何 `import PyQt | PySide | fastapi | celery`。这一条是 CI 守门的。

## 3.5 四级流水线总览(含接缝兑现位)

把四个决策合起来,D8 的流水线长这样:

```
源(摄像头/视频/图片)
    │
    ▼  daemon 线程
┌───────────┐
│  _Reader  │  读 frame → reader.q
│           │  策略: live=丢旧只留最新; file=阻塞不丢
└─────┬─────┘
      │ reader.q (maxsize: live=1; file=max(bsz*2, 8))
      ▼
┌───────────┐
│   主线程   │  ★ 4 个 cancel_token 查询点(< 2s 响应)
│           │  ★ 周期 hooks.fire_progress
│           │  批量 model(images) → ultralytics
│           │  累计统计 + 非阻塞派发 + 读键(经 get_key)
└─────┬─────┘
      │ in_q (maxsize: max(bsz*2, 4))
      │  派发: save=阻塞不丢; 不save=丢旧
      ▼
┌───────────┐
│ _Renderer │  美化 viz.draw
│           │  ★ sink.write(frame, annotated)   ← 接缝
│           │  ★ hooks.fire_frame(FrameEvent)    ← 接缝
│           │  叠 HUD draw_hud(disp, m)
└─────┬─────┘
      │ out_q (maxsize: 2, 浅且通常丢旧 = 低延迟)
      ▼
┌───────────┐
│ _Display  │  ★ 唯一碰 cv2.imshow / cv2.pollKey 的地方
│           │  自带 _last 缓存 → 暂停时叠 draw_pause
│           │  (桌面 GUI 模式: 此线程不启动, 走 QtSignalSink)
└───────────┘

收尾: pipeline 调 sink.close() + service 调 hooks.fire_complete(result)
异常: service 顶层 except 调 hooks.fire_error(exc) → 不抛
```

阶段 4-9 会一个文件一个文件地把这条流水线搭起来。**搭的顺序是从外向内,从"配置 / 测量 / 接缝"这种独立小模块开始,最后才到核心 pipeline.py**。这样每一步都能独立测试,不会变成"必须等所有文件都写完才能跑"的灾难。

搭建顺序:

| 阶段 | 文件 | 依赖谁 |
|---|---|---|
| 阶段 4 | `pipeline_config.py` | 只依赖 frame_source 的 CameraConfig |
| 阶段 5 | `overlay.py` | 只依赖 cv2 |
| 阶段 6 | `sinks.py` + `hooks.py` + `cancel.py` | ★ 接缝模块:几乎 0 依赖, 纯抽象 |
| 阶段 7 | `pipeline.py` | 依赖 overlay + frame_source + 接缝模块 |
| 阶段 8 | `service.py` | 依赖 pipeline + pipeline_config + D5 + D2 + common + 接缝模块 |
| 阶段 9 | `cli/infer.py` + `__init__.py` | 依赖 service |
| 阶段 10 | (真机跑通 CLI, 不新增代码) | — |
| 阶段 11 | `apps/desktop/{qt_sink, infer_worker, main}.py` | 依赖 service + 接缝模块 + PySide6 |
| 阶段 12 | (总结, 不新增代码) | — |

每个阶段末尾都给完整代码,**学生抄到对应路径下就能立刻 import + 单测**。

---
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 4: `pipeline_config.py` — 装 D5 管不到的那一半配置

## 4.1 为什么不全塞 D5

阶段 0.3 已经说了:D5 的 `YOLOInferConfig` 是扁平 key:value 模型,而帧源 + 美化的配置天然嵌套(camera 块、label_mapping 字典、style 块)。强塞 D5 要改 D5 反射器,破坏"配置系统只能加不能改"的承诺。

我们的处理:**自起一份 `infer_pipeline.yaml`**,只装这一半配置,由 inference 子系统自己读、自己用。**两份 yaml 互不干涉,各管各的**。

```
infer.yaml           ← D5 build_infer_config 读, 装 YOLO predict 参数(扁平)
infer_pipeline.yaml  ← 本阶段的 helper 读, 装 帧源+美化 参数(嵌套)
```

## 4.2 设计点①: `PipelineConfig` 是纯 dataclass,延迟构造 CameraConfig

`PipelineConfig` 解析结果是一个**纯数据 dataclass**,不持有任何"活的"对象:

- `camera_raw: dict` — 原始 camera 子字典(不立即构造 `CameraConfig`)
- `label_mapping: dict`、`color_mapping: dict`、`style_overrides: dict` — 都是普通字典

为什么不立即构造 `CameraConfig` 实例?

**因为不确定是不是摄像头源**。`infer_pipeline.yaml` 是个**通用配置**,可能 source 是视频文件(此时 camera 块毫无意义)。立即构造会导致:

- 视频源场景下白构造了一个 `CameraConfig` → 浪费
- 用户配错(`fps: "thirty"`)却在构造时炸 → 报错位置错(不应该在视频源场景下报)

**解决**: `PipelineConfig` 持有 `camera_raw: dict`,真到要用时才 `CameraConfig(**camera_raw)` — 这个动作放在 `PipelineConfig.build_camera_config()` 方法里。`frame_source.create_frame_source` 内部会自动判断"摄像头才需要 camera_config",不是摄像头就忽略,完美对接。

## 4.3 设计点②: 文件缺失不算错, 降级 + warn

`infer_pipeline.yaml` 是**锦上添花**,不是**核心必需**:

- 你完全可以只在 `infer.yaml` 写 `source: 0` + `model: yolo11n.pt`,啥 pipeline yaml 都不要,推理也能跑(走默认值,不美化,摄像头走 CameraConfig 默认 720p@30)。
- 有需要再写 pipeline yaml,加 label_mapping(英文 → 中文)、color_mapping(自定义类别色)、style overrides(字号 / 线宽)。

所以 `load_pipeline_config(yaml_path)` 遇到文件不存在时:**logger.warning + 返回空 PipelineConfig**,**不抛**。这跟"D8 整体永不抛"的纪律 A 一脉相承。

## 4.4 设计点③: BGR 颜色的统一转换

yaml 里写颜色:

```yaml
color_mapping:
  person: [0, 255, 0]      # 绿
  car:    [0, 0, 255]      # 红
default_color: [255, 0, 0] # 蓝
```

yaml 解析出来是 **list**,但美化模块 `BeautifyVisualizer` 吃的是 **tuple**(因为 tuple 不可变、能 hash、能当 dict key)。

中间用一个 helper `_to_bgr_tuple` 做统一转换:

```python
def _to_bgr_tuple(value: Any) -> tuple[int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    raise ValueError(f"颜色必须是 3 元素的 [B, G, R], 收到: {value!r}")
```

**fail-fast 在解析时**(yaml 写错了立刻知道哪一行错),**而不是延迟到美化时**(那时帧已经在跑,报错位置不直观)。

## 4.5 完整代码:`apps/platform/src/odp_platform/inference/pipeline_config.py`

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : pipeline_config.py
# @Project   : ODPlatform
# @Function  : 读取 infer_pipeline.yaml(帧源+美化) — D5 管不到的那半边配置
"""帧源捕获 + 美化 的配置读取 helper.

★ 核心纪律: 不重新发明校验. 这个 helper 只做"yaml → 子字典 → 喂给现成 pydantic 模型":
  - camera 块  → frame_source.CameraConfig(**...)   (extra=forbid, 自带校验)
  - style 块   → 透传给 visualization.DrawStyle.from_image_size(**...) (拿到帧尺寸后才构造)
  - 颜色 list  → tuple (BGR), 因为美化模块吃 tuple

跟 D5 的关系: D5 的 infer.yaml 管 YOLO predict 参数(build_infer_config 读),
这份 infer_pipeline.yaml 管帧源+美化, 两份互不干涉. service 阶段 1 各读各的再捏一起.

文件缺失不算错误 —— 用默认值(美化开启、无中文映射、摄像头走 CameraConfig 默认),
打一条 warning 即可. 基本版只要有模型 + 源就能跑, pipeline yaml 是锦上添花.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _to_bgr_tuple(value: Any) -> tuple[int, int, int]:
    """yaml 里颜色是 list [B,G,R], 美化模块吃 tuple, 转一下."""
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    raise ValueError(f"颜色必须是 3 元素的 [B, G, R], 收到: {value!r}")


@dataclass
class PipelineConfig:
    """帧源 + 美化 配置的解析结果(纯数据, 不含行为)."""

    # ---- 帧源 ----
    camera_raw: dict[str, Any] = field(default_factory=dict)   # 原始 camera 子字典, 延迟构造 CameraConfig

    # ---- 美化 ----
    viz_enabled: bool = True
    use_label_mapping: bool = True
    label_mapping: dict[str, str] = field(default_factory=dict)
    color_mapping: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    default_color: tuple[int, int, int] = (0, 255, 0)
    font_path: str | None = None
    style_overrides: dict[str, Any] = field(default_factory=dict)   # 透传给 DrawStyle.from_image_size

    def build_camera_config(self):
        """延迟构造 CameraConfig —— 不是摄像头源时 create_frame_source 会忽略."""
        from odp_platform.frame_source import CameraConfig
        if not self.camera_raw:
            return None
        try:
            return CameraConfig(**self.camera_raw)
        except Exception as e:
            logger.warning(f"camera 配置无效, 走默认: {e}")
            return None

    def to_audit(self) -> dict[str, Any]:
        """给 odp_audit.json 用的纯字典快照."""
        return {
            "viz_enabled": self.viz_enabled,
            "use_label_mapping": self.use_label_mapping,
            "label_mapping_n": len(self.label_mapping),
            "color_mapping_n": len(self.color_mapping),
            "default_color": list(self.default_color),
            "font_path": self.font_path,
            "camera": dict(self.camera_raw),
            "style_overrides_n": len(self.style_overrides),
        }


def load_pipeline_config(yaml_path: str | Path | None) -> PipelineConfig:
    """读 infer_pipeline.yaml. None / 文件不存在 → 空配置 + warning, 不抛."""
    if yaml_path is None:
        # 走默认路径: configs/runtime/infer_pipeline.yaml
        yaml_path = Path("configs/runtime/infer_pipeline.yaml")
    else:
        yaml_path = Path(yaml_path)

    if not yaml_path.exists():
        logger.warning(f"pipeline yaml 不存在, 用默认配置: {yaml_path}")
        return PipelineConfig()

    try:
        with yaml_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"pipeline yaml 解析失败, 用默认配置: {e}")
        return PipelineConfig()

    pc = PipelineConfig()

    # ---- 帧源 ----
    fs = raw.get("frame_source", {}) or {}
    pc.camera_raw = fs.get("camera", {}) or {}

    # ---- 美化 ----
    vz = raw.get("visualization", {}) or {}
    pc.viz_enabled = bool(vz.get("enabled", True))
    pc.use_label_mapping = bool(vz.get("use_label_mapping", True))
    pc.label_mapping = dict(vz.get("label_mapping", {}) or {})

    raw_colors = vz.get("color_mapping", {}) or {}
    pc.color_mapping = {k: _to_bgr_tuple(v) for k, v in raw_colors.items()}

    if "default_color" in vz:
        pc.default_color = _to_bgr_tuple(vz["default_color"])

    pc.font_path = vz.get("font_path")
    pc.style_overrides = dict(vz.get("style", {}) or {})

    logger.info(f"pipeline 配置加载: {yaml_path}, "
                f"美化={pc.viz_enabled}, 标签映射={len(pc.label_mapping)}, "
                f"颜色映射={len(pc.color_mapping)}")
    return pc
```

## 4.6 配套 yaml 模板:`configs/runtime/infer_pipeline.yaml`

跟代码并列发布一份**模板**,里面写所有可配字段 + 注释解释,**新同学复制就能改**。

```yaml
# infer_pipeline.yaml — ODPlatform D8 推理子系统的"帧源 + 美化"配置
# 这份配置管 D5 的 infer.yaml 管不到的那一半. 互不重叠, 各管各的.

# ============================================================================
# 帧源 (frame_source) — 主要给摄像头/RTSP 用; 视频文件 / 图片夹 走默认即可
# ============================================================================
frame_source:
  camera:
    # 这一块只有 source 是摄像头号 (0/1/2...) 时才生效, 视频文件源会被忽略
    width: 1280
    height: 720
    fps: 30
    # backend: AUTO         # 可选, 默认 AUTO; 也可以 DSHOW(Win) / V4L2(Linux) / AVFOUNDATION(Mac)
    # auto_focus: true
    # buffer_size: 1        # 摄像头驱动内部缓冲, 越小延迟越低

# ============================================================================
# 美化 (visualization) — 关掉就走 YOLO 原生 result.plot()
# ============================================================================
visualization:
  enabled: true                 # false → 退回 YOLO 原生绘制 (更快但丑)
  use_label_mapping: true       # false → 全显英文 (即使 label_mapping 非空)

  # 英文 → 中文 (没写的类别保持英文)
  label_mapping:
    person: 人员
    car: 汽车
    bicycle: 自行车
    motorcycle: 摩托车
    bus: 公交车
    truck: 卡车
    cat: 猫
    dog: 狗

  # 类别 → 颜色 (BGR), 没写的用 default_color
  color_mapping:
    person:    [0, 255, 0]      # 绿
    car:       [0, 0, 255]      # 红
    bicycle:   [255, 128, 0]    # 橙
    cat:       [255, 100, 200]  # 粉
    dog:       [200, 150, 50]   # 棕

  default_color: [0, 255, 0]    # 没在 color_mapping 里的类别用这个

  # 中文字体路径 (没装就用 PIL 默认, 中文会乱码)
  # Windows 自带: C:/Windows/Fonts/msyh.ttc
  # Mac 自带:    /System/Library/Fonts/PingFang.ttc
  # font_path: /usr/share/fonts/truetype/wqy/wqy-microhei.ttc

  # 样式覆盖 — 透传给 DrawStyle.from_image_size, 全部可省
  style:
    # box_thickness: 2            # 框线粗细 (默认自适应)
    # text_scale: 0.6             # 标签字号
    # text_color: [255, 255, 255] # 标签字色
    # text_bg_alpha: 0.6          # 标签背景不透明度 (0-1)
```

学生需要的关键提示已经全在注释里了 — 不需要再翻文档。

## 4.7 测试:4 行验证

```bash
$ cd apps/platform/src
$ python -c "
from odp_platform.inference.pipeline_config import load_pipeline_config
pc = load_pipeline_config('configs/runtime/infer_pipeline.yaml')
print(pc.viz_enabled, pc.label_mapping['person'], pc.color_mapping['car'])
print(pc.to_audit())
"
# 期望输出:
# True 人员 (0, 0, 255)
# {'viz_enabled': True, 'use_label_mapping': True, 'label_mapping_n': 8, ...}
```

故意写错一行测降级:

```bash
$ python -c "
from odp_platform.inference.pipeline_config import load_pipeline_config
pc = load_pipeline_config('/nonexistent/path.yaml')
print(pc.viz_enabled, len(pc.label_mapping))   # 走默认, 不炸
"
# WARNING: pipeline yaml 不存在, 用默认配置: /nonexistent/path.yaml
# True 0
```

文件缺失走默认 + warning,**不抛**,符合纪律 A。

## 4.8 git commit

```bash
git add apps/platform/src/odp_platform/inference/pipeline_config.py
git add configs/runtime/infer_pipeline.yaml
git commit -m "feat(D8): inference 子系统 pipeline_config.py — 装 D5 管不到的帧源+美化嵌套配置

- PipelineConfig dataclass 是纯数据 (camera_raw 延迟构造)
- 文件缺失走默认 + warning, 不抛 (纪律 A)
- 颜色 list → tuple 转换 fail-fast 在解析时
- 配套 infer_pipeline.yaml 模板, 学生复制改即可"
```

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 5: `overlay.py` — 5 维 FPS 测量 + 画面 HUD

## 5.1 5 维 FPS 各自啥口径

阶段 1 的朴素脚本只有一个"总 FPS"。**生产推理需要把 FPS 拆开看** —— 否则你只知道"慢",但不知道**谁慢**。

D8 用 **5 维**:

| 维度 | 测量点 | 反映什么 |
|---|---|---|
| **capture** | `_Reader` 线程, 每读一帧 update | 帧源**能多快给帧** (摄像头驱动 / 视频解码 上限) |
| **infer** | 主线程, `m.add_speed(result.speed)` | 模型**纯推理**速率 (ultralytics 内部测的, 不含读帧/绘制) |
| **render** | `_Renderer` 线程, 每画完一帧 update | 美化绘制速率 (BeautifyVisualizer.draw 的耗时) |
| **loop** | 主线程,**批级测量 + 均摊到帧** | **整体吞吐** (端到端单帧均摊时间) |
| **current** | `loop` 的瞬时值 (最近一个样本) | 实时波动 |

**为什么"batch 整体"算 loop, 不是"批内每一帧"算?**

主线程的一个"批"是这样跑的:

```python
# 1. reader.get(timeout=2.0) 拿首帧
# 2. for 凑 batch_size 帧 (基本是 nowait, ms 级)
# 3. self.proc.infer_batch(images)     ← 一次 GPU 调, 整批一起出
# 4. for 遍历批内每帧: stats 累加, hooks fire_progress, put 到 in_q
# 5. 回 1
```

**整批的端到端耗时 = (步骤 1 拿首帧时间) + (步骤 3 GPU 推理时间) + (步骤 4 派发时间)**。批内 N 帧**共享**这个时间。如果在"步骤 4 的 for 内部"逐帧测 `now - last_loop`,会得到:

- 第 1 帧: 真实的批端到端时间 (~50ms,合理)
- 第 2~N 帧: 几微秒 (因为只是 stats 累加 + put,没 sleep) → **污染数据**

所以正确的测量姿势是:**每批结束时算一次 (batch_end - last_batch_end) / batch_size 作为单帧均摊时间,然后这个值 update N 次填窗口**。这样滑动窗口里所有样本都是合理的"单帧时间",`loop.fps` 反映真实吞吐。

这个细节在阶段 7.9(`ThreadedPipeline` 的主循环)有完整代码 — 这里先在 5.x 把口径讲清楚,后面看代码就不困惑。

## 5.2 设计点①: `FPSCounter` — 滑动窗口 + 瞬时双口径

`FPSCounter` 是 5 维 FPS 的**单一实现**,只有两个核心方法:

```python
class FPSCounter:
    def __init__(self, window_size: int = 30) -> None:
        self._samples: deque[float] = deque(maxlen=window_size)   # 最近 30 个单帧 ms
        self._last_ms: float = 0.0

    def update(self, ms: float) -> None:
        if ms > 0:
            self._samples.append(ms)
            self._last_ms = ms

    @property
    def fps(self) -> float:
        if not self._samples:
            return 0.0
        avg = sum(self._samples) / len(self._samples)
        return 1000.0 / avg if avg > 0 else 0.0

    @property
    def inst(self) -> float:
        return 1000.0 / self._last_ms if self._last_ms > 0 else 0.0
```

**关键设计**:

- **`update(ms)` 接收毫秒**,不是秒。统一单位,**调用方就不会算错**(算错的人会写出 4000+ FPS 的 bug — 单位约束是防呆机制)。
- **`maxlen=30`** 是经验值。30 帧 ≈ 1 秒(30FPS 场景),既能平滑短期抖动,又能反映 1 秒内的变化。
- **`fps`(滑动平均)** 适合 HUD 显示和审计快照。**`inst`(瞬时)** 适合显示"当前画面"FPS,反映毛刺。

## 5.3 设计点②: `Metrics` 把 4 维 FPSCounter + ultralytics speed 打包

```python
@dataclass
class Metrics:
    capture: FPSCounter = field(default_factory=FPSCounter)
    infer:   FPSCounter = field(default_factory=FPSCounter)
    render:  FPSCounter = field(default_factory=FPSCounter)
    loop:    FPSCounter = field(default_factory=FPSCounter)

    # ultralytics result.speed 累计, 用于 audit
    _spp: float = 0.0
    _sinf: float = 0.0
    _spost: float = 0.0
    _sn: int = 0

    def add_speed(self, speed: dict | None) -> None:
        """喂入 ultralytics result.speed (ms). 同时更新 infer 帧率."""
        if not speed: return
        self._spp += float(speed.get("preprocess", 0.0))
        self._sinf += float(speed.get("inference", 0.0))
        self._spost += float(speed.get("postprocess", 0.0))
        self._sn += 1
        if speed.get("inference"):
            self.infer.update(float(speed["inference"]))
```

`Metrics` 是**一次推理跑完的快照容器**。它的 `snapshot()` 方法返回纯字典,直接序列化进 `odp_audit.json`:

```python
def snapshot(self) -> dict:
    return {
        "capture_fps": round(self.capture.fps, 1),
        "infer_fps":   round(self.infer.fps, 1),
        "render_fps":  round(self.render.fps, 1),
        "loop_fps":    round(self.loop.fps, 1),
        "current_fps": round(self.loop.inst, 1),
        "speed_ms":    self.speed_avg_ms(),
    }
```

注意 `current_fps` 直接复用 `loop.inst` —— "当前 FPS" 就是 loop 的瞬时值,不需要单独的 FPSCounter。

## 5.4 设计点③: 线程间共享 `Metrics` 是否需要锁?

`Metrics` 实例是个 dataclass,会被 `_Reader` / 主线程 / `_Renderer` **三个线程**写。需不需要加锁?

**结论:不需要**。理由:

1. **三个线程写的字段不重叠**:`_Reader` 只写 `capture.update`,主线程只写 `infer.update` / `loop.update`,`_Renderer` 只写 `render.update`。**字段级独占,没有写写冲突**。
2. **读发生在 `_Renderer` 调 `draw_hud()` 和 收尾 `snapshot()` 时**。HUD 读到的可能是"半新半旧"的值(比如 capture 已经更新到第 100 帧,render 才到第 80 帧),**这不是 bug,这是真实状态**。
3. **Python 的 GIL 保护字典/dataclass 的属性赋值原子性**,不会出现"读到一半"的破损浮点数。

所以 D8 全程不加任何 lock 在 Metrics 上 — **这是"按职责切线程"带来的免费红利**,跟决策一呼应。

## 5.5 设计点④: HUD 画面叠加 — 半透明面板 + REC 红点

`draw_hud(frame, metrics, *, n_dets, recording, show_info)` 在画面**左上角**叠一个半透明面板:

```
┌─────────────────────────┐
│ Capture  29.8 FPS       │  ← capture
│ Infer    63.2 FPS       │  ← infer
│ Render   34.1 FPS       │  ← render
│ Loop     29.5 FPS       │  ← loop (真实吞吐, 决定流畅度)
│ Current  31.2 FPS       │  ← current (瞬时, 反映抖动)
│ Objects  3              │  ← 当前帧检测数
└─────────────────────────┘
```

实现细节:

- **半透明** = 先在 `overlay` 副本上画实心黑矩形,再 `cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)` 跟原图混合 — 这是 OpenCV 实现半透明的标准做法(它原生不支持 alpha 通道叠加)。
- **左侧 4px 彩色装饰条** 一眼能看到这块区域是 HUD,不会跟画面内容混淆。
- **右上角 REC 红点** 只在 `recording=True` 时画(即 sink 在写盘),提示用户"正在录制" — 跟相机的 REC 灯设计一致。
- **`show_info=False`** 时整个 HUD 不画 — 给"演示用、画面要干净"的场景留出口。

## 5.6 完整代码:`apps/platform/src/odp_platform/inference/overlay.py`

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : overlay.py
# @Project   : ODPlatform
# @Function  : 画面信息面板(HUD) + 多维帧率采集 — 实时/顺序引擎共用
"""推理画面信息叠加 + 帧率指标.

提供:
  - FPSCounter : 滑动窗口 FPS, 带瞬时值 (当前画面帧率)
  - Metrics    : 一次推理的多维帧率 (捕获/推理/渲染/loop) + 模型 speed 分解, 可快照
  - draw_hud   : 在画面左上角画一个半透明信息面板 (开关 show_info 控制)
  - draw_pause : 暂停时的居中提示层

帧率口径 (写论文/快照都用得上):
  - capture(捕获) : 帧源读帧的速率
  - infer(推理)   : 模型推理速率, 取自 ultralytics result.speed (纯模型, 不含读帧/绘制)
  - render(渲染)  : 美化绘制 (BeautifyVisualizer.draw) 的速率
  - loop(端到端)  : 整个主循环一帧的速率 (批级测量, 均摊到帧 — 反映真实吞吐)
  - current(当前) : loop 的瞬时值 (最近一个样本)

★ loop 测量纪律 (在 pipeline.py 的主循环里兑现, 详见阶段 7.9):
  - 测量点: 每批派发完时算一次 (batch_end - last_batch_end) / batch_size
  - 这个值 update batch_size 次填窗口
  - 不在"批内 for 每一帧"测 —— 会得到几微秒的污染值
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


class FPSCounter:
    """滑动窗口 FPS (按每帧耗时 ms 估算), 同时保留最近一帧的瞬时值."""

    def __init__(self, window_size: int = 30) -> None:
        self._samples: deque[float] = deque(maxlen=window_size)
        self._last_ms: float = 0.0

    def update(self, ms: float) -> None:
        if ms > 0:
            self._samples.append(ms)
            self._last_ms = ms

    @property
    def fps(self) -> float:
        """滑动平均 FPS."""
        if not self._samples:
            return 0.0
        avg = sum(self._samples) / len(self._samples)
        return 1000.0 / avg if avg > 0 else 0.0

    @property
    def inst(self) -> float:
        """瞬时 FPS (最近一帧)."""
        return 1000.0 / self._last_ms if self._last_ms > 0 else 0.0


@dataclass
class Metrics:
    """一次推理的多维帧率 + 模型 speed 分解."""
    capture: FPSCounter = field(default_factory=FPSCounter)
    infer:   FPSCounter = field(default_factory=FPSCounter)
    render:  FPSCounter = field(default_factory=FPSCounter)
    loop:    FPSCounter = field(default_factory=FPSCounter)

    # ultralytics result.speed 累计 (ms), 用于平均出 preprocess/inference/postprocess
    _spp: float = 0.0
    _sinf: float = 0.0
    _spost: float = 0.0
    _sn: int = 0

    def add_speed(self, speed: dict | None) -> None:
        """喂入 ultralytics result.speed (单位 ms). 同时更新 infer 帧率."""
        if not speed:
            return
        self._spp += float(speed.get("preprocess", 0.0))
        self._sinf += float(speed.get("inference", 0.0))
        self._spost += float(speed.get("postprocess", 0.0))
        self._sn += 1
        if speed.get("inference"):
            self.infer.update(float(speed["inference"]))

    def speed_avg_ms(self) -> dict[str, float]:
        if not self._sn:
            return {}
        return {
            "preprocess":  round(self._spp / self._sn, 2),
            "inference":   round(self._sinf / self._sn, 2),
            "postprocess": round(self._spost / self._sn, 2),
        }

    def snapshot(self) -> dict[str, Any]:
        """给日志 / audit 快照用的纯数据 (论文里可直接引用)."""
        return {
            "capture_fps": round(self.capture.fps, 1),
            "infer_fps":   round(self.infer.fps, 1),
            "render_fps":  round(self.render.fps, 1),
            "loop_fps":    round(self.loop.fps, 1),
            "current_fps": round(self.loop.inst, 1),
            "speed_ms":    self.speed_avg_ms(),
        }


# ============================================================================
# 画面叠加
# ============================================================================
# 颜色统一 BGR
_C_LABEL = (200, 200, 200)
_C_CAPTURE = (0, 200, 255)     # 橙黄
_C_INFER = (0, 230, 0)         # 绿
_C_RENDER = (255, 120, 220)    # 粉紫
_C_LOOP = (255, 200, 0)        # 青蓝
_C_CURRENT = (255, 255, 255)   # 白
_C_OBJ = (120, 220, 255)


def draw_hud(
    frame,
    metrics: Metrics,
    *,
    n_dets: int = 0,
    recording: bool = False,
    show_info: bool = True,
) -> None:
    """左上角半透明信息面板. show_info=False 则不画.

    直接在传入的 frame (已是绘制后的副本) 上原地叠加.
    """
    import cv2

    if not show_info:
        return

    rows = [
        ("Capture", f"{metrics.capture.fps:5.1f} FPS", _C_CAPTURE),
        ("Infer",   f"{metrics.infer.fps:5.1f} FPS", _C_INFER),
        ("Render",  f"{metrics.render.fps:5.1f} FPS", _C_RENDER),
        ("Loop",    f"{metrics.loop.fps:5.1f} FPS", _C_LOOP),
        ("Current", f"{metrics.loop.inst:5.1f} FPS", _C_CURRENT),
        ("Objects", f"{n_dets}", _C_OBJ),
    ]

    font = cv2.FONT_HERSHEY_SIMPLEX
    fs, th, lh = 0.5, 1, 22
    pad = 10
    label_w = 84
    panel_w = 230
    panel_h = pad * 2 + lh * len(rows)
    x0, y0 = 12, 12

    # 半透明深色面板
    overlay = frame.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + panel_w, y0 + panel_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
    # 左侧彩色装饰条
    cv2.rectangle(frame, (x0, y0), (x0 + 4, y0 + panel_h), (0, 200, 255), -1)

    y = y0 + pad + 14
    for label, value, color in rows:
        cv2.putText(frame, label, (x0 + pad + 6, y), font, fs, _C_LABEL, th, cv2.LINE_AA)
        cv2.putText(frame, value, (x0 + pad + label_w, y), font, fs, color, th, cv2.LINE_AA)
        y += lh

    # 录制指示 (右上角红点 + REC)
    if recording:
        h, w = frame.shape[:2]
        cv2.circle(frame, (w - 70, 24), 7, (0, 0, 255), -1)
        cv2.putText(frame, "REC", (w - 56, 30), font, 0.6, (0, 0, 255), 2, cv2.LINE_AA)


def draw_pause(frame) -> None:
    """暂停: 暗化全屏 + 居中 PAUSED + 提示."""
    import cv2
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], frame.shape[0]), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

    h, w = frame.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    text, fscale, fth = "PAUSED", 1.8, 3
    (tw, tht), _ = cv2.getTextSize(text, font, fscale, fth)
    cx, cy = (w - tw) // 2, (h + tht) // 2
    cv2.putText(frame, text, (cx, cy), font, fscale, (255, 255, 255), fth, cv2.LINE_AA)

    hint = "Press SPACE to resume  |  Q / Esc to quit"
    (hw, _), _ = cv2.getTextSize(hint, font, 0.6, 1)
    cv2.putText(frame, hint, ((w - hw) // 2, cy + 44), font, 0.6, (210, 210, 210), 1, cv2.LINE_AA)
```

## 5.7 单测验证

不需要画面, 跑下 FPSCounter 和 Metrics 的纯逻辑:

```python
# /tmp/test_overlay.py
from odp_platform.inference.overlay import FPSCounter, Metrics

# --- FPSCounter ---
fps = FPSCounter(window_size=5)
for ms in [10, 12, 11, 9, 10]:
    fps.update(ms)
assert abs(fps.fps - 95.2) < 1.0, f"{fps.fps}"   # 1000/10.4 ≈ 96
assert abs(fps.inst - 100.0) < 1.0                 # 最近一个是 10ms → 100 FPS
print(f"✅ FPSCounter: fps={fps.fps:.1f}, inst={fps.inst:.1f}")

# --- Metrics ---
m = Metrics()
m.capture.update(33.3)        # 30 FPS
m.add_speed({"preprocess": 1.5, "inference": 8.0, "postprocess": 2.0})
m.add_speed({"preprocess": 1.6, "inference": 8.5, "postprocess": 2.1})
m.render.update(28.0)
m.loop.update(50.0)           # 20 FPS

snap = m.snapshot()
print(f"✅ Metrics snapshot: {snap}")
assert snap["capture_fps"] > 25
assert snap["infer_fps"] > 100      # 1000/8.25 ≈ 121
assert snap["loop_fps"] > 15
print(f"✅ speed_avg: {m.speed_avg_ms()}")
```

跑:

```bash
$ python /tmp/test_overlay.py
✅ FPSCounter: fps=95.2, inst=100.0
✅ Metrics snapshot: {'capture_fps': 30.0, 'infer_fps': 121.2, 'render_fps': 35.7, 'loop_fps': 20.0, 'current_fps': 20.0, 'speed_ms': {'preprocess': 1.55, 'inference': 8.25, 'postprocess': 2.05}}
✅ speed_avg: {'preprocess': 1.55, 'inference': 8.25, 'postprocess': 2.05}
```

`draw_hud` / `draw_pause` 是画面 API,真要测就在朴素脚本里调一下,目测 HUD 是不是预期的样子。这里不写自动化测试(画面单测要 image diff,过度工程化)。

## 5.8 git commit

```bash
git add apps/platform/src/odp_platform/inference/overlay.py
git commit -m "feat(D8): inference 子系统 overlay.py — 5 维 FPS 测量 + 画面 HUD

- FPSCounter: 滑动窗口 (30 帧) + 瞬时双口径
- Metrics: 4 路 FPSCounter (capture/infer/render/loop) + ultralytics speed 分解
- draw_hud: 左上角半透明面板 + 右上角 REC 红点
- draw_pause: 居中 PAUSED 提示层
- 线程共享 Metrics 无锁 (字段级独占, GIL 保护原子性, 是 '按职责切' 的红利)
- loop FPS 的批级测量纪律见 pipeline.py 主循环"
```

至此 **配置 + 测量** 两层完成。两个文件都是**独立小模块**:不依赖 pipeline/service,可以单独 import 用,后面 pipeline 和 service 会一起用它们。

下一阶段开始进入 D8 的**新核心** — **接缝模块**。这是让"同一套引擎服务 CLI / 桌面 / Web" 成为可能的关键设计。

---
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 6: 接缝模块 — `sinks.py` + `hooks.py` + `cancel.py`

> 这一章是 D8 的**架构主轴**。配置 / 测量 / 流水线 / Service 都是"传统多线程推理"也会有的东西,但**这三个文件是 D8 区别于老式 yolo_server 的关键**。
>
> 三个接缝让我们交付的 `apps/platform/.../inference/` 是**一个干净的推理引擎包**,既能被 CLI 直接调,也能被桌面端 / Web 后端 / Celery 任务 0 改动地复用。

## 6.0 为什么单立一章

回想阶段 3.4 决策四:**业务方需要定制三个维度,我们用三个抽象接缝盖住**。

| 维度 | 接缝文件 | 抽象 | 默认实现 |
|---|---|---|---|
| 输出去哪儿 | `sinks.py` | `OutputSink` ABC | `LocalFileSink` (本地 mp4/jpg)、`NullSink` (no-op) |
| 进度/事件 | `hooks.py` | `InferHooks` dataclass | 全 `None` 回调 (零开销) |
| 谁来叫停 | `cancel.py` | `CancelToken` | (调用方自己 new, 不传则 `None` = 永不取消) |

**为什么这三个一起讲, 不分散到 pipeline / service 章节里去?** 因为:

1. **它们三个共同构成"接缝层"**, 概念一脉相承 — 一起讲学生更容易理解 "为什么不分别塞在用到的地方"。
2. **它们几乎 0 依赖** (只依赖 `frame_source.SourceType` 一个枚举), 可以**独立测试 + 独立 commit**。
3. **它们要在 pipeline / service 之前讲**, 因为后两章会大量用到这三个的类型注解。

## 6.1 `sinks.py` — 输出去哪儿

### 6.1.1 抽象基类的"小骨架": open / write / close

`OutputSink` 是 Python 标准的 `abc.ABC`, 三个抽象方法构成完整生命周期:

```python
class OutputSink(ABC):
    @abstractmethod
    def open(self, output_dir: Path, source_type: SourceType) -> None:
        """初始化. 由 pipeline 在首批帧到达后调 (此时 source_type 已知)."""

    @abstractmethod
    def write(self, frame, annotated: np.ndarray) -> None:
        """写一帧画好的图. 在 _Renderer 线程里被调."""

    @abstractmethod
    def close(self) -> None:
        """收尾. 由 pipeline 在退出时调. 必须幂等."""
```

**三个方法的关键纪律**:

- **`open` 推迟到首批帧**: pipeline 拿到第一帧才知道源是视频还是图片(`reader.source_type`),sink 需要这个信息决定写 mp4 还是写 jpg。所以 `__init__` 时只准备字段,真初始化在 `open` 里。
- **`write` 永不抛**: 单帧写入失败 `logger.warning` + 跳过,不影响后续帧。这是纪律 A "永不抛"在 sink 层的兑现。
- **`close` 幂等**: 允许多次调用不出错(VideoWriter release 完置 None,再 release 不炸)。pipeline 在 finally 块里调 close,任何路径都要走到,幂等才安全。

### 6.1.2 内置实现 `LocalFileSink` — 等价老式 `cv2.imwrite` / `VideoWriter`

CLI 默认行为就是"画好的图写本地",这是最常用的场景。`LocalFileSink` 完整实现:

- **视频/摄像头源**: 写一个 `output.mp4`,lazy 打开 VideoWriter(首帧拿到尺寸后才知道 width/height)
- **图片源**: 每帧写一张 jpg,文件名复用源文件名

**关键细节**:

- **fps 取自 frame.info.fps**: 摄像头协商出的 fps(比如 90) — 这跟"实际消费 fps"(可能 60)可能不一致。但 mp4 header 写 90 在大部分播放器里也能正常播,只是时长会偏短。如果你需要严格的时间轴对齐,改成消费端实测 fps,这是已知工程遗留(详见阶段 12.7)。
- **图片 sink 用 `Path(fname).stem`**: 保留原文件名 stem,后缀强制 `.jpg`。这样 `cat.png` 出来 `cat.jpg`,容易跟原图对照。

### 6.1.3 内置实现 `NullSink` — 啥也不干

什么场景用 `NullSink`?

- **CLI 的 `--no-save` 模式**: 用户只想看画面不想存盘
- **桌面 demo**: annotated 帧通过 QtSignalSink 给 UI 了,本地不需要副本
- **Web 流推**: annotated 帧已经通过 WebSocketSink 推走了
- **性能基准**: 排除 IO 干扰,只测推理速度

实现 4 行:

```python
class NullSink(OutputSink):
    def open(self, output_dir, source_type): pass
    def write(self, frame, annotated):       pass
    def close(self):                          pass
```

**为什么不让 sink=None 等价 NullSink, 非要专门一个类?** 因为 pipeline 内部用 `sink.write(...)` 的代码路径只有一条。如果 `sink=None` 要兼容,每次都得 `if sink: sink.write(...)`,**4 个地方写 if 不仅丑还容易漏写一处导致 bug**。`NullSink` 是个**有方法但什么也不做的对象**,pipeline 调用方完全统一,`if sink` 这种分支零出现 — 这就是空对象模式(Null Object Pattern)。

### 6.1.4 完整代码:`apps/platform/src/odp_platform/inference/sinks.py`

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : sinks.py
# @Project   : ODPlatform
# @Function  : 推理结果输出适配器 (OutputSink 抽象 + LocalFileSink + NullSink)
"""推理结果输出适配器.

把"画好的 annotated 帧"送到不同目的地的抽象层:

  - OutputSink     : 抽象基类 (open/write/close 三个方法)
  - LocalFileSink  : 本地 mp4 / jpg (★ CLI 默认行为, 等价于老式 cv2.imwrite/VideoWriter)
  - NullSink       : 不写任何东西 (web 流推 / 只跑统计 / 不存盘 时用)

业务端在自己仓库继承 OutputSink 实现自定义 sink:
  - S3Sink         : 写对象存储
  - WebSocketSink  : 实时推流
  - QtSignalSink   : 桥接到 Qt 信号 (本仓库 apps/desktop 里有实现, 见阶段 11)

实现纪律 (与 D8 InferService 的"永不抛"一脉相承):
  - write() 内部 try/except 包住, 单帧写入失败 logger.warning + 跳过, 不抛
  - close() 幂等 (允许多次调用)
  - open() 由 pipeline 在首批帧到达后调用 (此时 source_type 已知)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

from odp_platform.frame_source import SourceType

logger = logging.getLogger(__name__)


# ============================================================================
# 抽象基类
# ============================================================================
class OutputSink(ABC):
    """推理结果输出适配器.

    生命周期: open() → write() × N → close().

    实现要求:
      - write 永不抛 (出错 logger.warning + 跳过这一帧)
      - close 幂等 (多次调不出错)
      - 线程亲缘: write 在 _Renderer 线程被调, open/close 在主线程
    """

    @abstractmethod
    def open(self, output_dir: Path, source_type: SourceType) -> None:
        """初始化. 由 ThreadedPipeline 在首批帧到达后调用.

        Args:
            output_dir:  推理输出根目录 (部分 sink 可能不用)
            source_type: 帧源类型 (决定按视频流还是单图处理)
        """

    @abstractmethod
    def write(self, frame, annotated: np.ndarray) -> None:
        """写一帧画好的图.

        Args:
            frame:     frame_source 给出的 Frame 对象 (含 image / info 元数据)
            annotated: 已画过框的 BGR 图像
        """

    @abstractmethod
    def close(self) -> None:
        """收尾. 由 ThreadedPipeline 在退出时调用. 必须幂等."""


# ============================================================================
# 内置实现 1: LocalFileSink (CLI 默认, 视频写 mp4 / 图片写 jpg)
# ============================================================================
class LocalFileSink(OutputSink):
    """本地文件 sink — 视频源写 mp4, 图片源写 jpg.

    实现细节:
      - 视频源 (VIDEO / CAMERA): lazy 打开 cv2.VideoWriter, 首帧拿到尺寸再建
      - 图片源 (IMAGE / IMAGES): 每帧 cv2.imwrite 一张 jpg
      - fps 从 frame.info.fps 拿; 摄像头/缺失时兜底 30
    """

    def __init__(self) -> None:
        self.output_dir: Path | None = None
        self._is_stream: bool = False
        self._video = None      # cv2.VideoWriter, lazy
        self._count: int = 0

    def open(self, output_dir: Path, source_type: SourceType) -> None:
        self.output_dir = output_dir
        self._is_stream = source_type in (SourceType.VIDEO, SourceType.CAMERA)

    def write(self, frame, annotated) -> None:
        import cv2
        try:
            if self._is_stream:
                if self._video is None:
                    h, w = annotated.shape[:2]
                    fps = float(frame.info.fps) if getattr(frame.info, "fps", None) else 30.0
                    out = self.output_dir / "output.mp4"
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    self._video = cv2.VideoWriter(str(out), fourcc, fps, (w, h))
                self._video.write(annotated)
            else:
                fname = frame.info.filename or f"frame_{frame.info.frame_index:06d}"
                cv2.imwrite(str(self.output_dir / f"{Path(fname).stem}.jpg"), annotated)
            self._count += 1
        except Exception as e:
            logger.warning(f"LocalFileSink.write 失败, 跳过: {e}")

    def close(self) -> None:
        if self._video is not None:
            try:
                self._video.release()
            except Exception as e:
                logger.warning(f"LocalFileSink.close release 失败 (已吞): {e}")
            finally:
                self._video = None


# ============================================================================
# 内置实现 2: NullSink (不写任何东西)
# ============================================================================
class NullSink(OutputSink):
    """什么也不写.

    用途:
      - web 流推: annotated 已通过 WebSocketSink 推走, 后端无需落盘
      - desktop: annotated 已通过 QtSignalSink 给 UI, 不需要本地文件
      - 性能基准测试: 排除 IO 干扰
      - --no-save 模式下的 CLI
    """

    def open(self, output_dir: Path, source_type: SourceType) -> None:
        pass

    def write(self, frame, annotated) -> None:
        pass

    def close(self) -> None:
        pass
```

## 6.2 `hooks.py` — 生命周期回调

### 6.2.1 4 个时机, 4 个回调

```python
@dataclass
class InferHooks:
    on_frame:    Callable[[FrameEvent],    None] | None = None   # 每帧
    on_progress: Callable[[ProgressEvent], None] | None = None   # 每 N 帧
    on_complete: Callable[[InferResult],   None] | None = None   # 收尾 (1 次)
    on_error:    Callable[[Exception],     None] | None = None   # 异常 (0 或 1 次)
    progress_interval_frames: int = 30                            # on_progress 频率
```

为什么 4 个时机选这 4 个?

| 时机 | 频率 | 典型用途 |
|---|---|---|
| `on_frame` | 每帧 (高频) | 桌面端推画面到 QLabel、Web 端推帧到 WS |
| `on_progress` | 每 N 帧 (低频) | 进度条更新、Redis 写 task progress |
| `on_complete` | 1 次 | 触发"下载结果"按钮、邮件通知 |
| `on_error` | 0 或 1 次 | 弹错误对话框、Sentry 上报 |

**为什么 `on_frame` 和 `on_progress` 都要?** 因为频率不同。`on_frame` 每帧调,适合"实时画面推送"这种必须高频的场景;`on_progress` 每 N 帧调(默认 30,约 1 秒一次),适合"GUI 进度条 / 远程 task 状态"这种没必要高频(高频反而浪费)的场景。

**为什么 `on_complete` 跟 `on_progress` 分开?** 因为语义不同。`on_progress` 是"我跑到第 N 帧了",每次都触发,业务方可能要去重;`on_complete` 是"我整个跑完了,这是最终 InferResult",只触发一次,业务方拿到这个就能做收尾(关数据库连接、发邮件、清缓存)。

### 6.2.2 ★ 核心纪律: 业务回调抛异常一定要吞

这是 hooks 模块**最关键的一条纪律**。业务方写的回调函数可能有 bug:

```python
hooks = InferHooks(on_progress=lambda e: db.write(e.frame_idx))  # db 可能断
```

`db.write` 可能因为网络问题抛 `ConnectionError`。如果让这个异常冒到 pipeline,**整个推理就死了** — 但实际上"数据库连不上"跟"推理"完全无关,不该让前者杀死后者。

所以所有 `fire_*` 方法**强制 try/except**:

```python
def fire_progress(self, evt: ProgressEvent) -> None:
    if self.on_progress is not None:
        try:
            self.on_progress(evt)
        except Exception as e:
            logger.warning(f"on_progress 回调异常 (已吞): {e}")
```

**纪律 A "永不抛" 在 hooks 层的兑现**:

| 层 | 兑现位 |
|---|---|
| service | 顶层 try/except, 异常打包成 InferResult.error |
| pipeline | 每个 _Reader / _Renderer / _Display run 都 try 包裹 |
| sink | write 内部 try, 失败 warning + 跳过 |
| **hooks** | **fire_* 内部 try, 业务回调异常吞掉 + warning** |

四层兜底,**任何业务方的 bug 都不能炸掉推理**。这是 D8 跟"老式 yolo 部署脚本"最显著的健壮性差异。

### 6.2.3 事件数据 dataclass: `FrameEvent` 和 `ProgressEvent`

```python
@dataclass
class FrameEvent:
    frame_idx: int                      # 帧序号 (从 0 开始)
    image: np.ndarray                   # 原始 BGR 图像
    annotated: np.ndarray               # 画完框的 BGR 图像
    n_detections: int                   # 当前帧检测数
    detections: list | None = None      # 可选: list[dict]{label, conf, xyxy}
```

**关键细节**:

- **`image` 和 `annotated` 是 ndarray 视图**: 不 copy。业务方如果要异步处理(比如塞 queue), **必须自己 `.copy()`** — 否则 pipeline 后续会拿这个 ndarray 加 HUD,业务拿到的就是带 HUD 的脏数据。这条在 docstring 里明说。
- **`detections` 默认 None**: 默认不打包 `boxes.xyxy.cpu().numpy()` 这些 GPU → CPU 拷贝(可能拖性能)。业务方真要这些数据,自己在 on_frame 里 `result.boxes.xyxy.cpu().numpy()` 拿。

```python
@dataclass
class ProgressEvent:
    frame_idx: int                      # 当前帧序号 (累计)
    total_frames: int | None            # 总帧数 (视频源知道, 摄像头/RTSP 为 None)
    elapsed_sec: float                  # 已运行秒数
    fps_loop: float                     # 端到端 FPS
    fps_infer: float                    # 推理 FPS
    detections_total: int               # 累计检测数
```

`total_frames` 是 `Optional[int]` — **摄像头 / RTSP 永远不知道总长度**,只有视频文件知道。GUI 进度条要处理 `total_frames is None` 的情况(显示"不确定模式" — `QProgressBar.setRange(0, 0)`)。

### 6.2.4 完整代码:`apps/platform/src/odp_platform/inference/hooks.py`

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : hooks.py
# @Project   : ODPlatform
# @Function  : 推理生命周期钩子 (InferHooks + FrameEvent + ProgressEvent)
"""推理生命周期回调.

InferService / ThreadedPipeline 在 4 个时机触发回调:
  on_frame    : 每帧推理 + 绘制完成 (高频, 适合实时画面推送)
  on_progress : 每 N 帧 (低频, 适合进度条 / 状态更新)
  on_complete : 推理收尾 (1 次, 拿到完整 InferResult)
  on_error    : 异常发生 (0 或 1 次, 拿到 Exception)

设计纪律:
  - 所有 fire_xxx 用 try/except 包住, 业务回调抛异常【不】让 pipeline 死
  - 回调里【不要】做阻塞操作 (网络/db), 应塞到队列异步处理
  - on_frame 在 renderer 线程触发, 其它回调在主线程或 service 线程触发

CLI 默认不传 hooks → 全空回调 → 行为跟改造前 100% 一致.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FrameEvent:
    """每帧推理完后的事件数据.

    image / annotated 都是 ndarray 视图, 业务方如果要异步处理需要先 .copy().
    detections 是从 ultralytics result.boxes 提取的字段字典列表 (可序列化).
    """
    frame_idx: int                      # 帧序号 (从 0 开始)
    image: np.ndarray                   # 原始 BGR 图像
    annotated: np.ndarray               # 画完框的 BGR 图像
    n_detections: int                   # 当前帧检测数
    detections: list = None             # list[dict] {label, conf, xyxy}, 可选


@dataclass
class ProgressEvent:
    """周期性进度事件 (每 progress_interval_frames 帧触发)."""
    frame_idx: int                      # 当前帧序号 (累计)
    total_frames: Optional[int]         # 总帧数 (视频源知道, 摄像头/RTSP 为 None)
    elapsed_sec: float                  # 已运行秒数
    fps_loop: float                     # 端到端 FPS
    fps_infer: float                    # 推理 FPS
    detections_total: int               # 累计检测数


@dataclass
class InferHooks:
    """所有回调钩子. None 表示空回调.

    CLI 默认行为: InferHooks() 全部 None → 触发时全 short-circuit, 零开销.
    """
    on_frame:    Optional[Callable[[FrameEvent],    None]] = None
    on_progress: Optional[Callable[[ProgressEvent], None]] = None
    on_complete: Optional[Callable[[Any],           None]] = None   # InferResult → None
    on_error:    Optional[Callable[[Exception],     None]] = None

    progress_interval_frames: int = 30      # 每 N 帧触发一次 on_progress

    # ------------------------------------------------------------------
    # 触发 helper —— 全部 try/except 包住, 业务回调抛异常不能炸 pipeline
    # ------------------------------------------------------------------
    def fire_frame(self, evt: FrameEvent) -> None:
        if self.on_frame is not None:
            try:
                self.on_frame(evt)
            except Exception as e:
                logger.warning(f"on_frame 回调异常 (已吞): {e}")

    def fire_progress(self, evt: ProgressEvent) -> None:
        if self.on_progress is not None:
            try:
                self.on_progress(evt)
            except Exception as e:
                logger.warning(f"on_progress 回调异常 (已吞): {e}")

    def fire_complete(self, result: Any) -> None:
        if self.on_complete is not None:
            try:
                self.on_complete(result)
            except Exception as e:
                logger.warning(f"on_complete 回调异常 (已吞): {e}")

    def fire_error(self, exc: Exception) -> None:
        if self.on_error is not None:
            try:
                self.on_error(exc)
            except Exception as e:
                logger.warning(f"on_error 回调异常 (已吞): {e}")
```

## 6.3 `cancel.py` — 程序化取消

### 6.3.1 为什么不复用 `threading.Event` 自己

理论上, `CancelToken` 是 `threading.Event` 的一层薄包装 — 接口几乎一样(`set` → `cancel`,`is_set` → `is_cancelled`)。为什么不直接让调用方传 `Event`?

3 个理由:

1. **语义命名更清楚**。`event.set()` 在协作场景里语义模糊(set 什么?表达什么?),`token.cancel()` 一看就懂。
2. **类型注解更精确**。函数签名 `cancel_token: CancelToken | None` 比 `cancel_event: Event | None` 信息量大。
3. **未来可扩展**。如果以后要加"理由"字段(`token.cancel(reason="user clicked stop")`),`Event` 没法直接扩,自己的类随时加。

### 6.3.2 4 个 pipeline 主循环查询点保证 < 2s 响应

`CancelToken.cancel()` 是个 setter, 不会主动通知 pipeline。pipeline 必须主动查 `token.is_cancelled()` 才能响应。

`ThreadedPipeline.run()` 主循环里 **4 个查询点**:

```python
while True:
    # ★ 查询点 1: 暂停状态下也要能取消
    if controller.is_paused():
        if self._is_cancelled(): break
        ...continue

    # ★ 查询点 2: 取批前查 (主循环最常走的路径)
    if self._is_cancelled(): break

    first = reader.get(timeout=2.0)    # ← 最慢的一处, 2 秒
    ...
    images = [f.image for f in batch]
    results = self.proc.infer_batch(images)
    ...

    # ★ 查询点 3: 派发完查 (避免立刻又走到 reader.get 2 秒)
    if self._is_cancelled(): break

    # ★ 查询点 4: 读键 (CLI 的 q/Esc 走这一条)
    if self._handle_key(...): break
```

**为什么是 4 个不是更多?** 每个查询都有开销(虽然小),太多查询拖性能。这 4 个位置覆盖了:

- 暂停态(查询点 1)
- 正常态(查询点 2、3、4 三处保险)

**最差响应时间 = `reader.get(timeout=2.0)` = 2 秒**。这就是 D8 承诺的"< 2 秒响应取消"的依据。

### 6.3.3 `InferenceCancelled` 异常 — 留给未来用

```python
class InferenceCancelled(Exception):
    """推理被主动取消."""
    pass
```

定义了但 pipeline / service **目前不抛它**(走优雅退出更合适)。留个类给业务方在需要明确区分"用户取消" vs "真错误"时用:

```python
result = service.predict(..., cancel_token=token)
if result.error and "cancel" in result.error.lower():
    # 用户取消, 不算失败
    show("已取消")
elif not result.success:
    # 真错误
    show_error(result.error)
```

将来如果需要区分得更明确(比如返回 `InferResult.cancelled: bool`),这是个**预留扩展点**。

### 6.3.4 完整代码:`apps/platform/src/odp_platform/inference/cancel.py`

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : cancel.py
# @Project   : ODPlatform
# @Function  : 线程安全的取消信号 (CancelToken)
"""推理取消信号.

GUI 端 / web 端 没有键盘按键, 需要程序化告诉 pipeline "该停了".
ThreadedPipeline 在主循环 4 个检查点查询 is_cancelled(), 收到信号优雅退出.

使用模式:
    token = CancelToken()

    # 在后台启动推理
    threading.Thread(target=lambda: service.predict(..., cancel_token=token)).start()

    # 用户点取消按钮 / WebSocket 断开 / Celery task revoke
    token.cancel()

    # pipeline 在下次主循环查询点检测到 (< 2s), 退出主循环
"""
from __future__ import annotations

import threading


class CancelToken:
    """线程安全的取消信号.

    调用方持有, pipeline 周期性查询. 永远只查不阻塞 (除非显式 wait).
    """

    def __init__(self) -> None:
        self._evt = threading.Event()

    def cancel(self) -> None:
        """请求取消. 幂等 (多次调无副作用)."""
        self._evt.set()

    def is_cancelled(self) -> bool:
        """非阻塞查询. pipeline 主循环每个检查点调一次."""
        return self._evt.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        """阻塞等待 cancel 信号. 给"等推理结束 + 超时强终止"的场景."""
        return self._evt.wait(timeout)


class InferenceCancelled(Exception):
    """推理被主动取消. 不一定真用 (pipeline 走优雅退出更常见),
    留个类型给业务方在需要明确区分"用户取消"和"真错误"时用."""
    pass
```

## 6.4 测试:接缝模块的合约验证

接缝模块是后续 pipeline / service 的基础, **必须先把它们测试好**, 否则上层 bug 会很难定位。

```python
# /tmp/test_seams.py
"""验证 3 个接缝模块的关键合约."""
import logging
logging.basicConfig(level=logging.INFO)

import threading, time
import numpy as np
from pathlib import Path

# ============================================================
# 1. CancelToken: 基础 + 跨线程
# ============================================================
from odp_platform.inference import CancelToken

t = CancelToken()
assert not t.is_cancelled()
t.cancel()
assert t.is_cancelled()
t.cancel(); t.cancel()       # 幂等, 不炸
print("✅ CancelToken 基础 + 幂等")

# 跨线程: 一个线程 cancel, 另一个立即看到
t2 = CancelToken()
seen = threading.Event()
def watcher():
    for _ in range(100):
        if t2.is_cancelled():
            seen.set(); return
        time.sleep(0.005)
threading.Thread(target=watcher).start()
time.sleep(0.05); t2.cancel()
assert seen.wait(0.5)
print("✅ CancelToken 跨线程可见")

# ============================================================
# 2. InferHooks: 默认空 + 业务回调被调 + ★ 业务异常被吞
# ============================================================
from odp_platform.inference import InferHooks, FrameEvent, ProgressEvent

h = InferHooks()
assert h.on_frame is None and h.progress_interval_frames == 30
fe = FrameEvent(0, np.zeros((1,1,3),dtype=np.uint8),
                np.zeros((1,1,3),dtype=np.uint8), 0)
pe = ProgressEvent(10, 100, 1.0, 30.0, 60.0, 5)
# 空 hooks: 全 short-circuit
h.fire_frame(fe); h.fire_progress(pe); h.fire_complete("R"); h.fire_error(RuntimeError())
print("✅ InferHooks 空回调 short-circuit")

# 业务回调被调
calls = []
h2 = InferHooks(
    on_frame=lambda e: calls.append(("frame", e.frame_idx)),
    on_complete=lambda r: calls.append(("done", r)),
)
h2.fire_frame(fe); h2.fire_complete("OK")
assert calls == [("frame", 0), ("done", "OK")]
print("✅ InferHooks 业务回调被调")

# ★ 业务 hook 抛异常被吞 (核心纪律)
def bad(*a, **kw): raise RuntimeError("user code bug")
h3 = InferHooks(on_frame=bad, on_progress=bad, on_complete=bad, on_error=bad)
try:
    h3.fire_frame(fe); h3.fire_progress(pe); h3.fire_complete("x"); h3.fire_error(Exception())
    print("✅ InferHooks ★ 业务 hook 异常被吞 (核心纪律)")
except Exception as e:
    print(f"❌ FAIL: 业务 hook 异常应被吞但泄露了: {e}")

# ============================================================
# 3. OutputSink: ABC + LocalFileSink + NullSink
# ============================================================
from odp_platform.inference import OutputSink, LocalFileSink, NullSink
from odp_platform.frame_source import SourceType
from unittest.mock import MagicMock

# ABC 不能直接实例化
try:
    OutputSink()
    print("❌ FAIL: OutputSink ABC 居然能直接实例化")
except TypeError:
    print("✅ OutputSink ABC 拒绝直接实例化")

# NullSink: open/write/close 都不出错, 不写文件
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    sink = NullSink()
    sink.open(Path(tmp), SourceType.VIDEO)
    for _ in range(5):
        sink.write(MagicMock(), np.zeros((10,10,3),dtype=np.uint8))
    sink.close(); sink.close()    # 幂等
    assert list(Path(tmp).iterdir()) == []
    print("✅ NullSink no-op + 幂等")

# LocalFileSink: 图片源写 jpg
with tempfile.TemporaryDirectory() as tmp:
    sink = LocalFileSink()
    sink.open(Path(tmp), SourceType.IMAGES)
    for i in range(3):
        frame = MagicMock(); frame.info.filename = f"test_{i}.png"
        sink.write(frame, np.full((50,50,3), 128, dtype=np.uint8))
    sink.close()
    jpgs = sorted(Path(tmp).glob("*.jpg"))
    assert len(jpgs) == 3 and jpgs[0].name == "test_0.jpg"
    print("✅ LocalFileSink 图片源 → 3 张 jpg")

# LocalFileSink: 视频源写 mp4
with tempfile.TemporaryDirectory() as tmp:
    sink = LocalFileSink()
    sink.open(Path(tmp), SourceType.VIDEO)
    for i in range(8):
        frame = MagicMock(); frame.info.fps = 30.0; frame.info.frame_index = i
        sink.write(frame, np.full((100,200,3), i*30, dtype=np.uint8))
    sink.close()
    assert (Path(tmp) / "output.mp4").exists()
    print("✅ LocalFileSink 视频源 → output.mp4")

print("\n========== 接缝模块全部通过 ==========")
```

跑一下:

```bash
$ python /tmp/test_seams.py
✅ CancelToken 基础 + 幂等
✅ CancelToken 跨线程可见
✅ InferHooks 空回调 short-circuit
✅ InferHooks 业务回调被调
WARNING:odp_platform.inference.hooks:on_frame 回调异常 (已吞): user code bug
WARNING:odp_platform.inference.hooks:on_progress 回调异常 (已吞): user code bug
WARNING:odp_platform.inference.hooks:on_complete 回调异常 (已吞): user code bug
WARNING:odp_platform.inference.hooks:on_error 回调异常 (已吞): user code bug
✅ InferHooks ★ 业务 hook 异常被吞 (核心纪律)
✅ OutputSink ABC 拒绝直接实例化
✅ NullSink no-op + 幂等
✅ LocalFileSink 图片源 → 3 张 jpg
✅ LocalFileSink 视频源 → output.mp4

========== 接缝模块全部通过 ==========
```

**所有合约一次通过**。注意中间 4 条 `WARNING` —— 这正是"业务 hook 抛异常被 fire_* 用 logger.warning 吞掉"的证据,**它们是设计目标,不是 bug**。

## 6.5 git commit

```bash
git add apps/platform/src/odp_platform/inference/sinks.py
git add apps/platform/src/odp_platform/inference/hooks.py
git add apps/platform/src/odp_platform/inference/cancel.py
git commit -m "feat(D8): inference 接缝层 — sinks/hooks/cancel 三个抽象

这是 D8 区别于'老式 yolo_server'的关键设计 — 让同一套引擎能服务
CLI / 桌面 / Web / Celery, 但推理子系统不依赖任何前端框架.

sinks.py:
- OutputSink ABC (open/write/close)
- LocalFileSink (CLI 默认, 视频写 mp4 / 图片写 jpg)
- NullSink (no-op, 给 --no-save 和流推场景)

hooks.py:
- InferHooks dataclass (4 个回调: frame/progress/complete/error)
- ★ fire_* 全部 try/except 吞业务回调异常 (永不抛在 hooks 层的兑现)
- FrameEvent / ProgressEvent 数据载体

cancel.py:
- CancelToken (threading.Event 的语义化包装)
- InferenceCancelled 异常类 (留给未来需要时用)

接缝纪律 (grep 守门):
  grep -rE 'import PyQt|import PySide|fastapi|celery' inference/
  → 必须 0 输出"
```

至此 **接缝层 3 个文件完成**。这一层是后面 pipeline / service 的基础, 它们都会接受接缝作为参数, 让业务方"插进来"。

下一阶段开始进入 D8 的**核心** — 多线程流水线 `pipeline.py`。

---
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 7: `pipeline.py` — 四级多线程流水线 (核心)

终于到核心模块。**这一阶段最长** — 486 行代码,把阶段 3 设计的"四级流水线 + 接缝隔离"完整实现出来,处理好缓冲策略、暂停、退出、取消、错误传播、loop FPS 批级测量。

## 7.1 模块顶部 — 哨兵 + 两个 put helper

```python
_SENTINEL = object()


def _put_latest(q: Queue, item) -> None:
    """满则丢最旧再放 (latest-wins, 低延迟)."""
    try:
        q.put_nowait(item)
    except Full:
        try:
            q.get_nowait()
        except Empty:
            pass
        try:
            q.put_nowait(item)
        except Full:
            pass


def _put_block(q: Queue, item) -> None:
    """满则阻塞 (不丢, 存盘完整)."""
    while True:
        try:
            q.put(item, timeout=1.0)
            return
        except Full:
            continue
```

**两个 helper 对应两种相反的取舍**:

- **`_put_latest`(丢旧只留最新)**: 用于"低延迟优先"场景 —— 摄像头 reader 队列(只关心最新的帧)、纯显示队列(看新画面就行,丢就丢)
- **`_put_block`(满则等)**: 用于"完整性优先"场景 —— 视频源 reader(每帧都重要)、save=True 的派发队列(存盘要完整)

策略选择不是写死,而是**每个队列在创建时根据用途选**。后面看 `ThreadedPipeline.run()` 时这一点会再次出现。

**`_put_block` 用 timeout=1.0 不是无限等**: 万一下游线程挂了卡住,主线程也不会永远阻塞 — 1 秒一轮重试,主线程的取消查询点还能跑到。

## 7.2 `_Controller` — 暂停只用一个 Event

```python
class _Controller:
    """暂停控制 (线程共享)."""
    def __init__(self) -> None:
        self._paused = Event()
    def toggle(self) -> None:
        self._paused.clear() if self._paused.is_set() else self._paused.set()
    def is_paused(self) -> bool:
        return self._paused.is_set()
```

暂停状态全局只有一份, 用 `threading.Event` (天然线程安全)。`toggle()` 让 _Display 收到空格键时一下子切换状态。

主循环和 _Display 都查 `is_paused()` — **没有"通知"机制, 各自轮询**。这跟 cancel 是一样的设计:**轮询比通知更可控**。

## 7.3 `_Reader` 线程 — 根据源类型选不同的队列策略

```python
class _Reader(Thread):
    """读帧线程. 相机: 只留最新; 视频/图片: 有界阻塞."""

    def __init__(self, source, camera_config, *, live: bool,
                 capacity: int, capture_fps) -> None:
        super().__init__(daemon=True)
        self._source = source
        self._camera_config = camera_config
        self._live = live
        self._capture_fps = capture_fps
        self.q: Queue = Queue(maxsize=1 if live else capacity)
        self._stop_evt = Event()
        self.source_type = None
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            with create_frame_source(self._source, camera_config=self._camera_config) as src:
                self.source_type = src.get_source_type()
                t_prev = time.perf_counter()
                for frame in src:
                    if self._stop_evt.is_set():
                        break
                    now = time.perf_counter()
                    self._capture_fps.update((now - t_prev) * 1000)
                    t_prev = now
                    if self._live:
                        _put_latest(self.q, frame)        # 相机: 丢旧只留最新
                    else:
                        _put_block(self.q, frame)         # 视频/图片: 阻塞, 全处理
        except Exception as e:
            self.error = e
        finally:
            _put_block(self.q, _SENTINEL)                 # 结束哨兵
```

**关键纪律**:

- **`daemon=True`**: 主线程退出, 这个线程自动死。学生最容易忘的细节。
- **`maxsize=1 if live else capacity`**: 实时源 (相机/RTSP) 队列只装 1 帧, **天然丢旧**;文件源装 batch_size * 2,缓冲一些但不撑爆内存。
- **`with create_frame_source(...) as src`**: 用 frame_source 自己的 context manager,**资源释放交给它管**。我们不重复发明。
- **`source_type` 在 run() 里赋值, 主线程在首批后读**: 这是个**跨线程通信**, 但只是个枚举值,Python 的属性赋值原子,**不需要锁**(读写一次,值不会破)。
- **`self.error` 装异常**: reader 线程的异常**不冒到主线程**,而是装进 `self.error`,主线程在每次 `reader.get(timeout=2.0)` 拿到 `None` 时检查 `if reader.error: raise reader.error`。这是 D8 跨线程异常传播的标准模式。
- **`finally _put_block(...SENTINEL)`**: **不管 reader 怎么死, 哨兵必须放进队列**。否则主线程会一直在 `reader.get(timeout=2.0)` 上轮询拿不到东西。

## 7.4 `_Renderer` 线程 — 美化 + 接缝 + HUD

```python
class _Renderer(Thread):
    """渲染线程: 美化绘制 → sink.write → fire_frame → 叠 HUD → 丢给显示队列."""

    def __init__(
        self,
        processor,
        in_q: Queue,
        out_q: Queue,
        *,
        drop: bool,
        output_sink: OutputSink,
        show: bool,
        show_info: bool,
        recording: bool,
        metrics: Metrics,
        hooks: InferHooks,
    ) -> None:
        super().__init__(daemon=True)
        self._proc = processor
        self._in = in_q
        self._out = out_q
        self._drop = drop
        self._sink = output_sink
        self._show = show
        self._show_info = show_info
        self._recording = recording
        self._m = metrics
        self._hooks = hooks
        self._stop_evt = Event()
        self._frame_idx = 0

    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                item = self._in.get(timeout=0.1)
            except Empty:
                continue
            if item is _SENTINEL:
                _put_block(self._out, _SENTINEL)
                break
            frame, result, labels, n = item
            t0 = time.perf_counter()
            try:
                annotated = self._proc.draw(frame.image, result, labels, n)
            except Exception as e:
                logger.warning(f"渲染单帧失败, 跳过: {e}")
                continue
            self._m.render.update((time.perf_counter() - t0) * 1000)

            # ★ 接缝 1: sink.write — NullSink 是 no-op, LocalFileSink 写本地
            self._sink.write(frame, annotated)

            # ★ 接缝 2: fire_frame — 业务方注册了 on_frame 就推, 没注册零开销
            if self._hooks.on_frame is not None:
                self._hooks.fire_frame(FrameEvent(
                    frame_idx=self._frame_idx,
                    image=frame.image,
                    annotated=annotated,
                    n_detections=n,
                    detections=None,
                ))
            self._frame_idx += 1

            if self._show:
                # ★ 永远 copy 一份给 HUD —— sink 可能持有 annotated 引用 (LocalFileSink
                #   的 VideoWriter.write 是异步排队的, 我们立刻在原 ndarray 上画 HUD 会污染存盘帧).
                #   720p 一次 copy ~1MB, 30FPS 30MB/s, 完全可接受.
                disp = annotated.copy()
                draw_hud(disp, self._m, n_dets=n, recording=self._recording,
                         show_info=self._show_info)
                _put_latest(self._out, disp) if self._drop else _put_block(self._out, disp)
```

**关键纪律 (4 条全部一起出现, 这一段是 D8 接缝设计的兑现位)**:

1. **接缝 1 — `sink.write(frame, annotated)`**: 把"画好的 clean 帧"(没有 HUD)交给 sink。NullSink 不写,LocalFileSink 写本地,QtSignalSink 发 Qt 信号。**Renderer 不在乎是哪种**。
2. **接缝 2 — `fire_frame(FrameEvent)`**: 通知业务方。没注册 `on_frame` 时 fire 内部 short-circuit 零开销;注册了就推数据。
3. **★ "clean 帧 vs HUD 帧"分离**: 写盘 / sink 拿到的是**无 HUD 的干净 annotated**, 显示的才叠 HUD。所以 `disp = annotated.copy()` 必须做 — 否则我们在原 ndarray 上画 HUD,sink 还没异步写完的话存盘就脏了。这一行**统一 copy**,不像老式实现里"只在有 writer 时 copy"那么巧妙(那种条件 copy 容易踩坑,我们用一行简单的 always copy 换可读性)。
4. **`_put_latest if drop else _put_block`**: 显示队列的策略也分两路 —— save=False(`drop=True`)走低延迟丢旧,save=True(`drop=False`)走阻塞不丢。

## 7.5 `_Display` 线程 — ★ 速度命门所在

```python
class _Display(Thread):
    """显示线程: imshow + pollKey (非阻塞) 抓键 + 暂停层."""

    def __init__(self, out_q: Queue, window_name: str, controller: _Controller) -> None:
        super().__init__(daemon=True)
        self._out = out_q
        self._win = window_name
        self._ctrl = controller
        self._stop_evt = Event()
        self._key_lock = Lock()
        self._key = -1
        self._last = None

    def stop(self) -> None:
        self._stop_evt.set()

    def get_key(self) -> int:
        with self._key_lock:
            k, self._key = self._key, -1
            return k

    def run(self) -> None:
        import cv2
        poll = cv2.pollKey if hasattr(cv2, "pollKey") else (lambda: cv2.waitKey(1))
        while not self._stop_evt.is_set():
            frame = None
            try:
                item = self._out.get(timeout=0.03)
                if item is _SENTINEL:
                    pass
                else:
                    frame = item
                    self._last = frame
            except Empty:
                if self._ctrl.is_paused() and self._last is not None:
                    frame = self._last.copy()
                    draw_pause(frame)
            if frame is not None:
                cv2.imshow(self._win, frame)
            key = poll() & 0xFF
            if key != 255:
                with self._key_lock:
                    self._key = key
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
```

**这个文件里最关键的 30 行代码**。把它单独拎出来理由如下:

### 7.5.1 主线程不碰 GUI, 唯一例外在这

阶段 1.5 撞墙②已经讲了 `waitKey` 不是 1ms。**关键洞察:`waitKey` / `pollKey` 必须在 _Display 这个独立线程跑**,主线程在 ms 级速度上跑 predict 不被它拖。

这一条就是**纪律 C 的唯一兑现位**。整个 D8 代码库里, `cv2.imshow / waitKey / pollKey / destroyAllWindows` **只在这个文件里出现**。grep 验证:

```bash
$ grep -rE "cv2\.(imshow|waitKey|pollKey|destroyAllWindows)" apps/platform/src/odp_platform/
# 应该只匹配 _Display 一处, 否则就有人破纪律了
```

### 7.5.2 `pollKey` 优先, `waitKey(1)` fallback

`cv2.pollKey()` 是 OpenCV 4.5+ 加的"完全非阻塞读键",**不刷 GUI 事件循环**,几乎 0 开销。OpenCV 旧版没有,fallback 到 `waitKey(1)`(虽然有 1~20ms 阻塞,但只在 _Display 线程里,不拖主线程)。

```python
poll = cv2.pollKey if hasattr(cv2, "pollKey") else (lambda: cv2.waitKey(1))
```

### 7.5.3 按键不在 _Display 处理, 走 `get_key()` 给主线程

为什么? 因为按键处理 (空格暂停、q 退出) 涉及状态修改 (`controller.toggle()`、 退出主循环), **统一在主线程处理逻辑更简单**, _Display 只负责"抓键 + 转发"。

```python
def get_key(self) -> int:
    with self._key_lock:
        k, self._key = self._key, -1
        return k
```

主线程在主循环里调 `display.get_key()` 拿到键值, 然后 `_handle_key` 处理。**Lock 保护 self._key 的读写, 防止主线程读到一半 _Display 又写了新值**。

### 7.5.4 暂停层 — 队列空了 + 暂停态 → 重画 `_last` 加 PAUSED

```python
except Empty:
    if self._ctrl.is_paused() and self._last is not None:
        frame = self._last.copy()
        draw_pause(frame)
```

暂停时主线程不再推新帧, _Display 队列会很快空。如果不做处理, 画面就**冻住**(显示最后一帧)。我们改成:

- 队列空 + 暂停态 + 有上一帧 → 复制上一帧 + 叠 `PAUSED` 文字 + 显示
- 这样画面是**动态的"暂停画面"**, 比死锁的冻屏体验好

`self._last` 一直缓存最近一帧 (无论是否暂停, 每次 imshow 后更新)。

### 7.5.5 收尾 destroyAllWindows 用 try

```python
try:
    cv2.destroyAllWindows()
except Exception:
    pass
```

windowless 模式或者 OpenCV build 没带 GUI 时 `destroyAllWindows` 可能抛, **吞掉** —— 这是清理动作, 不能成功也别炸。

## 7.6 缓冲策略矩阵 — 一处定策略, 三处一致兑现

队列策略不是凭感觉填的,是 `save` 标志驱动的**全局策略**, 在 3 个队列上要**一致兑现**:

| 队列 | save=True (文件源, 完整优先) | save=False (相机, 低延迟优先) |
|---|---|---|
| **reader.q** (源 → 主) | live=False → `_put_block` 阻塞不丢 | live=True → `maxsize=1`, `_put_latest` 丢旧 |
| **in_q** (主 → renderer) | `_put_block` 阻塞不丢 | `_put_latest` 丢旧 |
| **out_q** (renderer → display) | `_put_block` 阻塞不丢 | `_put_latest` 丢旧 |

代码上, `save` 标志映射成两个布尔:

- `live = source.isdigit() or source.startswith(("rtsp://", "rtmp://"))` —— 是否实时源
- `render_drop = not save` —— renderer 派发是否丢旧

3 个队列各自选 helper, 但**口径一致** — 这是"缓冲策略 SSoT" 的体现。

## 7.7 队列容量 — 浅就是低延迟

```python
reader.q : maxsize = 1 if live else max(batch_size * 2, 8)
in_q     : maxsize = max(batch_size * 2, 4)
out_q    : maxsize = 2
```

为什么 **`out_q` 容量 = 2**? 浅到极致。**显示队列越深, 端到端延迟越大** — 如果 out_q 装 30 帧, 用户看到的画面就比"真实当前时刻"晚 1 秒(30 帧 @ 30fps)。

我们用 `_put_latest` + `maxsize=2` 把延迟逼到几十毫秒。

`reader.q` 和 `in_q` 容量大一点 (batch_size * 2),是给文件源**缓冲一批 + 一批冗余**, 让主线程的 batch 永远凑得满,GPU 不闲。摄像头 `reader.q=1` 直接最小化延迟,batch 凑不满也无所谓(摄像头本身就是 batch=1)。

## 7.8 `ThreadedPipeline.__init__` — 收下所有依赖

```python
class ThreadedPipeline:
    """多线程流水线. run() 阻塞跑完, 填充 stats, 返回是否被用户中断."""

    def __init__(
        self,
        *,
        processor,
        source,
        camera_config,
        output_dir,
        output_sink: OutputSink,
        batch_size,
        save,
        show,
        show_info,
        window_name,
        warmup_frames,
        hooks: InferHooks | None = None,
        cancel_token: CancelToken | None = None,
    ) -> None:
        self.proc = processor
        self.source = str(source)
        self.camera_config = camera_config
        self.output_dir = output_dir
        self.sink = output_sink
        self.batch_size = max(1, batch_size)
        self.save = save
        self.show = show
        self.show_info = show_info
        self.window_name = window_name
        self.warmup_frames = warmup_frames
        self.hooks = hooks if hooks is not None else InferHooks()
        self.cancel_token = cancel_token

    def _is_cancelled(self) -> bool:
        """统一查询入口 (cancel_token 为 None 时永远 False, 等价于零开销)."""
        return self.cancel_token is not None and self.cancel_token.is_cancelled()
```

**所有参数 keyword-only** (`*` 之后) — 这样调用方一定看名字传, 不会传错位置:

```python
# 调用方必须:
pipeline = ThreadedPipeline(processor=..., source=..., output_sink=..., ...)
# 而不能:
pipeline = ThreadedPipeline(processor, "demo.mp4", None, ...)   # ← 这个写法会 SyntaxError
```

3 个接缝 (`output_sink` / `hooks` / `cancel_token`) 都在这里收下, 后面 `run()` 里 dispatch 给对应的子线程或查询点。

`_is_cancelled()` 是个**统一查询入口** — 把"cancel_token 可能是 None"的 if 在这里处理一次, 主循环只看 `if self._is_cancelled(): break`, 干净。这就是"统一对 None 的处理"的小技巧。

## 7.9 `run()` 主循环 — 4 个 cancel 查询点 + 批级 loop FPS

完整 `run()` 方法 (约 110 行), 这是整个 D8 最复杂的一段代码。**先看完结构再细解读**。

```python
def run(self, stats) -> bool:
    m = Metrics()
    s = self.source
    live = s.isdigit() or s.lower().startswith(("rtsp://", "rtmp://"))
    eff_batch = 1 if live else self.batch_size      # 相机不批, 文件批
    render_drop = not self.save                      # 存盘不丢, 纯显示丢旧

    reader = _Reader(s, self.camera_config, live=live,
                     capacity=max(eff_batch * 2, 8), capture_fps=m.capture)
    in_q: Queue = Queue(maxsize=max(eff_batch * 2, 4))
    out_q: Queue = Queue(maxsize=2)
    controller = _Controller()

    renderer = None
    display = None
    interrupted = False
    warmed = 0
    last_batch_end_t = None         # ★ 批级测量 loop FPS 用的
    start_time = time.perf_counter()
    sink_opened = False

    reader.start()

    try:
        while True:
            # 暂停: 不 predict, 只查取消 + 读键
            if controller.is_paused():
                if self._is_cancelled():        # ★ 查询点 1
                    logger.info("收到取消信号 (暂停状态), 退出.")
                    interrupted = True
                    break
                if self._handle_key(display, controller):
                    interrupted = True
                    break
                time.sleep(0.02)
                continue

            # ★ 查询点 2: 取批之前查
            if self._is_cancelled():
                logger.info("收到取消信号, 退出主循环.")
                interrupted = True
                break

            # 取一批 (第一帧阻塞等 2 秒, 其余 nowait 凑批)
            first = reader.get(timeout=2.0)
            if first is None:
                if reader.error:
                    raise reader.error          # reader 异常向主线程传播
                continue
            if first is _SENTINEL:
                break
            batch = [first]
            ended = False
            for _ in range(eff_batch - 1):
                nxt = reader.get_nowait()
                if nxt is None:
                    break
                if nxt is _SENTINEL:
                    ended = True
                    break
                batch.append(nxt)

            # warmup: 丢弃前 N 帧 (摄像头刚启动帧率不稳)
            if warmed < self.warmup_frames:
                warmed += len(batch)
                if ended:
                    break
                continue

            # 首批时把 renderer/display 拉起来 + 开 sink (此时 source_type 已知)
            if renderer is None:
                try:
                    self.sink.open(self.output_dir, reader.source_type)
                    sink_opened = True
                except Exception as e:
                    logger.error(f"sink.open 失败, 退化用 NullSink: {e}")
                    self.sink = NullSink()
                    self.sink.open(self.output_dir, reader.source_type)
                    sink_opened = True

                renderer = _Renderer(
                    self.proc, in_q, out_q,
                    drop=render_drop,
                    output_sink=self.sink,
                    show=self.show,
                    show_info=self.show_info,
                    recording=self.save,
                    metrics=m,
                    hooks=self.hooks,
                )
                renderer.start()
                if self.show:
                    display = _Display(out_q, self.window_name, controller)
                    display.start()

            # --- 主线程: 批量 predict (不碰 GUI) ---
            images = [f.image for f in batch]
            results, labels_list, n_list, batch_dt = self.proc.infer_batch(images)
            stats.infer_time_sec += batch_dt
            for frame, result, labels, n in zip(batch, results, labels_list, n_list):
                stats.frames += 1
                stats.detections += n
                for name in labels:
                    stats.per_class[name] = stats.per_class.get(name, 0) + 1
                m.add_speed(getattr(result, "speed", None))
                # ★ 注意: 不在这里 update m.loop —— 批级测量在循环外做 (见下面)
                if render_drop:
                    _put_latest(in_q, (frame, result, labels, n))
                else:
                    _put_block(in_q, (frame, result, labels, n))

                # ★ 周期触发 on_progress (没注册时 fire 内部 short-circuit)
                if (self.hooks.on_progress is not None
                        and stats.frames % self.hooks.progress_interval_frames == 0):
                    self.hooks.fire_progress(ProgressEvent(
                        frame_idx=stats.frames,
                        total_frames=None,
                        elapsed_sec=time.perf_counter() - start_time,
                        fps_loop=m.loop.fps,
                        fps_infer=m.infer.fps,
                        detections_total=stats.detections,
                    ))

            # ★ 批级测量 loop FPS, 均摊到每帧填窗口
            #   - 测量点: 一批完整派发完之后
            #   - 单帧均摊 = (整批端到端耗时) / batch_size
            #   - 用这个值 update batch_size 次, 让滑动窗口样本数跟实际帧数对齐
            #   - 不在"批内 for 每一帧"测 —— 那样得到的"帧间隔"是几微秒, 会污染窗口
            batch_end_t = time.perf_counter()
            if last_batch_end_t is not None:
                per_frame_loop_ms = (batch_end_t - last_batch_end_t) * 1000 / len(batch)
                for _ in batch:
                    m.loop.update(per_frame_loop_ms)
            last_batch_end_t = batch_end_t

            # ★ 查询点 3: 派发完查 (避免下一轮 reader.get(2s) 拖延响应)
            if self._is_cancelled():
                logger.info("收到取消信号 (派发后), 退出.")
                interrupted = True
                break

            # ★ 查询点 4: 读键
            if self._handle_key(display, controller):
                interrupted = True
                break
            if ended:
                break
    finally:
        reader.stop()
        _put_block(in_q, _SENTINEL)
        if renderer is not None:
            renderer.join(timeout=3.0)
            renderer.stop()
        if display is not None:
            time.sleep(0.05)
            display.stop()
            display.join(timeout=1.0)
        # sink.close — 任何路径都要走到, 幂等
        if sink_opened:
            try:
                self.sink.close()
            except Exception as e:
                logger.warning(f"sink.close 异常 (已吞): {e}")

    _write_fps(stats, m)
    logger.info("流水线收尾: 捕获 %.1f | 推理 %.1f | 渲染 %.1f | loop %.1f FPS"
                % (m.capture.fps, m.infer.fps, m.render.fps, m.loop.fps))
    return interrupted
```

### 7.9.1 4 个 cancel 查询点 — 最差响应 2 秒

- **查询点 1**: 暂停状态。暂停时主线程在 `time.sleep(0.02)`,每次醒来检查。20ms 间隔, 响应几乎瞬间。
- **查询点 2**: 取批之前。**最常走的路径**, 主循环只要不在 GPU 推理就会走到。
- **查询点 3**: 派发完。避免如果刚好下一轮 `reader.get(timeout=2.0)` 拖 2 秒, 这里再查一次。
- **查询点 4**: 读键。CLI 按 q/Esc 走这一条, GUI 不依赖。

**最差响应**: 查询点 2 之后 + `reader.get(timeout=2.0)` 还没拿到帧 + GPU 在跑 → 等到下一次循环, 最差 ~2 秒。这就是 D8 承诺的 "< 2s 响应取消"。

### 7.9.2 sink 生命周期管理 — open / close 各一处

- **`sink.open(...)`** 在**首批帧到达后**(此时 `reader.source_type` 已知)调用, 用 `sink_opened` 标记
- **`sink.close()`** 在 **finally 块** 里调用,**任何退出路径都会走到**

如果 `sink.open` 抛了(比如 LocalFileSink 的 output_dir 没权限创建),**退化用 NullSink** —— 这样推理不死, 只是不写盘 + warning 提示。这是个**异常降级**, 跟纪律 A 一致(永不抛)。

### 7.9.3 批级 loop FPS — 解释一遍

`m.loop.update` **只在批末做一次**, 单帧均摊 update batch_size 次。为什么这么做, 阶段 5.1 已经详细说过:

- 批内 for 循环 N 次, 帧间真实间隔 ≈ 0 (没有 sleep, 只是 stats 累加 + put)
- 如果在 for 内逐帧 `update((now - last) * 1000)`, 滑动窗口会被 N-1 个污染样本灌满
- 改成"批结束算一次 (batch_end - last_batch_end) / N, update N 次填窗口" → 窗口里每个样本都是合理的"单帧均摊时间"

batch_size=16, REAL_BATCH_MS=50:
- 错误做法: loop FPS 飙到 4000+
- 正确做法: loop FPS = 320 (= 16 帧 / 50ms = 真实吞吐)

### 7.9.4 收尾顺序的纪律

`finally` 块的顺序很关键, **不能反**:

```
1. reader.stop()         ← 先告诉 reader 别再读了
2. _put_block(in_q, SENTINEL)  ← 给 renderer 一个结束信号
3. renderer.join(3s)     ← 等 renderer 把剩余帧消化完
4. renderer.stop()       ← 兜底 (3 秒还没自然退就强停)
5. time.sleep(0.05)      ← 给 display 一点时间处理 out_q 里的最后帧
6. display.stop()
7. display.join(1s)
8. sink.close()          ← 最后关 sink (renderer 已经停了, 不会再 write)
```

**反过来会出 bug**:

- 如果先 `sink.close()` 后 `renderer.join()`, renderer 还在跑就调 sink 写, sink 已关, write 失败 + warning
- 如果先 `renderer.stop()` 后 `_put_block(SENTINEL)`, renderer 已经退了不会消费这个 SENTINEL, 不影响但是哨兵机制语义不清

## 7.10 完整代码:`apps/platform/src/odp_platform/inference/pipeline.py`

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : pipeline.py
# @Project   : ODPlatform
# @Function  : 多线程推理流水线 — 采集/推理/渲染/显示 四级解耦, 主线程不碰 GUI
"""多线程推理流水线 (含接缝: OutputSink / InferHooks / CancelToken).

★ 速度的关键: 主线程【只做 predict + 非阻塞派发 + 读按键】, 从不调
  cv2.imshow / cv2.waitKey. 显示在【独立线程】里用 cv2.pollKey (非阻塞) 刷新.

四级流水线:
    reader 线程  读帧 (相机→只留最新; 视频/图片→有界阻塞)
      → 主线程   批量 predict + 派发 + 周期 fire_progress + 4 个 cancel 查询点
      → render 线程  美化绘制 → sink.write → fire_frame → 叠 HUD
      → display 线程 imshow + pollKey (仅 show=True 时)

接缝 (向后 100% 兼容, CLI 不传等价老式行为):
  - output_sink: 任意 OutputSink 实现, 默认 LocalFileSink (CLI) 或 NullSink (no-save)
  - hooks      : InferHooks dataclass, 默认全空回调零开销
  - cancel_token: CancelToken, 默认 None → 主循环查询零开销

loop FPS 测量纪律 (见 7.9.3):
  - 批级测量 + 均摊到帧, 不在批内 for 逐帧 update
  - 不然滑动窗口会被几微秒的污染样本灌满
"""
from __future__ import annotations

import logging
import time
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

from odp_platform.frame_source import create_frame_source

from .cancel import CancelToken
from .hooks import FrameEvent, InferHooks, ProgressEvent
from .overlay import Metrics, draw_hud, draw_pause
from .sinks import NullSink, OutputSink

logger = logging.getLogger(__name__)

_SENTINEL = object()


def _put_latest(q: Queue, item) -> None:
    """满则丢最旧再放 (latest-wins, 低延迟)."""
    try:
        q.put_nowait(item)
    except Full:
        try:
            q.get_nowait()
        except Empty:
            pass
        try:
            q.put_nowait(item)
        except Full:
            pass


def _put_block(q: Queue, item) -> None:
    """满则阻塞 (不丢, 存盘完整)."""
    while True:
        try:
            q.put(item, timeout=1.0)
            return
        except Full:
            continue


class _Controller:
    """暂停控制 (线程共享)."""
    def __init__(self) -> None:
        self._paused = Event()
    def toggle(self) -> None:
        self._paused.clear() if self._paused.is_set() else self._paused.set()
    def is_paused(self) -> bool:
        return self._paused.is_set()


# ============================================================================
# reader 线程
# ============================================================================
class _Reader(Thread):
    """读帧线程. 相机: 只留最新 (低延迟); 视频/图片: 有界阻塞 (全处理不丢)."""

    def __init__(self, source, camera_config, *, live: bool, capacity: int, capture_fps) -> None:
        super().__init__(daemon=True)
        self._source = source
        self._camera_config = camera_config
        self._live = live
        self._capture_fps = capture_fps
        self.q: Queue = Queue(maxsize=1 if live else capacity)
        self._stop_evt = Event()
        self.source_type = None
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            with create_frame_source(self._source, camera_config=self._camera_config) as src:
                self.source_type = src.get_source_type()
                t_prev = time.perf_counter()
                for frame in src:
                    if self._stop_evt.is_set():
                        break
                    now = time.perf_counter()
                    self._capture_fps.update((now - t_prev) * 1000)
                    t_prev = now
                    if self._live:
                        _put_latest(self.q, frame)
                    else:
                        _put_block(self.q, frame)
        except Exception as e:
            self.error = e
        finally:
            _put_block(self.q, _SENTINEL)

    def get(self, timeout: float):
        try:
            return self.q.get(timeout=timeout)
        except Empty:
            return None

    def get_nowait(self):
        try:
            return self.q.get_nowait()
        except Empty:
            return None

    def stop(self) -> None:
        self._stop_evt.set()


# ============================================================================
# render 线程
# ============================================================================
class _Renderer(Thread):
    """渲染线程: 美化绘制 → sink.write → fire_frame → 叠 HUD → 丢给显示队列."""

    def __init__(
        self,
        processor,
        in_q: Queue,
        out_q: Queue,
        *,
        drop: bool,
        output_sink: OutputSink,
        show: bool,
        show_info: bool,
        recording: bool,
        metrics: Metrics,
        hooks: InferHooks,
    ) -> None:
        super().__init__(daemon=True)
        self._proc = processor
        self._in = in_q
        self._out = out_q
        self._drop = drop
        self._sink = output_sink
        self._show = show
        self._show_info = show_info
        self._recording = recording
        self._m = metrics
        self._hooks = hooks
        self._stop_evt = Event()
        self._frame_idx = 0

    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                item = self._in.get(timeout=0.1)
            except Empty:
                continue
            if item is _SENTINEL:
                _put_block(self._out, _SENTINEL)
                break
            frame, result, labels, n = item
            t0 = time.perf_counter()
            try:
                annotated = self._proc.draw(frame.image, result, labels, n)
            except Exception as e:
                logger.warning(f"渲染单帧失败, 跳过: {e}")
                continue
            self._m.render.update((time.perf_counter() - t0) * 1000)

            # ★ 接缝 1: sink.write (NullSink no-op, LocalFileSink 写本地, QtSignalSink 发 Qt 信号)
            self._sink.write(frame, annotated)

            # ★ 接缝 2: fire_frame
            if self._hooks.on_frame is not None:
                self._hooks.fire_frame(FrameEvent(
                    frame_idx=self._frame_idx,
                    image=frame.image,
                    annotated=annotated,
                    n_detections=n,
                    detections=None,
                ))
            self._frame_idx += 1

            if self._show:
                # 永远 copy 给 HUD (sink 可能持有 annotated 引用, 不能就地改)
                disp = annotated.copy()
                draw_hud(disp, self._m, n_dets=n, recording=self._recording,
                         show_info=self._show_info)
                _put_latest(self._out, disp) if self._drop else _put_block(self._out, disp)


# ============================================================================
# display 线程 (★ 唯一碰 cv2.imshow/pollKey 的地方)
# ============================================================================
class _Display(Thread):
    """显示线程: imshow + pollKey (非阻塞) 抓键 + 暂停层."""

    def __init__(self, out_q: Queue, window_name: str, controller: _Controller) -> None:
        super().__init__(daemon=True)
        self._out = out_q
        self._win = window_name
        self._ctrl = controller
        self._stop_evt = Event()
        self._key_lock = Lock()
        self._key = -1
        self._last = None

    def stop(self) -> None:
        self._stop_evt.set()

    def get_key(self) -> int:
        with self._key_lock:
            k, self._key = self._key, -1
            return k

    def run(self) -> None:
        import cv2
        poll = cv2.pollKey if hasattr(cv2, "pollKey") else (lambda: cv2.waitKey(1))
        while not self._stop_evt.is_set():
            frame = None
            try:
                item = self._out.get(timeout=0.03)
                if item is _SENTINEL:
                    pass
                else:
                    frame = item
                    self._last = frame
            except Empty:
                if self._ctrl.is_paused() and self._last is not None:
                    frame = self._last.copy()
                    draw_pause(frame)
            if frame is not None:
                cv2.imshow(self._win, frame)
            key = poll() & 0xFF
            if key != 255:
                with self._key_lock:
                    self._key = key
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass


# ============================================================================
# 主编排
# ============================================================================
class ThreadedPipeline:
    """多线程流水线. run() 阻塞跑完, 填充 stats, 返回是否被用户中断."""

    def __init__(
        self,
        *,
        processor,
        source,
        camera_config,
        output_dir,
        output_sink: OutputSink,
        batch_size,
        save,
        show,
        show_info,
        window_name,
        warmup_frames,
        hooks: InferHooks | None = None,
        cancel_token: CancelToken | None = None,
    ) -> None:
        self.proc = processor
        self.source = str(source)
        self.camera_config = camera_config
        self.output_dir = output_dir
        self.sink = output_sink
        self.batch_size = max(1, batch_size)
        self.save = save
        self.show = show
        self.show_info = show_info
        self.window_name = window_name
        self.warmup_frames = warmup_frames
        self.hooks = hooks if hooks is not None else InferHooks()
        self.cancel_token = cancel_token

    def _is_cancelled(self) -> bool:
        """统一查询入口 (cancel_token 为 None 时永远 False, 零开销)."""
        return self.cancel_token is not None and self.cancel_token.is_cancelled()

    def run(self, stats) -> bool:
        m = Metrics()
        s = self.source
        live = s.isdigit() or s.lower().startswith(("rtsp://", "rtmp://"))
        eff_batch = 1 if live else self.batch_size
        render_drop = not self.save

        reader = _Reader(s, self.camera_config, live=live,
                         capacity=max(eff_batch * 2, 8), capture_fps=m.capture)
        in_q: Queue = Queue(maxsize=max(eff_batch * 2, 4))
        out_q: Queue = Queue(maxsize=2)
        controller = _Controller()

        renderer = None
        display = None
        interrupted = False
        warmed = 0
        last_batch_end_t = None
        start_time = time.perf_counter()
        sink_opened = False

        reader.start()

        try:
            while True:
                # 暂停: 不 predict, 只查取消 + 读键
                if controller.is_paused():
                    if self._is_cancelled():           # ★ 查询点 1
                        logger.info("收到取消信号 (暂停状态), 退出.")
                        interrupted = True
                        break
                    if self._handle_key(display, controller):
                        interrupted = True
                        break
                    time.sleep(0.02)
                    continue

                # ★ 查询点 2: 取批之前查
                if self._is_cancelled():
                    logger.info("收到取消信号, 退出主循环.")
                    interrupted = True
                    break

                # 取一批
                first = reader.get(timeout=2.0)
                if first is None:
                    if reader.error:
                        raise reader.error
                    continue
                if first is _SENTINEL:
                    break
                batch = [first]
                ended = False
                for _ in range(eff_batch - 1):
                    nxt = reader.get_nowait()
                    if nxt is None:
                        break
                    if nxt is _SENTINEL:
                        ended = True
                        break
                    batch.append(nxt)

                # warmup: 丢弃前 N 帧
                if warmed < self.warmup_frames:
                    warmed += len(batch)
                    if ended:
                        break
                    continue

                # 首批时拉起 renderer/display + 开 sink
                if renderer is None:
                    try:
                        self.sink.open(self.output_dir, reader.source_type)
                        sink_opened = True
                    except Exception as e:
                        logger.error(f"sink.open 失败, 退化用 NullSink: {e}")
                        self.sink = NullSink()
                        self.sink.open(self.output_dir, reader.source_type)
                        sink_opened = True

                    renderer = _Renderer(
                        self.proc, in_q, out_q,
                        drop=render_drop,
                        output_sink=self.sink,
                        show=self.show,
                        show_info=self.show_info,
                        recording=self.save,
                        metrics=m,
                        hooks=self.hooks,
                    )
                    renderer.start()
                    if self.show:
                        display = _Display(out_q, self.window_name, controller)
                        display.start()

                # --- 主线程: 批量 predict ---
                images = [f.image for f in batch]
                results, labels_list, n_list, batch_dt = self.proc.infer_batch(images)
                stats.infer_time_sec += batch_dt
                for frame, result, labels, n in zip(batch, results, labels_list, n_list):
                    stats.frames += 1
                    stats.detections += n
                    for name in labels:
                        stats.per_class[name] = stats.per_class.get(name, 0) + 1
                    m.add_speed(getattr(result, "speed", None))
                    # 不在这里 update m.loop, 批级测量在循环外做
                    if render_drop:
                        _put_latest(in_q, (frame, result, labels, n))
                    else:
                        _put_block(in_q, (frame, result, labels, n))

                    # ★ 周期 fire_progress
                    if (self.hooks.on_progress is not None
                            and stats.frames % self.hooks.progress_interval_frames == 0):
                        self.hooks.fire_progress(ProgressEvent(
                            frame_idx=stats.frames,
                            total_frames=None,
                            elapsed_sec=time.perf_counter() - start_time,
                            fps_loop=m.loop.fps,
                            fps_infer=m.infer.fps,
                            detections_total=stats.detections,
                        ))

                # ★ 批级测量 loop FPS, 均摊到每帧填窗口
                batch_end_t = time.perf_counter()
                if last_batch_end_t is not None:
                    per_frame_loop_ms = (batch_end_t - last_batch_end_t) * 1000 / len(batch)
                    for _ in batch:
                        m.loop.update(per_frame_loop_ms)
                last_batch_end_t = batch_end_t

                # ★ 查询点 3: 派发完查
                if self._is_cancelled():
                    logger.info("收到取消信号 (派发后), 退出.")
                    interrupted = True
                    break

                # ★ 查询点 4: 读键
                if self._handle_key(display, controller):
                    interrupted = True
                    break
                if ended:
                    break
        finally:
            reader.stop()
            _put_block(in_q, _SENTINEL)
            if renderer is not None:
                renderer.join(timeout=3.0)
                renderer.stop()
            if display is not None:
                time.sleep(0.05)
                display.stop()
                display.join(timeout=1.0)
            if sink_opened:
                try:
                    self.sink.close()
                except Exception as e:
                    logger.warning(f"sink.close 异常 (已吞): {e}")

        _write_fps(stats, m)
        logger.info("流水线收尾: 捕获 %.1f | 推理 %.1f | 渲染 %.1f | loop %.1f FPS"
                    % (m.capture.fps, m.infer.fps, m.render.fps, m.loop.fps))
        return interrupted

    def _handle_key(self, display, controller) -> bool:
        """读显示线程抓到的键. 返回是否要退出."""
        if display is None:
            return False
        key = display.get_key()
        if key in (ord("q"), 27):
            logger.info("用户请求退出 (q/Esc).")
            return True
        if key == ord(" "):
            controller.toggle()
            logger.info("已暂停 (空格恢复)" if controller.is_paused() else "已恢复")
        return False


def _write_fps(stats, m: Metrics) -> None:
    snap = m.snapshot()
    stats.capture_fps = snap["capture_fps"]
    stats.infer_fps = snap["infer_fps"]
    stats.render_fps = snap["render_fps"]
    stats.loop_fps = snap["loop_fps"]
    stats.current_fps = snap["current_fps"]
    stats.speed_ms = snap["speed_ms"]
```

## 7.11 这一阶段先不单测

`ThreadedPipeline` 需要真实的 `_FrameProcessor`(下一阶段的 service.py 才有)和真实的 frame_source 才能跑通。**单独跑 pipeline.py 没意义** — 留到阶段 8 写完 service.py 后, 直接跑 CLI 验证。

如果想现在就 mock 测试, 可以参考 `regression_test/test_05_pipeline_integration.py`(D8 配套的回归测试), 那里用 mock frame_source + mock processor 验证 pipeline 的"行为骨架", 跑通不需要 ultralytics / cv2 / GPU。

## 7.12 git commit

```bash
git add apps/platform/src/odp_platform/inference/pipeline.py
git commit -m "feat(D8): inference 子系统 pipeline.py — 四级多线程流水线

四级流水线: reader / 主线程 / renderer / display

关键设计:
- ★ 主线程不碰 GUI (纪律 C, cv2.imshow/pollKey 只在 _Display)
- 队列缓冲策略矩阵: save/不save × 视频/相机, 三处一致兑现
- out_q maxsize=2 + 丢旧 = 低延迟显示
- in_q / reader.q = batch_size*2 = GPU 不闲

接缝集成:
- sink.write 在 renderer 线程 (业务无感知)
- fire_frame / fire_progress 周期触发, 没注册零开销
- 4 个 cancel 查询点保证 < 2s 响应

loop FPS 批级测量纪律:
- (batch_end - last_batch_end) / batch_size, update N 次填窗口
- 不在批内 for 逐帧 update (会污染滑动窗口)

收尾顺序纪律 (finally 块):
- reader → in_q SENTINEL → renderer join → display join → sink.close"
```

至此, **D8 推理子系统最复杂的一个文件完成**。下一阶段 `service.py` 把所有这些组装成对外的 `InferService.predict()`。

---
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 8: `service.py` — `InferService` 装配 + 异常兜底

`InferService` 是 D8 的**对外接口**, 它把前面 7 个阶段做的所有零件**装配**起来, 提供一个干净的 `predict(...)` 方法。

跟 D6 的 `TrainService` 同构 (都是 Service 模式), 但里面调的是 `ThreadedPipeline` + 接缝, 不是 `model.train`。

## 8.1 `InferService` 不做的事

先列出 `InferService` **不该做**什么 — 这些事让别人做, 体现"不重新发明"纪律:

| 不做的事 | 由谁做 |
|---|---|
| 解析 yaml → pydantic | D5 `build_infer_config` |
| 装 logging handler | D2 `get_logger`, 在 CLI 入口装一次 |
| 解析模型路径 | `common.resolve_model_path` |
| 读各种源的帧 | `frame_source.create_frame_source` |
| 画框 | `visualization.BeautifyVisualizer` |
| 跟 GPU 打交道 | `ultralytics.YOLO` |
| 写本地文件 | `LocalFileSink` (阶段 6 的接缝实现) |
| 多线程流水线 | `ThreadedPipeline` (阶段 7) |
| 决定输出 / 事件 / 取消 的具体行为 | 调用方传入的 sink / hooks / cancel_token |

剩下的事就是**装配 + 异常兜底 + 审计快照**, 这就是 `InferService.predict()` 的全部职责。

## 8.2 `InferService.predict()` 的 8 个阶段

```
阶段 1: 配置加载       (build_infer_config + load_pipeline_config)
阶段 2: 上下文日志     (log_device_info + 字段溯源)
阶段 3: 源 + 模型解析   (fail-fast 校验)
阶段 4: 加载模型 + 建美化器 + 建输出目录 + 决定 sink
阶段 5: 执行推理       (ThreadedPipeline.run)
阶段 6: 推理统计       (log_infer_stats)
阶段 7: 整理输出       (rename_log)
阶段 8: 审计快照       (写 odp_audit.json)

收尾: hooks.fire_complete + 返回 InferResult
异常: 顶层 except → hooks.fire_error + 打包成 InferResult.error
```

这 8 个阶段在 `predict()` 里**一字排开 + 注释明确分隔**, 学生看到第几个 `==========` 就知道在第几阶段, 找代码不绕。

## 8.3 设计点①: 两份配置各加各的, 互不干涉

```python
# 阶段 1: 配置加载
config, merger = build_infer_config(
    yaml_path=yaml_path or "infer.yaml",
    cli_args=cli_args,
)
pipe: PipelineConfig = load_pipeline_config(pipeline_yaml)
```

`config` 是 D5 的扁平 pydantic 模型 (YOLO predict 参数), `pipe` 是阶段 4 的嵌套 dataclass (帧源 + 美化)。**两者完全独立**, 后面用各拿各的:

- `config.source` / `config.model` / `config.conf` / ... → 给 ultralytics 用
- `pipe.viz_enabled` / `pipe.label_mapping` / `pipe.camera_raw` → 给 frame_source / visualization 用

`merger` 是 D5 给的字段溯源对象, 后面阶段 2 用它打"哪个字段来自哪个 yaml / CLI"。

## 8.4 设计点②: `_resolve_output_dir` — 自增编号跟 ultralytics 对齐

YOLO 训练时 ultralytics 的目录管理是这样的:

- `name=predict` 且目录已存在 → 自动建 `predict2`, `predict3`, ...
- `exist_ok=True` 时复用已有目录, 覆盖里面的文件

推理我们自己写主循环 (没调 `model.predict(source=...)`), 所以 ultralytics 不帮我们建目录, **必须自己实现这个语义**:

```python
def _resolve_output_dir(base: Path, name: str, *, exist_ok: bool) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    candidate = base / name
    if exist_ok or not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    i = 2
    while (base / f"{name}{i}").exists():
        i += 1
    out = base / f"{name}{i}"
    out.mkdir(parents=True, exist_ok=True)
    return out
```

用户体验跟训练一致: 同一个 name 多次跑, 自动 `predict / predict2 / predict3` 序号化。

## 8.5 设计点③: `resolve_model_path` 的搜索顺序

```python
model_path = resolve_model_path(
    raw_model,
    search_dirs=[CHECKPOINTS_DIR, PRETRAINED_MODELS_DIR],
)
```

**搜索顺序很重要**: **先查 `CHECKPOINTS_DIR` (训练归档的 best/last), 再查 `PRETRAINED_MODELS_DIR` (官方下载的 yolo11n.pt 之类)**。

为什么这个顺序? 因为:

- 用户在 `infer.yaml` 写 `model: best.pt` 是想用**自己训练出来的模型** — 优先从 checkpoints 找
- 用户写 `model: yolo11n.pt` 是想用**官方预训练** — 在 pretrained 里找

CHECKPOINTS_DIR 里没有就 fallback 到 PRETRAINED_MODELS_DIR, 都没就让 ultralytics 自己去网上拉。

这是**接口承诺**, `resolve_model_path` 自己 docstring 也写了。如果以后要支持 ONNX / TensorRT 模型, 也走这个函数, **加扩展不改用法**。

## 8.6 设计点④: `_PREDICT_KEYS` — 推理参数白名单, 不盲传 config

```python
_PREDICT_KEYS: tuple[str, ...] = (
    "conf", "iou", "imgsz", "max_det", "classes",
    "agnostic_nms", "augment", "device", "retina_masks",
)

# ...

predict_kwargs = {
    k: getattr(config, k)
    for k in _PREDICT_KEYS
    if getattr(config, k, None) is not None
}
predict_kwargs["verbose"] = False
```

**为什么不直接 `config.to_ultralytics_kwargs()` 全传?**

D5 的 `YOLOInferConfig` 继承 `BaseConfig`, 字段是从训练侧反射来的, **混进了一堆训练向字段**:

- `batch`, `workers`, `cache`, `rect`, `amp`, `seed`, `deterministic` (训练超参)
- `project`, `name`, `exist_ok` (输出路径管理, 我们自己处理了不要 ultralytics 管)
- `save`, `save_txt`, `save_conf` (保存控制, 我们用 sink 管了)

这些字段对**逐帧 model() 调用**要么报错要么被忽略, 但更糟的是:

- **行为变了**: 比如 `save=True` 让 ultralytics 又存了一份 (我们已经在 LocalFileSink 里存了, 重复存两份)
- **报错点变了**: ultralytics 内部哪个版本会校验哪个字段不一定, 升级时容易踩坑

所以我们**显式白名单** _PREDICT_KEYS, 只传真正影响"单帧检测计算"的 9 个参数。**安全、可读、不踩雷**。

`predict_kwargs["verbose"] = False` 是强制关掉 ultralytics 的 per-frame stdout 日志 (不然 1 秒 30 行 console 输出, 没法看)。

## 8.7 设计点⑤: `_FrameProcessor` — 推理与绘制的接缝

```python
@dataclass
class _FrameProcessor:
    model: Any
    predict_kwargs: dict[str, Any]
    do_beautify: bool
    visualizer: BeautifyVisualizer | None
    use_label_mapping: bool
    style_overrides: dict[str, Any]
    names: dict[int, str]
    _style: DrawStyle | None = None

    def infer_batch(self, images: list):
        """主线程: 批量推理. 返回 (results, labels_list, n_list, batch_dt)."""
        t0 = time.perf_counter()
        results = self.model(images, **self.predict_kwargs)
        batch_dt = time.perf_counter() - t0
        labels_list: list[list[str]] = []
        n_list: list[int] = []
        for result in results:
            boxes = result.boxes
            n = 0 if boxes is None else len(boxes)
            n_list.append(n)
            labels_list.append(
                [self.names[i] for i in boxes.cls.int().cpu().tolist()] if n else []
            )
        return results, labels_list, n_list, batch_dt

    def draw(self, image, result, labels, n):
        """绘制单帧 → annotated (BGR). 美化关时退回 YOLO 原生 plot()."""
        if self.do_beautify and self.visualizer is not None:
            if self._style is None:                  # 第一帧定样式, 后续复用
                h, w = image.shape[:2]
                self._style = DrawStyle.from_image_size(h, w, **self.style_overrides)
            boxes = result.boxes
            dets = BeautifyVisualizer.from_yolo_results(
                boxes=(boxes.xyxy.cpu().numpy() if n else _empty_boxes()),
                confidences=(boxes.conf.cpu().numpy() if n else _empty_conf()),
                labels=labels,
            )
            return self.visualizer.draw(
                image, dets, style=self._style, use_label_mapping=self.use_label_mapping,
            )
        return result.plot()
```

**`_FrameProcessor` 是 pipeline 跟 model / visualizer 之间的接缝**, 把两件不同性质的事放在一起:

- **`infer_batch`(主线程跑)**: 一次 GPU 调处理整批, 比逐帧快得多。返回 4 元组让 pipeline 用。
- **`draw`(renderer 线程跑)**: 绘制单帧。第一帧拿到尺寸后构造 `DrawStyle`, 后续复用。

**为什么 `_style` 不加锁?** 因为 `_style` 只被一个线程 (renderer) 写。pipeline 把 `_FrameProcessor` 实例传给 `_Renderer.__init__`, 此后 `_style` 的写入只在 `_Renderer` 线程里发生。主线程的 `infer_batch` 完全不碰 `_style`。所以**虽然这个对象被两个线程访问, 但访问的字段不重叠** — 跟 5.4 节讲的 Metrics 同样的道理, 不需要锁。

**为什么 `draw` 第一帧才定 style?** `DrawStyle.from_image_size(h, w)` 是个昂贵计算 (字号 / 线宽 / padding 都从图像尺寸推), 每帧重算浪费。第一帧拿到 (h, w) 后固化, 后续帧只要尺寸不变就一直复用 — 假设输入分辨率不会动态变化 (实际场景几乎都是这样)。

**为什么美化关掉走 `result.plot()`?** ultralytics 自带的 plot 是基础款 (英文标签 + 固定颜色), 但**很快、不挑环境**。当用户跑 `--no-viz` 时是图速度或排查美化模块 bug, 这时候退回原生 plot 是最稳的 fallback。

## 8.8 设计点⑥: 顶层异常兜底 — 永不向外抛

```python
def predict(self, ...) -> InferResult:
    if hooks is None:
        hooks = InferHooks()       # 兜底空 hooks, 后面 fire_* 不出错

    start = datetime.now()
    output_dir: Path | None = None

    try:
        # ... 8 个阶段 ...

        result = InferResult(success=True, ...)
        hooks.fire_complete(result)
        return result

    except Exception as e:
        logger.error(f"推理失败: {e}", exc_info=True)
        infer_time = (datetime.now() - start).total_seconds()
        hooks.fire_error(e)
        return InferResult(
            success=False,
            output_dir=output_dir or Path("unknown"),
            stats={},
            infer_time=infer_time,
            error=str(e),
            log_path=_find_project_log_path(),
        )
```

**纪律 A 在 service 层的最终兑现位**:

- 任何异常 (D5 配置错、模型不存在、源打不开、磁盘满) **都被这个顶层 try/except 兜住**
- 异常打包成 `InferResult.error` 返回
- 同步触发 `hooks.fire_error(e)` 让业务方收到通知
- 即便兜底过程本身又出问题, 也至少能返回一个 `InferResult(success=False)`

**CLI 层 (阶段 9) 看 `result.success` 决定 exit code:**

```python
result = infer_yolo(...)
sys.exit(0 if result.success else 1)
```

**桌面端拿到 `result` 决定 UI 状态**:

```python
def _on_finished(self, result):
    if result.success:
        self.statusBar().showMessage(f"完成 {result.stats['frames']} 帧")
    else:
        QMessageBox.critical(self, "失败", result.error)
```

**所有调用方都 0 try/except**, 这是 service 永不抛承诺的价值 — 调用方代码可以**线性写**, 不用包一堆错误处理。

## 8.9 设计点⑦: sink 的默认选择 — 不传时根据 want_save 自动选

```python
if output_sink is None:
    output_sink = LocalFileSink() if want_save else NullSink()
    _sink_owned = True
else:
    _sink_owned = False     # 调用方传的, 调用方知道自己在干啥
    logger.info(f"使用调用方提供的 sink: {output_sink.__class__.__name__}")
```

**默认行为兼容老式 CLI**:

| 调用方传值 | want_save | 内部用的 sink |
|---|---|---|
| `output_sink=None` (CLI 不传) | `save=True` (默认) | `LocalFileSink()` |
| `output_sink=None` (CLI 不传) | `save=False` (--no-save) | `NullSink()` |
| `output_sink=QtSignalSink()` (桌面端传) | (任意) | 用调用方的 |

**这就是"向后 100% 兼容"在 sink 层的兑现** — CLI 调用 `service.predict()` 不传 sink, 行为跟"没有接缝改造"完全一样。

`_sink_owned` 这个变量目前没用上 (pipeline 永远调 `sink.close()`, 不管 owned 不 owned), 留着是预留:**如果将来要让"调用方传的 sink 不能被 pipeline close"** (调用方有自己的生命周期), 这个标志就能 switch 行为。**预留扩展点而不是过早做扩展**。

## 8.10 设计点⑧: 审计快照 `odp_audit.json`

```python
audit_path = output_dir / "odp_audit.json"
log_path = _find_project_log_path()
try:
    audit_payload = {
        "mode": "infer",
        "config": config.to_audit_snapshot(),
        "merger": merger.to_audit_log(),
        "pipeline": pipe.to_audit(),
        "stats": stats.to_dict(),
        "result_summary": {
            "output_dir": str(output_dir),
            "saved": want_save,
            "beautified": do_beautify,
            "infer_time_sec": (datetime.now() - start).total_seconds(),
            "log_path": str(log_path) if log_path else None,
        },
    }
    audit_path.write_text(
        json.dumps(audit_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"审计快照:   {audit_path}")
except OSError as e:
    logger.warning(f"写审计快照失败 (不影响推理结果): {e}")
    audit_path = None
```

**每次推理都留一份 JSON 快照**, 内容:

- **`mode`**: `"infer"` (跟训练的 `"train"` 区分)
- **`config`**: D5 字段当前值 (脱敏过, 不带 secret)
- **`merger`**: 字段溯源链 (这个值是 yaml 还是 CLI 来的)
- **`pipeline`**: 帧源 + 美化配置摘要
- **`stats`**: 帧数 / 检测数 / 5 维 FPS / 模型 speed
- **`result_summary`**: 输出目录、是否存盘、是否美化、总耗时、日志路径

**用途**:

- 论文复现: 一年后想复现这次实验, 直接看 audit 知道用了啥配置
- 实验对比: 跑 N 次不同 conf 阈值, 后期对比 N 个 audit 文件就行
- 失败追溯: 推理失败时 audit 文件可能没写出来, 但**日志路径在错误日志里**, 双保险

**异常处理**: 写 audit 失败 (磁盘满 / 权限) → warning + 继续, 不让 audit 失败拖累推理结果。

## 8.11 `infer_yolo` 便捷函数

```python
def infer_yolo(
    yaml_path=None, pipeline_yaml=None, cli_args=None,
    *,
    beautify=True, rename_log=True, threaded=False,
    warmup_frames=0, window_name="odp-infer", show_info=True,
    output_sink=None, hooks=None, cancel_token=None,
) -> InferResult:
    """一行启动推理 —— 风格跟 D5 build_infer_config / D6 train_yolo 一致."""
    service = InferService()
    return service.predict(
        yaml_path=yaml_path,
        pipeline_yaml=pipeline_yaml,
        cli_args=cli_args,
        beautify=beautify,
        rename_log=rename_log,
        threaded=threaded,
        warmup_frames=warmup_frames,
        window_name=window_name,
        show_info=show_info,
        output_sink=output_sink,
        hooks=hooks,
        cancel_token=cancel_token,
    )
```

**风格跟 D6 `train_yolo` 对齐** — 一行启动, 不用 new service。当业务只需要"跑一次推理"时, 用这个比 `InferService().predict(...)` 更简洁。

## 8.12 完整代码:`apps/platform/src/odp_platform/inference/service.py`

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : service.py
# @Project   : ODPlatform
# @Function  : InferService — 编排 D5 配置 + 帧源捕获 + ultralytics 推理 + 美化绘制
"""推理服务编排器.

★ 核心纪律 (跟 D6 TrainService 完全同构): 不重新发明 D5 / 帧源 / 美化已有的轮子.

★ 接缝 (向后 100% 兼容):
  - predict() 3 个新参数: output_sink / hooks / cancel_token, 全部 keyword-only Optional[None]
  - 不传 = CLI 默认行为 (LocalFileSink / 空 hooks / 无 cancel)
  - 传了 = 桌面 / Web / Celery 业务方能完全定制输出 + 事件 + 取消

★ 跟训练的两点关键差异:
  1. 推理不调 model.predict(source=...) —— 而是 frame_source 逐帧喂 + 自己画
  2. 逐帧 model() 只传 predict 计算参数白名单, 不盲传 to_ultralytics_kwargs()
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ultralytics import YOLO

from odp_platform.common.log_rename import rename_log_to_save_dir
from odp_platform.common.model_path import resolve_model_path
from odp_platform.common.paths import CHECKPOINTS_DIR, PRETRAINED_MODELS_DIR, RUNS_DIR
from odp_platform.common.system_utils import log_device_info
from odp_platform.common.config_log import log_effective_config, log_override_chains
from odp_platform.runtime_config import build_infer_config

from odp_platform.frame_source import create_frame_source, SourceType, IMAGE_EXTENSIONS
from odp_platform.visualization import BeautifyVisualizer, DrawStyle

from .cancel import CancelToken
from .hooks import InferHooks
from .pipeline_config import PipelineConfig, load_pipeline_config
from .sinks import LocalFileSink, NullSink, OutputSink

logger = logging.getLogger(__name__)


# ============================================================================
# 逐帧 model() 的 predict 计算参数白名单
# ----------------------------------------------------------------------------
# 为什么不盲传 config.to_ultralytics_kwargs()? YOLOInferConfig 继承 BaseConfig,
# 带进来一堆训练向字段 (batch/workers/cache/rect/amp/seed/...), 这些传给逐帧
# model() 要么报错要么被忽略. 显式列出真正影响"单帧检测计算"的参数, 只传这些.
# ============================================================================
_PREDICT_KEYS: tuple[str, ...] = (
    "conf", "iou", "imgsz", "max_det", "classes",
    "agnostic_nms", "augment", "device", "retina_masks",
)


def _find_project_log_path() -> Path | None:
    """从 D2 'odp_platform' 根 logger 找 FileHandler 的实际文件路径 (只读, 给 audit 用)."""
    root = logging.getLogger("odp_platform")
    for h in root.handlers:
        if isinstance(h, logging.FileHandler):
            return Path(h.baseFilename)
    return None


def _resolve_output_dir(base: Path, name: str, *, exist_ok: bool) -> Path:
    """自建推理输出目录 (跟 ultralytics 行为对齐: 重名自增 name2/name3...)."""
    base.mkdir(parents=True, exist_ok=True)
    candidate = base / name
    if exist_ok or not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    i = 2
    while (base / f"{name}{i}").exists():
        i += 1
    out = base / f"{name}{i}"
    out.mkdir(parents=True, exist_ok=True)
    return out


# ============================================================================
# 推理统计 —— 推理侧没有 mAP, 取而代之的是 帧数/检测数/每类计数/FPS
# ============================================================================
@dataclass
class InferStats:
    """一次推理跑完的统计快照."""
    frames: int = 0
    detections: int = 0
    per_class: dict[str, int] = field(default_factory=dict)
    infer_time_sec: float = 0.0

    # 多维帧率 (引擎跑完填入)
    capture_fps: float = 0.0
    infer_fps: float = 0.0
    render_fps: float = 0.0
    loop_fps: float = 0.0
    current_fps: float = 0.0
    speed_ms: dict[str, float] = field(default_factory=dict)

    @property
    def avg_fps(self) -> float:
        return self.frames / self.infer_time_sec if self.infer_time_sec > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return (self.infer_time_sec / self.frames * 1000.0) if self.frames else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames": self.frames,
            "detections": self.detections,
            "per_class": dict(self.per_class),
            "infer_time_sec": round(self.infer_time_sec, 4),
            "avg_fps": round(self.avg_fps, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "fps": {
                "capture": self.capture_fps,
                "infer": self.infer_fps,
                "render": self.render_fps,
                "loop": self.loop_fps,
                "current": self.current_fps,
            },
            "speed_ms": dict(self.speed_ms),
        }


def log_infer_stats(stats: InferStats, *, logger: logging.Logger = logger) -> None:
    """漂亮打印推理统计 (含多维帧率)."""
    logger.info(f"处理帧数:   {stats.frames}")
    logger.info(f"检测总数:   {stats.detections}")
    logger.info(f"平均延迟:   {stats.avg_latency_ms:.2f} ms/帧")
    logger.info("帧率(FPS):  捕获 %.1f | 推理 %.1f | 渲染 %.1f | loop %.1f | 当前 %.1f" % (
        stats.capture_fps, stats.infer_fps, stats.render_fps,
        stats.loop_fps, stats.current_fps,
    ))
    if stats.speed_ms:
        logger.info("模型 speed(ms): 预处理 %.2f | 推理 %.2f | 后处理 %.2f" % (
            stats.speed_ms.get("preprocess", 0.0),
            stats.speed_ms.get("inference", 0.0),
            stats.speed_ms.get("postprocess", 0.0),
        ))
    if stats.per_class:
        logger.info("各类别检测数:")
        for name, cnt in sorted(stats.per_class.items(), key=lambda kv: -kv[1]):
            logger.info(f"    {name:<20} {cnt}")


@dataclass(frozen=True)
class InferResult:
    """推理结果一次性快照 (跟 TrainResult 平行)."""
    success:    bool
    output_dir: Path
    stats:      dict[str, Any] = field(default_factory=dict)
    infer_time: float | None = None
    saved:      bool = False
    error:      str | None = None
    audit_path: Path | None = None
    log_path:   Path | None = None


# ============================================================================
# InferService 主类
# ============================================================================
class InferService:
    """YOLO 推理流程编排."""

    def __init__(self) -> None:
        """__init__ 不接任何参数 —— 配置都通过 predict() 传."""
        pass

    def predict(
        self,
        yaml_path: str | Path | None = None,
        pipeline_yaml: str | Path | None = None,
        cli_args: dict[str, Any] | None = None,
        *,
        # ---- CLI 默认行为参数 (传统) ----
        beautify: bool = True,
        rename_log: bool = True,
        threaded: bool = False,
        warmup_frames: int = 0,
        window_name: str = "odp-infer",
        show_info: bool = True,
        # ---- ★ 接缝参数 (业务定制), keyword-only + 默认 None 让 CLI 行为不变 ----
        output_sink: OutputSink | None = None,
        hooks: InferHooks | None = None,
        cancel_token: CancelToken | None = None,
    ) -> InferResult:
        """跑一次完整推理.

        Args:
            yaml_path:     D5 infer.yaml 路径. None 走默认.
            pipeline_yaml: 帧源+美化 infer_pipeline.yaml 路径. None 走默认.
            cli_args:      CLI 覆盖字段 (source/conf/show/save/...), 交给 D5 merger.
            beautify:      是否美化. False → 退回 YOLO 原生 plot().
            rename_log:    是否把日志名改成跟 output_dir 对齐.
            threaded:      历史遗留, 现在永远是多线程, 这个参数被忽略.
            warmup_frames: 启动丢弃前 N 帧 (摄像头帧率不稳).
            window_name:   显示窗口标题 (--show 时).
            show_info:     是否画 HUD 信息面板.
            output_sink:   自定义输出适配器 (默认根据 want_save 选 LocalFileSink / NullSink).
            hooks:         生命周期回调 (默认全空回调, 零开销).
            cancel_token:  程序化取消信号 (默认 None, 只能等帧源耗尽).

        Returns:
            InferResult. ★ 永不抛 —— 任何异常打包进 InferResult.error.
        """
        # ★ hooks 兜底空回调 (内部 fire 时 short-circuit, 零开销)
        if hooks is None:
            hooks = InferHooks()

        start = datetime.now()
        output_dir: Path | None = None

        try:
            # ================================================================
            # 阶段 1: 配置加载
            # ================================================================
            config, merger = build_infer_config(
                yaml_path=yaml_path or "infer.yaml",
                cli_args=cli_args,
            )
            pipe: PipelineConfig = load_pipeline_config(pipeline_yaml)

            # ================================================================
            # 阶段 2: 上下文日志
            # ================================================================
            logger.info("=" * 60)
            logger.info(f"开始 YOLO 推理 (task={config.task})".center(60))
            logger.info("=" * 60)

            raw_model = config.model or "yolo11n.pt"
            raw_source = config.source
            logger.info(f"任务类型:    {config.task}")
            logger.info(f"输入源(声明): {raw_source!r}")
            logger.info(f"模型(声明):  {raw_model}")

            log_device_info()
            log_effective_config(config, merger, logger=logger)
            log_override_chains(config, merger, logger=logger)

            # ================================================================
            # 阶段 3: 源 + 模型解析
            # ================================================================
            if raw_source is None:
                raise RuntimeError(
                    "未指定推理输入源. 请在 infer.yaml 写 source, 或用 "
                    "`odp-infer --source <图/视频/目录/摄像头号>` 传入."
                )

            model_path = resolve_model_path(
                raw_model,
                search_dirs=[CHECKPOINTS_DIR, PRETRAINED_MODELS_DIR],
            )
            logger.info(f"模型(解析):  {model_path}")

            # ================================================================
            # 阶段 4: 加载模型 + 建美化器 + 建输出目录 + 决定 sink
            # ================================================================
            model = YOLO(str(model_path))
            class_names: list[str] = list(model.names.values())

            do_beautify = beautify and pipe.viz_enabled
            visualizer: BeautifyVisualizer | None = None
            if do_beautify:
                visualizer = BeautifyVisualizer(
                    labels=class_names,
                    label_mapping=pipe.label_mapping or None,
                    color_mapping=pipe.color_mapping or None,
                    default_color=pipe.default_color,
                    font_path=pipe.font_path,
                )
            else:
                logger.info("美化已关闭, 使用 YOLO 原生 plot() 绘制.")

            # 输出根: runs/<task>_infer/<name> —— 跟训练 runs/<task>_train 对齐
            run_name = config.experiment_name or "predict"
            output_dir = _resolve_output_dir(
                RUNS_DIR / f"{config.task}_infer",
                run_name,
                exist_ok=bool(getattr(config, "exist_ok", False)),
            )
            logger.info(f"输出目录:    {output_dir}")

            # 逐帧 predict 计算参数 (白名单, 不盲传整个 config)
            predict_kwargs = {
                k: getattr(config, k)
                for k in _PREDICT_KEYS
                if getattr(config, k, None) is not None
            }
            predict_kwargs["verbose"] = False

            want_save = bool(getattr(config, "save", True))
            want_show = bool(getattr(config, "show", False))

            # ★ 决定 sink: 调用方没传 → 按 want_save 自动选 LocalFileSink / NullSink
            #   调用方传了 → 用调用方的 (此时 want_save 仅影响 pipeline 的派发策略)
            if output_sink is None:
                output_sink = LocalFileSink() if want_save else NullSink()
                _sink_owned = True
            else:
                _sink_owned = False
                logger.info(f"使用调用方提供的 sink: {output_sink.__class__.__name__}")

            # ================================================================
            # 阶段 5: 执行推理
            # ================================================================
            logger.info("=" * 60)
            logger.info("启动推理".center(60))
            logger.info("=" * 60)

            stats = InferStats()
            camera_cfg = pipe.build_camera_config()
            processor = _FrameProcessor(
                model=model,
                predict_kwargs=predict_kwargs,
                do_beautify=do_beautify,
                visualizer=visualizer,
                use_label_mapping=pipe.use_label_mapping,
                style_overrides=pipe.style_overrides,
                names=model.names,
            )

            raw_batch = getattr(config, "batch", 16)
            batch_size = raw_batch if isinstance(raw_batch, int) and raw_batch >= 1 else 16

            from .pipeline import ThreadedPipeline
            logger.info(f"执行引擎: 多线程流水线 (batch={batch_size}, 显示与主循环解耦)")
            pipeline = ThreadedPipeline(
                processor=processor,
                source=str(raw_source),
                camera_config=camera_cfg,
                output_dir=output_dir,
                output_sink=output_sink,
                batch_size=batch_size,
                save=want_save,
                show=want_show,
                show_info=show_info,
                window_name=window_name,
                warmup_frames=warmup_frames,
                hooks=hooks,
                cancel_token=cancel_token,
            )
            interrupted = pipeline.run(stats)

            if interrupted:
                logger.warning("推理被用户提前结束.")

            # ================================================================
            # 阶段 6: 推理统计
            # ================================================================
            logger.info("=" * 60)
            logger.info("推理完成".center(60))
            logger.info("=" * 60)
            log_infer_stats(stats, logger=logger)

            # ================================================================
            # 阶段 7: 整理输出
            # ================================================================
            model_stem = Path(raw_model).stem
            if rename_log:
                rename_log_to_save_dir(output_dir, model_stem)

            # ================================================================
            # 阶段 8: 审计快照
            # ================================================================
            audit_path: Path | None = output_dir / "odp_audit.json"
            log_path = _find_project_log_path()
            try:
                audit_payload = {
                    "mode": "infer",
                    "config": config.to_audit_snapshot(),
                    "merger": merger.to_audit_log(),
                    "pipeline": pipe.to_audit(),
                    "stats": stats.to_dict(),
                    "result_summary": {
                        "output_dir": str(output_dir),
                        "saved": want_save,
                        "beautified": do_beautify,
                        "infer_time_sec": (datetime.now() - start).total_seconds(),
                        "log_path": str(log_path) if log_path else None,
                    },
                }
                audit_path.write_text(
                    json.dumps(audit_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(f"审计快照:   {audit_path}")
            except OSError as e:
                logger.warning(f"写审计快照失败 (不影响推理结果): {e}")
                audit_path = None

            # ---- 收尾 ----
            infer_time = (datetime.now() - start).total_seconds()
            logger.info("=" * 60)
            logger.info(f"推理总耗时: {infer_time:.2f} 秒")
            logger.info(f"输出目录:   {output_dir}")
            if want_save:
                logger.info(f"结果已保存到上面的目录.")
            if log_path:
                logger.info(f"本次日志:   {log_path}")
            logger.info("=" * 60)

            result = InferResult(
                success=True,
                output_dir=output_dir,
                stats=stats.to_dict(),
                infer_time=infer_time,
                saved=want_save,
                audit_path=audit_path,
                log_path=log_path,
            )
            hooks.fire_complete(result)
            return result

        # ====================================================================
        # 顶层异常拦截 —— 永不抛, 打包成 InferResult.error
        # ====================================================================
        except Exception as e:
            logger.error(f"推理失败: {e}", exc_info=True)
            infer_time = (datetime.now() - start).total_seconds()
            hooks.fire_error(e)
            return InferResult(
                success=False,
                output_dir=output_dir or Path("unknown"),
                stats={},
                infer_time=infer_time,
                error=str(e),
                log_path=_find_project_log_path(),
            )


# ============================================================================
# 帧处理器 —— 把"推理"和"绘制"拆成两半, pipeline 共用
# ============================================================================
@dataclass
class _FrameProcessor:
    model: Any
    predict_kwargs: dict[str, Any]
    do_beautify: bool
    visualizer: BeautifyVisualizer | None
    use_label_mapping: bool
    style_overrides: dict[str, Any]
    names: dict[int, str]
    _style: DrawStyle | None = None

    def infer_batch(self, images: list):
        """主线程: 批量推理. 返回 (results, labels_list, n_list, batch_dt)."""
        t0 = time.perf_counter()
        results = self.model(images, **self.predict_kwargs)
        batch_dt = time.perf_counter() - t0
        labels_list: list[list[str]] = []
        n_list: list[int] = []
        for result in results:
            boxes = result.boxes
            n = 0 if boxes is None else len(boxes)
            n_list.append(n)
            labels_list.append(
                [self.names[i] for i in boxes.cls.int().cpu().tolist()] if n else []
            )
        return results, labels_list, n_list, batch_dt

    def draw(self, image, result, labels, n):
        """绘制单帧 → annotated(BGR). 美化关时退回 YOLO 原生 plot()."""
        if self.do_beautify and self.visualizer is not None:
            if self._style is None:
                h, w = image.shape[:2]
                self._style = DrawStyle.from_image_size(h, w, **self.style_overrides)
            boxes = result.boxes
            dets = BeautifyVisualizer.from_yolo_results(
                boxes=(boxes.xyxy.cpu().numpy() if n else _empty_boxes()),
                confidences=(boxes.conf.cpu().numpy() if n else _empty_conf()),
                labels=labels,
            )
            return self.visualizer.draw(
                image, dets, style=self._style, use_label_mapping=self.use_label_mapping,
            )
        return result.plot()


def _empty_boxes():
    import numpy as np
    return np.zeros((0, 4), dtype=float)


def _empty_conf():
    import numpy as np
    return np.zeros((0,), dtype=float)


def infer_yolo(
    yaml_path: str | Path | None = None,
    pipeline_yaml: str | Path | None = None,
    cli_args: dict[str, Any] | None = None,
    *,
    beautify: bool = True,
    rename_log: bool = True,
    threaded: bool = False,
    warmup_frames: int = 0,
    window_name: str = "odp-infer",
    show_info: bool = True,
    output_sink: OutputSink | None = None,
    hooks: InferHooks | None = None,
    cancel_token: CancelToken | None = None,
) -> InferResult:
    """一行启动推理 —— 风格跟 D5 build_infer_config / D6 train_yolo 一致."""
    service = InferService()
    return service.predict(
        yaml_path=yaml_path,
        pipeline_yaml=pipeline_yaml,
        cli_args=cli_args,
        beautify=beautify,
        rename_log=rename_log,
        threaded=threaded,
        warmup_frames=warmup_frames,
        window_name=window_name,
        show_info=show_info,
        output_sink=output_sink,
        hooks=hooks,
        cancel_token=cancel_token,
    )
```

## 8.13 git commit

```bash
git add apps/platform/src/odp_platform/inference/service.py
git commit -m "feat(D8): inference 子系统 service.py — InferService 编排 + 异常兜底

8 个阶段:
  1. 配置加载 (D5 + pipeline_config)
  2. 上下文日志 (设备 + 字段溯源)
  3. 源 + 模型解析
  4. 加载模型 + 美化器 + 输出目录 + 决定 sink
  5. 执行推理 (ThreadedPipeline.run)
  6. 推理统计
  7. 整理输出 (rename_log)
  8. 审计快照 (odp_audit.json)

★ 接缝集成:
- output_sink/hooks/cancel_token 三个 keyword-only Optional[None] 参数
- 默认 None → CLI 等价老式行为 (LocalFileSink / 空 hooks / 无 cancel)
- 业务方传 → 完全定制输出/事件/取消

★ 纪律 A 顶层兑现:
- 顶层 try/except 兜所有异常 → 打包成 InferResult.error
- hooks.fire_complete (成功) / hooks.fire_error (失败) 同步触发
- 调用方 0 try/except, exit code / UI 状态全看 result.success

★ predict() 9 个原参数 100% 向后兼容
  (顺序 + 默认值不变, 新参数全部 keyword-only + None default)"
```

至此 **推理引擎层 5 个文件全部完成** (pipeline_config + overlay + cancel + hooks + sinks + pipeline + service)。下一阶段把它装成 CLI 入口, 真正能 `odp-infer --source 0` 跑起来。

---
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 9: `__init__.py` + `cli/infer.py` — 装成对外可用的命令

8 个推理引擎文件已经齐了, 还差两件小事:

1. **`__init__.py`**:对外暴露干净的 API 面板, 业务方 `from odp_platform.inference import ...` 一行进所有有用的符号。
2. **`cli/infer.py`** + **`pyproject.toml` entry-point**:让用户能在 shell 直接 `odp-infer --source 0` 拉起推理, 不用敲 `python -m ...` 长串。

## 9.1 `__init__.py` — 对外面板

```python
# apps/platform/src/odp_platform/inference/__init__.py
"""ODPlatform 推理子系统对外面板.

业务方按需引入:
    from odp_platform.inference import infer_yolo                       # 一行启动
    from odp_platform.inference import InferService, InferResult, InferStats
    from odp_platform.inference import (
        OutputSink, LocalFileSink, NullSink,                            # 接缝 1
        InferHooks, FrameEvent, ProgressEvent,                          # 接缝 2
        CancelToken, InferenceCancelled,                                # 接缝 3
    )

★ 不导出 ThreadedPipeline / _Reader / _Renderer / _Display / _Controller / _FrameProcessor —
  那些是引擎内部细节, 外部不应该直接持有 (持有了一升级就坏).
"""
from .cancel import CancelToken, InferenceCancelled
from .hooks import FrameEvent, InferHooks, ProgressEvent
from .pipeline_config import PipelineConfig, load_pipeline_config
from .service import InferResult, InferService, InferStats, infer_yolo, log_infer_stats
from .sinks import LocalFileSink, NullSink, OutputSink

__all__ = [
    # 主入口 (跟 D6 train_yolo 平行)
    "infer_yolo",
    # Service / Result / Stats
    "InferService", "InferResult", "InferStats", "log_infer_stats",
    # 配置
    "PipelineConfig", "load_pipeline_config",
    # ★ 接缝 1: 输出
    "OutputSink", "LocalFileSink", "NullSink",
    # ★ 接缝 2: 事件
    "InferHooks", "FrameEvent", "ProgressEvent",
    # ★ 接缝 3: 取消
    "CancelToken", "InferenceCancelled",
]
```

### 9.1.1 为什么不直接 `from .pipeline import *`

业务方应该用 `infer_yolo()` 或 `InferService().predict()` 调推理, **不应该直接 new `ThreadedPipeline`**。原因:

- `ThreadedPipeline.__init__` 要 11 个 keyword-only 参数, 直接调容易传错
- `_FrameProcessor` / `_Reader` / `_Renderer` / `_Display` 是引擎内部协作的组件, 改它们的接口不应该影响业务方
- service 还做了配置加载 / 模型解析 / audit 等大量工作, 跳过 service 直接调 pipeline = **手工重新发明** D5 + 模型解析 + audit, **绕开纪律 B**

**只导出业务方真正需要的 11 个符号**, 内部实现留在模块里。改 `ThreadedPipeline` 的内部接口不破坏对外契约 — 这就是好的 API 面板的价值。

### 9.1.2 `__all__` 的另一个作用

设置 `__all__` 让 `from odp_platform.inference import *` 这种通配只拉这 11 个符号, 不会把 `time` `logging` 之类的间接导入污染进调用方的命名空间。

虽然我们不鼓励通配 import (PEP 8 也不鼓励), 但有 `__all__` 是"严肃 Python 包"的标志。

## 9.2 `cli/infer.py` — argparse + 转发到 `infer_yolo`

CLI 的职责:

1. 装 console + file logging handler (纪律 B: handler 唯一装配点)
2. 解析 `argparse` → 把 CLI 参数收集成 dict
3. **CLI 标志 → 推理参数** 的语义翻译 (例如 `--no-save` → `save: False`, `--no-show` → `show: False`)
4. 调 `infer_yolo(**...)` 跑
5. 根据 `result.success` 决定 exit code

**注意 CLI 完全不传 `output_sink / hooks / cancel_token`** — 走默认行为, 跟"没有接缝"的老式 CLI 100% 等价。这是接缝向后兼容性的最直接证据。

```python
# apps/platform/src/odp_platform/cli/infer.py
#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""ODPlatform odp-infer CLI 入口.

职责 (跟 odp-train 完全同构):
  1. 装 logging handler (D2 get_logger, console+file 两份)
  2. argparse → cli_args dict
  3. 调 infer_yolo() 跑
  4. 退出码: 0 成功, 1 失败 (CI 友好)

★ 不传任何接缝参数 → service 走默认 → 100% 等价老式 CLI 行为.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from odp_platform.common.logging_utils import get_logger
from odp_platform.inference import infer_yolo


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="odp-infer",
        description="ODPlatform YOLO 推理 CLI",
    )
    # ---- 输入输出 ----
    p.add_argument("--source", type=str, default=None,
                   help="输入源: 摄像头号(0/1) / 视频文件 / 图片或目录 / RTSP. 不传则用 infer.yaml.")
    p.add_argument("--model", type=str, default=None,
                   help="模型文件名 (best.pt / yolo11n.pt). 不传则用 infer.yaml.")
    p.add_argument("--yaml", type=str, default=None,
                   help="D5 infer.yaml 路径. 不传走默认.")
    p.add_argument("--pipeline-yaml", type=str, default=None,
                   help="帧源+美化 yaml 路径. 不传走默认 configs/runtime/infer_pipeline.yaml.")
    p.add_argument("--name", type=str, default=None, dest="experiment_name",
                   help="输出子目录名 (重复自增: predict / predict2 / ...).")

    # ---- 推理参数 ----
    p.add_argument("--conf", type=float, default=None, help="置信度阈值 (0~1).")
    p.add_argument("--iou",  type=float, default=None, help="NMS IoU 阈值 (0~1).")
    p.add_argument("--imgsz", type=int, default=None, help="推理输入尺寸.")
    p.add_argument("--max-det", type=int, default=None, dest="max_det", help="单图最大检测数.")
    p.add_argument("--classes", type=int, nargs="+", default=None, help="只保留这些类别 ID.")
    p.add_argument("--device", type=str, default=None, help="cpu / 0 / 0,1 / mps.")
    p.add_argument("--batch", type=int, default=None, help="批大小 (视频/图片夹).")

    # ---- 显示 / 存盘 ----
    g_show = p.add_mutually_exclusive_group()
    g_show.add_argument("--show", action="store_true", default=None, help="弹窗显示画面.")
    g_show.add_argument("--no-show", dest="show", action="store_false", help="关掉弹窗.")
    g_save = p.add_mutually_exclusive_group()
    g_save.add_argument("--save", action="store_true", default=None, help="结果存盘.")
    g_save.add_argument("--no-save", dest="save", action="store_false", help="不存盘.")
    p.add_argument("--no-viz", action="store_true", help="关掉美化, 用 YOLO 原生 plot().")
    p.add_argument("--no-hud", action="store_true", help="画面不叠 HUD 信息面板.")

    # ---- 其他 ----
    p.add_argument("--warmup", type=int, default=0,
                   help="启动丢弃前 N 帧 (摄像头帧率不稳).")
    p.add_argument("--log-level", type=str, default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="日志级别.")
    return p


def _ns_to_cli_args(ns: argparse.Namespace) -> dict:
    """argparse Namespace → cli_args dict (D5 merger 吃 dict).

    只放非 None 的字段, 让 D5 / pydantic 的 default 兜底.
    `--no-viz` / `--no-hud` / `--warmup` / `--yaml` / `--pipeline-yaml` / `--log-level`
    不进 cli_args (这些是 CLI 自己的行为开关, 不是 D5 配置字段).
    """
    keys = ("source", "model", "experiment_name",
            "conf", "iou", "imgsz", "max_det", "classes", "device", "batch",
            "show", "save")
    return {k: v for k in keys if (v := getattr(ns, k, None)) is not None}


def main(argv: list[str] | None = None) -> int:
    ns = _build_parser().parse_args(argv)

    # ★ 纪律 B: 整个进程里【唯一】装 handler 的地方
    get_logger(
        base_path=Path("logs"),
        log_type="infer",
        log_level=getattr(logging, ns.log_level),
    )

    cli_args = _ns_to_cli_args(ns)
    result = infer_yolo(
        yaml_path=ns.yaml,
        pipeline_yaml=ns.pipeline_yaml,
        cli_args=cli_args,
        beautify=(not ns.no_viz),
        show_info=(not ns.no_hud),
        warmup_frames=ns.warmup,
        # ★ 不传 output_sink / hooks / cancel_token → service 走默认 → 等价老式 CLI
    )

    if result.success:
        return 0
    sys.stderr.write(f"\n推理失败: {result.error}\n")
    if result.log_path:
        sys.stderr.write(f"详细日志见: {result.log_path}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

### 9.2.1 三个 CLI-only 标志, 不进 cli_args

`--no-viz` / `--no-hud` / `--warmup` 是 **CLI 自己的行为开关**, 它们不是 D5 配置字段, 所以**不能进 cli_args**(进了 D5 merger 会抛"未知字段")。它们直接传到 `infer_yolo(beautify=..., show_info=..., warmup_frames=...)`。

`--yaml` / `--pipeline-yaml` 同理 — 这是配置**文件路径**, 不是配置**字段**。

`--log-level` 也不进 — 这是 logging handler 装配参数, 是 CLI 进程的事。

### 9.2.2 mutually exclusive group — `--show` / `--no-show`

```python
g_show = p.add_mutually_exclusive_group()
g_show.add_argument("--show", action="store_true", default=None)
g_show.add_argument("--no-show", dest="show", action="store_false")
```

**为什么 `default=None` 而不是 `False`?** 因为我们要把"用户没传"跟"用户传了 `--no-show`"**区分开**:

- 用户没传 → `ns.show == None` → 不进 cli_args → D5 用 yaml 里的 `show:` 默认
- 用户传 `--show` → `ns.show == True` → 进 cli_args, 覆盖 yaml
- 用户传 `--no-show` → `ns.show == False` → 进 cli_args, 覆盖 yaml

这是 argparse 的标准坑, **`default=None` + 后续 if 过滤** 是唯一干净写法。

## 9.3 entry-point — `pyproject.toml` 注册 `odp-infer`

```toml
# apps/platform/pyproject.toml (片段)
[project.scripts]
odp-train = "odp_platform.cli.train:main"
odp-infer = "odp_platform.cli.infer:main"     # ← 新加这一行
```

`pip install -e .` 装一次, shell 就有 `odp-infer` 命令。在任何能 import 这个包的 venv 里直接用:

```bash
$ odp-infer --help
usage: odp-infer [-h] [--source SOURCE] [--model MODEL] [--yaml YAML] ...
```

## 9.4 一个历史问题: `--threaded` 还存在吗?

`service.predict()` 的签名里还有 `threaded=False` 这个参数, 但 CLI 里看不到对应的 `--threaded` 开关。**为什么?**

历史上有过"单线程" vs "多线程"两种引擎可选, 配 `--threaded` 切换。后来 `ThreadedPipeline` 稳定下来, **多线程成了唯一引擎** —— `threaded` 这个参数现在永远被忽略(`service.predict` 内部不分支)。

留着这个参数纯粹是 **API 兼容性** —— 已有调用方代码可能写了 `infer_yolo(threaded=True)`, 删掉会破坏它们。CLI 不暴露是因为新用户不应该看到这个无意义的开关。**老 API 入参保留 + 新 CLI 不暴露 = 兼容的同时不传染坏 API**。

将来某个版本如果决定彻底清理, 可以加 `DeprecationWarning` 走废弃流程。

## 9.5 git commit

```bash
git add apps/platform/src/odp_platform/inference/__init__.py
git add apps/platform/src/odp_platform/cli/infer.py
git add apps/platform/pyproject.toml
git commit -m "feat(D8): inference 子系统 __init__ + odp-infer CLI 入口

__init__.py 暴露 11 个对外符号 (含 3 个接缝),
不暴露 ThreadedPipeline / _Reader / _Renderer / _FrameProcessor 等内部细节.

cli/infer.py 完全转发到 infer_yolo, 不传接缝参数 → 等价老式 CLI 行为.

pyproject.toml entry-point: odp-infer = odp_platform.cli.infer:main

★ 验证 grep 守门:
  grep -rE 'import PyQt|import PySide|from fastapi|import celery' \\
       apps/platform/src/odp_platform/inference/
  → 0 输出 (纪律 D 兑现)"
```

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 10: 真机跑通 CLI

8 个文件 + CLI 入口 + entry-point 全齐了, 装好包 (`pip install -e apps/platform`) 后 `odp-infer` 应该能用。这一节走 **3 个最常见的源** + **审计快照解读** + **5 维 FPS 怎么看** + **常见错误排查**, 让你"跑过一次心里有底"。

## 10.1 准备

```bash
# 1. 装包 (一次性, 已装跳过)
pip install -e apps/platform

# 2. 准备一份最小 infer.yaml
mkdir -p configs/runtime
cat > configs/runtime/infer.yaml << 'YAML'
task: detect
model: yolo11n.pt    # 没有的话首跑会自动下载
source: null         # 用 --source 传, 或在这写
conf: 0.25
iou: 0.7
imgsz: 640
device: 0            # cpu / 0 / mps
save: true
show: false          # 默认不弹窗 (CI 友好), --show 显式开启
YAML

# 3. (可选) 准备 infer_pipeline.yaml 启用中文标签
# 用阶段 4.6 的模板, 复制到 configs/runtime/infer_pipeline.yaml
```

测试 entry-point 通了:

```bash
$ odp-infer --help
usage: odp-infer [-h] [--source SOURCE] ...
```

## 10.2 跑摄像头 (源类型 1)

```bash
odp-infer --source 0 --show
```

预期行为:

- 弹出 `odp-infer` 窗口, 显示实时画面
- 左上角 HUD 显示 5 维 FPS (capture / infer / render / loop / current)
- 检测到人/车/猫狗时框出来 (中文标签如果配了 label_mapping)
- 按 `空格` 暂停 → 画面动态叠 PAUSED 提示
- 再按 `空格` 恢复
- 按 `q` 或 `Esc` 退出 → 窗口关闭 + 终端输出统计

terminal 输出大概长这样:

```
============================================================
                  开始 YOLO 推理 (task=detect)
============================================================
任务类型:    detect
输入源(声明): '0'
模型(声明):  yolo11n.pt
设备:        cuda:0 (NVIDIA GeForce RTX 3060)
模型(解析):  /home/user/.../pretrained/yolo11n.pt
输出目录:    runs/detect_infer/predict
执行引擎: 多线程流水线 (batch=16, 显示与主循环解耦)
============================================================
                       推理完成
============================================================
处理帧数:   1834
检测总数:   5217
平均延迟:   12.83 ms/帧
帧率(FPS):  捕获 58.2 | 推理 70.1 | 渲染 51.9 | loop 60.5 | 当前 59.8
模型 speed(ms): 预处理 1.42 | 推理 8.10 | 后处理 2.14
各类别检测数:
    person               2840
    cup                  1102
    chair                ...
审计快照:   runs/detect_infer/predict/odp_audit.json
推理总耗时: 30.31 秒
输出目录:   runs/detect_infer/predict
本次日志:   runs/detect_infer/predict/odp-infer-...-yolo11n.log
============================================================
```

**关注 5 维 FPS 是不是接近 60**:

- `loop ≈ 60` = 整体跑出了摄像头的物理上限, **多线程吃满了**
- `infer 70` = GPU 还有冗余 (loop 受 capture/render 拖)
- `capture 58` = 摄像头给帧的速率, 跟 OBS 量出来差不多
- `render 51` = 美化绘制的速率, 比 loop 低正常 (renderer 在自己的线程, 不阻塞主流水)
- `current` ≈ `loop` 说明实时稳定无毛刺

如果你的 loop FPS 跟阶段 1 朴素脚本测出来差不多 (~25), 那一定有什么不对 — 走"常见错误"这一节排查。

## 10.3 跑视频文件 (源类型 2)

```bash
odp-infer --source demo.mp4
```

(默认不弹窗, 直接跑完存盘。要看实时画面加 `--show`。)

预期:

- 没有窗口 (CI / 远程跑得动)
- 终端有进度日志 (每 30 帧一行)
- 跑完输出统计 + 存盘到 `runs/detect_infer/predict/output.mp4`
- 时长约等于源视频时长 (主流水线吃满了 video 的解码速度, 1 倍速跑完)

如果想看实时画面 + 存盘两不误:

```bash
odp-infer --source demo.mp4 --show
```

**注意此时画面播放速度 = 实际处理速度, 不是 1 倍速** (无法控制视频解码节拍, 解码完一帧就处理一帧, 处理速度比视频源 fps 快就快放, 慢就慢放)。这是已知工程取舍 — "实时美化看效果" 跟 "1 倍速播放" 是相反诉求, 想要 1x 播放请用 VLC 看存好的 output.mp4。

## 10.4 跑图片文件夹 (源类型 3)

```bash
mkdir test_imgs
cp some/place/*.jpg test_imgs/

odp-infer --source ./test_imgs/
```

预期:

- 没有窗口
- 每张图推理一次 → 画好框 → 存到 `runs/detect_infer/predict/{name}.jpg`(同名)
- 终端输出整个文件夹的统计

**适合做"批量过一遍数据集看检测效果"的工作流** — 比手工一张张跑高效得多。

## 10.5 解读 `odp_audit.json`

打开 `runs/detect_infer/predict/odp_audit.json`:

```json
{
  "mode": "infer",
  "config": {
    "task": "detect",
    "model": "yolo11n.pt",
    "source": "0",
    "conf": 0.25,
    "iou": 0.7,
    "imgsz": 640,
    "device": 0,
    "save": true,
    "show": true,
    "..."
  },
  "merger": {
    "source": {"value": "0", "from": "cli"},
    "conf":   {"value": 0.25, "from": "yaml:infer.yaml"},
    "model":  {"value": "yolo11n.pt", "from": "yaml:infer.yaml"},
    "device": {"value": 0, "from": "yaml:infer.yaml"}
  },
  "pipeline": {
    "viz_enabled": true,
    "use_label_mapping": true,
    "label_mapping_n": 8,
    "color_mapping_n": 5,
    "camera": {"width": 1280, "height": 720, "fps": 30},
    "style_overrides_n": 0
  },
  "stats": {
    "frames": 1834,
    "detections": 5217,
    "per_class": {"person": 2840, "cup": 1102, ...},
    "infer_time_sec": 30.3098,
    "avg_fps": 60.51,
    "avg_latency_ms": 16.53,
    "fps": {
      "capture": 58.2, "infer": 70.1, "render": 51.9,
      "loop": 60.5,    "current": 59.8
    },
    "speed_ms": {"preprocess": 1.42, "inference": 8.10, "postprocess": 2.14}
  },
  "result_summary": {
    "output_dir": "runs/detect_infer/predict",
    "saved": true,
    "beautified": true,
    "infer_time_sec": 31.84,
    "log_path": "logs/odp-infer-2026-05-26-...-yolo11n.log"
  }
}
```

3 个最该看的字段:

- **`merger`**: 字段哪儿来的, 一目了然。论文复现 / 实验对比时关键。
- **`stats.fps`**: 5 维全在这, 找性能瓶颈不用翻日志。
- **`result_summary.log_path`**: 一年后想知道某次推理跑出来啥, 这是入口。

## 10.6 5 维 FPS 怎么看 —— 排查瓶颈

| 现象 | 瓶颈定位 | 解决方向 |
|---|---|---|
| 4 维都低 (loop, infer, capture, render 全 < 20) | CPU / GPU 整体不行 | 换更快机器, 或 `--imgsz 320` 缩小输入 |
| `capture` 远低于其他 (< 15) | **摄像头/视频源给帧慢** | 摄像头驱动问题; 视频源换更轻量 codec |
| `infer` 低 (< 30), 其他高 | **GPU 推理慢** | 换更小模型 (yolo11n → yolo11s 是反方向); 或 imgsz 缩小 |
| `render` 远低于其他 (< 20) | **绘制慢** (大画面 + 大量检测时常见) | `--no-viz` 退回原生 plot; 关 HUD `--no-hud` |
| `loop` 比 `capture` 低 | 整条流水有阻塞 | 通常是 in_q / out_q 派发被 sink 阻塞 (`--no-save` 排除) |
| `current` 远比 `loop` 抖 (相差 30+) | 偶发卡顿 (GC / 系统压力 / 驱动微卡) | 多跑几次取平均; 看系统资源监控 |

**论文里写 FPS 要写 5 个吗?** 不需要。**写 `loop` 是最诚实的** —— 它代表"用户实际看到的流畅度"。模型推理纸面 70 FPS 没用, 用户看到 30 卡 30 不卡, loop 才是真相。

## 10.7 常见错误排查

### 错误①: `RuntimeError: 未指定推理输入源`

```
推理失败: 未指定推理输入源. 请在 infer.yaml 写 source, 或用 `odp-infer --source <...>` 传入.
```

→ `infer.yaml` 里 `source: null` 且 CLI 没传 `--source`。**任何一个写**就行。

### 错误②: ImportError 关于 ultralytics

```
ImportError: ... ultralytics
```

→ 装 ultralytics: `pip install ultralytics`。

### 错误③: 摄像头打不开

```
ERROR: 推理失败: Could not open camera 0
```

→ Linux: 摄像头权限问题 (`sudo usermod -aG video $USER` 后重登录) 或被其他程序占用。
→ Mac: 系统设置 → 隐私 → 摄像头 → 给你的终端 / IDE 勾上。
→ Win: 设置 → 隐私 → 摄像头 → 允许应用访问。

### 错误④: CUDA out of memory

```
torch.cuda.OutOfMemoryError: CUDA out of memory.
```

→ batch_size 大了, `--batch 4`。
→ imgsz 大了, `--imgsz 416` 或 `320`。
→ 别的进程占了显存, `nvidia-smi` 看一下杀掉。

### 错误⑤: 跑视频跑完没存盘

预期 `runs/detect_infer/predict/output.mp4` 在, 但没有。

→ 看终端 / 日志有没有 `LocalFileSink.write 失败` 的 warning。
→ 检查 `output_dir` 是否有写权限。
→ `--no-save` 标志是不是不小心加了。

### 错误⑥: 弹窗没出来

跑 `--show` 但没窗口。

→ 远程 ssh 没装 X11 forwarding。本地跑或 `ssh -X` 。
→ Docker 容器没挂 `$DISPLAY`。
→ 终端被纯文本 SSH 攻击了 (笑)。无解, 改成存盘看回放。

### 错误⑦: 推理跑出来 5 帧 / 秒

`loop FPS ≈ 5`, 远不如朴素脚本 25。

→ 99% 是装在 CPU 上 `device: cpu`。改 `--device 0`(NVIDIA)或 `--device mps`(Mac)。
→ 或 imgsz 写成了 1280, 算力扛不住。改 `--imgsz 640` 或更小。

## 10.8 验证完整性

跑完上面 3 个源都 OK 之后, 整个 D8 推理子系统的 CLI 流程就**经过真机验证**。下一阶段把它套到桌面 GUI 上, **验证接缝设计真的让我们"零改动"换前端**。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 11: 桌面 demo 跑通 — 验证接缝隔离的价值

> 这一节做一件事:**用 PySide6 做一个最小的桌面 GUI, 通过接缝调用 `InferService.predict`, 不改 inference 任何代码就能在 Qt 窗口里看到推理画面**。
>
> 如果接缝设计成功, 这个 demo 应该:
> 1. **不修改 `apps/platform/src/odp_platform/inference/` 任何代码**
> 2. **跟 CLI 走同一个 InferService.predict**
> 3. **关键行为(60+ FPS、Stop 按钮 < 2s 响应、关窗不留僵尸)跟 CLI 一致**

## 11.1 工程结构

```
apps/desktop/                  ← 桌面端独立 app, 跟 platform 平级
├── qt_sink.py        ~75 行   ← OutputSink → Qt 信号桥
├── infer_worker.py  ~120 行   ← QObject + moveToThread, 在 QThread 里跑 service.predict
└── main.py          ~260 行   ← MainWindow + Browse 模型/源 + Start/Stop + QLabel 显示
```

**为什么选 PySide6 不选 PyQt6?** 因为:

- PySide6 的 License 是 LGPL, 商业项目用着更宽松
- PySide6 是 Qt Company 官方维护, API 最权威
- 两者 API 几乎完全一样, 切换成本几乎 0
- 公司既有桌面工具(原 yolo_server)走的就是 PySide6, 一致性

装一下:

```bash
pip install PySide6
```

## 11.2 关键设计: 3 个接缝在桌面端怎么用

回顾阶段 3.4 决策四的接缝表, 桌面端这一行是:

| 接缝 | 桌面端实现 |
|---|---|
| **`OutputSink`** | `QtSignalSink`(将 annotated 帧通过 Qt 信号发到 UI) |
| **`InferHooks`** | `InferHooks(on_progress=..., on_complete=..., on_error=...)` (更新状态栏 / 弹窗) |
| **`CancelToken`** | `CancelToken()`(GUI Stop 按钮 click → `token.cancel()`) |

3 个接缝合起来, **桌面端**:

- 不依赖 `cv2.imshow`(走 QLabel)
- 不依赖键盘按键退出(走 Stop 按钮)
- 实时画面流畅(QtSignalSink 通过 `Qt.QueuedConnection` 信号过线程, 主线程拿到帧直接 setPixmap)

## 11.3 设计点①: `QtSignalSink` — OutputSink → Qt 信号桥

QtSignalSink 既是个 `QObject`(能发信号)又是个 `OutputSink`(实现 open/write/close)。

```python
# apps/desktop/qt_sink.py
from __future__ import annotations

import logging
import numpy as np
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from odp_platform.frame_source import SourceType
from odp_platform.inference import OutputSink

logger = logging.getLogger(__name__)


class QtSignalSink(QObject, OutputSink):
    """OutputSink → Qt 信号桥.

    每帧推理完, 由 _Renderer 线程调 write(...) → 转成 Qt 信号
    → Qt 跨线程派发 (QueuedConnection) → 主线程 UI 槽函数 setPixmap.

    ★ Signal 用 object 而不是 np.ndarray:
       Qt 对 numpy 类型注册不一定可靠 (PySide6 不同版本行为不同),
       用 object 兜底, 槽函数自己 isinstance(frame, np.ndarray) 兜底验证.
    """

    frame_ready = Signal(object)        # 发: annotated (BGR, ndarray, contiguous)
    write_count = 0

    def __init__(self, parent: QObject | None = None) -> None:
        QObject.__init__(self, parent)
        OutputSink.__init__(self)

    # ---- OutputSink 三方法 ----
    def open(self, output_dir: Path, source_type: SourceType) -> None:
        logger.info(f"QtSignalSink.open: dir={output_dir}, source_type={source_type}")

    def write(self, frame, annotated: np.ndarray) -> None:
        try:
            # ★ 必须连续, QImage 直接拿底层 buffer 时不连续会乱
            if not annotated.flags["C_CONTIGUOUS"]:
                annotated = np.ascontiguousarray(annotated)
            self.frame_ready.emit(annotated)
            self.write_count += 1
            if self.write_count <= 3:
                logger.info(f"QtSignalSink.write[{self.write_count}]: "
                            f"shape={annotated.shape}, dtype={annotated.dtype}")
        except Exception as e:
            logger.warning(f"QtSignalSink.write 失败 (已吞): {e}")

    def close(self) -> None:
        logger.info(f"QtSignalSink.close: 共发了 {self.write_count} 帧")
```

**关键细节**:

- **多重继承 `QObject, OutputSink`**: 既能发 Qt 信号又是合法的 `OutputSink`。Python 的多重继承在这种"两个互不相干的接口"场景下用得很顺。
- **`Signal(object)` 不是 `Signal(np.ndarray)`**: PySide6 不同版本对 numpy 类型的注册行为不一定可靠, 用 object 是兜底。槽函数自己 `isinstance` 校验。
- **`np.ascontiguousarray` 兜底**: cv2 / 子区域切片 / `copy()` 出来的 ndarray 可能不连续, QImage 直接拿 buffer 会乱。这一行兜底防御。
- **前 3 帧打日志**: 诊断"画面没出来"时知道是 sink 没发还是 UI 没收。3 帧之后不打, 避免日志爆炸。
- **`write 永不抛`**: 跟 LocalFileSink 一样的纪律, 单帧失败 warning + 跳过, 不让推理死。

## 11.4 设计点②: `InferWorker` — QObject + moveToThread, 在 QThread 里跑 service

```python
# apps/desktop/infer_worker.py
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from odp_platform.inference import (
    CancelToken,
    FrameEvent,
    InferHooks,
    InferResult,
    ProgressEvent,
    infer_yolo,
)

logger = logging.getLogger(__name__)


class InferWorker(QObject):
    """跑 service.predict 的工作对象. 通过 moveToThread 放到 QThread 里.

    ★ 接缝集成:
      - sink         : 由 main 线程 new 后传进来 (Qt 信号必须在主线程构造), 见 main.py
      - cancel_token : 这里持有, GUI Stop 按钮 click → self.cancel_token.cancel()
      - hooks        : 在 start_infer 里组装, 把 service 事件转发成 Qt 信号
    """

    # 转 Qt 信号给 UI 监听
    progress_changed = Signal(int, int, float)            # frame_idx, total_frames|-1, fps_loop
    inference_finished = Signal(object)                    # InferResult
    inference_failed = Signal(str)                         # error message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cancel_token = CancelToken()
        self._sink = None                                  # 由 main 注入

    def set_sink(self, sink) -> None:
        """main 线程构造好 sink 后调 (sink 内部的 Signal 必须在主线程构造)."""
        self._sink = sink

    @Slot(str, str)
    def start_infer(self, model: str, source: str) -> None:
        """跑推理. 阻塞调用 (在 worker thread 里), 通过 hooks/signals 回报状态."""
        logger.info(f"InferWorker.start_infer: model={model}, source={source}")

        # 重置 cancel_token, 一个 worker 可以跑多次推理
        self.cancel_token = CancelToken()

        # ★ 组装 hooks: service 事件 → Qt 信号
        hooks = InferHooks(
            on_progress=self._on_progress,
            on_complete=self._on_complete,
            on_error=self._on_error,
            progress_interval_frames=15,        # 每 15 帧推一次 (~0.5 秒, 桌面 UI 不需要更频)
        )

        try:
            result: InferResult = infer_yolo(
                cli_args={
                    "source": source,
                    "model": model,
                    "show": False,              # 桌面端不要 cv2.imshow
                    "save": False,              # annotated 已通过 sink 给 UI 了, 不需要本地副本
                },
                output_sink=self._sink,
                hooks=hooks,
                cancel_token=self.cancel_token,
            )
            # service 永不抛, 所以这里只可能是正常返回
            # on_complete 已经在 hooks 里 emit 过了, 这里不重复
            logger.info(f"InferWorker 推理结束: success={result.success}")
        except Exception as e:
            # 兜底防御: 万一 service 哪天破纪律抛了
            logger.error(f"InferWorker 捕获到 service 异常: {e}", exc_info=True)
            self.inference_failed.emit(str(e))

    @Slot()
    def cancel(self) -> None:
        """GUI Stop 按钮 → 触发取消信号."""
        logger.info("InferWorker.cancel: 发取消信号 (< 2s 内 pipeline 会响应)")
        self.cancel_token.cancel()

    # ---- hooks → Qt 信号 ----
    def _on_progress(self, evt: ProgressEvent) -> None:
        total = evt.total_frames if evt.total_frames is not None else -1
        self.progress_changed.emit(evt.frame_idx, total, evt.fps_loop)

    def _on_complete(self, result: InferResult) -> None:
        self.inference_finished.emit(result)

    def _on_error(self, exc: Exception) -> None:
        self.inference_failed.emit(str(exc))
```

**几个关键设计 (容易踩坑的地方)**:

### 11.4.1 sink 由 main 线程构造, 通过 `set_sink` 注入

为什么 sink **不在 InferWorker 里 new**?

因为 `QtSignalSink` 是个 `QObject`, Qt 强制要求 QObject 在它**所属线程**里构造。Worker 已经被 `moveToThread(worker_thread)` 了, 在 worker 里 `QtSignalSink()` 会让 sink 属于 worker_thread。然后 sink 的 `frame_ready` 信号 emit 时, 跨线程到 main 槽函数 — Qt 自动用 `QueuedConnection`(没问题)。

**但是**, 如果 worker 没启动就 `QtSignalSink()`, 它属于 main thread。然后 `inference_thread.start()` 之后, sink 还在 main, worker 在 inference_thread。 worker 调 `sink.frame_ready.emit(...)` 走的是**worker thread → main thread**的 QueuedConnection — 这正是我们想要的!

**结论**: sink 在 **main 线程构造**, 通过 `worker.set_sink(sink)` 注入。这样它的 frame_ready 信号 emit 永远是 worker thread → main thread, 跨线程派发由 Qt 自动处理。

### 11.4.2 不在 InferWorker 里转发 sink.frame_ready

老式做法可能想这么写:

```python
# ❌ 反例: signal-to-signal 转发
class InferWorker(QObject):
    frame_ready = Signal(object)
    def __init__(self):
        self.sink = QtSignalSink()
        self.sink.frame_ready.connect(self.frame_ready)
```

让 worker 也暴露一个 `frame_ready`, 把 sink 的信号转发给它。**这是个坑** —— Qt 跨线程 signal-to-signal 转发的执行线程语义不直观, 容易出"帧没到 UI"的诡异 bug。

**正解**: 不转发。**让 UI 直接 connect sink 的信号**。main.py 里这样写:

```python
self.sink = QtSignalSink()
self.sink.frame_ready.connect(self._on_frame)     # ← UI 直接听 sink
self.worker.set_sink(self.sink)                    # ← 把 sink 给 worker
```

UI 直接 connect sink, 一条信号链:**sink (worker thread emit) → main thread _on_frame (QueuedConnection)**。简单, 可靠。

### 11.4.3 `cancel_token` 每次 start_infer 重置

一个 InferWorker 实例可以跑**多次**推理(用户点 Start → 跑完 → 再点 Start)。如果用同一个 `CancelToken`, **第二次推理一启动就被取消**(token 还记得上次的 cancel 状态)。

修复: `start_infer` 第一行 `self.cancel_token = CancelToken()` 重新 new 一个。

`worker.cancel()` 调的是 `self.cancel_token.cancel()`, 取的总是最新的实例 — 没问题。

## 11.5 完整代码:`apps/desktop/main.py`

```python
# apps/desktop/main.py
#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""ODPlatform Desktop demo (PySide6).

验证 D8 接缝设计:
- 不修改 inference/ 任何代码
- 通过 QtSignalSink / InferHooks / CancelToken 三个接缝跟 InferService 集成
- UI 不冻 (推理跑在 QThread)
- Stop < 2s 响应 (CancelToken 4 个查询点)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QStatusBar, QVBoxLayout, QWidget,
)

# 让 desktop app 能 import platform 包 (monorepo 跑法, 见 README)
THIS = Path(__file__).resolve()
sys.path.insert(0, str(THIS.parents[1] / "platform" / "src"))

from infer_worker import InferWorker
from qt_sink import QtSignalSink

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("desktop")


class MainWindow(QMainWindow):
    """最小桌面 demo:
      - 模型 / 源 两个文本框 + Browse 按钮
      - Start / Stop 按钮
      - 实时画面 QLabel
      - 进度条 + 状态栏
    """

    request_start = Signal(str, str)    # model_path, source

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ODPlatform Desktop Demo")
        self.resize(1280, 800)
        self._build_ui()
        self._build_worker()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        v = QVBoxLayout(central)

        # 模型行
        row_model = QHBoxLayout()
        row_model.addWidget(QLabel("Model:"))
        self.le_model = QLineEdit("yolo11n.pt")
        row_model.addWidget(self.le_model, 1)
        btn_browse_model = QPushButton("Browse...")
        btn_browse_model.clicked.connect(self._browse_model)
        row_model.addWidget(btn_browse_model)
        v.addLayout(row_model)

        # 源行
        row_src = QHBoxLayout()
        row_src.addWidget(QLabel("Source:"))
        self.le_source = QLineEdit("0")
        self.le_source.setPlaceholderText("摄像头号 (0/1...) 或 视频文件路径 或 图片目录")
        row_src.addWidget(self.le_source, 1)
        btn_browse_src = QPushButton("Browse...")
        btn_browse_src.clicked.connect(self._browse_source)
        row_src.addWidget(btn_browse_src)
        v.addLayout(row_src)

        # Start / Stop 行
        row_btn = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        row_btn.addWidget(self.btn_start)
        row_btn.addWidget(self.btn_stop)
        v.addLayout(row_btn)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)           # 启动时 indeterminate
        self.progress.setVisible(False)
        v.addWidget(self.progress)

        # 画面区
        self.video_label = QLabel("[ 点 Start 开始推理 ]")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background-color: #222; color: #888; font-size: 16px;")
        self.video_label.setMinimumHeight(480)
        v.addWidget(self.video_label, 1)

        # 状态栏
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

    def _build_worker(self) -> None:
        """构造 worker thread 和 sink (sink 在 main 线程 new)."""
        self.worker_thread = QThread(self)
        self.worker = InferWorker()
        self.worker.moveToThread(self.worker_thread)

        # ★ 关键: sink 在主线程 new, 直接 connect _on_frame
        #   (signal 跨线程 emit 时 Qt 自动用 QueuedConnection 派发回主线程)
        self.sink = QtSignalSink()
        self.sink.frame_ready.connect(self._on_frame, Qt.QueuedConnection)
        self.worker.set_sink(self.sink)

        # 信号路由
        self.request_start.connect(self.worker.start_infer)
        self.worker.progress_changed.connect(self._on_progress)
        self.worker.inference_finished.connect(self._on_finished)
        self.worker.inference_failed.connect(self._on_failed)

        self.worker_thread.start()
        logger.info("worker thread 启动完成")

    # ---- 按钮 ----
    def _browse_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择模型文件", "", "PyTorch 模型 (*.pt *.pth);;所有文件 (*)"
        )
        if path:
            self.le_model.setText(path)

    def _browse_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频/图片文件", "",
            "视频/图片 (*.mp4 *.avi *.mov *.mkv *.jpg *.jpeg *.png);;所有文件 (*)"
        )
        if path:
            self.le_source.setText(path)

    def _on_start(self) -> None:
        model = self.le_model.text().strip()
        source = self.le_source.text().strip()
        if not model or not source:
            QMessageBox.warning(self, "缺少参数", "请填写模型和源.")
            return
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setVisible(True)
        self.statusBar().showMessage(f"启动推理: model={model}, source={source}")
        logger.info(f"发送 start_infer 信号: model={model}, source={source}")
        self.request_start.emit(model, source)

    def _on_stop(self) -> None:
        self.statusBar().showMessage("Stop 按下, 等待 pipeline 响应 (< 2s)...")
        logger.info("用户点 Stop, 调 worker.cancel()")
        self.worker.cancel()
        self.btn_stop.setEnabled(False)

    # ---- worker → UI 槽函数 (在主线程跑) ----
    def _on_frame(self, annotated) -> None:
        """sink 发来一帧 annotated, 显示到 QLabel."""
        # 兜底校验
        if not isinstance(annotated, np.ndarray):
            logger.warning(f"_on_frame 收到非 ndarray: {type(annotated)}")
            return
        if annotated.ndim != 3 or annotated.shape[2] != 3:
            logger.warning(f"_on_frame 收到非 BGR ndarray: shape={annotated.shape}")
            return
        try:
            h, w, _ = annotated.shape
            # BGR → RGB (cv2 默认 BGR, QImage 要 RGB)
            rgb = annotated[..., ::-1]
            if not rgb.flags["C_CONTIGUOUS"]:
                rgb = np.ascontiguousarray(rgb)
            qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
            pix = QPixmap.fromImage(qimg).scaled(
                self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.video_label.setPixmap(pix)
        except Exception as e:
            logger.exception(f"_on_frame 显示失败: {e}")

    def _on_progress(self, frame_idx: int, total: int, fps_loop: float) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(frame_idx)
        self.statusBar().showMessage(f"帧 {frame_idx}/{total if total > 0 else '?'} | loop {fps_loop:.1f} FPS")

    def _on_finished(self, result) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)
        if result.success:
            stats = result.stats or {}
            msg = (f"✅ 完成 {stats.get('frames', '?')} 帧, "
                   f"检测 {stats.get('detections', '?')} 个, "
                   f"耗时 {result.infer_time:.1f}s, "
                   f"loop {stats.get('fps', {}).get('loop', '?')} FPS")
            self.statusBar().showMessage(msg)
        else:
            self.statusBar().showMessage(f"❌ 失败: {result.error}")
            QMessageBox.critical(self, "推理失败", result.error or "未知错误")

    def _on_failed(self, error: str) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)
        self.statusBar().showMessage(f"❌ 失败: {error}")
        QMessageBox.critical(self, "推理失败", error)

    def closeEvent(self, event) -> None:
        """关窗时优雅停掉 worker thread, 不留僵尸."""
        logger.info("关闭窗口, 先 cancel 推理再关 worker thread")
        try:
            self.worker.cancel()
        except Exception:
            pass
        self.worker_thread.quit()
        if not self.worker_thread.wait(3000):
            logger.warning("worker thread 3s 没退, 强终止")
            self.worker_thread.terminate()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
```

## 11.6 跑起来

monorepo 模式从仓库根目录跑(让 `apps/desktop/main.py` 能找到 `apps/platform/src/`):

```bash
$ python apps/desktop/main.py
```

预期顺序:

1. 窗口弹出, Model 默认 `yolo11n.pt`, Source 默认 `0`
2. (可选) 点 Browse 选模型 / 选源
3. 点 **Start** → 状态栏 "启动推理...", 一两秒后画面开始流, 进度条动
4. 状态栏滚动 "帧 N/? | loop XX.X FPS"
5. 点 **Stop** → 状态栏 "等待 pipeline 响应..." → < 2 秒画面停 + 状态栏显示成功统计
6. 再点 **Start** → 可以重新跑 (worker 复用)
7. 直接 **关窗** → 进程退出, 不留僵尸

## 11.7 ★ 4 个验证观察点

接缝设计成功的标志, 重点观察这 4 件事:

### 观察 1: 推理跑的时候 UI 不冻

拖窗口、放大缩小、点其他按钮 —— 全部流畅。如果冻了, 说明推理跑在了 main thread (没 moveToThread), 立刻看 `InferWorker.__init__` 和 `moveToThread` 那行。

### 观察 2: 点 Stop 后 < 2 秒画面停

如果 Stop 后画面继续跑 5+ 秒, 说明 cancel_token 没起作用。可能:

- worker 把 cancel_token 传给 service 时漏了 (`infer_yolo(..., cancel_token=...)` 检查)
- pipeline 的 4 个查询点被改坏了 (`grep _is_cancelled apps/platform/.../pipeline.py` 应该有 3+ 处)

### 观察 3: 跟 CLI 跑同样的源 FPS 接近

终端跑 `odp-infer --source 0 --show` 看 loop FPS, 桌面跑同源看状态栏的 loop FPS。**两者应该差不多** (桌面端 sink → Qt 信号 → QLabel 比 `cv2.imshow` 略重, 但差距 5 FPS 以内)。

如果桌面端 FPS 远低于 CLI (差 30+), 看:

- `QtSignalSink.frame_ready` 是不是 `QueuedConnection` (默认就是, 但显式写更安全)
- `_on_frame` 的 BGR→RGB / setPixmap 是不是太慢 (大画面 + scaled SmoothTransformation 会比较吃 CPU, 改成 FastTransformation 试试)

### 观察 4: 直接 X 关窗, 进程退出, 不留僵尸

`ps aux | grep python` 看一下窗口关后还有没有 python 进程。如果有:

- `closeEvent` 里的 `cancel + quit + wait` 链条某一环没起作用
- 看 main 的 `closeEvent` 有没有被定义 (没定义 Qt 默认行为是直接退, worker thread 可能没收到信号)

## 11.8 CLI vs 桌面 — 行为对照表

| 行为 | CLI | 桌面端 |
|---|---|---|
| 引擎模块导入 | `from odp_platform.inference import infer_yolo` | 同左 (一行不改) |
| 退出方式 | 按 q/Esc | 点 Stop 按钮 |
| 暂停 | 按空格 | (未实现, 接缝支持但 UI 没做按钮) |
| 显示 | cv2.imshow | QLabel + Pixmap |
| 输出 | LocalFileSink → output.mp4 | QtSignalSink → UI 流, 本地不存 |
| 进度反馈 | terminal 日志 | 状态栏 + 进度条 |
| 错误 | exit code 1 + stderr | QMessageBox 弹窗 |
| 推理子系统代码 | 一字不改 | **一字不改** |

最后一行是这一章的论文级 punchline:**两个完全不同的前端, 0 行 inference 代码改动**。

## 11.9 git commit

```bash
git add apps/desktop/qt_sink.py
git add apps/desktop/infer_worker.py
git add apps/desktop/main.py
git commit -m "feat(D8): apps/desktop demo — PySide6 桌面前端验证接缝隔离

3 个文件 ~460 行, 通过 3 个接缝消费推理引擎, 不改 inference/ 任何代码:
- QtSignalSink (OutputSink → Qt 信号桥), 主线程 new + worker.set_sink 注入
- InferWorker (QObject + moveToThread), hooks 转发成 Qt 信号
- MainWindow + Start/Stop/Browse + QLabel 显示

关键设计:
- sink 在主线程构造 (Qt 信号必须在主线程 emit)
- UI 直接 connect sink.frame_ready, 不通过 worker signal-to-signal 转发
- 每次 start_infer 重置 cancel_token (worker 可复用多轮推理)
- QImage 走 BGR→RGB + ascontiguousarray 防御不连续 buffer
- closeEvent 链条: worker.cancel → thread.quit → wait 3s → terminate

验证 4 观察点:
1. UI 不冻 (推理在 worker thread)
2. Stop < 2s 响应 (pipeline 4 个 cancel 查询点)
3. FPS 跟 CLI 一致 (差距 < 5)
4. 关窗不留僵尸"
```

---
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 阶段 12: 总结 — 6 条纪律 + 8 个 commit 终态 + 一句话

走完 11 阶段, 我们建好了一个能跑摄像头 60+ FPS 实时检测 + 视频/图片批处理 + 桌面 GUI 复用同引擎的推理子系统。回头看看, 收获了**6 条贯穿全文的纪律**。

## 12.1 6 条纪律重申

### 纪律 1: pipeline 永不抛、service 永不抛

四层兜底:

| 层 | 兑现位 | 失败时怎么走 |
|---|---|---|
| **service** | `predict()` 顶层 try/except | 打包成 `InferResult(success=False, error=str(e))` |
| **pipeline** | `_Reader.run` / `_Renderer.run` / `_Display.run` 各有 try | reader 异常装 `self.error` 主线程读; renderer 单帧失败 warn+跳 |
| **sink** | `LocalFileSink.write` 内部 try | warning + 跳过这一帧 |
| **hooks** | `fire_frame / fire_progress / fire_complete / fire_error` 全包 try | warning + 吞掉, 不让业务 bug 杀推理 |

**调用方 (CLI 或桌面 GUI) 永远只看 `result.success` 决定后续行为, 不需要 try/except 包 `predict()`**。

### 纪律 2: handler 唯一装配点 — CLI / GUI main

整个推理子系统:

- `service.py` / `pipeline.py` / `overlay.py` / `sinks.py` / `hooks.py` / `cancel.py` / `pipeline_config.py` — **0 处** `logging.basicConfig` / `addHandler`
- 所有模块只 `logger = logging.getLogger(__name__)` + `logger.info(...)`
- 装 handler **唯一**两处:
  - `apps/platform/src/odp_platform/cli/infer.py` → `get_logger(...)`
  - `apps/desktop/main.py` → `logging.basicConfig(...)`

库不污染调用方 logging。grep 验证:

```bash
grep -rE "basicConfig|addHandler|FileHandler|StreamHandler" \
     apps/platform/src/odp_platform/inference/
# → 0 输出
```

### 纪律 3: 主线程不碰 GUI

`cv2.imshow / waitKey / pollKey / destroyAllWindows` **只在** `pipeline._Display` 一个文件里出现。grep 验证:

```bash
grep -rE "cv2\.(imshow|waitKey|pollKey|destroyAllWindows)" \
     apps/platform/src/odp_platform/
# → 应该只匹配 pipeline.py 的 _Display 类
```

桌面 GUI 模式下 _Display 不启动(`want_show=False`), 走 `QtSignalSink` 跟 `QLabel`。

### 纪律 4: ★ 业务无感知的接缝

推理子系统**不依赖任何前端框架**:

```bash
grep -rE "import PyQt|import PySide|from fastapi|import celery" \
     apps/platform/src/odp_platform/inference/
# → 0 输出
```

业务方通过 3 个接缝接入:

- `OutputSink` — 输出去哪儿
- `InferHooks` — 进度 / 事件回调
- `CancelToken` — 程序化取消

CLI / 桌面 / Web / Celery 共用同一个 `InferService.predict`, 0 行 inference 代码改动。

### 纪律 5: 缓冲策略矩阵, 三处一致兑现

`save` 标志驱动**全局策略**, 3 个队列同时按它走:

| 队列 | save=True (文件源, 完整优先) | save=False (相机, 低延迟优先) |
|---|---|---|
| `reader.q` | `_put_block` 阻塞不丢 | maxsize=1 + `_put_latest` 丢旧 |
| `in_q` | `_put_block` 阻塞不丢 | `_put_latest` 丢旧 |
| `out_q` | `_put_block` 阻塞不丢 | `_put_latest` 丢旧 |

策略 SSoT 在 `ThreadedPipeline.run()` 顶部, 后面 3 处队列推送各自正确 dispatch。

### 纪律 6: loop FPS 批级测量

```python
# ❌ 反例: 批内 for 内逐帧 update → 滑动窗口被几微秒污染
for frame in batch:
    m.loop.update(now - last_loop_t)

# ✅ 正解: 批末算一次, update batch_size 次填窗口
batch_end_t = time.perf_counter()
if last_batch_end_t is not None:
    per_frame_loop_ms = (batch_end_t - last_batch_end_t) * 1000 / len(batch)
    for _ in batch:
        m.loop.update(per_frame_loop_ms)
last_batch_end_t = batch_end_t
```

每个滑动窗口样本都是合理的"单帧均摊时间", `loop.fps` 反映真实端到端吞吐。

## 12.2 8 个 git commit 终态清单

按时间顺序回看走过的 commit:

```
1. feat(D8): inference 子系统 pipeline_config.py
2. feat(D8): inference 子系统 overlay.py
3. feat(D8): inference 接缝层 — sinks/hooks/cancel 三个抽象
4. feat(D8): inference 子系统 pipeline.py — 四级多线程流水线
5. feat(D8): inference 子系统 service.py — InferService 编排 + 异常兜底
6. feat(D8): inference 子系统 __init__ + odp-infer CLI 入口
7. feat(D8): apps/desktop demo — PySide6 桌面前端验证接缝隔离
8. (本节预留) docs(D8): 教学讲义 d8_inference.md
```

跑 `git log --oneline -- apps/platform/src/odp_platform/inference/` 应该看到前 6 个; `git log --oneline -- apps/desktop/` 看到第 7 个。

## 12.3 一句话总结

> D8 的核心不是"多线程流水线", 是**"接缝设计让推理引擎成为一个真正可复用的库"**。多线程是手段, 接缝是目的。
>
> 你现在有了一个能服务 CLI / 桌面 / Web / Celery 的推理子系统, 推理子系统对它们一无所知 —— 这就是好抽象的标志。

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 附录 A: 文件路径总览

## A.1 推理引擎层 (apps/platform/src/odp_platform/inference/)

| 文件 | 行数 | 阶段 | 职责 |
|---|---|---|---|
| `pipeline_config.py` | 134 | 4 | 装 D5 管不到的帧源 + 美化嵌套配置 |
| `overlay.py` | 183 | 5 | 5 维 FPS 测量 + HUD 画面叠加 |
| `cancel.py` | 52 | 6 | `CancelToken` (程序化取消) |
| `hooks.py` | 99 | 6 | `InferHooks` (生命周期回调) |
| `sinks.py` | 146 | 6 | `OutputSink` ABC + `LocalFileSink` + `NullSink` |
| `pipeline.py` | 486 | 7 | 四级多线程流水线 (核心) |
| `service.py` | 526 | 8 | `InferService` 编排 + 异常兜底 |
| `__init__.py` | 45 | 9 | 对外面板 (11 个符号) |
| **合计** | **1671** | | |

## A.2 CLI 层 (apps/platform/src/odp_platform/cli/)

| 文件 | 行数 | 阶段 | 职责 |
|---|---|---|---|
| `infer.py` | ~180 | 9 | `odp-infer` argparse → infer_yolo 转发 |

## A.3 配置 (configs/runtime/)

| 文件 | 行数 | 阶段 | 职责 |
|---|---|---|---|
| `infer.yaml` | ~10 | 10 | D5 推理参数 (扁平, 自动生成 + 手填) |
| `infer_pipeline.yaml` | ~50 | 4 | 帧源 + 美化 (嵌套, 全手写) |

## A.4 桌面 demo (apps/desktop/)

| 文件 | 行数 | 阶段 | 职责 |
|---|---|---|---|
| `qt_sink.py` | ~75 | 11 | `OutputSink` → Qt `Signal` 桥 |
| `infer_worker.py` | ~120 | 11 | `QObject + moveToThread` 跑 InferService |
| `main.py` | ~260 | 11 | `MainWindow` + Browse + Start/Stop + QLabel |
| **合计** | **~455** | | |

---

# 附录 B: 自查清单 (跑完本章后, 学生应该能勾完所有项)

## B.1 概念关

- [ ] 能解释"为什么训练单线程够用, 推理必须多线程"
- [ ] 能解释 GIL, 知道"为什么 D8 多线程能加速"(因为 cv2 / pytorch / numpy 都释放 GIL)
- [ ] 能解释为什么"按职责切线程"比"按数据切线程"对
- [ ] 能解释为什么"GPU 那条线必须挂主线程"
- [ ] 能解释为什么"线程间用 queue.Queue + 哨兵"
- [ ] 能解释"接缝隔离"解决什么问题, 为什么不能在 pipeline 里 `import PySide6`

## B.2 代码关

- [ ] 能背出 `OutputSink` 的 3 个方法签名 (`open / write / close`)
- [ ] 能背出 `InferHooks` 的 4 个回调时机
- [ ] 能背出 4 个 cancel 查询点的位置, 知道为什么是这 4 个
- [ ] 能解释"批级 loop FPS 测量"的写法, 知道为什么不能批内逐帧 update
- [ ] 能解释 `_put_latest` 跟 `_put_block` 的差异, 知道什么场景用哪个
- [ ] 能解释 sink 为什么不在 `__init__` 立即初始化, 要推到 `open` 里
- [ ] 能解释为什么 hooks 的 `fire_*` 必须用 try/except 吞业务异常

## B.3 工程关

- [ ] 能跑通 `odp-infer --source 0 --show` 看到摄像头实时检测
- [ ] 能跑通 `odp-infer --source demo.mp4` 看到 output.mp4 生成
- [ ] 能跑通 `odp-infer --source ./images/` 看到每张图对应的 .jpg
- [ ] 能跑通 `python apps/desktop/main.py` 看到桌面 GUI 推理画面
- [ ] 能在桌面 demo 上点 Stop 看到 < 2 秒画面停 (验证 cancel)
- [ ] 能打开 `odp_audit.json` 看懂 5 维 FPS、字段溯源、模型 speed
- [ ] 能用 grep 验证 4 条边界纪律全部成立

## B.4 排查关

- [ ] 知道 loop FPS 突然飙到 1000+ 应该看哪儿 (批级测量被回归成批内逐帧了)
- [ ] 知道桌面端 UI 冻了应该看哪儿 (推理跑在 main thread, 没 moveToThread)
- [ ] 知道桌面端关窗后留僵尸应该看哪儿 (`closeEvent` 没定义或 `worker_thread.wait` 没生效)
- [ ] 知道写盘视频时长比源短应该看哪儿 (`LocalFileSink` 用了源 fps 而不是实际消费 fps, 已知工程取舍)
- [ ] 知道 sink.write 失败 (磁盘满) 不应该让推理死 — 这是设计目标, 看 warning 日志

---

# 附录 C: 下一步可以做什么

D8 完成后, 这套推理子系统已经能服务:

- ✅ CLI: `odp-infer`
- ✅ 桌面: `apps/desktop`
- 🔜 Web 后端: 阶段 11 验证了接缝可行, 但 `apps/web-backend` 还没建
- 🔜 异步任务: 同上, Celery 集成是后续工作

## C.1 后续工作 1: `apps/web-backend` (FastAPI + WebSocket)

按照 D8 接缝设计, 实现一个 `WebSocketSink`:

```python
class WebSocketSink(OutputSink, QObject if False else object):
    """WebSocket 输出 sink. 把 annotated 帧 jpg 编码后通过 ws 实时推."""

    def __init__(self, websocket):
        self._ws = websocket
        self._closed = False

    def open(self, output_dir, source_type):
        pass

    def write(self, frame, annotated):
        if self._closed:
            return
        import cv2, asyncio
        _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
        try:
            asyncio.run_coroutine_threadsafe(
                self._ws.send_bytes(buf.tobytes()), self._loop,
            )
        except Exception as e:
            logger.warning(f"WebSocketSink.write 失败 (已吞): {e}")

    def close(self):
        self._closed = True
```

配合 `CancelToken` 跟 WebSocket disconnect 事件绑定, FastAPI handler 大致这样:

```python
@app.websocket("/infer")
async def ws_infer(ws: WebSocket):
    await ws.accept()
    token = CancelToken()
    sink = WebSocketSink(ws)

    # 让 disconnect 触发 cancel
    async def watch_disconnect():
        try:
            await ws.receive_text()    # 阻塞等 client 发任何东西 (包括 close)
        except WebSocketDisconnect:
            token.cancel()
    asyncio.create_task(watch_disconnect())

    # 推理在另一个线程跑
    await asyncio.to_thread(
        infer_yolo,
        cli_args={"source": "0"},
        output_sink=sink,
        cancel_token=token,
    )
```

**整个 Web 后端集成大概 50 行代码**(主要是 FastAPI 模板代码), inference 子系统**一行不改**。

## C.2 后续工作 2: Celery 异步推理任务

```python
@celery_app.task(bind=True)
def infer_task(self, source: str, model: str):
    token = CancelToken()

    def watch_revoke():
        while not token.is_cancelled():
            if self.is_revoked():
                token.cancel(); return
            time.sleep(1.0)
    threading.Thread(target=watch_revoke, daemon=True).start()

    hooks = InferHooks(
        on_progress=lambda e: self.update_state(
            state="PROGRESS",
            meta={"frame": e.frame_idx, "fps": e.fps_loop},
        ),
    )
    result = infer_yolo(
        cli_args={"source": source, "model": model},
        output_sink=NullSink(),     # 异步任务不要画面, 只要 stats
        hooks=hooks,
        cancel_token=token,
    )
    return {"success": result.success, "stats": result.stats, "error": result.error}
```

跟 Web / 桌面**完全相同的接缝调用模式**, 只是把"消费方"换了一拨人。

## C.3 后续工作 3: 性能优化 (如果还需要)

D8 现状: yolo11n + 720p 摄像头 + RTX 3060 跑 60+ FPS, **绝大多数实时场景够用**。

如果还要更高:

- **TensorRT 导出**: `model.export(format="engine")` → load 后推理速度 ~2-3x。需要 ultralytics + TensorRT 的版本对得上。
- **更小的 imgsz**: `--imgsz 416` 或 `--imgsz 320`, 但 mAP 会掉。
- **batch=16 跑 IP 摄像头流**: 摄像头 IP 流多路汇集到一个推理服务, 一次喂多帧给 GPU 比单流跑 N 个服务利用率高。

## C.4 后续工作 4: 训练 ↔ 推理双向回环

目前 D6 训练完模型, 用户手工 cp 到 `data/checkpoints/`。可以补一个 `apps/cli/promote.py` 让训练完的 `best.pt` 自动归档到 checkpoints, 这样 `odp-infer --model best.pt` 直接跑最新的训练结果。

---

# 全文完

至此, D8 推理子系统教学讲义结束。

走完 12 个阶段, 8 个 commit, ~1671 行核心代码 + ~180 行 CLI + ~455 行桌面 demo, 总共约 2300 行新代码 + 6 条贯穿全文的纪律 + 一份 7000 行的教学讲义。

下一份讲义见 D9 (多前端 Web/Celery 真集成) 或 D10 (TensorRT 部署), 视后续工程优先级而定。

— END —
