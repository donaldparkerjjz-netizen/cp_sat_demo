# -*- coding: utf-8 -*-
"""test_diagnose.py -- 阶段2.5 业务合理性测试。"""
import pytest

from weaving_demo.model import VirtualBeam
from weaving_demo import prep
from weaving_demo.solver import solve
from weaving_demo.config import BUSINESS_RULES
from weaving_demo.tests.builders import (
    mk_product, mk_loom, mk_task, mk_scenario, mk_material,
)


def _sc(products, looms, tasks, **kw):
    return mk_scenario(products=products, looms=looms, tasks=tasks, start="2026-04-01",
                       end="2026-05-05", **kw)


def _r(sc, max_time=5.0, **kw):
    return solve(sc, max_time_s=max_time, config=BUSINESS_RULES, **kw)


# 1) 候选织机多且任务量少时，不能因换款目标导致大量任务未排
def test_many_looms_few_tasks_high_coverage():
    looms = [mk_loom(f"#{i}01") for i in range(1, 6)]
    tasks = [mk_task(f"T{i}", "P1", 800, due_minute=50000, allowed=[l.织机号 for l in looms])
             for i in range(1, 4)]
    r = _r(_sc([mk_product("P1")], looms, tasks))
    assert r["kpi"]["demand_coverage_rate"] >= 0.99, "大量可用机台不应因换款目标导致未排"


# 2) 减少换款不能降低需求覆盖率（L6 换款层在 L1 未排层之后）
def test_changeover_does_not_reduce_coverage():
    # 同一织机两个产品；换款目标不应使任务未排
    r = _r(_sc([mk_product("P1"), mk_product("P2")], [mk_loom("#101")],
               [mk_task("T1", "P1", 1000, due_minute=50000),
                mk_task("T2", "P2", 1000, due_minute=50000)]))
    assert r["kpi"]["demand_coverage_rate"] >= 0.99, "换款目标不得降低覆盖率"


# 3) 提高低优先级目标不能破坏高优先级最优值（L1 未排已固定）
def test_lower_priority_does_not_break_layer1():
    r = _r(_sc([mk_product("P1"), mk_product("P2")],
               [mk_loom("#101"), mk_loom("#102")],
               [mk_task("T1", "P1", 1500, due_minute=50000, allowed=["#101", "#102"]),
                mk_task("T2", "P2", 1500, due_minute=50000, allowed=["#101", "#102"])]))
    # L1 未排固定后，实际未排应与 L1 最优值一致
    l1 = next(l for l in r["objective_levels"] if l["name"] == "unscheduled_quantity")
    assert abs(r["kpi"]["unscheduled_quantity"] - l1["best_value"]) <= 1e-6, "后续层破坏了L1最优值"


# 4) 利用率公式可用手工数据准确复算
def test_utilization_manual_recompute():
    maints = [{"loom_id": "#101", "start_minute": 1000, "end_minute": 2000}]
    sc = _sc([mk_product("P1")], [mk_loom("#101")],
             [mk_task("T1", "P1", 1000, due_minute=50000)], maints=maints)
    r = _r(sc)
    # 手动：可用 = 1*horizon - 维修1000；已排 = sum(assignment end-start)
    usable_looms = 1
    avail = usable_looms * prep.horizon_minutes(sc, BUSINESS_RULES) - 1000
    sch_min = sum(a["end_minute"] - a["start_minute"] for a in r["assignments"])
    assert abs(r["kpi"]["scheduled_machine_minutes"] - sch_min) < 1e-6
    assert abs(r["kpi"]["utilization"] - sch_min / avail) < 1e-3


