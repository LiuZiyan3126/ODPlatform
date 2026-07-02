#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : convert_rsod.py
# @Author    : ODPlatform team
# @Project   : ODPlatform
# @Function  : RSOD 数据集转换脚本 — Pascal VOC → YOLO 格式
"""将 data/raw/rsod 的 Pascal VOC 标注转换为 YOLO 格式。

用法:
    python scripts/convert_rsod.py                # dry-run 查看统计
    python scripts/convert_rsod.py --convert       # 执行转换
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── 路径注入 ──────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
PLATFORM_SRC = REPO_ROOT / "apps" / "platform" / "src"
sys.path.insert(0, str(PLATFORM_SRC))

# ── 导入项目模块 ──────────────────────────────────────────
from od_platform.common.constants import AnnotationFormat, Task
from od_platform.data_pipeline.convert.registry import ConvertOptions, list_capabilities
from od_platform.data_pipeline.convert.service import convert_data_to_yolo


def main(convert: bool = False) -> None:
    # ── 数据集路径 ─────────────────────────────────────────
    raw_dir = REPO_ROOT / "data" / "raw" / "rsod"
    xml_dir = raw_dir / "annotations"
    images_dir = raw_dir / "images"
    output_dir = REPO_ROOT / "data" / "processed" / "rsod_yolo" / "labels"

    print("=" * 60)
    print("RSOD 数据集转换: Pascal VOC -> YOLO")
    print("=" * 60)

    # ── 数据集概览 ─────────────────────────────────────────
    xml_count = len(list(xml_dir.glob("*.xml")))
    img_count = len(list(images_dir.glob("*.jpg"))) + len(list(images_dir.glob("*.png")))
    print(f"\n[数据集概览]")
    print(f"   标注目录:   {xml_dir}")
    print(f"   图片目录:   {images_dir}")
    print(f"   XML 标注:   {xml_count} 个")
    print(f"   图片文件:   {img_count} 个")
    print(f"   背景图:     {img_count - xml_count} 个 (无标注)")

    # ── 注册表状态 ─────────────────────────────────────────
    print(f"\n[已注册的转换器]")
    caps = list_capabilities()
    for fmt, tasks in caps.items():
        enabled = "[V]" if Task.DETECT in tasks else "[!]"
        print(f"   {enabled} {fmt}: 支持 {', '.join(tasks)}")

    if not convert:
        print(f"\n[提示] 这是 dry-run 模式。要执行转换请加 --convert")
        return

    # ── 执行转换 ───────────────────────────────────────────
    print(f"\n[开始转换]")
    print(f"   输入:  {xml_dir}")
    print(f"   输出:  {output_dir}")

    options = ConvertOptions(task=Task.DETECT)
    classes = convert_data_to_yolo(
        input_dir=xml_dir,
        output_labels_dir=output_dir,
        annotation_format=AnnotationFormat.PASCAL_VOC,
        options=options,
    )

    # ── 转换结果 ───────────────────────────────────────────
    txt_count = len(list(output_dir.glob("*.txt"))) if output_dir.exists() else 0
    print(f"\n[转换完成]")
    print(f"   生成 YOLO 标签: {txt_count} 个")
    print(f"   检测到类别 ({len(classes)}): {', '.join(classes)}")
    print(f"   输出目录: {output_dir}")

    # ── 预览前 3 个标签文件 ────────────────────────────────
    print(f"\n[标签预览 (前 3 个)]")
    for i, txt_file in enumerate(sorted(output_dir.glob("*.txt"))[:3], 1):
        lines = txt_file.read_text().strip().split("\n")
        print(f"   [{i}] {txt_file.name}: {len(lines) if lines[0] else 0} 个目标")
        for line in lines[:3]:
            print(f"       {line}")


if __name__ == "__main__":
    convert_flag = "--convert" in sys.argv
    main(convert=convert_flag)
