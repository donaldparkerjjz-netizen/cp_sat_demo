# -*- coding: utf-8 -*-
"""把逐轴执行校验结果投影为全系统唯一的最终排程业务结果。"""
from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from weaving_demo import prep


FINAL_SCHEDULE_SCHEMA_VERSION = 1


def _round3(value: Any) -> float:
    return round(float(value or 0.0), 3)


def _task_map(scenario: Any) -> Dict[str, Any]:
    return {str(task.task_id): task for task in scenario.生产任务}


def _unavailable_minutes(rows: Sequence[Mapping[str, Any]], loom_ids: Iterable[str],
                         horizon: int) -> int:
    wanted = set(loom_ids)
    by_loom: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    for row in rows:
        loom_id = str(row.get("loom_id") or "")
        if loom_id not in wanted:
            continue
        start = max(0, int(row.get("start_minute") or 0))
        end = min(horizon, int(row.get("end_minute") or 0))
        if end > start:
            by_loom[loom_id].append((start, end))
    total = 0
    for intervals in by_loom.values():
        merged: List[List[int]] = []
        for start, end in sorted(intervals):
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        total += sum(end - start for start, end in merged)
    return total


def _source_assignment(initial_assignments: Sequence[Mapping[str, Any]],
                       event: Mapping[str, Any]) -> Mapping[str, Any]:
    task_id = event.get("task_id")
    loom_id = event.get("loom_id") or event.get("resource_id")
    part_index = event.get("assignment_part_index")
    exact = next((row for row in initial_assignments
                  if row.get("task_id") == task_id and row.get("loom_id") == loom_id
                  and (part_index is None or row.get("part_index") == part_index)), None)
    return exact or next((row for row in initial_assignments
                          if row.get("task_id") == task_id and row.get("loom_id") == loom_id), {})


