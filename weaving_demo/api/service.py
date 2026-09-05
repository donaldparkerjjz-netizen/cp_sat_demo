# -*- coding: utf-8 -*-
"""weaving_demo/api/service.py -- 业务逻辑：装载场景、求解、诊断、摘要。"""
from __future__ import annotations

import copy
import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from weaving_demo import prep, compat
from weaving_demo.config import BUSINESS_RULES, STAGE2_PARAMS
from weaving_demo.extract import extract_scenario
from weaving_demo.load import load_json
from weaving_demo.model import ShopFloorSnapshot, WeavingScenario, VirtualBeam
from weaving_demo.solver import solve
from weaving_demo.weekly_warping import build_weekly_warping_plan, align_warping_plan_to_weaving
from weaving_demo.weekly_weaving import build_weekly_weaving_plan
from weaving_demo.simulation import SimulationConfig, run_schedule_simulation
from weaving_demo.final_schedule import finalize_schedule, build_final_process_gantt
from weaving_demo.shopfloor import (
    SHOPFLOOR_STORE,
    build_simulated_snapshot,
    final_snapshot_from_simulation,
    merge_snapshot,
    runtime_states_from_snapshot,
)
from weaving_demo.validate import validate_scenario
from weaving_demo.api.store import STORE
from weaving_demo import process as process_mod
from weaving_demo.data_imports import DATA_IMPORT_STORE

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"
DEFAULT_EXCEL = r"C:\Users\Administrator\OneDrive\Desktop\副本【作成中整经织造】益丰生产管理表单260604.xlsx"

VALID_MODES = ("strict", "balanced", "simulation")
VALID_HORIZON_DAYS = (7, 14, 30, 60)   # None = 完整周期


def preview_data_import(params: Dict[str, Any]) -> Dict[str, Any]:
    return DATA_IMPORT_STORE.preview(
        filename=str(params.get("filename") or ""),
        content_base64=str(params.get("content_base64") or ""),
        current_summary=scenario_summary(),
    )


def save_data_snapshot(params: Dict[str, Any]) -> Dict[str, Any]:
    return DATA_IMPORT_STORE.save_snapshot(
        preview_id=str(params.get("preview_id") or ""),
        note=str(params.get("note") or ""),
    )


def list_data_snapshots() -> Dict[str, Any]:
    return DATA_IMPORT_STORE.list_snapshots()


def load_scenario() -> WeavingScenario:
    """装载当前场景（优先样例 JSON，否则从 Excel 提取）。"""
    if (SAMPLES / "scenario.json").exists():
        try:
            sc = load_json(str(SAMPLES / "scenario.json"))
            if sc.产品:
                return sc
        except Exception:  # noqa: BLE001
            pass
    return extract_scenario(DEFAULT_EXCEL)


def scenario_summary() -> Dict[str, Any]:
    sc = load_scenario()
    sc.规则配置 = BUSINESS_RULES
    if not sc.生产任务:
        sc.生产任务 = prep.build_tasks(sc, BUSINESS_RULES)
    report = validate_scenario(sc)
    return {
        "scenario_id": sc.数据来源 or "current",
        "products": len(sc.产品),
        "looms": len(sc.织机),
        "available_looms": sum(1 for l in sc.织机 if l.状态可用),
        "tasks": len(sc.生产任务),
        "warps": len(sc.经轴),
        "materials": len(sc.物料),
        "due_dates": len(sc.交期),
        "data_warnings": report.get("warnings", []),
        "data_errors": report.get("errors", []),
        "data_info": report.get("info", []),
        "severity": report.get("severity"),
        "compatibility_mode": STAGE2_PARAMS["compatibility_mode"],
    }


def _snapshot_summary(snapshot) -> Dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "version": snapshot.version,
        "captured_at": snapshot.captured_at,
        "source": snapshot.source,
        "schedule_id": snapshot.schedule_id,
        "parent_snapshot_id": snapshot.parent_snapshot_id,
        "loom_count": len(snapshot.looms),
        "beam_count": len(snapshot.beams),
        "event_count": len(snapshot.events),
        "loom_with_beam_count": sum(1 for loom in snapshot.looms if loom.current_beam_id),
        "loom_with_remaining_beam_count": sum(1 for loom in snapshot.looms
                                               if loom.remaining_beam_m > 1e-6),
    }


def get_shopfloor_snapshot(snapshot_id: Optional[str] = None) -> Dict[str, Any]:
    """读取指定或最新快照；首次读取时建立可运行的模拟版本1。"""
    snapshot = SHOPFLOOR_STORE.get(snapshot_id) if snapshot_id else SHOPFLOOR_STORE.latest()
    if snapshot_id and snapshot is None:
        raise ValueError(f"未找到车间状态快照 {snapshot_id}")
    if snapshot is None:
        sc = load_scenario()
        seed = build_simulated_snapshot(sc)
        snapshot = merge_snapshot(seed, {
            "captured_at": seed.captured_at,
            "source": "simulated_seed",
            "metadata": {
                "initialized_by": "get_shopfloor_snapshot",
                "note": "真实现场数据接入前使用的确定性模拟期初快照",
            },
        }, scenario=sc)
        snapshot = SHOPFLOOR_STORE.save(snapshot, expected_version=0)
    return {"snapshot": snapshot.to_dict(), "summary": _snapshot_summary(snapshot)}


def save_shopfloor_snapshot(params: Dict[str, Any]) -> Dict[str, Any]:
    """把部分现场更新合并到最新快照，并以新版本原子保存。"""
    sc = load_scenario()
    latest = SHOPFLOOR_STORE.latest()
    base = latest or build_simulated_snapshot(sc)
    requested_base = params.get("base_version")
    if requested_base is not None and int(requested_base) != base.version:
        raise ValueError(
            f"车间状态版本冲突：当前版本为 {base.version}，提交基于 {requested_base}"
        )
    snapshot = merge_snapshot(base, params, scenario=sc)
    saved = SHOPFLOOR_STORE.save(snapshot, expected_version=base.version)
    return {"snapshot": saved.to_dict(), "summary": _snapshot_summary(saved)}


def prepare_solve(sc: WeavingScenario, params: Dict[str, Any]):
    """把 API 参数应用到场景/配置副本。返回 (scenario, config, kwargs)。"""
    mode = params.get("compatibility_mode", "balanced")
    if mode not in VALID_MODES:
        raise ValueError(f"invalid compatibility_mode: {mode}")
    horizon_days = params.get("horizon_days", 7)
    if horizon_days is not None and horizon_days not in VALID_HORIZON_DAYS:
        raise ValueError(f"invalid horizon_days: {horizon_days}")

    conf = json.loads(json.dumps(BUSINESS_RULES))  # 深拷贝，避免污染全局
    conf["stage2_params"]["compatibility_mode"] = mode
    conf["stage2_params"]["freeze_days"] = int(params.get("freeze_days", STAGE2_PARAMS["freeze_days"]))
    if horizon_days is not None:
        conf["stage2_params"]["horizon_minutes"] = int(horizon_days) * 1440

    kwargs = {
        "max_time_s": float(params.get("max_time_s", 30.0)),
        "compatibility_mode": mode,
        "material_enabled": bool(params.get("enable_material_constraint", True)),
        "beam_enabled": bool(params.get("enable_beam_constraint", True)),
        "objective": params.get("objective_mode", "lexicographic"),
        "recompute_allowed": True,
    }
    if params.get("schedule_start"):
        kwargs["schedule_start"] = params["schedule_start"]
    if horizon_days is not None:
        kwargs["horizon_days"] = horizon_days
    if horizon_days == 7:
        # 一周计划先最大化本周产量，再把已选任务尽早压紧，避免相同产量下出现任意空档。
        # 规则优化开启时，在不牺牲本周总产量的前提下优先减少换款/仕挂，
        # 最后再压紧日历。关闭时保留原来的两层求解行为用于诊断对比。
        if params.get("optimize_rules"):
            conf["stage2_params"]["objective_layers"] = [
                "unscheduled_quantity", "changeover_count", "schedule_compactness",
            ]
            kwargs["max_layers"] = 3
        else:
            conf["stage2_params"]["objective_layers"] = [
                "unscheduled_quantity", "schedule_compactness",
            ]
            kwargs["max_layers"] = 2
    return sc, conf, kwargs


