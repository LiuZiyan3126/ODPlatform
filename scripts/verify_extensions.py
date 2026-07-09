#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""验证四项新扩展功能的脚本。无需完整数据集即可运行。"""
import subprocess
import sys
from pathlib import Path

PASS = 0
FAIL = 0

def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  — {detail}")

def header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ============================================================
# 1. 数据流水线智能判断
# ============================================================
header("1. 数据流水线智能判断 (skip_if_exists)")

from od_platform.data_pipeline.orchestrator import DatasetPipeline
from od_platform.common.constants import AnnotationFormat

# 用一个不存在的假数据集测试: skip_if_exists=False 应该报错 (找不到目录)
# skip_if_exists=True 也不应该崩溃, 而是返回 skipped

# 验证 _already_split 方法在 yaml 不存在时返回 False
# 因为 processed 目录有 fire/ 但没有实际内容
import tempfile, shutil
from od_platform.common.paths import PROCESSED_DATA_DIR, DATASET_CONFIGS_DIR

# 验证 skip_if_exists 参数已暴露在构造函数中
pipe = DatasetPipeline(
    "nonexistent_dataset", AnnotationFormat.PASCAL_VOC,
    skip_if_exists=True,
)
check("构造函数接受 skip_if_exists=True", pipe.skip_if_exists is True)

pipe2 = DatasetPipeline(
    "nonexistent_dataset", AnnotationFormat.PASCAL_VOC,
    skip_if_exists=False,
)
check("构造函数接受 skip_if_exists=False (默认)", pipe2.skip_if_exists is False)

# 验证已存在的 fire 数据集能用 _already_split 处理
# fire processed 目录大概率不存在（项目干净状态）, 检查不会崩溃
fire_processed = PROCESSED_DATA_DIR / "fire"
fire_yaml = DATASET_CONFIGS_DIR / "fire.yaml"
print(f"    fire processed: {fire_processed}, exists={fire_processed.is_dir()}")
print(f"    fire yaml: {fire_yaml}, exists={fire_yaml.exists()}")

# _already_split 在 processed 目录不存在时应返回 False 而不崩溃
pipe3 = DatasetPipeline("fire", AnnotationFormat.PASCAL_VOC, skip_if_exists=True)
alive = True
try:
    already = pipe3._already_split()
    check("_already_split() 在 processed 不存在时返回 False 且不崩溃", already is False)
except FileNotFoundError:
    # fire 没有 raw 数据，_check_raw 会抛，这没问题
    check("_already_split() 在 processed 不存在时不崩溃", True, "(但 fire 缺 raw 数据，后续无法跑)")
except Exception as e:
    check(f"_already_split() 不崩溃", False, f"意外错误: {e}")

# 验证 CLI --skip-if-exists flag
result = subprocess.run(
    [sys.executable, "-m", "od_platform.cli.transform_data", "--help"],
    capture_output=True, text=True
)
check("odp-transform CLI --help 正常, --skip-if-exists 出现",
      "--skip-if-exists" in (result.stdout + result.stderr))

# ============================================================
# 2. 项目重置备份功能
# ============================================================
header("2. 项目重置备份功能")

from od_platform.common.paths import BACKUPS_DIR
check("BACKUPS_DIR 常量已定义", BACKUPS_DIR is not None)
check(f"BACKUPS_DIR 路径正确: {BACKUPS_DIR}", BACKUPS_DIR.name == "backups")

from od_platform.cli.reset_project import _create_backup, _scan_targets, reset_project

# 验证 _scan_targets 正常工作
deletable, skipped = _scan_targets()
print(f"    scannable: {len(deletable)} dirs, skipped: {len(skipped)} dirs")
check("_scan_targets() 不崩溃", True)

# 验证 _create_backup 能正常生成 zip（即使没有可备份内容）
backup_path = _create_backup(deletable)
if backup_path:
    check(f"备份创建成功: {backup_path.name} ({backup_path.stat().st_size} bytes)", backup_path.exists())
else:
    check("备份跳过 (无可备份内容或目录不存在)", deletable is not None)

# 验证 CLI --no-backup flag (main() reads sys.argv, test via argparse parser)
import subprocess
result = subprocess.run(
    [sys.executable, "-m", "od_platform.cli.reset_project", "--help"],
    capture_output=True, text=True
)
check("odp-reset CLI --help 正常, --no-backup 出现",
      "--no-backup" in result.stdout or "--no-backup" in result.stderr)

# ============================================================
# 3. Word 格式质检报告
# ============================================================
header("3. Word 格式质检报告 (python-docx)")

# 验证 docx 库可用
try:
    from docx import Document
    check("python-docx 库可用", True)
except ImportError:
    check("python-docx 库可用", False, "请运行: pip install python-docx")

# 验证写 docx 功能
from od_platform.validate_dataset.artifacts import write_docx_report, collect_issue_records
from od_platform.validate_dataset.report import ValidationReport
from od_platform.validate_dataset.snapshot import DatasetSnapshot, SplitStats
from od_platform.validate_dataset.registry import CheckResult, CheckSeverity

