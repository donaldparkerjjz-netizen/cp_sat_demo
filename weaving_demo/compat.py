# -*- coding: utf-8 -*-
"""
compat.py -- 整经织造排工排产 Demo · 产品-织机适配（阶段2规则）
===============================================================================
适配判定（阶段2确认的规则）：
  1) 优先采用"产品明确指定的可用织机清单"(Product.allowed_loom_ids)。
  2) 没有明确清单时，再根据织机已安装能力(废边盘类型/废边盘安装孔位/切边/钢筘/
     全幅边撑/齿轮或铝轮/综丝/纱架/大卷装/水过滤)进行匹配。
  3) 钢筘规格已知时默认要求与织机钢筘完全匹配；钢筘规格缺失时不直接判定为兼容，
     产生数据警告。禁止把"适配信息为空"解释成"所有织机都可以生产"。
返回 (是否可行, 原因列表, 警告列表)。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from weaving_demo.model import Product, Loom
from weaving_demo.config import BUSINESS_RULES

# 织机已安装能力 -> 是否布尔型
_BOOL_CAPS = ["waste_edge_disc", "edge_cut", "yarn_frame", "big_package",
              "water_filter", "gear_or_aluminum_wheel", "heald"]
# 织机已安装能力 -> 字符串/数值型
_STR_CAPS = ["reed", "full_width_edge_support", "waste_edge_hole_pos"]


def product_required_tooling(product: Product, config: Optional[Dict[str, Any]] = None) -> List[str]:
    """推导产品要求的工装清单。仅包含产品确实需要的工装：
       * 钢筘型号已知 -> 需钢筘(且完全匹配)
       * 有效门幅>2.0 -> 需全幅边撑
       * 显式声明的工装要求
       缺省的其它能力(废边盘/切边/纱架/…)在数据未给出产品需求时不强制，仅做能力匹配与提示。"""
    req: List[str] = []
    if product.钢筘型号:
        req.append("reed")
    if product.有效门幅 and product.有效门幅 > 2.0:
        req.append("full_width_edge_support")
    for t in product.工装要求 or []:
        if t not in req:
            req.append(t)
    return req


def loom_capabilities(loom: Loom) -> Dict[str, Any]:
    """返回织机已安装能力映射（键 -> 值/布尔）。"""
    c: Dict[str, Any] = {}
    if loom.废边盘 is not None:
        c["waste_edge_disc"] = loom.废边盘
    if loom.废边盘安装孔位 is not None:
        c["waste_edge_hole_pos"] = loom.废边盘安装孔位
    if loom.切边 is not None:
        c["edge_cut"] = loom.切边
    if loom.钢筘 is not None:
        c["reed"] = loom.钢筘
    if loom.全幅边撑 is not None:
        c["full_width_edge_support"] = loom.全幅边撑
    if loom.齿轮或铝轮 is not None:
        c["gear_or_aluminum_wheel"] = loom.齿轮或铝轮
    if loom.综丝 is not None:
        c["heald"] = loom.综丝
    if loom.纱架 is not None:
        c["yarn_frame"] = loom.纱架
    if loom.大卷装 is not None:
        c["big_package"] = loom.大卷装
    if loom.水过滤 is not None:
        c["water_filter"] = loom.水过滤
    return c


def _parse_num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(v))
    return float(m.group(1)) if m else None


def _edge_support_meters(v: Any) -> Optional[float]:
    n = _parse_num(v)
    if n is None:
        return None
    s = str(v).strip().lower()
    if "m" in s and "mm" not in s:
        return n
    return n / 1000.0 if n > 10 else n


def _match_bool(actual: Any, required: bool) -> bool:
    if actual is None:
        return False          # 未配置 -> 无法确认
    return bool(actual) == required


def _mode(config: Optional[Dict[str, Any]]) -> str:
    mode = (config or BUSINESS_RULES).get("stage2_params", {}).get("compatibility_mode", "balanced")
    return mode if mode in ("strict", "balanced", "simulation") else "balanced"


def is_loom_compatible(product: Product, loom: Loom,
                       config: Optional[Dict[str, Any]] = None,
                       mode: Optional[str] = None) -> Tuple[bool, List[str], List[str]]:
    """判断产品能否排到该织机。返回 (是否可行, 原因列表, 警告列表)。
       mode: strict(缺关键适配数据禁排) / balanced(明确冲突禁排, 缺失试排+风险) /
             simulation(仅演示, 基础能力匹配)。"""
    cfg = (config or BUSINESS_RULES)
    mode = mode or _mode(config)
    reasons: List[str] = []
    warns: List[str] = []

    # 0) 织机不可用
    if not loom.状态可用:
        reasons.append(f"织机状态不可用({loom.当前状态})")

    # 1) 明确适配清单优先（先看产品指定的织机清单，再看织机声明的可对应产品）
    if product.allowed_loom_ids:
        if loom.织机号 not in product.allowed_loom_ids:
            reasons.append("不在产品允许织机清单")
            return False, reasons, warns
        return True, [], warns
    if loom.可对应产品:
        if product.产品款号 not in loom.可对应产品:
            reasons.append(f"不在织机可对应产品清单({','.join(loom.可对应产品)})")
            return False, reasons, warns
        return True, [], warns

    # 2) 无明确清单 -> 按已记录能力匹配
    if product.钢筘型号:
        if not loom.钢筘:
            reasons.append("缺钢筘")
        elif product.钢筘型号 not in loom.钢筘 and product.钢筘型号 != loom.钢筘:
            reasons.append(f"钢筘不匹配(需{product.钢筘型号}, 有{loom.钢筘})")
    else:
        warns.append(f"产品{product.产品款号}钢筘规格缺失，未启用钢筘精确匹配")

    if product.有效门幅:
        es = _edge_support_meters(loom.全幅边撑)
        if es is None:
            if mode == "strict":
                reasons.append("缺全幅边撑")
            else:
                warns.append(f"织机{loom.织机号}未配置全幅边撑，无法确认门幅适配")
        elif es < product.有效门幅:
            reasons.append(f"门幅{product.有效门幅}超过全幅边撑{loom.全幅边撑}")

    req = product_required_tooling(product, config)
    for t in req:
        if t != "full_width_edge_support":
            missing_tool = _check_one_tooling(loom, t)
            if missing_tool:
                reasons.append("缺工装: " + missing_tool)

    # 3) 织机无任何能力信息 -> 不可确认兼容(禁止"空适配=全兼容")
    caps = loom_capabilities(loom)
    if not caps:
        if mode != "simulation":
            reasons.append("织机无能力信息，无法确认适配")
            warns.append(f"织机{loom.织机号}与产品{product.产品款号}均无明确适配/能力信息")
        else:
            warns.append(f"织机{loom.织机号}无能力信息(simulation 模式试排)")

    return (len(reasons) == 0, reasons, warns)


def _check_one_tooling(loom: Loom, t: str) -> Optional[str]:
    name_map = {
        "waste_edge_disc": "废边盘", "edge_cut": "切边", "yarn_frame": "纱架",
        "big_package": "大卷装", "water_filter": "水过滤", "reed": "钢筘",
        "full_width_edge_support": "全幅边撑", "gear_or_aluminum_wheel": "齿轮/铝轮",
        "heald": "综丝",
    }
    flags = {"waste_edge_disc": loom.废边盘, "edge_cut": loom.切边, "yarn_frame": loom.纱架,
             "big_package": loom.大卷装, "water_filter": loom.水过滤,
             "gear_or_aluminum_wheel": loom.齿轮或铝轮, "heald": loom.综丝}
    if t in flags:
        return None if flags[t] is True else name_map[t]
    if t == "reed":
        return None if loom.钢筘 else name_map["reed"]
    return name_map.get(t)


def allowed_looms_for_product(product: Product, looms: List[Loom],
                              config: Optional[Dict[str, Any]] = None,
                              mode: Optional[str] = None) -> Tuple[List[str], List[str]]:
    """返回产品可用的全部织机编号 + 适配警告。空清单 = 无兼容织机。"""
    allowed: List[str] = []
    warns: List[str] = []
    for l in looms:
        ok, reasons, w = is_loom_compatible(product, l, config, mode)
        warns.extend(w)
        if ok:
            allowed.append(l.织机号)
    return allowed, warns


def diagnose_product_compat(product: Product, looms: List[Loom], config: Optional[Dict[str, Any]] = None,
                            mode: Optional[str] = None) -> Dict[str, Any]:
    """对单个产品输出适配诊断：明确指定可用织机数、工装推导可用织机数、最终候选织机数、
       被排除主要原因、以及 0/空/NULL/未知 字段语义。"""
    all_looms = [l for l in looms if l.状态可用]
    # 明确指定可用织机
    explicit = [l for l in all_looms if l.织机号 in (product.allowed_loom_ids or [])]
    # 工装推导可用织机(忽略明确清单，只看能力)
    tooling_allowed = []
    for l in all_looms:
        if l.可对应产品:
            if product.产品款号 in l.可对应产品:
                tooling_allowed.append(l.织机号)
        else:
            ok, _, _ = is_loom_compatible(product, l, config, mode)
            if ok:
                tooling_allowed.append(l.织机号)
    final_allowed, warns = allowed_looms_for_product(product, all_looms, config, mode)

    # 排除原因统计(仅考虑有效织机)
    reject_by = {"product_rule": 0, "tooling_rule": 0, "calendar": 0, "lock": 0,
                 "beam": 0, "material": 0, "horizon": 0}
    reject_msgs: Dict[str, List[str]] = {k: [] for k in reject_by}
    for l in all_looms:
        ok, reasons, _ = is_loom_compatible(product, l, config, mode)
        if ok:
            continue
        reason_str = "|".join(reasons)
        if "清单" in reason_str:
            reject_by["product_rule"] += 1
            reject_msgs["product_rule"].append(f"{l.织机号}:{reason_str}")
        elif "门幅" in reason_str or "钢筘" in reason_str or "工装" in reason_str:
            reject_by["tooling_rule"] += 1
            reject_msgs["tooling_rule"].append(f"{l.织机号}:{reason_str}")
        elif "不可用" in reason_str:
            reject_by["calendar"] += 1
            reject_msgs["calendar"].append(f"{l.织机号}:{reason_str}")
        else:
            reject_by["tooling_rule"] += 1
            reject_msgs["tooling_rule"].append(f"{l.织机号}:{reason_str}")

    main_reason = max(reject_by, key=lambda k: reject_by[k]) if any(reject_by.values()) else None
    return {
        "product_id": product.产品款号,
        "all_loom_count": len(all_looms),
        "explicit_loom_count": len(explicit),
        "tooling_derived_loom_count": len(tooling_allowed),
        "compatible_loom_count": len(final_allowed),
        "final_candidate_loom_count": len(final_allowed),
        "candidate_loom_ids": final_allowed,
        "rejected_loom_count": len(all_looms) - len(final_allowed),
        "rejected_by_product_rule": reject_by["product_rule"],
        "rejected_by_tooling_rule": reject_by["tooling_rule"],
        "rejected_by_calendar": reject_by["calendar"],
        "rejected_by_lock": reject_by["lock"],
        "rejected_by_beam": reject_by["beam"],
        "rejected_by_material": reject_by["material"],
        "rejected_by_horizon": reject_by["horizon"],
        "main_rejection_reason": main_reason,
        "rejection_details": reject_msgs,
        "warnings": warns,
    }
