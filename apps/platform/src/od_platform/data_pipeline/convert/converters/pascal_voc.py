"""Pascal VOC -> YOLO 转换器(detect)。

VOC:每张图一个 .xml,框是绝对像素坐标 (xmin,ymin,xmax,ymax)。
YOLO:每张图一个 .txt,每行 `cls_id cx cy w h`,坐标全部归一化到 [0,1]。
本转换器的核心就是"逐个读框 → 像素换算成归一化 → 写 txt",顺带收集类名表。

它如何接入框架:头顶一行 @register 即把自己签进格式注册表,框架代码无需任何改动。
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from od_platform.common.constants import AnnotationFormat, Task
from od_platform.data_pipeline.convert.registry import ConvertOptions, register

logger = logging.getLogger(__name__)


@register(AnnotationFormat.PASCAL_VOC, supported_tasks=(Task.DETECT,))
def convert_voc(input_dir: Path, out_labels_dir: Path, options: ConvertOptions) -> List[str]:
    out_labels_dir.mkdir(parents=True, exist_ok=True)

    # classes 既是"输出的类名表",也是"白名单":
    #   options.classes 为 None → discovering=True,边读边把新类名追加进去(探测模式);
    #   options.classes 给了名单 → discovering=False,不在名单的框直接跳过(=删类)。
    classes: List[str] = list(options.classes) if options.classes else []
    discovering = options.classes is None

    for xml_path in sorted(input_dir.glob("*.xml")):   # sorted:处理顺序确定 → class_id 跨机一致
        root = ET.parse(xml_path).getroot()
        size = root.find("size")
        W = float(size.findtext("width"))               # 用图宽把 x 归一化
        H = float(size.findtext("height"))              # 用图高把 y 归一化

        lines: List[str] = []
        for obj in root.findall("object"):              # 一张图可能有多个框
            name = obj.findtext("name")
            if name not in classes:
                if discovering:
                    classes.append(name)                # 探测模式:首次见到就登记
                else:
                    continue                            # 白名单模式:名单外的框跳过(删类)
            cls_id = classes.index(name)                # 类名 → 数字编号(列表下标)

            b = obj.find("bndbox")
            xmin = float(b.findtext("xmin")); ymin = float(b.findtext("ymin"))
            xmax = float(b.findtext("xmax")); ymax = float(b.findtext("ymax"))
            # 像素的左上/右下 → YOLO 的归一化中心点 + 宽高
            cx = (xmin + xmax) / 2 / W
            cy = (ymin + ymax) / 2 / H
            lines.append(f"{cls_id} {cx:.6f} {cy:.6f} {(xmax-xmin)/W:.6f} {(ymax-ymin)/H:.6f}")

        # 没框也写一个空 .txt:下游靠"每张图都有同名标注文件"配对,缺了它纯背景图会被漏掉。
        (out_labels_dir / (xml_path.stem + ".txt")).write_text("\n".join(lines), encoding="utf-8")

    return classes