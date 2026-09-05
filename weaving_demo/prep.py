# -*- coding: utf-8 -*-
"""
prep.py -- 整经织造排工排产 Demo · 阶段2 求解前的数据准备
===============================================================================
将场景数据整理为 CP-SAT 需要的输入：
  * 时间：整数分钟（相对 schedule_start 的分钟偏移），并支持 ISO8601 互转。
  * 生产任务：优先用显式 scenario.生产任务，否则由产品推导（并计算兼容织机清单）。
  * 虚拟经轴：数据只有品番级经轴，为满足"实体经轴独占"，生成虚拟实体。
  * 变更准备时间：落布10 / 上轴330 / 穿综穿筘480 分钟，配置于 STAGE2_PARAMS。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from weaving_demo.model import (
    Product, Loom, WeavingScenario, ProductionTask, VirtualBeam, WarpBeam,
)
from weaving_demo.config import BUSINESS_RULES, STAGE2_PARAMS
from weaving_demo import compat


# ---------------------------------------------------------------------------
# 时间工具
# ---------------------------------------------------------------------------
def parse_iso(s: Optional[str]) -> Optional[dt.datetime]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def iso_to_minute(iso: Optional[str], ref: dt.datetime) -> int:
    """ISO 日期字符串 -> 相对 ref 的分钟偏移（不足按 0）。"""
    d = parse_iso(iso)
    if d is None:
        return 0
    days = (d.replace(hour=0, minute=0, second=0) - ref.replace(hour=0, minute=0, second=0)).days
    return max(0, days * 1440)


def minute_to_iso(minute: int, ref: dt.datetime) -> str:
    return (ref + dt.timedelta(minutes=int(minute))).strftime("%Y-%m-%dT%H:%M:%S")


def schedule_ref(scenario: WeavingScenario, config: Dict[str, Any]) -> dt.datetime:
    s = (scenario.设置.排程起点 if scenario.设置 else None) or \
        STAGE2_PARAMS["horizon_start"] or "2026-04-01"
    return parse_iso(s) or dt.datetime(2026, 4, 1, 0, 0, 0)


def horizon_minutes(scenario: WeavingScenario, config: Dict[str, Any]) -> int:
    ref = schedule_ref(scenario, config)
    end = (scenario.设置.排程终点 if scenario.设置 else None) or STAGE2_PARAMS["horizon_end"] or "2026-08-31"
    de = parse_iso(end) or dt.datetime(2026, 8, 31, 0, 0, 0)
    return max(1, (de - ref).days * 1440)


# ---------------------------------------------------------------------------
# 变更准备时间 / 换款判据
# ---------------------------------------------------------------------------
def changeover_type(task: ProductionTask, loom: Loom, config: Dict[str, Any]) -> str:
    """返回该任务在该织机上的变更类型：same / style_change / threading / beam_change。"""
    sm = STAGE2_PARAMS["setup_minutes"]
    threading = _threading_needed(task, loom, config)
    product_change = _product_changed(task, loom)
    if threading:
        return "threading"
    if product_change:
        return "style_change"
    if task.beam_code:
        return "beam_change"
    return "same"


def _product_changed(task: ProductionTask, loom: Loom) -> bool:
    if not loom.目前对应产品 or loom.目前对应产品 in ("0", "NULL"):
        return False
    return task.product_id != loom.目前对应产品


def _threading_needed(task: ProductionTask, loom: Loom, config: Dict[str, Any]) -> bool:
    sm = STAGE2_PARAMS["setup_minutes"]
    if _product_changed(task, loom):
        return True
    # 钢筘已知且不匹配 -> 需重穿综
    if task.reed and loom.钢筘 and task.reed not in loom.钢筘 and task.reed != loom.钢筘:
        return True
    return False


def setup_minutes(task: ProductionTask, loom: Loom, config: Dict[str, Any]) -> int:
    """任务在该织机上的准备时间(分钟)：落布 + 上轴 + (穿综穿筘)。
       每次织造都需上轴(330)；产品/工艺/钢筘变化需穿综穿筘(480)。"""
    sm = STAGE2_PARAMS["setup_minutes"]
    total = int(sm["drop_prep"]) + int(sm["mount"])
    if _threading_needed(task, loom, config):
        total += int(sm["threading"])
    return total


# ---------------------------------------------------------------------------
# 生产时长
# ---------------------------------------------------------------------------
def minutes_per_meter(product: Product, config: Dict[str, Any]) -> int:
    """每米生产所需分钟（按产品织造效率 米/天 折算；不足 1 分钟按 1 分钟）。"""
    eff = product.织造效率 or 400.0
    per_meter = 1440.0 / eff
    return max(1, int(round(per_meter)))


# ---------------------------------------------------------------------------
# 生产任务
# ---------------------------------------------------------------------------
def build_tasks(scenario: WeavingScenario, config: Dict[str, Any],
                mode: Optional[str] = None, recompute_allowed: bool = False) -> List[ProductionTask]:
    """生成/补全生产任务。显式任务优先；否则由产品推导(来源='derive')。
       recompute_allowed=True 时忽略已有 allowed_loom_ids，按 mode 重算(用于诊断)。"""
    mode = mode or (config.get("stage2_params", {}).get("compatibility_mode", "balanced")) or None
    product_map = {p.产品款号: p for p in scenario.产品}
    if scenario.生产任务:
        tasks = scenario.生产任务
        for t in tasks:
            if recompute_allowed or not t.allowed_loom_ids:
                prod = product_map.get(t.product_id)
                if prod:
                    computed, _ = compat.allowed_looms_for_product(prod, scenario.织机, config, mode)
                    # 业务表明确指定目标织机时，只允许“目标织机 ∩ 工装兼容织机”。
                    # 这里在求解前最后一次重算，避免 API 传入的来源约束被覆盖。
                    if t.source_target_loom_ids and mode != "simulation":
                        source_targets = set(t.source_target_loom_ids)
                        computed = [loom_id for loom_id in computed if loom_id in source_targets]
                    if t.target_mapping_status in ("missing_blocked", "invalid_blocked"):
                        computed = []
                    t.allowed_loom_ids = computed
        return tasks

    tasks: List[ProductionTask] = []
    product_map = {p.产品款号: p for p in scenario.产品}
    ref = schedule_ref(scenario, config)
    default_due_minute = (STAGE2_PARAMS.get("default_due_minutes")
                          or 60 * 1440)
    for p in scenario.产品:
        if not p.织造效率:
            continue
        allowed, _ = compat.allowed_looms_for_product(p, scenario.织机, config, mode)
        qty = (p.整经设定长度 or 3600) * 2  # 代表该产品约 2 卷的需求
        # 交期：优先匹配 交期(按月份) 的交期，否则用默认
        due_minute = default_due_minute
        body = find_due(scenario, p)
        if body:
            due_minute = iso_to_minute(body, ref)
        split = STAGE2_PARAMS["split_default"]
        tasks.append(ProductionTask(
            task_id=f"T-{p.产品款号}",
            product_id=p.产品款号,
            required_quantity=float(qty),
            due_minute=due_minute,
            due_date=minute_to_iso(due_minute, ref) if due_minute else None,
            priority=1.0,
            split_allowed=bool(split["enabled_default"]),
            min_batch_qty=float(split["min_batch_qty"]),
            max_parts=int(split["max_parts"]),
            process=None,
            reed=p.钢筘型号,
            beam_code=p.经轴款号 or p.产品款号,
            allowed_loom_ids=allowed,
            来源="derive",
        ))
    return tasks


def find_due(scenario: WeavingScenario, product: Product) -> Optional[str]:
    """在 交期 中为该产品找一个交期（按客户或产品名匹配），无则返回 None。"""
    for d in scenario.交期:
        if d.产品款号 and (product.产品款号 in d.产品款号 or (product.客户 and product.客户 in d.产品款号)):
            # 交期=该月月末
            if d.月份 and len(str(d.月份)) == 7:
                year, month = int(d.月份[:4]), int(d.月份[5:7])
                last = dt.date(year, month + 1, 1) - dt.timedelta(days=1) if month < 12 else dt.date(year, 12, 31)
                return last.isoformat()
    return None


# ---------------------------------------------------------------------------
# 虚拟经轴实体
# ---------------------------------------------------------------------------
def create_virtual_beams(scenario: WeavingScenario, tasks: List[ProductionTask],
                         config: Dict[str, Any]) -> List[VirtualBeam]:
    """为用到的经轴品番生成虚拟实体(唯一编号 WB-<品番>-NNN)。
       若 scenario.虚拟经轴 已存在则直接复用。"""
    if scenario.虚拟经轴:
        return scenario.虚拟经轴
    prefix = STAGE2_PARAMS["virtual_beam_prefix"]
    beam_codes: List[str] = []
    for t in tasks:
        if t.beam_code and t.beam_code not in beam_codes:
            beam_codes.append(t.beam_code)
    # 每个品番生成实体数：缺省 1 个（独占最严格）；可配置 per_beam_capacity 提高
    ref = schedule_ref(scenario, config)
    beams: List[VirtualBeam] = []
    for code in beam_codes:
        # 取现有经轴主档长度
        length = _beam_total_length(scenario, code)
        beams.append(VirtualBeam(
            beam_id=f"{prefix}-{code}-001",
            beam_code=code,
            total_length=length,
            remaining_length=length,
            earliest_available_minute=0,
            earliest_available=minute_to_iso(0, ref),
            status="库存",
            current_loom_id=None,
            is_derived=True,
        ))
    return beams


def _beam_total_length(scenario: WeavingScenario, code: str) -> Optional[float]:
    for b in scenario.经轴:
        if b.经轴品番 == code:
            return b.设定米数
    return None


def material_budgets(scenario: WeavingScenario, config: Dict[str, Any]) -> Dict[str, float]:
    """返回按纱线代码的可用库存(kg)。仅"库存"行、已确认口径；减去安全库存。
       到货(到货kg/到货托)未确认，不计入可用库存。"""
    safety = float(STAGE2_PARAMS["safety_stock"] or 0)
    budgets: Dict[str, float] = {}
    for m in scenario.物料:
        if (m.内容 or "") != "库存":
            continue
        vals = [v for v in m.日常.values() if v is not None]
        avail = max(vals) if vals else (m.期初库存 or 0)
        budgets[m.纱线代码] = max(0.0, avail - safety)
    return budgets


def build_maintenance(scenario: WeavingScenario, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(scenario.维护区间 or [])
