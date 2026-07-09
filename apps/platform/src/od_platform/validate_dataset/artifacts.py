"""把结构化质检结果导出为问题 CSV、自包含 HTML 报告和 Word 报告。"""
from __future__ import annotations

import csv
import html
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List

from od_platform.validate_dataset.registry import CheckResult, CheckSeverity
from od_platform.validate_dataset.report import ValidationReport


@dataclass(frozen=True)
class IssueRecord:
    check_name: str
    severity: str
    split: str = ""
    file: str = ""
    line: str = ""
    issue_type: str = ""
    detail: str = ""
    recommendation: str = ""

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


_RECOMMENDATIONS = {
    "yaml_schema": "修正 dataset YAML 的 nc、names 和字段类型，使类别数量与名称表一致。",
    "missing_label": "补充与图片同名的 YOLO 标签；若图片无训练价值，则从数据集中移除。",
    "orphan_label": "恢复同名图片、修正文件名，或确认无用后删除该孤儿标签。",
    "empty_label": "确认图片确实是无目标背景图；否则补充目标标注。",
    "corrupt_image": "从原始数据重新导出或替换图片，并确认扩展名与真实编码一致。",
    "split_overlap": "只在一个 split 中保留该样本，重新划分后再次质检，避免评估数据泄漏。",
    "fingerprint_mismatch": "若变化非预期，请恢复数据；若为有意修改，请重新运行转换流程生成新指纹。",
    "fingerprint_missing": "重新运行数据转换流程，为该数据集生成可追溯指纹。",
    "fingerprint_metadata_invalid": "重新运行数据转换流程，生成结构完整且算法受支持的指纹。",
    "fingerprint_inputs_missing": "先补齐缺失文件，再重新运行数据转换与质检。",
    "field_count_mismatch": "按任务要求重写该行：detect 为 5 字段，segment 为 1+2N 字段。",
    "parse_error": "将类别 ID 改为整数、坐标改为可解析的浮点数。",
    "class_id_out_of_range": "把类别 ID 调整到 [0, nc)；同时核对 YAML names 的类别顺序。",
    "coord_out_of_range": "将归一化坐标裁剪或重新计算到 [0, 1] 范围。",
    "polygon_too_few_points": "为分割多边形提供至少 3 个有效点。",
    "non_positive_box_size": "重新标注目标框，确保 width 和 height 均大于 0。",
    "box_outside_image": "裁剪或重新计算目标框，使完整边界位于图片范围内。",
    "zero_area_polygon": "重新标注多边形，避免所有点重合或共线。",
}


def _recommendation(issue_type: str, check_name: str) -> str:
    return _RECOMMENDATIONS.get(
        issue_type,
        _RECOMMENDATIONS.get(
            check_name,
            "根据问题详情修复源数据，然后重新运行数据转换和质检。",
        ),
    )


def _record(
    result: CheckResult,
    *,
    split: str = "",
    file: str = "",
    line: object = "",
    issue_type: str,
    detail: str,
) -> IssueRecord:
    return IssueRecord(
        check_name=result.name,
        severity=result.severity,
        split=split,
        file=file,
        line=str(line),
        issue_type=issue_type,
        detail=detail,
        recommendation=_recommendation(issue_type, result.name),
    )


def _file_map_records(
    result: CheckResult,
    field: str,
    issue_type: str,
    detail: str,
) -> List[IssueRecord]:
    records = []
    for split, paths in result.details.get(field, {}).items():
        for path in paths:
            records.append(_record(
                result,
                split=split,
                file=str(path),
                issue_type=issue_type,
                detail=detail,
            ))
    return records