# 5) 部分任务已排与未排对账
def test_partial_reconcile():
    looms = [mk_loom("#101")]
    tasks = [mk_task("T1", "P1", 3000, due_minute=50000),
             mk_task("T2", "P1", 3000, due_minute=50000),
             mk_task("T3", "P1", 3000, due_minute=50000)]
    r = _r(_sc([mk_product("P1", consump=0.63)], looms, tasks,
               materials=[mk_material("LS7056AB", avail=1500)]))
    for u in r["unscheduled"]:
        assert abs(u["required_quantity"] - u["scheduled_quantity"] - u["unscheduled_quantity"]) < 1e-6


# 6) unscheduled 区分完全未排与部分未排
def test_unscheduled_classification():
    looms = [mk_loom("#101")]
    tasks = [mk_task("T1", "P1", 3000, due_minute=50000, split=True, min_batch=500, parts=2),
             mk_task("T2", "P1", 3000, due_minute=50000)]
    r = _r(_sc([mk_product("P1", consump=0.63)], looms, tasks,
               materials=[mk_material("LS7056AB", avail=1000)]))
    d = r["diagnostics"]
    assert d["fully_unscheduled_task_count"] + d["partially_unscheduled_task_count"] == \
        sum(1 for t in tasks if t.task_id in {u["task_id"] for u in r["unscheduled"] if u["unscheduled_quantity"] > 0})


# 7) 最大延误必须能定位到具体任务
def test_max_delay_task_locatable():
    tasks = [mk_task("T1", "P1", 1200, due_minute=10000),
             mk_task("T2", "P1", 1200, due_minute=50000)]
    r = _r(_sc([mk_product("P1")], [mk_loom("#101"), mk_loom("#102")], tasks))
    max_delay_a = max(a["lateness_minutes"] for a in r["assignments"])
    assert abs(max_delay_a - r["kpi"]["max_lateness_minutes"]) < 1e-6
    assert r["kpi"]["max_delay_task_id"] is not None
    worst = max(r["assignments"], key=lambda a: a["lateness_minutes"])
    assert r["kpi"]["max_delay_task_id"] == worst["task_id"]


# 8) 关闭物料约束后，已排数量不应减少
def test_disable_material_not_decrease_scheduled():
    sc = _sc([mk_product("P1", consump=0.63)], [mk_loom("#101")],
             [mk_task("T1", "P1", 3000, due_minute=50000, split=True, min_batch=500, parts=2)],
             materials=[mk_material("LS7056AB", avail=500)])
    a = _r(sc)
    b = _r(sc, material_enabled=False)
    assert b["kpi"]["scheduled_quantity"] >= a["kpi"]["scheduled_quantity"] - 1e-6


# 9) 关闭经轴约束后，已排数量不应减少
def test_disable_beam_not_decrease_scheduled():
    sc = _sc([mk_product("P1"), mk_product("P2")], [mk_loom("#101"), mk_loom("#102")],
             [mk_task("T1", "P1", 1200, beam="WB1", allowed=["#101", "#102"]),
              mk_task("T2", "P2", 1200, beam="WB1", allowed=["#101", "#102"])])
    a = _r(sc)
    c = _r(sc, beam_enabled=False)
    assert c["kpi"]["scheduled_quantity"] >= a["kpi"]["scheduled_quantity"] - 1e-6


# 10) 增加候选织机后，最小未排数量不应增加
def test_more_candidates_not_more_unscheduled():
    # simulation 模式给出更多候选织机(放宽缺失能力) -> 未排不应更多
    sc = _sc([mk_product("P1")], [mk_loom("#101", current=None, edge=None, reed=None),
                                 mk_loom("#102")],
             [mk_task("T1", "P1", 1500, due_minute=50000)])
    b = _r(sc, compatibility_mode="balanced", recompute_allowed=True)
    s = _r(sc, compatibility_mode="simulation", recompute_allowed=True)
    assert s["kpi"]["unscheduled_quantity"] <= b["kpi"]["unscheduled_quantity"] + 1e-6


