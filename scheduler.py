#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scheduler.py -- CP-SAT 排工排产调度求解器
=================================================
使用 Google OR-Tools CP-SAT 求解带先序约束 + 机器独占约束的
经典 Job-Shop / Flow-Shop 生产排程问题。

模型要素
--------
- 每个工单(Job)由若干工序(Operation)组成, 工序按固定工艺顺序执行(先序约束)
- 每道工序需要在指定的机器(Machine)上加工, 加工时长为 duration
- 同一台机器同一时刻只能加工一道工序(机器独占 -> AddNoOverlap)
- 优化目标可选:
    * makespan        : 最小化总完工时间(最后一个工序结束时间)
    * completion      : 最小化所有工单完工时间之和
    * tardiness       : 最小化总拖期时间(相对交期)
    * weighted        : 最小化加权完工时间(工单权重)

典型用法
--------
python scheduler.py --jobs 6 --machines 5 --objective makespan --seed 42
python scheduler.py --input problem.json --output schedule.json
"""

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

# 将解压出的 ortools 依赖加入路径(本 demo 通过 wheel 解压方式安装, 无 pip)
_LIBS = Path(__file__).resolve().parent / "libs"
if _LIBS.exists():
    sys.path.insert(0, str(_LIBS))

from ortools.sat.python import cp_model  # noqa: E402


# --------------------------------------------------------------------------- #
# 问题对象模型
# --------------------------------------------------------------------------- #
class Operation:
    """一道工序: 需要在某台机器上加工一段时间。"""

    __slots__ = ("job", "index", "machine", "duration")

    def __init__(self, job: int, index: int, machine: int, duration: int):
        self.job = job          # 所属工单编号
        self.index = index      # 工序在工单工艺路线中的序号(0 起)
        self.machine = machine  # 使用哪台机器(机器编号)
        self.duration = duration  # 加工时长(单位: 时间单位, 例如分钟)


def generate_job_shop(n_jobs: int, n_machines: int, seed: int,
                      rng=None, dur_min=2, dur_max=9, flow_shop=False):
    """随机生成一个调度实例。

    flow_shop=False  -> 每个工单随机走一条机器顺序(Job-Shop)
    flow_shop=True   -> 所有工单按相同的机器顺序(Flow-Shop)
    """
    rng = rng if rng is not None else random.Random(seed)
    jobs = []
    machine_rank = list(range(n_machines))
    for j in range(n_jobs):
        if flow_shop:
            order = list(machine_rank)              # 统一的机器顺序
        else:
            order = list(machine_rank)
            rng.shuffle(order)                      # 随机工艺路线(机器的排列)
        ops = []
        for k, m in enumerate(order):
            d = rng.randint(dur_min, dur_max)
            ops.append(Operation(job=j, index=k, machine=m, duration=d))
        jobs.append(ops)
    return jobs


def problem_to_dict(jobs, meta):
    """把问题(不包含解)序列化为字典。"""
    return {
        "meta": meta,
        "jobs": [
            {
                "order": [o.machine for o in ops],
                "durations": [o.duration for o in ops],
            }
            for ops in jobs
        ],
    }


# --------------------------------------------------------------------------- #
# CP-SAT 建模与求解
# --------------------------------------------------------------------------- #
def solve(jobs, n_machines, objective="makespan", max_time_s=10.0,
          due_dates=None, weights=None):
    """用 CP-SAT 求解调度问题, 返回包含统计与解的字典。

    参数:
        jobs       : List[List[Operation]], 每个工单的工序序列
        n_machines : 机器数量
        objective  : makespan | completion | tardiness | weighted
        max_time_s : 求解时间上限(秒)
        due_dates  : dict {job_id: due} 或 None
        weights    : dict {job_id: weight} 或 None
    """
    t0 = time.time()
    model = cp_model.CpModel()

    # 水平线: 所有工序时长之和的 1.5 倍作为安全上界
    total_dur = sum(op.duration for ops in jobs for op in ops)
    horizon = max(1, int(total_dur * 1.5)) + 1

    # 为每道工序创建 开始/结束/区间 变量
    starts, ends, intervals = {}, {}, {}
    for ops in jobs:
        for op in ops:
            s = model.NewIntVar(0, horizon, f"s_{op.job}_{op.index}")
            e = model.NewIntVar(0, horizon, f"e_{op.job}_{op.index}")
            iv = model.NewIntervalVar(s, op.duration, e, f"iv_{op.job}_{op.index}")
            starts[(op.job, op.index)] = s
            ends[(op.job, op.index)] = e
            intervals[(op.job, op.index)] = iv

    # 1) 先序约束: 同一工单内, 后一道工序在前一道之后开始
    for ops in jobs:
        for k in range(1, len(ops)):
            prev = ops[k - 1]
            cur = ops[k]
            model.Add(starts[(cur.job, cur.index)] >= ends[(prev.job, prev.index)])

    # 2) 机器独占约束: 每台机器上的工序区间彼此不重叠
    machine_intervals = {m: [] for m in range(n_machines)}
    for ops in jobs:
        for op in ops:
            machine_intervals[op.machine].append(intervals[(op.job, op.index)])
    for m in range(n_machines):
        model.AddNoOverlap(machine_intervals[m])

    # 各工单的最后一道工序结束时间(即工单完工时间)
    completion_vars = {}
    for ops in jobs:
        last = ops[-1]
        completion_vars[last.job] = ends[(last.job, last.index)]

    # -------------------------------------------------------------- 目标函数
    if objective == "makespan":
        makespan = model.NewIntVar(0, horizon, "makespan")
        for e in ends.values():
            model.Add(makespan >= e)
        model.Minimize(makespan)
    elif objective == "completion":
        model.Minimize(sum(completion_vars[j] for j in completion_vars))
    elif objective == "tardiness":
        tardiness = {}
        for job_id, comp in completion_vars.items():
            due = (due_dates or {}).get(job_id, horizon)
            t = model.NewIntVar(0, horizon, f"tardy_{job_id}")
            model.Add(t >= comp - due)
            tardiness[job_id] = t
        model.Minimize(sum(tardiness.values()))
    elif objective == "weighted":
        model.Minimize(sum(
            (weights or {}).get(j, 1) * completion_vars[j]
            for j in completion_vars
        ))
    else:
        raise ValueError(f"未知目标: {objective}")

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_time_s
    solver.parameters.num_workers = 8
    # 允许一定数值精度与更好的搜索
    solver.parameters.random_seed = 0

    status = solver.Solve(model)

    status_name = solver.StatusName(status)
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    result = {
        "meta": {},   # 由调用方补充
        "statistics": {
            "status": status_name,
            "objective_value": solver.ObjectiveValue() if feasible else None,
            "best_objective_bound": solver.BestObjectiveBound() if feasible else None,
            "solve_time_s": round(solver.WallTime(), 4),
            "num_operations": sum(len(ops) for ops in jobs),
            "num_jobs": len(jobs),
            "num_machines": n_machines,
            "num_conflicts": solver.NumConflicts(),
            "num_branches": solver.NumBranches(),
        },
        "machines": list(range(n_machines)),
        "jobs": [],
        "schedule": [],
    }

    if feasible:
        makespan_val = 0
        for ops in jobs:
            for op in ops:
                s = solver.Value(starts[(op.job, op.index)])
                e = solver.Value(ends[(op.job, op.index)])
                makespan_val = max(makespan_val, e)
                result["schedule"].append({
                    "job": op.job,
                    "op": op.index,
                    "machine": op.machine,
                    "duration": op.duration,
                    "start": int(s),
                    "end": int(e),
                })
        # 按工单组织(方便渲染)
        job_map = {}
        for item in result["schedule"]:
            job_map.setdefault(item["job"], []).append(item)
        for jid in sorted(job_map):
            ops_sorted = sorted(job_map[jid], key=lambda x: x["op"])
            result["jobs"].append({
                "id": jid,
                "name": f"工单 {jid}",
                "due_date": (due_dates or {}).get(jid),
                "weight": (weights or {}).get(jid, 1),
                "operations": ops_sorted,
                "completion": ops_sorted[-1]["end"] if ops_sorted else 0,
            })
        result["statistics"]["makespan"] = makespan_val

    result["statistics"]["total_wall_time_s"] = round(time.time() - t0, 4)
    return result


# --------------------------------------------------------------------------- #
# 命令行入口
# --------------------------------------------------------------------------- #
def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="CP-SAT 排工排产求解器")
    ap.add_argument("--jobs", type=int, default=6, help="工单数量")
    ap.add_argument("--machines", type=int, default=5, help="机器数量")
    ap.add_argument("--type", choices=["job", "flow"], default="job",
                    help="job=Job-Shop(每单不同工艺路线), flow=Flow-Shop(统一工艺路线)")
    ap.add_argument("--seed", type=int, default=42, help="随机种子")
    ap.add_argument("--objective", choices=["makespan", "completion", "tardiness", "weighted"],
                    default="makespan", help="优化目标")
    ap.add_argument("--max-time", type=float, default=10.0, help="求解时间上限(秒)")
    ap.add_argument("--input", type=str, default=None, help="读取问题 JSON 文件")
    ap.add_argument("--output", type=str, default=None,
                    help="输出调度结果 JSON 文件(默认 schedule.json)")
    ap.add_argument("--due", type=int, default=0, help="交期基准(用于拖期目标), 0 表示自动")
    args = ap.parse_args()

    # 生成/读取问题
    if args.input:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        n_jobs = data["meta"]["num_jobs"]
        n_machines = data["meta"]["num_machines"]
        seed = data["meta"].get("seed", 0)
        flow_shop = data["meta"].get("type") == "flow"
        jobs = generate_job_shop(n_jobs, n_machines, seed, flow_shop=flow_shop)
    else:
        n_jobs, n_machines, seed = args.jobs, args.machines, args.seed
        jobs = generate_job_shop(n_jobs, n_machines, seed, flow_shop=(args.type == "flow"))

    # 交期与权重
    if args.due:
        # 用一个较宽松的交期: 平均总加工时间除以机器数 * 系数
        due_dates = {}
        for j, ops in enumerate(jobs):
            sum_dur = sum(o.duration for o in ops)
            due_dates[j] = max(sum_dur, int(sum_dur * args.due))
    else:
        due_dates = None
    weights = {j: (j % 3 + 1) for j in range(n_jobs)}

    meta = {
        "type": "flow" if (args.type == "flow") else "job",
        "num_jobs": n_jobs,
        "num_machines": n_machines,
        "seed": seed,
        "objective": args.objective,
        "generated_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    result = solve(jobs, n_machines, objective=args.objective,
                   max_time_s=args.max_time, due_dates=due_dates, weights=weights)
    result["meta"] = meta
    result["problem_details"] = problem_to_dict(jobs, meta)

    out = args.output or str(here / "schedule.json")
    Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    # 控制台摘要
    st = result["statistics"]
    print("=" * 56)
    print(f"  目标        : {args.objective}")
    print(f"  工单/机器   : {n_jobs} / {n_machines}  ({meta['type']}-shop, seed={seed})")
    print(f"  求解状态    : {st['status']}")
    if st["objective_value"] is not None:
        print(f"  目标值      : {st['objective_value']:.2f}")
        if "makespan" in st:
            print(f"  总完工(Makespan): {st['makespan']}")
    print(f"  求解耗时    : {st['solve_time_s']} s")
    print(f"  写入文件    : {out}")
    print("=" * 56)
    # 打印甘特图文本预览
    if result["schedule"]:
        print_preview(result)


def print_preview(result):
    """在终端打印一个简单的文本甘特图预览。"""
    jobs = result["jobs"]
    makespan = result["statistics"].get("makespan", 0) or 1
    width = 70
    scale = max(1.0, width / makespan)
    print("\n[文本甘特图预览]  每行 = 一台机器, 数字 = 工单号")
    env = {("J%d-O%d" % (it["job"], it["op"])): it for it in result["schedule"]}
    # 按机器分行
    for m in result["machines"]:
        line = [" "] * (int(makespan * scale) + 1)
        for it in result["schedule"]:
            if it["machine"] != m:
                continue
            a = int(it["start"] * scale)
            b = max(a + 1, int(it["end"] * scale))
            for x in range(a, min(b, len(line))):
                line[x] = str(it["job"] % 10)
        print(f"M{m}: " + "".join(line))
    print("     " + "0" + " " * (width - 1) + str(makespan))


if __name__ == "__main__":
    main()