def _collect_from_result(result: CheckResult) -> List[IssueRecord]:
    details = result.details

    if result.name == "yaml_schema":
        return [
            _record(
                result,
                issue_type="yaml_schema",
                detail=str(problem),
            )
            for problem in details.get("problems", [])
        ]

    if result.name == "pair_existence":
        return _file_map_records(
            result,
            "missing_files",
            "missing_label",
            "图片缺少同名 YOLO 标签文件。",
        )

    if result.name == "orphan_labels":
        return _file_map_records(
            result,
            "orphan_files",
            "orphan_label",
            "标签文件没有对应图片。",
        )

    if result.name == "empty_labels":
        return _file_map_records(
            result,
            "empty_files",
            "empty_label",
            "标签文件为空，当前图片会被视为无目标背景图。",
        )

    if result.name in ("label_format", "annotation_geometry"):
        return [
            _record(
                result,
                split=str(error.get("split", "")),
                file=str(error.get("label", "")),
                line=error.get("line_no", ""),
                issue_type=str(error.get("kind", result.name)),
                detail=str(error.get("detail", "")),
            )
            for error in details.get("errors", [])
        ]

    if result.name == "image_integrity":
        return [
            _record(
                result,
                split=str(error.get("split", "")),
                file=str(error.get("image", "")),
                issue_type="corrupt_image",
                detail=str(error.get("error", "图片无法解码")),
            )
            for error in details.get("errors", [])
        ]

    if result.name == "split_uniqueness":
        records = []
        for overlap in details.get("overlaps", []):
            split = f"{overlap['split_a']}↔{overlap['split_b']}"
            for stem in overlap.get("files", []):
                records.append(_record(
                    result,
                    split=split,
                    file=str(stem),
                    issue_type="split_overlap",
                    detail="同名图片同时出现在多个 split，存在数据泄漏。",
                ))
        return records

    if result.name == "fingerprint_integrity":
        reason = str(details.get("reason", ""))
        if reason == "fingerprint_inputs_missing":
            return [
                _record(
                    result,
                    file=str(path),
                    issue_type=reason,
                    detail="指纹输入文件缺失。",
                )
                for path in details.get("missing_labels", [])
            ]
        if reason:
            changed = details.get("changed_splits", [])
            return [
                _record(
                    result,
                    split=",".join(changed),
                    issue_type=reason,
                    detail=result.summary,
                )
            ]

    if result.severity in (CheckSeverity.WARNING, CheckSeverity.ERROR):
        return [
            _record(
                result,
                issue_type=str(details.get("reason", result.name)),
                detail=result.summary,
            )
        ]
    return []


def collect_issue_records(results: Iterable[CheckResult]) -> List[IssueRecord]:
    records: List[IssueRecord] = []
    for result in results:
        records.extend(_collect_from_result(result))
    return records


def write_issues_csv(records: Iterable[IssueRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "check_name",
        "severity",
        "split",
        "file",
        "line",
        "issue_type",
        "detail",
        "recommendation",
    ]

    def csv_safe(value: object) -> object:
        # 防止用户控制的文件名或详情在 Excel 中被解释为公式。
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            {
                key: csv_safe(value)
                for key, value in record.to_dict().items()
            }
            for record in records
        )


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _severity_class(severity: str) -> str:
    return severity.lower() if severity in {
        CheckSeverity.PASS,
        CheckSeverity.INFO,
        CheckSeverity.WARNING,
        CheckSeverity.ERROR,
    } else "info"


def _render_check_rows(results: Iterable[CheckResult]) -> str:
    return "\n".join(
        "<tr>"
        f"<td><code>{_escape(result.name)}</code></td>"
        f"<td><span class='badge {_severity_class(result.severity)}'>"
        f"{_escape(result.severity)}</span></td>"
        f"<td>{_escape(result.summary)}</td>"
        "</tr>"
        for result in results
    )


