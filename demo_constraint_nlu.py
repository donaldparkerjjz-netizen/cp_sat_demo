# -*- coding: utf-8 -*-
"""
demo_constraint_nlu.py -- 自然语言约束解析 (企业方操作员用自然语言描述软/硬约束)
===============================================================================
把操作员输入的句子解析为结构化约束, 供排产引擎应用。本 Demo 面向"织造车间·
整经-穿综穿筘-织造": 资源为 织机(looms) / 整经机(warp_machines) / 穿综工位(draw_stations);
时间单位为小时(1h), 交期以"第X天Y时"表达。

支持约束类型:
  硬约束:
    order_deadline      订单须在某小时前完成              "O01必须在第3天12时前完成"
    order_machine       订单固定到某织机                 "O01只能上L3"
    product_machine     某产品只能在指定织机织造          "P3只能在L3 L4 L6上织造"
    machine_unavailable 某织机某些小时不可用(检修)        "L1第2天全天停机"
    max_shifts          某织机排产时长上限(小时)          "L5最多织造60小时"
    contiguity          订单连续生产(默认满足)            "订单必须连续生产"
  软约束:
    soft_changeover     尽量少改品番/换型                 "改品番尽量少", "换型越少越好"
    soft_beam_ready     经轴尽量提前/及时就绪(反向)       "经轴尽量提前就绪", "减少织机等经轴"
    soft_priority       优先排某订单/产品                 "O01优先", "P1优先"
    soft_utilization    提高织机利用率/减少空闲           "尽量提高织机利用率"

用法:
    from demo_constraint_nlu import parse_constraints
    parsed = parse_constraints("O01必须在第3天12时前完成；改品番尽量少", scenario)
"""
from __future__ import annotations
import re

CONSTRAINT_TYPES = {
    "order_deadline": ("硬约束-交期", True),
    "order_machine": ("硬约束-织机固定", True),
    "product_machine": ("硬约束-产品适配", True),
    "machine_unavailable": ("硬约束-织机停用", True),
    "max_shifts": ("硬约束-排产时长上限", True),
    "contiguity": ("硬约束-连续生产", True),
    "soft_changeover": ("软约束-换型最少", False),
    "soft_beam_ready": ("软约束-经轴就绪", False),
    "soft_priority": ("软约束-优先级", False),
    "soft_utilization": ("软约束-利用率", False),
}


def _scenario_hpd(scenario):
    return int(scenario.get("hours_per_day", 24))


def _scenario_T(scenario):
    return int(scenario.get("days", 7)) * _scenario_hpd(scenario)


def _vocab(scenario):
    products = {}
    for pid, v in scenario.get("products", {}).items():
        products[pid] = {"id": pid, "name": v.get("name", "")}
    machines = {}
    for lst in ("looms", "warp_machines", "draw_stations"):
        for m in scenario.get(lst, []):
            kind = {"looms": "loom", "warp_machines": "warp", "draw_stations": "draw"}[lst]
            machines[m["id"]] = {"id": m["id"], "name": m.get("name", ""),
                                 "team": m.get("team", ""), "kind": kind}
    teams = sorted({m.get("team", "") for m in scenario.get("looms", [])})
    orders = [{"id": o["id"], "product": o.get("product", ""), "pri": o.get("pri", 5)}
              for o in scenario.get("orders", [])]
    return {"products": products, "machines": machines, "teams": teams, "orders": orders}


# ---------- 实体识别 ----------
def _find_orders(text, voc):
    ids = set(re.findall(r"(?<![A-Za-z0-9])(O|R|N)[0-9]{2,}(?![0-9])", text, re.I))
    out, seen = [], set()
    low = text.lower()
    for o in voc["orders"]:
        if o["id"] in ids or o["id"].lower() in low:
            if o["id"] not in seen:
                seen.add(o["id"]); out.append(o)
    return out


def _find_products(text, voc):
    ids = set(re.findall(r"(?<![A-Za-z0-9])P[0-9]{1,3}(?![0-9])", text, re.I))
    out, seen = [], set()
    low = text.lower()
    for pid, p in voc["products"].items():
        if pid in ids or pid.lower() in low or (p["name"] and p["name"] in text):
            if pid not in seen:
                seen.add(pid); out.append(p)
    return out


def _find_machines(text, voc):
    ids = set(re.findall(r"(?<![A-Za-z0-9])(?:L|W|DR)[ ]?[0-9]{1,3}(?![0-9])", text, re.I))
    out, seen = [], set()
    low = text.lower()
    for mid, m in voc["machines"].items():
        if mid in ids or mid.lower() in low or (m["name"] and m["name"] in text):
            if mid not in seen:
                seen.add(mid); out.append(m)
    return out


