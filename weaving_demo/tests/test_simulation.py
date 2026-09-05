# -*- coding: utf-8 -*-
from weaving_demo.run_simulation import build_demo_scenario
from weaving_demo.tests.builders import mk_loom, mk_product, mk_scenario, mk_task
from weaving_demo.simulation import (
    BEAM_JOINING,
    CHANGE_STYLE_SETUP,
    DIRECT_CONTINUE,
    ORIGINAL_STYLE_SETUP,
    LoomRuntimeState,
    SimulationConfig,
    classify_setup,
    run_schedule_simulation,
)


def test_classify_four_setup_modes():
    cfg = SimulationConfig(edge_support_use_limit=5)
    assert classify_setup(LoomRuntimeState("L", "P", "B", 100, 4), "P", cfg) == DIRECT_CONTINUE
    assert classify_setup(LoomRuntimeState("L", "P", None, 0, 4), "P", cfg) == BEAM_JOINING
    assert classify_setup(LoomRuntimeState("L", "P", None, 0, 5), "P", cfg) == ORIGINAL_STYLE_SETUP
    assert classify_setup(LoomRuntimeState("L", "P1", None, 0, 2), "P2", cfg) == CHANGE_STYLE_SETUP


def test_demo_simulation_covers_flowchart_and_reconciles():
    scenario, states = build_demo_scenario()
    result = run_schedule_simulation(
        scenario,
        runtime_states=states,
        config=SimulationConfig(cp_sat_time_limit_s=5.0),
    )
    assert result["status"] == "SIMULATED"
    assert result["validation"]["ok"]
    counts = result["kpi"]["setup_type_counts"]
    assert counts[DIRECT_CONTINUE] >= 1
    assert counts[BEAM_JOINING] >= 1
    assert counts[ORIGINAL_STYLE_SETUP] >= 1
    assert counts[CHANGE_STYLE_SETUP] >= 1
    assert result["kpi"]["warping_task_count"] >= 1
    assert result["kpi"]["threading_task_count"] >= 1
    assert [x["cutoff_minutes"] for x in result["forecasts"]] == [1440, 2880]


def test_fault_window_has_no_loom_overlap():
    scenario, states = build_demo_scenario(with_fault=True)
    result = run_schedule_simulation(
        scenario,
        runtime_states=states,
        config=SimulationConfig(cp_sat_time_limit_s=5.0),
    )
    assert result["validation"]["ok"]
    fault = next(e for e in result["events"] if e["event_type"] == "downtime")
    for event in result["events"]:
        if event.get("loom_id") != fault["loom_id"] or event["event_type"] == "downtime":
            continue
        assert event["end_minute"] <= fault["start_minute"] or event["start_minute"] >= fault["end_minute"]


def _ledger_scenario(qty=200, beam_code="WP1"):
    task = mk_task("T1", "P1", qty, beam=beam_code, allowed=["#101"])
    return mk_scenario(
        products=[mk_product("P1", effic=400, beam=beam_code)],
        looms=[mk_loom("#101", current="OLD")],
        tasks=[task],
        start="2026-04-01", end="2026-04-08",
    )


def _ledger_result(qty=200, *, beam_code="WP1", with_beam=True):
    warp_tasks = []
    instances = []
    if with_beam:
        warp_tasks = [{
            "task_id": "WARP-WEEK-WP1-01", "warp_beam_sku": beam_code,
            "product_ids": ["P1"], "start": "2026-04-01T00:00:00",
            "end": "2026-04-01T04:00:00", "complete_at": "2026-04-01T04:00:00",
            "plan_meters": 3600, "target_loom_id": ["LOOM-101"],
            "machine_placeholder": "整经计划池", "beam_instance_id": "BEAM-WP1-001",
        }]
        instances = [{
            "beam_instance_id": "BEAM-WP1-001", "warp_beam_sku": beam_code,
            "total_meters": 3600, "remaining_meters": 3600, "available_minute": 240,
            "available_at": "2026-04-01T04:00:00", "source_task_id": "WARP-WEEK-WP1-01",
            "target_loom_ids": ["LOOM-101"], "status": "整经完成待上轴",
            "data_source": "一周整经任务推导", "allocations": [],
        }]
    return {
        "status": "FEASIBLE", "schedule_id": "sch-ledger",
        "kpi": {"horizon_days": 7, "scheduled_quantity": float(qty)},
        "assignments": [{
            "task_id": "T1", "product_id": "P1", "loom_id": "#101",
            "scheduled_quantity": float(qty), "start_minute": 0, "end_minute": 10080,
        }],
        "warping_plan": {"tasks": warp_tasks},
        "beam_ledger": {"instances": instances},
    }


