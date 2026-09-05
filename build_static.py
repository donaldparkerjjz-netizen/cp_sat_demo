#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_static.py -- 生成完全自包含的静态演示页 demo.html
========================================================
读取 static/index.html, 把 CP-SAT 求解结果内嵌到页面中, 得到不依赖后端的
独立 HTML。双击即可在任何浏览器打开查看甘特图。

用法:
    python build_static.py [--jobs 7 --machines 6 --objective makespan --seed 7]
"""

import argparse
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "libs"))

import scheduler as sched  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=7)
    ap.add_argument("--machines", type=int, default=6)
    ap.add_argument("--type", choices=["job", "flow"], default="job")
    ap.add_argument("--objective", choices=["makespan", "completion", "tardiness", "weighted"],
                    default="makespan")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--max-time", type=float, default=10.0)
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    jobs = sched.generate_job_shop(args.jobs, args.machines, args.seed,
                                   flow_shop=(args.type == "flow"))
    weights = {j: (j % 3 + 1) for j in range(args.jobs)}
    due_dates = None
    if args.objective == "tardiness":
        due_dates = {j: int(sum(o.duration for o in ops) * 1.35) for j, ops in enumerate(jobs)}

    res = sched.solve(jobs, args.machines, objective=args.objective,
                      max_time_s=args.max_time, due_dates=due_dates, weights=weights)
    res["meta"] = {
        "type": args.type, "num_jobs": args.jobs, "num_machines": args.machines,
        "seed": args.seed, "objective": args.objective,
        "generated_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    html = (BASE / "static" / "index.html").read_text(encoding="utf-8")
    data_json = json.dumps(res, ensure_ascii=False)  # 已是 JSON 字符串

    # 注入内嵌数据, 并切换到静态模式
    html = html.replace("window.__SCHEDULE__ = null;",
                        "window.__SCHEDULE__ = " + data_json + ";")
    html = html.replace("window.__STATIC__ = false;", "window.__STATIC__ = true;")

    out = args.out or str(BASE / "demo.html")
    Path(out).write_text(html, encoding="utf-8")

    st = res["statistics"]
    print("=" * 56)
    print("已生成静态演示页:", out)
    print("实例: %d 工单 x %d 机器 (%s-shop), 目标=%s" % (
        args.jobs, args.machines, args.type, args.objective))
    print("状态: %s  目标值: %s  Makespan: %s  求解耗时: %.4fs" % (
        st["status"], st["objective_value"], st.get("makespan"), st["solve_time_s"]))
    print("=" * 56)


if __name__ == "__main__":
    main()