# 11) strict/balanced/simulation 符合定义（覆盖率与候选机台数单调）
def test_modes_strict_balanced_simulation():
    sc = _sc([mk_product("P1")],
             [mk_loom("#101", reed=None), mk_loom("#102", reed="9.3钢筘")],
             [mk_task("T1", "P1", 1500, due_minute=50000)])
    res = {m: _r(sc, compatibility_mode=m, recompute_allowed=True)
           for m in ("strict", "balanced", "simulation")}
    cand = {m: res[m]["diagnostics"]["candidate_loom_count"] for m in res}
    cov = {m: res[m]["kpi"]["demand_coverage_rate"] for m in res}
    assert cand["strict"] <= cand["balanced"] <= cand["simulation"], "候选机台数应单调不减"
    assert cov["strict"] <= cov["balanced"] + 1e-6


# 12) solver_status 与 business_status 互不混淆
def test_status_not_confused():
    # INFEASIBLE(锁定冲突) -> business NOT_EXECUTABLE
    sc = _sc([mk_product("P1"), mk_product("P2")], [mk_loom("#101")],
             [mk_task("T1", "P1", 1000, due_minute=50000, locked=True, lock_machine="#101",
                      lock_start=1000, lock_end=5000, lock_qty=1000, lock_reason="r"),
              mk_task("T2", "P2", 1000, due_minute=50000, locked=True, lock_machine="#101",
                      lock_start=3000, lock_end=7000, lock_qty=1000, lock_reason="r")])
    sc.规则配置 = {}
    r = _r(sc)
    assert r["status"] == "INFEASIBLE"
    assert r["business_status"] == "NOT_EXECUTABLE"
    # 高未排 -> solver 可行但 business HIGH_RISK
    r2 = _r(_sc([mk_product("P1")], [mk_loom("#101")],
                [mk_task("T1", "P1", 30000, due_minute=50000)]), max_time=4.0)
    assert r2["status"] in ("OPTIMAL", "FEASIBLE")
    assert r2["business_status"] in ("PARTIAL", "HIGH_RISK")


# 13) 每层固定后，后续优化不破坏上一层最优值（用 L1 校验）
def test_layers_preserve_previous_optimum():
    r = _r(_sc([mk_product("P1"), mk_product("P2")],
               [mk_loom("#101"), mk_loom("#102")],
               [mk_task("T1", "P1", 1200, due_minute=50000, allowed=["#101", "#102"]),
                mk_task("T2", "P2", 1200, due_minute=50000, allowed=["#101", "#102"])]))
    l1 = next(x for x in r["objective_levels"] if x["name"] == "unscheduled_quantity")
    assert abs(r["kpi"]["unscheduled_quantity"] - l1["best_value"]) <= 1e-6


# 14) 同输入、同参数、单线程下可复现
def test_reproducible():
    def run():
        return _r(_sc([mk_product("P1")], [mk_loom("#101"), mk_loom("#102")],
                      [mk_task("T1", "P1", 1500, due_minute=50000, allowed=["#101", "#102"])]))
    a, b = run(), run()
    assert a["assignments"] == b["assignments"]
    assert a["kpi"] == b["kpi"]


# 15) 不存在超出排程周期的非法任务
def test_no_out_of_horizon_tasks():
    sc = _sc([mk_product("P1"), mk_product("P2")], [mk_loom("#101")],
             [mk_task("T1", "P1", 1000, due_minute=50000),
              mk_task("T2", "P2", 1000, due_minute=50000)])
    r = _r(sc)
    horizon = prep.horizon_minutes(sc, BUSINESS_RULES)
    for a in r["assignments"]:
        assert 0 <= a["start_minute"] <= horizon, "任务起点超出排程周期"
        assert a["end_minute"] <= horizon, "任务终点超出排程周期"


