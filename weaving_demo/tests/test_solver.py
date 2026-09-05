# -*- coding: utf-8 -*-
"""test_solver.py -- 阶段2 CP-SAT 排程核心的 20 项测试。"""
from threading import Thread
from typing import List
import math
import copy

from weaving_demo.model import VirtualBeam
from weaving_demo.solver import solve
from weaving_demo.config import BUSINESS_RULES
from weaving_demo.tests.builders import (
    mk_product, mk_loom, mk_task, mk_scenario, mk_material,
)

EFF = 400          # 织造效率 米/天
SETUP_MOUNT = 330
SETUP_DROP = 10
SETUP_THREAD = 480


def _short(products, looms, tasks, **kw):
    return mk_scenario(products=products, looms=looms, tasks=tasks, start="2026-04-01",
                       end="2026-05-05", **kw)


# 1) 单任务单织机可行
def test_single_task_single_loom():
    sc = _short([mk_product("P1")], [mk_loom("#101")],
                [mk_task("T1", "P1", 3000, due_minute=90000)])
    r = solve(sc, max_time_s=5.0)
    assert r["status"] in ("OPTIMAL", "FEASIBLE")
    assert len(r["assignments"]) == 1
    a = r["assignments"][0]
    assert a["loom_id"] == "#101"
    assert abs(a["scheduled_quantity"] - 3000) < 1e-6
    assert r["unscheduled"][0]["unscheduled_quantity"] == 0


def test_daily_capacity_uses_exact_minute_conversion():
    sc = _short([mk_product("P1", effic=400)], [mk_loom("#101", current="P1")],
                [mk_task("T1", "P1", 1000, due_minute=90000)])
    r = solve(sc, max_time_s=5.0, max_layers=1)
    a = r["assignments"][0]
    # 1000米÷400米/天=2.5天=3600分钟，再加落布和上轴340分钟。
    assert a["end_minute"] - a["start_minute"] == 3940


def test_weekly_compactness_places_selected_work_at_earliest_time():
    sc = mk_scenario([mk_product("P1")], [mk_loom("#101", current="P1")],
                     [mk_task("T1", "P1", 1000, due_minute=90000)],
                     start="2026-04-01", end="2026-04-08")
    conf = copy.deepcopy(BUSINESS_RULES)
    conf["stage2_params"]["objective_layers"] = [
        "unscheduled_quantity", "schedule_compactness",
    ]
    r = solve(sc, config=conf, max_time_s=6.0, max_layers=2, horizon_days=7)
    assert r["assignments"][0]["start_minute"] == 0


# 2) 产品没有兼容织机
def test_no_compatible_loom():
    # 产品要求 13钢筘，织机都是 9.3钢筘 -> 无兼容
    sc = _short([mk_product("P1", reed="13钢筘")], [mk_loom("#101", reed="9.3钢筘")],
                [mk_task("T1", "P1", 3000)])
    r = solve(sc, max_time_s=5.0)
    assert len(r["assignments"]) == 0
    u = r["unscheduled"][0]
    assert u["unscheduled_quantity"] == 3000
    assert "NO_COMPATIBLE_LOOM" in u["reason_codes"]


# 3) 两个任务争用同一织机 -> 序列化，无重叠
def test_two_tasks_same_loom():
    sc = _short([mk_product("P1"), mk_product("P2")],
                [mk_loom("#101")],
                [mk_task("T1", "P1", 2000, due_minute=90000),
                 mk_task("T2", "P2", 2000, due_minute=90000)])
    r = solve(sc, max_time_s=8.0)
    assert len(r["assignments"]) == 2
    # 同一织机两个任务时间不重叠
    aa = sorted(r["assignments"], key=lambda x: x["start_minute"])
    assert aa[0]["end_minute"] <= aa[1]["start_minute"]
    assert r["validation"]["ok"]


