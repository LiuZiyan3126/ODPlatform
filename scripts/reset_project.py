#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :reset_project.py
# @Time      :2026/6/30 13:05:06
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
import  sys
from pathlib import  Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLATFORM_SRC = REPO_ROOT / "apps" / "platform" / "src"

sys.path.insert(0, str(PLATFORM_SRC))


from od_platform.cli.reset_project import main

if __name__ == "__main__":
    sys.exit(main())