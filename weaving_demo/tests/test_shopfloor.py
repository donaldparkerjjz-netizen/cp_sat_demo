# -*- coding: utf-8 -*-
import pytest

from weaving_demo.shopfloor import (
    ShopFloorSnapshotStore,
    build_default_snapshot,
    build_simulated_snapshot,
    final_snapshot_from_simulation,
    merge_snapshot,
    runtime_states_from_snapshot,
)
from weaving_demo.api import service
from weaving_demo.api.store import STORE
from weaving_demo.tests.builders import mk_loom, mk_product, mk_scenario


def test_simulated_snapshot_is_deterministic_and_operationally_varied():
    products = [mk_product("P1")]
    looms = [mk_loom(f"#{100 + index}", current="P1") for index in range(1, 13)]
    looms.append(mk_loom("#201"))
    looms.append(mk_loom("#202", status="NULL"))
    scenario = mk_scenario(products=products, looms=looms, start="2026-05-18")

    first = build_simulated_snapshot(scenario, seed=20260604)
    second = build_simulated_snapshot(scenario, seed=20260604)

    assert first.to_dict() == second.to_dict()
    assert first.source == "simulated_seed"
    assert first.captured_at == "2026-05-18T08:00:00"
    assert first.metadata["data_source"] == "simulated"
    assert len(first.looms) == 14
    assert sum(loom.current_beam_id is not None for loom in first.looms) == 12
    assert sum(beam.location_type == "loom" for beam in first.beams) == 12
    assert sum(beam.location_type == "line_side" for beam in first.beams) == 1
    assert sum(event.event_type == "production_report" for event in first.events) == 12
    assert {"running", "fault", "material_shortage", "maintenance", "unavailable"} \
        <= {loom.status for loom in first.looms}
    assert any(loom.edge_support_uses == loom.edge_support_limit for loom in first.looms)
    assert all(beam.is_derived for beam in first.beams)


def test_partial_snapshot_update_creates_traceable_beam():
    scenario = mk_scenario(looms=[mk_loom("#101", current="P1"), mk_loom("#102")])
    seed = build_default_snapshot(scenario)
    snapshot = merge_snapshot(seed, {
        "source": "manual_test",
        "looms": [{
            "loom_id": "#101",
            "current_product_id": "P1",
            "current_beam_id": "REAL-BEAM-001",
            "remaining_beam_m": 850.0,
            "edge_support_uses": 4,
        }],
    }, scenario=scenario)

    assert snapshot.version == 1
    assert snapshot.parent_snapshot_id is None
    loom = next(row for row in snapshot.looms if row.loom_id == "#101")
    beam = next(row for row in snapshot.beams if row.beam_id == "REAL-BEAM-001")
    assert loom.remaining_beam_m == 850.0
    assert loom.edge_support_uses == 4
    assert beam.remaining_meters == 850.0
    assert beam.location_type == "loom"
    assert beam.is_derived is True


def test_snapshot_validation_rejects_negative_remaining_beam():
    scenario = mk_scenario(looms=[mk_loom("#101")])
    with pytest.raises(ValueError, match="余量不能为负数"):
        merge_snapshot(build_default_snapshot(scenario), {
            "looms": [{"loom_id": "#101", "remaining_beam_m": -1}],
        }, scenario=scenario)


def test_snapshot_store_persists_versions_and_rejects_stale_write(tmp_path):
    scenario = mk_scenario(looms=[mk_loom("#101")])
    store_path = tmp_path / "snapshots.json"
    store = ShopFloorSnapshotStore(store_path)
    first = merge_snapshot(build_default_snapshot(scenario), {
        "looms": [{"loom_id": "#101", "edge_support_uses": 2}],
    }, scenario=scenario)
    store.save(first, expected_version=0)

    reloaded = ShopFloorSnapshotStore(store_path)
    assert reloaded.latest().snapshot_id == first.snapshot_id
    assert reloaded.latest().version == 1

    second = merge_snapshot(reloaded.latest(), {
        "looms": [{"loom_id": "#101", "edge_support_uses": 3}],
    }, scenario=scenario)
    reloaded.save(second, expected_version=1)
    with pytest.raises(ValueError, match="版本冲突"):
        reloaded.save(second, expected_version=1)