# 4) 两台织机争用同一实体经轴 -> 无经轴时间重叠
def test_two_looms_share_beam():
    sc = _short([mk_product("P1"), mk_product("P2")],
                [mk_loom("#101"), mk_loom("#102")],
                [mk_task("T1", "P1", 2000, beam="WB1"),
                 mk_task("T2", "P2", 2000, beam="WB1")])
    r = solve(sc, max_time_s=8.0)
    assert len(r["assignments"]) == 2
    # 均需 WB1，经轴独占 -> 时间不得重叠
    bb = sorted(r["assignments"], key=lambda x: x["start_minute"])
    assert bb[0]["end_minute"] <= bb[1]["start_minute"], "同一经轴时间重叠"
    assert r["validation"]["ok"]


# 5) 经轴未到位时织造不得提前开始
def test_beam_availability():
    beam = VirtualBeam(beam_id="WB-P1-001", beam_code="WB1", earliest_available_minute=10000)
    sc = _short([mk_product("P1")], [mk_loom("#101")],
                [mk_task("T1", "P1", 1000, beam="WB1")], beams=[beam])
    r = solve(sc, max_time_s=5.0)
    a = r["assignments"][0]
    assert a["start_minute"] >= 10000, "经轴未到位，织造过早开始"


def test_beam_availability_applies_to_selected_non_first_loom():
    beam = VirtualBeam(beam_id="WB-P1-001", beam_code="WB1", earliest_available_minute=10000)
    sc = _short([mk_product("P1")], [mk_loom("#101"), mk_loom("#102")],
                [mk_task("T1", "P1", 1000, beam="WB1", allowed=["#101", "#102"])],
                beams=[beam], maints=[{"loom_id": "#101", "start_minute": 0, "end_minute": 50000}])
    r = solve(sc, max_time_s=5.0)
    a = r["assignments"][0]
    assert a["loom_id"] == "#102"
    assert a["start_minute"] >= 10000, "实际选中的非首台候选织机也必须等待整经完成"
    assert a["beam_ready_minute"] == 10000
    assert any(c["check"] == "process_precedence" and c["pass"] for c in r["validation"]["checks"])


# 6) 维修时间内不得安排任务
def test_maintenance_block():
    sc = _short([mk_product("P1")], [mk_loom("#101")],
                [mk_task("T1", "P1", 2000)],
                maints=[{"loom_id": "#101", "start_minute": 1000, "end_minute": 3000}])
    r = solve(sc, max_time_s=5.0)
    a = r["assignments"][0]
    assert not (a["start_minute"] < 3000 and a["end_minute"] > 1000), "任务落入维修区间"


# 7) 锁定任务位置保持不变
def test_locked_task_position():
    # 2000m @ 400m/天 = 7200分钟，加准备340分钟；5000开始 -> 12540结束。
    sc = _short([mk_product("P1")], [mk_loom("#101")],
                [mk_task("T1", "P1", 2000, locked=True, lock_machine="#101",
                         lock_start=5000, lock_end=12540, lock_qty=2000, lock_reason="人工")])
    r = solve(sc, max_time_s=5.0)
    a = r["assignments"][0]
    assert a["loom_id"] == "#101"
    assert a["start_minute"] == 5000 and a["end_minute"] == 12540
    assert a["locked"] is True and a["lock_reason"] == "人工"


# 8) 锁定任务互相冲突 -> 明确错误
def test_locked_task_conflict():
    sc = _short([mk_product("P1"), mk_product("P2")], [mk_loom("#101")],
                [mk_task("T1", "P1", 1000, locked=True, lock_machine="#101",
                         lock_start=1000, lock_end=5000, lock_qty=1000, lock_reason="r"),
                 mk_task("T2", "P2", 1000, locked=True, lock_machine="#101",
                         lock_start=3000, lock_end=7000, lock_qty=1000, lock_reason="r")])
    sc.规则配置 = {}
    r = solve(sc, max_time_s=5.0)
    assert r["status"] == "INFEASIBLE"
    assert any(i["severity"] == "ERROR" and "冲突" in i["message"] for i in r["issues"])


