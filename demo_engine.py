# -*- coding: utf-8 -*-
"""
demo_engine.py -- 工厂排工排产系统 Demo 核心引擎 (基于 OR-Tools CP-SAT)
==============================================================================
本 Demo 聚焦"织造车间·整经 → 穿综穿筘 → 织造"三个工序的短期排产:
  * 织造是瓶颈工序: 先/主目标确定织造任务在织机上的机台、顺序与起止时间(小时)。
  * 整经与穿综穿筘为前置准备: 依据织造计划"反向"推导, 使经轴(整经+穿综穿筘完成)
    在织机了机(上一产品结束)前及时准备到位, 减少织机等待经轴。
  * 排产粒度 1 小时, 未来 7 天滚动( hours = days*24 ), 支持意外情况(插单/停用/改交期)重排。
  * 目标: 优先按期按量(优先级加权拖期最小) + 减少改品番/原品番仕挂 + 经轴就绪(反向拉动)。

时间轴: days 天 × 24 h = T 个小时槽位(整数小时)。每台设备与工序均按小时占用。
求解器: OR-Tools CP-SAT, 返回最优(OPTIMAL)或当前最优可行解(FEASIBLE)。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import datetime

_THIS = os.path.dirname(os.path.abspath(__file__))
# 把预置的 ortools / openpyxl 加入路径(离线环境亦可运行)
for _p in (os.path.join(_THIS, "libs"),):
    if os.path.isdir(_p):
        sys.path.insert(0, _p)

from ortools.sat.python import cp_model  # noqa: E402


# ======================================================================
# 一、基础数据(默认场景: 织造车间·整经-穿综穿筘-织造)
# ======================================================================
DEFAULT_SCENARIO = {
    "name": "织造车间·整经-穿综穿筘-织造",
    "days": 7,
    "hours_per_day": 24,
    "work_start_h": 0,       # 每日工作起始小时(0-24)
    "work_end_h": 24,        # 每日工作结束小时(0-24)
    "rest_days": [7],        # 工厂日历: 第7天(周日)休息, 全天不排产

    # ---- 资源: 织机(织造, 瓶颈) / 整经机 / 穿综穿筘工位 ----
    "looms": [   # 织机
        {"id": "L1", "name": "织机1", "team": "A组", "eff": 1.0},
        {"id": "L2", "name": "织机2", "team": "A组", "eff": 1.0},
        {"id": "L3", "name": "织机3", "team": "A组", "eff": 1.0},
        {"id": "L4", "name": "织机4", "team": "B组", "eff": 1.1},
        {"id": "L5", "name": "织机5", "team": "B组", "eff": 0.95},
        {"id": "L6", "name": "织机6", "team": "B组", "eff": 1.0},
    ],
    "warp_machines": [  # 整经机
        {"id": "W1", "name": "整经机1", "team": "整经组", "eff": 1.0},
        {"id": "W2", "name": "整经机2", "team": "整经组", "eff": 1.0},
    ],
    "draw_stations": [  # 穿综穿筘工位
        {"id": "DR1", "name": "穿综穿筘1", "team": "穿综组", "eff": 1.0},
        {"id": "DR2", "name": "穿综穿筘2", "team": "穿综组", "eff": 1.0},
    ],

    # ---- 产品(织物): rate=织造速度(米/时), beam_len=单经轴可织长度(米, 决定了机), ----
    #      warp_h=整经一只经轴工时(时), draw_h=穿综穿筘一只经轴工时(时)
    "products": {
        "P1": {"name": "涤塔夫190", "rate": 60, "beam_len": 4000, "warp_h": 5,  "draw_h": 2},
        "P2": {"name": "尼丝纺",     "rate": 72, "beam_len": 4000, "warp_h": 6,  "draw_h": 2},
        "P3": {"name": "牛津布",     "rate": 48, "beam_len": 3200, "warp_h": 7,  "draw_h": 3},
        "P4": {"name": "塔丝隆",     "rate": 56, "beam_len": 3600, "warp_h": 5,  "draw_h": 2},
    },

    # ---- 产品-织机适配(可有部分机台织不了某些品种) ----
    "loom_eligibility": {
        "P1": ["L1", "L2", "L3", "L4", "L5"],
        "P2": ["L1", "L2", "L4", "L5", "L6"],
        "P3": ["L3", "L4", "L6"],
        "P4": ["L2", "L3", "L5", "L6"],
    },
    # ---- 产品-整经机 / 产品-穿综穿筘 适配(默认都可用) ----
    "warp_eligibility": {"P1": ["W1", "W2"], "P2": ["W1", "W2"],
                         "P3": ["W1", "W2"], "P4": ["W1", "W2"]},
    "draw_eligibility": {"P1": ["DR1", "DR2"], "P2": ["DR1", "DR2"],
                         "P3": ["DR1", "DR2"], "P4": ["DR1", "DR2"]},

    # ---- 织机换型/仕挂(小时): product_change_h=改品番(换不同品种), same_product_h=原品番仕挂 ----
    "changeover": {"product_change_h": 3, "same_product_h": 1},

    # ---- 织造订单(生产单): qty=米, due=交期(小时, 1..168), pri=优先级(越大越急) ----
    "orders": [
        {"id": "O01", "product": "P1", "qty": 3600, "due":  64, "pri": 9, "type": "normal", "source": "合同"},
        {"id": "O02", "product": "P2", "qty": 3200, "due":  80, "pri": 8, "type": "normal", "source": "合同"},
        {"id": "O03", "product": "P3", "qty": 2400, "due":  88, "pri": 7, "type": "normal", "source": "预测"},
        {"id": "O04", "product": "P4", "qty": 2800, "due":  72, "pri": 8, "type": "normal", "source": "合同"},
        {"id": "O05", "product": "P1", "qty": 3200, "due": 104, "pri": 6, "type": "normal", "source": "合同"},
        {"id": "O06", "product": "P2", "qty": 4000, "due": 120, "pri": 7, "type": "normal", "source": "预测"},
        {"id": "O07", "product": "P3", "qty": 2000, "due": 112, "pri": 5, "type": "normal", "source": "合同"},
        {"id": "O08", "product": "P4", "qty": 3200, "due": 128, "pri": 6, "type": "normal", "source": "预测"},
        {"id": "O09", "product": "P1", "qty": 2400, "due": 136, "pri": 4, "type": "normal", "source": "合同"},
        {"id": "O10", "product": "P2", "qty": 2800, "due": 144, "pri": 6, "type": "normal", "source": "急单"},
        {"id": "O11", "product": "P3", "qty": 3200, "due": 152, "pri": 5, "type": "normal", "source": "合同"},
        {"id": "O12", "product": "P4", "qty": 3600, "due": 160, "pri": 4, "type": "normal", "source": "预测"},
    ],
}


# ======================================================================
# 二、场景 -> 求解上下文(索引结构)
# ======================================================================
def scenario_to_ctx(sc: dict) -> dict:
    """把基础数据字典转化为求解所需的索引结构。"""
    looms = [m["id"] for m in sc["looms"]]
    loom_info = {m["id"]: m for m in sc["looms"]}
    warp_machines = [m["id"] for m in sc["warp_machines"]]
    warp_info = {m["id"]: m for m in sc["warp_machines"]}
    draw_stations = [m["id"] for m in sc["draw_stations"]]
    draw_info = {m["id"]: m for m in sc["draw_stations"]}

    products = sc["products"]
    prod_ids = list(products.keys())
    loom_elig = {p: [m for m in sc["loom_eligibility"][p] if m in looms] for p in prod_ids}
    warp_elig = {p: [m for m in sc.get("warp_eligibility", {}).get(p, warp_machines)
                     if m in warp_machines] for p in prod_ids}
    draw_elig = {p: [m for m in sc.get("draw_eligibility", {}).get(p, draw_stations)
                     if m in draw_stations] for p in prod_ids}

    days = sc["days"]; hpd = sc["hours_per_day"]
    T = days * hpd
    rest_days = sc.get("rest_days", [])
    # 计算不可用小时集(休息日整天 + 每工作日窗之外)
    off_hours = set()
    for t in range(T):
        day = t // hpd + 1          # 1-based
        hour_in_day = t % hpd
        if day in rest_days:
            off_hours.add(t)
        elif hour_in_day < sc.get("work_start_h", 0) or hour_in_day >= sc.get("work_end_h", 24):
            off_hours.add(t)
    # 将可用小时切分为连续可用段(用于区间不跨不可用小时)
    segments = _available_segments(T, off_hours)

    orders = []
    for i, o in enumerate(sc["orders"]):
        p = o["product"]
        rate = products[p]["rate"]
        beam_len = products[p]["beam_len"]
        orders.append({
            "idx": i, "id": o["id"], "product": p,
            "qty": int(o["qty"]), "due": int(o["due"]), "pri": int(o["pri"]),
            "type": o.get("type", "normal"), "source": o.get("source", "合同"),
            "rate": rate, "beam_len": beam_len,
            "warp_h": int(math.ceil(products[p]["warp_h"])),
            "draw_h": int(math.ceil(products[p]["draw_h"])),
            # 每(织机)织造时长(按机台效率折算, 整数小时)
            "hard_due": o.get("hard_due"), "fixed_loom": o.get("fixed_loom"),
        })
    # 每订单每织机织造时长 cache
    def weave_h(i, m):
        o = orders[i]; p = o["product"]
        eff = loom_info[m].get("eff", 1.0) or 1.0
        return max(1, int(math.ceil(o["qty"] / (products[p]["rate"] * eff))))

    return {
        "scenario": sc,
        "days": days, "hours_per_day": hpd, "T": T,
        "rest_days": rest_days, "off_hours": off_hours, "segments": segments,
        "looms": looms, "loom_info": loom_info, "loom_elig": loom_elig,
        "warp_machines": warp_machines, "warp_info": warp_info, "warp_elig": warp_elig,
        "draw_stations": draw_stations, "draw_info": draw_info, "draw_elig": draw_elig,
        "prod_ids": prod_ids, "products": products,
        "orders": orders,
        "changeover": sc.get("changeover", {"product_change_h": 3, "same_product_h": 1}),
        "weave_h": weave_h,
        "unavailable": sc.get("unavailable", {}),     # {"L1":[hour,...]} 停机
        "max_hours": sc.get("max_hours", {}),          # {"L1":max_weave_hours}
        "soft_bias": sc.get("soft_bias", {}),
    }


def _available_segments(T: int, off_hours: set) -> list:
    """把 [0,T) 切成若干连续可用段 [(lo,hi)...], lo<=t<hi 为可用小时。"""
    segs = []
    cur = None
    for t in range(T):
        if t in off_hours:
            if cur is not None:
                segs.append((cur[0], cur[1])); cur = None
        else:
            if cur is None:
                cur = (t, t + 1)
            else:
                cur = (cur[0], t + 1)
    if cur is not None:
        segs.append((cur[0], cur[1]))
    return segs or [(0, T)]


def allowed_looms(ctx, order) -> list[str]:
    """订单可用织机: 若 NL 固定机台则仅那台; 否则按适配矩阵。"""
    fix = order.get("fixed_loom")
    if fix and fix in ctx["looms"]:
        return [fix]
    return [m for m in ctx["loom_elig"][order["product"]] if m in ctx["looms"]]


# ======================================================================
# 三、CP-SAT 建模 + 求解(织造优先, 前置工序反向拉动)
# ======================================================================
def solve(ctx: dict, objective: str = "balanced",
          max_time_s: float = 30.0, num_workers: int = 8,
          weights: dict | None = None):
    """
    硬约束:
      1) 产品-织机适配(含固定织机) —— 只在 allowed 织机上空闲指派
      2) 织机独占 —— 每织机同时最多 1 个织造任务(AddNoOverlap)
      3) 换型/仕挂 —— 相邻织造任务在织机上需留 product_change_h(改品番)
         或 same_product_h(原品番仕挂) 空档
      4) 经轴前置 —— 整经(经轴)在前, 穿综穿筘随后, 且在织造开始前完成
         (经轴及时到位, 织机不等待经轴 —— 反向拉动)
      5) 工厂日历(休息日/工作窗) —— 任务不得落在不可用小时
    软目标(加权最小化):
      优先级加权拖期(主) / 改品番·仕挂(换型)最少 / 经轴就绪反向(越接近织造开始越好)
      未排产订单惩罚(优先按期按量)
    """
    sc = ctx["scenario"]
    orders = ctx["orders"]
    looms = ctx["looms"]
    warp_machines = ctx["warp_machines"]
    draw_stations = ctx["draw_stations"]
    T = ctx["T"]
    products = ctx["products"]
    changeover = ctx["changeover"]
    loom_elig = ctx["loom_elig"]
    warp_elig = ctx["warp_elig"]
    draw_elig = ctx["draw_elig"]

    model = cp_model.CpModel()

    # ---- 织造(织机)指派与区间 ----
    z = {}          # z[(i,m)] = 订单 i 是否在织机 m
    iw = {}         # iw[(i,m)] = 订单 i 在织机 m 的织造可选区间
    sw = {}; ew = {}  # sw/ew[(i,m)] 起/止小时
    for i, o in enumerate(orders):
        for m in allowed_looms(ctx, o):
            z[(i, m)] = model.NewBoolVar(f"z_{o['id']}_{m}")
            dur = ctx["weave_h"](i, m)
            s = model.NewIntVar(0, T, f"s_{o['id']}_{m}")
            e = model.NewIntVar(0, T, f"e_{o['id']}_{m}")
            sw[(i, m)] = s; ew[(i, m)] = e
            iw[(i, m)] = model.NewOptionalIntervalVar(s, dur, e, z[(i, m)], f"iv_{o['id']}_{m}")

    # ---- 整经(经轴) 指派与区间 ----
    zw = {}; iwarp = {}; swa = {}; ewa = {}
    for i, o in enumerate(orders):
        for wm in warp_elig[o["product"]]:
            zw[(i, wm)] = model.NewBoolVar(f"zw_{o['id']}_{wm}")
            s = model.NewIntVar(0, T, f"sw_{o['id']}_{wm}")
            e = model.NewIntVar(0, T, f"ew_{o['id']}_{wm}")
            swa[(i, wm)] = s; ewa[(i, wm)] = e
            iwarp[(i, wm)] = model.NewOptionalIntervalVar(s, o["warp_h"], e, zw[(i, wm)], f"iv_{o['id']}_{wm}")

    # ---- 穿综穿筘 指派与区间 ----
    zd = {}; idraw = {}; sdr = {}; edr = {}
    for i, o in enumerate(orders):
        for ds in draw_elig[o["product"]]:
            zd[(i, ds)] = model.NewBoolVar(f"zd_{o['id']}_{ds}")
            s = model.NewIntVar(0, T, f"sd_{o['id']}_{ds}")
            e = model.NewIntVar(0, T, f"ed_{o['id']}_{ds}")
            sdr[(i, ds)] = s; edr[(i, ds)] = e
            idraw[(i, ds)] = model.NewOptionalIntervalVar(s, o["draw_h"], e, zd[(i, ds)], f"id_{o['id']}_{ds}")

    # ---- 每个订单恰好在 1 台织机(可容忍不排: 允许为 0, 计入未排产惩罚) ----
    present = {}
    for i, o in enumerate(orders):
        al = allowed_looms(ctx, o)
        p = model.NewBoolVar(f"present_{o['id']}")
        present[i] = p
        model.Add(sum(z[(i, m)] for m in al) == p)
        # 整经/穿综与织造同步出现
        model.Add(sum(zw[(i, wm)] for wm in warp_elig[o["product"]]) == p)
        model.Add(sum(zd[(i, ds)] for ds in draw_elig[o["product"]]) == p)

    # ---- 每个订单的"规范"起止: 织造/整经/穿综/经轴就绪 ----
    w_start = {}; w_end = {}; wap_start = {}; wap_end = {}; dr_start = {}; dr_end = {}; ready = {}
    for i, o in enumerate(orders):
        w_start[i] = model.NewIntVar(0, T, f"ws_{o['id']}")
        w_end[i] = model.NewIntVar(0, T, f"we_{o['id']}")
        wap_start[i] = model.NewIntVar(0, T, f"wps_{o['id']}")
        wap_end[i] = model.NewIntVar(0, T, f"wpe_{o['id']}")
        dr_start[i] = model.NewIntVar(0, T, f"drs_{o['id']}")
        dr_end[i] = model.NewIntVar(0, T, f"dre_{o['id']}")
        ready[i] = dr_end[i]     # 经轴就绪 = 穿综穿筘完成时刻
        for m in allowed_looms(ctx, o):
            model.Add(sw[(i, m)] == w_start[i]).OnlyEnforceIf(z[(i, m)])
            model.Add(ew[(i, m)] == w_end[i]).OnlyEnforceIf(z[(i, m)])
        for wm in warp_elig[o["product"]]:
            model.Add(swa[(i, wm)] == wap_start[i]).OnlyEnforceIf(zw[(i, wm)])
            model.Add(ewa[(i, wm)] == wap_end[i]).OnlyEnforceIf(zw[(i, wm)])
        for ds in draw_elig[o["product"]]:
            model.Add(sdr[(i, ds)] == dr_start[i]).OnlyEnforceIf(zd[(i, ds)])
            model.Add(edr[(i, ds)] == dr_end[i]).OnlyEnforceIf(zd[(i, ds)])

    # ---- 前后置: 整经(经轴) -> 穿综穿筘 -> 织造开始(经轴及时到位) ----
    for i, o in enumerate(orders):
        model.Add(wap_end[i] <= dr_start[i]).OnlyEnforceIf(present[i])
        model.Add(dr_end[i] <= w_start[i]).OnlyEnforceIf(present[i])   # 织机不等待经轴

    # ---- 织机独占 + 换型/仕挂衔接(序列相关 setup) ----
    for m in looms:
        iv_list = [iw[(i, m)] for i, o in enumerate(orders) if m in allowed_looms(ctx, o)]
        if iv_list:
            model.AddNoOverlap(iv_list)
        # 序列相关 setup: 任意两订单同机台时按先后留空档
        elig_i = [i for i, o in enumerate(orders) if m in allowed_looms(ctx, o)]
        for a in range(len(elig_i)):
            for b in range(a + 1, len(elig_i)):
                i, j = elig_i[a], elig_i[b]
                pi, pj = orders[i]["product"], orders[j]["product"]
                gap = changeover.get("product_change_h", 3) if pi != pj else changeover.get("same_product_h", 1)
                ob = model.NewBoolVar(f"ord_{m}_{orders[i]['id']}_{orders[j]['id']}")
                za, zb = z[(i, m)], z[(j, m)]
                model.Add(ew[(i, m)] + gap <= sw[(j, m)]).OnlyEnforceIf([za, zb, ob])
                model.Add(ew[(j, m)] + gap <= sw[(i, m)]).OnlyEnforceIf([za, zb, ob.Not()])

    # ---- 整经机独占 / 穿综工位独占 ----
    for wm in warp_machines:
        lst = [iwarp[(i, wm)] for i, o in enumerate(orders) if wm in warp_elig[o["product"]]]
        if lst:
            model.AddNoOverlap(lst)
    for ds in draw_stations:
        lst = [idraw[(i, ds)] for i, o in enumerate(orders) if ds in draw_elig[o["product"]]]
        if lst:
            model.AddNoOverlap(lst)

    # ---- 工厂日历: 区间必须落在某一连续可用段内 ----
    segments_c = ctx["segments"]
    all_presence = (
        [(z[(i, m)], sw[(i, m)], ew[(i, m)]) for i, o in enumerate(orders) for m in allowed_looms(ctx, o)] +
        [(zw[(i, wm)], swa[(i, wm)], ewa[(i, wm)]) for i, o in enumerate(orders) for wm in warp_elig[o["product"]]] +
        [(zd[(i, ds)], sdr[(i, ds)], edr[(i, ds)]) for i, o in enumerate(orders) for ds in draw_elig[o["product"]]]
    )
    if len(segments_c) == 1:
        seg_lo, seg_hi = segments_c[0]
        for (p_, s_, e_) in all_presence:
            model.Add(s_ >= seg_lo).OnlyEnforceIf(p_)
            model.Add(e_ <= seg_hi).OnlyEnforceIf(p_)
    else:
        for (p_, s_, e_) in all_presence:
            segbools = []
            for k, (lo, hi) in enumerate(segments_c):
                b = model.NewBoolVar(f"seg_{s_}_{k}")
                segbools.append(b)
                model.Add(s_ >= lo).OnlyEnforceIf([p_, b])
                model.Add(e_ <= hi).OnlyEnforceIf([p_, b])
            model.Add(sum(segbools) >= 1).OnlyEnforceIf(p_)

    # ---- NL 硬约束: 织机停用小时 / 排产时长上限 / 交期不晚于 hard_due ----
    for m, slots in ctx.get("unavailable", {}).items():
        if m not in looms:
            continue
        for slot in slots:
            tt = int(slot) - 1
            if 0 <= tt < T:
                for i, o in enumerate(orders):
                    if m in allowed_looms(ctx, o):
                        # 织造区间不得跨该小时(此处强制织造起点 >= tt+1 或止点 <= tt)
                        model.Add(sw[(i, m)] >= tt + 1).OnlyEnforceIf(z[(i, m)])
    for m, n in ctx.get("max_hours", {}).items():
        if m not in looms:
            continue
        model.Add(sum(ctx["weave_h"](i, m) * z[(i, m)]
                      for i, o in enumerate(orders) if m in allowed_looms(ctx, o)) <= int(n))
    for i, o in enumerate(orders):
        if o.get("hard_due"):
            model.Add(w_end[i] <= int(o["hard_due"])).OnlyEnforceIf(present[i])

    # ---- 目标: 优先级加权拖期 + 换型少 + 经轴反向就绪 ----
    UN_SCHED_PENALTY = 10_000
    prio_tard = []
    for i, o in enumerate(orders):
        tard = model.NewIntVar(0, T, f"tard_{o['id']}")
        model.Add(tard >= w_end[i] - o["due"]).OnlyEnforceIf(present[i])
        model.Add(tard >= 0)
        prio_tard.append(int(o["pri"]) * tard)
    prio_term = sum(prio_tard)

    # 换型/仕挂代理: 鼓励同产品集中(减少织机上产品-织机组合数)
    has = []
    for m in looms:
        for p in ctx["prod_ids"]:
            rel = [i for i, o in enumerate(orders) if o["product"] == p and m in allowed_looms(ctx, o)]
            if not rel:
                continue
            h = model.NewBoolVar(f"has_{m}_{p}")
            for i in rel:
                model.Add(h >= z[(i, m)])
            model.Add(h <= sum(z[(i, m)] for i in rel))
            has.append(h)
    chg_term = sum(has)

    # 经轴就绪反向: 透轴完工越接近织造开始越好(减少经轴过早堆料/闲置)
    jit = []
    for i, o in enumerate(orders):
        d = model.NewIntVar(0, T, f"jit_{o['id']}")
        model.Add(d == w_start[i] - dr_end[i]).OnlyEnforceIf(present[i])
        model.Add(d >= 0)
        jit.append(d)
    jit_term = sum(jit)

    # 未排产惩罚(优先按期按量)
    unsch = sum((1 - present[i]) for i in range(len(orders)))
    unsch_term = model.NewIntVar(0, len(orders), "unsch")
    model.Add(unsch_term == unsch)

    w = weights or {"priority": 10.0, "changeover": 0.3, "jit": 0.05, "unscheduled": 1000.0}
    obj_terms = [
        ("priority_due", prio_term, w.get("priority", 10.0)),
        ("changeover", chg_term, w.get("changeover", 0.3)),
        ("beam_jit", jit_term, w.get("jit", 0.05)),
        ("unscheduled", unsch_term, w.get("unscheduled", 1000.0)),
    ]
    obj = sum(term * wt for _, term, wt in obj_terms)
    model.Minimize(obj)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(max_time_s)
    solver.parameters.num_workers = int(num_workers)
    solver.parameters.relative_gap_limit = 0.01
    t0 = time.time()
    status = solver.Solve(model)
    solve_time = time.time() - t0
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return {
        "status": solver.StatusName(status), "feasible": feasible,
        "solve_time_s": round(solve_time, 3),
        "objective_value": solver.ObjectiveValue() if feasible else None,
        "solver": solver, "model": model,
        "z": z, "zw": zw, "zd": zd,
        "iw": iw, "iwarp": iwarp, "idraw": idraw,
        "sw": sw, "ew": ew, "swa": swa, "ewa": ewa, "sdr": sdr, "edr": edr,
        "w_start": w_start, "w_end": w_end,
        "wap_start": wap_start, "wap_end": wap_end,
        "dr_start": dr_start, "dr_end": dr_end,
        "present": present, "has": has,
        "obj_terms": obj_terms, "w": w,
    }


# ======================================================================
# 四、解提取 + 分析
# ======================================================================
def extract(ctx: dict, sres: dict) -> dict:
    """从求解结果提取织造/整经/穿综穿筘任务、经轴就绪与各工序分析。"""
    sc = ctx["scenario"]
    orders = ctx["orders"]
    looms = ctx["looms"]
    warp_machines = ctx["warp_machines"]
    draw_stations = ctx["draw_stations"]
    looms_info = ctx["loom_info"]; warp_info = ctx["warp_info"]; draw_info = ctx["draw_info"]
    T = ctx["T"]
    products = ctx["products"]
    solver = sres["solver"]
    avail_h = max(1, T - len(ctx["off_hours"]))

    def val(v):
        return int(round(solver.Value(v)))

    weave_sched, jobs = [], []
    warp_sched, draw_sched = [], []
    for i, o in enumerate(orders):
        pres = solver.Value(sres["present"][i])
        # 织造
        m0 = None
        for m in allowed_looms(ctx, o):
            if solver.Value(sres["z"][(i, m)]) == 1:
                m0 = m; break
        if not pres or not m0:
            jobs.append(_job_entry(o, None, None, None, None, None, None, None, None, None, None, None))
            continue
        dur = ctx["weave_h"](i, m0)
        ws = val(sres["w_start"][i]); we = val(sres["w_end"][i])
        wap_s = val(sres["wap_start"][i]); wap_e = val(sres["wap_end"][i])
        dr_s = val(sres["dr_start"][i]); dr_e = val(sres["dr_end"][i])
        ready_h = dr_e
        comp = we
        tard = max(0, comp - o["due"])
        linfo = looms_info[m0]
        jobs.append(_job_entry(o, m0, linfo, ws, we, dur, wap_s, wap_e, dr_s, dr_e, ready_h, tard))
        weave_sched.append({
            "job": o["id"], "product": o["product"], "machine": m0, "name": linfo["name"],
            "process": "weave", "team": linfo["team"], "priority": o["pri"],
            "qty": o["qty"], "start_h": ws, "end_h": we, "duration": dur,
        })
        # 整经
        wm0 = None
        for wm in warp_machines:
            if solver.Value(sres["zw"][(i, wm)]) == 1:
                wm0 = wm; break
        if wm0:
            warp_sched.append({
                "job": o["id"], "product": o["product"], "machine": wm0, "name": warp_info[wm0]["name"],
                "process": "warp", "team": warp_info[wm0]["team"], "priority": o["pri"],
                "qty": o["qty"], "start_h": wap_s, "end_h": wap_e, "duration": o["warp_h"],
            })
        # 穿综穿筘
        ds0 = None
        for ds in draw_stations:
            if solver.Value(sres["zd"][(i, ds)]) == 1:
                ds0 = ds; break
        if ds0:
            draw_sched.append({
                "job": o["id"], "product": o["product"], "machine": ds0, "name": draw_info[ds0]["name"],
                "process": "draw", "team": draw_info[ds0]["team"], "priority": o["pri"],
                "qty": o["qty"], "start_h": dr_s, "end_h": dr_e, "duration": o["draw_h"],
            })

    # 合并为单一甘特 schedule(前端按 process 分带)
    schedule = weave_sched + warp_sched + draw_sched

    # 资源利用率(按工序)
    def resource_util(res_list, info, sched):
        out = {}
        for r in res_list:
            used = sum(1 for s in sched if s["machine"] == r)
            # 用时(小时) = 各任务时长之和; 这里用记录数即小时(每任务占用 duration 小时)
            used_h = sum(s["duration"] for s in sched if s["machine"] == r)
            info_r = info[r]
            out[r] = {
                "machine": r, "name": info_r["name"], "team": info_r.get("team", ""),
                "process": info_r.get("process", "loom"),
                "used_hours": used_h, "capacity_hours": avail_h,
                "utilization_pct": round(100.0 * used_h / avail_h, 1),
                "num_jobs": used,
            }
        return out

    loom_util = {}
    for m in looms:
        used_h = sum(s["duration"] for s in weave_sched if s["machine"] == m)
        loftr = looms_info[m]
        loom_util[m] = {"machine": m, "name": loftr["name"], "team": loftr.get("team", ""),
                        "process": "loom", "used_hours": used_h, "capacity_hours": avail_h,
                        "utilization_pct": round(100.0 * used_h / avail_h, 1),
                        "num_jobs": sum(1 for s in weave_sched if s["machine"] == m)}
    warp_util = resource_util(warp_machines, warp_info, warp_sched)
    draw_util = resource_util(draw_stations, draw_info, draw_sched)
    for d in warp_util.values(): d["process"] = "warp"
    for d in draw_util.values(): d["process"] = "draw"
    machine_util = {**loom_util, **warp_util, **draw_util}

    # 工艺链: 织造为核心, 整经/穿综为前置; 利用率按工序汇总
    def agg(util_map):
        if not util_map: return 0.0
        used = sum(u["used_hours"] for u in util_map.values())
        cap = sum(u["capacity_hours"] for u in util_map.values())
        return round(100.0 * used / cap, 1) if cap else 0.0
    process_util = {
        "weave": {"used_hours": sum(u["used_hours"] for u in loom_util.values()),
                  "capacity_hours": len(looms) * avail_h,
                  "utilization_pct": agg(loom_util),
                  "resources": looms},
        "warp": {"used_hours": sum(u["used_hours"] for u in warp_util.values()),
                 "capacity_hours": len(warp_machines) * avail_h,
                 "utilization_pct": agg(warp_util),
                 "resources": warp_machines},
        "draw": {"used_hours": sum(u["used_hours"] for u in draw_util.values()),
                 "capacity_hours": len(draw_stations) * avail_h,
                 "utilization_pct": agg(draw_util),
                 "resources": draw_stations},
    }

    # 经轴就绪分析
    ready_orders = [j for j in jobs if j.get("ready_h") is not None]
    n_ready = len(ready_orders)
    on_time = [j for j in ready_orders if j["tardiness"] <= 0]
    tardy = [j for j in ready_orders if j["tardiness"] > 0]
    unsch = [j for j in jobs if j.get("machine") is None]
    # 经轴裕量(织造开始 - 经轴就绪): 越小越"反向拉动"JIT
    ready_slack = [j["start_h"] - j["ready_h"] for j in ready_orders]

    # 换型/仕挂次数(织机上按时间顺序的设备切换)
    chg_count, same_count = 0, 0
    for m in looms:
        runs = sorted([s for s in weave_sched if s["machine"] == m], key=lambda x: x["start_h"])
        prev_prod = None
        for r in runs:
            if prev_prod is not None:
                if r["product"] != prev_prod:
                    chg_count += 1
                else:
                    same_count += 1
            prev_prod = r["product"]

    # 织机等经轴时间: 织造开始 - 经轴就绪(>=0, 硬约束已保证, 用于展示裕量)
    loom_wait_h = sum(max(0, j["start_h"] - j["ready_h"]) for j in ready_orders)

    analysis = {
        "machine_util": machine_util,
        "process_util": process_util,
        "bottleneck": max(loom_util.values(), key=lambda x: x["utilization_pct"]),
        "beam": {
            "total_orders": len(orders),
            "scheduled_orders": len(ready_orders),
            "unscheduled_orders": len(unsch),
            "avg_slack_h": round(sum(ready_slack) / len(ready_slack), 1) if ready_slack else 0,
            "max_slack_h": max(ready_slack) if ready_slack else 0,
            "loom_wait_h": loom_wait_h,
            "ready_before_weave": len([j for j in ready_orders if j["ready_h"] <= j["start_h"]]),
        },
        "tardiness": {
            "total_tardy": len(tardy), "on_time_rate": round(100.0 * len(on_time) / n_ready, 1) if n_ready else 0,
            "tardy_orders": [{"id": j["id"], "product": j["product"], "machine": j["machine"],
                              "due": j["due"], "completion": j["completion"], "tardiness": j["tardiness"],
                              "priority": j["priority"]} for j in tardy],
            "max_tardiness": max((j["tardiness"] for j in ready_orders), default=0),
        },
        "changeovers": chg_count, "same_product_setups": same_count,
        "overall_utilization_pct": round(100.0 * sum(u["used_hours"] for u in loom_util.values()) / (len(looms) * avail_h), 1),
        "total_weave_h": sum(u["used_hours"] for u in loom_util.values()),
        "total_capacity_h": len(looms) * avail_h,
        "calendar": {"days": sc["days"], "hours_per_day": sc["hours_per_day"], "num_hours": T,
                     "rest_days": ctx.get("rest_days", []), "off_hours": sorted(ctx["off_hours"]),
                     "avail_hours": avail_h},
        "type_stats": _type_stats(jobs, orders),
        "wip": _wip(weave_sched, orders, avail_h),
    }
    return {"jobs": jobs, "schedule": schedule,
            "weave_schedule": weave_sched, "warp_schedule": warp_sched,
            "draw_schedule": draw_sched, "analysis": analysis}


def _job_entry(o, m, linfo, ws, we, dur, wap_s, wap_e, dr_s, dr_e, ready_h, tard):
    """组装一个织造订单的任务条目。"""
    return {
        "id": o["id"], "product": o["product"], "product_name": o.get("product", ""),
        "qty": o["qty"], "due": o["due"], "priority": o["pri"], "type": o["type"], "source": o["source"],
        "machine": m, "machine_name": linfo["name"] if m else "", "team": linfo["team"] if m else "",
        "weave_h": dur, "start_h": ws, "end_h": we, "completion": we,
        "warp_start_h": wap_s, "warp_end_h": wap_e, "warp_machine": None,
        "draw_start_h": dr_s, "draw_end_h": dr_e, "ready_h": ready_h,
        "beam_ready_before": (ready_h is not None and ws is not None and ready_h <= ws),
        "tardiness": tard if tard is not None else 0,
        "on_time": (tard is not None and tard <= 0) if m else False,
        "scheduled": bool(m),
    }


def _type_stats(jobs, orders):
    res = {}
    for j in jobs:
        ty = j.get("type", "normal")
        if ty not in res:
            res[ty] = {"count": 0, "qty": 0, "hours": 0}
        res[ty]["count"] += 1
        res[ty]["qty"] += int(j["qty"])
        res[ty]["hours"] += int(j["weave_h"] or 0)
    return res


def _wip(weave_sched, orders, avail_h):
    """在制统计: 以"每小时在织的经轴数"近似, 这里给出织造中订单均分到各小时的近似。"""
    if not weave_sched:
        return {"avg_wip": 0, "peak_wip": 0, "total_in_process_qty": 0, "working_hours": 0}
    hours = []
    for s in weave_sched:
        for h in range(s["start_h"], s["end_h"]):
            hours.append(h)
    from collections import Counter
    per_h = Counter(hours)
    total_qty = sum(s["qty"] for s in weave_sched)
    return {
        "avg_wip": round(sum(per_h.values()) / max(1, avail_h), 1),
        "peak_wip": max(per_h.values()) if per_h else 0,
        "total_in_process_qty": total_qty,
        "working_hours": len(per_h),
    }


def build_result(ctx, sres, objective: str = "balanced", note: str = "") -> dict:
    """组装最终输出 JSON。"""
    sc = ctx["scenario"]
    ex = extract(ctx, sres)
    meta = {
        "title": f"{sc['name']} · 智能排产",
        "data_source": "demo(织造车间·整经-穿综穿筘-织造)",
        "unit": "小时(1h)",
        "days": ctx["days"], "hours_per_day": ctx["hours_per_day"],
        "num_slots": ctx["T"], "num_hours": ctx["T"],
        "num_looms": len(ctx["looms"]), "num_warp": len(ctx["warp_machines"]),
        "num_draw": len(ctx["draw_stations"]),
        "num_machines": len(ctx["looms"]) + len(ctx["warp_machines"]) + len(ctx["draw_stations"]),
        "num_orders": len(ctx["orders"]),
        "status": sres["status"], "solve_time_s": sres["solve_time_s"],
        "objective": objective,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rest_days": ctx.get("rest_days", []), "off_hours": sorted(ctx["off_hours"]),
        "note": note,
    }
    machines = ([{**m, "process": "loom"} for m in ctx["loom_info"].values()] +
                [{**m, "process": "warp"} for m in ctx["warp_info"].values()] +
                [{**m, "process": "draw"} for m in ctx["draw_info"].values()])
    return {
        "meta": meta,
        "scenario": sc,
        "objectives": {
            "priority_due": sum(int(j["priority"]) * j["tardiness"] for j in ex["jobs"] if j["scheduled"]),
            "changeover": ex["analysis"]["changeovers"],
            "beam_jit": ex["analysis"]["beam"]["avg_slack_h"],
        },
        "machines": machines,
        "jobs": ex["jobs"],
        "schedule": ex["schedule"],
        "weave_schedule": ex["weave_schedule"],
        "warp_schedule": ex["warp_schedule"],
        "draw_schedule": ex["draw_schedule"],
        "analysis": ex["analysis"],
    }


# 多目标权重预设
WEIGHT_PRESETS = {
    "balanced":   {"priority": 10.0, "changeover": 0.3, "jit": 0.05, "unscheduled": 1000.0},
    "priority":   {"priority": 30.0, "changeover": 0.1, "jit": 0.02, "unscheduled": 2000.0},
    "changeover": {"priority": 6.0,  "changeover": 3.0, "jit": 0.05, "unscheduled": 1000.0},
    "jit":        {"priority": 6.0,  "changeover": 0.4, "jit": 0.5,  "unscheduled": 1000.0},
}
OBJ_LABELS = {"balanced": "多目标均衡", "priority": "交期/优先级优先",
              "changeover": "换型最少", "jit": "经轴就绪(反向)优先"}


def solve_scenario(sc: dict | None = None, objective: str = "balanced",
                   max_time_s: float = 30.0, weights: dict | None = None) -> dict:
    """把字典场景一键求解为输出 JSON。软约束(NL 解析)通过 sc['soft_bias'] 覆盖权重。"""
    sc = sc or DEFAULT_SCENARIO
    w0 = weights if weights is not None else dict(WEIGHT_PRESETS.get(objective, WEIGHT_PRESETS["balanced"]))
    w = dict(w0)
    for k, v in sc.get("soft_bias", {}).items():
        w[k] = v
    ctx = scenario_to_ctx(sc)
    sres = solve(ctx, objective=objective, max_time_s=max_time_s, weights=w)
    return build_result(ctx, sres, objective=objective)


# ======================================================================
# 五、插单与重排
# ======================================================================
def insert_order(sc: dict, new_order: dict, objective: str = "balanced",
                 max_time_s: float = 30.0) -> dict:
    """插入一张急单并重新求解。返回 baseline/result/comparison/recommendation/kpi_compare。"""
    new_sc = json.loads(json.dumps(sc))
    new_sc.setdefault("orders", []).append(new_order)
    baseline = solve_scenario(sc, objective=objective, max_time_s=max_time_s)
    after = solve_scenario(new_sc, objective=objective, max_time_s=max_time_s)

    before_by_id = {j["id"]: j for j in baseline["jobs"]}
    after_by_id = {j["id"]: j for j in after["jobs"]}
    comparison = []
    for jid, bj in before_by_id.items():
        aj = after_by_id.get(jid)
        if not aj:
            continue
        dc = (aj["completion"] or 0) - (bj["completion"] or 0)
        dt = aj["tardiness"] - bj["tardiness"]
        if dc > 0 or dt > 0:
            comparison.append({
                "id": jid, "product": bj["product"],
                "machine_before": bj["machine"], "machine_after": aj["machine"],
                "start_before": bj["start_h"], "start_after": aj["start_h"],
                "completion_before": bj["completion"], "completion_after": aj["completion"],
                "tardiness_before": bj["tardiness"], "tardiness_after": aj["tardiness"],
                "priority": bj["priority"], "due": bj["due"],
                "delta_completion": dc, "delta_tardiness": dt,
            })
    recommendation = _recommend(ctx := scenario_to_ctx(new_sc), after, comparison)
    kpi = {"before": _kpi(baseline), "after": _kpi(after)}
    return {"new_scenario": new_sc, "baseline": baseline, "result": after,
            "comparison": comparison, "recommendation": recommendation,
            "kpi_compare": kpi, "new_order": new_order}


def _kpi(res: dict) -> dict:
    a = res["analysis"]
    return {
        "status": res["meta"]["status"], "solve_time_s": res["meta"]["solve_time_s"],
        "on_time_rate": a["tardiness"]["on_time_rate"],
        "tardy_count": a["tardiness"]["total_tardy"],
        "changeovers": a["changeovers"],
        "same_product_setups": a.get("same_product_setups", 0),
        "utilization": a["overall_utilization_pct"],
        "max_tardiness": a["tardiness"]["max_tardiness"],
        "loom_wait_h": a["beam"]["loom_wait_h"],
        "avg_beam_slack_h": a["beam"]["avg_slack_h"],
    }


def _recommend(ctx, after: dict, comparison: list) -> dict:
    """被挤任务调剂建议: P1 同品种其他可用织机 / P2 原织机顺延 / P3 跨机台跨日期需人工确认。"""
    T = ctx["T"]
    loom_info = ctx["loom_info"]
    after_sched = after["weave_schedule"]
    displaced_ids = {c["id"] for c in comparison}
    displaced = [j for j in after["jobs"] if j["id"] in displaced_ids]
    items = []
    for j in displaced:
        prod = j["product"]
        eligible = [m for m in ctx["loom_elig"][prod] if m in ctx["looms"]]
        free = []
        for m in eligible:
            if m == j["machine"]:
                continue
            used = sum(s["duration"] for s in after_sched if s["machine"] == m)
            cap = T - len(ctx["off_hours"])
            free.append({"machine": m, "name": loom_info[m]["name"],
                         "team": loom_info[m]["team"], "free_hours": max(0, cap - used),
                         "need_conf_ok": (cap - used) >= j["weave_h"]})
        items.append({
            "id": j["id"], "product": prod, "priority": j["priority"], "due": j["due"],
            "machine": j["machine"], "completion": j["completion"],
            "tardiness": j["tardiness"], "weave_h": j["weave_h"],
            "P1": free,
            "P2": {"machine": j["machine"], "name": loom_info[j["machine"]]["name"]},
            "P3": {"need_confirm": True},
        })
    return {
        "generated_at": datetime.datetime.now().strftime("%H:%M:%S"),
        "items": items,
        "summary": "插单挤动 %d 个织造订单; 建议优先按 P1(同品种其他可用织机)调剂, 其次 P2(原织机顺延), "
                   "P3(跨机台跨日期)需人工确认, 并注意经轴是否能在新织造开始前就绪。" % len(items),
    }


# ======================================================================
# 六、自然语言约束应用(把解析后的结构化约束写入场景)
# ======================================================================
def _find_order(sc: dict, oid: str) -> dict | None:
    for o in sc["orders"]:
        if o["id"] == oid:
            return o
    return None


def apply_constraints(sc: dict, parsed: list) -> tuple:
    """把 NL 解析得到的结构化约束应用到场景(深拷贝), 返回 (新场景, 应用摘要)。"""
    import copy
    new_sc = json.loads(json.dumps(sc))
    summary = []
    for c in parsed or []:
        if not c.get("recognized", True):
            summary.append({"ok": False, "hard": False, "msg": f"未能识别：{c.get('raw', '')}"})
            continue
        t, h = c.get("type"), c.get("hard", True)
        try:
            if t == "order_deadline":
                slot = int(c["params"]["slot"])
                if c.get("entity") == "__all__":
                    for o in new_sc["orders"]:
                        o["hard_due"] = slot
                else:
                    order = _find_order(new_sc, c["entity"])
                    if not order:
                        raise ValueError(f"未找到订单 {c['entity']}")
                    order["hard_due"] = slot
                summary.append({"ok": True, "hard": True, "msg": c["desc"]})
            elif t == "product_machine":
                p = c["entity"]
                new_sc["loom_eligibility"][p] = list(c["params"]["machines"])
                summary.append({"ok": True, "hard": True, "msg": c["desc"]})
            elif t == "order_machine":
                oid = c["entity"]; m = c["params"]["machines"][0]
                order = _find_order(new_sc, oid)
                if not order:
                    raise ValueError(f"未找到订单 {oid}")
                order["fixed_loom"] = m
                summary.append({"ok": True, "hard": True, "msg": c["desc"]})
            elif t == "machine_unavailable":
                m = c["entity"]; slots = [int(x) for x in c["params"]["slots"]]
                new_sc.setdefault("unavailable", {}).setdefault(m, [])
                new_sc["unavailable"][m] = sorted(set(new_sc["unavailable"][m] + slots))
                summary.append({"ok": True, "hard": True, "msg": c["desc"]})
            elif t == "max_shifts":
                m = c["entity"]; n = int(c["params"]["count"])
                new_sc.setdefault("max_hours", {})[m] = n
                summary.append({"ok": True, "hard": True, "msg": c["desc"]})
            elif t == "soft_changeover":
                new_sc.setdefault("soft_bias", {})["changeover"] = max(
                    new_sc.get("soft_bias", {}).get("changeover", 0), 3.0)
                summary.append({"ok": True, "hard": False, "msg": c["desc"]})
            elif t == "soft_beam_ready":
                new_sc.setdefault("soft_bias", {})["jit"] = max(
                    new_sc.get("soft_bias", {}).get("jit", 0), 0.5)
                summary.append({"ok": True, "hard": False, "msg": c["desc"]})
            elif t == "soft_priority":
                pri = int(c["params"].get("priority", 10))
                for oid in c["entities"]:
                    order = _find_order(new_sc, oid)
                    if order:
                        order["pri"] = max(int(order.get("pri", 5)), pri)
                summary.append({"ok": True, "hard": False, "msg": c["desc"]})
            elif t == "contiguity":
                summary.append({"ok": True, "hard": True, "msg": c["desc"]})
            else:
                summary.append({"ok": False, "hard": h, "msg": f"暂不支持约束类型 {t}"})
        except Exception as e:  # noqa: BLE001
            summary.append({"ok": False, "hard": h, "msg": f"应用失败：{e}"})
    return new_sc, summary


def _hh(t, ctx_days=7, hpd=24):
    """把小时索引格式化为 第X天 HH时。"""
    if t is None:
        return "-"
    day = t // hpd + 1
    hh = t % hpd
    return f"第{day}天{hh:02d}时"


if __name__ == "__main__":
    print("求解默认场景(织造车间·整经-穿综穿筘-织造)...")
    r = solve_scenario(DEFAULT_SCENARIO, max_time_s=30)
    out = os.path.join(_THIS, "demo_schedule.json")
    json.dump(r, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("状态:", r["meta"]["status"], " 耗时:", r["meta"]["solve_time_s"], "s")
    a = r["analysis"]
    print("订单:", len(r["jobs"]), " 织机:", r["meta"]["num_looms"], " 整经机:", r["meta"]["num_warp"],
          " 穿综工位:", r["meta"]["num_draw"], " 时段(小时):", r["meta"]["num_hours"])
    print("织造负荷:", a["overall_utilization_pct"], "%  改品番:", a["changeovers"],
          "  原品番仕挂:", a["same_product_setups"])
    print("经轴: 就绪%=", round(100.0 * a["beam"]["ready_before_weave"] / max(1, a["beam"]["scheduled_orders"]), 1),
          " 平均裕量:", a["beam"]["avg_slack_h"], "h  织机等经轴:", a["beam"]["loom_wait_h"], "h")
    print("拖期单:", a["tardiness"]["total_tardy"], " 准交率:", a["tardiness"]["on_time_rate"], "%")
    print("瓶颈:", a["bottleneck"]["machine"], a["bottleneck"]["name"], a["bottleneck"]["utilization_pct"], "%")
    print("\n-- 织造订单排产(时间: 第X天 HH时) --")
    for j in r["jobs"]:
        if not j["scheduled"]:
            print("%-6s %-4s 数量%-5d  [未排]" % (j["id"], j["product"], j["qty"]))
            continue
        mark = "  [拖期]" if j["tardiness"] > 0 else ""
        print("%-6s %-4s 数量%-5d 织机%-4s %s->%s 经轴就绪%s 交期%-3d 完成%-3d 拖期%-2d%s"
              % (j["id"], j["product"], j["qty"], j["machine"],
                 _hh(j["start_h"], ctx_days=7, hpd=24), _hh(j["end_h"], ctx_days=7, hpd=24),
                 _hh(j["ready_h"], ctx_days=7, hpd=24), j["due"], j["completion"], j["tardiness"], mark))
    print("\n-- 整经/穿综 --")
    for s in r["warp_schedule"]:
        print("整经 %-6s %-4s %-4s %s->%s" % (s["job"], s["product"], s["machine"], _hh(s["start_h"]), _hh(s["end_h"])))
    for s in r["draw_schedule"]:
        print("穿综 %-6s %-4s %-4s %s->%s" % (s["job"], s["product"], s["machine"], _hh(s["start_h"]), _hh(s["end_h"])))
    print("\n输出:", out)
