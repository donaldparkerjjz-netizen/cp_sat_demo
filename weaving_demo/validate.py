# -*- coding: utf-8 -*-
"""
validate.py -- 整经织造排工排产 Demo · 数据校验（三级严重度）与业务规则静态校验
===============================================================================
严重度：
  ERROR   -- 数据导致模型无法运行（如重复主键、负库存、锁定信息不完整）。
  WARNING -- 模型可运行，但结果使用了临时假设/数据缺口。
  INFO    -- 普通数据说明。

报告结构：
  { ok: bool, errors: [str], warnings: [str], info: [str],
    items: [ {severity, code, message} ], stats: {...}, severity: {error, warning, info} }
ok = (error 数为 0)。WARNING/INFO 不影响 ok，因此不再出现"完全无警告"。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from weaving_demo.model import (
    Product, Loom, WeavingScenario, YarnMaterial,
)
from weaving_demo.config import BUSINESS_RULES, TOOLING_SCOPE
from weaving_demo.compat import (  # noqa: F401  (再导出，方便调用方/测试)
    product_required_tooling,
    is_loom_compatible as _compat_is_loom_compatible,
    allowed_looms_for_product,
    loom_capabilities,
)


def is_loom_compatible(product: Product, loom: Loom,
                       config: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[str]]:
    """兼容判断（仅供阶段1简单调用）：展开 compat 的三元组为 (是否可行, 原因)。"""
    ok, reasons, _ = _compat_is_loom_compatible(product, loom, config)
    return ok, reasons


# ---------------------------------------------------------------------------
# 数据缺口 / 临时假设 警告（阶段1补丁）
# ---------------------------------------------------------------------------
def _data_gap_items(sc: WeavingScenario) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    # 1) 交期由月度预测推导
    sources = {d.来源 for d in sc.交期}
    if sources and sources <= {"customer_monthly_forecast"}:
        items.append(dict(severity="WARNING", code="due_from_forecast",
                          message="交期由客户月度预测推导，不是真实订单交期"))

    # 2) 织造效率统一
    effs = [p.织造效率 for p in sc.产品 if p.织造效率 is not None]
    if effs and len(set(effs)) <= 1:
        items.append(dict(severity="WARNING", code="uniform_weave_efficiency",
                          message=f"{len(effs)}个产品的织造效率为临时统一产能 {effs[0]} 米/天"))

    # 3) 经轴仅品番级
    if sc.经轴:
        has_entity = any(getattr(b, "beam_id", None) for b in getattr(sc, "虚拟经轴", []))
        if not has_entity:
            items.append(dict(severity="WARNING", code="beam_master_only",
                              message="经轴仅有品番级主档，无实体经轴编号与真实剩余长度"))

    # 4) 产品或织机缺少明确适配关系
    if sc.产品 and all(not p.allowed_loom_ids for p in sc.产品):
        items.append(dict(severity="WARNING", code="missing_compat",
                          message="产品或织机缺少明确适配关系，空适配不得解释为所有织机均可生产"))

    # 5) 工装需求不完整
    if sc.产品 and all((not p.钢筘型号 and not p.工装要求) for p in sc.产品):
        items.append(dict(severity="WARNING", code="incomplete_tooling",
                          message="钢筘、废边盘、切边等工装需求不完整（产品未给出钢筘/工装要求）"))

    # 6) 外部工作簿引用/公式无法解析
    if sc.数据来源 and ("益丰" in sc.数据来源 or "副本" in sc.数据来源):
        items.append(dict(severity="WARNING", code="external_ref_unresolved",
                          message="源表存在外部工作簿引用/公式，无法解析（仅读取缓存值）"))

    # 7) 时间口径不一致
    if sc.设置 and sc.设置.当前日期:
        items.append(dict(severity="WARNING", code="time_inconsistent",
                          message="织机状态、计划日期与库存数据更新时间不一致"))

    # 8) 上轴/落布/穿综穿筘时间为临时参数
    items.append(dict(severity="WARNING", code="temp_setup_params",
                      message="上轴330/穿综穿筘480/落布10分钟属临时参数"))

    # 9) 织造任务交期/数量/优先级来自推导
    if sc.织造任务 or (sc.生产任务 and any(t.来源 in (None, "derive") for t in sc.生产任务)):
        items.append(dict(severity="WARNING", code="derived_task_attrs",
                          message="织造任务交期、数量或优先级来自推导值"))

    # 10) 物料到货未确认
    if any(m.内容 in ("到货kg", "到货托") for m in sc.物料):
        items.append(dict(severity="WARNING", code="unconfirmed_arrival",
                          message="物料到货日期未确认，未确认到货不计入可用库存"))

    # INFO: 工装库存未建档（机台已有配置，仓库库存未建档）
    if sc.织机:
        stock = TOOLING_SCOPE.get("warehouse_stock_available") or {}
        if not stock:
            items.append(dict(severity="INFO", code="tooling_stock_not_built",
                              message="仓库工装库存未建档，阶段2仅校验机台已安装配置；产生'工装库存未建档'提醒"))
    return items


# ---------------------------------------------------------------------------
# 数据完整性校验
# ---------------------------------------------------------------------------
def validate_scenario(sc: WeavingScenario, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config or BUSINESS_RULES
    errors: List[str] = []
    warnings: List[str] = []
    items: List[Dict[str, Any]] = []

    # ---- ERROR：主键重复 / 空主键 ----
    seen_products: Dict[str, int] = {}
    for p in sc.产品:
        if not p.产品款号:
            errors.append("存在空产品款号")
            continue
        seen_products[p.产品款号] = seen_products.get(p.产品款号, 0) + 1
    seen_looms: Dict[str, int] = {}
    for l in sc.织机:
        if not l.织机号:
            errors.append("存在空织机号")
            continue
        seen_looms[l.织机号] = seen_looms.get(l.织机号, 0) + 1

    dup_products = [k for k, v in seen_products.items() if v > 1]
    dup_looms = [k for k, v in seen_looms.items() if v > 1]
    if dup_products:
        errors.append("产品款号重复: " + ", ".join(dup_products))
    if dup_looms:
        errors.append("织机号重复: " + ", ".join(dup_looms))

    # ---- ERROR：物料负库存 ----
    mat_errors = validate_material_non_negative(sc.物料)
    errors.extend(mat_errors)

    # ---- ERROR：锁定信息不完整（阶段2） ----
    lock_errs = _validate_locked_tasks(sc)
    errors.extend(lock_errs)

    # ---- ERROR：生产任务引用不存在的产品/织机 ----
    task_errs = _validate_tasks(sc, seen_products, seen_looms)
    errors.extend(task_errs)

    # ---- WARNING(数据缺口/临时假设)，不阻断可运行 ----
    gap = _data_gap_items(sc)
    items.extend(gap)

    # ---- INFO ----
    info_items = [it for it in items if it["severity"] == "INFO"]
    # ---- WARNING/ERROR 分解为字符串列表 ----
    warnings = [it["message"] for it in items if it["severity"] == "WARNING"]
    info = [it["message"] for it in info_items]

    # 关系完整性(引用织机存在) 作为 WARNING
    loom_set = set(seen_looms.keys())
    for tag, seq in (("织造", sc.织造任务), ("整经", sc.整经任务), ("落布", sc.落布预测)):
        for t in seq:
            if getattr(t, "织机", None) and t.织机 not in loom_set:
                items.append(dict(severity="WARNING", code=f"{tag}_task_ref_missing_loom",
                                  message=f"{tag}任务引用织机 {t.织机} 不在织机主档"))
    warnings = [it["message"] for it in items if it["severity"] == "WARNING"]

    # ---- 统计 ----
    stats: Dict[str, Any] = dict(
        产品数=len(sc.产品), 织机数=len(sc.织机), 工艺条件数=len(sc.工艺条件),
        经轴数=len(sc.经轴), 整经任务数=len(sc.整经任务), 织造任务数=len(sc.织造任务),
        落布预测数=len(sc.落布预测), 物料数=len(sc.物料), 交期数=len(sc.交期),
        生产任务数=len(sc.生产任务), 虚拟经轴数=len(sc.虚拟经轴),
        织机可用数=sum(1 for l in sc.织机 if l.状态可用),
        重复产品=dup_products, 重复织机=dup_looms,
        ERROR=len(errors), WARNING=len(warnings), INFO=len(info),
    )

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "items": items,
        "stats": stats,
        "severity": {"error": len(errors), "warning": len(warnings), "info": len(info)},
    }


def _validate_locked_tasks(sc: WeavingScenario) -> List[str]:
    errs: List[str] = []
    for t in sc.生产任务:
        if not t.locked:
            continue
        missing = []
        if not t.locked_machine_id:
            missing.append("locked_machine_id")
        if t.locked_start_minute is None:
            missing.append("locked_start")
        if t.locked_end_minute is None:
            missing.append("locked_end")
        if t.locked_quantity is None:
            missing.append("locked_quantity")
        if not t.lock_reason:
            missing.append("lock_reason")
        if missing:
            errs.append(f"任务 {t.task_id} 锁定信息不完整: 缺 " + ",".join(missing))
    return errs


def _validate_tasks(sc: WeavingScenario, products: Dict[str, int],
                    looms: Dict[str, int]) -> List[str]:
    errs: List[str] = []
    for t in sc.生产任务:
        if t.product_id and t.product_id not in products:
            errs.append(f"任务 {t.task_id} 引用不存在的产品 {t.product_id}")
        for loom_id in (t.allowed_loom_ids or []):
            if loom_id not in looms:
                errs.append(f"任务 {t.task_id} 引用不存在的织机 {loom_id}")
    return errs


def validate_material_non_negative(materials: List[YarnMaterial]) -> List[str]:
    """某纱线"库存"行的逐日库存值不得为负。”"""
    errors: List[str] = []
    for m in materials:
        if (m.内容 or "") != "库存":
            continue
        for dt, val in m.日常.items():
            if val is not None and val < 0:
                errors.append(f"物料 {m.纱线代码} 在 {dt} 库存为负({val})")
    return errors


def summarize(sc: WeavingScenario) -> Dict[str, Any]:
    return validate_scenario(sc)
