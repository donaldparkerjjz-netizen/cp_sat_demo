from weaving_demo.weekly_weaving import build_weekly_weaving_plan


def test_weekly_weaving_plan_links_assignment_to_first_ready_beam():
    result = {
        "assignments": [{"task_id": "T1", "product_id": "P1", "beam_id": "WB-WP1-001",
                         "loom_id": "#101", "beam_ready_at": "2026-04-01T04:00:00",
                         "start": "2026-04-01T04:00:00", "end": "2026-04-03T00:00:00",
                         "scheduled_quantity": 700, "changeover_type": "beam_change"}],
        "kpi": {"unscheduled_quantity": 300},
    }
    warping = {"schedule_start": "2026-04-01", "horizon_days": 7,
               "tasks": [{"warp_beam_sku": "WP1", "complete_at": "2026-04-01T04:00:00"}]}
    dataset = {"reconciliation": {"product_rows": [{"product_id": "P1", "warp_beam_sku": "WP1"}]}}
    plan = build_weekly_weaving_plan(result, warping, dataset)
    assert plan["tasks"][0]["warp_beam_sku"] == "WP1"
    assert plan["tasks"][0]["order_ok"] is True
    assert plan["stats"]["scheduled_meters"] == 700
    assert plan["stats"]["order_violation_count"] == 0


def test_weekly_weaving_plan_reports_order_violation():
    result = {"assignments": [{"task_id": "T1", "product_id": "P1", "loom_id": "#101",
                               "start": "2026-04-01T03:00:00", "end": "2026-04-01T10:00:00",
                               "scheduled_quantity": 100}], "kpi": {}}
    warping = {"schedule_start": "2026-04-01", "horizon_days": 7,
               "tasks": [{"warp_beam_sku": "WP1", "complete_at": "2026-04-01T04:00:00"}]}
    dataset = {"reconciliation": {"product_rows": [{"product_id": "P1", "warp_beam_sku": "WP1"}]}}
    plan = build_weekly_weaving_plan(result, warping, dataset)
    assert plan["stats"]["order_violation_count"] == 1