def _find_teams(text, voc):
    out = []
    for te in voc["teams"]:
        if not te:
            continue
        key = te.rstrip("组")
        if te in text or (key and key in text):
            out.append(te)
    return out


# ---------- 时间解析: 返回 1-based 小时槽位(跨天) ----------
def _extract_slot(text, T=168, hpd=24):
    """把'第X天Y时'解析为小时索引(1..T)。支持 第X天 / 第X天Y时 / 第N小时 / 今天/明天。"""
    m = re.search(r"(?:第)[ ]*([0-9]{1,2})[ ]*天[ ]*([0-9]{1,2})[ ]*(?:时|点)?", text)
    if m:
        day = int(m.group(1)); hh = int(m.group(2) or 0)
        return min(T, (day - 1) * hpd + hh)
    m = re.search(r"(?:第)[ ]*([0-9]{1,2})[ ]*天", text)
    if m:
        day = int(m.group(1))
        return min(T, day * hpd)
    m = re.search(r"(?:第|小时|槽)[ ]*([0-9]{1,3})[ ]*(?:h|小时|时|槽)?", text)
    if m:
        return min(T, int(m.group(1)))
    m = re.search(r"([0-9]{1,3})[ ]*[个]?(?:小时|h|时|点)", text)
    if m:
        return min(T, int(m.group(1)))
    if "今天" in text: return min(T, 1 * hpd)
    if "明天" in text: return min(T, 2 * hpd)
    if "后天" in text: return min(T, 3 * hpd)
    return None


def _extract_number(text, default=None):
    for m in re.finditer(r"([0-9]{1,4})", text):
        return int(m.group(1))
    return default


def _extract_shift_count(text, default=None):
    """提取'最多N小时'中的时长(跳过资源编号里的数字)。"""
    m = re.search(r"([0-9]{1,3})[ ]*(?:个[ ]*)?(?:小时|h|时)", text)
    if m:
        return int(m.group(1))
    return default


def _ids(objs):
    return [o["id"] for o in objs]