# 9) 物料不足 -> 部分可行方案与未排数量
def test_material_shortage_partial():
    # 单耗 0.63 kg/m，任务 3000m -> 需求 1890kg；库存 1000kg -> 只能排 ~1587m
    sc = _short([mk_product("P1", consump=0.63)], [mk_loom("#101")],
                [mk_task("T1", "P1", 3000, due_minute=90000, split=True, min_batch=500, parts=2)],
                materials=[mk_material("LS7056AB", avail=1000)])
    r = solve(sc, max_time_s=8.0)
    assert r["status"] in ("OPTIMAL", "FEASIBLE")
    sch = sum(a["scheduled_quantity"] for a in r["assignments"])
    assert sch > 0, "应有部分可行"
    assert sch < 3000, "物料不足应无法全部排完"
    us = r["unscheduled"][0]["unscheduled_quantity"]
    assert us > 0
    assert abs(sch + us - 3000) < 1e-6


# 10) 紧急任务优先降低交期延误
def test_urgent_priority_reduces_lateness():
    # 同一织机，两个任务，产能有限；高优先级紧急任务交期早，应被优先安排且不逾期
    sc = _short([mk_product("P1"), mk_product("P2")], [mk_loom("#101")],
                [mk_task("T1", "P1", 3000, due_minute=13000, priority=10.0),
                 mk_task("T2", "P2", 3000, due_minute=13000, priority=0.1)])
    r = solve(sc, max_time_s=8.0)
    # 高优先级 T1 应被排；T2 可能未排/逾期。检查 T1 无逾期
    t1 = [a for a in r["assignments"] if a["task_id"] == "T1"]
    assert len(t1) == 1
    assert t1[0]["lateness_minutes"] == 0


# 11) 不允许拆分的任务只使用一台织机
def test_no_split_one_loom():
    sc = _short([mk_product("P1")], [mk_loom("#101"), mk_loom("#102")],
                [mk_task("T1", "P1", 3000, split=False, allowed=["#101", "#102"])])
    r = solve(sc, max_time_s=5.0)
    assign = [a for a in r["assignments"] if a["task_id"] == "T1"]
    assert len(assign) == 1, "不允许拆分只能用一台织机"


def test_no_split_task_can_be_partially_scheduled_in_seven_day_window():
    sc = _short([mk_product("P1")], [mk_loom("#101"), mk_loom("#102")],
                [mk_task("T1", "P1", 3000, split=False, allowed=["#101", "#102"])])
    r = solve(sc, max_time_s=5.0, horizon_days=7)
    assign = [a for a in r["assignments"] if a["task_id"] == "T1"]
    assert len(assign) == 1, "不允许拆分的任务仍应只占一台织机"
    assert 0 < assign[0]["scheduled_quantity"] < 3000, "7 天窗口应允许滚动安排部分数量"
    assert r["unscheduled"][0]["unscheduled_quantity"] > 0


# 12) 允许拆分的任务满足最小批量和最大份数
def test_split_min_batch_max_parts():
    sc = _short([mk_product("P1")], [mk_loom("#101"), mk_loom("#102")],
                [mk_task("T1", "P1", 3000, split=True, min_batch=500, parts=3,
                         allowed=["#101", "#102"])])
    r = solve(sc, max_time_s=8.0)
    assign = [a for a in r["assignments"] if a["task_id"] == "T1"]
    assert len(assign) <= 3, "最大份数限制"
    assert len(assign) >= 1
    for a in assign:
        assert a["scheduled_quantity"] >= 500, "最小批量"
    total = sum(a["scheduled_quantity"] for a in assign)
    assert abs(total + r["unscheduled"][0]["unscheduled_quantity"] - 3000) < 1e-6


# 13) 换产品产生换款成本
def test_change_product_cost():
    # 织机当前生产 P1，任务为 P2 -> 换款
    sc = _short([mk_product("P1"), mk_product("P2")],
                [mk_loom("#101", current="P1")],
                [mk_task("T1", "P2", 1000)])
    r = solve(sc, max_time_s=5.0)
    a = r["assignments"][0]
    assert a["changeover_type"] in ("style_change", "threading")
    assert r["kpi"]["changeover_count"] >= 1


# 14) 同产品连续生产不产生换款成本
def test_same_product_no_change_cost():
    sc = _short([mk_product("P1")], [mk_loom("#101", current="P1")],
                [mk_task("T1", "P1", 1000)])
    r = solve(sc, max_time_s=5.0)
    a = r["assignments"][0]
    assert a["changeover_type"] not in ("style_change",)
    assert r["kpi"]["changeover_count"] == 0


