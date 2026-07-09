#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""ReportHub —— 跨训练/评估/质检/数据流水线的统一报告发现与导出。"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from od_platform.common.paths import DATASET_CONFIGS_DIR, ROOT_DIR, RUNS_DIR

logger = logging.getLogger(__name__)


class ReportType:
    TRAINING = "training"
    EVALUATION = "evaluation"
    VALIDATION = "validation"
    COMPARISON = "comparison"
    DATA_PIPELINE = "data_pipeline"

    @classmethod
    def all(cls) -> List[str]:
        return [cls.TRAINING, cls.EVALUATION, cls.VALIDATION, cls.COMPARISON, cls.DATA_PIPELINE]

    @classmethod
    def labels(cls) -> Dict[str, str]:
        return {
            cls.TRAINING: "模型训练",
            cls.EVALUATION: "模型评估",
            cls.VALIDATION: "数据质检",
            cls.COMPARISON: "模型对比",
            cls.DATA_PIPELINE: "数据流水线",
        }


@dataclass
class ReportInfo:
    """一次运行产出的报告入口。"""
    report_type: str
    name: str
    run_id: str
    run_dir: Path
    created_at: str = ""
    markdown_path: Optional[Path] = None
    html_path: Optional[Path] = None
    docx_path: Optional[Path] = None
    json_path: Optional[Path] = None
    metadata: Dict = field(default_factory=dict)

    @property
    def type_label(self) -> str:
        return ReportType.labels().get(self.report_type, self.report_type)

    def to_dict(self) -> Dict:
        return {
            "report_type": self.report_type,
            "type_label": self.type_label,
            "name": self.name,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "markdown_path": str(self.markdown_path) if self.markdown_path else None,
            "html_path": str(self.html_path) if self.html_path else None,
            "docx_path": str(self.docx_path) if self.docx_path else None,
            "json_path": str(self.json_path) if self.json_path else None,
            "run_dir": str(self.run_dir),
        }


