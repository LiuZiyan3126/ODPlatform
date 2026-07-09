#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""odp-reports — 统一报告查询与导出 CLI。"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from od_platform.common.logging_utils import get_logger
from od_platform.common.paths import LOGGING_DIR
from od_platform.report_api import ReportHub, ReportType

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERR = 1


def _setup_logging() -> None:
    get_logger(base_path=LOGGING_DIR, log_type="reports", temp_log=False)


def cmd_list(args: argparse.Namespace) -> int:
    hub = ReportHub()
    hub.scan()
    report_type = args.type

    reports = hub.list_reports(report_type)
    if not reports:
        print("(未发现报告)")
        return EXIT_OK

    type_label = ""
    if report_type:
        type_label = f" [{ReportType.labels().get(report_type, report_type)}]"
    print(f"共发现 {len(reports)} 份报告{type_label}:\n")

    for i, r in enumerate(reports, 1):
        links = []
        if r.html_path:
            links.append(f"HTML: {r.html_path}")
        if r.markdown_path:
            links.append(f"MD: {r.markdown_path}")
        if r.docx_path:
            links.append(f"DOCX: {r.docx_path}")
        if r.json_path:
            links.append(f"JSON: {r.json_path}")

        print(f"  [{i}] [{r.type_label}] {r.name}")
        print(f"      时间: {r.created_at}  |  ID: {r.run_id}")
        if links:
            print(f"      产物: {'  '.join(links)}")
        print()

    # 汇总
    summary = hub.summary()
    parts = [f"{ReportType.labels().get(k, k)}: {v}" for k, v in summary.items()]
    print(f"类型分布: {', '.join(parts)}")
    return EXIT_OK


def cmd_show(args: argparse.Namespace) -> int:
    hub = ReportHub()
    report = hub.get_report(args.run_id)
    if report is None:
        print(f"未找到 run_id={args.run_id!r} 的报告")
        return EXIT_ERR

    print(f"报告详情: {report.name}")
    print(f"  类型:      {report.type_label}")
    print(f"  Run ID:    {report.run_id}")
    print(f"  创建时间:  {report.created_at}")
    print(f"  运行目录:  {report.run_dir}")
    print(f"  Markdown:  {report.markdown_path or '-'}")
    print(f"  HTML:      {report.html_path or '-'}")
    print(f"  DOCX:      {report.docx_path or '-'}")
    print(f"  JSON:      {report.json_path or '-'}")

    if report.metadata:
        print(f"  元数据字段: {', '.join(report.metadata.keys())}")
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    hub = ReportHub()
    output = Path(args.output)
    fmt = args.format

    exported = hub.export_all(output, format=fmt)
    print(f"导出完成: {len(exported) - 1} 份报告 + index.html → {output.resolve()}")
    for p in exported:
        if p.name != "index.html":
            print(f"  {p.name}")
    return EXIT_OK


def cmd_summary(_args: argparse.Namespace) -> int:
    hub = ReportHub()
    hub.scan()
    summary = hub.summary()
    if not summary:
        print("(未发现报告)")
        return EXIT_OK

    total = sum(summary.values())
    print(f"共 {total} 份报告:\n")
    for rtype, count in summary.items():
        label = ReportType.labels().get(rtype, rtype)
        print(f"  {label}: {count}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    _setup_logging()

    parser = argparse.ArgumentParser(
        prog="odp-reports",
        description="ODPlatform 统一报告查询与导出工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # list
    p_list = sub.add_parser("list", help="列出所有报告")
    p_list.add_argument("--type", choices=ReportType.all(), help="按报告类型过滤")

    # show
    p_show = sub.add_parser("show", help="查看报告详情")
    p_show.add_argument("run_id", help="报告 run_id")

    # export
    p_export = sub.add_parser("export", help="导出所有报告到统一目录")
    p_export.add_argument("--output", "-o", required=True, help="输出目录")
    p_export.add_argument("--format", "-f", choices=["html", "md", "docx"], default="html")

    # summary
    sub.add_parser("summary", help="报告类型数量摘要")

    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "show":
        return cmd_show(args)
    if args.command == "export":
        return cmd_export(args)
    if args.command == "summary":
        return cmd_summary(args)

    parser.print_help()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