# 15) 需要穿综穿筘时增加准备时间
def test_threading_adds_setup():
    sc = _short([mk_product("P1"), mk_product("P2")],
                [mk_loom("#101", current="P1")],
                [mk_task("T1", "P2", 2000)])  # 产品不同于织机当前 -> 需穿综穿筘
    r = solve(sc, max_time_s=5.0)
    a = r["assignments"][0]
    dur = a["end_minute"] - a["start_minute"]
    min_prod = math.ceil(2000 * 1440 / EFF)
    assert dur >= min_prod + SETUP_DROP + SETUP_MOUNT + SETUP_THREAD, "未加入穿综穿筘准备时间"


# 16) 求解时间到期返回当前最佳 FEASIBLE
def test_timeout_returns_best():
    # 容量受限 + 小超时，应返回 FEASIBLE/OPTIMAL，而非 INFEASIBLE
    looms = [mk_loom(f"#{i}01") for i in range(1, 4)]
    tasks = [mk_task(f"T{i}", "P1", 3000, due_minute=30000) for i in range(1, 9)]
    sc = _short([mk_product("P1")], looms, tasks)
    r = solve(sc, max_time_s=0.5)
    assert r["status"] in ("OPTIMAL", "FEASIBLE")
    if r["assignments"]:
        assert abs(sum(a["scheduled_quantity"] for a in r["assignments"]) +
                   sum(u["unscheduled_quantity"] for u in r["unscheduled"]) -
                   sum(u["required_quantity"] for u in r["unscheduled"])) < 1e-6


# 17) 可复现
def test_reproducible():
    def run():
        sc = _short([mk_product("P1")], [mk_loom("#101"), mk_loom("#102")],
                    [mk_task("T1", "P1", 3000, due_minute=90000, allowed=["#101", "#102"])])
        return solve(sc, max_time_s=5.0)
    a = run()
    b = run()
    assert a["assignments"] == b["assignments"]
    assert a["kpi"] == b["kpi"]


# 18) 无机台时间重叠
def test_no_loom_overlap():
    sc = _short([mk_product("P1"), mk_product("P2"), mk_product("P3")], [mk_loom("#101")],
                [mk_task("T1", "P1", 1500, due_minute=90000),
                 mk_task("T2", "P2", 1500, due_minute=90000),
                 mk_task("T3", "P3", 1500, due_minute=90000)])
    r = solve(sc, max_time_s=8.0)
    assert r["validation"]["ok"]
    assert any(c["check"] == "loom_no_overlap" and c["pass"] for c in r["validation"]["checks"])


# 19) 无经轴时间重叠
def test_no_beam_overlap():
    sc = _short([mk_product("P1"), mk_product("P2")], [mk_loom("#101"), mk_loom("#102")],
                [mk_task("T1", "P1", 2000, beam="WB1"), mk_task("T2", "P2", 2000, beam="WB1")])
    r = solve(sc, max_time_s=8.0)
    assert any(c["check"] == "beam_no_overlap" and c["pass"] for c in r["validation"]["checks"])


# 20) 已排+未排=需求 对账
def test_quantity_reconcile():
    looms = [mk_loom("#101")]
    tasks = [mk_task("T1", "P1", 3000, due_minute=90000),
             mk_task("T2", "P1", 3000, due_minute=90000),
             mk_task("T3", "P1", 3000, due_minute=90000)]
    sc = _short([mk_product("P1", consump=0.63)], looms, tasks,
                materials=[mk_material("LS7056AB", avail=1500)])
    r = solve(sc, max_time_s=8.0)
    for u in r["unscheduled"]:
        assert abs(u["required_quantity"] - u["scheduled_quantity"] - u["unscheduled_quantity"]) < 1e-6
    total_req = sum(u["required_quantity"] for u in r["unscheduled"])
    total_sch = sum(u["scheduled_quantity"] for u in r["unscheduled"])
    total_us = sum(u["unscheduled_quantity"] for u in r["unscheduled"])
    assert abs(total_req - total_sch - total_us) < 1e-6