def test_weekly_simulation_uses_same_warping_plan_and_specific_beam():
    scenario = _ledger_scenario()
    result = run_schedule_simulation(
        scenario,
        runtime_states={"#101": LoomRuntimeState("#101", "OLD")},
        solve_result=_ledger_result(),
    )

    assert result["validation"]["ok"]
    assert result["warping_plan_source"] == "solve_result.warping_plan"
    assert [e["task_id"] for e in result["warping_plan"]] == ["WARP-WEEK-WP1-01"]
    weave = result["weaving_plan"][0]
    assert weave["beam_id"] == "BEAM-WP1-001"
    assert weave["beam_source_task_id"] == "WARP-WEEK-WP1-01"
    assert weave["beam_ready_minute"] <= weave["required_ready_by_minute"]
    assert weave["end_minute"] <= 10080
    trace = result["planning_trace"]
    assert [stage["label"] for stage in trace["stages"]] == [
        "订单需求", "织造初排", "逐轴拆分", "整经反排", "穿综与备轴", "可执行织造",
    ]
    decision = trace["decisions"][0]
    assert decision["beam_ids"] == ["BEAM-WP1-001"]
    assert decision["lead_time_ok"]
    assert decision["reduced_quantity"] == 0


def test_single_beam_can_continue_weaving_through_april_6_without_new_warping():
    """一根轴余量足够时，4月6日允许续织，不能重复整经或换成无来源轴。"""
    qty = 2000
    result = run_schedule_simulation(
        _ledger_scenario(qty),
        runtime_states={"#101": LoomRuntimeState("#101", "OLD")},
        solve_result=_ledger_result(qty),
    )

    assert result["validation"]["ok"]
    assert result["kpi"]["simulated_quantity"] == qty
    assert result["kpi"]["reduced_quantity"] == 0
    assert result["kpi"]["supplemental_warping_count"] == 0
    assert len(result["warping_plan"]) == 1
    assert result["warping_plan"][0]["end_minute"] == 240

    weave = result["weaving_plan"][0]
    assert weave["beam_id"] == "BEAM-WP1-001"
    assert weave["quantity"] == qty
    assert weave["start_minute"] < 5 * 1440
    assert weave["end_minute"] > 5 * 1440  # 跨入 4 月 6 日
    assert weave["end_minute"] <= 7 * 1440
    assert weave["beam_initial_meters"] >= weave["quantity"]


def test_weekly_simulation_reduces_quantity_instead_of_crossing_horizon():
    qty = 3000
    result = run_schedule_simulation(
        _ledger_scenario(qty),
        runtime_states={"#101": LoomRuntimeState("#101", "OLD")},
        solve_result=_ledger_result(qty),
    )

    assert result["status"] == "SIMULATED_ADJUSTED"
    assert 0 < result["kpi"]["reduced_quantity"] < qty
    assert result["kpi"]["simulated_quantity"] + result["kpi"]["reduced_quantity"] == qty
    assert result["kpi"]["over_horizon_event_count"] == 0
    assert all(event["end_minute"] <= 10080 for event in result["events"])
    assert result["validation"]["ok"]


def test_weekly_simulation_unmapped_shortage_does_not_invent_beam():
    qty = 600
    result = run_schedule_simulation(
        _ledger_scenario(qty, beam_code="UNMAPPED-P1"),
        runtime_states={"#101": LoomRuntimeState("#101", "OLD")},
        solve_result=_ledger_result(qty, beam_code="UNMAPPED-P1", with_beam=False),
    )

    assert result["kpi"]["simulated_quantity"] == 0
    assert result["kpi"]["reduced_quantity"] == qty
    assert result["kpi"]["supplemental_warping_count"] == 0
    assert not any(str(event.get("beam_id", "")).startswith("SIM-") for event in result["events"])