# 16) 关闭更多硬约束后，第一层最优未排数量不能增加
def test_disable_more_constraints_not_increase_layer1_optimum():
    sc = _sc([mk_product("P1", consump=0.63)], [mk_loom("#101")],
             [mk_task("T1", "P1", 3000, due_minute=50000, split=True, min_batch=500, parts=2)],
             materials=[mk_material("LS7056AB", avail=1000)])
    a = _r(sc, max_layers=1)
    b = _r(sc, material_enabled=False, max_layers=1)
    d = _r(sc, material_enabled=False, beam_enabled=False, max_layers=1)
    # 关更多约束 -> 第一层最小未排不应增加（可行域更大）
    assert b["kpi"]["unscheduled_quantity"] <= a["kpi"]["unscheduled_quantity"] + 1e-6
    assert d["kpi"]["unscheduled_quantity"] <= b["kpi"]["unscheduled_quantity"] + 1e-6


# 17) 相同输入重复求解，第一层最优未排数量必须一致
def test_repeat_solve_layer1_consistent():
    def l1():
        sc = _sc([mk_product("P1")], [mk_loom("#101"), mk_loom("#102")],
                 [mk_task("T1", "P1", 2000, due_minute=50000, allowed=["#101", "#102"])])
        return _r(sc, max_layers=1)
    a, b = l1(), l1()
    la = next(x for x in a["objective_levels"] if x["name"] == "unscheduled_quantity")
    lb = next(x for x in b["objective_levels"] if x["name"] == "unscheduled_quantity")
    assert la["best_value"] == lb["best_value"], "重复求解第一层最优未排应一致"
    assert abs(a["kpi"]["unscheduled_quantity"] - b["kpi"]["unscheduled_quantity"]) < 1e-6


# 18) 完整八层求解的第一层结果不得差于单层最优
def test_full_layers_result_not_worse_than_single_layer():
    sc = _sc([mk_product("P1")], [mk_loom("#101"), mk_loom("#102")],
             [mk_task("T1", "P1", 2500, due_minute=50000, allowed=["#101", "#102"]),
              mk_task("T2", "P1", 2500, due_minute=50000, allowed=["#101", "#102"])])
    single = _r(sc, max_layers=1)
    full = _r(sc)
    assert full["kpi"]["unscheduled_quantity"] <= single["kpi"]["unscheduled_quantity"] + 1e-6, \
        "完整八层第一层结果不得差于已证明最优的单层结果"


# 19) L8 最大化目标符号归一化：OPTIMAL 时 gap=0，best_value 与 best_bound 同号同单位
def test_utilization_layer_symbol_normalized():
    sc = _sc([mk_product("P1")], [mk_loom("#101")],
             [mk_task("T1", "P1", 1000, due_minute=50000)])
    r8 = _r(sc)
    util = next((x for x in r8["objective_levels"] if x["name"] == "utilization"), None)
    assert util is not None
    assert util["best_value"] >= 0, "利用率 best_value 应为非负(同向)"
    assert util["best_bound"] >= 0, "利用率 best_bound 应为非负(同向同一单位)"
    if util["status"] == "OPTIMAL":
        assert util["gap"] == 0, "OPTIMAL 时 gap 必须为 0"
        assert abs(util["best_value"] - util["best_bound"]) <= 1e-6, "OPTIMAL 时 best_value 与 best_bound 一致"


# 20) 结果包含追溯字段(provenance)
def test_provenance_present():
    sc = _sc([mk_product("P1")], [mk_loom("#101")],
             [mk_task("T1", "P1", 1000, due_minute=50000)])
    r = _r(sc, max_layers=1)
    p = r["provenance"]
    for key in ("scenario_id", "data_snapshot_hash", "schedule_id", "schedule_start", "schedule_end",
                "horizon_minutes", "compatibility_mode", "material_enabled", "beam_enabled",
                "objective_layers", "per_layer_time_limit_s", "total_time_limit_s",
                "task_count", "required_quantity", "config_version", "code_version"):
        assert key in p, f"provenance 缺 {key}"
    assert p["data_snapshot_hash"]
    assert p["task_count"] == 1


