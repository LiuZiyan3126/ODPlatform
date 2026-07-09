#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""模型评估报告 Markdown + HTML 生成器."""
from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from od_platform.common.system_utils import get_basic_device_info

logger = logging.getLogger(__name__)

_EVAL_REPORT_TEMPLATE = """\
# 模型评估报告 — {model_name}

## 基本信息

| 字段 | 值 |
|------|-----|
| 评估人 | {author} |
| 评估时间 | {eval_time} |
| 任务类型 | {task} |
| 评估分片 | {split} |

## 模型与数据

| 字段 | 值 |
|------|-----|
| 模型 | {model_name} |
| 模型路径 | {model_path} |
| 数据集 | {data_name} |

## 运行环境

| 项目 | 值 |
|------|-----|
| 操作系统 | {os} |
| CPU | {cpu} |
| Python | {python_ver} |
| PyTorch | {torch_ver} |
| Ultralytics | {ultra_ver} |
{device_rows}
## 整体评估指标

| 指标 | 值 |
|------|-----|
{metric_rows}
## 逐类指标 (mAP@0.5:0.95)

| 类别 | mAP@50-95 |
|------|-----------|
{class_rows}
## 评估可视化

### PR 曲线
![PR curve]({img_pr})

### F1 曲线
![F1 curve]({img_f1})

### 混淆矩阵
![confusion]({img_cm})

### 规范化混淆矩阵
![confusion normalized]({img_cmn})

### 验证批次预测
![val pred0]({img_val_pred0})
![val pred1]({img_val_pred1})

## 产出文件

| 类型 | 路径 |
|------|------|
| 输出目录 | `{output_dir}` |
| 审计快照 | `{audit_snapshot}` |
"""

# ---- HTML 仪表盘 ----

