# -*- coding: utf-8 -*-
"""pytest 公共配置：把项目根与 libs 加入 sys.path，确保可导入 weaving_demo。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # D:\dsh\cp_sat_demo
for p in (str(ROOT), str(ROOT / "libs"), str(ROOT / "weaving_demo")):
    if p not in sys.path:
        sys.path.insert(0, p)
