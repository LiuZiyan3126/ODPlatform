"""COCO -> YOLO 转换器(detect / segment)。

COCO 与 VOC 的差异只在"读法":整个数据集一个 .json,框是 [x,y,w,h](左上角 + 宽高)。
读完之后,归一化、写 txt、白名单处理与 VOC 完全一样 —— 这也是为什么三种 converter 能
被同一张表一视同仁地调用:它们的输入/输出契约相同。
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import List

from od_platform.common.constants import AnnotationFormat, Task
from od_platform.data_pipeline.convert.registry import ConvertOptions, register

logger = logging.getLogger(__name__)


@register(AnnotationFormat.COCO, supported_tasks=(Task.DETECT, Task.SEGMENT))
def convert_coco(input_dir: Path, out_labels_dir: Path, options: ConvertOptions) -> List[str]:
    out_labels_dir.mkdir(parents=True, exist_ok=True)

    # COCO 习惯整个数据集一个 json(取目录下第一个);先把它解析成几张查找表。
    data = json.loads(sorted(input_dir.glob("*.json"))[0].read_text(encoding="utf-8"))
    cat_name = {c["id"]: c["name"] for c in data["categories"]}   # 类别 id → 名字
    img_info = {im["id"]: im for im in data["images"]}            # 图 id → 图信息(含宽高/文件名)
    per_image = defaultdict(list)                                 # 图 id → 它的所有标注
    for ann in data["annotations"]:
        per_image[ann["image_id"]].append(ann)

    classes: List[str] = list(options.classes) if options.classes else []
    discovering = options.classes is None                         # 同 VOC:None=探测,[...]=白名单
    for img_id, im in img_info.items():
        W, H = float(im["width"]), float(im["height"])
        stem = im["file_name"].rsplit(".", 1)[0]                  # 去扩展名,作为输出 txt 的文件名
        lines: List[str] = []
        for ann in per_image.get(img_id, []):
            name = cat_name[ann["category_id"]]
            if name not in classes:
                if discovering:
                    classes.append(name)
                else:
                    continue
            cls_id = classes.index(name)
            x, y, w, h = ann["bbox"]                              # COCO:左上角 (x,y) + 宽高 (w,h)
            lines.append(f"{cls_id} {(x+w/2)/W:.6f} {(y+h/2)/H:.6f} {w/W:.6f} {h/H:.6f}")
        (out_labels_dir / (stem + ".txt")).write_text("\n".join(lines), encoding="utf-8")

    return classes