def _render_issue_rows(records: Iterable[IssueRecord]) -> str:
    rows = []
    for record in records:
        file_cell = _escape(record.file) if record.file else "—"
        rows.append(
            "<tr>"
            f"<td><span class='badge {_severity_class(record.severity)}'>"
            f"{_escape(record.severity)}</span></td>"
            f"<td><code>{_escape(record.check_name)}</code></td>"
            f"<td>{_escape(record.split) or '—'}</td>"
            f"<td class='path'>{file_cell}</td>"
            f"<td>{_escape(record.line) or '—'}</td>"
            f"<td><code>{_escape(record.issue_type)}</code></td>"
            f"<td>{_escape(record.detail)}</td>"
            f"<td>{_escape(record.recommendation)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def write_html_report(
    report: ValidationReport,
    records: List[IssueRecord],
    path: Path,
) -> None:
    counts = report.counts_by_severity
    count_cards = "".join(
        f"<div class='metric {_severity_class(severity)}'>"
        f"<strong>{counts.get(severity, 0)}</strong><span>{severity}</span></div>"
        for severity in (
            CheckSeverity.PASS,
            CheckSeverity.INFO,
            CheckSeverity.WARNING,
            CheckSeverity.ERROR,
        )
    )
    split_rows = "\n".join(
        "<tr>"
        f"<td>{_escape(split)}</td>"
        f"<td>{stats.image_count}</td>"
        f"<td>{stats.annotated_count}</td>"
        f"<td>{stats.total_instances}</td>"
        "</tr>"
        for split, stats in report.snapshot.stats_per_split.items()
    )
    issues_section = (
        "<p class='empty-state'>没有发现需要记录的问题数据。</p>"
        if not records
        else (
            "<div class='table-wrap'><table><thead><tr>"
            "<th>级别</th><th>检测项</th><th>Split</th><th>文件</th>"
            "<th>行</th><th>问题类型</th><th>问题详情</th><th>修复建议</th>"
            "</tr></thead><tbody>"
            f"{_render_issue_rows(records)}</tbody></table></div>"
        )
    )
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>数据集质检报告 · {_escape(report.run_id)}</title>
  <style>
    :root {{ color-scheme: light; --ink:#172033; --muted:#667085; --line:#e4e7ec;
      --panel:#fff; --canvas:#f6f7fb; --pass:#067647; --info:#175cd3;
      --warning:#b54708; --error:#b42318; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--canvas); color:var(--ink);
      font:14px/1.55 Inter, "Segoe UI", "Microsoft YaHei", sans-serif; }}
    main {{ width:min(1440px, calc(100% - 32px)); margin:32px auto 56px; }}
    header {{ padding:28px 32px; color:white; border-radius:18px;
      background:linear-gradient(135deg,#14213d,#3157a4); box-shadow:0 16px 40px #1d2d501f; }}
    h1 {{ margin:0 0 8px; font-size:28px; }} h2 {{ margin:0 0 18px; font-size:19px; }}
    .subtitle {{ opacity:.82; }} .grid {{ display:grid; grid-template-columns:repeat(4,1fr);
      gap:12px; margin:18px 0; }}
    .metric {{ background:var(--panel); border:1px solid var(--line); border-radius:14px;
      padding:18px; display:flex; justify-content:space-between; align-items:end; }}
    .metric strong {{ font-size:28px; }} .metric span {{ color:var(--muted); font-weight:700; }}
    .metric.pass strong {{ color:var(--pass); }} .metric.info strong {{ color:var(--info); }}
    .metric.warning strong {{ color:var(--warning); }} .metric.error strong {{ color:var(--error); }}
    section {{ background:var(--panel); border:1px solid var(--line); border-radius:16px;
      padding:24px; margin-top:16px; box-shadow:0 5px 18px #1018280a; }}
    .meta {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 24px; }}
    .meta div {{ overflow-wrap:anywhere; }} .meta b {{ color:var(--muted); margin-right:8px; }}
    table {{ width:100%; border-collapse:collapse; }} th {{ background:#f9fafb;
      color:#475467; font-size:12px; text-align:left; position:sticky; top:0; }}
    th,td {{ padding:11px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
    tbody tr:hover {{ background:#fcfcfd; }} .table-wrap {{ overflow:auto; max-height:720px; }}
    .path {{ min-width:220px; max-width:420px; overflow-wrap:anywhere; }}
    code {{ font-family:"Cascadia Code",Consolas,monospace; font-size:12px; }}
    .badge {{ display:inline-block; padding:3px 8px; border-radius:999px; font-size:11px;
      font-weight:800; }} .badge.pass {{ color:var(--pass); background:#ecfdf3; }}
    .badge.info {{ color:var(--info); background:#eff8ff; }}
    .badge.warning {{ color:var(--warning); background:#fffaeb; }}
    .badge.error {{ color:var(--error); background:#fef3f2; }}
    .empty-state {{ padding:24px; text-align:center; color:var(--pass); background:#ecfdf3;
      border-radius:12px; }} .links a {{ color:#3157a4; margin-right:18px; }}
    @media(max-width:760px) {{ .grid {{ grid-template-columns:repeat(2,1fr); }}
      .meta {{ grid-template-columns:1fr; }} header,section {{ padding:20px; }} }}
  </style>
</head>
<body><main>
  <header>
    <h1>YOLO 数据集质检报告</h1>
    <div class="subtitle">运行 {_escape(report.run_id)} · 总体级别 {_escape(report.overall_severity)}
      · 耗时 {report.duration_seconds:.3f}s</div>
  </header>
  <div class="grid">{count_cards}</div>
  <section><h2>数据集信息</h2>
    <div class="meta">
      <div><b>YAML</b>{_escape(report.yaml_path)}</div>
      <div><b>任务</b>{_escape(report.snapshot.task_type)}</div>
      <div><b>类别数</b>{_escape(report.snapshot.nc)}</div>
      <div><b>类别</b>{_escape(", ".join(report.snapshot.class_names))}</div>
      <div><b>开始时间</b>{_escape(report.started_at_iso)}</div>
      <div><b>问题记录</b>{len(records)} 条</div>
    </div>
  </section>
  <section><h2>数据集摘要</h2>
    <table><thead><tr><th>Split</th><th>图片数</th><th>有标注图片</th><th>实例数</th>
    </tr></thead><tbody>{split_rows}</tbody></table>
  </section>
  <section><h2>检测项结果</h2>
    <table><thead><tr><th>检测项</th><th>级别</th><th>摘要</th>
    </tr></thead><tbody>{_render_check_rows(report.results)}</tbody></table>
  </section>
  <section><h2>问题数据与修复建议</h2>{issues_section}</section>
  <section class="links"><h2>原始产物</h2>
    <a href="report.json">JSON 报告</a><a href="issues.csv">问题 CSV</a>
  </section>
</main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


def write_docx_report(
    report: ValidationReport,
    records: list[IssueRecord],
    path: Path,
) -> None:
    """生成 Word (.docx) 格式的质检报告。"""
    from docx import Document
    from docx.shared import Cm, Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn

    doc = Document()

    # 设置默认字体为宋体以支持中文
    style = doc.styles["Normal"]
    font = style.font
    font.name = "宋体"
    font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    def _set_cell_font(cell, text: str, bold: bool = False, size: Pt | None = None):
        cell.text = ""
        p = cell.paragraphs[0]
        run = p.add_run(text)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        run.bold = bold
        if size:
            run.font.size = size

    # ---- 标题 ----
    title = doc.add_heading("YOLO 数据集质检报告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(
        f"运行 {report.run_id}  |  总体级别 {report.overall_severity}  |  耗时 {report.duration_seconds:.3f}s"
    )
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(102, 102, 102)

    doc.add_paragraph()

    # ---- 概览卡片 ----
    doc.add_heading("检测概览", level=1)
    counts = report.counts_by_severity
    overview_table = doc.add_table(rows=1, cols=4)
    overview_table.style = "Light Grid Accent 1"
    overview_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = overview_table.rows[0].cells
    severities = [CheckSeverity.PASS, CheckSeverity.INFO, CheckSeverity.WARNING, CheckSeverity.ERROR]
    for i, sev in enumerate(severities):
        _set_cell_font(hdr[i], f"{sev}: {counts.get(sev, 0)}", bold=True, size=Pt(11))
    doc.add_paragraph()

    # ---- 数据集信息 ----
    doc.add_heading("数据集信息", level=1)
    info_table = doc.add_table(rows=6, cols=2)
    info_table.style = "Light Grid Accent 1"
    info_data = [
        ("YAML 路径", str(report.yaml_path)),
        ("任务类型", report.snapshot.task_type),
        ("类别数", str(report.snapshot.nc)),
        ("类别", ", ".join(report.snapshot.class_names)),
        ("开始时间", report.started_at_iso),
        ("问题记录", f"{len(records)} 条"),
    ]
    for i, (k, v) in enumerate(info_data):
        _set_cell_font(info_table.rows[i].cells[0], k, bold=True)
        _set_cell_font(info_table.rows[i].cells[1], v)
    doc.add_paragraph()

    # ---- 数据集摘要 ----
    doc.add_heading("数据集摘要", level=1)
    split_headers = ["Split", "图片数", "有标注图片", "实例数"]
    split_data = [
        [split, str(stats.image_count), str(stats.annotated_count), str(stats.total_instances)]
        for split, stats in report.snapshot.stats_per_split.items()
    ]
    split_table = doc.add_table(rows=1 + len(split_data), cols=4)
    split_table.style = "Light Grid Accent 1"
    for i, h in enumerate(split_headers):
        _set_cell_font(split_table.rows[0].cells[i], h, bold=True)
    for r, row_data in enumerate(split_data):
        for c, val in enumerate(row_data):
            _set_cell_font(split_table.rows[r + 1].cells[c], val)
    doc.add_paragraph()

    # ---- 检测项结果 ----
    doc.add_heading("检测项结果", level=1)
    check_headers = ["检测项", "级别", "摘要"]
    check_table = doc.add_table(rows=1 + len(report.results), cols=3)
    check_table.style = "Light Grid Accent 1"
    for i, h in enumerate(check_headers):
        _set_cell_font(check_table.rows[0].cells[i], h, bold=True)
    for r, result in enumerate(report.results):
        _set_cell_font(check_table.rows[r + 1].cells[0], result.name)
        _set_cell_font(check_table.rows[r + 1].cells[1], result.severity)
        _set_cell_font(check_table.rows[r + 1].cells[2], result.summary)
    doc.add_paragraph()

    # ---- 问题数据与修复建议 ----
    doc.add_heading("问题数据与修复建议", level=1)
    if records:
        issue_headers = ["级别", "检测项", "Split", "文件", "行", "问题类型", "问题详情", "修复建议"]
        issue_table = doc.add_table(rows=1 + len(records), cols=8)
        issue_table.style = "Light Grid Accent 1"
        for i, h in enumerate(issue_headers):
            _set_cell_font(issue_table.rows[0].cells[i], h, bold=True, size=Pt(9))
        for r, record in enumerate(records):
            row_cells = issue_table.rows[r + 1].cells
            _set_cell_font(row_cells[0], record.severity)
            _set_cell_font(row_cells[1], record.check_name)
            _set_cell_font(row_cells[2], record.split or "—")
            _set_cell_font(row_cells[3], record.file or "—")
            _set_cell_font(row_cells[4], record.line or "—")
            _set_cell_font(row_cells[5], record.issue_type)
            _set_cell_font(row_cells[6], record.detail)
            _set_cell_font(row_cells[7], record.recommendation)
    else:
        p = doc.add_paragraph("没有发现需要记录的问题数据。")
        p.runs[0].font.color.rgb = RGBColor(6, 118, 71)

    doc.add_paragraph()

    # ---- 原始产物链接 ----
    doc.add_heading("原始产物", level=1)
    doc.add_paragraph(f"JSON 报告: report.json", style="List Bullet")
    doc.add_paragraph(f"问题 CSV: issues.csv", style="List Bullet")
    doc.add_paragraph(f"HTML 报告: report.html", style="List Bullet")

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
