# -*- coding: utf-8 -*-
"""
solver.py -- 整经织造排工排产 Demo · 阶段2 CP-SAT 排程核心
===============================================================================
使用 Google OR-Tools CP-SAT 真实求解（整数分钟）。要点：
  * 每个任务对每台兼容织机建立可选区间变量；NoOverlap 保证织机任务不重叠。
  * 维修/停机/锁定作为固定区间加入机台日历。
  * 同一实体经轴独占（虚拟经轴实体 WB-<品番>-001）。
  * 允许未排数量：能力/物料不足时返回部分可行方案，而非直接 INFEASIBLE。
  * 7 层字典序目标：未排数量→加权交期延误→最大交期延误→换产品次数→
    换经轴+穿综穿筘次数→相对原计划变动→提高利用率，每层固定后求下一层。
  * 所有时间输出 ISO 8601，同时保留内部分钟偏移。

接口：solve(scenario, objective="lexicographic", max_time_s=30.0, config=None)。
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from ortools.sat.python import cp_model  # type: ignore  # noqa: E402

from weaving_demo.model import (
    Product, Loom, WeavingScenario, ProductionTask, VirtualBeam,
)
from weaving_demo.config import BUSINESS_RULES, STAGE2_PARAMS, CONFIG_VERSION, CODE_VERSION
from weaving_demo import compat, prep, diagnose

STATUS_MAP = {
    cp_model.OPTIMAL: "OPTIMAL",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.UNKNOWN: "UNKNOWN",
}


# ============================================================================
# 内部：部件(task,k,loom)
# ============================================================================
class _Part:
    __slots__ = ("task_id", "k", "m", "loom_sel", "qty", "start", "end", "dur", "itv",
                 "production_dur", "_setup", "_capacity_scaled")

    def __init__(self, task_id: str, k: int, m: str):
        self.task_id = task_id
        self.k = k
        self.m = m
        self.loom_sel = None
        self.qty = None
        self.start = None
        self.end = None
        self.dur = None
        self.itv = None
        self.production_dur = None


class _TaskVars:
    __slots__ = ("active", "scheduled", "unscheduled", "lateness", "ends", "task")

    def __init__(self):
        self.active: List[Any] = []
        self.scheduled = None
        self.unscheduled = None
        self.lateness = None
        self.ends: List[Any] = []
        self.task = None


# ============================================================================
# 主求解
# ============================================================================
def solve(scenario: WeavingScenario, objective: str = "lexicographic",
          max_time_s: float = 30.0, config: Optional[Dict[str, Any]] = None,
          material_enabled: Optional[bool] = None, beam_enabled: Optional[bool] = None,
          compatibility_mode: Optional[str] = None, recompute_allowed: Optional[bool] = None,
          max_layers: Optional[int] = None, schedule_start: Optional[str] = None,
          horizon_days: Optional[int] = None):
    conf = config or BUSINESS_RULES
    t0 = time.time()
    # 允许按 API 请求覆盖排程窗口
    if schedule_start and scenario.设置:
        scenario.设置.排程起点 = schedule_start
    if horizon_days is not None and scenario.设置:
        import datetime as _dt
        from weaving_demo.prep import parse_iso as _pi
        st = _pi(schedule_start) if schedule_start else _pi(scenario.设置.排程起点)
        if st is None:
            st = _dt.datetime(2026, 4, 1, 0, 0, 0)
        scenario.设置.排程终点 = (st + _dt.timedelta(days=int(horizon_days))).strftime("%Y-%m-%d")
    ref = prep.schedule_ref(scenario, conf)
    horizon = prep.horizon_minutes(scenario, conf)

    tasks = prep.build_tasks(scenario, conf, mode=compatibility_mode,
                             recompute_allowed=bool(recompute_allowed))
    beams = prep.create_virtual_beams(scenario, tasks, conf)
    scenario.虚拟经轴 = beams  # 回填以便结果引用

    mat = STAGE2_PARAMS["material_enabled"] if material_enabled is None else material_enabled
    beam = STAGE2_PARAMS["beam_enabled"] if beam_enabled is None else beam_enabled
    mode = compatibility_mode or (conf.get("stage2_params", {}).get("compatibility_mode", "balanced"))

    plan = _Planner(scenario, tasks, conf, ref, horizon, material_enabled=mat,
                    beam_enabled=beam, compatibility_mode=mode)

    conflict = _detect_lock_conflicts(plan)
    if conflict:
        res = _infeasible_result(plan, conflict, objective, t0, model_stats=None)
        res["business_status"], res["risk_reasons"] = diagnose.business_status(res, conf)
        return res

    # 取消独立 L1 预求解：由正式分层求解的第一层承担"最小未排数量"的验证（全局截止时间控制总耗时）
    solver, best_values, layer_bounds, status, model_stats, layer_info = _run_layers(
        plan, max_time_s, objective, conf, max_layers=max_layers)
    if status in ("INFEASIBLE", "MODEL_INVALID", "UNKNOWN"):
        if status == "UNKNOWN" and best_values:
            r = _assemble(plan, solver, best_values, "FEASIBLE", t0, objective, model_stats, layer_bounds, layer_info, model_stats)
        else:
            res = _infeasible_result(plan, f"CP-SAT {status}", objective, t0, model_stats=model_stats, layer_info=layer_info)
            res["business_status"], res["risk_reasons"] = diagnose.business_status(res, conf)
            return res
        r["validation"] = _validate_schedule(r)
    else:
        r = _assemble(plan, solver, best_values, status, t0, objective, model_stats, layer_bounds, layer_info, model_stats)
        r["validation"] = _validate_schedule(r)

    r["diagnostics"] = diagnose.compute_diagnostics(scenario, tasks, r, conf, horizon, mode)
    diagnose._enrich_result(r, scenario, tasks, conf, mode, horizon)
    r["business_status"], r["risk_reasons"] = diagnose.business_status(r, conf)
    r["schedule_id"] = r.get("schedule_id") or f"sch-{int(time.time()*1000):x}"
    r["actual_total_wall_time_s"] = round(time.time() - t0, 3)
    r["provenance"] = _provenance(
        scenario, tasks, plan, conf, t0, max_time_s, mat, beam, mode, r["schedule_id"],
        model_stats.get("num_layers") if model_stats else None,
    )
    return r


def _provenance(scenario, tasks, plan, conf, t0, max_time_s, mat, beam, mode, schedule_id,
                objective_layer_count=None):
    """结果追溯字段：数据快照哈希、算法/配置版本、求解参数等。"""
    import hashlib
    base = {"products": [p.to_dict() for p in scenario.产品[:200]],
            "looms": [l.to_dict() for l in scenario.织机[:400]],
            "tasks": [t.to_dict() for t in tasks],
            "materials": [m.to_dict() for m in scenario.物料[:200]]}
    snap = hashlib.sha1(json.dumps(base, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    layer_count = int(objective_layer_count or len(STAGE2_PARAMS["objective_layers"]))
    return {
        "scenario_id": scenario.数据来源 or "current",
        "data_snapshot_hash": snap,
        "schedule_id": schedule_id,
        "schedule_start": prep.minute_to_iso(0, plan.ref),
        "schedule_end": prep.minute_to_iso(plan.horizon, plan.ref),
        "horizon_minutes": plan.horizon,
        "horizon_days": plan.horizon // 1440,
        "compatibility_mode": mode,
        "material_enabled": mat,
        "beam_enabled": beam,
        "objective_layers": layer_count,
        "per_layer_time_limit_s": round(float(max_time_s) / max(1, layer_count), 3),
        "total_time_limit_s": float(max_time_s),
        "task_count": len(tasks),
        "required_quantity": float(sum(t.required_quantity for t in tasks)),
        "config_version": CONFIG_VERSION,
        "code_version": CODE_VERSION,
        "solver": "google-or-tools-cp-sat",
    }


# ============================================================================
# Planner：把任务/织机/经轴排布为变量结构
# ============================================================================
class _Planner:
    def __init__(self, scenario: WeavingScenario, tasks: List[ProductionTask],
                 conf: Dict[str, Any], ref, horizon: int,
                 material_enabled: bool = True, beam_enabled: bool = True,
                 compatibility_mode: str = "balanced"):
        self.scenario = scenario
        self.tasks = tasks
        self.conf = conf
        self.ref = ref
        self.horizon = horizon
        self.material_enabled = material_enabled
        self.beam_enabled = beam_enabled
        self.compatibility_mode = compatibility_mode
        self.product_map = {p.产品款号: p for p in scenario.产品}
        self.loom_map = {l.织机号: l for l in scenario.织机}
        self.beam_entities: Dict[str, VirtualBeam] = {b.beam_id: b for b in scenario.虚拟经轴}
        # (task_id,k,m) -> _Part
        self.parts: Dict[Tuple[str, int, str], _Part] = {}
        # loom_id -> [(task_id,k)]
        self.parts_by_loom: Dict[str, List[Tuple[str, int]]] = {}
        # beam_code -> [(task_id,k)]
        self.parts_by_beam: Dict[str, List[Tuple[str, int]]] = {}
        self.task_max_parts: Dict[str, int] = {}
        self.task_min_batch: Dict[str, float] = {}
        self.task_compatible: Dict[str, List[str]] = {}
        self._build()

    def _build(self):
        for t in self.tasks:
            compat_ids = [m for m in (t.allowed_loom_ids or []) if m in self.loom_map]
            self.task_compatible[t.task_id] = compat_ids
            P = 1 if not t.split_allowed else max(1, int(t.max_parts or STAGE2_PARAMS["split_default"]["max_parts"]))
            self.task_max_parts[t.task_id] = P
            # split_allowed 控制的是“能否拆到多台织机”，不是“本周期必须一次做完全部需求”。
            # 即使不允许跨机拆分，短周期滚动排产也应允许在单台织机上安排部分数量。
            self.task_min_batch[t.task_id] = (
                t.min_batch_qty or STAGE2_PARAMS["split_default"]["min_batch_qty"]
            )
            prod = self.product_map.get(t.product_id)
            for k in range(P):
                for m in compat_ids:
                    part = _Part(t.task_id, k, m)
                    loom = self.loom_map[m]
                    part_setup = prep.setup_minutes(t, loom, config=self.conf)
                    capacities = [value for value in (
                        prod.织造效率 if prod else None,
                        loom.产能设定,
                    ) if value and float(value) > 0]
                    daily_capacity = min(float(value) for value in capacities) if capacities else 400.0
                    key = (t.task_id, k, m)
                    self.parts[key] = part
                    self.parts[key]._setup = part_setup
                    self.parts[key]._capacity_scaled = max(1, int(round(daily_capacity * 1000)))
                    self.parts_by_loom.setdefault(m, []).append((t.task_id, k))
            if t.beam_code:
                self.parts_by_beam.setdefault(t.beam_code, []).extend(
                    (t.task_id, k) for k in range(P))


# ============================================================================
# 锁定冲突预检
# ============================================================================
def _detect_lock_conflicts(plan: _Planner) -> Optional[str]:
    by_loom: Dict[str, List[ProductionTask]] = {}
    for t in plan.tasks:
        if not t.locked:
            continue
        mid = t.locked_machine_id
        if mid not in plan.loom_map:
            return f"任务 {t.task_id} 锁定机台 {mid} 不存在"
        if t.locked_start_minute is None or t.locked_end_minute is None or t.locked_quantity is None:
            return f"任务 {t.task_id} 锁定信息不完整（缺 start/end/quantity）"
        by_loom.setdefault(mid, []).append(t)
    for mid, lst in by_loom.items():
        lst.sort(key=lambda x: x.locked_start_minute)
        for a, b in zip(lst, lst[1:]):
            if b.locked_start_minute < a.locked_end_minute:
                return (f"锁定任务 {a.task_id} 与 {b.task_id} 在机台 {mid} 时间冲突 "
                        f"({a.locked_start_minute}-{a.locked_end_minute} vs "
                        f"{b.locked_start_minute}-{b.locked_end_minute})")
    return None


# ============================================================================
# 模型构建 + 分层求解
# ============================================================================
def _run_layers(plan: _Planner, max_time_s: float, objective: str, conf: Dict[str, Any],
                max_layers: Optional[int] = None):
    model = cp_model.CpModel()
    # Big-M 同时被用作未排数量等目标变量的上界。短周期（例如 7 天）
    # 可能无法消化全部需求，因此上界必须至少覆盖总需求量，不能只随时间窗变化。
    total_required = int(sum(max(0, t.required_quantity) for t in plan.tasks))
    big = max(int(plan.horizon) + 100000, total_required + 1)
    task_by_id = {t.task_id: t for t in plan.tasks}

    beam_entities_by_code: Dict[str, List[VirtualBeam]] = {}
    for b in plan.scenario.虚拟经轴:
        beam_entities_by_code.setdefault(b.beam_code, []).append(b)

    # ---- 部件变量/区间 ----
    for (tid, k, m), part in plan.parts.items():
        task = task_by_id[tid]
        name = f"{tid}_k{k}_m{m}"
        part.loom_sel = model.NewBoolVar(f"sel_{name}")
        part.qty = model.NewIntVar(0, int(task.required_quantity), f"qty_{name}")
        part.dur = model.NewIntVar(0, big, f"dur_{name}")
        part.production_dur = model.NewIntVar(0, big, f"prod_dur_{name}")
        part.start = model.NewIntVar(0, int(plan.horizon), f"s_{name}")
        part.end = model.NewIntVar(0, int(plan.horizon), f"e_{name}")
        part.itv = model.NewOptionalIntervalVar(part.start, part.dur, part.end, part.loom_sel,
                                                f"itv_{name}")
        _setup = getattr(part, "_setup")
        capacity_scaled = getattr(part, "_capacity_scaled")
        # 精确折算 ceil(qty * 1440 / 日产能)，避免400米/天被round成360米/天。
        numerator = model.NewIntVar(
            0,
            int(task.required_quantity) * 1440 * 1000 + capacity_scaled,
            f"prod_numerator_{name}",
        )
        model.Add(numerator == part.qty * 1440 * 1000 + capacity_scaled - 1)
        model.AddDivisionEquality(part.production_dur, numerator, capacity_scaled)
        model.Add(part.dur == part.production_dur + _setup * part.loom_sel)
        minb = int(plan.task_min_batch[tid])
        model.Add(part.qty >= minb * part.loom_sel)
        # 未选中该机时数量必为 0
        model.Add(part.qty <= int(task.required_quantity) * part.loom_sel)
        # 让未选区间的时间变量归零，使紧凑化目标只统计真实任务。
        model.Add(part.start == 0).OnlyEnforceIf(part.loom_sel.Not())
        model.Add(part.end == 0).OnlyEnforceIf(part.loom_sel.Not())

    # ---- 每织机 NoOverlap（含维修、锁定固定区间） ----
    for m, entries in plan.parts_by_loom.items():
        intervals = [plan.parts[(tid, k, m)].itv for (tid, k) in entries]
        for maint in plan.scenario.维护区间:
            if maint.get("loom_id") == m:
                intervals.append(model.NewFixedSizeIntervalVar(
                    maint["start_minute"], maint["end_minute"] - maint["start_minute"],
                    f"maint_{m}_{maint['start_minute']}"))
        model.AddNoOverlap(intervals)

    # ---- 锁定任务：强制占用锁定的机台与时间窗口（其自身部件即锁定区间） ----
    _add_lock_constraints(model, plan, task_by_id)

    # ---- 任务聚合、经轴独占、目标 ----
    task_vars: Dict[str, _TaskVars] = {}
    for t in plan.tasks:
        tv = _TaskVars()
        tv.task = t
        task_vars[t.task_id] = tv
        P = plan.task_max_parts[t.task_id]
        loom_ids = plan.task_compatible[t.task_id]
        qty_sum = []
        sels = []
        ends = []
        for k in range(P):
            if not loom_ids:
                continue
            active_k = model.NewBoolVar(f"act_{t.task_id}_k{k}")
            sel_of_k = [plan.parts[(t.task_id, k, m)].loom_sel for m in loom_ids]
            model.Add(sum(sel_of_k) == active_k)
            tv.active.append(active_k)
            for m in loom_ids:
                tv.ends.append(plan.parts[(t.task_id, k, m)].end)
            # 该部件所有织机的 qty 都对 scheduled 有贡献（只有被选中织机 qty>0）
            for m in loom_ids:
                qty_sum.append(plan.parts[(t.task_id, k, m)].qty)
            sels.extend(sel_of_k)
        if not loom_ids:
            # 无兼容织机 -> 必然全部未排
            tv.scheduled = model.NewIntVar(0, int(t.required_quantity), f"sch_{t.task_id}")
            model.Add(tv.scheduled == 0)
            tv.unscheduled = model.NewIntVar(0, int(t.required_quantity), f"unsch_{t.task_id}")
            model.Add(tv.unscheduled == int(t.required_quantity))
            continue
        tv.scheduled = model.NewIntVar(0, int(t.required_quantity), f"sch_{t.task_id}")
        model.Add(sum(qty_sum) == tv.scheduled)
        tv.unscheduled = model.NewIntVar(0, int(t.required_quantity), f"unsch_{t.task_id}")
        model.Add(int(t.required_quantity) == tv.scheduled + tv.unscheduled)

    # ---- 物料硬约束（库存>=0；未确认到货不计入；不足时靠未排数量部分可行） ----
    if plan.material_enabled:
        _add_material_constraint(model, plan, task_vars)

    # ---- 经轴独占（按品番聚合，非本任务内部即被排） ----
    if plan.beam_enabled:
        for code, entries in plan.parts_by_beam.items():
            intervals = []
            for (tid, k) in entries:
                loom_ids = plan.task_compatible[tid]
                if not loom_ids:
                    continue
                # 每个候选织机都有自己的可选区间；实际被选中的区间必须等待经轴可用。
                # 不能只约束候选清单中的第一台织机，否则换到其它织机时会绕过前道约束。
                for m in loom_ids:
                    part = plan.parts[(tid, k, m)]
                    intervals.append(part.itv)
                    for b in beam_entities_by_code.get(code, []):
                        model.Add(part.start >= b.earliest_available_minute).OnlyEnforceIf(part.loom_sel)
            if intervals:
                model.AddNoOverlap(intervals)

    # ---- 延误与各层目标 ----
    obj_exprs: Dict[str, Any] = {}
    unsched_terms = []
    tard_terms = []
    all_tard = []
    obj_style = model.NewIntVar(0, big, "obj_style")
    style_terms = []
    obj_changeover = model.NewIntVar(0, big, "obj_changeover")
    changeover_all_terms = []
    obj_split = model.NewIntVar(0, big, "obj_split")
    obj_machine = model.NewIntVar(0, big, "obj_machine")
    obj_plan = model.NewIntVar(0, big, "obj_plan")
    plan_terms = []
    prod_terms = []
    compact_terms = []

    for t in plan.tasks:
        tv = task_vars[t.task_id]
        if tv.unscheduled is not None:
            unsched_terms.append(tv.unscheduled)
        due = t.due_minute or int(plan.horizon)
        lateness = model.NewIntVar(0, big, f"late_{t.task_id}")
        tv.lateness = lateness
        if tv.ends:
            t_end = model.NewIntVar(0, int(plan.horizon), f"tend_{t.task_id}")
            model.AddMaxEquality(t_end, tv.ends)
            active_any = model.NewBoolVar(f"any_{t.task_id}")
            model.Add(sum(tv.active) == active_any) if tv.active else model.Add(active_any == 0)
            model.Add(lateness >= t_end - due - big * (1 - active_any))
        model.Add(lateness >= 0)
        all_tard.append(lateness)
        tard_terms.append(int(round(t.priority * 1000)) * lateness)

    max_tard = model.NewIntVar(0, big, "max_tard")
    model.AddMaxEquality(max_tard, all_tard) if all_tard else model.Add(max_tard == 0)

    for (tid, k, m), part in plan.parts.items():
        task = task_by_id[tid]
        loom = plan.loom_map[m]
        ct = prep.changeover_type(task, loom, conf)
        style_terms.append((1 if ct in ("style_change", "threading") else 0) * part.loom_sel)
        changeover_all_terms.append((1 if ct != "same" else 0) * part.loom_sel)
        plan_terms.append((1 if (task.original_loom_id and m != task.original_loom_id) else 0) * part.loom_sel)
        prod_terms.append(part.production_dur)
        compact_terms.append(part.end)

    # 任务拆分份数：每个任务除第 0 份之外的额外份数
    split_terms = []
    for t in plan.tasks:
        tv = task_vars[t.task_id]
        for k in range(1, len(tv.active)):
            split_terms.append(tv.active[k])

    # 启用机台数量：每台织机若安排了任意部件则计 1
    loom_used = {}
    machine_terms = []
    for m, entries in plan.parts_by_loom.items():
        sels = [plan.parts[(tid, k, m)].loom_sel for (tid, k) in entries]
        if not sels:
            continue
        lm = model.NewBoolVar(f"loom_used_{m}")
        model.AddMaxEquality(lm, sels)
        loom_used[m] = lm
        machine_terms.append(lm)

    model.Add(obj_style == sum(style_terms))
    model.Add(obj_plan == sum(plan_terms))
    model.Add(obj_changeover == sum(changeover_all_terms))
    model.Add(obj_split == sum(split_terms))
    model.Add(obj_machine == sum(machine_terms))
    obj_util = model.NewIntVar(0, big * 100, "obj_util")
    model.Add(obj_util == sum(prod_terms))
    obj_compact = model.NewIntVar(0, max(big, plan.horizon * max(1, len(plan.parts))), "obj_compact")
    model.Add(obj_compact == sum(compact_terms))

    obj_unsched = model.NewIntVar(0, big, "obj_unsched")
    model.Add(obj_unsched == sum(unsched_terms))
    obj_tard = model.NewIntVar(0, big * 1000, "obj_tard")
    model.Add(obj_tard == sum(tard_terms))

    expr_map = {
        "unscheduled_quantity": obj_unsched,
        "weighted_tardiness": obj_tard,
        "max_tardiness": max_tard,
        "task_split_count": obj_split,
        "machine_spread_count": obj_machine,
        "changeover_count": obj_changeover,
        "plan_change_count": obj_plan,
        "schedule_compactness": obj_compact,
        "utilization": obj_util,
    }
    layers = plan.conf.get("stage2_params", {}).get(
        "objective_layers", STAGE2_PARAMS["objective_layers"]
    )
    if max_layers:
        layers = layers[:int(max_layers)]
    solver = cp_model.CpSolver()
    per_layer_time = max(0.5, float(max_time_s) / max(1, len(layers)))
    # 第一层决定“尽量把需求排进去”，它的搜索空间通常最大，也直接决定后续层的
    # 可行上界。给第一层保留主要预算，避免层数增加后反而因时间被平均切碎而少排。
    if len(layers) <= 1:
        layer_time_budgets = [float(max_time_s)]
    else:
        first_budget = max(0.5, float(max_time_s) * 0.6)
        later_budget = max(0.2, (float(max_time_s) - first_budget) / (len(layers) - 1))
        layer_time_budgets = [first_budget] + [later_budget] * (len(layers) - 1)
    solver.parameters.max_time_in_seconds = per_layer_time
    solver.parameters.random_seed = int(STAGE2_PARAMS["random_seed"])
    solver.parameters.num_workers = 1
    solver.parameters.log_search_progress = False

    proto = model.Proto()
    model_stats = {
        "num_variables": len(proto.variables),
        "num_constraints": len(proto.constraints),
        "num_boolean": sum(1 for v in proto.variables if v.domain[0] == 1 and v.domain[-1] == 1),
        "solver": "ortools-cp-sat",
        "num_workers": int(solver.parameters.num_workers),
        "time_limit_s": float(max_time_s),
        "per_layer_time_s": round(per_layer_time, 3),
        "num_layers": len(layers),
    }

    best_values: Dict[str, int] = {}
    layer_bounds: Dict[str, int] = {}
    layer_info: List[Dict[str, Any]] = []
    status_name = "UNKNOWN"
    prev_var, prev_best = None, None
    last_solver = None
    last_obj_expr = None

    # 全局截止时间：max_time_s 为总时间预算，每层时间不得超过剩余时间
    deadline = time.monotonic() + float(max_time_s)
    solver_wall = 0.0

    # 给 CP-SAT 一个"全部未排"的可行初始解提示，确保每层快速拿到 FEASIBLE incumbent
    for part in plan.parts.values():
        model.add_hint(part.loom_sel, 0)
        model.add_hint(part.qty, 0)
        model.add_hint(part.start, 0)
        model.add_hint(part.end, 0)

    for li, layer in enumerate(layers):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break  # 时间预算耗尽，停止后续求解
        # 每层时间上限 = min(名义每层时间, 剩余时间)，并受全局截止时间约束
        layer_time = max(0.2, min(layer_time_budgets[li], remaining))
        if prev_var is not None:
            model.Add(prev_var <= prev_best + _tol(layer, conf))
        if layer == "utilization":
            model.Minimize(-expr_map[layer])
        else:
            model.Minimize(expr_map[layer])
        ls = cp_model.CpSolver()
        ls.parameters.max_time_in_seconds = layer_time
        ls.parameters.random_seed = int(STAGE2_PARAMS["random_seed"])
        ls.parameters.num_workers = 1
        ls.parameters.log_search_progress = False
        st = ls.Solve(model)
        lstatus = STATUS_MAP.get(st, "UNKNOWN")
        ltime = round(ls.WallTime(), 3)
        solver_wall += ltime
        if lstatus == "INFEASIBLE":
            status_name = "INFEASIBLE"; break
        if lstatus == "UNKNOWN":
            status_name = "UNKNOWN"; break
        val = ls.Value(expr_map[layer]) if layer != "utilization" else ls.Value(obj_util)
        best_values[layer] = val
        try:
            raw_bound = ls.BestObjectiveBound()
            if layer == "utilization":
                layer_bounds[layer] = -int(round(raw_bound))
            else:
                layer_bounds[layer] = int(round(raw_bound))
        except Exception:  # noqa: BLE001
            layer_bounds[layer] = None
        layer_info.append({
            "level": li + 1, "name": layer,
            "raw_status": lstatus,
            "raw_objective_value": val,
            "raw_best_bound": layer_bounds[layer],
            "raw_wall_time_s": ltime,
            "raw_objective_direction": "maximize" if layer == "utilization" else "minimize",
            "time_limit_s": round(layer_time, 3),
            "solve_time_s": ltime,
            "proven_optimal": lstatus == "OPTIMAL",
            "fixed_to_next": li < len(layers) - 1,
        })
        prev_var = expr_map[layer]
        prev_best = val
        last_solver = ls
        last_obj_expr = expr_map[layer]

    # 后续层允许在不破坏既有上界的前提下继续改善前序目标。
    # 因此对外报告应采用最终方案中的目标值，而不是该层刚结束时的旧 incumbent。
    if last_solver is not None:
        for info in layer_info:
            layer_name = info["name"]
            final_value = last_solver.Value(
                obj_util if layer_name == "utilization" else expr_map[layer_name]
            )
            info["raw_objective_value"] = final_value
            best_values[layer_name] = final_value

    # 补齐未求解层为 NOT_SOLVED（时间预算耗尽或中途停止），保证 L1–L8 都有真实状态
    done = {li["name"] for li in layer_info}
    for li, layer in enumerate(layers):
        if layer not in done:
            layer_info.append({
                "level": li + 1, "name": layer, "raw_status": "NOT_SOLVED",
                "raw_objective_value": None, "raw_best_bound": None,
                "raw_wall_time_s": 0.0, "raw_objective_direction":
                    "maximize" if layer == "utilization" else "minimize",
                "time_limit_s": None, "solve_time_s": None,
                "proven_optimal": False, "fixed_to_next": False,
            })

    status_name = status_name if status_name != "UNKNOWN" else _aggregate_status(layer_info)
    model_stats["actual_solver_wall_time_s"] = round(solver_wall, 3)
    model_stats["completed_layers"] = sum(1 for li in layer_info if li["raw_status"] in ("OPTIMAL", "FEASIBLE"))
    model_stats["deadline_exhausted"] = bool(status_name == "UNKNOWN" or any(li["raw_status"] == "NOT_SOLVED" for li in layer_info))
    model_stats["requested_time_limit_s"] = float(max_time_s)
    if last_solver is None:
        return solver, best_values, layer_bounds, "INFEASIBLE", model_stats, layer_info
    return last_solver, best_values, layer_bounds, status_name, model_stats, layer_info


def _aggregate_status(layer_info: List[Dict[str, Any]]) -> str:
    """整体状态：全部必需层均 OPTIMAL → OPTIMAL；L1 OPTIMAL + 后续 FEASIBLE → FEASIBLE；
       任一层不一致/未解 → 不声称 OPTIMAL（NOT_EXECUTABLE / UNKNOWN）。"""
    if not layer_info:
        return "UNKNOWN"
    if any(not li.get("consistent", True) for li in layer_info):
        return "NOT_EXECUTABLE"
    statuses = [li["raw_status"] for li in layer_info]
    if "NOT_SOLVED" in statuses or "UNKNOWN" in statuses:
        return "UNKNOWN" if any(s in ("NOT_SOLVED", "UNKNOWN", "INFEASIBLE") for s in statuses) else "FEASIBLE"
    if all(s == "OPTIMAL" for s in statuses):
        return "OPTIMAL"
    if statuses[0] == "OPTIMAL" and set(statuses) <= {"OPTIMAL", "FEASIBLE"}:
        return "FEASIBLE"
    if any(s == "INFEASIBLE" for s in statuses):
        return "INFEASIBLE"
    return "FEASIBLE"


def _tol(layer: str, conf: Dict[str, Any]) -> int:
    return int(conf.get("stage2_params", {}).get(
        "lexicographic_tolerances", STAGE2_PARAMS["lexicographic_tolerances"]
    ).get(layer, 0))


def _add_material_constraint(model, plan: _Planner, task_vars: Dict[str, "_TaskVars"]):
    """全局物料约束: 每纱线代码 已排数量*消耗 <= 可用库存(已确认)。
       这是硬约束；由于允许未排数量，物料不足时模型会减少/放弃部分任务，
       从而返回部分可行方案，而非整个模型 INFEASIBLE。"""
    budgets = prep.material_budgets(plan.scenario, plan.conf)
    per_yarn: Dict[str, List[Tuple[Any, float]]] = {}
    for t in plan.tasks:
        prod = plan.product_map.get(t.product_id)
        if not prod:
            continue
        yarn = prod.使用纱线
        consump = prod.纱线单耗KG_M
        if not yarn or not consump:
            continue
        tv = task_vars.get(t.task_id)
        if tv is None or tv.scheduled is None:
            continue
        per_yarn.setdefault(yarn, []).append((tv.scheduled, consump))
    for yarn, lst in per_yarn.items():
        avail = budgets.get(yarn)
        if avail is None:
            continue  # 无库存建档 -> 不约束（仅提示风险）
        scale = 1000
        model.Add(sum(sch * int(c * scale) for sch, c in lst) <= int(avail * scale))


def _add_lock_constraints(model, plan: _Planner, task_by_id: Dict[str, ProductionTask]):
    """锁定任务强制占用 locked_machine_id 的 locked_start~locked_end 窗口。
       locked_quantity 若给定则固定数量；其余部件必须未排。"""
    for t in plan.tasks:
        if not t.locked:
            continue
        loom_ids = plan.task_compatible.get(t.task_id, [])
        mid = t.locked_machine_id
        if mid not in loom_ids:
            continue  # 锁定机台不在兼容清单，仅依赖 NoOverlap；数据已由预检拦截
        for k in range(plan.task_max_parts[t.task_id]):
            key = (t.task_id, k, mid)
            if key not in plan.parts:
                continue
            part = plan.parts[key]
            if k == 0:
                model.Add(part.loom_sel == 1)
                model.Add(part.start == t.locked_start_minute)
                model.Add(part.end == t.locked_end_minute)
                if t.locked_quantity is not None:
                    model.Add(part.qty == int(t.locked_quantity))
            else:
                # 其余部件不排
                for m in loom_ids:
                    pk = (t.task_id, k, m)
                    if pk in plan.parts:
                        model.Add(plan.parts[pk].loom_sel == 0)


# ============================================================================
# 结果组装
# ============================================================================
def _assemble(plan: _Planner, solver, best_values: Dict[str, int], status: str,
              t0: float, objective: str, model_stats=None, layer_bounds=None, layer_info=None,
              model_stats2=None):
    task_by_id = {t.task_id: t for t in plan.tasks}
    assignments = []
    scheduled_by_task: Dict[str, float] = {tid: 0.0 for tid in task_by_id}
    kpi = dict(required_quantity=0.0, scheduled_quantity=0.0, unscheduled_quantity=0.0,
               on_time_quantity=0.0, late_quantity=0.0, total_lateness_minutes=0.0,
               max_lateness_minutes=0.0, changeover_count=0, beam_change_count=0,
               threading_count=0, plan_change_count=0, utilization=0.0)
    total_assigned_minutes = 0.0

    for (tid, k, m), part in plan.parts.items():
        if solver.Value(part.loom_sel) != 1:
            continue
        task = task_by_id[tid]
        loom = plan.loom_map[m]
        qty = float(min(max(0, solver.Value(part.qty)), int(task.required_quantity)))
        s_min = int(min(max(0, solver.Value(part.start)), plan.horizon))
        e_min = int(min(max(0, solver.Value(part.end)), plan.horizon))
        if e_min < s_min:
            e_min = s_min
        ct = prep.changeover_type(task, loom, plan.conf)
        lateness_min = max(0, e_min - (task.due_minute or plan.horizon))
        beam_id = _beam_id_for(plan, task.beam_code)
        beam_entity = next((b for b in plan.scenario.虚拟经轴 if b.beam_id == beam_id), None)
        assignments.append({
            "task_id": tid,
            "part_index": k,
            "loom_id": m,
            "product_id": task.product_id,
            "source_target_loom_ids": list(task.source_target_loom_ids or []),
            "target_mapping_status": task.target_mapping_status,
            "source_target_match": (m in (task.source_target_loom_ids or []))
            if task.source_target_loom_ids else None,
            "beam_id": beam_id,
            "beam_ready_minute": beam_entity.earliest_available_minute if beam_entity else 0,
            "beam_ready_at": beam_entity.earliest_available if beam_entity else None,
            "start": prep.minute_to_iso(s_min, plan.ref),
            "end": prep.minute_to_iso(e_min, plan.ref),
            "start_minute": s_min,
            "end_minute": e_min,
            "scheduled_quantity": qty,
            "locked": task.locked,
            "lock_reason": task.lock_reason,
            "changeover_type": ct,
            "lateness_minutes": lateness_min,
        })
        scheduled_by_task[tid] += qty
        total_assigned_minutes += (e_min - s_min)
        kpi["scheduled_quantity"] += qty
        kpi["total_lateness_minutes"] += lateness_min
        kpi["max_lateness_minutes"] = max(kpi["max_lateness_minutes"], lateness_min)
        if lateness_min > 0:
            kpi["late_quantity"] += qty
        else:
            kpi["on_time_quantity"] += qty
        if ct in ("style_change", "threading"):
            kpi["changeover_count"] += 1
        if ct == "beam_change":
            kpi["beam_change_count"] += 1
        if ct == "threading":
            kpi["threading_count"] += 1
        if task.original_loom_id and m != task.original_loom_id:
            kpi["plan_change_count"] += 1

    unscheduled = []
    # 机器散布/利用率相关指标
    loom_tasks: Dict[str, int] = {}
    for a in assignments:
        loom_tasks[a["loom_id"]] = loom_tasks.get(a["loom_id"], 0) + 1
    used_looms = set(loom_tasks.keys())
    task_fragment_count = len(assignments)  # 每一条 assignment 视为一份
    single_task_loom_count = sum(1 for c in loom_tasks.values() if c == 1)
    # 每台已用织机在其最早/最晚任务之间(或窗口内)的空档分钟
    loom_interval: Dict[str, List[int]] = {}
    for a in assignments:
        loom_interval.setdefault(a["loom_id"], []).append((a["start_minute"], a["end_minute"]))
    total_idle_gap = 0.0
    for lo, ivs in loom_interval.items():
        ivs.sort()
        for c in range(len(ivs) - 1):
            total_idle_gap += max(0, ivs[c + 1][0] - ivs[c][1])

    # 每任务延误(取该任务所有份的最大完成时间)
    lateness_by_task: Dict[str, float] = {}
    for a in assignments:
        lateness_by_task[a["task_id"]] = max(lateness_by_task.get(a["task_id"], 0.0),
                                             a["lateness_minutes"])
    max_delay_task_id = max(lateness_by_task, key=lateness_by_task.get) if lateness_by_task else None

    for t in plan.tasks:
        kpi["required_quantity"] += float(t.required_quantity)
        sch = scheduled_by_task.get(t.task_id, 0.0)
        us = max(0.0, round(float(t.required_quantity) - sch, 4))
        t.scheduled_quantity = sch
        t.unscheduled_quantity = us
        unscheduled.append({
            "task_id": t.task_id,
            "required_quantity": float(t.required_quantity),
            "scheduled_quantity": sch,
            "unscheduled_quantity": us,
            "reason_codes": _unscheduled_reasons(plan, t, us),
        })
    kpi["unscheduled_quantity"] = sum(u["unscheduled_quantity"] for u in unscheduled)
    # 机台利用率 = 已排机器分钟 / 可用机器分钟(维修/停机/禁排/班次外已扣)
    usable_n = usable_looms_n(plan)
    gross, maint_min, downtime_min, avail_min = _machine_minutes(plan, usable_n)
    used_gross, used_maint, used_downtime, used_avail = _machine_minutes(
        plan, len(used_looms), loom_ids=used_looms
    ) if used_looms else (0, 0, 0, 0)
    kpi["scheduled_machine_minutes"] = round(total_assigned_minutes, 1)
    kpi["horizon_minutes"] = plan.horizon
    kpi["horizon_days"] = plan.horizon // 1440
    kpi["gross_machine_minutes"] = gross
    kpi["maintenance_minutes"] = maint_min
    kpi["downtime_minutes"] = downtime_min
    kpi["available_machine_minutes"] = avail_min
    kpi["utilization"] = round(total_assigned_minutes / avail_min, 4) if avail_min else 0.0
    kpi["fleet_utilization"] = kpi["utilization"]
    kpi["used_loom_gross_minutes"] = used_gross
    kpi["used_loom_maintenance_minutes"] = used_maint
    kpi["used_loom_downtime_minutes"] = used_downtime
    kpi["used_loom_available_minutes"] = used_avail
    kpi["used_loom_utilization"] = round(total_assigned_minutes / used_avail, 4) if used_avail else 0.0
    # 比率口径
    req = kpi["required_quantity"]
    kpi["demand_coverage_rate"] = round(kpi["scheduled_quantity"] / req, 4) if req else 0.0
    kpi["on_time_rate"] = round(kpi["on_time_quantity"] / kpi["scheduled_quantity"], 4) if kpi["scheduled_quantity"] else 0.0
    kpi["on_time_demand_rate"] = round(kpi["on_time_quantity"] / req, 4) if req else 0.0
    kpi["total_delay_minutes"] = round(kpi["total_lateness_minutes"], 1)
    kpi["max_delay_task_id"] = max_delay_task_id
    # 机器散布指标
    kpi["used_loom_count"] = len(used_looms)
    kpi["task_fragment_count"] = task_fragment_count
    kpi["single_task_loom_count"] = single_task_loom_count
    kpi["average_tasks_per_used_loom"] = round(task_fragment_count / len(used_looms), 3) if used_looms else 0.0
    kpi["total_idle_gap_minutes"] = round(total_idle_gap, 1)

    issues = _build_issues(plan, unscheduled)
    levels = _normalize_levels(layer_info or [])
    comparison_status = _comparison_status(levels)
    diagnostics_consistent = _objectives_consistent(levels)

    return {
        "status": status,
        "solver_status": status,
        "solve_time_s": round(time.time() - t0, 3),
        "schedule_start": prep.minute_to_iso(0, plan.ref),
        "schedule_end": prep.minute_to_iso(plan.horizon, plan.ref),
        "model_stats": model_stats or {},
        "assignments": assignments,
        "unscheduled": unscheduled,
        "objective_levels": levels,
        "comparison_status": comparison_status,
        "diagnostics_consistent": diagnostics_consistent,
        "kpi": kpi,
        "issues": issues,
    }


def _gap(best_value, best_bound):
    if best_value is None or best_bound is None:
        return None
    if best_value == 0:
        return 0.0 if best_bound == 0 else None
    return round((best_value - best_bound) / max(1, best_value), 6)


# 统一的目标层结果归一化：所有层(最小化/最大化)共用一套口径。
# 绝不根据状态改写原始值。只做方向/符号转换，并据原始证据计算归一化值。
def _normalize_levels(layer_info: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for li in layer_info:
        is_max = (li["raw_objective_direction"] == "maximize")
        raw_status = li["raw_status"]
        raw_val = li["raw_objective_value"]
        raw_bound = li["raw_best_bound"]
        nval = raw_val
        nbound = raw_bound
        gap = None
        consistent = True
        if raw_val is None:
            gap = None
        elif raw_bound is None:
            gap = None
        else:
            if is_max:
                # 最大化：界限 = 目标值的上界；valid 界应 >= 值
                if raw_bound < raw_val:
                    consistent = False
                    gap = None
                else:
                    gap = round((raw_bound - raw_val) / max(1.0, raw_val), 6)
            else:
                # 最小化：界限 = 目标值的下界；valid 界应 <= 值
                if raw_bound > raw_val:
                    consistent = False
                    gap = None
                else:
                    gap = round((raw_val - raw_bound) / max(1.0, raw_val), 6)
        # OPTIMAL 时归一化后的值必须等于界限；若不一致 → 证据不一致
        if raw_status == "OPTIMAL":
            if gap != 0.0:
                consistent = False
        out.append({
            "level": li["level"], "name": li["name"],
            "raw_status": raw_status, "raw_objective_value": raw_val,
            "raw_best_bound": raw_bound, "raw_wall_time_s": li.get("raw_wall_time_s"),
            "raw_objective_direction": li.get("raw_objective_direction"),
            "normalized_best_value": nval, "normalized_best_bound": nbound,
            "normalized_gap": gap, "consistent": consistent,
            "layer_status": raw_status, "objective_value": raw_val, "best_bound": nbound,
            "best_value": raw_val, "gap": gap, "status": raw_status,
            "solve_time_s": li.get("solve_time_s"), "time_limit_s": li.get("time_limit_s"),
            "proven_optimal": li.get("proven_optimal"), "fixed_to_next": li.get("fixed_to_next"),
        })
    return out


def _objectives_consistent(levels: List[Dict[str, Any]]) -> bool:
    return all(lv.get("consistent", True) for lv in levels)


def _comparison_status(levels: List[Dict[str, Any]]) -> str:
    """第一层若证明最优(OPTIMAL 或 bound==value)才允许视为可比，否则 INCONCLUSIVE。"""
    if not levels:
        return "INCONCLUSIVE"
    l1 = levels[0]
    if l1["status"] == "OPTIMAL":
        return "COMPARABLE"
    bv, bb = l1.get("best_value"), l1.get("best_bound")
    if bv is not None and bb is not None and abs(bv - bb) <= 1:
        return "COMPARABLE"
    return "INCONCLUSIVE"


def usable_looms_n(plan: _Planner) -> int:
    return sum(1 for l in plan.scenario.织机 if l.状态可用)


def _machine_minutes(plan: _Planner, usable_looms: int,
                     loom_ids: Optional[set[str]] = None) -> Tuple[int, int, int, int]:
    """返回 (gross, maintenance, downtime, available)。
       gross = 可用织机数 × 排程窗口；
       available = gross - maintenance - downtime(停机/锁定)。
       班次外(未提供班次)暂不扣。"""
    deduct = STAGE2_PARAMS["available_machine_deduct"]
    gross = usable_looms * plan.horizon
    maint_min = 0
    if deduct.get("maintenance", True):
        maint_min = sum(max(0, m.get("end_minute", 0) - m.get("start_minute", 0))
                        for m in plan.scenario.维护区间
                        if loom_ids is None or m.get("loom_id") in loom_ids)
    downtime_min = 0
    if deduct.get("stop", True):
        downtime_min = sum(max(0, t.locked_end_minute - t.locked_start_minute)
                           for t in plan.tasks
                           if t.locked and t.locked_end_minute is not None
                           and t.locked_start_minute is not None
                           and (loom_ids is None or t.locked_machine_id in loom_ids))
    available = max(1, gross - maint_min - downtime_min)
    return gross, maint_min, downtime_min, available


def _beam_id_for(plan: _Planner, beam_code):
    if not beam_code:
        return None
    for b in plan.scenario.虚拟经轴:
        if b.beam_code == beam_code:
            return b.beam_id
    return None


def _unscheduled_reasons(plan: _Planner, t, us: float) -> List[str]:
    reasons = []
    if us <= 0:
        return reasons
    if not plan.task_compatible.get(t.task_id):
        reasons.append("no_compatible_loom")
    reasons.append("capacity_material_or_priority")
    return reasons


def _build_issues(plan: _Planner, unscheduled) -> List[Dict[str, Any]]:
    issues = []
    for u in unscheduled:
        if u["unscheduled_quantity"] > 0:
            issues.append({
                "severity": "WARNING",
                "code": "unscheduled",
                "task_id": u["task_id"],
                "loom_id": None,
                "message": f"任务 {u['task_id']} 未排数量 {u['unscheduled_quantity']}（需求 {u['required_quantity']}）",
            })
    return issues


def _infeasible_result(plan, reason, objective, t0, model_stats=None, layer_info=None):
    res = {
        "status": "INFEASIBLE",
        "solver_status": "INFEASIBLE",
        "solve_time_s": round(time.time() - t0, 3),
        "schedule_start": prep.minute_to_iso(0, plan.ref),
        "schedule_end": prep.minute_to_iso(plan.horizon, plan.ref),
        "model_stats": model_stats or {},
        "assignments": [],
        "unscheduled": [{
            "task_id": t.task_id,
            "required_quantity": float(t.required_quantity),
            "scheduled_quantity": 0.0,
            "unscheduled_quantity": float(t.required_quantity),
            "reason_codes": ["infeasible"],
        } for t in plan.tasks],
        "objective_levels": [],
        "kpi": {},
        "issues": [{"severity": "ERROR", "code": "infeasible", "task_id": None, "loom_id": None,
                    "message": reason}],
        "diagnostics": {"demand_coverage_rate": 0.0, "available_loom_count": 0,
                        "candidate_loom_count": 0, "used_loom_count": 0, "unused_loom_count": 0,
                        "horizon_total_minutes": plan.horizon, "available_machine_minutes": 0,
                        "scheduled_machine_minutes": 0, "utilization_formula": "0 / -",
                        "utilization": 0.0, "unscheduled_reason_summary": [], "task_diagnostics": []},
    }
    res["business_status"], res["risk_reasons"] = diagnose.business_status(res, plan.conf)
    return res


def _validate_schedule(result: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    ok = True
    # 机台时间重叠
    by_loom: Dict[str, List[Tuple[int, int, str]]] = {}
    for a in result["assignments"]:
        by_loom.setdefault(a["loom_id"], []).append((a["start_minute"], a["end_minute"], a["task_id"]))
    for lo, ivs in by_loom.items():
        ivs.sort()
        for c, (s, e, tid) in enumerate(ivs[:-1]):
            if e > ivs[c + 1][0]:
                ok = False
                checks.append({"check": "loom_no_overlap", "pass": False, "loom_id": lo,
                               "message": f"机台 {lo} 任务 {tid} 与 {ivs[c+1][2]} 时间重叠"})
    # 经轴重叠
    by_beam: Dict[str, List[Tuple[int, int, str]]] = {}
    for a in result["assignments"]:
        if a["beam_id"]:
            by_beam.setdefault(a["beam_id"], []).append((a["start_minute"], a["end_minute"], a["task_id"]))
    for be, ivs in by_beam.items():
        ivs.sort()
        for c, (s, e, tid) in enumerate(ivs[:-1]):
            if e > ivs[c + 1][0]:
                ok = False
                checks.append({"check": "beam_no_overlap", "pass": False, "beam_id": be,
                               "message": f"经轴 {be} 任务 {tid} 与 {ivs[c+1][2]} 时间重叠"})
    # 工艺前后顺序：织造开始不得早于整经完成/经轴可用时间。
    for a in result["assignments"]:
        ready = int(a.get("beam_ready_minute") or 0)
        if a["start_minute"] < ready:
            ok = False
            checks.append({
                "check": "process_precedence", "pass": False, "task_id": a["task_id"],
                "message": f"任务 {a['task_id']} 在经轴可用前开始织造",
            })
    # 数量对账
    for u in result["unscheduled"]:
        if abs(u["required_quantity"] - u["scheduled_quantity"] - u["unscheduled_quantity"]) > 1e-6:
            ok = False
            checks.append({"check": "quantity_reconcile", "pass": False, "task_id": u["task_id"],
                           "message": f"任务 {u['task_id']} 数量对账失败"})
    if not checks and ok:
        checks.append({"check": "loom_no_overlap", "pass": True, "message": "无机台时间重叠"})
        checks.append({"check": "beam_no_overlap", "pass": True, "message": "无经轴时间重叠"})
        checks.append({"check": "process_precedence", "pass": True,
                       "message": "整经完成后上轴，之后才开始织造"})
        checks.append({"check": "quantity_reconcile", "pass": True, "message": "已排+未排=需求 对账通过"})
    return {"ok": ok, "checks": checks}
