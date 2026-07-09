#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""训练报告 Markdown + HTML 生成器."""
from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import markdown

from od_platform.common.system_utils import get_basic_device_info

if TYPE_CHECKING:
    from od_platform.training.service import TrainResult

logger = logging.getLogger(__name__)


def _data_quality_display(
    report_path_raw: str | None,
    output_dir: Path,
) -> tuple[str, str]:
    """Build Markdown and HTML labels for a linked validation report."""
    if not report_path_raw:
        return "未验证", "未验证"

    report_path = Path(report_path_raw).expanduser().resolve()
    severity = ""
    link_target = report_path
    if report_path.suffix.casefold() == ".json":
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            severity = str(payload.get("overall_severity") or "")
            html_artifact = payload.get("artifacts", {}).get("html")
            if html_artifact:
                link_target = Path(html_artifact)
            elif report_path.with_name("report.html").is_file():
                link_target = report_path.with_name("report.html")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    label = f"已验证（{severity}） · 查看报告" if severity else "已验证 · 查看报告"
    try:
        link = os.path.relpath(link_target, output_dir).replace("\\", "/")
    except ValueError:
        link = link_target.as_uri()
    markdown_label = f"[{label}]({link})"
    html_label = (
        f'<a href="{html.escape(link, quote=True)}">'
        f"{html.escape(label)}</a>"
    )
    return markdown_label, html_label


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def _build_html_report(
    *,
    title: str,
    author: str,
    started_at: str,
    finished_at: str,
    duration: str,
    task: str,
    status: str,
    status_class: str,
    os: str,
    cpu: str,
    python_ver: str,
    torch_ver: str,
    ultra_ver: str,
    gpu_rows: str,
    data_name: str,
    data_path: str,
    data_quality: str,
    config_rows: str,
    audit_path: str,
    metrics: dict[str, float],
    metric_cards: str,
    img_results: str,
    img_pr: str,
    img_f1: str,
    img_cm: str,
    img_cmn: str,
    img_labels: str,
    img_train_batch0: str,
    img_train_batch1: str,
    img_val_pred0: str,
    img_val_pred1: str,
    output_dir: str,
    best_weight: str,
    last_weight: str,
    log_path: str,
) -> str:
    """直接构建现代化 HTML 仪表盘报告."""

    # 关键指标卡片
    cards_html = _build_metric_cards(metrics, metric_cards)

    # 配置表格
    config_html = _build_config_table(audit_path, config_rows)

    # 可视化区域
    gallery_html = _build_gallery(
        img_results, img_pr, img_f1, img_cm, img_cmn,
        img_labels, img_train_batch0, img_train_batch1,
        img_val_pred0, img_val_pred1,
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --primary: #1a73e8;
    --primary-light: #e8f0fe;
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
    --radius-sm: 8px;
    --shadow: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06);
    --shadow-md: 0 4px 6px rgba(0,0,0,.07), 0 2px 4px rgba(0,0,0,.06);
    --shadow-lg: 0 10px 15px rgba(0,0,0,.07), 0 4px 6px rgba(0,0,0,.05);
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Helvetica, Arial, sans-serif;
    background: #f1f5f9;
    color: var(--gray-800);
    line-height: 1.6;
    min-height: 100vh;
  }}

  /* ---- Hero Header ---- */
  .hero {{
    background: linear-gradient(135deg, #1e3a5f 0%, #1a73e8 50%, #4f8ef7 100%);
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
  }}
  .badge-success {{ background: rgba(255,255,255,.2); color: #fff; border: 1px solid rgba(255,255,255,.3); }}

  /* ---- Layout ---- */
  .container {{ max-width: 1120px; margin: 0 auto; padding: 0 24px; }}
  .main-content {{ padding: 32px 0 64px; }}

  /* ---- Section ---- */
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

  /* ---- Metric Cards ---- */
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
  .metric-card .metric-unit {{ font-size: 14px; font-weight: 400; color: var(--gray-500); }}
  .metric-high {{ color: var(--success) !important; }}
  .metric-mid  {{ color: var(--warning) !important; }}
  .metric-low  {{ color: var(--danger) !important; }}

  /* ---- Info Card ---- */
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
    gap: 12px;
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

  /* ---- Table ---- */
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

  /* ---- Gallery ---- */
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

  /* ---- Footer ---- */
  .footer {{
    text-align: center;
    padding: 32px;
    color: var(--gray-400);
    font-size: 12px;
    border-top: 1px solid var(--gray-200);
    margin-top: 48px;
  }}

  /* ---- Tags ---- */
  .tag {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: .2px;
  }}
  .tag-ok {{ background: var(--success-bg); color: var(--success); }}
  .tag-warn {{ background: var(--warning-bg); color: var(--warning); }}
  .tag-info {{ background: var(--primary-light); color: var(--primary); }}

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

<!-- Hero -->
<header class="hero">
  <div class="hero-content">
    <h1>{title}</h1>
    <p class="subtitle">{author} · {started_at} → {finished_at} · 总耗时 {duration}</p>
    <span class="badge badge-success">{status}</span>
  </div>
</header>

<div class="main-content">
<div class="container">

<!-- 关键指标仪表盘 -->
<section class="section">
  <div class="section-title">关键指标</div>
  <div class="metric-grid">
    {cards_html}
  </div>
</section>

<!-- 基本信息 + 运行环境 -->
<section class="section">
  <div class="section-title">基本信息</div>
  <div class="info-grid" style="gap:20px;">
    <div class="card">
      <div class="card-header">实验信息</div>
      <div class="card-body">
        <div class="info-item"><span class="info-key">训练人</span><span class="info-val">{author}</span></div>
        <div class="info-item"><span class="info-key">任务类型</span><span class="info-val"><span class="tag tag-info">{task}</span></span></div>
        <div class="info-item"><span class="info-key">训练状态</span><span class="info-val"><span class="tag tag-ok">{status}</span></span></div>
        <div class="info-item"><span class="info-key">开始时间</span><span class="info-val">{started_at}</span></div>
        <div class="info-item"><span class="info-key">结束时间</span><span class="info-val">{finished_at}</span></div>
        <div class="info-item"><span class="info-key">总耗时</span><span class="info-val">{duration}</span></div>
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
    <div class="card">
      <div class="card-header">数据集</div>
      <div class="card-body">
        <div class="info-item"><span class="info-key">数据集名称</span><span class="info-val">{data_name}</span></div>
        <div class="info-item"><span class="info-key">数据质量</span><span class="info-val"><span class="tag {'tag-ok' if '查看' in str(data_quality) else 'tag-warn'}">{data_quality}</span></span></div>
        <div class="info-item" style="flex-direction:column;align-items:flex-start;gap:4px;">
          <span class="info-key">数据集路径</span>
          <span class="info-val" style="font-size:12px;word-break:break-all;text-align:left;font-weight:400;">{data_path}</span>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- 训练配置 -->
<section class="section">
  <div class="section-title">训练配置</div>
  <div class="card">
    <div class="table-wrapper">
      <table>
        <thead><tr><th>参数</th><th>值</th></tr></thead>
        <tbody>
          {config_html}
        </tbody>
      </table>
    </div>
  </div>
</section>

<!-- 训练可视化 -->
<section class="section">
  <div class="section-title">训练可视化</div>
  {gallery_html}
</section>

<!-- 产出文件 -->
<section class="section">
  <div class="section-title">产出文件</div>
  <div class="card">
    <div class="table-wrapper">
      <table>
        <thead><tr><th>类型</th><th>路径</th></tr></thead>
        <tbody>
          <tr><td>输出目录</td><td style="font-family:monospace;font-size:13px;">{output_dir}</td></tr>
          <tr><td>最佳权重</td><td style="font-family:monospace;font-size:13px;">{best_weight}</td></tr>
          <tr><td>最后权重</td><td style="font-family:monospace;font-size:13px;">{last_weight}</td></tr>
          <tr><td>审计快照</td><td style="font-family:monospace;font-size:13px;">{audit_path}</td></tr>
          <tr><td>训练日志</td><td style="font-family:monospace;font-size:13px;">{log_path}</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>

</div>
</div>

<footer class="footer">
  Generated by ODPlatform · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
</footer>
</body>
</html>"""


def _build_metric_cards(metrics: dict[str, float], extra: str) -> str:
    """构建指标卡片 HTML."""
    # 提取关键指标并着色
    key_map = {
        "metrics/mAP50(B)": ("mAP@50", "↑"),
        "metrics/mAP50-95(B)": ("mAP@50-95", "↑"),
        "metrics/precision(B)": ("Precision", "↑"),
        "metrics/recall(B)": ("Recall", "↑"),
        "fitness": ("Fitness", "↑"),
    }
    cards = []
    for key, (label, _arrow) in key_map.items():
        val = metrics.get(key)
        if val is not None:
            cls = "metric-high" if val >= 0.7 else ("metric-mid" if val >= 0.4 else "metric-low")
            cards.append(f"""<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value {cls}">{val:.4f}</div></div>""")

    # 额外卡片
    if extra:
        for line in extra.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(":", 1)
            if len(parts) == 2:
                k, v = parts[0].strip(), parts[1].strip()
                if k and v:
                    cards.append(f"""<div class="metric-card"><div class="metric-label">{k}</div><div class="metric-value" style="font-size:20px;">{v}</div></div>""")

    if not cards:
        cards = ['<div class="metric-card"><div class="metric-label">-</div><div class="metric-value">-</div></div>']
    return "\n".join(cards)


def _build_config_table(audit_path: str, config_summary: str) -> str:
    # 优先用 config_summary 中已格式化的行
    if config_summary:
        rows = []
        for line in config_summary.split("\n"):
            line = line.strip()
            if line.startswith("|") and line.endswith("|"):
                parts = [p.strip() for p in line.strip("|").split("|")]
                if len(parts) == 2:
                    rows.append(f"<tr><td>{parts[0]}</td><td>{parts[1]}</td></tr>")
        if rows:
            return "\n".join(rows)

    # fallback: 从 audit json 读取
    try:
        import json
        data = json.loads(Path(audit_path).read_text(encoding="utf-8"))
        values = data.get("config", {}).get("values", {})
        key_fields = [
            "model", "data", "epochs", "batch", "imgsz", "optimizer",
            "lr0", "lrf", "device", "amp", "seed", "workers",
        ]
        rows = []
        for f in key_fields:
            v = values.get(f)
            if v is not None:
                rows.append(f"<tr><td>{f}</td><td>{v}</td></tr>")
        return "\n".join(rows) if rows else f"<tr><td>-</td><td>-</td></tr>"
    except Exception:
        return f"<tr><td>完整配置</td><td style='font-size:12px;word-break:break-all;'>{audit_path}</td></tr>"


def _build_gallery(
    img_results, img_pr, img_f1, img_cm, img_cmn,
    img_labels, img_train_batch0, img_train_batch1,
    img_val_pred0, img_val_pred1,
) -> str:
    items = [
        ("训练曲线", img_results),
        ("PR 曲线", img_pr),
        ("F1 曲线", img_f1),
        ("混淆矩阵", img_cm),
        ("规范化混淆矩阵", img_cmn),
        ("标签分布", img_labels),
        ("训练批次 #0", img_train_batch0),
        ("训练批次 #1", img_train_batch1),
        ("验证预测 #0", img_val_pred0),
        ("验证预测 #1", img_val_pred1),
    ]
    cards = []
    for label, src in items:
        if src.startswith("./"):
            cards.append(f"""<div class="gallery-item"><div class="gallery-item-header">{label}</div><img src="{src}" alt="{label}" loading="lazy" /></div>""")
    return f'<div class="gallery-grid">{"".join(cards)}</div>' if cards else "<p>暂无可视化图表</p>"


# ============================================================
# Markdown 报告模板（保持不变）
# ============================================================

_REPORT_TEMPLATE = """\
# 训练报告 — {experiment_name}

## 基本信息

| 字段 | 值 |
|------|-----|
| 训练人 | {author} |
| 开始时间 | {started_at} |
| 结束时间 | {finished_at} |
| 总耗时 | {duration} |
| 任务类型 | {task} |
| 训练状态 | {status} |

## 运行环境

| 项目 | 值 |
|------|-----|
| 操作系统 | {os} |
| CPU | {cpu} |
| Python | {python_ver} |
| PyTorch | {torch_ver} |
| Ultralytics | {ultra_ver} |
{device_rows}
## 数据集

| 字段 | 值 |
|------|-----|
| 数据集名称 | {data_name} |
| 数据集路径 | {data_path} |
| 数据质量报告 | {data_quality} |

## 训练配置

| 参数 | 值 |
|------|-----|
{config_rows}
完整配置见 `{audit_path}`

## 训练结果

| 指标 | 值 |
|------|-----|
{metric_rows}
## 训练可视化

### 训练曲线
![results]({img_results})

### PR 曲线
![PR curve]({img_pr})

### F1 曲线
![F1 curve]({img_f1})

### 混淆矩阵
![confusion]({img_cm})

### 规范化混淆矩阵
![confusion normalized]({img_cmn})

### 标签分布
![labels]({img_labels})

### 训练批次预览
![train batch0]({img_train_batch0})
![train batch1]({img_train_batch1})

### 验证批次预测
![val pred0]({img_val_pred0})
![val pred1]({img_val_pred1})

## 产出文件

| 类型 | 路径 |
|------|------|
| 输出目录 | `{output_dir}` |
| 最佳权重 | `{best_weight}` |
| 最后权重 | `{last_weight}` |
| 审计快照 | `{audit_snapshot}` |
| 训练日志 | `{log_path}` |
"""


def generate_train_report(
    result: TrainResult,
    *,
    author: str = "",
    experiment_name: str = "",
    task: str = "detect",
    data_name: str = "",
    data_path_raw: str = "",
    data_quality_report_path: str | None = None,
    config_summary: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> Path:
    finished_at = datetime.now()
    if started_at is None and result.train_time is not None:
        started_at = datetime.fromtimestamp(
            finished_at.timestamp() - result.train_time
        )

    started_str = started_at.strftime("%Y-%m-%d %H:%M:%S") if started_at else "-"
    finished_str = finished_at.strftime("%Y-%m-%d %H:%M:%S")
    duration = _format_duration(result.train_time)

    status = "成功" if result.success else "失败"
    status_class = "success" if result.success else "fail"
    if not result.success:
        status += f"（错误: {result.error}）"

    # ---- 运行环境 ----
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

    # ---- 数据集 ----
    data_quality, data_quality_html = _data_quality_display(
        data_quality_report_path,
        result.output_dir,
    )

    # ---- 训练配置 ----
    if config_summary is None:
        config_summary = {}
    config_rows = "\n".join(
        f"| {k} | {v} |" for k, v in config_summary.items()
    )
    if not config_rows:
        config_rows = "| - | - |"

    # ---- 训练结果指标 ----
    metric_rows = ""
    for k, v in result.metrics.items():
        if isinstance(v, float):
            metric_rows += f"| {k} | {v:.4f} |\n"
        else:
            metric_rows += f"| {k} | {v} |\n"
    if not metric_rows:
        metric_rows = "| - | - |"

    # ---- 训练可视化 ----
    od = result.output_dir

    def _img(name: str) -> str:
        p = od / name
        return f"./{name}" if p.exists() else f"(未生成: {name})"

    img_results = _img("results.png")
    img_pr = _img("BoxPR_curve.png")
    img_f1 = _img("BoxF1_curve.png")
    img_cm = _img("confusion_matrix.png")
    img_cmn = _img("confusion_matrix_normalized.png")
    img_labels = _img("labels.jpg")
    img_train_batch0 = _img("train_batch0.jpg")
    img_train_batch1 = _img("train_batch1.jpg")
    img_val_pred0 = _img("val_batch0_pred.jpg")
    img_val_pred1 = _img("val_batch1_pred.jpg")

    # ---- 产出文件 ----
    audit_snapshot = str(result.audit_path) if result.audit_path else "-"
    log_path = str(result.log_path) if result.log_path else "-"

    # ============================================================
    # Markdown 报告
    # ============================================================
    content = _REPORT_TEMPLATE.format(
        experiment_name=experiment_name or "-",
        author=author or "-",
        started_at=started_str,
        finished_at=finished_str,
        duration=duration,
        task=task,
        status=status,
        os=os_str,
        cpu=cpu_str,
        python_ver=python_ver,
        torch_ver=torch_ver,
        ultra_ver=ultra_ver,
        device_rows=device_rows,
        data_name=data_name or "-",
        data_path=data_path_raw or "-",
        data_quality=data_quality,
        config_rows=config_rows,
        audit_path=audit_snapshot,
        metric_rows=metric_rows,
        img_results=img_results,
        img_pr=img_pr,
        img_f1=img_f1,
        img_cm=img_cm,
        img_cmn=img_cmn,
        img_labels=img_labels,
        img_train_batch0=img_train_batch0,
        img_train_batch1=img_train_batch1,
        img_val_pred0=img_val_pred0,
        img_val_pred1=img_val_pred1,
        output_dir=str(od),
        best_weight=str(result.best_weight) if result.best_weight else "-",
        last_weight=str(result.last_weight) if result.last_weight else "-",
        audit_snapshot=audit_snapshot,
        log_path=log_path,
    )

    report_path = od / "report.md"
    try:
        report_path.write_text(content, encoding="utf-8")
        logger.info(f"训练报告已生成: {report_path}")
    except OSError as e:
        logger.warning(f"训练报告写入失败: {e}")
        return report_path

    # ============================================================
    # HTML 仪表盘报告
    # ============================================================
    html_path = od / "report.html"
    try:
        html_content = _build_html_report(
            title=f"训练报告 — {experiment_name or '未命名'}",
            author=author or "-",
            started_at=started_str,
            finished_at=finished_str,
            duration=duration,
            task=task,
            status=status,
            status_class=status_class,
            os=os_str,
            cpu=cpu_str,
            python_ver=python_ver,
            torch_ver=torch_ver,
            ultra_ver=ultra_ver,
            gpu_rows=gpu_rows,
            data_name=data_name or "-",
            data_path=data_path_raw or "-",
            data_quality=data_quality_html,
            config_rows=config_rows,
            audit_path=audit_snapshot,
            metrics=result.metrics,
            metric_cards="",
            img_results=img_results,
            img_pr=img_pr,
            img_f1=img_f1,
            img_cm=img_cm,
            img_cmn=img_cmn,
            img_labels=img_labels,
            img_train_batch0=img_train_batch0,
            img_train_batch1=img_train_batch1,
            img_val_pred0=img_val_pred0,
            img_val_pred1=img_val_pred1,
            output_dir=str(od),
            best_weight=str(result.best_weight) if result.best_weight else "-",
            last_weight=str(result.last_weight) if result.last_weight else "-",
            log_path=log_path,
        )
        html_path.write_text(html_content, encoding="utf-8")
        logger.info(f"HTML 训练报告已生成: {html_path}")
    except OSError as e:
        logger.warning(f"HTML 报告写入失败: {e}")

    return report_path