def test_committed_final_snapshot_is_next_runtime_input(tmp_path):
    scenario = mk_scenario(looms=[mk_loom("#101", current="P1")])
    base = merge_snapshot(build_default_snapshot(scenario), {
        "looms": [{
            "loom_id": "#101",
            "current_product_id": "P1",
            "current_beam_id": "B-001",
            "remaining_beam_m": 1000,
            "edge_support_uses": 3,
        }],
    }, scenario=scenario)
    store = ShopFloorSnapshotStore(tmp_path / "snapshots.json")
    store.save(base, expected_version=0)

    result = {
        "status": "SIMULATED",
        "solver_schedule_id": "sch-1",
        "validation": {"ok": True},
        "kpi": {"simulated_quantity": 400},
        "final_runtime_states": {
            "#101": {
                "loom_id": "#101",
                "current_product_id": "P1",
                "current_beam_id": "B-001",
                "remaining_beam_m": 600,
                "edge_support_uses": 3,
                "available_minute": 1440,
            },
        },
    }
    final = final_snapshot_from_simulation(base, result, source="simulation_final")
    store.save(final, expected_version=1)

    next_input = runtime_states_from_snapshot(store.latest())
    assert store.latest().version == 2
    assert next_input["#101"].remaining_beam_m == 600
    assert next_input["#101"].current_beam_id == "B-001"
    assert next_input["#101"].available_minute == 1440


def test_weekly_simulation_preview_does_not_persist_but_commit_does(monkeypatch, tmp_path):
    scenario = mk_scenario(looms=[mk_loom("#101", current="P1")])
    snapshot_store = ShopFloorSnapshotStore(tmp_path / "shopfloor.json")
    base = merge_snapshot(build_default_snapshot(scenario), {
        "looms": [{
            "loom_id": "#101",
            "current_product_id": "P1",
            "current_beam_id": "B-001",
            "remaining_beam_m": 800,
            "edge_support_uses": 4,
        }],
    }, scenario=scenario)
    snapshot_store.save(base, expected_version=0)

    STORE._data.clear()
    STORE._latest_id = None
    STORE.save("sch-1", {
        "schedule_id": "sch-1",
        "status": "OPTIMAL",
        "schedule_start": "2026-04-01T00:00:00",
        "kpi": {"horizon_days": 7, "scheduled_quantity": 300},
        "params": {"compatibility_mode": "balanced"},
        "assignments": [],
    })
    captured = {}

    def fake_simulation(sc, runtime_states, config, solve_result):
        captured["remaining"] = runtime_states["#101"].remaining_beam_m
        return {
            "status": "SIMULATED",
            "schedule_start": "2026-04-01T00:00:00",
            "solver_schedule_id": "sch-1",
            "solver": {"status": "OPTIMAL"},
            "validation": {"ok": True},
            "kpi": {"simulated_quantity": 300},
            "final_runtime_states": {
                "#101": {
                    "loom_id": "#101",
                    "current_product_id": "P1",
                    "current_beam_id": "B-001",
                    "remaining_beam_m": 500,
                    "edge_support_uses": 4,
                    "available_minute": 720,
                },
            },
        }

    monkeypatch.setattr(service, "SHOPFLOOR_STORE", snapshot_store)
    monkeypatch.setattr(service, "load_scenario", lambda: scenario)
    monkeypatch.setattr(service, "_warping_dataset", lambda: {})
    monkeypatch.setattr(service, "_apply_source_target_looms", lambda *args: {})
    monkeypatch.setattr(service, "_apply_process_precedence", lambda *args, **kwargs: {})
    monkeypatch.setattr(service, "run_schedule_simulation", fake_simulation)

    preview = service.run_weekly_simulation({"schedule_id": "sch-1"})
    assert captured["remaining"] == 800
    assert preview["shopfloor_snapshot"]["committed"] is False
    assert snapshot_store.latest().version == 1

    committed = service.run_weekly_simulation({
        "schedule_id": "sch-1",
        "commit_final_state": True,
    })
    assert committed["shopfloor_snapshot"]["committed"] is True
    assert snapshot_store.latest().version == 2
    assert runtime_states_from_snapshot(snapshot_store.latest())["#101"].remaining_beam_m == 500
