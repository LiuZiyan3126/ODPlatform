#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :__init__.py
# @Time      :2026/6/29 13:38:23
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
if __name__ == "__main__":
    # 运行时获取实际路径信息
    import sys, os, platform

    print("\n===== 环境信息 =====")
    print(f"解释器路径: {sys.executable}")
    print(f"脚本路径: {os.path.abspath(__file__)}")
    print(f"操作系统: {platform.system()} {platform.release()}")

    run_code = 0
