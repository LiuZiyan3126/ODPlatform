from pathlib import Path

from od_platform.validate_dataset.registry import CheckContext, list_check_names
from od_platform.validate_dataset.service import run_all_checks
from od_platform.common.paths import LOGGING_DIR
from od_platform.common.logging_utils import get_logger

get_logger(
    base_path=LOGGING_DIR,
    log_type="数据质检测试",
    temp_log=False
)

print(f"已经注册的check: {list_check_names()}")

ctx = CheckContext(yaml_path=Path(r"C:\Users\Lenovo\Desktop\ODPlatform\apps\platform\configs\datasets\rsod.yaml"))
results = run_all_checks(ctx)
for r in results:
    print(r.severity, r.name, '-', r.summary)