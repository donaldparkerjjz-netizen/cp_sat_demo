# -*- coding: utf-8 -*-
"""织造排产的滚动工况模拟层。

现有 :mod:`weaving_demo.solver` 负责 CP-SAT 织造任务分配；本模块把求解结果展开为
可执行的经轴级事件，补齐业务流程图中的四类准备方式、整经/穿综穿筘联动、提前备轴和
未来 1～2 天工况预测。

这是第一版可运行模拟，准备时长均为显式可配置的演示参数。待现场确认后，应替换为真实
标准工时、整经机/穿综穿筘工位数量和实体经轴状态。
"""
from __future__ import annotations

import copy
import datetime as dt
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from weaving_demo import prep
from weaving_demo.model import Loom, Product, ProductionTask, WeavingScenario
from weaving_demo.solver import solve


DIRECT_CONTINUE = "direct_continue"
BEAM_JOINING = "beam_joining"
ORIGINAL_STYLE_SETUP = "original_style_setup"
CHANGE_STYLE_SETUP = "change_style_setup"

SETUP_LABELS = {
    DIRECT_CONTINUE: "线边余轴直接续产",
    BEAM_JOINING: "同品番接经",
    ORIGINAL_STYLE_SETUP: "原品番仕挂",
    CHANGE_STYLE_SETUP: "改品番仕挂",
}


@dataclass(frozen=True)
class SimulationConfig:
    """模拟参数；所有时间单位均为分钟。"""

    lead_time_minutes: int = 120
    edge_support_use_limit: int = 5
    default_beam_length_m: float = 3600.0
    warping_minutes_per_beam: int = 240
    threading_minutes: int = 480
    loom_setup_minutes: Mapping[str, int] = field(default_factory=lambda: {
        DIRECT_CONTINUE: 0,
        BEAM_JOINING: 120,
        ORIGINAL_STYLE_SETUP: 390,
        CHANGE_STYLE_SETUP: 340,
    })
    forecast_hours: Tuple[int, ...] = (24, 48)
    cp_sat_time_limit_s: float = 8.0
    compatibility_mode: str = "simulation"

    def assumptions(self) -> List[str]:
        return [
            f"经轴最晚在上机前 {self.lead_time_minutes} 分钟准备完成。",
            f"边撑连续使用上限暂按 {self.edge_support_use_limit} 次模拟。",
            f"缺少产品设定长度时，经轴长度暂按 {self.default_beam_length_m:g} 米。",
            "整经与穿综穿筘暂各按一个资源池串行安排。",
            "织造速度使用产品织造效率；任务在停机区间内不可开工，暂不允许中途抢占。",
            "准备工时为演示参数，现场确认后应替换。",
        ]


@dataclass
class LoomRuntimeState:
    """滚动窗口起点的织机/经轴状态。"""

    loom_id: str
    current_product_id: Optional[str] = None
    current_beam_id: Optional[str] = None
    remaining_beam_m: float = 0.0
    edge_support_uses: int = 0
    available_minute: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class _ResourcePool:
    resource_id: str
    available_minute: int = 0

    def reserve(self, duration: int, earliest: int = 0) -> Tuple[int, int]:
        start = max(int(earliest), self.available_minute)
        end = start + max(0, int(duration))
        self.available_minute = end
        return start, end


@dataclass
class _BeamStock:
    """工况模拟中的单根经轴；米数只允许从统一逐轴台账扣减。"""

    beam_id: str
    beam_code: str
    product_id: Optional[str]
    initial_meters: float
    remaining_meters: float
    available_minute: int
    target_loom_ids: Tuple[str, ...]
    source_task_id: Optional[str]
    origin: str
    bound_loom_id: Optional[str] = None
    on_loom_at_window_start: bool = False


def default_runtime_states(scenario: WeavingScenario) -> Dict[str, LoomRuntimeState]:
    """根据织机主档生成保守的窗口起点状态。"""
    return {
        loom.织机号: LoomRuntimeState(
            loom_id=loom.织机号,
            current_product_id=_clean_product(loom.目前对应产品),
            remaining_beam_m=0.0,
            edge_support_uses=0,
        )
        for loom in scenario.织机
    }


