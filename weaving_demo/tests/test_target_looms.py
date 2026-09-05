# -*- coding: utf-8 -*-
"""来源目标织机映射与硬约束回归测试。"""
from weaving_demo import prep
from weaving_demo.api.service import (
    _apply_source_target_looms,
    _build_target_loom_audit,
    _build_weekly_beam_ledger,
)
from weaving_demo.config import BUSINESS_RULES
from weaving_demo.tests.builders import mk_loom, mk_product, mk_scenario, mk_task


def _dataset(targets):
    return {
        "reconciliation": {
            "product_rows": [
                {"product_id": "P1", "target_loom_ids": targets},
            ]
        }
    }


def test_balanced_intersects_source_targets_with_compatible_looms():
    product = mk_product("P1")
    task = mk_task("T1", "P1", 1000)
    scenario = mk_scenario(
        products=[product],
        looms=[mk_loom("#501"), mk_loom("#502")],
        tasks=[task],
    )

    mapping = _apply_source_target_looms(scenario, [task], _dataset(["LOOM-502"]), "balanced")
    tasks = prep.build_tasks(scenario, BUSINESS_RULES, mode="balanced", recompute_allowed=True)

    assert mapping["mapped_task_count"] == 1
    assert task.source_target_loom_ids == ["#502"]
    assert tasks[0].allowed_loom_ids == ["#502"]


def test_balanced_missing_mapping_is_trial_but_strict_is_blocked():
    for mode, expected_status, expected_allowed in (
        ("balanced", "missing_trial", ["#501"]),
        ("strict", "missing_blocked", []),
    ):
        product = mk_product("P1")
        task = mk_task("T1", "P1", 1000)
        scenario = mk_scenario(products=[product], looms=[mk_loom("#501")], tasks=[task])

        _apply_source_target_looms(scenario, [task], _dataset([]), mode)
        tasks = prep.build_tasks(scenario, BUSINESS_RULES, mode=mode, recompute_allowed=True)

        assert task.target_mapping_status == expected_status
        assert tasks[0].allowed_loom_ids == expected_allowed


def test_simulation_records_target_without_restricting_trial_assignment():
    product = mk_product("P1")
    task = mk_task("T1", "P1", 1000)
    scenario = mk_scenario(
        products=[product],
        looms=[mk_loom("#501"), mk_loom("#502")],
        tasks=[task],
    )

    _apply_source_target_looms(scenario, [task], _dataset(["LOOM-502"]), "simulation")
    tasks = prep.build_tasks(scenario, BUSINESS_RULES, mode="simulation", recompute_allowed=True)

    assert task.source_target_loom_ids == ["#502"]
    assert set(tasks[0].allowed_loom_ids) == {"#501", "#502"}


def test_target_audit_flags_outside_and_missing_assignments():
    mapping = {"mode": "balanced", "products": {}}
    payload = {
        "assignments": [
            {"task_id": "T1", "product_id": "P1", "loom_id": "#502",
             "source_target_loom_ids": ["#502"]},
            {"task_id": "T2", "product_id": "P2", "loom_id": "#601",
             "source_target_loom_ids": ["#602"]},
            {"task_id": "T3", "product_id": "P3", "loom_id": "#603",
             "source_target_loom_ids": [], "target_mapping_status": "missing_trial"},
        ]
    }

    audit = _build_target_loom_audit(payload, mapping)

    assert audit["matched_assignment_count"] == 1
    assert audit["outside_target_count"] == 1
    assert audit["missing_target_assignment_count"] == 1
    assert audit["publishable"] is False


def test_weekly_beam_ledger_allocates_only_completed_physical_beams():
    payload = {
        "schedule_start": "2026-04-01T00:00:00",
        "assignments": [{"task_id": "T1", "product_id": "P1", "loom_id": "#501",
                         "start_minute": 300, "scheduled_quantity": 600}],
    }
    weekly = {"tasks": [
        {"task_id": "W1", "warp_beam_sku": "WP1", "plan_meters": 500,
         "complete_at": "2026-04-01T04:00:00", "target_loom_id": ["LOOM-501"]},
        {"task_id": "W2", "warp_beam_sku": "WP1", "plan_meters": 500,
         "complete_at": "2026-04-01T08:00:00", "target_loom_id": ["LOOM-501"]},
    ]}
    dataset = {
        "reconciliation": {"product_rows": [{"product_id": "P1", "warp_beam_sku": "WP1"}]},
        "beams": {"WP1": {"set_length": 500, "initial_inventory": None}},
        "beam_to_looms": {"WP1": ["LOOM-501"]},
    }

    ledger = _build_weekly_beam_ledger(payload, weekly, dataset)

    assert ledger["instance_count"] == 2
    assert ledger["allocated_meters"] == 500
    assert ledger["shortage_count"] == 1
    assert payload["assignments"][0]["beam_allocations"][0]["beam_instance_id"] == "BEAM-WP1-001"
    assert payload["assignments"][0]["beam_quantity_ok"] is False


def test_weekly_beam_ledger_reconciles_quantity_when_axes_are_ready():
    payload = {
        "schedule_start": "2026-04-01T00:00:00",
        "assignments": [{"task_id": "T1", "product_id": "P1", "loom_id": "#501",
                         "start_minute": 600, "scheduled_quantity": 600}],
    }
    weekly = {"tasks": [
        {"task_id": "W1", "warp_beam_sku": "WP1", "plan_meters": 500,
         "complete_at": "2026-04-01T04:00:00", "target_loom_id": []},
        {"task_id": "W2", "warp_beam_sku": "WP1", "plan_meters": 500,
         "complete_at": "2026-04-01T08:00:00", "target_loom_id": []},
    ]}
    dataset = {
        "reconciliation": {"product_rows": [{"product_id": "P1", "warp_beam_sku": "WP1"}]},
        "beams": {"WP1": {"set_length": 500}},
    }

    ledger = _build_weekly_beam_ledger(payload, weekly, dataset)

    assert ledger["quantity_ok"] is True
    assert ledger["allocated_meters"] == 600
    assert len(payload["assignments"][0]["beam_allocations"]) == 2
    assert payload["assignments"][0]["beam_quantity_ok"] is True
