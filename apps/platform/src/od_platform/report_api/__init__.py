#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""报告统一访问 API —— 提供跨子系统的报告发现与导出能力。

用法:
    from od_platform.report_api import ReportHub

    hub = ReportHub()
    for report in hub.scan():
        print(report.report_type, report.name, report.html_path)
"""
from od_platform.report_api.hub import ReportHub, ReportInfo, ReportType

__all__ = ["ReportHub", "ReportInfo", "ReportType"]