def _attach_roll_plan(payload: Dict[str, Any], warping_dataset: Dict[str, Any]) -> Dict[str, Any]:
    """为每根已投用经轴生成4—5匹、单匹800—1000米的计划切分。

    匹计划按经轴主档全长生成；本周只织造了一部分时，用 scheduled_meters 标识
    已落布/在制部分，未完成的匹留作跨周期执行计划，不虚增本周产量。
    """
    beams = warping_dataset.get("beams", {}) or {}
    final_schedule = payload.get("final_schedule", {}) or {}
    assignments = final_schedule.get("assignments", []) or []
    ledger_rows = (final_schedule.get("beam_ledger", {}) or {}).get("instances", []) or []
    ledger_by_id = {str(row.get("beam_instance_id") or ""): row for row in ledger_rows}
    plans: List[Dict[str, Any]] = []

    for assignment in assignments:
        beam_id = str(assignment.get("beam_id") or "")
        ledger = ledger_by_id.get(beam_id, {})
        beam_sku = str(ledger.get("warp_beam_sku") or "")
        observed_capacity = float(
            ledger.get("initial_meters")
            or (beams.get(beam_sku) or {}).get("set_length")
            or ledger.get("total_meters")
            or ledger.get("plan_meters")
            or assignment.get("scheduled_quantity")
            or 0.0
        )
        if observed_capacity <= 1e-6:
            continue
        master_capacity = float((beams.get(beam_sku) or {}).get("set_length") or 0.0)
        capacity = master_capacity or observed_capacity
        assumed_capacity = False
        if capacity < 3200 - 1e-6 or capacity > 5000 + 1e-6:
            # 期初台账有时只有余量而缺少原轴全长；余量不能直接当作落布规划基数。
            # 在真实主档补齐前使用系统统一模拟轴长，并在输出中明确标记推导来源。
            capacity = 3600.0
            assumed_capacity = True
        # 正常经轴按4或5匹切分；主档在3200—5000米时可保证单匹800—1000米。
        if capacity >= 4000:
            roll_count = 5
        else:
            roll_count = 4
        planned_per_roll = capacity / roll_count
        remaining_scheduled = float(assignment.get("scheduled_quantity") or 0.0)
        rolls = []
        for index in range(1, roll_count + 1):
            planned = planned_per_roll if index < roll_count else capacity - planned_per_roll * (roll_count - 1)
            scheduled = min(planned, max(0.0, remaining_scheduled))
            remaining_scheduled -= scheduled
            rolls.append({
                "roll_id": f"{beam_id}-ROLL-{index:02d}",
                "sequence": index,
                "planned_meters": round(planned, 3),
                "scheduled_meters": round(scheduled, 3),
                "status": "本周完成" if scheduled + 1e-6 >= planned else ("本周部分" if scheduled > 1e-6 else "后续待织"),
            })
        assignment["rolls"] = copy.deepcopy(rolls)
        plans.append({
            "beam_instance_id": beam_id,
            "warp_beam_sku": beam_sku or None,
            "product_id": assignment.get("product_id"),
            "loom_id": assignment.get("loom_id"),
            "beam_capacity_meters": round(capacity, 3),
            "observed_or_remaining_meters": round(observed_capacity, 3),
            "capacity_is_assumed": assumed_capacity,
            "capacity_source": "模拟标准轴长3600米" if assumed_capacity else ("经轴主档设定长度" if master_capacity else "逐轴台账总长"),
            "roll_count": roll_count,
            "rolls": rolls,
            "rule_ok": roll_count in (4, 5) and all(800 - 1e-6 <= row["planned_meters"] <= 1000 + 1e-6 for row in rolls),
        })

    payload["assignments"] = assignments
    final_schedule["assignments"] = assignments
    final_schedule["roll_plan"] = copy.deepcopy(plans)
    payload["roll_plan"] = plans
    return {
        "beam_count": len(plans),
        "roll_count": sum(row["roll_count"] for row in plans),
        "compliant_beam_count": sum(1 for row in plans if row["rule_ok"]),
    }


def _apply_shopfloor_snapshot(sc: WeavingScenario,
                              snapshot: ShopFloorSnapshot) -> Dict[str, Any]:
    """把阶段一快照转换为主求解可识别的机台期初状态和停机窗口。"""
    loom_map = {loom.织机号: loom for loom in sc.织机}
    existing_maintenance = {
        (row.get("loom_id"), int(row.get("start_minute") or 0), int(row.get("end_minute") or 0))
        for row in sc.维护区间
    }
    applied = 0
    unavailable = 0
    delayed = 0
    for state in snapshot.looms:
        loom = loom_map.get(state.loom_id)
        if loom is None:
            continue
        applied += 1
        loom.目前对应产品 = state.current_product_id
        if state.status == "unavailable":
            loom.当前状态 = "NULL"
            unavailable += 1
        else:
            loom.当前状态 = state.status
        if state.available_minute > 0 and state.status in (
            "fault", "maintenance", "material_shortage", "unavailable"
        ):
            key = (state.loom_id, 0, int(state.available_minute))
            if key not in existing_maintenance:
                sc.维护区间.append({
                    "loom_id": state.loom_id,
                    "start_minute": 0,
                    "end_minute": int(state.available_minute),
                    "reason": f"阶段一快照:{state.status}",
                    "source": snapshot.source,
                })
                existing_maintenance.add(key)
            delayed += 1
    return {
        "applied_loom_count": applied,
        "unavailable_loom_count": unavailable,
        "delayed_loom_count": delayed,
        "available_beam_meters": round(sum(
            beam.remaining_meters for beam in snapshot.beams
            if beam.status in ("on_loom", "available")
        ), 3),
        "application_note": "模拟/现场快照已进入主求解的机台期初状态、停机窗口和经轴可用时间。",
    }