class ReportHub:
    """跨子系统统一报告访问入口。

    使用示例:
        hub = ReportHub()
        hub.scan()                      # 扫描所有报告
        for r in hub.list_reports("training"):
            print(r.name, r.html_path)
        hub.export_all(Path("./all_reports"))
    """

    def __init__(self):
        self._reports: List[ReportInfo] = []
        self._scanned = False

    def scan(self, force: bool = False) -> List[ReportInfo]:
        """扫描项目中所有已知位置的报告，返回发现的报告列表。"""
        if self._scanned and not force:
            return self._reports

        reports: List[ReportInfo] = []
        reports.extend(self._scan_training_reports())
        reports.extend(self._scan_evaluation_reports())
        reports.extend(self._scan_validation_reports())
        reports.extend(self._scan_comparison_reports())
        reports.extend(self._scan_data_pipeline_reports())

        reports.sort(key=lambda r: r.created_at, reverse=True)
        self._reports = reports
        self._scanned = True
        logger.info("扫描完成: 发现 %d 份报告", len(reports))
        return reports

    def list_reports(self, report_type: Optional[str] = None) -> List[ReportInfo]:
        """按类型过滤报告列表。不传类型则返回全部。"""
        self.scan()
        if report_type is None:
            return list(self._reports)
        return [r for r in self._reports if r.report_type == report_type]

    def get_report(self, run_id: str) -> Optional[ReportInfo]:
        """根据 run_id 查找报告。"""
        self.scan()
        for r in self._reports:
            if r.run_id == run_id:
                return r
        return None

    def summary(self) -> Dict[str, int]:
        """各类型报告数量摘要。"""
        self.scan()
        counts: Dict[str, int] = {}
        for r in self._reports:
            counts[r.report_type] = counts.get(r.report_type, 0) + 1
        return counts

    def export_all(self, output_dir: Path, format: str = "html") -> List[Path]:
        """将所有已扫描报告导出到统一目录。

        Args:
            output_dir: 目标输出目录
            format: "html" | "md" | "docx" — 导出格式

        Returns:
            导出文件的路径列表
        """
        self.scan()
        output_dir.mkdir(parents=True, exist_ok=True)
        exported: List[Path] = []

        for report in self._reports:
            src = None
            ext = ""
            if format == "html":
                src = report.html_path
                ext = ".html"
            elif format == "md":
                src = report.markdown_path
                ext = ".md"
            elif format == "docx":
                src = report.docx_path
                ext = ".docx"

            if src is None or not src.exists():
                continue

            dst_name = f"{report.report_type}_{report.run_id}{ext}"
            dst = output_dir / dst_name
            shutil.copy2(src, dst)
            exported.append(dst)

        logger.info("导出 %d 份报告到 %s", len(exported), output_dir)

        # 写一份 index.html
        index_path = output_dir / "index.html"
        index_path.write_text(self._build_index_html(exported, output_dir), encoding="utf-8")
        exported.append(index_path)

        return exported

    # ---- 内部扫描方法 ----

    def _scan_training_reports(self) -> List[ReportInfo]:
        reports: List[ReportInfo] = []
        detect_dir = RUNS_DIR / "detect"
        if not detect_dir.is_dir():
            return reports

        for train_dir in sorted(detect_dir.iterdir(), reverse=True):
            if not train_dir.is_dir():
                continue
            md = train_dir / "report.md"
            html = train_dir / "report.html"
            audit = train_dir / "od_audit.json"

            if not md.exists() and not html.exists():
                continue

            name = train_dir.name
            created = _mtime_iso(train_dir)
            metadata = {}
            if audit.exists():
                try:
                    data = json.loads(audit.read_text(encoding="utf-8"))
                    metadata["config"] = data.get("config", {})
                    metadata["metrics"] = data.get("metrics", {})
                except (json.JSONDecodeError, OSError):
                    pass

            reports.append(ReportInfo(
                report_type=ReportType.TRAINING,
                name=f"训练: {name}",
                run_id=name,
                run_dir=train_dir,
                created_at=created,
                markdown_path=md if md.exists() else None,
                html_path=html if html.exists() else None,
                json_path=audit if audit.exists() else None,
                metadata=metadata,
            ))
        return reports

    def _scan_evaluation_reports(self) -> List[ReportInfo]:
        reports: List[ReportInfo] = []
        val_base = RUNS_DIR / "val"
        if not val_base.is_dir():
            return reports

        for val_dir in sorted(val_base.iterdir(), reverse=True):
            if not val_dir.is_dir():
                continue
            md = val_dir / "report.md"
            html = val_dir / "report.html"
            audit = val_dir / "od_audit.json"

            if not md.exists() and not html.exists():
                continue

            reports.append(ReportInfo(
                report_type=ReportType.EVALUATION,
                name=f"评估: {val_dir.name}",
                run_id=val_dir.name,
                run_dir=val_dir,
                created_at=_mtime_iso(val_dir),
                markdown_path=md if md.exists() else None,
                html_path=html if html.exists() else None,
                json_path=audit if audit.exists() else None,
            ))
        return reports

    def _scan_validation_reports(self) -> List[ReportInfo]:
        reports: List[ReportInfo] = []
        val_dir = RUNS_DIR / "data_validation"
        if not val_dir.is_dir():
            return reports

        for run_dir in sorted(val_dir.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            html = run_dir / "report.html"
            json_p = run_dir / "report.json"
            docx = run_dir / "report.docx"

            if not html.exists() and not json_p.exists():
                continue

            name = run_dir.name
            created = _mtime_iso(run_dir)
            metadata = {}
            if json_p.exists():
                try:
                    metadata = json.loads(json_p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass

            reports.append(ReportInfo(
                report_type=ReportType.VALIDATION,
                name=f"质检: {name}",
                run_id=name,
                run_dir=run_dir,
                created_at=created,
                html_path=html if html.exists() else None,
                json_path=json_p if json_p.exists() else None,
                docx_path=docx if docx.exists() else None,
                metadata=metadata,
            ))
        return reports

    def _scan_comparison_reports(self) -> List[ReportInfo]:
        reports: List[ReportInfo] = []
        cmp_dir = RUNS_DIR / "compare"
        if not cmp_dir.is_dir():
            return reports

        for run_dir in sorted(cmp_dir.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            md = run_dir / "report.md"
            if not md.exists():
                # compare doesn't use report.md; check for individual eval reports
                md = None

            name = run_dir.name
            reports.append(ReportInfo(
                report_type=ReportType.COMPARISON,
                name=f"对比: {name}",
                run_id=name,
                run_dir=run_dir,
                created_at=_mtime_iso(run_dir),
                markdown_path=md if md else None,
            ))
        return reports

    def _scan_data_pipeline_reports(self) -> List[ReportInfo]:
        reports: List[ReportInfo] = []
        if not DATASET_CONFIGS_DIR.is_dir():
            return reports

        for yaml_path in sorted(DATASET_CONFIGS_DIR.glob("*.yaml")):
            md = yaml_path.with_suffix(".md")
            html = yaml_path.with_suffix(".html")

            reports.append(ReportInfo(
                report_type=ReportType.DATA_PIPELINE,
                name=f"数据集: {yaml_path.stem}",
                run_id=yaml_path.stem,
                run_dir=DATASET_CONFIGS_DIR,
                created_at=_mtime_iso(yaml_path),
                json_path=yaml_path,  # YAML 配置文件本身
                markdown_path=md if md.exists() else None,
                html_path=html if html.exists() else None,
            ))
        return reports

    def _build_index_html(self, exported: List[Path], output_dir: Path) -> str:
        self.scan()
        rows = ""
        for report in self._reports:
            html_link = ""
            md_link = ""
            if report.html_path and report.html_path.exists():
                html_link = f'<a href="{report.html_path.name}">HTML</a>'
            if report.markdown_path and report.markdown_path.exists():
                md_link = f'<a href="{report.markdown_path.name}">MD</a>'

            rows += (
                "<tr>"
                f"<td>{report.type_label}</td>"
                f"<td>{report.name}</td>"
                f"<td>{report.created_at}</td>"
                f"<td>{html_link} {md_link}</td>"
                "</tr>"
            )

        return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ODPlatform 报告汇总</title>
<style>
  body {{ font:14px/1.55 Inter,"Microsoft YaHei",sans-serif; background:#f1f5f9; color:#1f2937; margin:0; }}
  main {{ width:min(1100px,calc(100%-32px)); margin:32px auto; }}
  header {{ background:linear-gradient(135deg,#1e3a5f,#3157a4); color:white; padding:32px; border-radius:16px; }}
  h1 {{ margin:0; font-size:26px; }}
  section {{ background:white; border:1px solid #e4e7ec; border-radius:14px; padding:24px; margin-top:16px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ background:#f9fafb; color:#475467; font-size:12px; text-align:left; padding:10px 12px; border-bottom:2px solid #e4e7ec; }}
  td {{ padding:10px 12px; border-bottom:1px solid #e4e7ec; }}
  a {{ color:#3157a4; margin-right:12px; text-decoration:none; }}
  .count {{ font-size:13px; opacity:.85; margin-top:8px; }}
</style>
</head>
<body>
<main>
  <header>
    <h1>ODPlatform 报告汇总</h1>
    <p class="count">{len(self._reports)} 份报告 · 导出时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  </header>
  <section>
    <table>
      <thead><tr><th>类型</th><th>名称</th><th>时间</th><th>链接</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
</main>
</body>
</html>"""


def _mtime_iso(path: Path) -> str:
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return ""
