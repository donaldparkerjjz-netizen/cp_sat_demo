# -*- coding: utf-8 -*-
"""
diagnose.py -- 整经织造排工排产 Demo · 结果诊断、指标核对与业务状态
===============================================================================
提供：
  * 标准未排原因编码（REASON_CODES）。
  * 每个任务的适配诊断与未排原因拆解（可统计）。
  * 场景级 diagnostics（覆盖率/机台/利用率/未排原因汇总）。
  * business_status（业务结果状态）与 solver_status（算法状态）区分。
  * KPI 公式审计与修正口径。
仅做“事后诊断”，不改动求解结果；结果中新增 diagnostics/business_status 字段。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from weaving_demo.model import (
    Product, Loom, WeavingScenario, ProductionTask,
)
from weaving_demo.config import BUSINESS_RULES, STAGE2_PARAMS
from weaving_demo import compat, prep

# 标准未排原因编码
REASON_CODES = [
    "NO_COMPATIBLE_LOOM", "TOOLING_MISMATCH", "NO_AVAILABLE_BEAM", "MATERIAL_SHORTAGE",
    "OUTSIDE_HORIZON", "LOCK_CONFLICT", "MIN_BATCH_NOT_MET", "CAPACITY_SHORTAGE",
    "INVALID_DUE_DATE", "MISSING_MASTER_DATA",
]


# ---------------------------------------------------------------------------
# 未排原因分类
# ---------------------------------------------------------------------------
def classify_unscheduled(task: ProductionTask, product: Optional[Product],
                         compat_diag: Dict[str, Any], budgets: Dict[str, float],
                         beams: List[Any], config: Dict[str, Any]) -> Tuple[str, List[str]]:
    """判断一个未排任务的(主原因, 次原因列表)。
       主因决定该未排数量归到哪个原因码(用于对账)；次因仅为说明，不重复计入。"""
    secondary: List[str] = []
    if product is None:
        return "MISSING_MASTER_DATA", secondary

    compat_count = compat_diag.get("compatible_loom_count") or \
        compat_diag.get("final_candidate_loom_count") or \
        len(compat_diag.get("final_candidate_loom_ids", [])) or \
        len(compat_diag.get("candidate_loom_ids", []))
    if compat_count == 0:
        if compat_diag.get("rejected_by_tooling_rule", 0) > 0:
            secondary.append("TOOLING_MISMATCH")
        return "NO_COMPATIBLE_LOOM", secondary

    # 有兼容织机但仍然未排：产品必须存在
    # 锁冲突
    if task.locked:
        return "LOCK_CONFLICT", secondary
    # 经轴不足/未到位
    if task.beam_code:
        ents = [b for b in beams if b.beam_code == task.beam_code]
        horizon = _horizon_hint(config)
        if not ents or all(
            b.status == "前道未完成" or b.earliest_available_minute >= horizon for b in ents
        ):
            return "NO_AVAILABLE_BEAM", secondary
    # 物料不足(已确认库存)：只有前道经轴可用后才继续判断物料。
    if product and product.使用纱线 and product.纱线单耗KG_M:
        avail = budgets.get(product.使用纱线)
        if avail is not None:
            need = task.required_quantity * product.纱线单耗KG_M
            if need > avail:
                if compat_diag.get("rejected_by_tooling_rule", 0) > 0:
                    secondary.append("TOOLING_MISMATCH")
                return "MATERIAL_SHORTAGE", secondary
    # 最小批量
    if task.split_allowed:
        mb = task.min_batch_qty or STAGE2_PARAMS["split_default"]["min_batch_qty"]
        if mb and task.required_quantity < mb:
            return "MIN_BATCH_NOT_MET", secondary
    # 排程窗口不足(交期在窗口前)
    if task.due_minute is not None and task.due_minute < 0:
        return "INVALID_DUE_DATE", secondary
    if task.due_minute is not None and task.due_minute > _horizon_hint(config):
        secondary.append("OUTSIDE_HORIZON")
    # 兜底：有兼容织机、物料/经轴均满足，但仍未排 -> 产能不足
    return "CAPACITY_SHORTAGE", secondary


def _horizon_hint(config: Dict[str, Any]) -> int:
    return int(config.get("stage2_params", {}).get("horizon_minutes") or 300000)


def task_diagnostics(scenario: WeavingScenario, task: ProductionTask, config: Dict[str, Any],
                     mode: Optional[str] = None) -> Dict[str, Any]:
    """输出单任务的适配/未排诊断。"""
    product = next((p for p in scenario.产品 if p.产品款号 == task.product_id), None)
    usable = [l for l in scenario.织机 if l.状态可用]
    diag = compat.diagnose_product_compat(product, usable, config, mode) if product else {
        "compatible_loom_count": 0, "final_candidate_loom_ids": [],
        "rejected_by_product_rule": 0, "rejected_by_tooling_rule": 0,
    }
    budgets = prep.material_budgets(scenario, config)
    usq = float(task.unscheduled_quantity or 0.0)
    primary, secondary = classify_unscheduled(task, product, diag, budgets, scenario.虚拟经轴, config) \
        if (task.scheduled_quantity or 0) < task.required_quantity - 1e-6 else ("", [])
    return {
        "task_id": task.task_id,
        "product_id": task.product_id,
        "required_quantity": float(task.required_quantity),
        "scheduled_quantity": float(task.scheduled_quantity or 0),
        "unscheduled_quantity": usq,
        "due_date": task.due_date,
        "due_minute": task.due_minute,
        "compatible_loom_count": diag.get("compatible_loom_count", len(diag.get("final_candidate_loom_ids", []))),
        "all_loom_count": len(usable),
        "rejected_by_product_rule": diag.get("rejected_by_product_rule", 0),
        "rejected_by_tooling_rule": diag.get("rejected_by_tooling_rule", 0),
        "rejected_by_calendar": diag.get("rejected_by_calendar", 0),
        "rejected_by_lock": diag.get("rejected_by_lock", 0),
        "rejected_by_beam": diag.get("rejected_by_beam", 0),
        "rejected_by_material": diag.get("rejected_by_material", 0),
        "rejected_by_horizon": diag.get("rejected_by_horizon", 0),
        "candidate_loom_ids": diag.get("final_candidate_loom_ids", []),
        "main_rejection_reason": diag.get("main_rejection_reason"),
        "primary_reason": primary,
        "secondary_reasons": secondary,
        "final_reason_codes": ([primary] + secondary) if primary else [],
    }


# ---------------------------------------------------------------------------
# 机器分钟
# ---------------------------------------------------------------------------
def available_machine_minutes(scenario: WeavingScenario, config: Dict[str, Any],
                              horizon: int) -> Tuple[int, int]:
    """计算可用机台总分钟 = 可用织机数 × 排程窗口，再扣除维修/锁定(停机/禁排)时间。
       返回 (used_factor, available)。"""
    usable = [l for l in scenario.织机 if l.状态可用]
    deduct = STAGE2_PARAMS["available_machine_deduct"]
    total = len(usable) * horizon
    for maint in scenario.维护区间:
        if deduct.get("maintenance", True):
            total -= max(0, maint.get("end_minute", 0) - maint.get("start_minute", 0))
    for t in scenario.生产任务:
        if t.locked and deduct.get("stop", True):
            if t.locked_end_minute is not None and t.locked_start_minute is not None:
                total -= max(0, t.locked_end_minute - t.locked_start_minute)
    return (usable, total)


def utilization_formula(scheduled_machine_minutes: float, available_machine_minutes: float) -> str:
    return f"{scheduled_machine_minutes:.0f} / {available_machine_minutes:.0f}"


# ---------------------------------------------------------------------------
# 场景 diagnostics
# ---------------------------------------------------------------------------
def compute_diagnostics(scenario: WeavingScenario, tasks: List[ProductionTask],
                        result: Dict[str, Any], config: Dict[str, Any],
                        horizon: int, mode: Optional[str] = None) -> Dict[str, Any]:
    kpi = result.get("kpi", {})
    req = kpi.get("required_quantity", 0.0) or 0.0
    sch = kpi.get("scheduled_quantity", 0.0) or 0.0
    coverage = (sch / req) if req else 0.0

    usable = [l for l in scenario.织机 if l.状态可用]
    used_looms = {a["loom_id"] for a in result.get("assignments", [])}
    # 候选机台 = 所有任务 allowed_loom_ids 的并集
    candidate = {m for t in tasks for m in (t.allowed_loom_ids or []) if m in {l.织机号 for l in usable}}

    _, avail = available_machine_minutes(scenario, config, horizon)
    # scheduled_machine_minutes 已在 kpi(由 _assemble 计算)
    sch_min = kpi.get("scheduled_machine_minutes", 0.0) or 0.0
    util = (sch_min / avail) if avail else 0.0

    task_diags = [task_diagnostics(scenario, t, config, mode) for t in tasks]
    # 未排原因汇总：按主因统计（数量与未排总量对账，不重复累计），次因单独列出
    summary_map: Dict[str, Dict[str, Any]] = {}
    secondary_map: Dict[str, Dict[str, Any]] = {}
    for td in task_diags:
        us = td["unscheduled_quantity"]
        if us <= 0:
            continue
        primary = td.get("primary_reason") or "UNKNOWN"
        s = summary_map.setdefault(primary, {"reason_code": primary, "task_count": 0, "quantity": 0.0})
        s["task_count"] += 1
        s["quantity"] += us
        for code in td.get("secondary_reasons", []):
            s2 = secondary_map.setdefault(code, {"reason_code": code, "task_count": 0, "quantity": 0.0})
            s2["task_count"] += 1
            s2["quantity"] += us
    reason_summary = sorted(summary_map.values(), key=lambda x: -x["quantity"])
    secondary_summary = sorted(secondary_map.values(), key=lambda x: -x["quantity"])
    # 对账：主因合计 == 未排总量
    sum_primary = sum(x["quantity"] for x in reason_summary)
    reconcile_ok = abs(sum_primary - kpi.get("unscheduled_quantity", 0.0)) <= 1.0

    diagnostics = {
        "demand_coverage_rate": round(coverage, 4),
        "available_loom_count": len(usable),
        "candidate_loom_count": len(candidate),
        "used_loom_count": len(used_looms),
        "unused_loom_count": len(usable) - len(used_looms),
        "horizon_total_minutes": horizon,
        "available_machine_minutes": avail,
        "scheduled_machine_minutes": round(sch_min, 1),
        "utilization_formula": utilization_formula(sch_min, avail),
        "utilization": round(util, 4),
        "task_count": len(tasks),
        "scheduled_task_count": sum(1 for td in task_diags if td["scheduled_quantity"] > 0),
        "fully_unscheduled_task_count": sum(1 for td in task_diags if td["scheduled_quantity"] == 0 and td["unscheduled_quantity"] > 0),
        "partially_unscheduled_task_count": sum(1 for td in task_diags if 0 < td["scheduled_quantity"] < td["required_quantity"]),
        "unscheduled_reason_summary": reason_summary,
        "unscheduled_secondary_summary": secondary_summary,
        "unscheduled_reason_quantity_reconcile": reconcile_ok,
        "task_diagnostics": task_diags,
        "compatibility_mode": mode or _compat_mode(config),
    }
    return diagnostics


def _compat_mode(config: Dict[str, Any]) -> str:
    return config.get("stage2_params", {}).get("compatibility_mode", "balanced")


# 未排原因的中文业务说明
REASON_TEXT = {
    "NO_COMPATIBLE_LOOM": "无兼容织机：产品在数据中无满足工艺/工装条件的织机",
    "TOOLING_MISMATCH": "工装不匹配：织机缺少产品所需钢筘/边撑/废边盘等",
    "NO_AVAILABLE_BEAM": "经轴不足：无可用实体经轴或经轴未到位",
    "MATERIAL_SHORTAGE": "物料不足：对应纱线已确认库存不足",
    "OUTSIDE_HORIZON": "排程周期不足：任务需时长超过排程窗口",
    "LOCK_CONFLICT": "锁定冲突：锁定任务与其他任务时间/机台冲突",
    "MIN_BATCH_NOT_MET": "最小批量不足：任务数量小于拆分最小批量",
    "CAPACITY_SHORTAGE": "产能不足：窗口内可用机台生产能力不足",
    "INVALID_DUE_DATE": "非法交期：任务交期无效",
    "MISSING_MASTER_DATA": "主数据缺失：产品/织机/物料等主数据不完整",
    "UNKNOWN": "其他",
}


def _enrich_result(result: Dict[str, Any], scenario: WeavingScenario, tasks: List[ProductionTask],
                   config: Dict[str, Any], mode: Optional[str], horizon: int) -> None:
    """为 unscheduled / task_diagnostics 补充业务化字段(中文说明、缺料、候选、换款/换轴/穿筘等)。"""
    req_map = {t.task_id: t for t in tasks}
    budgets = prep.material_budgets(scenario, config)
    # 当前安排(每个任务的主分配/换款等)
    assign_by_task: Dict[str, Dict[str, Any]] = {}
    for a in result.get("assignments", []):
        assign_by_task.setdefault(a["task_id"], a)

    def theory_capacity(td: Dict[str, Any]) -> float:
        return round(td.get("compatible_loom_count", 0) * max(1, horizon // 1440) * 400.0, 0)

    def missing_material(t: ProductionTask) -> Dict[str, Any]:
        prod = next((p for p in scenario.产品 if p.产品款号 == t.product_id), None)
        if not prod or not prod.使用纱线 or not prod.纱线单耗KG_M:
            return {"material_code": None, "missing_kg": None}
        avail = budgets.get(prod.使用纱线)
        if avail is None:
            return {"material_code": prod.使用纱线, "missing_kg": None}
        need = t.required_quantity * prod.纱线单耗KG_M
        return {"material_code": prod.使用纱线, "missing_kg": max(0.0, round(need - avail, 2))}

    enriched_td = []
    for t in tasks:
        td = task_diagnostics(scenario, t, config, mode)
        ta = assign_by_task.get(t.task_id)
        ct = (ta or {}).get("changeover_type", "")
        # 以任务实际候选(allowed_loom_ids)为准，避免与 build_tasks 不一致
        cand_ids = list(t.allowed_loom_ids or [])
        allc = td.get("all_loom_count", 0) or len([l for l in scenario.织机 if l.状态可用])
        td["candidate_loom_ids"] = cand_ids
        td["top10_candidate_looms"] = cand_ids[:10]
        td["candidate_loom_count"] = len(cand_ids)
        td["compatible_loom_count"] = len(cand_ids)
        td["current_loom_id"] = (ta or {}).get("loom_id")
        td["current_loom_reason"] = ("在候选清单内且满足适配" if ta and cand_ids else
                                     "以兼容织机被选中" if ta else "")
        td["excluded_loom_count"] = max(0, allc - len(cand_ids))
        td["exclusion_reason_categories"] = {
            "product_rule": td.get("rejected_by_product_rule", 0),
            "tooling_rule": td.get("rejected_by_tooling_rule", 0),
            "calendar": td.get("rejected_by_calendar", 0),
            "lock": td.get("rejected_by_lock", 0),
            "beam": td.get("rejected_by_beam", 0),
            "material": td.get("rejected_by_material", 0),
            "horizon": td.get("rejected_by_horizon", 0),
        }
        td["is_style_change"] = ct == "style_change"
        td["is_beam_change"] = ct == "beam_change"
        td["is_threading"] = ct == "threading"
        td["theoretical_capacity"] = theory_capacity(td)
        td["missing_material"] = missing_material(t)
        td["business_text"] = REASON_TEXT.get(td.get("primary_reason") or "", "")
        enriched_td.append(td)

    # 未排列表：用业务化主因/次因/说明替代内部 reason_codes
    for u in result.get("unscheduled", []):
        td = next((x for x in enriched_td if x["task_id"] == u["task_id"]), None)
        if td:
            u["primary_reason"] = td["primary_reason"]
            u["secondary_reasons"] = td["secondary_reasons"]
            u["business_text"] = td["business_text"] if u["unscheduled_quantity"] > 0 else ""
            u["candidate_loom_count"] = td["candidate_loom_count"]
            u["missing_material"] = td["missing_material"]
            u["theoretical_capacity"] = td["theoretical_capacity"]
            # 保留内部编码但放"技术信息"字段；业务展示用中文
            u["reason_codes"] = [td["primary_reason"]] + list(td["secondary_reasons"]) \
                if td["primary_reason"] else []
    result["task_diagnostics"] = enriched_td
    result["diagnostics"]["task_diagnostics"] = enriched_td


# ---------------------------------------------------------------------------
# 业务结果状态
# ---------------------------------------------------------------------------
def business_status(result: Dict[str, Any], config: Dict[str, Any]) -> Tuple[str, List[str]]:
    """区分算法状态与业务结果状态。"""
    reasons: List[str] = []
    if result.get("diagnostics_consistent") is False:
        return "NOT_EXECUTABLE", ["求解证据不一致：存在层在 OPTIMAL 状态下归一化后的值与界限不一致，禁止标记可发布"]
    if result.get("status") in ("INFEASIBLE", "MODEL_INVALID", "UNKNOWN"):
        return "NOT_EXECUTABLE", [f"算法状态 {result.get('status')}，无可行方案"]
    if not result.get("validation", {}).get("ok", True):
        return "NOT_EXECUTABLE", ["结果校验不通过（违反硬约束/对账失败）"]
    kpi = result.get("kpi", {})
    req = kpi.get("required_quantity", 0.0) or 0.0
    sch = kpi.get("scheduled_quantity", 0.0) or 0.0
    coverage = (sch / req) if req else 0.0
    if coverage >= 0.999:
        if _uses_temp_derived(result, config):
            return "PARTIAL", ["已全部排完，但使用了临时参数/推导交期"]
        return "READY", ["全部需求已排且无硬约束风险"]
    if coverage < 0.5:
        reasons.append(f"未排比例高(覆盖率 {coverage:.1%})")
        return "HIGH_RISK", reasons + _risk_detail(result, config)
    # 已排部分可执行，但存在未排/临时参数
    reasons.append(f"存在未排数量(覆盖率 {coverage:.1%})，已排部分可执行")
    return "PARTIAL", reasons + _risk_detail(result, config)


def _uses_temp_derived(result: Dict[str, Any], config: Dict[str, Any]) -> bool:
    return True  # 本 Demo 使用临时参数/推导交期，视为 PARTIAL 级


def _risk_detail(result: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
    out = []
    out.append("使用临时参数(上轴330/穿筘480/落布10分钟)")
    out.append("交期为推导值/月度预测")
    out.append("经轴为虚拟实体(WB-XX-001)")
    out.append("工装库存未建档")
    return out


# ---------------------------------------------------------------------------
# KPI 公式审计（供测试/报告）
# ---------------------------------------------------------------------------
def kpi_formulae() -> Dict[str, str]:
    return {
        "demand_coverage_rate": "scheduled_quantity / required_quantity",
        "on_time_rate": "on_time_quantity / scheduled_quantity",
        "on_time_demand_rate": "on_time_quantity / required_quantity",
        "utilization": "scheduled_machine_minutes / available_machine_minutes(扣维修/停机/禁排/班次外)",
        "total_delay": "Σ max(0, end - due)（若拆分，按任务最大完成时间）",
        "max_delay": "max(所有任务延误)，并返回对应 task_id",
        "unscheduled_reconcile": "required_quantity == scheduled_quantity + unscheduled_quantity",
    }