def run_solve(params: Dict[str, Any]) -> Dict[str, Any]:
    sc = load_scenario()
    sc.规则配置 = BUSINESS_RULES
    snapshot = SHOPFLOOR_STORE.latest() or build_simulated_snapshot(sc)
    snapshot_application = _apply_shopfloor_snapshot(sc, snapshot)
    if not sc.生产任务:
        sc.生产任务 = prep.build_tasks(sc, BUSINESS_RULES)
    warping_dataset = _warping_dataset()
    target_mapping = _apply_source_target_looms(
        sc, sc.生产任务, warping_dataset,
        params.get("compatibility_mode", "balanced"),
    )
    horizon_days = params.get("horizon_days", 7)
    weekly_plan = None
    precedence_dataset = warping_dataset
    if horizon_days == 7:
        weekly_plan = build_weekly_warping_plan(
            warping_dataset, sc.生产任务,
            params.get("schedule_start") or (sc.设置.排程起点 if sc.设置 else "2026-04-01"),
            days=7,
        )
        precedence_dataset = {**warping_dataset, "tasks": weekly_plan["tasks"]}
    precedence = _apply_process_precedence(
        sc, sc.生产任务, precedence_dataset,
        schedule_start=params.get("schedule_start"),
        horizon_days=horizon_days,
        shopfloor_snapshot=snapshot,
    )
    sc, conf, kwargs = prepare_solve(sc, params)
    result = solve(sc, config=conf, **kwargs)
    schedule_id = f"sch-{int(time.time() * 1000)}"
    payload = {**result, "schedule_id": schedule_id, "created_at": time.time(),
               "params": params}
    payload["target_loom_audit"] = _build_target_loom_audit(payload, target_mapping)
    if payload.get("provenance"):
        payload["provenance"]["schedule_id"] = schedule_id
    if weekly_plan is not None:
        if params.get("optimize_rules", False):
            weekly_plan = align_warping_plan_to_weaving(
                weekly_plan, payload.get("assignments", []), sc.生产任务, warping_dataset
            )
        payload["warping_plan"] = weekly_plan
        payload["beam_ledger"] = _build_weekly_beam_ledger(
            payload, weekly_plan, warping_dataset, snapshot
        )
        payload["weaving_plan"] = build_weekly_weaving_plan(payload, weekly_plan, warping_dataset)
        # 每次求解立即执行同一份周整经计划与逐轴台账的可执行性展开，
        # 使“订单→织造→经轴→整经→最终织造”成为主算法结果，而非仅在打开模拟页时临时计算。
        simulation_config = SimulationConfig(
            lead_time_minutes=120,
            edge_support_use_limit=5,
            warping_minutes_per_beam=int(weekly_plan.get("minutes_per_beam") or 240),
            threading_minutes=480,
            forecast_hours=(24, 48),
            compatibility_mode=params.get("compatibility_mode", "balanced"),
        )
        execution_preview = run_schedule_simulation(
            sc,
            runtime_states=runtime_states_from_snapshot(snapshot, payload.get("schedule_start")),
            config=simulation_config,
            solve_result=payload,
        )
        solver_copy = execution_preview.pop("solver", {})
        config_payload = {
            "lead_time_minutes": simulation_config.lead_time_minutes,
            "edge_support_use_limit": simulation_config.edge_support_use_limit,
            "warping_minutes_per_beam": simulation_config.warping_minutes_per_beam,
            "threading_minutes": simulation_config.threading_minutes,
            "forecast_hours": list(simulation_config.forecast_hours),
            "compatibility_mode": simulation_config.compatibility_mode,
        }
        snapshot_summary = {**_snapshot_summary(snapshot), **snapshot_application}
        execution_preview["solver_summary"] = {
            "schedule_id": schedule_id,
            "status": solver_copy.get("status") or payload.get("status"),
            "scheduled_quantity": payload.get("kpi", {}).get("scheduled_quantity"),
            "target_loom_audit": copy.deepcopy(payload.get("target_loom_audit", {})),
        }
        execution_preview["simulation_config"] = config_payload
        execution_preview["shopfloor_snapshot"] = {
            "input": copy.deepcopy(snapshot_summary),
            "committed": False,
            "note": "求解时使用的现场快照已随最终计划固化；刷新页面不会改用其他快照重算。",
        }
        execution_preview["result_scope"] = "final_executable"
        payload["execution_preview"] = execution_preview
        finalize_schedule(sc, payload, execution_preview, snapshot_summary, config_payload)
        roll_summary = _attach_roll_plan(payload, warping_dataset)
        alignment = copy.deepcopy(payload.get("warping_plan", {}).get("alignment", {}) or {})
        payload["rule_optimization"] = {
            "enabled": bool(params.get("optimize_rules", False)),
            "mode": "hard_constraints_plus_lexicographic_objectives",
            "hard_rules": ["R01", "R06", "R11", "R12", "R15", "R19"],
            "optimization_rules": ["R02", "R07", "R08", "R09", "R14"],
            "generated_rules": ["R13", "R20"],
            "objective_layers": [row.get("name") for row in payload.get("objective_levels", [])],
            "warping_alignment": alignment,
            "roll_plan": roll_summary,
            "remaining_manual_rules": ["R04", "R10", "R16", "R17", "R21", "R22", "R23", "R24"],
            "note": (
                "点击运行排程已执行规则优化：硬规则作为可执行校验，产量/换款/紧凑度按字典序优化，"
                "整经由已选织造反推，并生成匹级落布计划。无法由现有数据证明的规则仍保留为待确认。"
            ),
        }
        payload["final_schedule"]["rule_optimization"] = copy.deepcopy(payload["rule_optimization"])
        # 最终逐轴段是各业务接口的唯一数量口径；初排只留在 initial_plan 中作为诊断证据。
        payload["target_loom_audit"] = _build_target_loom_audit(payload, target_mapping)
        payload["weaving_plan"] = build_weekly_weaving_plan(
            payload, payload["warping_plan"], warping_dataset
        )
        payload["weaving_plan"]["result_scope"] = "final_executable"
        payload["weaving_plan"]["note"] = (
            "由后端保存的最终逐轴织造段生成；任务池、资源页、甘特图和工况模拟共用此口径。"
        )
        payload["final_schedule"]["target_loom_audit"] = copy.deepcopy(payload["target_loom_audit"])
        payload["final_schedule"]["weaving_plan"] = copy.deepcopy(payload["weaving_plan"])
        if not payload.get("validation", {}).get("ok"):
            payload["business_status"] = "NOT_EXECUTABLE"
            payload.setdefault("risk_reasons", []).append("最终逐轴执行校验未通过")
    payload["process_precedence"] = precedence
    payload["input_shopfloor_snapshot"] = {
        **_snapshot_summary(snapshot),
        **snapshot_application,
    }
    STORE.save(schedule_id, payload)
    return payload


def _normalize_source_loom_id(value: Any, available_ids: set[str]) -> Optional[str]:
    """把来源表 LOOM-502 / 502 / #502 统一为织机主档中的 #502。"""
    raw = str(value or "").strip().upper()
    if not raw:
        return None
    number = raw.removeprefix("LOOM-").removeprefix("#").strip()
    candidates = (f"#{number}", f"LOOM-{number}", number)
    return next((candidate for candidate in candidates if candidate in available_ids), None)


def _apply_source_target_looms(sc: WeavingScenario, tasks, dataset: Dict[str, Any],
                               mode: str) -> Dict[str, Any]:
    """将工艺串联表中的目标织机写入求解任务。

    strict/balanced 中，有明确目标时实施硬约束；strict 中缺失/无效映射直接禁排。
    balanced 中缺失映射允许试排，但结果会标记为不可发布。
    simulation 保留宽松试排能力，仅记录来源目标供对比。
    """
    available_ids = {loom.织机号 for loom in sc.织机}
    rows = dataset.get("reconciliation", {}).get("product_rows", [])
    row_by_product = {row.get("product_id"): row for row in rows}
    summary = {"mode": mode, "products": {}, "mapped_task_count": 0,
               "missing_task_count": 0, "invalid_task_count": 0}

    for task in tasks:
        raw_targets = list((row_by_product.get(task.product_id) or {}).get("target_loom_ids") or [])
        normalized = []
        invalid = []
        for raw in raw_targets:
            loom_id = _normalize_source_loom_id(raw, available_ids)
            if loom_id and loom_id not in normalized:
                normalized.append(loom_id)
            elif not loom_id:
                invalid.append(str(raw))

        task.source_target_loom_ids = normalized
        if normalized:
            status = "mapped"
            summary["mapped_task_count"] += 1
        elif raw_targets:
            status = "invalid_blocked" if mode in ("strict", "balanced") else "invalid_trial"
            summary["invalid_task_count"] += 1
        else:
            status = "missing_blocked" if mode == "strict" else "missing_trial"
            summary["missing_task_count"] += 1
        task.target_mapping_status = status
        summary["products"][task.product_id] = {
            "raw_target_loom_ids": raw_targets,
            "source_target_loom_ids": normalized,
            "invalid_target_loom_ids": invalid,
            "status": status,
        }
    return summary


def _build_target_loom_audit(payload: Dict[str, Any], mapping: Dict[str, Any]) -> Dict[str, Any]:
    assignments = payload.get("assignments", [])
    outside = []
    missing = []
    matched = 0
    for assignment in assignments:
        targets = assignment.get("source_target_loom_ids") or []
        if targets:
            if assignment.get("loom_id") in targets:
                matched += 1
            else:
                outside.append({
                    "task_id": assignment.get("task_id"),
                    "product_id": assignment.get("product_id"),
                    "assigned_loom_id": assignment.get("loom_id"),
                    "source_target_loom_ids": targets,
                })
        else:
            missing.append({
                "task_id": assignment.get("task_id"),
                "product_id": assignment.get("product_id"),
                "assigned_loom_id": assignment.get("loom_id"),
                "mapping_status": assignment.get("target_mapping_status"),
            })
    return {
        **mapping,
        "assignment_count": len(assignments),
        "matched_assignment_count": matched,
        "outside_target_count": len(outside),
        "missing_target_assignment_count": len(missing),
        "outside_target_assignments": outside,
        "missing_target_assignments": missing,
        "publishable": not outside and not missing,
    }


