#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py -- CP-SAT 排工排产 在线演示后端
========================================
FastAPI 服务, 负责:
  * 提供前端页面(static/index.html)
  * 暴露 /api/solve 接口, 用 CP-SAT 求解并返回排程 JSON

运行:
    python app.py
    然后在浏览器打开  http://127.0.0.1:8000
"""

import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
# 第 1 个候选项: 本目录(便于直接 import scheduler)
for p in (str(BASE), str(BASE / "libs")):
    if p not in sys.path:
        sys.path.insert(0, p)

import scheduler as sched  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
import uvicorn  # noqa: E402

app = FastAPI(title="CP-SAT 排工排产演示", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HOST, PORT = "127.0.0.1", 8000


@app.get("/")
def index():
    return FileResponse(str(BASE / "static" / "index.html"))


@app.get("/api/solve")
def solve(
    jobs: int = 6,
    machines: int = 5,
    type: str = "job",
    objective: str = "makespan",
    seed: int = 42,
    max_time: float = 10.0,
):
    """根据参数生成实例并用 CP-SAT 求解, 返回排程 JSON。"""
    t0 = time.time()
    try:
        jobs = max(2, min(30, int(jobs)))
        machines = max(2, min(20, int(machines)))
        max_time = max(0.1, min(60.0, float(max_time)))
        if objective not in ("makespan", "completion", "tardiness", "weighted"):
            objective = "makespan"

        flow_shop = (type == "flow")
        jobs_list = sched.generate_job_shop(jobs, machines, int(seed), flow_shop=flow_shop)

        # 对一些目标补充交期/权重数据(让调度更有意义)
        due_dates = None
        if objective == "tardiness":
            due_dates = {}
            for j, ops in enumerate(jobs_list):
                sum_dur = sum(o.duration for o in ops)
                due_dates[j] = int(sum_dur * 1.35)  # 略宽松的交期
        weights = {j: (j % 3 + 1) for j in range(jobs)}

        res = sched.solve(jobs_list, machines, objective=objective,
                          max_time_s=max_time, due_dates=due_dates, weights=weights)
        res["meta"] = {
            "type": "flow" if flow_shop else "job",
            "num_jobs": jobs,
            "num_machines": machines,
            "seed": int(seed),
            "objective": objective,
            "generated_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        res["statistics"]["api_wall_time_s"] = round(time.time() - t0, 4)
        return res
    except Exception as e:  # noqa: BLE001
        return {"error": "%s: %s" % (type(e).__name__, e)}


if __name__ == "__main__":
    print("CP-SAT 排工排产演示 running on http://%s:%d" % (HOST, PORT))
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")