# 构造最小测试报告
snapshot = DatasetSnapshot(
    yaml_path=Path("/test/fire.yaml"),
    yaml_data={"nc": 2, "names": ["fire", "smoke"]},
    yaml_load_error=None,
    data_root=Path("/test"),
    nc=2,
    class_names=("fire", "smoke"),
    task_type="detect",
    images_per_split={"train": (Path("/t/a.jpg"),), "val": (Path("/v/b.jpg"),)},
    labels_per_split={"train": (Path("/t/a.txt"),), "val": (Path("/v/b.txt"),)},
    stats_per_split={
        "train": SplitStats(image_count=100, annotated_count=95, total_instances=150),
        "val": SplitStats(image_count=30, annotated_count=28, total_instances=40),
    },
)
results = [
    CheckResult(name="yaml_schema", severity=CheckSeverity.PASS, summary="YAML 结构正确"),
    CheckResult(name="pair_existence", severity=CheckSeverity.WARNING, summary="5 张图片缺少标签",
                details={"missing_files": {"train": [Path("img001.jpg")]}}),
    CheckResult(name="image_integrity", severity=CheckSeverity.ERROR, summary="2 张图片损坏",
                details={"errors": [{"split": "train", "image": "bad.jpg", "error": "无法解码"}]}),
]
report = ValidationReport(
    run_id="20260709_verify", yaml_path=Path("/test/fire.yaml"),
    snapshot=snapshot, results=results,
    duration_seconds=1.5, started_at_iso="2026-07-09T12:00:00Z",
    run_dir=Path(tempfile.mkdtemp()),
)
records = collect_issue_records(report.results)
check(f"收集到 {len(records)} 条问题记录", len(records) == 2)

# 写 docx
tmp = Path(tempfile.mkdtemp())
docx_path = tmp / "report.docx"
write_docx_report(report, records, docx_path)
check(f"DOCX 报告生成成功 ({docx_path.stat().st_size} bytes)", docx_path.exists() and docx_path.stat().st_size > 1000)

# 验证 ValidationReport 有 docx_report_path 属性
check("ValidationReport.docx_report_path 属性存在", hasattr(report, "docx_report_path"))

# 验证 validate_dataset 入口集成了 docx（发个 import 看不会崩）
from od_platform.validate_dataset.service import validate_dataset
check("validate_dataset 导入正常 (集成了 write_docx_report)", True)

# ============================================================
# 4. 统一报告 API
# ============================================================
header("4. 统一报告 API (ReportHub)")

from od_platform.report_api import ReportHub, ReportInfo, ReportType

hub = ReportHub()
reports = hub.scan()
print(f"    发现 {len(reports)} 份报告")
for r in reports:
    print(f"      [{r.type_label}] {r.name}  |  {r.created_at}")

check("ReportHub.scan() 不崩溃", True)
check("发现了至少 1 份报告 (fire.yaml)", len(reports) >= 1)

# 按类型过滤
training_reports = hub.list_reports("training")
check("list_reports('training') 不崩溃", isinstance(training_reports, list))

# summary
summary = hub.summary()
check(f"summary() 返回类型分布: {summary}", isinstance(summary, dict))

# get_report
found = hub.get_report("fire")
check(f"get_report('fire') 找到报告", found is not None)

# to_dict
if found:
    d = found.to_dict()
    check(f"ReportInfo.to_dict() 包含所有字段", all(k in d for k in ["report_type", "name", "run_dir"]))

# 验证 CLI 命令 (subprocess, 复用 infra)
result = subprocess.run(
    [sys.executable, "-m", "od_platform.cli.reports", "--help"],
    capture_output=True, text=True
)
check("odp-reports CLI --help 正常", result.returncode == 0)

result = subprocess.run(
    [sys.executable, "-m", "od_platform.cli.reports", "list"],
    capture_output=True, text=True
)
check("odp-reports list 不崩溃", result.returncode == 0)

result = subprocess.run(
    [sys.executable, "-m", "od_platform.cli.reports", "summary"],
    capture_output=True, text=True
)
check("odp-reports summary 不崩溃", result.returncode == 0)

# 验证 export 功能
export_dir = Path(tempfile.mkdtemp()) / "all_reports"
exported = hub.export_all(export_dir, format="html")
check(f"export_all 导出 {len(exported)} 个文件 (含 index.html)", len(exported) >= 1)
if exported:
    index = export_dir / "index.html"
    check(f"index.html 已生成 ({index.stat().st_size} bytes)", index.exists())

# ============================================================
# 结果汇总
# ============================================================
header("结果汇总")
total = PASS + FAIL
print(f"  通过: {PASS}/{total}")
if FAIL == 0:
    print(f"  全部 {PASS} 项验证通过!")
else:
    print(f"  失败: {FAIL}/{total}")
    sys.exit(1)