def test_weekly_simulation_can_explicitly_append_supplemental_warping():
    qty = 200
    result = run_schedule_simulation(
        _ledger_scenario(qty),
        runtime_states={"#101": LoomRuntimeState("#101", "OLD")},
        solve_result=_ledger_result(qty, with_beam=False),
    )

    assert result["kpi"]["supplemental_warping_count"] == 1
    assert result["weaving_plan"][0]["beam_origin"] == "supplemental_warping"
    assert result["warping_plan"][0]["data_source"] == "simulation_supplement"
    assert result["validation"]["ok"]


def test_weekly_unmounted_beam_target_is_advisory_and_can_weave_on_day_one():
    solve_result = _ledger_result()
    solve_result["beam_ledger"]["instances"][0]["target_loom_ids"] = ["LOOM-999"]

    result = run_schedule_simulation(
        _ledger_scenario(),
        runtime_states={"#101": LoomRuntimeState("#101", "OLD")},
        solve_result=solve_result,
    )

    weave = result["weaving_plan"][0]
    assert weave["beam_id"] == "BEAM-WP1-001"
    assert weave["beam_origin"] == "weekly_warping_plan"
    assert weave["start_minute"] < 1440
    assert result["kpi"]["supplemental_warping_count"] == 0
    assert result["validation"]["ok"]


def test_weekly_simulation_dispatches_earlier_ready_beam_before_late_beam():
    early_task = mk_task("T-EARLY", "P-EARLY", 100, beam="WP-E", allowed=["#102"])
    late_task = mk_task("T-LATE", "P-LATE", 100, beam="WP-L", allowed=["#101"])
    scenario = mk_scenario(
        products=[mk_product("P-EARLY", effic=400, beam="WP-E"),
                  mk_product("P-LATE", effic=400, beam="WP-L")],
        looms=[mk_loom("#101", current="OLD"), mk_loom("#102", current="OLD")],
        tasks=[early_task, late_task], start="2026-04-01", end="2026-04-08",
    )
    solve_result = {
        "status": "FEASIBLE", "schedule_id": "sch-dispatch",
        "kpi": {"horizon_days": 7, "scheduled_quantity": 200.0},
        "assignments": [
            {"task_id": "T-LATE", "product_id": "P-LATE", "loom_id": "#101",
             "scheduled_quantity": 100.0, "start_minute": 0, "end_minute": 10080},
            {"task_id": "T-EARLY", "product_id": "P-EARLY", "loom_id": "#102",
             "scheduled_quantity": 100.0, "start_minute": 0, "end_minute": 10080},
        ],
        "warping_plan": {"tasks": [
            {"task_id": "W-E", "warp_beam_sku": "WP-E", "product_ids": ["P-EARLY"],
             "start": "2026-04-01T00:00:00", "complete_at": "2026-04-01T04:00:00",
             "plan_meters": 3600, "machine_placeholder": "整经计划池", "beam_instance_id": "B-E"},
            {"task_id": "W-L", "warp_beam_sku": "WP-L", "product_ids": ["P-LATE"],
             "start": "2026-04-03T00:00:00", "complete_at": "2026-04-03T04:00:00",
             "plan_meters": 3600, "machine_placeholder": "整经计划池", "beam_instance_id": "B-L"},
        ]},
        "beam_ledger": {"instances": [
            {"beam_instance_id": "B-E", "warp_beam_sku": "WP-E", "remaining_meters": 3600,
             "available_minute": 240, "source_task_id": "W-E", "target_loom_ids": ["LOOM-102"],
             "data_source": "一周整经任务推导", "allocations": []},
            {"beam_instance_id": "B-L", "warp_beam_sku": "WP-L", "remaining_meters": 3600,
             "available_minute": 3120, "source_task_id": "W-L", "target_loom_ids": ["LOOM-101"],
             "data_source": "一周整经任务推导", "allocations": []},
        ]},
    }

    result = run_schedule_simulation(
        scenario,
        runtime_states={"#101": LoomRuntimeState("#101", "OLD"),
                        "#102": LoomRuntimeState("#102", "OLD")},
        solve_result=solve_result,
    )

    by_task = {row["task_id"]: row for row in result["weaving_plan"]}
    assert by_task["T-EARLY"]["start_minute"] < 1440
    assert by_task["T-EARLY"]["start_minute"] < by_task["T-LATE"]["start_minute"]
    assert result["validation"]["ok"]
