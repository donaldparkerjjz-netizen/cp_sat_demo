from weaving_demo.tests.builders import mk_task
from weaving_demo.weekly_warping import build_weekly_warping_plan, align_warping_plan_to_weaving


def test_weekly_warping_plan_uses_seven_days_and_serial_pool():
    dataset = {
        "reconciliation": {"product_rows": [{"product_id": "P1", "warp_beam_sku": "WP1"}]},
        "beams": {"WP1": {"set_length": 3600, "warp_plan_m": {}}},
        "beam_to_looms": {"WP1": ["LOOM-101"]},
    }
    result = build_weekly_warping_plan(dataset, [mk_task("T1", "P1", 7200)], "2026-04-01")
    assert result["horizon_days"] == 7
    assert len(result["daily"]) == 7
    assert len(result["tasks"]) == 2
    assert result["tasks"][0]["start"] == "2026-04-01T00:00:00"
    assert result["tasks"][1]["start"] == result["tasks"][0]["end"]
    assert result["stats"]["plan_meters"] == 7200


def test_weekly_warping_plan_keeps_unmapped_product_blocked():
    dataset = {"reconciliation": {"product_rows": []}, "beams": {}, "beam_to_looms": {}}
    result = build_weekly_warping_plan(dataset, [mk_task("T1", "P1", 7200)], "2026-04-01")
    assert result["tasks"] == []
    assert result["blocked_products"] == ["P1"]


def test_weekly_warping_plan_prioritizes_order_due_then_priority():
    dataset = {
        "reconciliation": {"product_rows": [
            {"product_id": "P-LATE", "warp_beam_sku": "WP-L"},
            {"product_id": "P-HIGH", "warp_beam_sku": "WP-H"},
            {"product_id": "P-LOW", "warp_beam_sku": "WP-N"},
        ]},
        "beams": {code: {"set_length": 3600, "warp_plan_m": {}}
                  for code in ("WP-L", "WP-H", "WP-N")},
        "beam_to_looms": {},
    }
    tasks = [
        mk_task("T-L", "P-LATE", 100, due_minute=3000, priority=9),
        mk_task("T-N", "P-LOW", 100, due_minute=1000, priority=1),
        mk_task("T-H", "P-HIGH", 100, due_minute=1000, priority=5),
    ]
    result = build_weekly_warping_plan(dataset, tasks, "2026-04-01")
    assert [row["warp_beam_sku"] for row in result["tasks"]] == ["WP-H", "WP-N", "WP-L"]
    assert result["tasks"][0]["planning_basis"].startswith("订单交期优先")


def test_rule_optimization_keeps_only_beams_driven_by_selected_weaving():
    dataset = {
        "reconciliation": {"product_rows": [
            {"product_id": "P1", "warp_beam_sku": "WP1"},
            {"product_id": "P2", "warp_beam_sku": "WP2"},
        ]},
        "beams": {
            "WP1": {"set_length": 3600, "warp_plan_m": {}},
            "WP2": {"set_length": 4500, "warp_plan_m": {}},
        },
        "beam_to_looms": {},
    }
    tasks = [mk_task("T1", "P1", 7200), mk_task("T2", "P2", 9000)]
    source = build_weekly_warping_plan(dataset, tasks, "2026-04-01")
    aligned = align_warping_plan_to_weaving(
        source,
        [{"task_id": "T2", "product_id": "P2", "scheduled_quantity": 800}],
        tasks,
        dataset,
    )

    assert aligned["planning_mode"] == "weaving_pull"
    assert len(aligned["tasks"]) == 1
    assert aligned["tasks"][0]["warp_beam_sku"] == "WP2"
    assert aligned["tasks"][0]["plan_meters"] == 4500
    assert aligned["alignment"]["removed_task_count"] == 3
    assert aligned["alignment"]["driving_weaving_meters"] == 800
