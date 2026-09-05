# -*- coding: utf-8 -*-
"""一周整经计划池排程。

源表没有具体整经机编号和标准产能，因此第一版按一个串行计划池、每轴 240 分钟模拟。
计划由后续织造需求反推经轴数量，并保留所有推导假设供页面展示。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, Iterable, Mapping, Sequence


def build_weekly_warping_plan(dataset: Dict[str, Any], production_tasks: Iterable[Any],
                              start_date: str, days: int = 7,
                              minutes_per_beam: int = 240) -> Dict[str, Any]:
    start = dt.datetime.fromisoformat(str(start_date)[:10])
    horizon_minutes = max(1, int(days)) * 1440
    rows = dataset.get("reconciliation", {}).get("product_rows", [])
    row_by_product = {r.get("product_id"): r for r in rows}
    beams = dataset.get("beams", {})
    beam_to_looms = dataset.get("beam_to_looms", {})

    demand_by_beam: Dict[str, float] = {}
    products_by_beam: Dict[str, list[str]] = {}
    blocked_products: list[str] = []
    product_order: Dict[str, int] = {}
    due_by_beam: Dict[str, int] = {}
    due_date_by_beam: Dict[str, str] = {}
    priority_by_beam: Dict[str, float] = {}
    for index, task in enumerate(production_tasks):
        row = row_by_product.get(task.product_id) or {}
        code = row.get("warp_beam_sku")
        if not code:
            blocked_products.append(task.product_id)
            continue
        demand_by_beam[code] = demand_by_beam.get(code, 0.0) + float(task.required_quantity)
        products_by_beam.setdefault(code, []).append(task.product_id)
        product_order.setdefault(code, index)
        due_minute = int(task.due_minute) if task.due_minute is not None else 10**12
        due_by_beam[code] = min(due_by_beam.get(code, 10**12), due_minute)
        if task.due_date:
            current_due = due_date_by_beam.get(code)
            due_date_by_beam[code] = min(current_due, task.due_date) if current_due else task.due_date
        priority_by_beam[code] = max(priority_by_beam.get(code, float("-inf")), float(task.priority or 0))

    source_dates = {
        code: min(rec.get("warp_plan_m", {}) or {"9999-12-31": 0})
        for code, rec in beams.items()
    }
    ordered_beams = sorted(
        demand_by_beam,
        key=lambda code: (
            due_by_beam.get(code, 10**12),
            -priority_by_beam.get(code, 0.0),
            source_dates.get(code, "9999-12-31"),
            product_order.get(code, 9999),
            code,
        ),
    )

    tasks: list[Dict[str, Any]] = []
    unscheduled: list[Dict[str, Any]] = []
    cursor = 0
    sequence = 0
    for code in ordered_beams:
        rec = beams.get(code, {})
        beam_length = float(rec.get("set_length") or 3600.0)
        remaining = demand_by_beam[code]
        required_count = max(1, int(math.ceil(remaining / beam_length)))
        for beam_index in range(1, required_count + 1):
            meters = min(beam_length, remaining)
            if cursor + minutes_per_beam > horizon_minutes:
                unscheduled.append({
                    "warp_beam_sku": code,
                    "remaining_meters": round(remaining, 1),
                    "remaining_beams": required_count - beam_index + 1,
                    "reason": "超出一周整经计划池容量",
                })
                break
            sequence += 1
            begin = start + dt.timedelta(minutes=cursor)
            finish = begin + dt.timedelta(minutes=minutes_per_beam)
            tasks.append({
                "task_id": f"WARP-WEEK-{code}-{beam_index:02d}",
                "sequence": sequence,
                "warp_beam_sku": code,
                "product_ids": sorted(set(products_by_beam.get(code, []))),
                "order_due_minute": None if due_by_beam.get(code, 10**12) >= 10**12 else due_by_beam[code],
                "order_due_date": due_date_by_beam.get(code),
                "order_priority": priority_by_beam.get(code, 0.0),
                "planning_basis": "订单交期优先，其次订单优先级；同品番连续整经",
                "plan_date": begin.date().isoformat(),
                "start": begin.isoformat(timespec="seconds"),
                "end": finish.isoformat(timespec="seconds"),
                "complete_at": finish.isoformat(timespec="seconds"),
                "plan_meters": round(meters, 1),
                "plan_count": 1,
                "target_loom_id": beam_to_looms.get(code, []),
                "warping_machine_id": "",
                "machine_placeholder": "整经计划池",
                "machine_status": "按计划池管理",
                "warping_resource_mode": "计划池",
                "data_source": "一周滚动排产推导",
                "is_derived": True,
                "plan_src_cell": None,
                "count_src_cell": None,
            })
            remaining -= meters
            cursor += minutes_per_beam

    daily: list[Dict[str, Any]] = []
    for day_index in range(max(1, int(days))):
        day = (start.date() + dt.timedelta(days=day_index)).isoformat()
        rows_for_day = [t for t in tasks if t["plan_date"] == day]
        daily.append({
            "date": day,
            "task_count": len(rows_for_day),
            "plan_count": sum(t["plan_count"] for t in rows_for_day),
            "plan_meters": round(sum(t["plan_meters"] for t in rows_for_day), 1),
        })

    return {
        "schedule_start": start.date().isoformat(),
        "schedule_end": (start.date() + dt.timedelta(days=max(1, int(days)))).isoformat(),
        "horizon_days": max(1, int(days)),
        "resource_mode": "计划池",
        "resource_count": 1,
        "minutes_per_beam": int(minutes_per_beam),
        "tasks": tasks,
        "daily": daily,
        "unscheduled": unscheduled,
        "blocked_products": sorted(set(blocked_products)),
        "stats": {
            "task_count": len(tasks),
            "beam_sku_count": len({t["warp_beam_sku"] for t in tasks}),
            "plan_count": sum(t["plan_count"] for t in tasks),
            "plan_meters": round(sum(t["plan_meters"] for t in tasks), 1),
            "utilization": round(cursor / horizon_minutes, 4),
        },
        "assumptions": [
            "源表没有具体整经机编号，按一个整经计划池串行模拟。",
            f"每轴整经工时暂按 {minutes_per_beam} 分钟。",
            "经轴数量按织造需求量 ÷ 经轴设定米数向上取整。",
            "整经任务按订单交期升序、订单优先级降序排列，同一经轴品番连续生产。",
            "同一经轴品番首根完成后即可上轴织造，后续经轴按计划连续补充。",
        ],
    }


def align_warping_plan_to_weaving(
    source_plan: Mapping[str, Any],
    assignments: Sequence[Mapping[str, Any]],
    production_tasks: Iterable[Any],
    dataset: Mapping[str, Any],
) -> Dict[str, Any]:
    """按本轮已选织造量收敛整经计划，但仍保留完整经轴容量。

    排程模型先决定本周要做哪些织造任务；本函数随后只保留这些任务真正需要的
    经轴。由于经轴不能只整经本周会织掉的零头，所保留的每根轴仍采用主档设定
    长度，剩余米数进入期末余轴台账。这样既避免凭总需求过量备轴，也不会伪造
    893 米之类的不完整经轴。
    """
    import copy

    plan = copy.deepcopy(dict(source_plan or {}))
    task_by_id = {str(task.task_id): task for task in production_tasks}
    row_by_product = {
        str(row.get("product_id") or ""): row
        for row in (dataset.get("reconciliation", {}) or {}).get("product_rows", []) or []
    }
    beam_master = dataset.get("beams", {}) or {}

    demand_by_beam: Dict[str, float] = {}
    task_ids_by_beam: Dict[str, list[str]] = {}
    for assignment in assignments or []:
        quantity = float(assignment.get("scheduled_quantity") or 0.0)
        if quantity <= 1e-6:
            continue
        task_id = str(assignment.get("task_id") or "")
        task = task_by_id.get(task_id)
        product_id = str(assignment.get("product_id") or getattr(task, "product_id", "") or "")
        code = str(
            getattr(task, "beam_code", None)
            or (row_by_product.get(product_id) or {}).get("warp_beam_sku")
            or ""
        )
        if not code:
            continue
        demand_by_beam[code] = demand_by_beam.get(code, 0.0) + quantity
        task_ids_by_beam.setdefault(code, []).append(task_id)

    needed_count: Dict[str, int] = {}
    for code, meters in demand_by_beam.items():
        set_length = float((beam_master.get(code) or {}).get("set_length") or 3600.0)
        needed_count[code] = max(1, int(math.ceil(meters / max(1.0, set_length))))

    kept: list[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    for row in plan.get("tasks", []) or []:
        code = str(row.get("warp_beam_sku") or "")
        if seen.get(code, 0) >= needed_count.get(code, 0):
            continue
        seen[code] = seen.get(code, 0) + 1
        kept.append(copy.deepcopy(row))

    # 收敛后重新连续排计划池，保证没有因删除无关经轴留下的空洞。
    start = dt.datetime.fromisoformat(str(plan.get("schedule_start") or "2026-04-01")[:10])
    minutes_per_beam = int(plan.get("minutes_per_beam") or 240)
    for index, row in enumerate(kept, start=1):
        begin = start + dt.timedelta(minutes=(index - 1) * minutes_per_beam)
        finish = begin + dt.timedelta(minutes=minutes_per_beam)
        row.update({
            "sequence": index,
            "plan_date": begin.date().isoformat(),
            "start": begin.isoformat(timespec="seconds"),
            "end": finish.isoformat(timespec="seconds"),
            "complete_at": finish.isoformat(timespec="seconds"),
            "planning_basis": "本轮CP-SAT已选织造量反推；保留完整经轴，余量进入期末台账",
            "rule_optimized": True,
            "driving_weaving_task_ids": sorted(set(task_ids_by_beam.get(str(row.get("warp_beam_sku") or ""), []))),
        })

    days = int(plan.get("horizon_days") or 7)
    daily = []
    for offset in range(days):
        date = (start.date() + dt.timedelta(days=offset)).isoformat()
        rows = [row for row in kept if row.get("plan_date") == date]
        daily.append({
            "date": date,
            "task_count": len(rows),
            "plan_count": sum(int(row.get("plan_count") or 0) for row in rows),
            "plan_meters": round(sum(float(row.get("plan_meters") or 0.0) for row in rows), 1),
        })

    before_tasks = list(plan.get("tasks", []) or [])
    before_meters = sum(float(row.get("plan_meters") or 0.0) for row in before_tasks)
    after_meters = sum(float(row.get("plan_meters") or 0.0) for row in kept)
    plan.update({
        "tasks": kept,
        "daily": daily,
        "unscheduled": [],
        "stats": {
            **copy.deepcopy(plan.get("stats", {}) or {}),
            "task_count": len(kept),
            "beam_sku_count": len({row.get("warp_beam_sku") for row in kept if row.get("warp_beam_sku")}),
            "plan_count": sum(int(row.get("plan_count") or 0) for row in kept),
            "plan_meters": round(after_meters, 1),
            "utilization": round((len(kept) * minutes_per_beam) / max(1, days * 1440), 4),
        },
        "planning_mode": "weaving_pull",
        "alignment": {
            "optimized": True,
            "source_task_count": len(before_tasks),
            "source_plan_meters": round(before_meters, 3),
            "retained_task_count": len(kept),
            "retained_plan_meters": round(after_meters, 3),
            "driving_weaving_meters": round(sum(demand_by_beam.values()), 3),
            "removed_task_count": max(0, len(before_tasks) - len(kept)),
            "note": "仅保留本轮织造所需完整经轴；整经多于本周织造的部分作为同一根轴的期末余量。",
        },
        "note": "规则优化：由本轮CP-SAT已选织造量反推整经，经轴按主档长度整根生产。",
    })
    return plan