_HTML_HEADER = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --primary: #0d9488;
    --primary-light: #f0fdfa;
    --success: #0d9488;
    --success-bg: #f0fdfa;
    --warning: #d97706;
    --warning-bg: #fffbeb;
    --danger: #dc2626;
    --danger-bg: #fef2f2;
    --gray-50: #f9fafb;
    --gray-100: #f3f4f6;
    --gray-200: #e5e7eb;
    --gray-300: #d1d5db;
    --gray-400: #9ca3af;
    --gray-500: #6b7280;
    --gray-600: #4b5563;
    --gray-700: #374151;
    --gray-800: #1f2937;
    --gray-900: #111827;
    --radius: 12px;
    --shadow: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06);
    --shadow-md: 0 4px 6px rgba(0,0,0,.07), 0 2px 4px rgba(0,0,0,.06);
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Helvetica, Arial, sans-serif;
    background: #f1f5f9;
    color: var(--gray-800);
    line-height: 1.6;
    min-height: 100vh;
  }}
  .hero {{
    background: linear-gradient(135deg, #134e4a 0%, #0d9488 50%, #14b8a6 100%);
    color: white;
    padding: 48px 32px 40px;
    text-align: center;
    position: relative;
    overflow: hidden;
  }}
  .hero::before {{
    content: '';
    position: absolute;
    inset: 0;
    background: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.04'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
  }}
  .hero-content {{ position: relative; z-index: 1; }}
  .hero h1 {{ font-size: 32px; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.5px; }}
  .hero .subtitle {{ font-size: 15px; opacity: .85; font-weight: 400; }}
  .hero .badge {{
    display: inline-block;
    padding: 4px 16px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
    margin-top: 16px;
    letter-spacing: .3px;
    background: rgba(255,255,255,.2);
    border: 1px solid rgba(255,255,255,.3);
  }}
  .container {{ max-width: 1120px; margin: 0 auto; padding: 0 24px; }}
  .main-content {{ padding: 32px 0 64px; }}
  .section {{ margin-bottom: 28px; }}
  .section-title {{
    font-size: 19px;
    font-weight: 700;
    color: var(--gray-900);
    margin-bottom: 16px;
    padding-left: 14px;
    border-left: 4px solid var(--primary);
    line-height: 1.3;
  }}
  .metric-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 12px;
  }}
  .metric-card {{
    background: white;
    border-radius: var(--radius);
    padding: 20px 24px;
    box-shadow: var(--shadow);
    border: 1px solid var(--gray-200);
    transition: transform .15s, box-shadow .15s;
  }}
  .metric-card:hover {{ transform: translateY(-2px); box-shadow: var(--shadow-md); }}
  .metric-card .metric-label {{
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .6px;
    color: var(--gray-500);
    margin-bottom: 8px;
  }}
  .metric-card .metric-value {{
    font-size: 28px;
    font-weight: 800;
    color: var(--gray-900);
    font-variant-numeric: tabular-nums;
  }}
  .metric-high {{ color: var(--success) !important; }}
  .metric-mid  {{ color: var(--warning) !important; }}
  .metric-low  {{ color: var(--danger) !important; }}
  .card {{
    background: white;
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    border: 1px solid var(--gray-200);
    overflow: hidden;
  }}
  .card-header {{
    background: var(--gray-50);
    padding: 14px 20px;
    font-weight: 700;
    font-size: 14px;
    color: var(--gray-700);
    text-transform: uppercase;
    letter-spacing: .5px;
    border-bottom: 1px solid var(--gray-200);
  }}
  .card-body {{ padding: 20px 24px; }}
  .info-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 20px;
  }}
  .info-item {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid var(--gray-100);
  }}
  .info-item:last-child {{ border-bottom: none; }}
  .info-key {{ font-size: 13px; color: var(--gray-500); font-weight: 500; }}
  .info-val {{ font-size: 14px; color: var(--gray-800); font-weight: 600; text-align: right; }}
  .table-wrapper {{ overflow-x: auto; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }}
  th {{
    background: var(--gray-50);
    padding: 12px 16px;
    text-align: left;
    font-weight: 600;
    color: var(--gray-600);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: .4px;
    border-bottom: 2px solid var(--gray-200);
  }}
  td {{
    padding: 12px 16px;
    border-bottom: 1px solid var(--gray-100);
    color: var(--gray-700);
  }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: var(--gray-50); }}
  .gallery-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(450px, 1fr));
    gap: 20px;
  }}
  .gallery-item {{
    background: white;
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    border: 1px solid var(--gray-200);
    overflow: hidden;
  }}
  .gallery-item-header {{
    padding: 12px 16px;
    font-weight: 600;
    font-size: 13px;
    color: var(--gray-600);
    background: var(--gray-50);
    border-bottom: 1px solid var(--gray-200);
    text-transform: uppercase;
    letter-spacing: .3px;
  }}
  .gallery-item img {{
    width: 100%;
    display: block;
    padding: 8px;
    background: white;
  }}
  .tag {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: .2px;
  }}
  .tag-ok {{ background: var(--success-bg); color: var(--success); }}
  .tag-info {{ background: var(--primary-light); color: var(--primary); }}
  .footer {{
    text-align: center;
    padding: 32px;
    color: var(--gray-400);
    font-size: 12px;
    border-top: 1px solid var(--gray-200);
    margin-top: 48px;
  }}
  @media (max-width: 768px) {{
    .hero {{ padding: 32px 16px 28px; }}
    .hero h1 {{ font-size: 22px; }}
    .metric-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .gallery-grid {{ grid-template-columns: 1fr; }}
    .info-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
"""

_HTML_FOOTER = """\
<footer class="footer">
  Generated by ODPlatform · {timestamp}
</footer>
</body>
</html>"""


def generate_eval_report(
    result: Any,
    *,
    author: str = "",
    model_name: str = "",
    data_name: str = "",
    split: str = "test",
    task: str = "detect",
    class_map: dict[str, float] | None = None,
) -> Path:
    eval_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sys_info = get_basic_device_info()
    os_str = sys_info.get("系统信息", {}).get("操作系统", "-")
    cpu_str = sys_info.get("CPU信息", {}).get("cpu型号", "-")
    python_ver = sys_info.get("系统信息", {}).get("Python版本", "-")
    torch_ver = sys_info.get("系统信息", {}).get("pytorch版本", "-")
    ultra_ver = sys_info.get("系统信息", {}).get("ultralytics版本", "-")

    device_rows = ""
    gpu_rows = ""
    gpu_info = sys_info.get("GPU信息", {})
    if gpu_info.get("GPU可用") and gpu_info.get("GPU数量", 0) > 0:
        for i in range(gpu_info["GPU数量"]):
            gpu_name = gpu_info.get(f"GPU {i}", "-")
            device_rows += f"| GPU {i} | {gpu_name} |\n"
            gpu_rows += f'<div class="info-item"><span class="info-key">GPU {i}</span><span class="info-val">{gpu_name}</span></div>\n'

    metric_rows = ""
    for k, v in result.metrics.items():
        if isinstance(v, float) and not math.isnan(v):
            metric_rows += f"| {k} | {v:.4f} |\n"
    if not metric_rows:
        metric_rows = "| - | - |"

    class_rows = ""
    if class_map:
        valid = {k: v for k, v in class_map.items() if not math.isnan(v)}
        for name, ap in sorted(valid.items(), key=lambda kv: kv[1], reverse=True):
            class_rows += f"| {name} | {ap:.4f} |\n"
    if not class_rows:
        class_rows = "| - | - |"

    od = result.output_dir

    def _img(name: str) -> str:
        p = od / name
        return f"./{name}" if p.exists() else f"(未生成: {name})"

    img_pr = _img("BoxPR_curve.png")
    img_f1 = _img("BoxF1_curve.png")
    img_cm = _img("confusion_matrix.png")
    img_cmn = _img("confusion_matrix_normalized.png")
    img_val_pred0 = _img("val_batch0_pred.jpg")
    img_val_pred1 = _img("val_batch1_pred.jpg")

    audit_snapshot = str(result.audit_path) if result.audit_path else "-"

    # ---- Markdown ----
    content = _EVAL_REPORT_TEMPLATE.format(
        author=author or "-",
        eval_time=eval_time_str,
        task=task,
        split=split,
        model_name=model_name or "-",
        model_path=str(result.model_path),
        data_name=data_name or "-",
        os=os_str,
        cpu=cpu_str,
        python_ver=python_ver,
        torch_ver=torch_ver,
        ultra_ver=ultra_ver,
        device_rows=device_rows,
        metric_rows=metric_rows,
        class_rows=class_rows,
        img_pr=img_pr,
        img_f1=img_f1,
        img_cm=img_cm,
        img_cmn=img_cmn,
        img_val_pred0=img_val_pred0,
        img_val_pred1=img_val_pred1,
        output_dir=str(od),
        audit_snapshot=audit_snapshot,
    )

    report_path = od / "report.md"
    try:
        report_path.write_text(content, encoding="utf-8")
        logger.info(f"评估报告已生成: {report_path}")
    except OSError as e:
        logger.warning(f"评估报告写入失败: {e}")
        return report_path

    # ---- HTML 仪表盘 ----
    html_path = od / "report.html"
    try:
        html_content = _build_eval_html(
            title=f"评估报告 — {model_name or '未命名'}",
            author=author,
            eval_time=eval_time_str,
            task=task,
            split=split,
            model_name=model_name,
            model_path=str(result.model_path),
            data_name=data_name,
            os=os_str, cpu=cpu_str,
            python_ver=python_ver, torch_ver=torch_ver, ultra_ver=ultra_ver,
            gpu_rows=gpu_rows,
            metrics=result.metrics,
            class_rows=class_rows,
            img_pr=img_pr, img_f1=img_f1, img_cm=img_cm, img_cmn=img_cmn,
            img_val_pred0=img_val_pred0, img_val_pred1=img_val_pred1,
            output_dir=str(od),
            audit_snapshot=audit_snapshot,
        )
        html_path.write_text(html_content, encoding="utf-8")
        logger.info(f"HTML 评估报告已生成: {html_path}")
    except OSError as e:
        logger.warning(f"HTML 报告写入失败: {e}")

    return report_path


def _build_eval_html(
    *, title, author, eval_time, task, split, model_name, model_path,
    data_name, os, cpu, python_ver, torch_ver, ultra_ver, gpu_rows,
    metrics, class_rows,
    img_pr, img_f1, img_cm, img_cmn, img_val_pred0, img_val_pred1,
    output_dir, audit_snapshot,
) -> str:
    # 指标卡片
    cards = []
    key_map = {
        "metrics/mAP50(B)": "mAP@50",
        "metrics/mAP50-95(B)": "mAP@50-95",
        "metrics/precision(B)": "Precision",
        "metrics/recall(B)": "Recall",
        "fitness": "Fitness",
    }
    for key, label in key_map.items():
        val = metrics.get(key)
        if val is not None and not math.isnan(val):
            cls = "metric-high" if val >= 0.7 else ("metric-mid" if val >= 0.4 else "metric-low")
            cards.append(f"""<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value {cls}">{val:.4f}</div></div>""")
    cards_html = "\n".join(cards) if cards else '<div class="metric-card"><div class="metric-label">-</div><div class="metric-value">-</div></div>'

    # 逐类表格
    class_table_rows = ""
    if class_rows:
        for line in class_rows.strip().split("\n"):
            line = line.strip()
            if line.startswith("|") and line.endswith("|"):
                parts = [p.strip() for p in line.strip("|").split("|")]
                if len(parts) == 2:
                    cls_name, val = parts[0], parts[1]
                    vf = float(val) if val != "-" else 0
                    cls_cls = "metric-high" if vf >= 0.5 else ("metric-mid" if vf >= 0.2 else "metric-low")
                    class_table_rows += f'<tr><td>{cls_name}</td><td style="font-weight:700;color:var(--{"success" if vf>=0.5 else "warning" if vf>=0.2 else "danger"});">{val}</td></tr>\n'

    # 图库
    gallery_items = []
    for label, src in [
        ("PR 曲线", img_pr), ("F1 曲线", img_f1), ("混淆矩阵", img_cm),
        ("规范化混淆矩阵", img_cmn), ("验证批次预测 #0", img_val_pred0), ("验证批次预测 #1", img_val_pred1),
    ]:
        if src.startswith("./"):
            gallery_items.append(f"""<div class="gallery-item"><div class="gallery-item-header">{label}</div><img src="{src}" alt="{label}" loading="lazy" /></div>""")
    gallery_html = f'<div class="gallery-grid">{"".join(gallery_items)}</div>' if gallery_items else "<p>暂无可视化图表</p>"

    return f"""{_HTML_HEADER.format(title=title)}

<header class="hero">
  <div class="hero-content">
    <h1>{title}</h1>
    <p class="subtitle">{author} · {eval_time} · 分片: {split}</p>
    <span class="badge">模型评估</span>
  </div>
</header>

<div class="main-content">
<div class="container">

<section class="section">
  <div class="section-title">关键指标</div>
  <div class="metric-grid">
    {cards_html}
  </div>
</section>

<section class="section">
  <div class="section-title">基本信息</div>
  <div class="info-grid">
    <div class="card">
      <div class="card-header">评估信息</div>
      <div class="card-body">
        <div class="info-item"><span class="info-key">评估人</span><span class="info-val">{author}</span></div>
        <div class="info-item"><span class="info-key">任务类型</span><span class="info-val"><span class="tag tag-info">{task}</span></span></div>
        <div class="info-item"><span class="info-key">评估分片</span><span class="info-val">{split}</span></div>
        <div class="info-item"><span class="info-key">模型</span><span class="info-val">{model_name}</span></div>
        <div class="info-item"><span class="info-key">评估时间</span><span class="info-val">{eval_time}</span></div>
      </div>
    </div>
    <div class="card">
      <div class="card-header">运行环境</div>
      <div class="card-body">
        <div class="info-item"><span class="info-key">操作系统</span><span class="info-val">{os}</span></div>
        <div class="info-item"><span class="info-key">CPU</span><span class="info-val">{cpu}</span></div>
        <div class="info-item"><span class="info-key">Python</span><span class="info-val">{python_ver}</span></div>
        <div class="info-item"><span class="info-key">PyTorch</span><span class="info-val">{torch_ver}</span></div>
        <div class="info-item"><span class="info-key">Ultralytics</span><span class="info-val">{ultra_ver}</span></div>
        {gpu_rows}
      </div>
    </div>
  </div>
</section>

<section class="section">
  <div class="section-title">逐类指标</div>
  <div class="card">
    <div class="table-wrapper">
      <table>
        <thead><tr><th>类别</th><th>mAP@50-95</th></tr></thead>
        <tbody>
          {class_table_rows if class_table_rows else '<tr><td>-</td><td>-</td></tr>'}
        </tbody>
      </table>
    </div>
  </div>
</section>

<section class="section">
  <div class="section-title">评估可视化</div>
  {gallery_html}
</section>

<section class="section">
  <div class="section-title">产出文件</div>
  <div class="card">
    <div class="table-wrapper">
      <table>
        <thead><tr><th>类型</th><th>路径</th></tr></thead>
        <tbody>
          <tr><td>输出目录</td><td style="font-family:monospace;font-size:13px;">{output_dir}</td></tr>
          <tr><td>审计快照</td><td style="font-family:monospace;font-size:13px;">{audit_snapshot}</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>

</div>
</div>

{_HTML_FOOTER.format(timestamp=eval_time)}
"""