# ---------- 意图匹配 ----------
def _parse_sentence(sent, voc, T=168, hpd=24):
    s = sent.strip().strip("，,。；; ")
    if not s:
        return None
    orders = _find_orders(s, voc)
    products = _find_products(s, voc)
    machines = _find_machines(s, voc)
    teams = _find_teams(s, voc)
    slot = _extract_slot(s, T, hpd)

    def rec(type_, hard, entity="", entities=None, params=None, desc=""):
        return {"type": type_, "hard": hard,
                "entity": entity or (entities[0] if entities else ""),
                "entities": entities or [], "params": params or {},
                "raw": s, "desc": desc, "recognized": True}

    def unknown(why=""):
        return {"type": "unknown", "hard": False, "entity": "", "entities": [], "params": {},
                "raw": s, "desc": "未能识别：" + (why or s), "recognized": False}

    # 1) 织机停用/不可用
    if machines and re.search(r"(停机|停用|检修|停产|不能生产|不可用|不排|休息|不生产)", s):
        m = machines[0]["id"]
        if re.search(r"(全天|整天|当天|一天|停一天)", s):
            # 封锁整天
            dm = re.search(r"(?:第)[ ]*([0-9]{1,2})[ ]*天", s)
            day = int(dm.group(1)) if dm else 1
            hours = list(range((day - 1) * hpd + 1, min(T, day * hpd) + 1))
            desc = f"织机 {m} 停工：第 {day} 天（{hours[0]}-{hours[-1]} 小时）"
        else:
            hours = [slot] if slot else list(range(1, T + 1))
            desc = f"织机 {m} 不可用小时：{'、'.join(map(str, [slot] if slot else [hours[0],'..',hours[-1]]))}（停机/检修）"
        return rec("machine_unavailable", True, entity=m, params={"slots": hours}, desc=desc)

    # 2) 排产时长上限
    if machines and re.search(r"(最多|上限|不能超过|不超过|不得超过|最多只能)", s):
        n = _extract_shift_count(s)
        if n:
            m = machines[0]["id"]
            return rec("max_shifts", True, entity=m, params={"count": n},
                       desc=f"织机 {m} 排产时长不超过 {n} 小时")

    # 3) 换型/改品番最少(软)
    if re.search(r"(改品番|换型|换版|切换|转产|换品种)", s) and re.search(r"(越少越好|尽量少|最小|最少|减少|降低)", s):
        return rec("soft_changeover", False, desc="软约束：改品番/换型次数越少越好")

    # 4) 经轴就绪/反向拉动(软)
    if re.search(r"(经轴|织机等待|就绪)", s) and re.search(r"(提前|及时|就绪|越早|减少等待|反向|拉动)", s):
        return rec("soft_beam_ready", False, desc="软约束：经轴尽量提前/及时就绪，减少织机等待经轴")

    # 5) 利用率(软)
    if re.search(r"(利用率|开机率|空闲)", s) and re.search(r"(提高|最大|越满|减少|降低)", s):
        return rec("soft_utilization", False, desc="软约束：提高织机利用率/减少空闲")

    # 6) 交期/必须完成(硬)
    if re.search(r"(完成|交期|截止|之前|不晚于|最晚|必须|前交货|前交付|前完成)", s):
        if orders:
            d = slot or _extract_number(s)
            if d:
                return rec("order_deadline", True, entity=orders[0]["id"],
                           params={"slot": int(d), "product": orders[0]["product"]},
                           desc=f"订单 {orders[0]['id']} 硬约束：完成不晚于第 {int(d)} 小时")
        if products:
            d = slot or _extract_number(s)
            if d:
                return rec("order_deadline", True, entity=products[0]["id"],
                           entities=[products[0]["id"]], params={"slot": int(d), "product": products[0]["id"]},
                           desc=f"产品 {products[0]['id']} 硬约束：全部订单完成不晚于第 {int(d)} 小时")
        if slot:
            return rec("order_deadline", True, entity="__all__", params={"slot": int(slot)},
                       desc=f"全局硬约束：所有订单完成不晚于第 {slot} 小时")

    # 7) 产品只能在某织机
    if products and machines and re.search(r"(只能|仅限|限定|必须上|只能在|安排在|织造)", s):
        p = products[0]["id"]
        ms = _ids(machines)
        return rec("product_machine", True, entity=p, entities=[p], params={"machines": ms},
                   desc=f"产品 {p} 只能在织机 {'、'.join(ms)} 织造")

    # 8) 订单固定织机
    if orders and machines and re.search(r"(固定|安排在|排到|只上|只能上|放在|改到)", s):
        o = orders[0]
        m = machines[0]["id"]
        return rec("order_machine", True, entity=o["id"], params={"machines": [m]},
                   desc=f"订单 {o['id']} 固定到织机 {m}")

    # 9) 优先(软)
    if re.search(r"(优先|先做|先排|加急|紧急|急单|提前)", s):
        if orders:
            ids = _ids(orders)
            return rec("soft_priority", False, entity=ids[0], entities=ids, params={"priority": 10},
                       desc=f"软约束：优先排订单 {'、'.join(ids)}")
        if products:
            ids = _ids(products)
            return rec("soft_priority", False, entity=ids[0], entities=ids, params={"priority": 10},
                       desc=f"软约束：优先排产品 {'、'.join(ids)}")
        if teams:
            return rec("soft_priority", False, entity=teams[0], entities=[teams[0]],
                       params={"team": teams[0]}, desc=f"软约束：优先排班组 {teams[0]}")

    # 10) 连续生产(默认满足)
    if re.search(r"(连续|不间断|一次|连排)", s):
        return rec("contiguity", True, desc="硬约束：订单连续生产(已默认满足)")

    return unknown("未匹配到已知约束类型")


def parse_constraints(text, scenario):
    """解析一段自然语言文本(可含多句), 返回结构化约束列表。"""
    hpd = _scenario_hpd(scenario)
    T = _scenario_T(scenario)
    voc = _vocab(scenario)
    parts = re.split(r"[。；;\n]+", text)
    parsed, errors = [], []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        r = _parse_sentence(p, voc, T, hpd)
        if r and r["recognized"]:
            parsed.append(r)
        elif r:
            errors.append(r)
    return {"count": len(parsed), "parsed": parsed, "errors": errors,
            "summary": _summarize(parsed)}


def _summarize(parsed):
    hard = [c for c in parsed if c["hard"]]
    soft = [c for c in parsed if not c["hard"]]
    return {"text": f"解析成功 {len(parsed)} 条：硬约束 {len(hard)} 条，软约束 {len(soft)} 条。",
            "details": [c["desc"] for c in parsed]}


if __name__ == "__main__":
    import sys, json
    sys.path.insert(0, r"D:\dsh\cp_sat_demo")
    from demo_engine import DEFAULT_SCENARIO
    demo = ("O01必须在第3天12时前完成；P3只能在L3 L4 L6上织造；L1第2天全天停机；"
            "L5最多织造60小时；改品番尽量少；经轴尽量提前就绪；O01优先织")
    print(json.dumps(parse_constraints(demo, DEFAULT_SCENARIO), ensure_ascii=False, indent=2))
