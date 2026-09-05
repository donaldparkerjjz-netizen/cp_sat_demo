# -*- coding: utf-8 -*-
"""把 CP-SAT 织造结果整理为由一周整经计划驱动的织造周计划。"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict


def build_weekly_weaving_plan(result: Dict[str, Any], warping_plan: Dict[str, Any],
                              dataset: Dict[str, Any]) -> Dict[str, Any]:
    params = result.get("params", {})
    material_enabled = bool(params.get("enable_material_constraint", True))
    beam_enabled = bool(params.get("enable_beam_constraint", True))
    rows = dataset.get("reconciliation", {}).get("product_rows", [])
    beam_by_product = {r.get("product_id"): r.get("warp_beam_sku") for r in rows}
    first_ready: Dict[str, str] = {}
    for task in warping_plan.get("tasks", []):
        code = task.get("warp_beam_sku")
        complete_at = task.get("complete_at") or task.get("end")
        if code and complete_at and (code not in first_ready or complete_at < first_ready[code]):
            first_ready[code] = complete_at

    tasks = []
    violations = []
    for index, assignment in enumerate(result.get("assignments", []), start=1):
        product = assignment.get("product_id")
        beam = beam_by_product.get(product)
        ready_at = assignment.get("beam_ready_at") or first_ready.get(beam)
        start = assignment.get("start")
        order_ok = _parse(start) >= _parse(ready_at) if start and ready_at else False
        row = {
            "sequence": index,
            "task_id": assignment.get("task_id"),
            "product_id": product,
            "warp_beam_sku": beam,
            "beam_instance_id": assignment.get("beam_id"),
            "beam_allocations": assignment.get("beam_allocations", []),
            "beam_quantity_ok": assignment.get("beam_quantity_ok"),
            "beam_ledger_status": assignment.get("beam_ledger_status"),
            "loom_id": assignment.get("loom_id"),
            "source_target_loom_ids": assignment.get("source_target_loom_ids", []),
            "target_mapping_status": assignment.get("target_mapping_status"),
            "source_target_match": assignment.get("source_target_match"),
            "beam_ready_at": ready_at,
            "start": start,
            "end": assignment.get("end"),
            "scheduled_quantity": assignment.get("scheduled_quantity", 0),
            "changeover_type": assignment.get("changeover_type"),
            "order_ok": order_ok,
            "status": "已排织造" if order_ok else "工艺顺序异常",
            "data_source": "CP-SAT求解结果（一周整经计划驱动）",
        }
        tasks.append(row)
        if not order_ok:
            violations.append({"task_id": row["task_id"], "reason": "织造开始早于经轴可用时间"})

    start = warping_plan.get("schedule_start") or result.get("schedule_start", "")[:10]
    days = int(warping_plan.get("horizon_days") or 7)
    start_day = dt.date.fromisoformat(str(start)[:10])
    daily = []
    for offset in range(days):
        day = start_day + dt.timedelta(days=offset)
        day_tasks = [t for t in tasks if str(t.get("start") or "")[:10] == day.isoformat()]
        daily.append({
            "date": day.isoformat(),
            "task_count": len(day_tasks),
            "scheduled_meters": round(sum(float(t["scheduled_quantity"] or 0) for t in day_tasks), 1),
            "loom_count": len({t["loom_id"] for t in day_tasks if t.get("loom_id")}),
        })

    return {
        "schedule_start": start_day.isoformat(),
        "schedule_end": (start_day + dt.timedelta(days=days)).isoformat(),
        "horizon_days": days,
        "tasks": tasks,
        "daily": daily,
        "order_violations": violations,
        "stats": {
            "task_count": len(tasks),
            "product_count": len({t["product_id"] for t in tasks}),
            "loom_count": len({t["loom_id"] for t in tasks}),
            "scheduled_meters": round(sum(float(t["scheduled_quantity"] or 0) for t in tasks), 1),
            "unscheduled_meters": float(result.get("kpi", {}).get("unscheduled_quantity", 0) or 0),
            "order_violation_count": len(violations),
        },
        "simulation_basis": {
            "compatibility_mode": params.get("compatibility_mode", "balanced"),
            "material_enabled": material_enabled,
            "beam_enabled": beam_enabled,
            "target_loom_violation_count": int(result.get("target_loom_audit", {}).get("outside_target_count", 0)),
            "target_loom_missing_count": int(result.get("target_loom_audit", {}).get("missing_target_assignment_count", 0)),
            "beam_ledger_shortage_count": int(result.get("beam_ledger", {}).get("shortage_count", 0)),
            "beam_instance_ids_derived": bool(result.get("beam_ledger", {}).get("all_instance_ids_derived", True)),
            "publishable": (material_enabled and beam_enabled and not violations
                            and not result.get("target_loom_audit", {}).get("outside_target_count")
                            and not result.get("target_loom_audit", {}).get("missing_target_assignment_count")
                            and result.get("beam_ledger", {}).get("publishable", False)),
        },
        "note": ("织造最早开始时间由对应经轴品番首根完成时间确定，后续经轴按整经计划连续补充。"
                 + (" 当前为模拟方案：物料硬约束暂未开启，不可直接下达生产。" if not material_enabled else "")),
    }


def _parse(value: Any) -> dt.datetime:
    if not value:
        return dt.datetime.max
    text = str(value).replace("/", "-")
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return dt.datetime.max
