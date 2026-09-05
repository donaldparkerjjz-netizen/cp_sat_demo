# -*- coding: utf-8 -*-
"""test_process.py -- 工艺流程可视化 后端测试。"""
from weaving_demo import process as pm
from weaving_demo.tests.builders import mk_product, mk_loom, mk_task, mk_scenario, mk_material
from weaving_demo.config import BUSINESS_RULES
from weaving_demo.solver import solve


def _result():
    sc = mk_scenario(
        [mk_product("P1", consump=0.63), mk_product("P2")],
        [mk_loom("#101")],
        [mk_task("T1", "P1", 3000, due_minute=50000, split=True, min_batch=500, parts=2),
         mk_task("T2", "P2", 3000, due_minute=50000)],
        materials=[mk_material("LS7056AB", avail=1000)],
    )
    sc.规则配置 = BUSINESS_RULES
    from weaving_demo import prep
    sc.生产任务 = prep.build_tasks(sc, BUSINESS_RULES)
    sc.虚拟经轴 = prep.create_virtual_beams(sc, sc.生产任务, BUSINESS_RULES)
    return solve(sc, max_time_s=5.0, config=BUSINESS_RULES)


def test_process_overview_steps():
    r = _result()
    ov = pm.process_overview(None, r)
    assert len(ov["flow"]) >= 10
    assert ov["statuses"] == ["未开始", "等待条件", "已排程", "部分已排", "进行中", "已完成", "已跳过", "异常阻塞"]
    assert len(ov["branch_notes"]) >= 5
    c0 = ov["flow"][0]
    for k in ("process", "pending_count", "in_progress_count", "completed_count",
              "anomaly_count", "quantity", "main_risk"):
        assert k in c0


def test_assign_process_states_fields():
    r = _result()
    tasks = pm.assign_process_states(None, r)
    assert len(tasks) == 2
    for k in ("task_id", "order_id", "product_id", "required_quantity", "current_process",
              "current_status", "completed_processes", "next_process", "blocked_reason",
              "data_source"):
        assert k in tasks[0], f"缺字段 {k}"
    # 未排任务若物料不足应停在原料库存检查并标记缺料
    mat_blocked = [t for t in tasks if t["blocked_reason"].startswith("物料")]
    assert any(t["current_process"] == "原料库存检查" and t["current_status"] == "异常阻塞" for t in mat_blocked)
    # 织造已排程只是计划结果，不能反推整经、上轴等工序已经实际完成
    weave_planned = [t for t in tasks if t["current_process"] == "织造生产" and t["scheduled_quantity"] > 0]
    assert weave_planned
    assert all(t["current_status"] in ("已排程", "部分已排") for t in weave_planned)
    assert all("整经生产" not in t["completed_processes"] for t in weave_planned)
    assert all("上轴" not in t["completed_processes"] for t in weave_planned)


def test_warping_summary_does_not_turn_weave_tasks_into_warping_completed():
    r = _result()
    ov = pm.process_overview(None, r, {
        "warp_task_count": 5,
        "warp_plan_meters": 38450,
        "virtual_beam_count": 7,
        "instance_meters": 38450,
    })
    by_name = {p["process"]: p for p in ov["flow"]}
    assert by_name["整经生产"]["pending_count"] == 5
    assert by_name["整经生产"]["completed_count"] == 0
    assert by_name["经轴准备"]["pending_count"] == 7
    assert by_name["织造生产"]["pending_count"] + by_name["织造生产"]["in_progress_count"] > 0


def test_homepage_progress():
    r = _result()
    p = pm.homepage_progress(None, r)
    for k in ("required_qty", "material_ready_qty", "beam_ready_qty", "weave_scheduled_qty",
              "weave_done_qty", "finishing_qty", "stocked_qty"):
        assert k in p


def test_demonstration_cases():
    r = _result()
    cases = pm.demonstration_cases(None, r)
    assert len(cases) >= 5
    assert cases[0]["label"] == "已进入织造排程的任务"
    assert all(c["label"] != "正常完成全部流程" for c in cases)