def build_final_assignments(scenario: Any, initial_result: Mapping[str, Any],
                            execution: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """把每个可执行织造事件转换为正式 assignment；一条记录只绑定一根经轴。"""
    tasks = _task_map(scenario)
    initial_assignments = list(initial_result.get("assignments", []) or [])
    events = list(execution.get("weaving_plan", []) or [])
    completion: Dict[str, int] = {}
    for event in events:
        task_id = str(event.get("task_id") or "")
        completion[task_id] = max(completion.get(task_id, 0), int(event.get("end_minute") or 0))

    rows: List[Dict[str, Any]] = []
    schedule_ref = prep.parse_iso(initial_result.get("schedule_start"))
    for index, event in enumerate(events):
        source = _source_assignment(initial_assignments, event)
        task_id = str(event.get("task_id") or source.get("task_id") or f"EXEC-{index + 1}")
        task = tasks.get(task_id)
        due_minute = getattr(task, "due_minute", None) if task else None
        lateness = max(0, completion.get(task_id, 0) - int(due_minute)) if due_minute is not None else 0
        targets = list(source.get("source_target_loom_ids") or [])
        loom_id = str(event.get("loom_id") or event.get("resource_id") or source.get("loom_id") or "")
        ready_minute = event.get("beam_ready_minute")
        ready_at = (prep.minute_to_iso(int(ready_minute), schedule_ref)
                    if ready_minute is not None and schedule_ref else initial_result.get("schedule_start"))
        rows.append({
            "task_id": task_id,
            "part_index": index,
            "source_part_index": event.get("assignment_part_index", source.get("part_index")),
            "beam_segment_index": event.get("beam_segment_index"),
            "loom_id": loom_id,
            "product_id": str(event.get("product_id") or source.get("product_id") or ""),
            "source_target_loom_ids": targets,
            "target_mapping_status": source.get("target_mapping_status"),
            "source_target_match": loom_id in targets if targets else source.get("source_target_match"),
            "beam_id": event.get("beam_id"),
            "beam_origin": event.get("beam_origin"),
            "beam_source_task_id": event.get("beam_source_task_id"),
            "beam_ready_minute": ready_minute,
            "beam_ready_at": ready_at,
            "required_ready_by_minute": event.get("required_ready_by_minute"),
            "start": str(event.get("start") or source.get("start") or ""),
            "end": str(event.get("end") or source.get("end") or ""),
            "start_minute": int(event.get("start_minute") or 0),
            "end_minute": int(event.get("end_minute") or 0),
            "scheduled_quantity": _round3(event.get("quantity")),
            "locked": bool(source.get("locked")),
            "lock_reason": source.get("lock_reason"),
            "changeover_type": str(event.get("setup_type") or source.get("changeover_type") or "same"),
            "lateness_minutes": lateness,
            "data_source": "最终可执行计划（逐轴校验）",
        })
    return rows


_SIMULATION_REASON_CODES = {
    "WEAVING_REDUCED_HORIZON": "OUTSIDE_HORIZON",
    "WEAVING_REDUCED_BEAM_SHORTAGE": "NO_AVAILABLE_BEAM",
    "MISSING_MASTER_DATA": "MISSING_MASTER_DATA",
}


def _simulation_shortages(execution: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for issue in execution.get("issues", []) or []:
        code = _SIMULATION_REASON_CODES.get(str(issue.get("code") or ""))
        task_id = str(issue.get("task_id") or "")
        quantity = float(issue.get("reduced_quantity") or 0.0)
        if not code or not task_id or quantity <= 1e-6:
            continue
        row = grouped.setdefault(task_id, {"breakdown": defaultdict(float), "messages": []})
        row["breakdown"][code] += quantity
        if issue.get("message"):
            row["messages"].append(str(issue["message"]))
    return grouped


def build_final_unscheduled(scenario: Any, initial_result: Mapping[str, Any],
                            assignments: Sequence[Mapping[str, Any]],
                            execution: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """按任务对账最终已排/未排，并用稳定原因码记录初排短缺和执行缩减。"""
    tasks = _task_map(scenario)
    initial_by_task: Dict[str, float] = defaultdict(float)
    final_by_task: Dict[str, float] = defaultdict(float)
    for row in initial_result.get("assignments", []) or []:
        initial_by_task[str(row.get("task_id") or "")] += float(row.get("scheduled_quantity") or 0.0)
    for row in assignments:
        final_by_task[str(row.get("task_id") or "")] += float(row.get("scheduled_quantity") or 0.0)

    source_rows = {str(row.get("task_id") or ""): row
                   for row in initial_result.get("unscheduled", []) or []}
    diagnostics = initial_result.get("diagnostics", {}).get("task_diagnostics", []) or initial_result.get("task_diagnostics", []) or []
    diag_by_task = {str(row.get("task_id") or ""): row for row in diagnostics}
    simulation = _simulation_shortages(execution)
    rows: List[Dict[str, Any]] = []

    for task_id, task in tasks.items():
        source = source_rows.get(task_id, {})
        diag = diag_by_task.get(task_id, {})
        required = float(task.required_quantity or source.get("required_quantity") or 0.0)
        initial_scheduled = min(required, initial_by_task.get(task_id, 0.0))
        scheduled = min(required, final_by_task.get(task_id, 0.0))
        unscheduled = max(0.0, required - scheduled)
        initial_shortage = max(0.0, required - initial_scheduled)
        execution_reduction = max(0.0, initial_scheduled - scheduled)
        breakdown: Dict[str, float] = defaultdict(float)
        source_code = str(source.get("primary_reason") or diag.get("primary_reason") or "")
        if initial_shortage > 1e-6:
            breakdown[source_code or "CAPACITY_SHORTAGE"] += initial_shortage
        sim_row = simulation.get(task_id, {})
        sim_breakdown = sim_row.get("breakdown", {})
        if execution_reduction > 1e-6:
            recorded = sum(float(value) for value in sim_breakdown.values())
            for code, value in sim_breakdown.items():
                breakdown[str(code)] += float(value)
            if recorded + 1e-6 < execution_reduction:
                breakdown["CAPACITY_SHORTAGE"] += execution_reduction - recorded
        if unscheduled > 1e-6 and not breakdown:
            breakdown["CAPACITY_SHORTAGE"] = unscheduled

        reason_breakdown = [
            {"reason_code": code, "quantity": _round3(quantity)}
            for code, quantity in sorted(breakdown.items(), key=lambda item: (-item[1], item[0]))
            if quantity > 1e-6
        ]
        reason_codes = [row["reason_code"] for row in reason_breakdown]
        primary = reason_codes[0] if reason_codes else ""
        messages = list(dict.fromkeys([
            str(source.get("business_text") or diag.get("business_text") or ""),
            *(sim_row.get("messages", []) or []),
        ]))
        rows.append({
            **copy.deepcopy(source),
            "task_id": task_id,
            "product_id": task.product_id,
            "required_quantity": _round3(required),
            "initial_scheduled_quantity": _round3(initial_scheduled),
            "scheduled_quantity": _round3(scheduled),
            "unscheduled_quantity": _round3(unscheduled),
            "execution_reduced_quantity": _round3(execution_reduction),
            "reason_codes": reason_codes,
            "primary_reason": primary,
            "secondary_reasons": reason_codes[1:],
            "reason_breakdown": reason_breakdown,
            "business_text": "；".join(text for text in messages if text),
            "candidate_loom_count": int(source.get("candidate_loom_count") or diag.get("candidate_loom_count") or 0),
            "theoretical_capacity": float(source.get("theoretical_capacity") or diag.get("theoretical_capacity") or 0.0),
            "missing_material": copy.deepcopy(source.get("missing_material") or diag.get("missing_material")
                                                or {"material_code": None, "missing_kg": None}),
            "data_source": "最终可执行计划（逐轴校验）",
        })
    return rows


def build_final_kpi(scenario: Any, initial_result: Mapping[str, Any],
                    assignments: Sequence[Mapping[str, Any]],
                    unscheduled: Sequence[Mapping[str, Any]],
                    execution: Mapping[str, Any]) -> Dict[str, Any]:
    initial = copy.deepcopy(initial_result.get("kpi", {}) or {})
    tasks = _task_map(scenario)
    required = sum(float(task.required_quantity or 0.0) for task in tasks.values())
    scheduled = sum(float(row.get("scheduled_quantity") or 0.0) for row in assignments)
    unscheduled_quantity = max(0.0, required - scheduled)
    completion: Dict[str, int] = {}
    qty_by_task: Dict[str, float] = defaultdict(float)
    for row in assignments:
        task_id = str(row.get("task_id") or "")
        completion[task_id] = max(completion.get(task_id, 0), int(row.get("end_minute") or 0))
        qty_by_task[task_id] += float(row.get("scheduled_quantity") or 0.0)
    lateness = {
        task_id: max(0, end - int(tasks[task_id].due_minute))
        for task_id, end in completion.items()
        if task_id in tasks and tasks[task_id].due_minute is not None
    }
    late_tasks = {task_id for task_id, value in lateness.items() if value > 0}
    late_quantity = sum(qty_by_task[task_id] for task_id in late_tasks)
    on_time_quantity = max(0.0, scheduled - late_quantity)

    horizon = int(initial.get("horizon_minutes") or int(initial.get("horizon_days") or 7) * 1440)
    used_looms = {str(row.get("loom_id") or "") for row in assignments if row.get("loom_id")}
    scheduled_minutes = sum(max(0, int(row.get("end_minute") or 0) - int(row.get("start_minute") or 0))
                            for row in assignments)
    used_gross = len(used_looms) * horizon
    used_downtime = _unavailable_minutes(scenario.维护区间, used_looms, horizon)
    used_available = max(0, used_gross - used_downtime)
    fleet_available = int(initial.get("available_machine_minutes") or 0)
    if fleet_available <= 0:
        available_looms = [loom.织机号 for loom in scenario.织机 if loom.状态可用]
        fleet_gross = len(available_looms) * horizon
        fleet_available = max(0, fleet_gross - _unavailable_minutes(scenario.维护区间, available_looms, horizon))
    else:
        fleet_gross = int(initial.get("gross_machine_minutes") or fleet_available)

    setup_counts = execution.get("kpi", {}).get("setup_type_counts", {}) or {}
    loom_tasks: Dict[str, set[str]] = defaultdict(set)
    for row in assignments:
        loom_tasks[str(row.get("loom_id") or "")].add(str(row.get("task_id") or ""))
    max_delay_task = max(lateness, key=lateness.get) if lateness and max(lateness.values()) > 0 else None
    return {
        **initial,
        "required_quantity": _round3(required),
        "scheduled_quantity": _round3(scheduled),
        "unscheduled_quantity": _round3(unscheduled_quantity),
        "on_time_quantity": _round3(on_time_quantity),
        "late_quantity": _round3(late_quantity),
        "total_lateness_minutes": int(sum(lateness.values())),
        "total_delay_minutes": int(sum(lateness.values())),
        "max_lateness_minutes": int(max(lateness.values(), default=0)),
        "max_delay_task_id": max_delay_task,
        "changeover_count": int(execution.get("kpi", {}).get("setup_segment_count") or 0),
        "beam_change_count": int(setup_counts.get("beam_joining", 0)),
        "threading_count": int(execution.get("kpi", {}).get("threading_task_count") or 0),
        "scheduled_machine_minutes": scheduled_minutes,
        "available_machine_minutes": fleet_available,
        "gross_machine_minutes": fleet_gross,
        "used_loom_count": len(used_looms),
        "used_loom_gross_minutes": used_gross,
        "used_loom_maintenance_minutes": used_downtime,
        "used_loom_downtime_minutes": used_downtime,
        "used_loom_available_minutes": used_available,
        "utilization": scheduled_minutes / fleet_available if fleet_available else 0.0,
        "fleet_utilization": scheduled_minutes / fleet_available if fleet_available else 0.0,
        "used_loom_utilization": scheduled_minutes / used_available if used_available else 0.0,
        "demand_coverage_rate": scheduled / required if required else 1.0,
        "on_time_rate": on_time_quantity / scheduled if scheduled else 0.0,
        "on_time_demand_rate": on_time_quantity / required if required else 0.0,
        "task_fragment_count": len(assignments),
        "single_task_loom_count": sum(1 for task_ids in loom_tasks.values() if len(task_ids) == 1),
        "average_tasks_per_used_loom": (sum(len(task_ids) for task_ids in loom_tasks.values()) / len(used_looms)
                                        if used_looms else 0.0),
        "total_idle_gap_minutes": max(0, used_available - scheduled_minutes),
        "initial_scheduled_quantity": _round3(initial.get("scheduled_quantity")),
        "execution_reduced_quantity": _round3(execution.get("kpi", {}).get("reduced_quantity")),
        "result_scope": "final_executable",
    }


def build_final_diagnostics(initial_result: Mapping[str, Any], kpi: Mapping[str, Any],
                            unscheduled: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    diagnostics = copy.deepcopy(initial_result.get("diagnostics", {}) or {})
    old_rows = diagnostics.get("task_diagnostics", []) or initial_result.get("task_diagnostics", []) or []
    old_by_task = {str(row.get("task_id") or ""): row for row in old_rows}
    task_rows = []
    for final in unscheduled:
        row = copy.deepcopy(old_by_task.get(str(final.get("task_id") or ""), {}))
        row.update({
            "task_id": final.get("task_id"),
            "product_id": final.get("product_id"),
            "required_quantity": final.get("required_quantity"),
            "scheduled_quantity": final.get("scheduled_quantity"),
            "unscheduled_quantity": final.get("unscheduled_quantity"),
            "primary_reason": final.get("primary_reason"),
            "secondary_reasons": final.get("secondary_reasons", []),
            "final_reason_codes": final.get("reason_codes", []),
            "business_text": final.get("business_text", ""),
        })
        task_rows.append(row)

    grouped: Dict[str, Dict[str, Any]] = {}
    for row in unscheduled:
        quantity = float(row.get("unscheduled_quantity") or 0.0)
        if quantity <= 1e-6:
            continue
        code = str(row.get("primary_reason") or "CAPACITY_SHORTAGE")
        item = grouped.setdefault(code, {"reason_code": code, "task_count": 0, "quantity": 0.0})
        item["task_count"] += 1
        item["quantity"] += quantity
    summary = sorted(({
        **item, "quantity": _round3(item["quantity"]),
    } for item in grouped.values()), key=lambda item: (-item["quantity"], item["reason_code"]))

    diagnostics.update({
        "task_diagnostics": task_rows,
        "demand_coverage_rate": kpi.get("demand_coverage_rate", 0.0),
        "used_loom_count": kpi.get("used_loom_count", 0),
        "unused_loom_count": max(0, int(diagnostics.get("available_loom_count") or 0) - int(kpi.get("used_loom_count") or 0)),
        "available_machine_minutes": kpi.get("available_machine_minutes", 0),
        "scheduled_machine_minutes": kpi.get("scheduled_machine_minutes", 0),
        "utilization": kpi.get("fleet_utilization", 0.0),
        "utilization_formula": "最终织造分钟 / 扣除停机后的全厂可用织机分钟",
        "fully_unscheduled_task_count": sum(1 for row in unscheduled if float(row.get("scheduled_quantity") or 0) <= 1e-6),
        "partially_unscheduled_task_count": sum(1 for row in unscheduled
                                                 if float(row.get("scheduled_quantity") or 0) > 1e-6
                                                 and float(row.get("unscheduled_quantity") or 0) > 1e-6),
        "unscheduled_reason_summary": summary,
        "unscheduled_reason_quantity_reconcile": abs(
            sum(float(item["quantity"]) for item in summary) - float(kpi.get("unscheduled_quantity") or 0.0)
        ) <= 1e-3,
        "result_scope": "final_executable",
    })
    return diagnostics


def build_final_beam_ledger(initial_ledger: Mapping[str, Any],
                            execution: Mapping[str, Any]) -> Dict[str, Any]:
    """按最终逐轴分配重建余量和分配记录，保留初排台账作为来源证据。"""
    ledger = copy.deepcopy(initial_ledger or {})
    instances = ledger.get("instances", []) or []
    by_id: Dict[str, Dict[str, Any]] = {}
    for row in instances:
        beam_id = str(row.get("beam_instance_id") or "")
        if not beam_id:
            continue
        initial_meters = float(row.get("remaining_meters") or 0.0) + sum(
            float(item.get("allocated_meters") or 0.0) for item in row.get("allocations", []) or []
        )
        row["initial_meters"] = _round3(initial_meters)
        row["remaining_meters"] = _round3(initial_meters)
        row["allocations"] = []
        by_id[beam_id] = row

    weave_by_beam: Dict[str, Mapping[str, Any]] = {}
    for event in execution.get("weaving_plan", []) or []:
        beam_id = str(event.get("beam_id") or "")
        if beam_id:
            weave_by_beam.setdefault(beam_id, event)
    for event in execution.get("warping_plan", []) or []:
        beam_id = str(event.get("beam_id") or "")
        if not beam_id or beam_id in by_id:
            continue
        weave = weave_by_beam.get(beam_id, {})
        meters = float(event.get("quantity") or weave.get("beam_initial_meters") or 0.0)
        row = {
            "beam_instance_id": beam_id,
            "warp_beam_sku": _beam_sku_for(execution, beam_id),
            "total_meters": _round3(meters),
            "initial_meters": _round3(meters),
            "remaining_meters": _round3(meters),
            "available_minute": int(event.get("end_minute") or 0),
            "available_at": event.get("end"),
            "source_task_id": event.get("task_id"),
            "target_loom_ids": [event.get("loom_id")] if event.get("loom_id") else [],
            "status": "补排整经完成待上轴",
            "is_derived": True,
            "data_source": "最终执行计划明确补排",
            "allocations": [],
        }
        instances.append(row)
        by_id[beam_id] = row

    for allocation in execution.get("beam_allocation_audit", []) or []:
        beam_id = str(allocation.get("beam_instance_id") or "")
        row = by_id.get(beam_id)
        if row is None:
            continue
        quantity = float(allocation.get("allocated_meters") or 0.0)
        row["allocations"].append(copy.deepcopy(dict(allocation)))
        row["remaining_meters"] = _round3(max(0.0, float(row.get("remaining_meters") or 0.0) - quantity))
        row["status"] = "已分配" if row["remaining_meters"] <= 1e-6 else "部分分配"

    allocated = sum(float(item.get("allocated_meters") or 0.0)
                    for row in instances for item in row.get("allocations", []) or [])
    ledger.update({
        "instances": instances,
        "allocated_meters": _round3(allocated),
        "remaining_meters": _round3(sum(float(row.get("remaining_meters") or 0.0) for row in instances)),
        "final_allocation_count": sum(len(row.get("allocations", []) or []) for row in instances),
        "source": "最终可执行计划逐轴台账",
        "validation_ok": bool(execution.get("validation", {}).get("ok")),
    })
    return ledger


def _beam_sku_for(execution: Mapping[str, Any], beam_id: str) -> Optional[str]:
    for decision in execution.get("planning_trace", {}).get("decisions", []) or []:
        if beam_id in (decision.get("beam_ids") or []):
            return decision.get("warp_beam_sku")
    return None


def build_final_weekly_warping_plan(source_plan: Mapping[str, Any],
                                    execution: Mapping[str, Any]) -> Dict[str, Any]:
    source = copy.deepcopy(source_plan or {})
    source_by_id = {str(row.get("task_id") or ""): row for row in source.get("tasks", []) or []}
    tasks = []
    for index, event in enumerate(execution.get("warping_plan", []) or [], start=1):
        original = source_by_id.get(str(event.get("task_id") or ""), {})
        tasks.append({
            **original,
            "task_id": event.get("task_id") or event.get("event_id"),
            "sequence": index,
            "warp_beam_sku": original.get("warp_beam_sku") or _beam_sku_for(execution, str(event.get("beam_id") or "")),
            "product_ids": original.get("product_ids") or ([event.get("product_id")] if event.get("product_id") else []),
            "plan_date": str(event.get("start") or "")[:10],
            "start": event.get("start"),
            "end": event.get("end"),
            "complete_at": event.get("end"),
            "plan_meters": _round3(event.get("quantity")),
            "plan_count": 1,
            "target_loom_id": original.get("target_loom_id") or ([event.get("loom_id")] if event.get("loom_id") else []),
            "machine_placeholder": event.get("resource_id") or "整经计划池",
            "warping_resource_mode": "计划池",
            "data_source": "最终可执行计划",
            "is_derived": True,
            "beam_instance_id": event.get("beam_id"),
            "beam_origin": event.get("beam_origin"),
        })
    days = int(source.get("horizon_days") or 7)
    start_day = str(source.get("schedule_start") or execution.get("schedule_start") or "")[:10]
    daily = []
    if start_day:
        import datetime as dt
        base = dt.date.fromisoformat(start_day)
        for offset in range(days):
            date = (base + dt.timedelta(days=offset)).isoformat()
            rows = [row for row in tasks if str(row.get("plan_date") or "") == date]
            daily.append({
                "date": date,
                "task_count": len(rows),
                "plan_count": sum(int(row.get("plan_count") or 0) for row in rows),
                "plan_meters": _round3(sum(float(row.get("plan_meters") or 0.0) for row in rows)),
            })
    source.update({
        "tasks": tasks,
        "daily": daily,
        "stats": {
            **copy.deepcopy(source.get("stats", {}) or {}),
            "task_count": len(tasks),
            "beam_sku_count": len({row.get("warp_beam_sku") for row in tasks if row.get("warp_beam_sku")}),
            "plan_count": sum(int(row.get("plan_count") or 0) for row in tasks),
            "plan_meters": _round3(sum(float(row.get("plan_meters") or 0.0) for row in tasks)),
            "utilization": sum(max(0, int(event.get("end_minute") or 0) - int(event.get("start_minute") or 0))
                               for event in execution.get("warping_plan", []) or []) / (days * 1440) if days else 0.0,
        },
        "result_scope": "final_executable",
        "note": "与最终织造计划共用同一份逐轴执行事件，包含明确补排整经。",
    })
    return source


def build_final_process_gantt(base: Mapping[str, Any], final_schedule: Mapping[str, Any]) -> Dict[str, Any]:
    """把最终工艺事件转换为工艺甘特图接口结构，避免前端二次推断。"""
    result = copy.deepcopy(base)
    execution = final_schedule.get("execution", {}) or {}
    chains = {str(row.get("product_id") or ""): row
              for row in result.get("product_reconciliation", []) or []}

    def event_bar(event: Mapping[str, Any], process: str, index: int) -> Dict[str, Any]:
        product_id = str(event.get("product_id") or "")
        chain = chains.get(product_id, {})
        beam_id = event.get("beam_id")
        quantity = _round3(event.get("quantity"))
        row = {
            "bar_id": str(event.get("event_id") or f"FINAL-{process}-{index}"),
            "process": process,
            "label": str(event.get("label") or product_id or beam_id or ""),
            "product_id": product_id,
            "resource_id": str(event.get("resource_id") or event.get("loom_id") or ""),
            "loom_id": event.get("loom_id"),
            "beam_id": beam_id,
            "beam_instance_id": beam_id,
            "warp_beam_sku": chain.get("warp_beam_sku") or _beam_sku_for(execution, str(beam_id or "")),
            "weaving_sku": chain.get("weaving_sku"),
            "washing_sku": chain.get("washing_sku"),
            "quantity": quantity,
            "setup_type": event.get("setup_type"),
            "setup_label": event.get("setup_label"),
            "start": event.get("start"),
            "end": event.get("end"),
            "derived": True,
            "time_source": "最终执行事件",
            "data_source": "最终可执行计划",
        }
        if process == "整经":
            row.update({"plan_meters": quantity, "plan_count": 1,
                        "machine_display": row["resource_id"],
                        "target_loom_ids": [event.get("loom_id")] if event.get("loom_id") else [],
                        "beam_instance_ids": [beam_id] if beam_id else []})
        if process == "水洗":
            row.update({"machine_id": row["resource_id"], "plan_length": quantity})
        return row

    mapping = [
        ("整经", "warping_plan"),
        ("穿综穿筘", "threading_plan"),
        ("织造准备", "loom_setup_plan"),
        ("织造", "weaving_plan"),
    ]
    groups = []
    for process, key in mapping:
        groups.append({"process": process, "bars": [event_bar(event, process, index)
                                                      for index, event in enumerate(execution.get(key, []) or [], 1)]})
    washing = [event for event in execution.get("events", []) or [] if event.get("event_type") == "washing"]
    groups.append({"process": "水洗", "bars": [event_bar(event, "水洗", index)
                                                  for index, event in enumerate(washing, 1)]})
    counts = {group["process"]: len(group["bars"]) for group in groups}
    result.update({
        "process_order": ["整经", "穿综穿筘", "织造准备", "织造", "水洗"],
        "groups": groups,
        "stats": {
            **copy.deepcopy(result.get("stats", {}) or {}),
            "warp_task_count": counts["整经"],
            "threading_task_count": counts["穿综穿筘"],
            "setup_task_count": counts["织造准备"],
            "weave_task_count": counts["织造"],
            "wash_task_count": counts["水洗"],
        },
        "order_warnings": [] if final_schedule.get("validation", {}).get("ok") else ["最终执行校验未通过"],
        "note": "当前甘特图与工况模拟共用后端保存的最终可执行计划事件；跨天任务由前端按日切片显示。",
        "view_mode": "executable" if final_schedule.get("validation", {}).get("ok") else "invalid",
        "schedule_id": final_schedule.get("schedule_id"),
        "result_scope": "final_executable",
    })
    return result


def finalize_schedule(scenario: Any, payload: Dict[str, Any], execution: Dict[str, Any],
                      snapshot_summary: Mapping[str, Any],
                      simulation_config: Mapping[str, Any]) -> Dict[str, Any]:
    """保留初排证据，并将顶层结果替换为最终可执行业务口径。"""
    initial_plan = {
        "assignments": copy.deepcopy(payload.get("assignments", []) or []),
        "unscheduled": copy.deepcopy(payload.get("unscheduled", []) or []),
        "kpi": copy.deepcopy(payload.get("kpi", {}) or {}),
        "diagnostics": copy.deepcopy(payload.get("diagnostics", {}) or {}),
        "task_diagnostics": copy.deepcopy(payload.get("task_diagnostics", []) or []),
        "validation": copy.deepcopy(payload.get("validation", {}) or {}),
        "warping_plan": copy.deepcopy(payload.get("warping_plan", {}) or {}),
        "weaving_plan": copy.deepcopy(payload.get("weaving_plan", {}) or {}),
        "beam_ledger": copy.deepcopy(payload.get("beam_ledger", {}) or {}),
        "target_loom_audit": copy.deepcopy(payload.get("target_loom_audit", {}) or {}),
    }
    assignments = build_final_assignments(scenario, initial_plan, execution)
    unscheduled = build_final_unscheduled(scenario, initial_plan, assignments, execution)
    kpi = build_final_kpi(scenario, initial_plan, assignments, unscheduled, execution)
    diagnostics = build_final_diagnostics(initial_plan, kpi, unscheduled)
    beam_ledger = build_final_beam_ledger(initial_plan["beam_ledger"], execution)
    warping_plan = build_final_weekly_warping_plan(initial_plan["warping_plan"], execution)
    validation = copy.deepcopy(execution.get("validation", {}) or {"ok": False, "checks": [], "errors": ["缺少执行校验"]})

    final_schedule = {
        "schema_version": FINAL_SCHEDULE_SCHEMA_VERSION,
        "schedule_id": payload.get("schedule_id"),
        "result_scope": "final_executable",
        "status": "EXECUTABLE" if validation.get("ok") else "INVALID",
        "generated_at": execution.get("generated_at"),
        "schedule_start": payload.get("schedule_start"),
        "schedule_end": payload.get("schedule_end"),
        "input_shopfloor_snapshot": copy.deepcopy(dict(snapshot_summary)),
        "simulation_config": copy.deepcopy(dict(simulation_config)),
        "assignments": assignments,
        "unscheduled": unscheduled,
        "kpi": kpi,
        "diagnostics": diagnostics,
        "validation": validation,
        "process_events": copy.deepcopy(execution.get("events", []) or []),
        "warping_plan": warping_plan,
        "warping_events": copy.deepcopy(execution.get("warping_plan", []) or []),
        "threading_events": copy.deepcopy(execution.get("threading_plan", []) or []),
        "loom_setup_events": copy.deepcopy(execution.get("loom_setup_plan", []) or []),
        "weaving_events": copy.deepcopy(execution.get("weaving_plan", []) or []),
        "beam_ledger": beam_ledger,
        "planning_trace": copy.deepcopy(execution.get("planning_trace", {}) or {}),
        "execution": copy.deepcopy(execution),
    }

    payload["initial_plan"] = initial_plan
    payload["final_schedule"] = final_schedule
    payload["assignments"] = assignments
    payload["unscheduled"] = unscheduled
    payload["kpi"] = kpi
    payload["diagnostics"] = diagnostics
    payload["task_diagnostics"] = diagnostics.get("task_diagnostics", [])
    payload["validation"] = validation
    payload["warping_plan"] = warping_plan
    payload["beam_ledger"] = beam_ledger
    payload["result_scope"] = "final_executable"
    return payload