def run_schedule_simulation(
    scenario: WeavingScenario,
    *,
    runtime_states: Optional[Mapping[str, LoomRuntimeState]] = None,
    config: Optional[SimulationConfig] = None,
    solve_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """求解织造计划并展开为经轴级生产模拟。

    ``runtime_states`` 不会被原地修改，便于同一输入做基线/异常场景对照。
    """
    cfg = config or SimulationConfig()
    sc = copy.deepcopy(scenario)
    states = _copy_states(runtime_states or default_runtime_states(sc))
    ref = prep.schedule_ref(sc, sc.规则配置 or {})
    product_map = {p.产品款号: p for p in sc.产品}
    task_map = {t.task_id: t for t in sc.生产任务}

    if solve_result is None:
        solve_result = solve(
            sc,
            objective="lexicographic",
            max_time_s=cfg.cp_sat_time_limit_s,
            compatibility_mode=cfg.compatibility_mode,
            recompute_allowed=False,
        )

    if solve_result.get("status") not in ("OPTIMAL", "FEASIBLE"):
        return {
            "status": "SOLVE_FAILED",
            "solver": solve_result,
            "assumptions": cfg.assumptions(),
            "events": [],
            "forecasts": [],
            "validation": {"ok": False, "checks": [], "errors": ["CP-SAT 未返回可用排程"]},
        }

    # API 周排程必须走统一整经计划 + 逐轴台账路径。旧的最小演示场景没有这两项，
    # 仍保留下面的独立演示逻辑，避免把测试样例误当成可发布计划。
    if "warping_plan" in solve_result and "beam_ledger" in solve_result:
        return _run_ledger_constrained_simulation(
            sc=sc,
            states=states,
            input_states=_copy_states(runtime_states or default_runtime_states(sc)),
            cfg=cfg,
            solve_result=solve_result,
            ref=ref,
            product_map=product_map,
            task_map=task_map,
        )

    warping_pool = _ResourcePool("WAR-POOL-01")
    threading_pool = _ResourcePool("THREAD-01")
    downtime = _downtime_by_loom(sc.维护区间)
    events: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    sequence_by_loom: Dict[str, int] = {}
    beam_sequence = 0

    assignments = sorted(
        solve_result.get("assignments", []),
        key=lambda x: (int(x.get("start_minute", 0)), str(x.get("loom_id")), str(x.get("task_id"))),
    )
    for assignment in assignments:
        loom_id = str(assignment["loom_id"])
        state = states.setdefault(loom_id, LoomRuntimeState(loom_id=loom_id))
        task = task_map.get(str(assignment["task_id"]))
        product = product_map.get(str(assignment["product_id"]))
        if task is None or product is None:
            issues.append({
                "severity": "ERROR",
                "code": "MISSING_MASTER_DATA",
                "task_id": assignment.get("task_id"),
                "message": "求解结果引用了不存在的任务或产品主档。",
            })
            continue

        sequence_by_loom[loom_id] = sequence_by_loom.get(loom_id, 0) + 1
        remaining_qty = float(assignment.get("scheduled_quantity", 0.0))
        planned_start = int(assignment.get("start_minute", 0))
        part_no = 0
        assignment_beams = list(assignment.get("beam_allocations") or [])
        while remaining_qty > 1e-6:
            part_no += 1
            same_product = state.current_product_id == task.product_id
            has_line_beam = same_product and state.remaining_beam_m > 1e-6
            beam_length = _beam_length(product, cfg)

            if has_line_beam:
                setup_type = DIRECT_CONTINUE
                segment_qty = min(remaining_qty, state.remaining_beam_m)
                beam_id = state.current_beam_id or f"LINE-{loom_id}-{task.product_id}"
                beam_ready = None
            else:
                setup_type = classify_setup(state, task.product_id, cfg)
                ledger_beam = assignment_beams.pop(0) if assignment_beams else None
                if ledger_beam:
                    beam_length = float(ledger_beam.get("beam_total_meters") or beam_length)
                    segment_qty = min(remaining_qty, float(ledger_beam.get("allocated_meters") or beam_length))
                    beam_id = str(ledger_beam.get("beam_instance_id"))
                else:
                    segment_qty = min(remaining_qty, beam_length)
                    beam_sequence += 1
                    beam_id = f"SIM-{task.beam_code or task.product_id}-{beam_sequence:03d}"
                beam_ready = _schedule_upstream_preparation(
                    events=events,
                    task=task,
                    product=product,
                    loom_id=loom_id,
                    beam_id=beam_id,
                    setup_type=setup_type,
                    segment_qty=segment_qty,
                    warping_pool=warping_pool,
                    threading_pool=threading_pool,
                    ref=ref,
                    cfg=cfg,
                )
                state.current_beam_id = beam_id
                state.remaining_beam_m = beam_length

            desired_setup_start = max(state.available_minute, planned_start)
            if beam_ready is not None:
                desired_setup_start = max(desired_setup_start, beam_ready + cfg.lead_time_minutes)
                if desired_setup_start > planned_start:
                    issues.append({
                        "severity": "INFO",
                        "code": "PREP_PUSHED_WEAVE",
                        "task_id": task.task_id,
                        "loom_id": loom_id,
                        "message": f"{beam_id} 准备与提前期使织造开始后移 {desired_setup_start - planned_start} 分钟。",
                    })

            setup_duration = int(cfg.loom_setup_minutes[setup_type])
            production_duration = _weave_minutes(segment_qty, product)
            block_duration = setup_duration + production_duration
            block_start = _next_non_overlapping_start(
                desired_setup_start, block_duration, downtime.get(loom_id, [])
            )
            if block_start > desired_setup_start:
                issues.append({
                    "severity": "WARNING",
                    "code": "DOWNTIME_PUSHED_TASK",
                    "task_id": task.task_id,
                    "loom_id": loom_id,
                    "message": f"设备停机窗口使任务后移 {block_start - desired_setup_start} 分钟。",
                })

            setup_start = block_start
            setup_end = setup_start + setup_duration
            if setup_duration:
                events.append(_event(
                    event_type="loom_setup",
                    process="织造准备",
                    task=task,
                    product=product,
                    resource_id=loom_id,
                    loom_id=loom_id,
                    beam_id=beam_id,
                    start=setup_start,
                    end=setup_end,
                    ref=ref,
                    quantity=segment_qty,
                    setup_type=setup_type,
                    label=SETUP_LABELS[setup_type],
                ))

            weave_start = setup_end
            weave_end = weave_start + production_duration
            events.append(_event(
                event_type="weaving",
                process="织造生产",
                task=task,
                product=product,
                resource_id=loom_id,
                loom_id=loom_id,
                beam_id=beam_id,
                start=weave_start,
                end=weave_end,
                ref=ref,
                quantity=segment_qty,
                setup_type=setup_type,
                label=f"{task.product_id} 织造",
                extra={
                    "assignment_part_index": assignment.get("part_index"),
                    "beam_segment_index": part_no,
                    "planned_start_minute": planned_start,
                    "planned_end_minute": int(assignment.get("end_minute", planned_start)),
                    "sequence_on_loom": sequence_by_loom[loom_id],
                    "beam_ready_minute": beam_ready,
                    "required_ready_by_minute": setup_start - cfg.lead_time_minutes,
                },
            ))

            state.available_minute = weave_end
            state.current_product_id = task.product_id
            state.remaining_beam_m = max(0.0, state.remaining_beam_m - segment_qty)
            _advance_edge_support(state, setup_type)
            remaining_qty -= segment_qty
            planned_start = weave_end

    _append_downtime_events(events, downtime, ref)
    events.sort(key=lambda x: (x["start_minute"], x["end_minute"], x["event_type"]))

    forecasts = build_forecasts(
        events=events,
        scenario=sc,
        tasks=task_map,
        ref=ref,
        cutoffs=[hours * 60 for hours in cfg.forecast_hours],
    )
    validation = validate_simulation(events, solve_result, cfg)
    kpi = _simulation_kpi(events, solve_result, task_map)

    return {
        "status": "SIMULATED" if validation["ok"] else "SIMULATION_INVALID",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "schedule_start": prep.minute_to_iso(0, ref),
        "solver_status": solve_result.get("status"),
        "solver_schedule_id": solve_result.get("schedule_id"),
        "assumptions": cfg.assumptions(),
        "input_runtime_states": {k: v.to_dict() for k, v in _copy_states(runtime_states or default_runtime_states(sc)).items()},
        "final_runtime_states": {k: v.to_dict() for k, v in states.items()},
        "events": events,
        "weaving_plan": [e for e in events if e["event_type"] == "weaving"],
        "loom_setup_plan": [e for e in events if e["event_type"] == "loom_setup"],
        "threading_plan": [e for e in events if e["event_type"] == "threading"],
        "warping_plan": [e for e in events if e["event_type"] == "warping"],
        "forecasts": forecasts,
        "kpi": kpi,
        "issues": issues,
        "validation": validation,
        "solver": solve_result,
    }


def _run_ledger_constrained_simulation(
    *,
    sc: WeavingScenario,
    states: Dict[str, LoomRuntimeState],
    input_states: Dict[str, LoomRuntimeState],
    cfg: SimulationConfig,
    solve_result: Dict[str, Any],
    ref: dt.datetime,
    product_map: Mapping[str, Product],
    task_map: Mapping[str, ProductionTask],
) -> Dict[str, Any]:
    """用同一份周整经计划和逐轴台账生成七天内可执行的工况事件。

    与旧演示路径不同，本路径不会在缺轴时直接构造 ``SIM-*`` 经轴。只有周整经计划、
    期初台账或明确追加到整经计划池的补排轴可以被织造事件消耗；无法满足时缩减织造量。
    """
    horizon = int(solve_result.get("kpi", {}).get("horizon_days") or 7) * 1440
    downtime = _downtime_by_loom(sc.维护区间)
    events: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    threading_pool = _ResourcePool("THREAD-01")
    warping_pool = _ResourcePool("WAR-POOL-01")
    stocks = _beam_stocks_from_ledger(
        solve_result.get("beam_ledger", {}), states, task_map
    )

    weekly_rows = list((solve_result.get("warping_plan") or {}).get("tasks") or [])
    for row in weekly_rows:
        start = _minute_from_iso(row.get("start"), ref)
        end = _minute_from_iso(row.get("complete_at") or row.get("end"), ref)
        if end <= start or start < 0 or end > horizon:
            issues.append({
                "severity": "ERROR",
                "code": "WARPING_OUTSIDE_HORIZON",
                "task_id": row.get("task_id"),
                "message": "一周整经任务超出七天边界，未纳入可执行工况。",
            })
            continue
        warping_pool.available_minute = max(warping_pool.available_minute, end)
        events.append(_warping_event_from_weekly_row(row, start, end, ref))

    sequence_by_loom: Dict[str, int] = {}
    allocation_audit: List[Dict[str, Any]] = []
    reduced_total = 0.0
    supplemental_count = 0
    supplemental_sequence = 0

    def assignment_dispatch_key(row: Mapping[str, Any]) -> Tuple[int, int, str, str]:
        """先投放已到位/更早到位的轴，避免晚到轴占住穿综资源。"""
        planned = max(0, int(row.get("start_minute") or 0))
        loom_id = str(row.get("loom_id") or "")
        task = task_map.get(str(row.get("task_id") or ""))
        state = states.get(loom_id, LoomRuntimeState(loom_id=loom_id))
        candidates = (
            _compatible_beam_stocks(stocks, task=task, loom_id=loom_id, state=state)
            if task is not None and loom_id else []
        )
        beam_ready = min((beam.available_minute for beam in candidates), default=horizon + 1)
        return max(planned, int(beam_ready)), planned, loom_id, str(row.get("task_id") or "")

    assignments = sorted(solve_result.get("assignments", []), key=assignment_dispatch_key)
    for assignment in assignments:
        loom_id = str(assignment.get("loom_id") or "")
        state = states.setdefault(loom_id, LoomRuntimeState(loom_id=loom_id))
        task = task_map.get(str(assignment.get("task_id")))
        product = product_map.get(str(assignment.get("product_id")))
        requested_qty = float(assignment.get("scheduled_quantity") or 0.0)
        if task is None or product is None or not loom_id:
            reduced_total += requested_qty
            issues.append({
                "severity": "ERROR",
                "code": "MISSING_MASTER_DATA",
                "task_id": assignment.get("task_id"),
                "message": "任务、产品或织机主数据缺失，织造量已从模拟中移除。",
            })
            continue

        sequence_by_loom[loom_id] = sequence_by_loom.get(loom_id, 0) + 1
        remaining_qty = requested_qty
        planned_start = max(0, int(assignment.get("start_minute") or 0))
        segment_index = 0
        supplement_attempted = False
        last_failure = "beam_shortage"

        while remaining_qty > 1e-6:
            candidates = _compatible_beam_stocks(
                stocks, task=task, loom_id=loom_id, state=state
            )
            scheduled = False
            for beam in candidates:
                setup_type = _setup_type_for_beam(state, task.product_id, beam, loom_id, cfg)
                current_on_loom = (
                    beam.on_loom_at_window_start
                    and beam.bound_loom_id == loom_id
                    and state.current_beam_id == beam.beam_id
                    and state.current_product_id == task.product_id
                )
                thread_start = thread_end = None
                ready_for_loom = int(beam.available_minute)
                if setup_type == CHANGE_STYLE_SETUP:
                    thread_start = max(threading_pool.available_minute, ready_for_loom)
                    thread_end = thread_start + int(cfg.threading_minutes)
                    ready_for_loom = thread_end

                lead = 0 if current_on_loom else int(cfg.lead_time_minutes)
                desired_setup_start = max(
                    int(state.available_minute), planned_start, ready_for_loom + lead
                )
                setup_duration = int(cfg.loom_setup_minutes[setup_type])
                block_start, segment_qty, production_duration = _fit_segment_in_horizon(
                    desired_start=desired_setup_start,
                    setup_duration=setup_duration,
                    requested_qty=min(remaining_qty, beam.remaining_meters),
                    product=product,
                    horizon=horizon,
                    downtime=downtime.get(loom_id, []),
                )
                if segment_qty <= 1e-6:
                    last_failure = "horizon"
                    continue

                if thread_end is not None:
                    if thread_end > horizon:
                        last_failure = "horizon"
                        continue
                    threading_pool.available_minute = thread_end
                    events.append(_event(
                        event_type="threading", process="穿综穿筘", task=task, product=product,
                        resource_id=threading_pool.resource_id, loom_id=loom_id,
                        beam_id=beam.beam_id, start=thread_start, end=thread_end, ref=ref,
                        quantity=segment_qty, setup_type=setup_type,
                        label=f"{beam.beam_id} 穿综穿筘",
                        extra={"beam_source_task_id": beam.source_task_id, "beam_origin": beam.origin},
                    ))

                setup_start = block_start
                setup_end = setup_start + setup_duration
                if setup_duration:
                    events.append(_event(
                        event_type="loom_setup", process="织造准备", task=task, product=product,
                        resource_id=loom_id, loom_id=loom_id, beam_id=beam.beam_id,
                        start=setup_start, end=setup_end, ref=ref, quantity=segment_qty,
                        setup_type=setup_type, label=SETUP_LABELS[setup_type],
                        extra={"beam_source_task_id": beam.source_task_id, "beam_origin": beam.origin},
                    ))

                weave_start = setup_end
                weave_end = weave_start + production_duration
                segment_index += 1
                events.append(_event(
                    event_type="weaving", process="织造生产", task=task, product=product,
                    resource_id=loom_id, loom_id=loom_id, beam_id=beam.beam_id,
                    start=weave_start, end=weave_end, ref=ref, quantity=segment_qty,
                    setup_type=setup_type, label=f"{task.product_id} 织造",
                    extra={
                        "assignment_part_index": assignment.get("part_index"),
                        "beam_segment_index": segment_index,
                        "planned_start_minute": int(assignment.get("start_minute") or 0),
                        "planned_end_minute": int(assignment.get("end_minute") or 0),
                        "sequence_on_loom": sequence_by_loom[loom_id],
                        "beam_ready_minute": None if current_on_loom else ready_for_loom,
                        "required_ready_by_minute": setup_start - int(cfg.lead_time_minutes),
                        "beam_source_task_id": beam.source_task_id,
                        "beam_origin": beam.origin,
                        "beam_initial_meters": round(beam.initial_meters, 6),
                    },
                ))

                beam.bound_loom_id = loom_id
                beam.remaining_meters = max(0.0, beam.remaining_meters - segment_qty)
                state.available_minute = weave_end
                state.current_product_id = task.product_id
                state.current_beam_id = beam.beam_id
                state.remaining_beam_m = beam.remaining_meters
                _advance_edge_support(state, setup_type)
                remaining_qty -= segment_qty
                planned_start = weave_end
                allocation_audit.append({
                    "task_id": task.task_id,
                    "loom_id": loom_id,
                    "beam_instance_id": beam.beam_id,
                    "beam_source_task_id": beam.source_task_id,
                    "beam_origin": beam.origin,
                    "beam_available_minute": beam.available_minute,
                    "allocated_meters": round(segment_qty, 6),
                    "weave_start_minute": weave_start,
                    "weave_end_minute": weave_end,
                })
                scheduled = True
                supplement_attempted = False
                break

            if scheduled:
                continue

            # 台账里没有可分配经轴时，只允许把补轴任务明确追加到同一整经计划池；
            # 无品番映射或补轴后已无法在七天内织造，则不补虚拟轴，直接缩减织造量。
            if not candidates and not supplement_attempted and not str(task.beam_code or "").startswith("UNMAPPED-"):
                supplement_attempted = True
                supplemental_sequence += 1
                supplement = _append_supplemental_beam(
                    task=task,
                    product=product,
                    loom_id=loom_id,
                    state=state,
                    cfg=cfg,
                    ref=ref,
                    horizon=horizon,
                    warping_pool=warping_pool,
                    threading_pool=threading_pool,
                    sequence=supplemental_sequence,
                    planned_start=planned_start,
                )
                if supplement is not None:
                    beam, event = supplement
                    stocks.append(beam)
                    events.append(event)
                    supplemental_count += 1
                    issues.append({
                        "severity": "INFO",
                        "code": "SUPPLEMENTAL_WARPING_ADDED",
                        "task_id": task.task_id,
                        "loom_id": loom_id,
                        "message": f"经轴不足，已在同一整经计划池补排 {beam.beam_id}。",
                    })
                    continue
            break

        if remaining_qty > 1e-6:
            reduced_total += remaining_qty
            code = "WEAVING_REDUCED_HORIZON" if last_failure == "horizon" else "WEAVING_REDUCED_BEAM_SHORTAGE"
            reason = "七天内剩余时间不足" if last_failure == "horizon" else "没有可用且可追溯的经轴"
            issues.append({
                "severity": "WARNING",
                "code": code,
                "task_id": task.task_id,
                "loom_id": loom_id,
                "reduced_quantity": round(remaining_qty, 6),
                "message": f"{reason}，模拟织造量减少 {remaining_qty:.1f} 米。",
            })

    # 最终整经计划只保留被本轮可执行织造实际引用的经轴。期初余轴足够、
    # 或织造在执行校验中被缩减时，不得继续保留一根无人使用的“预防性”整经轴。
    used_beam_ids = {
        str(row.get("beam_instance_id") or "")
        for row in allocation_audit if row.get("beam_instance_id")
    }
    events = [
        event for event in events
        if event.get("event_type") != "warping"
        or str(event.get("beam_id") or "") in used_beam_ids
    ]
    final_warping_count = sum(1 for event in events if event.get("event_type") == "warping")
    _append_downtime_events(events, downtime, ref)
    events.sort(key=lambda row: (row["start_minute"], row["end_minute"], row["event_type"]))
    forecasts = build_forecasts(
        events=events, scenario=sc, tasks=task_map, ref=ref,
        cutoffs=[hours * 60 for hours in cfg.forecast_hours],
    )
    validation = validate_simulation(
        events, solve_result, cfg, horizon_minutes=horizon,
        explicitly_reduced_quantity=reduced_total,
    )
    kpi = _simulation_kpi(events, solve_result, task_map)
    kpi.update({
        "reduced_quantity": round(reduced_total, 3),
        "supplemental_warping_count": supplemental_count,
        "beam_bound_segment_count": len(allocation_audit),
        "over_horizon_event_count": sum(1 for e in events if int(e["end_minute"]) > horizon),
        "source_warping_task_count": final_warping_count,
    })
    planning_trace = _build_planning_trace(
        solve_result=solve_result,
        task_map=task_map,
        product_map=product_map,
        events=events,
        issues=issues,
        horizon=horizon,
        cfg=cfg,
        reduced_total=reduced_total,
        source_warping_count=final_warping_count,
        supplemental_count=supplemental_count,
    )
    return {
        "status": ("SIMULATED_ADJUSTED" if reduced_total > 1e-6 else "SIMULATED")
                  if validation["ok"] else "SIMULATION_INVALID",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "schedule_start": prep.minute_to_iso(0, ref),
        "solver_status": solve_result.get("status"),
        "solver_schedule_id": solve_result.get("schedule_id"),
        "assumptions": cfg.assumptions(),
        "input_runtime_states": {key: value.to_dict() for key, value in input_states.items()},
        "final_runtime_states": {key: value.to_dict() for key, value in states.items()},
        "events": events,
        "weaving_plan": [e for e in events if e["event_type"] == "weaving"],
        "loom_setup_plan": [e for e in events if e["event_type"] == "loom_setup"],
        "threading_plan": [e for e in events if e["event_type"] == "threading"],
        "warping_plan": [e for e in events if e["event_type"] == "warping"],
        "forecasts": forecasts,
        "kpi": kpi,
        "issues": issues,
        "validation": validation,
        "beam_allocation_audit": allocation_audit,
        "planning_trace": planning_trace,
        "warping_plan_source": "solve_result.warping_plan",
        "beam_ledger_source": "solve_result.beam_ledger",
        "solver": solve_result,
    }


def _build_planning_trace(
    *, solve_result: Mapping[str, Any], task_map: Mapping[str, ProductionTask],
    product_map: Mapping[str, Product], events: Sequence[Mapping[str, Any]],
    issues: Sequence[Mapping[str, Any]], horizon: int, cfg: SimulationConfig,
    reduced_total: float, source_warping_count: int, supplemental_count: int,
) -> Dict[str, Any]:
    """形成前端可解释的“订单→织造→经轴→整经→执行”决策链。"""
    weave_events = [event for event in events if event.get("event_type") == "weaving"]
    schedule_ref = prep.parse_iso(solve_result.get("schedule_start"))
    decisions: List[Dict[str, Any]] = []
    for assignment in solve_result.get("assignments", []) or []:
        task_id = str(assignment.get("task_id") or "")
        loom_id = str(assignment.get("loom_id") or "")
        part_index = assignment.get("part_index")
        task = task_map.get(task_id)
        product = product_map.get(str(assignment.get("product_id") or ""))
        matched = [
            event for event in weave_events
            if event.get("task_id") == task_id and event.get("loom_id") == loom_id
            and (part_index is None or event.get("assignment_part_index") == part_index)
        ]
        matched.sort(key=lambda event: int(event.get("start_minute") or 0))
        requested = float(assignment.get("scheduled_quantity") or 0.0)
        executable = sum(float(event.get("quantity") or 0.0) for event in matched)
        reduced = max(0.0, requested - executable)
        beam_ids = list(dict.fromkeys(str(event.get("beam_id")) for event in matched if event.get("beam_id")))
        origins = list(dict.fromkeys(str(event.get("beam_origin")) for event in matched if event.get("beam_origin")))
        ready_minutes = [int(event["beam_ready_minute"]) for event in matched
                         if event.get("beam_ready_minute") is not None]
        required_minutes = [int(event["required_ready_by_minute"]) for event in matched
                            if event.get("required_ready_by_minute") is not None]
        lead_ok = all(
            event.get("beam_ready_minute") is None
            or int(event["beam_ready_minute"]) <= int(event.get("required_ready_by_minute") or 0)
            for event in matched
        )
        related_issues = [
            str(issue.get("message")) for issue in issues
            if issue.get("task_id") == task_id
            and (not issue.get("loom_id") or issue.get("loom_id") == loom_id)
            and issue.get("code") not in ("SUPPLEMENTAL_WARPING_ADDED",)
        ]
        beam_length = _beam_length(product, cfg) if product is not None else 0.0
        due_at = task.due_date if task else None
        if not due_at and task and task.due_minute is not None and schedule_ref is not None:
            due_at = prep.minute_to_iso(int(task.due_minute), schedule_ref)
        status = "可执行" if reduced <= 1e-6 else ("部分排入" if executable > 1e-6 else "未排入")
        decisions.append({
            "task_id": task_id,
            "order_id": task_id.removeprefix("T-") or task_id,
            "product_id": assignment.get("product_id"),
            "due_at": due_at,
            "priority": float(task.priority or 0) if task else None,
            "split_allowed": bool(task.split_allowed) if task else False,
            "loom_id": loom_id,
            "warp_beam_sku": task.beam_code if task else None,
            "requested_quantity": round(requested, 3),
            "beam_length": round(beam_length, 3),
            "required_beam_count": math.ceil(requested / beam_length) if beam_length > 1e-6 else None,
            "beam_ids": beam_ids,
            "beam_origins": origins,
            "beam_ready_at": prep.minute_to_iso(min(ready_minutes), schedule_ref) if ready_minutes and schedule_ref else None,
            "required_ready_by": prep.minute_to_iso(min(required_minutes), schedule_ref) if required_minutes and schedule_ref else None,
            "lead_time_minutes": int(cfg.lead_time_minutes),
            "lead_time_ok": lead_ok and bool(matched),
            "first_weave_start": matched[0].get("start") if matched else None,
            "last_weave_end": matched[-1].get("end") if matched else None,
            "executable_quantity": round(executable, 3),
            "reduced_quantity": round(reduced, 3),
            "status": status,
            "reason": "；".join(dict.fromkeys(related_issues)) or ("全部约束通过" if matched else "没有可执行织造区段"),
        })

    required_quantity = sum(float(task.required_quantity or 0.0) for task in task_map.values())
    solver_quantity = sum(float(row.get("scheduled_quantity") or 0.0)
                          for row in solve_result.get("assignments", []) or [])
    distinct_beams = {str(event.get("beam_id")) for event in weave_events if event.get("beam_id")}
    executable_quantity = sum(float(event.get("quantity") or 0.0) for event in weave_events)
    return {
        "flow": ["订单需求", "织造初排", "逐轴拆分", "整经反排", "穿综与备轴", "可执行织造"],
        "rules": [
            "订单按交期优先、优先级次之进入计划。",
            "织造任务按适配织机、产能、现有机上状态和换款成本初排。",
            "每段织造必须绑定具体经轴，且累计用量不得超过经轴剩余米数。",
            f"非机上经轴必须在织造准备前至少 {cfg.lead_time_minutes} 分钟到位。",
            "缺轴时只能明确补排整经或缩减织造数量，不能凭空补轴。",
            f"所有整经、准备和织造事件必须位于 {horizon // 1440} 天窗口内。",
        ],
        "stages": [
            {"key": "orders", "label": "订单需求", "value": f"{len(task_map)} 单 / {required_quantity:,.1f} 米",
             "detail": "读取品番、数量、交期、优先级和拆单规则"},
            {"key": "weaving_draft", "label": "织造初排", "value": f"{len(solve_result.get('assignments', []) or [])} 段 / {solver_quantity:,.1f} 米",
             "detail": "按织机适配、产能、停机和换款成本分配"},
            {"key": "beams", "label": "逐轴拆分", "value": f"{len(distinct_beams)} 根 / {len(weave_events)} 段",
             "detail": "逐段绑定轴号并扣减剩余米数"},
            {"key": "warping", "label": "整经反排", "value": f"原计划 {source_warping_count} / 补排 {supplemental_count}",
             "detail": "由织造需要时间反推经轴完成与投放顺序"},
            {"key": "lead", "label": "穿综与备轴", "value": f"提前 {cfg.lead_time_minutes} 分钟",
             "detail": "按仕挂类型安排穿综、上轴和准备"},
            {"key": "execution", "label": "可执行织造", "value": f"{executable_quantity:,.1f} 米",
             "detail": f"缩减 {reduced_total:,.1f} 米；全部限制在七天内"},
        ],
        "decisions": decisions,
    }


def _beam_stocks_from_ledger(
    ledger: Mapping[str, Any],
    states: Mapping[str, LoomRuntimeState],
    task_map: Mapping[str, ProductionTask],
) -> List[_BeamStock]:
    state_by_beam = {
        state.current_beam_id: state
        for state in states.values()
        if state.current_beam_id and state.remaining_beam_m > 1e-6
    }
    product_to_code = {task.product_id: str(task.beam_code or task.product_id) for task in task_map.values()}
    stocks: List[_BeamStock] = []
    seen = set()
    for row in ledger.get("instances", []) or []:
        beam_id = str(row.get("beam_instance_id") or "")
        if not beam_id:
            continue
        allocated = sum(float(item.get("allocated_meters") or 0.0) for item in row.get("allocations", []) or [])
        initial = float(row.get("remaining_meters") or 0.0) + allocated
        if initial <= 1e-6:
            continue
        state = state_by_beam.get(beam_id)
        source_task_id = row.get("source_task_id")
        data_source = str(row.get("data_source") or "")
        if source_task_id:
            origin = "weekly_warping_plan"
        elif "阶段一" in data_source:
            origin = "shopfloor_snapshot"
        else:
            origin = "initial_inventory"
        stocks.append(_BeamStock(
            beam_id=beam_id,
            beam_code=str(row.get("warp_beam_sku") or ""),
            product_id=state.current_product_id if state else None,
            initial_meters=initial,
            remaining_meters=initial,
            available_minute=int(row.get("available_minute") or 0),
            target_loom_ids=tuple(str(x) for x in (row.get("target_loom_ids") or [])),
            source_task_id=str(source_task_id) if source_task_id else None,
            origin=origin,
            bound_loom_id=state.loom_id if state else None,
            on_loom_at_window_start=state is not None,
        ))
        seen.add(beam_id)

    # 防止旧台账漏掉真实机上余轴；只补快照中明确存在的当前轴，不创造线边备轴。
    for state in states.values():
        if not state.current_beam_id or state.current_beam_id in seen or state.remaining_beam_m <= 1e-6:
            continue
        product_id = state.current_product_id
        stocks.append(_BeamStock(
            beam_id=state.current_beam_id,
            beam_code=product_to_code.get(product_id or "", product_id or ""),
            product_id=product_id,
            initial_meters=float(state.remaining_beam_m),
            remaining_meters=float(state.remaining_beam_m),
            available_minute=0,
            target_loom_ids=(state.loom_id,),
            source_task_id=None,
            origin="shopfloor_snapshot",
            bound_loom_id=state.loom_id,
            on_loom_at_window_start=True,
        ))
    return stocks


def _compatible_beam_stocks(
    stocks: Sequence[_BeamStock], *, task: ProductionTask,
    loom_id: str, state: LoomRuntimeState,
) -> List[_BeamStock]:
    loom = _loom_key(loom_id)
    candidates = []
    for beam in stocks:
        if beam.remaining_meters <= 1e-6:
            continue
        if beam.beam_code != str(task.beam_code or "") and beam.product_id != task.product_id:
            continue
        if beam.bound_loom_id and _loom_key(beam.bound_loom_id) != loom:
            continue
        # 周整经计划的 target_loom_ids 是品番主档给出的建议投向，并非已经上机的物理绑定。
        # 织机适配由上游 CP-SAT assignment 保证；只有已上机/已绑定经轴才在上面按 bound_loom_id 锁定。
        if (
            beam.origin != "weekly_warping_plan"
            and beam.target_loom_ids
            and loom not in {_loom_key(x) for x in beam.target_loom_ids}
        ):
            continue
        candidates.append(beam)
    candidates.sort(key=lambda beam: (
        0 if beam.beam_id == state.current_beam_id else 1,
        beam.available_minute,
        beam.beam_id,
    ))
    return candidates


def _setup_type_for_beam(
    state: LoomRuntimeState, product_id: str, beam: _BeamStock,
    loom_id: str, cfg: SimulationConfig,
) -> str:
    if (
        beam.on_loom_at_window_start and beam.bound_loom_id == loom_id
        and beam.beam_id == state.current_beam_id
        and state.current_product_id == product_id
    ):
        return DIRECT_CONTINUE
    return classify_setup(state, product_id, cfg)


def _fit_segment_in_horizon(
    *, desired_start: int, setup_duration: int, requested_qty: float,
    product: Product, horizon: int, downtime: Sequence[Tuple[int, int]],
) -> Tuple[int, float, int]:
    if requested_qty <= 1e-6:
        return desired_start, 0.0, 0
    capacity = float(product.织造效率 or 400.0)
    start = _next_non_overlapping_start(desired_start, setup_duration + 1, downtime)
    for _ in range(3):
        available_production = max(0, horizon - start - setup_duration)
        max_qty = math.floor(available_production * capacity / 1440.0 * 1000.0) / 1000.0
        qty = min(float(requested_qty), max_qty)
        if qty <= 1e-6:
            return start, 0.0, 0
        production_duration = _weave_minutes(qty, product)
        shifted = _next_non_overlapping_start(
            desired_start, setup_duration + production_duration, downtime
        )
        if shifted == start:
            return start, qty, production_duration
        start = shifted
    available_production = max(0, horizon - start - setup_duration)
    qty = min(
        float(requested_qty),
        math.floor(available_production * capacity / 1440.0 * 1000.0) / 1000.0,
    )
    return start, qty, _weave_minutes(qty, product) if qty > 1e-6 else 0


def _append_supplemental_beam(
    *, task: ProductionTask, product: Product, loom_id: str,
    state: LoomRuntimeState, cfg: SimulationConfig, ref: dt.datetime,
    horizon: int, warping_pool: _ResourcePool, threading_pool: _ResourcePool,
    sequence: int, planned_start: int,
) -> Optional[Tuple[_BeamStock, Dict[str, Any]]]:
    warp_start = int(warping_pool.available_minute)
    warp_end = warp_start + int(cfg.warping_minutes_per_beam)
    setup_type = classify_setup(state, task.product_id, cfg)
    ready = warp_end
    if setup_type == CHANGE_STYLE_SETUP:
        ready = max(threading_pool.available_minute, warp_end) + int(cfg.threading_minutes)
    earliest_setup = max(state.available_minute, planned_start, ready + int(cfg.lead_time_minutes))
    if warp_end > horizon or earliest_setup + int(cfg.loom_setup_minutes[setup_type]) + 1 > horizon:
        return None
    warping_pool.available_minute = warp_end
    beam_id = f"SUPP-{task.beam_code}-{sequence:03d}"
    beam_length = _beam_length(product, cfg)
    beam = _BeamStock(
        beam_id=beam_id,
        beam_code=str(task.beam_code or ""),
        product_id=task.product_id,
        initial_meters=beam_length,
        remaining_meters=beam_length,
        available_minute=warp_end,
        target_loom_ids=(loom_id,),
        source_task_id=f"WARP-SUPP-{task.task_id}-{sequence:03d}",
        origin="supplemental_warping",
    )
    event = _event(
        event_type="warping", process="整经", task=task, product=product,
        resource_id=warping_pool.resource_id, loom_id=loom_id, beam_id=beam_id,
        start=warp_start, end=warp_end, ref=ref, quantity=beam_length,
        setup_type=setup_type, label=f"{beam_id} 补排整经",
        extra={"beam_source_task_id": beam.source_task_id, "beam_origin": beam.origin,
               "data_source": "simulation_supplement"},
    )
    return beam, event


def _warping_event_from_weekly_row(
    row: Mapping[str, Any], start: int, end: int, ref: dt.datetime,
) -> Dict[str, Any]:
    product_ids = list(row.get("product_ids") or [])
    resource = str(row.get("warping_machine_id") or row.get("machine_placeholder") or "WAR-POOL-01")
    task_id = str(row.get("task_id") or f"WARP-{row.get('warp_beam_sku')}-{start}")
    beam_id = str(row.get("beam_instance_id") or task_id)
    return {
        "event_id": f"warping:{task_id}:{start}:{end}:{beam_id}",
        "event_type": "warping",
        "process": "整经",
        "label": f"{beam_id} 整经",
        "task_id": task_id,
        "product_id": product_ids[0] if product_ids else None,
        "resource_id": resource,
        "loom_id": None,
        "target_loom_ids": list(row.get("target_loom_id") or []),
        "beam_id": beam_id,
        "setup_type": None,
        "setup_label": None,
        "quantity": round(float(row.get("plan_meters") or 0.0), 6),
        "start_minute": start,
        "end_minute": end,
        "start": prep.minute_to_iso(start, ref),
        "end": prep.minute_to_iso(end, ref),
        "beam_source_task_id": task_id,
        "beam_origin": "weekly_warping_plan",
        "data_source": row.get("data_source") or "一周整经计划",
    }


def _minute_from_iso(value: Any, ref: dt.datetime) -> int:
    parsed = prep.parse_iso(value)
    if parsed is None:
        return 0
    return int((parsed - ref).total_seconds() // 60)


def _loom_key(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return raw.removeprefix("LOOM-").removeprefix("#").strip()


def classify_setup(
    state: LoomRuntimeState,
    product_id: str,
    config: Optional[SimulationConfig] = None,
) -> str:
    """按流程图判定下一只经轴的准备方式。"""
    cfg = config or SimulationConfig()
    if state.current_product_id == product_id and state.remaining_beam_m > 1e-6:
        return DIRECT_CONTINUE
    if state.current_product_id == product_id:
        if state.edge_support_uses < cfg.edge_support_use_limit:
            return BEAM_JOINING
        return ORIGINAL_STYLE_SETUP
    return CHANGE_STYLE_SETUP


def build_forecasts(
    *,
    events: Sequence[Dict[str, Any]],
    scenario: WeavingScenario,
    tasks: Mapping[str, ProductionTask],
    ref: dt.datetime,
    cutoffs: Iterable[int],
) -> List[Dict[str, Any]]:
    """按事件线性进度计算指定时点的产出和设备工况。"""
    loom_ids = [l.织机号 for l in scenario.织机]
    forecasts = []
    for cutoff in sorted(set(int(x) for x in cutoffs)):
        produced_by_product: Dict[str, float] = {}
        completed_tasks = set()
        task_last_end: Dict[str, int] = {}
        for e in events:
            if e["event_type"] != "weaving":
                continue
            start, end = e["start_minute"], e["end_minute"]
            duration = max(1, end - start)
            if cutoff <= start:
                done = 0.0
            elif cutoff >= end:
                done = float(e["quantity"])
                completed_tasks.add(e["task_id"])
            else:
                done = float(e["quantity"]) * (cutoff - start) / duration
            produced_by_product[e["product_id"]] = produced_by_product.get(e["product_id"], 0.0) + done
            task_last_end[e["task_id"]] = max(task_last_end.get(e["task_id"], 0), end)

        states = {loom_id: "等待" for loom_id in loom_ids}
        active_detail: Dict[str, Optional[str]] = {loom_id: None for loom_id in loom_ids}
        for e in events:
            loom_id = e.get("loom_id")
            if not loom_id or not (e["start_minute"] <= cutoff < e["end_minute"]):
                continue
            if e["event_type"] == "downtime":
                states[loom_id] = "停机"
            elif e["event_type"] == "loom_setup" and states[loom_id] != "停机":
                states[loom_id] = "准备"
                active_detail[loom_id] = e.get("label")
            elif e["event_type"] == "weaving" and states[loom_id] not in ("停机", "准备"):
                states[loom_id] = "织造"
                active_detail[loom_id] = e.get("product_id")

        late_tasks = []
        for task_id, end in task_last_end.items():
            task = tasks.get(task_id)
            if task and task.due_minute is not None and end > task.due_minute:
                late_tasks.append({"task_id": task_id, "lateness_minutes": end - task.due_minute})

        forecasts.append({
            "cutoff_minutes": cutoff,
            "cutoff": prep.minute_to_iso(cutoff, ref),
            "produced_meters": round(sum(produced_by_product.values()), 3),
            "produced_by_product": {k: round(v, 3) for k, v in sorted(produced_by_product.items())},
            "loom_state_count": {name: sum(1 for v in states.values() if v == name)
                                 for name in ("织造", "准备", "停机", "等待")},
            "loom_states": [{"loom_id": loom_id, "state": states[loom_id],
                             "detail": active_detail[loom_id]} for loom_id in loom_ids],
            "completed_task_count": len(completed_tasks),
            "late_task_count": len(late_tasks),
            "late_tasks": late_tasks,
        })
    return forecasts


def validate_simulation(
    events: Sequence[Dict[str, Any]],
    solve_result: Dict[str, Any],
    config: Optional[SimulationConfig] = None,
    *,
    horizon_minutes: Optional[int] = None,
    explicitly_reduced_quantity: float = 0.0,
) -> Dict[str, Any]:
    cfg = config or SimulationConfig()
    checks: List[Dict[str, Any]] = []
    errors: List[str] = []

    for resource_key, event_types, name in (
        ("loom_id", {"loom_setup", "weaving", "downtime"}, "loom_no_overlap"),
        ("resource_id", {"warping"}, "warping_no_overlap"),
        ("resource_id", {"threading"}, "threading_no_overlap"),
    ):
        grouped: Dict[str, List[Tuple[int, int, str]]] = {}
        for e in events:
            if e["event_type"] not in event_types or not e.get(resource_key):
                continue
            grouped.setdefault(str(e[resource_key]), []).append(
                (int(e["start_minute"]), int(e["end_minute"]), str(e["event_id"]))
            )
        overlaps = []
        for resource, intervals in grouped.items():
            intervals.sort()
            for left, right in zip(intervals, intervals[1:]):
                if right[0] < left[1]:
                    overlaps.append({"resource": resource, "left": left[2], "right": right[2]})
        passed = not overlaps
        checks.append({"check": name, "pass": passed, "details": overlaps})
        if not passed:
            errors.append(f"{name} 存在资源时间重叠")

    lead_violations = []
    for e in events:
        if e["event_type"] != "weaving" or e.get("beam_ready_minute") is None:
            continue
        if int(e["beam_ready_minute"]) > int(e["required_ready_by_minute"]):
            lead_violations.append(e["event_id"])
    checks.append({"check": "beam_ready_lead_time", "pass": not lead_violations,
                   "details": lead_violations, "lead_time_minutes": cfg.lead_time_minutes})
    if lead_violations:
        errors.append("存在经轴未提前准备完成的织造段")

    if horizon_minutes is not None:
        horizon_violations = [
            e["event_id"] for e in events
            if int(e.get("start_minute", 0)) < 0
            or int(e.get("end_minute", 0)) > int(horizon_minutes)
        ]
        checks.append({
            "check": "seven_day_horizon_boundary",
            "pass": not horizon_violations,
            "details": horizon_violations,
            "horizon_minutes": int(horizon_minutes),
        })
        if horizon_violations:
            errors.append("存在超出七天边界的工况事件")

    unbound = [
        e["event_id"] for e in events
        if e.get("event_type") == "weaving" and not e.get("beam_id")
    ]
    checks.append({"check": "every_weaving_segment_has_beam", "pass": not unbound,
                   "details": unbound})
    if unbound:
        errors.append("存在未绑定具体经轴的织造段")

    consumption: Dict[str, float] = {}
    initial_by_beam: Dict[str, float] = {}
    missing_origin = []
    for e in events:
        if e.get("event_type") != "weaving":
            continue
        beam_id = str(e.get("beam_id") or "")
        if not beam_id:
            continue
        consumption[beam_id] = consumption.get(beam_id, 0.0) + float(e.get("quantity") or 0.0)
        if e.get("beam_initial_meters") is not None:
            initial_by_beam[beam_id] = max(
                initial_by_beam.get(beam_id, 0.0), float(e["beam_initial_meters"])
            )
        if horizon_minutes is not None and not e.get("beam_origin"):
            missing_origin.append(e["event_id"])
    overdrawn = [
        {"beam_id": beam_id, "consumed_meters": round(used, 6),
         "available_meters": round(initial_by_beam.get(beam_id, 0.0), 6)}
        for beam_id, used in consumption.items()
        if beam_id in initial_by_beam and used > initial_by_beam[beam_id] + 1e-6
    ]
    checks.append({"check": "beam_quantity_capacity", "pass": not overdrawn,
                   "details": overdrawn})
    checks.append({"check": "beam_source_traceability", "pass": not missing_origin,
                   "details": missing_origin})
    if overdrawn:
        errors.append("存在经轴米数超额消耗")
    if missing_origin:
        errors.append("存在无法追溯到整经计划或期初台账的经轴")

    solver_qty = sum(float(a.get("scheduled_quantity", 0.0)) for a in solve_result.get("assignments", []))
    simulated_qty = sum(float(e.get("quantity", 0.0)) for e in events if e["event_type"] == "weaving")
    qty_ok = abs(solver_qty - simulated_qty - float(explicitly_reduced_quantity)) <= 1e-3
    checks.append({"check": "quantity_reconciliation", "pass": qty_ok,
                   "solver_quantity": solver_qty, "simulated_quantity": simulated_qty,
                   "explicitly_reduced_quantity": round(float(explicitly_reduced_quantity), 6)})
    if not qty_ok:
        errors.append("模拟产量、明确缩减量与 CP-SAT 已排数量无法对账")

    return {"ok": not errors, "checks": checks, "errors": errors}


def _schedule_upstream_preparation(
    *,
    events: List[Dict[str, Any]],
    task: ProductionTask,
    product: Product,
    loom_id: str,
    beam_id: str,
    setup_type: str,
    segment_qty: float,
    warping_pool: _ResourcePool,
    threading_pool: _ResourcePool,
    ref: dt.datetime,
    cfg: SimulationConfig,
) -> int:
    warp_start, warp_end = warping_pool.reserve(cfg.warping_minutes_per_beam)
    events.append(_event(
        event_type="warping", process="整经", task=task, product=product,
        resource_id=warping_pool.resource_id, loom_id=loom_id, beam_id=beam_id,
        start=warp_start, end=warp_end, ref=ref, quantity=segment_qty,
        setup_type=setup_type, label=f"{beam_id} 整经",
    ))
    ready = warp_end
    if setup_type == CHANGE_STYLE_SETUP:
        th_start, th_end = threading_pool.reserve(cfg.threading_minutes, earliest=warp_end)
        events.append(_event(
            event_type="threading", process="穿综穿筘", task=task, product=product,
            resource_id=threading_pool.resource_id, loom_id=loom_id, beam_id=beam_id,
            start=th_start, end=th_end, ref=ref, quantity=segment_qty,
            setup_type=setup_type, label=f"{beam_id} 穿综穿筘",
        ))
        ready = th_end
    return ready


def _event(
    *,
    event_type: str,
    process: str,
    task: ProductionTask,
    product: Product,
    resource_id: str,
    loom_id: Optional[str],
    beam_id: Optional[str],
    start: int,
    end: int,
    ref: dt.datetime,
    quantity: float,
    setup_type: Optional[str],
    label: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event_id = f"{event_type}:{task.task_id}:{loom_id or resource_id}:{start}:{end}:{beam_id or '-'}"
    body = {
        "event_id": event_id,
        "event_type": event_type,
        "process": process,
        "label": label,
        "task_id": task.task_id,
        "product_id": product.产品款号,
        "resource_id": resource_id,
        "loom_id": loom_id,
        "beam_id": beam_id,
        "setup_type": setup_type,
        "setup_label": SETUP_LABELS.get(setup_type),
        "quantity": round(float(quantity), 6),
        "start_minute": int(start),
        "end_minute": int(end),
        "start": prep.minute_to_iso(start, ref),
        "end": prep.minute_to_iso(end, ref),
    }
    if extra:
        body.update(extra)
    return body


def _append_downtime_events(
    events: List[Dict[str, Any]],
    downtime: Mapping[str, Sequence[Tuple[int, int]]],
    ref: dt.datetime,
) -> None:
    for loom_id, intervals in downtime.items():
        for idx, (start, end) in enumerate(intervals, 1):
            events.append({
                "event_id": f"downtime:{loom_id}:{idx}:{start}:{end}",
                "event_type": "downtime",
                "process": "设备停机",
                "label": "故障/维修不可用",
                "task_id": None,
                "product_id": None,
                "resource_id": loom_id,
                "loom_id": loom_id,
                "beam_id": None,
                "setup_type": None,
                "setup_label": None,
                "quantity": 0.0,
                "start_minute": start,
                "end_minute": end,
                "start": prep.minute_to_iso(start, ref),
                "end": prep.minute_to_iso(end, ref),
            })


def _simulation_kpi(
    events: Sequence[Dict[str, Any]],
    solve_result: Dict[str, Any],
    task_map: Mapping[str, ProductionTask],
) -> Dict[str, Any]:
    weaving = [e for e in events if e["event_type"] == "weaving"]
    setups = [e for e in events if e["event_type"] == "loom_setup"]
    completion: Dict[str, int] = {}
    for e in weaving:
        completion[e["task_id"]] = max(completion.get(e["task_id"], 0), e["end_minute"])
    late = {
        tid: max(0, end - task_map[tid].due_minute)
        for tid, end in completion.items()
        if tid in task_map and task_map[tid].due_minute is not None and end > task_map[tid].due_minute
    }
    setup_counts = {key: sum(1 for e in weaving if e.get("setup_type") == key) for key in SETUP_LABELS}
    return {
        "required_quantity": solve_result.get("kpi", {}).get("required_quantity"),
        "solver_scheduled_quantity": solve_result.get("kpi", {}).get("scheduled_quantity"),
        "simulated_quantity": round(sum(float(e["quantity"]) for e in weaving), 3),
        "simulated_completion_minute": max((e["end_minute"] for e in weaving), default=0),
        "late_task_count": len(late),
        "total_lateness_minutes": sum(late.values()),
        "setup_segment_count": len(setups),
        "setup_type_counts": setup_counts,
        "warping_task_count": sum(1 for e in events if e["event_type"] == "warping"),
        "threading_task_count": sum(1 for e in events if e["event_type"] == "threading"),
    }


def _copy_states(states: Mapping[str, LoomRuntimeState]) -> Dict[str, LoomRuntimeState]:
    return {key: copy.deepcopy(value) for key, value in states.items()}


def _clean_product(value: Optional[str]) -> Optional[str]:
    if value is None or str(value).strip() in ("", "0", "NULL"):
        return None
    return str(value).strip()


def _beam_length(product: Product, cfg: SimulationConfig) -> float:
    value = float(product.整经设定长度 or cfg.default_beam_length_m)
    return value if value > 0 else cfg.default_beam_length_m


def _weave_minutes(quantity: float, product: Product) -> int:
    efficiency = float(product.织造效率 or 400.0)
    return max(1, int(math.ceil(float(quantity) * 1440.0 / efficiency)))


def _advance_edge_support(state: LoomRuntimeState, setup_type: str) -> None:
    if setup_type == BEAM_JOINING:
        state.edge_support_uses += 1
    elif setup_type in (ORIGINAL_STYLE_SETUP, CHANGE_STYLE_SETUP):
        state.edge_support_uses = 1


def _downtime_by_loom(rows: Sequence[Dict[str, Any]]) -> Dict[str, List[Tuple[int, int]]]:
    out: Dict[str, List[Tuple[int, int]]] = {}
    for row in rows or []:
        loom_id = str(row.get("loom_id") or "")
        start = int(row.get("start_minute", 0))
        end = int(row.get("end_minute", 0))
        if loom_id and end > start:
            out.setdefault(loom_id, []).append((start, end))
    for intervals in out.values():
        intervals.sort()
    return out


def _next_non_overlapping_start(
    start: int,
    duration: int,
    downtime: Sequence[Tuple[int, int]],
) -> int:
    candidate = int(start)
    while True:
        conflict = next(
            ((left, right) for left, right in downtime
             if candidate < right and candidate + duration > left),
            None,
        )
        if conflict is None:
            return candidate
        candidate = conflict[1]
