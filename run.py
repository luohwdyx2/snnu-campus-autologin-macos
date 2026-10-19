#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台入口（launchd 直接调用本文件）
==================================
用法：run.py agent
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from snnu_autologin.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["agent"]))
