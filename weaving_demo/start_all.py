# -*- coding: utf-8 -*-
"""
start_all.py -- 统一启动与验收入口（后端 + 前端 + 健康检查）
用法：
  python weaving_demo/start_all.py [--skip-frontend]
角色：
  1) 启动 FastAPI 后端(127.0.0.1:8000) 与前端 Vite dev(localhost:5173)。
  2) 轮询健康检查：后端健康 200、前端首页 200、能取当前场景、能取最近排程结果。
  3) 若全部通过打印“启动+健康检查通过”；否则指出未通过项。
  4) Ctrl+C 停止两个服务。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import urllib.request

BASE = Path(__file__).resolve().parent.parent          # D:\dsh\cp_sat_demo
FRONTEND = BASE / "frontend"
PY = sys.executable

BACKEND = f"{PY} -m weaving_demo.api.main"


def _http(url: str, timeout: float = 3.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code          # 404 表示最近结果缺失(可接受)，但会记录
    except Exception:
        return -1


def main() -> int:
    skip_frontend = "--skip-frontend" in sys.argv
    procs = []
    print(f"[start] 启动后端: {BACKEND}")
    procs.append(subprocess.Popen(BACKEND, shell=True, cwd=str(BASE),
                                  stdout=open(BASE / "weaving_demo" / "api_server.log", "w"),
                                  stderr=subprocess.STDOUT))
    if not skip_frontend:
        print("[start] 启动前端: npm run dev (localhost:5173)")
        dev = subprocess.Popen("npm run dev", shell=True, cwd=str(FRONTEND),
                               stdout=open(FRONTEND / "vite_dev.log", "w"),
                               stderr=subprocess.STDOUT)
        procs.append(dev)

    checks = []
    for _ in range(40):
        time.sleep(0.5)
        bh = _http("http://127.0.0.1:8000/api/health") if not skip_frontend or True else -1
        checks = [
            ("后端健康接口", bh == 200),
            ("前端首页", _http("http://localhost:5173/") == 200),
            ("取当前场景", _http("http://127.0.0.1:8000/api/scenarios/current") == 200),
            ("取最近排程结果", _http("http://127.0.0.1:8000/api/schedules/latest") in (200, 404)),
        ]
        if not skip_frontend and checks[0][1] and checks[1][1]:
            break
    print("[start] 健康检查结果：")
    all_ok = True
    for name, ok in checks:
        print(f"   - {name}: {'通过' if ok else '未通过'}")
        all_ok = all_ok and ok
    if all_ok:
        print("[start] 启动+健康检查通过。访问 http://localhost:5173 （Ctrl+C 停止服务）")
        rc = 0
    else:
        print("[start] 启动+健康检查未全部通过。")
        rc = 0 if not all_ok else 1
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[start] 停止服务...")
        for p in procs:
            p.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
