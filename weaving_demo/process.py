# -*- coding: utf-8 -*-
"""
process.py -- 工艺流程可视化与流程状态构建
===============================================================================
基于现有 scenario 与 solve_result 的真实数据，为每个生产任务分配统一流程状态，
并输出工序总览、首页进度与订单流程跟踪。不新增后整 CP-SAT 排程。
缺真实数据的工序以"演示数据/推导数据/待补充数据"标注，不把模拟完成时间当真实记录。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 主流程（顺序）
PROCESS_FLOW = [
    "客户需求", "生产需求确认", "原料库存检查", "缺料处理", "整经计划", "整经生产",
    "经轴准备", "上轴", "穿综穿筘", "织造生产", "落布", "水洗", "涂层", "验布", "成品入库", "订单完成",
]

# 后整工序（本期仅展示流程位置与模拟状态，后续阶段接入正式排程）
FINISHING_PROCESSES = ["水洗", "涂层", "验布", "成品入库"]

STATUSES = ["未开始", "等待条件", "已排程", "部分已排", "进行中", "已完成", "已跳过", "异常阻塞"]

# 各工序前置与后续
PRED_SUCC: Dict[str, Dict[str, List[str]]] = {
    "客户需求": {"pred": [], "succ": ["生产需求确认"]},
    "生产需求确认": {"pred": ["客户需求"], "succ": ["原料库存检查"]},
    "原料库存检查": {"pred": ["生产需求确认"], "succ": ["缺料处理", "整经计划"]},
    "缺料处理": {"pred": ["原料库存检查"], "succ": ["原料库存检查"]},
    "整经计划": {"pred": ["原料库存检查"], "succ": ["整经生产"]},
    "整经生产": {"pred": ["整经计划"], "succ": ["经轴准备"]},
    "经轴准备": {"pred": ["整经生产"], "succ": ["上轴"]},
    "上轴": {"pred": ["经轴准备"], "succ": ["穿综穿筘", "织造生产"]},
    "穿综穿筘": {"pred": ["上轴"], "succ": ["织造生产"]},
    "织造生产": {"pred": ["上轴", "穿综穿筘"], "succ": ["落布"]},
    "落布": {"pred": ["织造生产"], "succ": ["水洗", "涂层"]},
    "水洗": {"pred": ["落布"], "succ": ["涂层", "验布"]},
    "涂层": {"pred": ["落布"], "succ": ["验布"]},
    "验布": {"pred": ["水洗", "涂层"], "succ": ["成品入库"]},
    "成品入库": {"pred": ["验布"], "succ": ["订单完成"]},
    "订单完成": {"pred": ["成品入库"], "succ": []},
}

# 分支标注
BRANCH_NOTES = [
    "物料不足时，停留在原料准备阶段并标记缺料。",
    "经轴未准备完成时，织造任务不得进入待生产状态。",
    "同品种连续生产时，可以不进行穿综穿筘。",
    "换品种、换工艺或工装不匹配时，需要经过换轴或穿综穿筘。",
    "不需要水洗或涂层的产品，可以跳过对应工序。",
    "验布不合格时，显示返工、降级或待处理状态。",
]


def _reason(reason: str) -> str:
    return reason or ""


def _confirmed_completed_processes(current: str, reason: str) -> List[str]:
    """只返回有数据依据的已完成工序，不按流程位置机械补齐前置工序。"""
    done = ["客户需求", "生产需求确认"]
    if current != "原料库存检查" and reason != "MATERIAL_SHORTAGE":
        done.append("原料库存检查")
    if current in ("整经生产", "经轴准备"):
        done.append("整经计划")
    return done


def assign_process_states(scenario: Any, result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """为每个任务分配统一的流程状态结构。"""
    out: List[Dict[str, Any]] = []
    unsched = result.get("unscheduled", [])
    diag_by_task = {d["task_id"]: d for d in result.get("task_diagnostics", [])}
    for u in unsched:
        tid = u["task_id"]
        required = float(u["required_quantity"])
        sched = float(u["scheduled_quantity"])
        unsched_qty = float(u["unscheduled_quantity"])
        reason = _reason(u.get("primary_reason"))
        diag = diag_by_task.get(tid, {})
        product = u.get("product_id", diag.get("product_id", ""))
        # 判定当前工序 + 状态
        if unsched_qty > 1e-6 and sched > 1e-6:
            current, status, blocked, src = "织造生产", "部分已排", "部分未排", "CP-SAT排程结果"
        elif sched > 1e-6:
            current, status, blocked, src = "织造生产", "已排程", "", "CP-SAT排程结果"
        elif reason == "MATERIAL_SHORTAGE":
            current, status, blocked, src = "原料库存检查", "异常阻塞", "物料不足(缺料)", "推导数据"
        elif reason == "NO_AVAILABLE_BEAM":
            current, status, blocked, src = "整经生产", "等待条件", "经轴未准备", "推导数据"
        elif reason in ("NO_COMPATIBLE_LOOM", "TOOLING_MISMATCH"):
            current, status, blocked, src = "织造生产", "异常阻塞", "无兼容织机或工装不匹配", "推导数据"
        elif reason == "CAPACITY_SHORTAGE":
            current, status, blocked, src = "织造生产", "等待条件", "窗口内产能不足", "推导数据"
        else:
            current, status, blocked, src = "织造生产", "等待条件", reason or "", "推导数据"

        # 仅把有数据依据的工序标记为已完成。CP-SAT 已排程不代表整经、上轴等已执行。
        idx = PROCESS_FLOW.index(current)
        done = _confirmed_completed_processes(current, reason)
        next_proc = PROCESS_FLOW[idx + 1] if idx + 1 < len(PROCESS_FLOW) else "订单完成"
        if current in FINISHING_PROCESSES:
            src = "演示数据(后续阶段接入正式排程)"
        out.append({
            "task_id": tid,
            "order_id": f"ORD-{tid}",
            "product_id": product,
            "required_quantity": required,
            "scheduled_quantity": sched,
            "unscheduled_quantity": unsched_qty,
            "current_process": current,
            "current_status": status,
            "completed_processes": done,
            "next_process": next_proc if current != "已完成" else "",
            "blocked_reason": blocked,
            "est_complete_at": None,
            "data_source": src,
            "use_temp_params": True,
            "raw_reason": reason,
        })
    return out


def process_overview(scenario: Any, result: Dict[str, Any],
                     warping_summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """工序总览：每道工序的待处理/进行中/已完成/异常/涉及数量/主要风险。"""
    tasks = assign_process_states(scenario, result)
    # 把所有任务当作"到该工序"的处理对象
    state_counts: Dict[str, Dict[str, int]] = {p: {"待处理": 0, "进行中": 0, "已完成": 0, "异常": 0} for p in PROCESS_FLOW}
    qty_by_proc: Dict[str, float] = {p: 0.0 for p in PROCESS_FLOW}
    risk_by_proc: Dict[str, str] = {p: "" for p in PROCESS_FLOW}
    for t in tasks:
        cur = t["current_process"]
        if cur in state_counts:
            st = t["current_status"]
            if st in ("异常阻塞",):
                state_counts[cur]["异常"] += 1
                if not risk_by_proc[cur]:
                    risk_by_proc[cur] = t["blocked_reason"] or "异常阻塞"
            elif st in ("进行中", "部分已排"):
                state_counts[cur]["进行中"] += 1
            elif st in ("已完成",):
                state_counts[cur]["已完成"] += 1
            elif st in ("等待条件", "可以开始", "已排程"):
                state_counts[cur]["待处理"] += 1
            qty_by_proc[cur] += t["required_quantity"]
        # 已完成工序也计数
        for done in t["completed_processes"]:
            if done in state_counts:
                state_counts[done]["已完成"] += 1
                qty_by_proc[done] += t["scheduled_quantity"]

    # 整经与经轴使用来源表任务口径，避免把织造已排程误算为整经已完成。
    if warping_summary:
        warp_tasks = int(warping_summary.get("warp_task_count", 0))
        virtual_beams = int(warping_summary.get("virtual_beam_count", 0))
        warp_meters = float(warping_summary.get("warp_plan_meters", 0.0))
        instance_meters = float(warping_summary.get("instance_meters", 0.0))
        for proc in ("整经计划", "整经生产"):
            state_counts[proc]["待处理"] = max(state_counts[proc]["待处理"], warp_tasks)
            state_counts[proc]["已完成"] = 0
            qty_by_proc[proc] = max(qty_by_proc[proc], warp_meters)
        if warp_tasks:
            risk_by_proc["整经生产"] = "源表仅有计划，实际执行状态待确认"
        state_counts["经轴准备"]["待处理"] = max(state_counts["经轴准备"]["待处理"], virtual_beams)
        state_counts["经轴准备"]["已完成"] = 0
        qty_by_proc["经轴准备"] = max(qty_by_proc["经轴准备"], instance_meters)
        if virtual_beams:
            risk_by_proc["经轴准备"] = f"{virtual_beams}根虚拟经轴，实体编号待确认"
            risk_by_proc["上轴"] = "仅有关联目标织机，实际绑定待确认"
            risk_by_proc["穿综穿筘"] = "实际工装执行状态待补充"

    cards = []
    for i, p in enumerate(PROCESS_FLOW):
        s = state_counts[p]
        cards.append({
            "order": i + 1, "process": p,
            "pending_count": s["待处理"], "in_progress_count": s["进行中"],
            "completed_count": s["已完成"], "anomaly_count": s["异常"],
            "quantity": round(qty_by_proc[p], 1),
            "main_risk": risk_by_proc[p],
            "is_finishing": p in FINISHING_PROCESSES,
            "pred": PRED_SUCC.get(p, {}).get("pred", []),
            "succ": PRED_SUCC.get(p, {}).get("succ", []),
        })
    return {"flow": cards, "statuses": STATUSES, "branch_notes": BRANCH_NOTES}


def homepage_progress(scenario: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    """首页顶部简化流程进度：7 项。"""
    kpi = result.get("kpi", {})
    tasks = assign_process_states(scenario, result)
    weave_sched = sum(t["scheduled_quantity"] for t in tasks)
    # 织造"已完成" = 已越过落布/后整/入库的任务（CP-SAT 仅排织造，故当前为 0）
    post_weave = ["落布", "水洗", "涂层", "验布", "成品入库", "订单完成"]
    weave_done = sum(t["scheduled_quantity"] for t in tasks if t["current_process"] in post_weave)
    finishing = sum(t["required_quantity"] for t in tasks if t["current_process"] in FINISHING_PROCESSES)
    return {
        "required_qty": round(kpi.get("required_quantity", 0.0), 1),
        "material_ready_qty": round(weave_sched, 1),
        "beam_ready_qty": round(weave_sched, 1),
        "weave_scheduled_qty": round(weave_sched, 1),
        "weave_done_qty": round(weave_done, 1),
        "finishing_qty": round(finishing, 1),
        "stocked_qty": 0.0,
        "note": "后整(水洗/涂层/验布/入库)仅为模拟状态，后续阶段接入正式排程。",
    }


def demonstration_cases(scenario: Any, result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """五个可点击查看的演示案例。"""
    tasks = assign_process_states(scenario, result)
    def pick(pred):
        return next((t for t in tasks if pred(t)), None)
    cases = [
        {"label": "已进入织造排程的任务", "task": pick(lambda t: t["current_process"] == "织造生产" and t["current_status"] in ("已排程", "部分已排") and not t["blocked_reason"])},
        {"label": "因物料不足被阻塞的任务", "task": pick(lambda t: t["blocked_reason"].startswith("物料"))},
        {"label": "等待整经或经轴准备的任务", "task": pick(lambda t: t["current_process"] == "整经生产" or t["current_process"] == "经轴准备")},
        {"label": "织造部分已排的任务", "task": pick(lambda t: t["current_process"] == "织造生产" and t["current_status"] == "部分已排")},
        {"label": "织造完成但等待水洗或涂层的任务", "task": pick(lambda t: t["current_process"] in FINISHING_PROCESSES or (t["current_process"] == "落布"))},
    ]
    return [{"label": c["label"], "task_id": c["task"]["task_id"] if c["task"] else None,
             "product_id": c["task"]["product_id"] if c["task"] else "",
             "current_process": c["task"]["current_process"] if c["task"] else "", "found": bool(c["task"])} for c in cases]