# 21) 归一化贯穿全部目标层：OPTIMAL 时 gap=0 且 best_value==best_bound（含 L5 回归）
def test_all_objective_layers_normalization():
    sc = _sc([mk_product("P1"), mk_product("P2")],
             [mk_loom("#101"), mk_loom("#102")],
             [mk_task("T1", "P1", 1500, due_minute=50000, allowed=["#101", "#102"]),
              mk_task("T2", "P2", 1500, due_minute=50000, allowed=["#101", "#102"])])
    r = _r(sc)
    assert len(r["objective_levels"]) == 8, "必须遍历全部 8 层"
    assert r["diagnostics_consistent"] is True
    for lv in r["objective_levels"]:
        if lv["status"] == "OPTIMAL":
            assert lv["gap"] == 0, f"L{lv['level']} OPTIMAL 时 gap 必须为 0"
            assert abs(lv["best_value"] - lv["best_bound"]) <= 1e-6, \
                f"L{lv['level']} OPTIMAL 时 best_value 与 best_bound 必须一致(方向/单位统一)"
        else:
            assert lv["gap"] in (None, 0.0) or (lv["gap"] is not None and lv["gap"] >= 0), \
                f"L{lv['level']} gap 不能为负数"
    # L5(machine_spread_count)与 L8(utilization)必须存在且不产生矛盾的 gap/bound
    l5 = next(lv for lv in r["objective_levels"] if lv["name"] == "machine_spread_count")
    l8 = next(lv for lv in r["objective_levels"] if lv["name"] == "utilization")
    assert l5["best_value"] is not None
    assert l8["best_value"] >= 0
    assert l8["best_bound"] is None or l8["best_bound"] >= 0


# 22) 相同快照+参数重复求解，L1–L8 全部一致（单线程+固定种子）
def test_repeat_all_layers_consistent():
    def run():
        sc = _sc([mk_product("P1")], [mk_loom("#101"), mk_loom("#102")],
                 [mk_task("T1", "P1", 2000, due_minute=50000, allowed=["#101", "#102"])])
        return _r(sc)
    a, b = run(), run()
    for la, lb in zip(a["objective_levels"], b["objective_levels"]):
        assert la["best_value"] == lb["best_value"], f"L{la['level']} 重复求解应一致"
        assert la["raw_status"] == lb["raw_status"], f"L{la['level']} 状态应一致"


# 23) 更长时间不能在两次都声称 OPTIMAL 的情况下得到更差的 L5
def test_longer_time_not_worse_when_both_optimal():
    sc = _sc([mk_product("P1"), mk_product("P2")],
             [mk_loom("#101"), mk_loom("#102")],
             [mk_task("T1", "P1", 1500, due_minute=50000, allowed=["#101", "#102"]),
              mk_task("T2", "P2", 1500, due_minute=50000, allowed=["#101", "#102"])])
    short = _r(sc, max_time=3.0)
    long = _r(sc, max_time=8.0)
    l5s = next(x for x in short["objective_levels"] if x["name"] == "machine_spread_count")
    l5l = next(x for x in long["objective_levels"] if x["name"] == "machine_spread_count")
    # 若两者都声称 L5 已证明最优(consistent 且 OPTIMAL)，则更长时间不应更差
    if l5s["status"] == "OPTIMAL" and l5l["status"] == "OPTIMAL":
        assert l5l["best_value"] <= l5s["best_value"], "更长时间得不到更差的最优 L5"


# 24) 真实耗时受限：请求 3 秒，总后端耗时不应明显超过 3 秒
def test_actual_wall_time_bounded():
    sc = _sc([mk_product("P1")], [mk_loom("#101")],
             [mk_task("T1", "P1", 1000, due_minute=50000)])
    import time
    t0 = time.monotonic()
    r = _r(sc, max_time=3.0)
    wall = time.monotonic() - t0
    assert wall < 8.0, f"3 秒请求真实耗时 {wall:.1f}s 明显过高"
    assert r["model_stats"]["requested_time_limit_s"] == 3.0