def _build_weekly_beam_ledger(payload: Dict[str, Any], weekly_plan: Dict[str, Any],
                              dataset: Dict[str, Any],
                              shopfloor_snapshot: Optional[ShopFloorSnapshot] = None) -> Dict[str, Any]:
    """把一周整经任务展开为逐轴台账，并将织造数量分配到具体经轴。

    源表当前无真实轴号，因此生成的编号会明确标记 is_derived；
    即使数量对账通过，也不会被误判为可直接发布的实体经轴。
    """
    start = prep.parse_iso(payload.get("schedule_start")) or dt.datetime(2026, 4, 1)
    rows = dataset.get("reconciliation", {}).get("product_rows", [])
    beam_by_product = {row.get("product_id"): row.get("warp_beam_sku") for row in rows}
    instances: List[Dict[str, Any]] = []

    def loom_key(value: Any) -> str:
        """统一 #501、LOOM-501、501 三种来源编码后再核对目标织机。"""
        raw = str(value or "").strip().upper()
        return raw.removeprefix("LOOM-").removeprefix("#").strip()

    # 阶段一期初快照中的机上余轴和线边备轴优先进入台账，按所在机台限制使用。
    if shopfloor_snapshot is not None:
        for beam in shopfloor_snapshot.beams:
            if beam.remaining_meters <= 1e-6 or beam.status not in ("on_loom", "available"):
                continue
            code = beam_by_product.get(beam.product_id) or beam.beam_code
            targets = [beam.location_id] if beam.location_id and beam.location_type in ("loom", "line_side") else []
            instances.append({
                "beam_instance_id": beam.beam_id,
                "warp_beam_sku": code,
                "total_meters": round(float(beam.total_meters or beam.remaining_meters), 3),
                "remaining_meters": round(float(beam.remaining_meters), 3),
                "available_minute": 0,
                "available_at": prep.minute_to_iso(0, start),
                "source_task_id": None,
                "target_loom_ids": targets,
                "status": "机上余轴" if beam.location_type == "loom" else "线边可用",
                "is_derived": beam.is_derived,
                "data_source": "阶段一模拟车间快照",
                "allocations": [],
            })

    # 将确认的期初库存按设定长度拆成经轴；当前源数据通常为空。
    for code, rec in dataset.get("beams", {}).items():
        stock = float(rec.get("initial_inventory") or 0.0)
        beam_length = float(rec.get("set_length") or 3600.0)
        index = 0
        while stock > 1e-6:
            index += 1
            meters = min(stock, beam_length)
            instances.append({
                "beam_instance_id": f"STOCK-{code}-{index:03d}",
                "warp_beam_sku": code,
                "total_meters": round(meters, 3),
                "remaining_meters": round(meters, 3),
                "available_minute": 0,
                "available_at": prep.minute_to_iso(0, start),
                "source_task_id": None,
                "target_loom_ids": dataset.get("beam_to_looms", {}).get(code, []),
                "status": "期初库存",
                "is_derived": True,
                "data_source": "来源表库存数量按设定长度拆轴（待补真实轴号）",
                "allocations": [],
            })
            stock -= meters

    for index, warp_task in enumerate(weekly_plan.get("tasks", []), start=1):
        code = warp_task.get("warp_beam_sku")
        available_at = warp_task.get("complete_at") or warp_task.get("end")
        available_dt = prep.parse_iso(available_at)
        available_minute = max(0, int((available_dt - start).total_seconds() // 60)) if available_dt else 0
        instance_id = f"BEAM-{code}-{index:03d}"
        warp_task["beam_instance_id"] = instance_id
        meters = float(warp_task.get("plan_meters") or 0.0)
        instances.append({
            "beam_instance_id": instance_id,
            "warp_beam_sku": code,
            "total_meters": round(meters, 3),
            "remaining_meters": round(meters, 3),
            "available_minute": available_minute,
            "available_at": available_at,
            "source_task_id": warp_task.get("task_id"),
            "target_loom_ids": list(warp_task.get("target_loom_id") or []),
            "status": "整经完成待上轴",
            "is_derived": True,
            "data_source": "一周整经任务推导（待补真实轴号）",
            "allocations": [],
        })

    shortages: List[Dict[str, Any]] = []
    by_code: Dict[str, List[Dict[str, Any]]] = {}
    for instance in instances:
        by_code.setdefault(instance["warp_beam_sku"], []).append(instance)
    for pool in by_code.values():
        pool.sort(key=lambda item: (item["available_minute"], item["beam_instance_id"]))

    for assignment in sorted(payload.get("assignments", []), key=lambda a: (a.get("start_minute", 0), a.get("task_id", ""))):
        code = beam_by_product.get(assignment.get("product_id"))
        need = float(assignment.get("scheduled_quantity") or 0.0)
        allocations = []
        for instance in by_code.get(code, []):
            if need <= 1e-6:
                break
            if instance["available_minute"] > int(assignment.get("start_minute") or 0):
                continue
            targets = instance.get("target_loom_ids") or []
            # 周整经产生的待上轴经轴尚未物理绑定，目标织机只作建议；
            # 期初机上轴/线边轴仍按真实所在机台锁定。
            if (not instance.get("source_task_id") and targets
                    and loom_key(assignment.get("loom_id")) not in {loom_key(x) for x in targets}):
                continue
            take = min(need, float(instance["remaining_meters"]))
            if take <= 1e-6:
                continue
            alloc = {
                "beam_instance_id": instance["beam_instance_id"],
                "allocated_meters": round(take, 3),
                "beam_total_meters": instance["total_meters"],
                "beam_available_at": instance["available_at"],
                "is_derived": instance["is_derived"],
            }
            allocations.append(alloc)
            instance["allocations"].append({
                "task_id": assignment.get("task_id"),
                "loom_id": assignment.get("loom_id"),
                "allocated_meters": round(take, 3),
            })
            instance["remaining_meters"] = round(float(instance["remaining_meters"]) - take, 3)
            instance["status"] = "已分配" if instance["remaining_meters"] <= 1e-6 else "部分分配"
            need -= take
        assignment["beam_allocations"] = allocations
        assignment["beam_quantity_ok"] = need <= 1e-6
        assignment["beam_ledger_status"] = "逐轴对账通过" if need <= 1e-6 else "可用经轴不足"
        if allocations:
            assignment["beam_id"] = allocations[0]["beam_instance_id"]
        if need > 1e-6:
            shortages.append({
                "task_id": assignment.get("task_id"),
                "product_id": assignment.get("product_id"),
                "loom_id": assignment.get("loom_id"),
                "warp_beam_sku": code,
                "shortage_meters": round(need, 3),
                "reason": "织造开始前已完成的实体经轴米数不足",
            })

    allocated = sum(float(a["allocated_meters"]) for i in instances for a in i["allocations"])
    all_derived = bool(instances) and all(i["is_derived"] for i in instances)
    return {
        "instances": instances,
        "instance_count": len(instances),
        "real_instance_count": sum(1 for i in instances if not i["is_derived"]),
        "derived_instance_count": sum(1 for i in instances if i["is_derived"]),
        "total_meters": round(sum(float(i["total_meters"]) for i in instances), 3),
        "allocated_meters": round(allocated, 3),
        "remaining_meters": round(sum(float(i["remaining_meters"]) for i in instances), 3),
        "shortage_count": len(shortages),
        "shortages": shortages,
        "quantity_ok": not shortages,
        "all_instance_ids_derived": all_derived,
        "publishable": not shortages and not all_derived,
        "note": "已按轴校验可用时间和剩余米数；当前轴号为推导编号，需补录现场真实轴号后才可发布。",
    }


def run_diagnostic_compare(params: Dict[str, Any]) -> Dict[str, Any]:
    """A/B/C/D 对照诊断。仅供诊断，不可作为正式排程发布。"""
    sc = load_scenario()
    sc.规则配置 = BUSINESS_RULES
    if not sc.生产任务:
        sc.生产任务 = prep.build_tasks(sc, BUSINESS_RULES)
    _apply_process_precedence(sc, sc.生产任务)
    max_time = float(params.get("max_time_s", 20.0))
    mode = params.get("compatibility_mode", "balanced")
    schemes = [
        ("A_all_constraints", dict(material_enabled=True, beam_enabled=True)),
        ("B_no_material", dict(material_enabled=False, beam_enabled=True)),
        ("C_no_beam", dict(material_enabled=True, beam_enabled=False)),
        ("D_no_material_no_beam", dict(material_enabled=False, beam_enabled=False)),
    ]
    results = []
    for name, opts in schemes:
        # 每次用全新场景，避免快照污染
        sc2 = load_scenario(); sc2.规则配置 = BUSINESS_RULES
        sc2.生产任务 = prep.build_tasks(sc2, BUSINESS_RULES)
        _apply_process_precedence(sc2, sc2.生产任务)
        res = solve(sc2, config=BUSINESS_RULES, max_layers=1, compatibility_mode=mode,
                    max_time_s=max_time, **opts)
        l1 = res["objective_levels"][0] if res["objective_levels"] else {}
        required = res["kpi"].get("required_quantity", 0.0) or 0.0
        l1_best = l1.get("best_value")
        comparable = res["status"] == "OPTIMAL" and _bound_consistent(l1)
        l1_sched = (required - l1_best) if l1_best is not None else res["kpi"].get("scheduled_quantity")
        results.append({
            "scheme": name,
            "enabled_constraints": {"material": opts["material_enabled"],
                                    "beam": opts["beam_enabled"]},
            "scheduled_quantity": round(l1_sched, 1),
            "unscheduled_quantity": l1_best,
            "demand_coverage_rate": round(l1_sched / required, 4) if required else 0.0,
            "used_loom_count": res["kpi"].get("used_loom_count"),
            "utilization": res["kpi"].get("utilization"),
            "solver_status": res["status"],
            "best_value": l1.get("best_value"),
            "best_bound": l1.get("best_bound"),
            "gap": l1.get("gap"),
            "comparison_status": "COMPARABLE" if comparable else "INCONCLUSIVE",
        })
    all_comp = all(r["comparison_status"] == "COMPARABLE" for r in results)
    return {
        "diagnostic_only": True,
        "note": "仅供诊断，不可作为正式排程发布。",
        "all_comparable": all_comp,
        "conclusion": ("在证明最优下，物料约束是瓶颈之一。" if all_comp else
                       "当前求解时间内无法得出可靠对比。" ),
        "schemes": results,
    }


def _bound_consistent(l1: dict) -> bool:
    bv, bb = l1.get("best_value"), l1.get("best_bound")
    if bv is None or bb is None:
        return False
    return abs(bv - bb) <= 1


def _apply_process_precedence(sc: WeavingScenario, tasks, dataset=None,
                              schedule_start: Optional[str] = None,
                              horizon_days: Optional[int] = None,
                              shopfloor_snapshot: Optional[ShopFloorSnapshot] = None) -> Dict[str, Any]:
    """把 产品→经轴→整经完成日 写入 CP-SAT 输入。

    无初始库存时，经轴在整经计划日结束后的次日才可上轴织造；缺少经轴映射或整经计划时，
    经轴在本排程窗口内不可用。关闭经轴约束时仍可作为诊断方案试排。
    """
    if dataset is None:
        dataset = _warping_dataset()
    rows = dataset.get("reconciliation", {}).get("product_rows", [])
    row_by_product = {r.get("product_id"): r for r in rows}
    beams = dataset.get("beams", {})
    ref = prep.parse_iso(schedule_start) if schedule_start else None
    ref = ref or prep.schedule_ref(sc, BUSINESS_RULES)
    horizon = int(horizon_days) * 1440 if horizon_days is not None else prep.horizon_minutes(sc, BUSINESS_RULES)

    def minute_offset(value: str) -> int:
        parsed = prep.parse_iso(value)
        if parsed is None:
            return 0
        return max(0, int((parsed - ref).total_seconds() // 60))

    ready_by_beam: Dict[str, List[int]] = {}
    for warp_task in dataset.get("tasks", []):
        code = warp_task.get("warp_beam_sku")
        if not code:
            continue
        if warp_task.get("complete_at"):
            ready_by_beam.setdefault(code, []).append(
                minute_offset(warp_task["complete_at"])
            )
        elif warp_task.get("plan_date"):
            complete_day = dt.date.fromisoformat(str(warp_task["plan_date"])[:10]) + dt.timedelta(days=1)
            ready_by_beam.setdefault(code, []).append(
                minute_offset(complete_day.isoformat())
            )
    virtual_by_code: Dict[str, VirtualBeam] = {}
    blocked_products: List[str] = []
    snapshot_beams_by_product: Dict[str, List[Any]] = {}
    if shopfloor_snapshot is not None:
        for beam in shopfloor_snapshot.beams:
            if (beam.product_id and beam.remaining_meters > 1e-6
                    and beam.status in ("on_loom", "available")):
                snapshot_beams_by_product.setdefault(beam.product_id, []).append(beam)

    for task in tasks:
        row = row_by_product.get(task.product_id) or {}
        code = row.get("warp_beam_sku")
        if not code:
            code = f"UNMAPPED-{task.product_id}"
            blocked_products.append(task.product_id)
        task.beam_code = code
        if code in virtual_by_code:
            floor_beams = snapshot_beams_by_product.get(task.product_id, [])
            if floor_beams:
                available = sum(float(beam.remaining_meters) for beam in floor_beams)
                virtual_by_code[code].total_length = float(virtual_by_code[code].total_length or 0) + available
                virtual_by_code[code].remaining_length = float(virtual_by_code[code].remaining_length or 0) + available
                virtual_by_code[code].earliest_available_minute = 0
                virtual_by_code[code].earliest_available = prep.minute_to_iso(0, ref)
                virtual_by_code[code].status = "阶段一快照余轴可用"
            continue

        rec = beams.get(code, {})
        initial_inventory = float(rec.get("initial_inventory") or 0.0)
        ready_minutes = ready_by_beam.get(code, [])
        floor_beams = snapshot_beams_by_product.get(task.product_id, [])
        floor_available = sum(float(beam.remaining_meters) for beam in floor_beams)
        if floor_available > 0:
            ready_minute = 0
            ready_iso = prep.minute_to_iso(0, ref)
            status = "阶段一快照余轴可用"
        elif initial_inventory > 0:
            ready_minute = 0
            ready_iso = prep.minute_to_iso(0, ref)
            status = "库存可用"
        elif ready_minutes:
            # 首根经轴完成即可上轴；后续同品番经轴按整经计划连续补充。
            # 当前整经补轴速度显著快于单台织机消耗速度，首根库存可覆盖补轴间隔。
            ready_minute = min(ready_minutes)
            ready_iso = prep.minute_to_iso(ready_minute, ref)
            status = "首根整经完成后可用"
        else:
            ready_minute = horizon + 1
            ready_iso = prep.minute_to_iso(ready_minute, ref)
            status = "前道未完成"
            blocked_products.append(task.product_id)

        plan_meters = sum(float(t.get("plan_meters") or 0.0) for t in dataset.get("tasks", [])
                          if t.get("warp_beam_sku") == code)
        length = floor_available + float(initial_inventory or 0) + float(plan_meters or 0)
        if length <= 1e-6:
            length = rec.get("set_length")
        virtual_by_code[code] = VirtualBeam(
            beam_id=f"WB-{code}-001",
            beam_code=code,
            product_id=task.product_id,
            total_length=length,
            remaining_length=length,
            earliest_available_minute=ready_minute,
            earliest_available=ready_iso,
            status=status,
            current_loom_id=None,
            is_derived=True,
        )

    sc.虚拟经轴 = list(virtual_by_code.values())
    return {
        "beam_count": len(sc.虚拟经轴),
        "blocked_products": sorted(set(blocked_products)),
        "snapshot_product_count": len(snapshot_beams_by_product),
        "snapshot_available_meters": round(sum(
            beam.remaining_meters
            for beams in snapshot_beams_by_product.values() for beam in beams
        ), 3),
        "process_order": ["整经", "上轴", "织造", "水洗"],
    }


def _ensure_result(sc: WeavingScenario):
    """若尚无排程结果，运行一次默认求解以获取真实数据。"""
    r = STORE.latest()
    if r is None:
        r = run_solve({"compatibility_mode": "balanced", "max_time_s": 15, "horizon_days": 7,
                       "enable_material_constraint": True, "enable_beam_constraint": True,
                       "freeze_days": 3, "objective_mode": "lexicographic", "schedule_start": "2026-04-01"})
    return r


def process_overview() -> Dict[str, Any]:
    sc = load_scenario(); sc.规则配置 = BUSINESS_RULES
    if not sc.生产任务:
        sc.生产任务 = prep.build_tasks(sc, BUSINESS_RULES)
    r = _ensure_result(sc)
    return process_mod.process_overview(sc, r, _warping_process_summary())


def process_tasks() -> Dict[str, Any]:
    sc = load_scenario(); sc.规则配置 = BUSINESS_RULES
    r = _ensure_result(sc)
    return {"tasks": process_mod.assign_process_states(sc, r),
            "result_scope": r.get("result_scope", "initial")}


def homepage_progress() -> Dict[str, Any]:
    sc = load_scenario(); sc.规则配置 = BUSINESS_RULES
    r = _ensure_result(sc)
    return process_mod.homepage_progress(sc, r)


def process_cases() -> Dict[str, Any]:
    sc = load_scenario(); sc.规则配置 = BUSINESS_RULES
    r = _ensure_result(sc)
    return {"cases": process_mod.demonstration_cases(sc, r)}


def task_pool() -> Dict[str, Any]:
    """生产任务池：任务主档 + 排程结果(机台/起止/数量/延误) + 流程状态，供任务池页展示。"""
    sc = load_scenario(); sc.规则配置 = BUSINESS_RULES
    if not sc.生产任务:
        sc.生产任务 = prep.build_tasks(sc, BUSINESS_RULES)
    r = _ensure_result(sc)

    # 从结果里整理
    assign_by_task: Dict[str, List[Dict[str, Any]]] = {}
    for a in r.get("assignments", []):
        assign_by_task.setdefault(a.get("task_id"), []).append(a)
    unsched_by_task = {u.get("task_id"): u for u in r.get("unscheduled", [])}
    diag_by_task = {d.get("task_id"): d for d in r.get("diagnostics", {}).get("task_diagnostics", [])}
    proc_by_task = {t["task_id"]: t for t in process_mod.assign_process_states(sc, r)}
    try:
        chain_rows = _warping_dataset()["reconciliation"]["product_rows"]
    except Exception:  # 数据链异常不阻断任务池，产品映射保持待建档
        chain_rows = []
    chain_by_product = {x["product_id"]: x for x in chain_rows}

    rows = []
    for t in sc.生产任务:
        tid = t.task_id
        assigns = assign_by_task.get(tid, [])
        unsched = unsched_by_task.get(tid, {})
        diag = diag_by_task.get(tid, {})
        proc = proc_by_task.get(tid, {})
        chain = chain_by_product.get(t.product_id, {})
        scheduled = sum(a.get("scheduled_quantity", 0.0) for a in assigns)
        required = float(t.required_quantity)
        unscheduled = max(0.0, required - scheduled)
        # 状态
        if t.locked:
            status = "锁定"
        elif unscheduled <= 1e-6 and scheduled > 0:
            status = "已排程"
        elif scheduled > 0:
            status = "部分排程"
        else:
            status = "未排程"
        # 机台/时间
        looms = [a.get("loom_id") for a in assigns if a.get("loom_id")]
        first = assigns[0] if assigns else None
        rows.append({
            "task_id": tid,
            "product_id": t.product_id,
            "required_quantity": round(required, 3),
            "scheduled_quantity": round(scheduled, 3),
            "unscheduled_quantity": round(unscheduled, 3),
            "due_date": (t.due_date or "")[:10] if t.due_date else None,
            "priority": t.priority,
            "split_allowed": bool(t.split_allowed),
            "min_batch_qty": t.min_batch_qty,
            "max_parts": t.max_parts,
            "locked": bool(t.locked),
            "lock_reason": t.lock_reason,
            # beam_code 是求解模型内部字段，不等同于来源表经轴品番。
            "beam_code": t.beam_code,
            "flow_id": chain.get("flow_id") or f"FLOW-{t.product_id}",
            "product_back_sku": chain.get("product_back_sku"),
            "warp_beam_sku": chain.get("warp_beam_sku"),
            "weaving_sku": chain.get("weaving_sku"),
            "washing_sku": chain.get("washing_sku"),
            "beam_instance_id": first.get("beam_id") if first else None,
            "chain_status": chain.get("status") or "待建档",
            "chain_missing_fields": chain.get("missing_fields") or [
                "product_back_sku", "warp_beam_sku", "weaving_sku", "washing_sku"
            ],
            "chain_reason": chain.get("reason") or "未匹配到产品工艺链主档",
            "mapping_state": chain.get("mapping_state") or "待建档",
            "mapping_source": chain.get("mapping_source") or "①基础资料",
            "process": t.process,
            "reed": t.reed,
            "compatible_loom_count": diag.get("compatible_loom_count"),
            "allowed_loom_count": len(t.allowed_loom_ids or []),
            "assigned_looms": looms,
            "machine_id": first.get("loom_id") if first else None,
            "assign_start": first.get("start")[:10] if first and first.get("start") else None,
            "assign_end": first.get("end")[:10] if first and first.get("end") else None,
            "lateness_minutes": first.get("lateness_minutes", 0) if first else 0,
            "changeover_type": first.get("changeover_type") if first else None,
            "status": status,
            "current_process": proc.get("current_process") or "织造生产",
            "current_status": proc.get("current_status") or "",
            "blocked_reason": proc.get("blocked_reason") or "",
            "primary_reason": unsched.get("primary_reason") or diag.get("primary_reason") or "",
            "secondary_reasons": unsched.get("secondary_reasons") or diag.get("secondary_reasons") or [],
            "data_source": proc.get("data_source") or "来源表",
        })
    # 统计
    by_status: Dict[str, int] = {}
    chain_status_count: Dict[str, int] = {}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        chain_status_count[row["chain_status"]] = chain_status_count.get(row["chain_status"], 0) + 1
    return {
        "tasks": rows,
        "count": len(rows),
        "by_status": by_status,
        "chain_status_count": chain_status_count,
        "sum_required": round(sum(x["required_quantity"] for x in rows), 3),
        "sum_scheduled": round(sum(x["scheduled_quantity"] for x in rows), 3),
        "sum_unscheduled": round(sum(x["unscheduled_quantity"] for x in rows), 3),
        "result_scope": r.get("result_scope", "initial"),
        "urgent_window_days": 14,
        "due_urgent_count": sum(1 for x in rows if _is_urgent(x["due_date"], r)),
        "locked_count": sum(1 for x in rows if x["locked"]),
        "split_count": sum(1 for x in rows if x["split_allowed"]),
    }


def _is_urgent(due_date: str, result: Dict[str, Any]) -> bool:
    """14 天紧急窗口：交期在主档当前日期之后 14 天内(或无交期但未排)。"""
    if not due_date:
        return False
    try:
        import datetime as dt
        base = dt.date(2026, 4, 1)   # 排程起点(主档当前日期)
        due = dt.date.fromisoformat(due_date)
        return 0 <= (due - base).days <= 14
    except Exception:  # noqa: BLE001
        return False


def process_gantt() -> Dict[str, Any]:
    """返回与最终可执行计划同源的整经到水洗工艺甘特图。"""
    from weaving_demo.process_gantt import build_process_gantt, DEFAULT_EXCEL
    latest = STORE.latest() or {}
    weekly_plan = latest.get("warping_plan")
    data = build_process_gantt(
        DEFAULT_EXCEL,
        weaving_assigns=latest.get("assignments") or None,
        warping_plan=weekly_plan,
    )
    if latest.get("final_schedule"):
        data = build_final_process_gantt(data, latest["final_schedule"])
    data["generated_by"] = "weaving_demo/api/service.process_gantt"
    return data


def weekly_warping_plan() -> Dict[str, Any]:
    latest = STORE.latest() or {}
    if latest.get("warping_plan"):
        return latest["warping_plan"]
    sc = load_scenario(); sc.规则配置 = BUSINESS_RULES
    if not sc.生产任务:
        sc.生产任务 = prep.build_tasks(sc, BUSINESS_RULES)
    return build_weekly_warping_plan(_warping_dataset(), sc.生产任务, "2026-04-01", days=7)


def weekly_weaving_plan() -> Dict[str, Any]:
    """返回最近一次由整经计划驱动的织造周计划。"""
    latest = STORE.latest() or {}
    if not latest:
        latest = run_solve({"compatibility_mode": "balanced", "max_time_s": 15,
                            "horizon_days": 7, "enable_material_constraint": False,
                            "enable_beam_constraint": True, "freeze_days": 0,
                            "objective_mode": "lexicographic", "schedule_start": "2026-04-01"})
    if latest.get("weaving_plan"):
        return latest["weaving_plan"]
    warping_plan = latest.get("warping_plan") or weekly_warping_plan()
    return build_weekly_weaving_plan(latest, warping_plan, _warping_dataset())


def run_weekly_simulation(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把最近一次周排程展开为整经、穿综穿筘、织造准备和织造事件。"""
    params = params or {}
    schedule_id = params.get("schedule_id")
    result = STORE.get(schedule_id) if schedule_id else STORE.latest()
    if result is None:
        raise ValueError("暂无可模拟的排程结果，请先运行一周排程")
    if int(result.get("kpi", {}).get("horizon_days") or 0) != 7:
        raise ValueError("工况模拟当前仅支持一周 7 天排程")

    # 阶段A：页面查看和刷新只读取求解时已保存、已校验的执行结果，避免因现场最新
    # 快照变化而让同一个 schedule_id 出现另一份排程。旧数据仍走下方兼容重算路径。
    final_schedule = result.get("final_schedule") or {}
    if final_schedule and not bool(params.get("commit_final_state", False)):
        stored = copy.deepcopy(final_schedule.get("execution") or result.get("execution_preview") or {})
        stored["solver_summary"] = {
            **copy.deepcopy(stored.get("solver_summary", {}) or {}),
            "schedule_id": result.get("schedule_id"),
            "status": result.get("status"),
            "scheduled_quantity": result.get("kpi", {}).get("scheduled_quantity"),
            "target_loom_audit": copy.deepcopy(result.get("target_loom_audit", {})),
        }
        stored["simulation_config"] = copy.deepcopy(final_schedule.get("simulation_config", {}))
        stored["shopfloor_snapshot"] = {
            "input": copy.deepcopy(final_schedule.get("input_shopfloor_snapshot", {})),
            "committed": False,
            "note": "读取求解时固化的最终可执行计划；本次未重新求解、未推进现场状态。",
        }
        stored["result_scope"] = "final_executable"
        return stored

    sc = load_scenario()
    sc.规则配置 = BUSINESS_RULES
    if not sc.生产任务:
        sc.生产任务 = prep.build_tasks(sc, BUSINESS_RULES)
    requested_snapshot_id = params.get("snapshot_id")
    snapshot = (SHOPFLOOR_STORE.get(requested_snapshot_id)
                if requested_snapshot_id else SHOPFLOOR_STORE.latest())
    if requested_snapshot_id and snapshot is None:
        raise ValueError(f"未找到车间状态快照 {requested_snapshot_id}")
    if snapshot is None:
        snapshot = build_simulated_snapshot(sc)
    dataset = _warping_dataset()
    mode = result.get("params", {}).get("compatibility_mode", "balanced")
    _apply_source_target_looms(sc, sc.生产任务, dataset, mode)
    weekly_plan = result.get("warping_plan")
    precedence_dataset = ({**dataset, "tasks": weekly_plan.get("tasks", [])}
                          if weekly_plan else dataset)
    _apply_process_precedence(
        sc, sc.生产任务, precedence_dataset,
        schedule_start=result.get("schedule_start"), horizon_days=7,
        shopfloor_snapshot=snapshot,
    )

    cfg = SimulationConfig(
        lead_time_minutes=int(params.get("lead_time_minutes", 120)),
        edge_support_use_limit=int(params.get("edge_support_use_limit", 5)),
        warping_minutes_per_beam=int(params.get("warping_minutes_per_beam", 240)),
        threading_minutes=int(params.get("threading_minutes", 480)),
        forecast_hours=(24, 48),
        compatibility_mode=mode,
    )
    simulated = run_schedule_simulation(
        sc,
        runtime_states=runtime_states_from_snapshot(snapshot, result.get("schedule_start")),
        config=cfg,
        solve_result=result,
    )
    # API 仅返回模拟所需证据，避免再嵌套一份完整求解结果。
    solver_copy = simulated.pop("solver", {})
    simulated["solver_summary"] = {
        "schedule_id": result.get("schedule_id"),
        "status": solver_copy.get("status") or result.get("status"),
        "scheduled_quantity": result.get("kpi", {}).get("scheduled_quantity"),
        "target_loom_audit": result.get("target_loom_audit", {}),
    }
    simulated["simulation_config"] = {
        "lead_time_minutes": cfg.lead_time_minutes,
        "edge_support_use_limit": cfg.edge_support_use_limit,
        "warping_minutes_per_beam": cfg.warping_minutes_per_beam,
        "threading_minutes": cfg.threading_minutes,
    }
    commit_final_state = bool(params.get("commit_final_state", False))
    preview = final_snapshot_from_simulation(
        snapshot,
        simulated,
        source="simulation_final" if commit_final_state else "simulation_preview",
    )
    snapshot_info = {
        "input": _snapshot_summary(snapshot),
        "output_preview": _snapshot_summary(preview),
        "committed": False,
        "note": "模拟默认不推进现场状态；仅在 commit_final_state=true 时保存期末快照。",
    }
    if commit_final_state:
        if not simulated.get("validation", {}).get("ok"):
            raise ValueError("模拟校验未通过，不能提交期末车间状态")
        saved = SHOPFLOOR_STORE.save(preview, expected_version=snapshot.version)
        snapshot_info.update({
            "committed": True,
            "output": _snapshot_summary(saved),
            "note": "模拟期末状态已保存，下一轮默认从该快照开始。",
        })
    simulated["shopfloor_snapshot"] = snapshot_info
    return simulated


def loom_resources() -> Dict[str, Any]:
    """织机资源：能力(工装)/状态/当前产品/产能/排程占用，供织机资源页展示。"""
    sc = load_scenario(); sc.规则配置 = BUSINESS_RULES
    if not sc.生产任务:
        sc.生产任务 = prep.build_tasks(sc, BUSINESS_RULES)
    r = _ensure_result(sc)

    # 织造计划：当前生产品番 / 产能 / 状态 按织机
    cur_prod: Dict[str, str] = {}
    cap_by_loom: Dict[str, float] = {}
    status_by_loom: Dict[str, str] = {}
    for t in sc.织造任务:
        if not t.织机:
            continue
        if t.当前生产品番 and t.当前生产品番 not in ("#N/A", "0", ""):
            cur_prod.setdefault(t.织机, t.当前生产品番)
        if t.产能设定:
            cap_by_loom.setdefault(t.织机, t.产能设定)
        if t.织机当前状态:
            status_by_loom.setdefault(t.织机, t.织机当前状态)

    # 排程占用按织机
    assign_by_loom: Dict[str, List[Dict[str, Any]]] = {}
    for a in r.get("assignments", []):
        assign_by_loom.setdefault(a.get("loom_id"), []).append(a)
    used_looms = set(assign_by_loom.keys())

    rows = []
    for l in sc.织机:
        lid = l.织机号
        assigns = assign_by_loom.get(lid, [])
        used = lid in used_looms
        # 状态：优先 ①基础资料状态(主档)，织造计划状态补充
        status = l.当前状态 or status_by_loom.get(lid)
        if status in (None, "NULL", "0"):
            status = "待确认/不可用"
        # 当前产品：主档 目前对应产品 -> 织造计划 当前生产品番
        cur = l.目前对应产品 or cur_prod.get(lid)
        # 拥塞：该机被分配的任务数/总排程分钟
        total_min = sum(a.get("end_minute", 0) - a.get("start_minute", 0) for a in assigns)
        rows.append({
            "loom_id": lid,
            "region": l.区域,
            "status": status,
            "available": bool(l.状态可用),
            "current_product": cur,
            "capacity_m_per_day": l.产能设定 or cap_by_loom.get(lid),
            # 工装能力
            "waste_edge_disc": l.废边盘,
            "waste_edge_hole": l.废边盘安装孔位,
            "edge_cut": l.切边,
            "big_package": l.大卷装,
            "water_filter": l.水过滤,
            "yarn_frame": l.纱架,
            "reed": l.钢筘,
            "full_width_edge_support": l.全幅边撑,
            "wheels_gear": l.齿轮或铝轮,
            "heald": l.综丝,
            "compatible_products": l.可对应产品,
            "tooling_note": (_capability_text(l)),
            # 排程占用
            "used": used,
            "assigned_task_count": len(assigns),
            "scheduled_minutes": total_min,
            "assign_starts": sorted({a["start"][:10] for a in assigns if a.get("start")}),
            "assign_ends": sorted({a["end"][:10] for a in assigns if a.get("end")}),
            "products_scheduled": sorted({a.get("product_id") for a in assigns if a.get("product_id")}),
            "source_sheet": "②织机状态",
        })
    by_region: Dict[str, int] = {}
    for row in rows:
        by_region[row["region"] or "未标注"] = by_region.get(row["region"] or "未标注", 0) + 1
    return {
        "looms": rows,
        "count": len(rows),
        "available_count": sum(1 for x in rows if x["available"]),
        "unavailable_count": sum(1 for x in rows if not x["available"]),
        "used_count": len(used_looms),
        "idle_count": len(rows) - len(used_looms),
        "by_region": by_region,
        "by_status": _loom_status_count(rows),
        "result_scope": r.get("result_scope", "initial"),
        "capability_summary": {
            "waste_edge_disc": sum(1 for x in rows if x["waste_edge_disc"]),
            "edge_cut": sum(1 for x in rows if x["edge_cut"]),
            "big_package": sum(1 for x in rows if x["big_package"]),
            "water_filter": sum(1 for x in rows if x["water_filter"]),
            "yarn_frame": sum(1 for x in rows if x["yarn_frame"]),
        },
        "data_source": "来源表(②织机状态/织造计划) + 排程结果",
        "note": "织机主档 108 台；当前状态/能力取自 ②织机状态与织造计划；占用为最近一次排程结果。",
    }


def _capability_text(l) -> str:
    """织机能力简述：钢筘/边撑/废边盘/切边等。"""
    parts = []
    if l.钢筘:
        parts.append(f"钢筘 {l.钢筘}")
    if l.全幅边撑:
        parts.append(f"边撑 {l.全幅边撑}")
    if l.废边盘:
        parts.append("废边盘")
    if l.切边:
        parts.append("切边")
    if l.大卷装:
        parts.append("大卷装")
    if l.水过滤:
        parts.append("水过滤")
    if l.纱架:
        parts.append("纱架")
    return " / ".join(parts)


def _loom_status_count(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in rows:
        out[x["status"]] = out.get(x["status"], 0) + 1
    return out


def _warping_dataset():
    """从源 Excel 构建整经数据集(不落盘)。"""
    from weaving_demo.warping import build_warping_dataset, DEFAULT_EXCEL
    return build_warping_dataset(DEFAULT_EXCEL)


def _warping_process_summary() -> Dict[str, Any]:
    """为流程总览提供来源表整经任务与虚拟经轴的独立口径。"""
    try:
        ds = _warping_dataset()
    except Exception:  # 流程页仍可使用织造结果，整经状态显示为待补充
        return {}
    tasks = ds.get("tasks", [])
    instances = ds.get("instances", [])
    return {
        "warp_task_count": len(tasks),
        "warp_plan_meters": sum(float(t.get("plan_meters") or 0.0) for t in tasks),
        "virtual_beam_count": sum(1 for i in instances if i.get("is_derived")),
        "real_beam_count": sum(1 for i in instances if not i.get("is_derived")),
        "instance_meters": sum(float(i.get("instance_meters") or 0.0) for i in instances),
    }


def warping_beams() -> Dict[str, Any]:
    """经轴品番主档。"""
    ds = _warping_dataset()
    beams = []
    for b, rec in ds["beams"].items():
        beams.append({
            "warp_beam_sku": rec["warp_beam_sku"],
            "set_length": rec.get("set_length"),
            "warp_threads": rec.get("warp_threads"),
            "reed": rec.get("reed"),
            "yarn_code": rec.get("yarn_code"),
            "unit_consumption_kg": rec.get("unit_consumption_kg"),
            "initial_inventory": rec.get("initial_inventory"),
            "plan_dates": sorted(rec.get("warp_plan_m", {})),
            "target_loom_ids": ds["beam_to_looms"].get(b, []),
            "source_sheet": rec.get("source_sheet"),
            "data_source": rec.get("data_source", "来源表"),
        })
    return {"count": len(beams), "beams": beams}


def warping_instances() -> Dict[str, Any]:
    """实体/虚拟经轴实例。"""
    ds = _warping_dataset()
    instances = ds["instances"]
    return {
        "count": len(instances),
        "virtual_count": sum(1 for i in instances if i.get("is_derived")),
        "real_count": sum(1 for i in instances if not i.get("is_derived")),
        "instances": instances,
        "note": "源表无实体经轴编号，实例全部为虚拟(推导)数据。",
    }


def warping_inventory() -> Dict[str, Any]:
    """经轴库存推移：每日 整经完成量/织造上轴需求/结存米数/异常日期。"""
    ds = _warping_dataset()
    rows = []
    anomaly_dates = []
    for b, rec in ds["beams"].items():
        plan = rec.get("warp_plan_m", {})
        demand = rec.get("weave_demand_m", {})
        computed = rec.get("inventory_m", {})
        src_inv = rec.get("inventory_m", {})
        dates = sorted(set(plan) | set(demand))
        daily = []
        for d in dates:
            daily.append({
                "date": d,
                "warp_complete_m": plan.get(d, 0.0),
                "weave_mount_demand_m": demand.get(d, 0.0),
                "stock_m": computed.get(d, 0.0),
            })
        # 异常日期：结存为负
        for d in dates:
            if (computed.get(d) or 0.0) < -1e-6:
                anomaly_dates.append({"beam": b, "date": d, "stock_m": computed.get(d)})
        rows.append({
            "warp_beam_sku": b,
            "initial_inventory": rec.get("initial_inventory"),
            "daily": daily,
            "anomaly_dates": [x["date"] for x in anomaly_dates if x["beam"] == b],
        })
    return {"count": len(rows), "inventory": rows, "anomaly_dates": anomaly_dates}
