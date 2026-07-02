"""类别平衡性报告 —— 只算账、打表、提醒。绝不过滤、绝不改数据。

核心边界(本课反复强调):检查 ≠ 过滤。
    本模块只产出一份只读报告 + (在支持的格式上)一行"可复制的 --classes 建议"。
    删不删类是【用户】的决定,走转换器已有的 --classes 白名单 —— 报告不替用户做主。
    它也 CI 友好:纯函数 + 字符串渲染,不交互、不阻断;是否因某类太少而停下,是
    orchestrator / 用户的策略选择,不是本模块的事。

两个维度(务必区分):
    · 图(image):决定"能不能切" —— 划分是按图做的,某类的图太少就进不了 val/test。
    · 框(box)  :决定"学不学得会" —— 模型从框里学,loss 被框数主导。
    占比的分母也不同:图占比是"普及度"(会重叠,不求和到 100%);框占比是"实例份额"
    (求和到 100%)。
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Tuple

from od_platform.common.constants import (
    CLASS_MIN_BOX_SHARE, CLASS_MIN_BOXES_WARN, CLASS_MIN_IMAGES_HARD, AnnotationFormat,
)
from od_platform.common.string_utils import (
    format_table_row, format_table_separator, get_display_width,
)

# 哪些格式能用 --classes 删类:voc/coco 有类名 → 能过滤+重排;yolo 只命名 → 不能删。
_CLASSES_FILTERABLE = {AnnotationFormat.PASCAL_VOC, AnnotationFormat.COCO}

_OK = "OK"
_BOTH = "⚠️ 严重不足(图/框双低)"
_BOX = "⚠️ 框数偏低"
_IMG = "⚠️ 图数偏低"


@dataclass(frozen=True)
class ClassStat:
    """单个类别的统计行。"""
    name: str
    image_count: int
    box_count: int
    image_pct: float       # image_count / total_images(普及度,不求和到 1)
    box_pct: float         # box_count / total_boxes(实例份额,求和到 1)
    status: str

    @property
    def ok(self) -> bool:
        return self.status == _OK


@dataclass(frozen=True)
class ClassBalanceReport:
    """整份报告:每类统计 + 总量 + "有用地板"。"""
    stats: List[ClassStat]
    total_images: int
    total_boxes: int
    usefulness_img_floor: int   # 图数低于此,大概率进不了最小的子集

    @property
    def flagged(self) -> List[ClassStat]:
        return [s for s in self.stats if not s.ok]

    @property
    def has_warnings(self) -> bool:
        return bool(self.flagged)

    def keeper_classes(self) -> List[str]:
        """状态 OK 的类(保留原顺序)—— 用于生成 --classes 建议行。"""
        return [s.name for s in self.stats if s.ok]


def analyze_class_balance(
    labels_per_image: Dict[str, List[str]],
    classes: List[str],
    train_rate: float,
    val_rate: float,
) -> ClassBalanceReport:
    """纯函数:由 {图: [类别名,...]} + 类别表 + 比例,算出每类的图/框分布与状态。"""
    total_images = len(labels_per_image)
    test_rate = max(0.0, 1.0 - train_rate - val_rate)

    image_count: Dict[str, int] = {c: 0 for c in classes}
    box_count: Dict[str, int] = {c: 0 for c in classes}
    for labs in labels_per_image.values():
        for name, k in Counter(labs).items():
            if name in box_count:
                box_count[name] += k          # 框数 = 出现次数(同图同类多次计多次)
                image_count[name] += 1         # 图数 = 含该类的图 +1(同图同类只算一次)
    total_boxes = sum(box_count.values())

    # "有用地板":想在最小子集里至少摊到 1 张,需要的图数 ≈ 1 / min(val,test)。
    smallest = min(r for r in (val_rate, test_rate) if r > 0) if (val_rate > 0 or test_rate > 0) else 0.0
    floor = max(CLASS_MIN_IMAGES_HARD, math.ceil(1.0 / smallest)) if smallest > 0 else CLASS_MIN_IMAGES_HARD

    stats: List[ClassStat] = []
    for c in classes:
        ic, bc = image_count[c], box_count[c]
        img_starved = ic < floor
        box_share = (bc / total_boxes) if total_boxes else 0.0
        box_starved = bc < CLASS_MIN_BOXES_WARN or box_share < CLASS_MIN_BOX_SHARE
        status = _BOTH if (img_starved and box_starved) else _BOX if box_starved else _IMG if img_starved else _OK
        stats.append(ClassStat(
            name=c, image_count=ic, box_count=bc,
            image_pct=(ic / total_images) if total_images else 0.0,
            box_pct=box_share, status=status,
        ))

    return ClassBalanceReport(
        stats=stats, total_images=total_images, total_boxes=total_boxes,
        usefulness_img_floor=floor,
    )


def render_balance_report(report: ClassBalanceReport, source_format: str) -> List[Tuple[str, bool]]:
    """把报告渲染成 [(行文本, 是否警告), ...]。只读,不改任何东西。

    偏弱类别的数据行 is_warning=True,调用方(如指挥家)可用 WARNING 级别高亮它们。
    列宽用 D1 的 CJK 宽度工具按"显示宽度"计算,中文类名不会错位。
    """
    flagged = {s.name for s in report.flagged}

    # 列宽 = max(表头显示宽, 各数据显示宽) + 余量
    name_w = max(get_display_width("类别"), max((get_display_width(s.name) for s in report.stats), default=0)) + 2
    img_w = max(get_display_width("图片数"), max((len(str(s.image_count)) for s in report.stats), default=0)) + 2
    box_w = max(get_display_width("框数"), max((len(str(s.box_count)) for s in report.stats), default=0)) + 2
    pct_w = max(get_display_width("图占比"), get_display_width("框占比"), 7) + 2     # 7 = "100.00%"
    status_w = max(get_display_width("状态"), max((get_display_width(s.status) for s in report.stats), default=0)) + 1
    widths = [name_w, img_w, box_w, pct_w, pct_w, status_w]
    aligns = ["left", "right", "right", "right", "right", "left"]

    out: List[Tuple[str, bool]] = []
    out.append(("数据平衡性报告".center(sum(widths) + len(widths) - 1, "="), False))
    out.append((format_table_row(["类别", "图片数", "框数", "图占比", "框占比", "状态"], widths, aligns), False))
    out.append((format_table_separator(widths), False))
    for s in report.stats:
        line = format_table_row(
            [s.name, str(s.image_count), str(s.box_count),
             f"{s.image_pct * 100:.2f}%", f"{s.box_pct * 100:.2f}%", s.status],
            widths, aligns,
        )
        out.append((line, s.name in flagged))          # 偏弱行标 True,调用方可高亮
    out.append((format_table_separator(widths), False))
    out.append((
        f"合计: {report.total_images} 张图, {report.total_boxes} 个框; "
        f"图数有用地板 ≈ {report.usefulness_img_floor} (低于它的类在 val/test 里多半摊不到样本)",
        False,
    ))

    # 有偏弱类才追加"建议"区。注意:这里只给建议,绝不替用户删类。
    if report.has_warnings:
        out.append(("", False))
        out.append((f"⚠️  以下类别偏弱: {', '.join(s.name for s in report.flagged)}", False))
        out.append(("   这只是提醒——本工具不会自动删类或改数据。处理方式:", False))
        if source_format in _CLASSES_FILTERABLE:
            keepers = report.keeper_classes()
            if keepers and len(keepers) < len(report.stats):
                kline = " ".join(f'"{k}"' for k in keepers)
                out.append((f"   · 想只训练正常的类, 重跑时加:  --classes {kline}", False))
            out.append(("   · 或者: 给偏弱的类补充/增强样本后重跑。", False))
        else:
            out.append(("   · yolo 源数据无法用 --classes 删类(会让 yaml 与 txt 的 id 对不上);", False))
            out.append(("     请在源头重写 txt 或补充样本。", False))
    return out