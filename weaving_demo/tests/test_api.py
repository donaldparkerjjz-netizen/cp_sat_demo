# -*- coding: utf-8 -*-
"""test_api.py -- 阶段3 后端 API 测试。"""
import base64
import json
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from weaving_demo.api.main import app
from weaving_demo.api import service
from weaving_demo.api.service import (
    prepare_solve, _apply_process_precedence, _apply_shopfloor_snapshot,
)
from weaving_demo.api.store import STORE
from weaving_demo.shopfloor import ShopFloorSnapshotStore, build_simulated_snapshot
from weaving_demo.config import BUSINESS_RULES
from weaving_demo.model import WeavingScenario, ProductionTask
from weaving_demo.solver import solve
from weaving_demo.tests.builders import mk_product, mk_loom, mk_task, mk_scenario
from weaving_demo.data_imports import DataImportStore, REQUIRED_SHEETS

client = TestClient(app)


def _reset_store():
    STORE._data.clear()
    STORE._latest_id = None


def _import_book_base64():
    wb = Workbook()
    wb.remove(wb.active)
    for name in REQUIRED_SHEETS:
        ws = wb.create_sheet(name)
        ws.append(["字段", "值"])
        ws.append(["测试", 1])
    out = BytesIO()
    wb.save(out)
    return base64.b64encode(out.getvalue()).decode("ascii")


# 1) API 健康检查
def test_health():
    _reset_store()
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["engine"] == "google-or-tools-cp-sat"
    assert "algorithm_module" in body


# 2) 场景加载
def test_current_scenario():
    r = client.get("/api/scenarios/current")
    assert r.status_code == 200
    body = r.json()
    assert body["products"] > 0
    assert body["looms"] > 0
    assert isinstance(body["data_warnings"], list)


def test_data_import_preview_save_and_history(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "DATA_IMPORT_STORE", DataImportStore(tmp_path / "imports"))
    preview = client.post("/api/data/import-preview", json={
        "filename": "客户数据.xlsx", "content_base64": _import_book_base64(),
    })
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["status"] == "READY"
    assert preview_body["can_save"] is True

    saved = client.post("/api/data/snapshots", json={
        "preview_id": preview_body["preview_id"], "note": "API测试候选版本",
    })
    assert saved.status_code == 200
    assert saved.json()["status"] == "SAVED_NOT_ACTIVE"
    history = client.get("/api/data/snapshots")
    assert history.status_code == 200
    assert history.json()["count"] == 1
    assert history.json()["active_snapshot_id"] is None


# 3) 运行真实 CP-SAT 求解
def test_run_real_solve():
    _reset_store()
    r = client.post("/api/schedules/solve", json={"max_time_s": 5, "horizon_days": 7})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN")
    assert "diagnostics" in body
    assert "assignments" in body
    assert "kpi" in body
    assert body["provenance"]["horizon_days"] == 7
    assert body["schedule_id"]
    assert "target_loom_audit" in body
    assert "beam_ledger" in body
    assert body["result_scope"] == "final_executable"
    assert body["final_schedule"]["result_scope"] == "final_executable"
    assert body["assignments"] == body["final_schedule"]["assignments"]
    assert body["initial_plan"]["assignments"] is not body["assignments"]
    assert abs(sum(a["scheduled_quantity"] for a in body["assignments"])
               - body["kpi"]["scheduled_quantity"]) < 1e-3
    assert all(a.get("beam_id") for a in body["assignments"])
    assert all(0 <= a["start_minute"] < a["end_minute"] <= 7 * 1440
               for a in body["assignments"])
    assert body["rule_optimization"]["enabled"] is True
    assert body["warping_plan"]["planning_mode"] == "weaving_pull"
    assert body["rule_optimization"]["warping_alignment"]["removed_task_count"] >= 0
    assert body["roll_plan"]
    assert all(row["rule_ok"] for row in body["roll_plan"])

    # 同一个 schedule_id 在各模块只能出现一套最终数量和事件。
    simulation = client.post("/api/simulation/run", json={"schedule_id": body["schedule_id"]}).json()
    tasks = client.get("/api/tasks/pool").json()
    looms = client.get("/api/looms/resource").json()
    gantt = client.get("/api/process/gantt").json()
    gantt_quantity = sum(bar.get("quantity", 0) for group in gantt["groups"]
                         if group["process"] == "织造" for bar in group["bars"])
    assert simulation["weaving_plan"] == body["execution_preview"]["weaving_plan"]
    assert simulation["shopfloor_snapshot"]["input"]["snapshot_id"] == \
        body["final_schedule"]["input_shopfloor_snapshot"]["snapshot_id"]
    assert abs(tasks["sum_scheduled"] - body["kpi"]["scheduled_quantity"]) < 1e-3
    assert looms["used_count"] == body["kpi"]["used_loom_count"]
    assert abs(gantt_quantity - body["kpi"]["scheduled_quantity"]) < 1e-3
    assert gantt["result_scope"] == "final_executable"


# 4) 获取最近结果
def test_latest_schedule():
    _reset_store()
    client.post("/api/schedules/solve", json={"max_time_s": 5, "horizon_days": 14})
    r = client.get("/api/schedules/latest")
    assert r.status_code == 200
    assert r.json()["schedule_id"]


# 5) 获取诊断信息
def test_schedule_diagnostics():
    _reset_store()
    body = client.post("/api/schedules/solve", json={"max_time_s": 4, "horizon_days": 14}).json()
    sid = body["schedule_id"]
    r = client.get(f"/api/schedules/{sid}/diagnostics")
    assert r.status_code == 200
    d = r.json()
    assert "diagnostics" in d
    assert "model_stats" in d
    assert "objective_levels" in d


# 6) 非法适配模式返回 400
def test_invalid_mode_400():
    r = client.post("/api/schedules/solve", json={"compatibility_mode": "nonsense"})
    assert r.status_code == 400
    assert "invalid compatibility_mode" in r.json()["detail"]


# 7) 非法排程周期返回 400
def test_invalid_horizon_400():
    r = client.post("/api/schedules/solve", json={"horizon_days": 45})
    assert r.status_code == 400
    assert "invalid horizon_days" in r.json()["detail"]


def test_weekly_window_maximizes_quantity_then_compacts_schedule():
    sc = mk_scenario([mk_product("P1")], [mk_loom("#101")], [mk_task("T1", "P1", 3000)])
    _, conf, kwargs = prepare_solve(sc, {"horizon_days": 7})
    assert kwargs["horizon_days"] == 7
    assert kwargs["max_layers"] == 2
    assert conf["stage2_params"]["objective_layers"] == [
        "unscheduled_quantity", "schedule_compactness",
    ]


def test_simulated_snapshot_enters_main_solve_precedence_and_machine_state():
    sc = mk_scenario([mk_product("P1")], [mk_loom("#101", current="P1"), mk_loom("#102")],
                     [mk_task("T1", "P1", 3000, allowed=["#101"])],
                     start="2026-04-01", end="2026-04-08")
    snapshot = build_simulated_snapshot(sc, captured_at="2026-04-01T08:00:00")
    applied = _apply_shopfloor_snapshot(sc, snapshot)
    dataset = {
        "reconciliation": {"product_rows": [{"product_id": "P1", "warp_beam_sku": "WP1"}]},
        "beams": {"WP1": {"set_length": 3600, "initial_inventory": None}},
        "tasks": [{"warp_beam_sku": "WP1", "plan_date": "2026-04-05", "plan_meters": 3600}],
    }
    info = _apply_process_precedence(
        sc, sc.生产任务, dataset, shopfloor_snapshot=snapshot,
    )

    assert applied["applied_loom_count"] == 2
    assert applied["available_beam_meters"] > 0
    assert info["snapshot_product_count"] == 1
    assert sc.虚拟经轴[0].earliest_available_minute == 0
    assert sc.虚拟经轴[0].status == "阶段一快照余轴可用"


def test_process_precedence_maps_beam_and_waits_until_warping_complete():
    sc = mk_scenario([mk_product("P1")], [mk_loom("#101")],
                     [mk_task("T1", "P1", 3000)], start="2026-04-01", end="2026-04-08")
    dataset = {
        "reconciliation": {"product_rows": [{"product_id": "P1", "warp_beam_sku": "WP1"}]},
        "beams": {"WP1": {"set_length": 3600, "initial_inventory": None}},
        "tasks": [{"warp_beam_sku": "WP1", "plan_date": "2026-04-03", "plan_meters": 3600}],
    }
    info = _apply_process_precedence(sc, sc.生产任务, dataset)
    assert sc.生产任务[0].beam_code == "WP1"
    assert sc.虚拟经轴[0].earliest_available == "2026-04-04T00:00:00"
    assert sc.虚拟经轴[0].earliest_available_minute == 3 * 1440
    assert info["process_order"] == ["整经", "上轴", "织造", "水洗"]


def test_weekly_precedence_uses_requested_start_and_hour_precision():
    sc = mk_scenario([mk_product("P1")], [mk_loom("#101")],
                     [mk_task("T1", "P1", 3000)], start="2026-06-01", end="2026-08-01")
    dataset = {
        "reconciliation": {"product_rows": [{"product_id": "P1", "warp_beam_sku": "WP1"}]},
        "beams": {"WP1": {"set_length": 3600, "initial_inventory": None}},
        "tasks": [{"warp_beam_sku": "WP1", "complete_at": "2026-04-01T16:00:00",
                   "plan_meters": 3600}],
    }
    _apply_process_precedence(sc, sc.生产任务, dataset,
                              schedule_start="2026-04-01", horizon_days=7)
    assert sc.虚拟经轴[0].earliest_available_minute == 16 * 60
    assert sc.虚拟经轴[0].earliest_available == "2026-04-01T16:00:00"


def test_simulation_api_returns_event_plan(monkeypatch):
    monkeypatch.setattr(service, "run_weekly_simulation", lambda params: {
        "status": "SIMULATED",
        "events": [{"event_type": "weaving"}],
        "validation": {"ok": True},
        "simulation_config": {"lead_time_minutes": params["lead_time_minutes"]},
    })
    r = client.post("/api/simulation/run", json={"lead_time_minutes": 120})
    assert r.status_code == 200
    assert r.json()["status"] == "SIMULATED"
    assert r.json()["validation"]["ok"] is True


def test_simulation_api_accepts_snapshot_and_explicit_commit(monkeypatch):
    monkeypatch.setattr(service, "run_weekly_simulation", lambda params: {
        "status": "SIMULATED",
        "snapshot_id": params["snapshot_id"],
        "committed": params["commit_final_state"],
    })
    r = client.post("/api/simulation/run", json={
        "snapshot_id": "sfs-1",
        "commit_final_state": True,
    })
    assert r.status_code == 200
    assert r.json()["snapshot_id"] == "sfs-1"
    assert r.json()["committed"] is True


def test_shopfloor_snapshot_api_versions_and_partial_updates(monkeypatch, tmp_path):
    snapshot_store = ShopFloorSnapshotStore(tmp_path / "shopfloor.json")
    scenario = mk_scenario(looms=[mk_loom("#101", current="P1")])
    monkeypatch.setattr(service, "SHOPFLOOR_STORE", snapshot_store)
    monkeypatch.setattr(service, "load_scenario", lambda: scenario)

    initial = client.get("/api/shopfloor/snapshot/latest")
    assert initial.status_code == 200
    assert initial.json()["summary"]["version"] == 1
    assert initial.json()["summary"]["source"] == "simulated_seed"
    assert initial.json()["snapshot"]["metadata"]["data_source"] == "simulated"

    updated = client.post("/api/shopfloor/snapshot", json={
        "base_version": 1,
        "source": "operator_input",
        "looms": [{
            "loom_id": "#101",
            "current_product_id": "P1",
            "current_beam_id": "REAL-001",
            "remaining_beam_m": 900,
            "edge_support_uses": 4,
        }],
    })
    assert updated.status_code == 200
    body = updated.json()
    assert body["summary"]["version"] == 2
    assert body["summary"]["loom_with_remaining_beam_count"] == 1
    assert body["summary"]["beam_count"] == 1

    sid = body["summary"]["snapshot_id"]
    fetched = client.get(f"/api/shopfloor/snapshot/{sid}")
    assert fetched.status_code == 200
    assert fetched.json()["snapshot"]["looms"][0]["remaining_beam_m"] == 900

    conflict = client.post("/api/shopfloor/snapshot", json={
        "base_version": 1,
        "looms": [{"loom_id": "#101", "edge_support_uses": 5}],
    })
    assert conflict.status_code == 409


# 8) 锁定冲突返回明确业务错误
def test_lock_conflict_business_error():
    sc = mk_scenario([mk_product("P1"), mk_product("P2")], [mk_loom("#101")],
                     [mk_task("T1", "P1", 1000, due_minute=50000, locked=True, lock_machine="#101",
                              lock_start=1000, lock_end=5000, lock_qty=1000, lock_reason="r"),
                      mk_task("T2", "P2", 1000, due_minute=50000, locked=True, lock_machine="#101",
                              lock_start=3000, lock_end=7000, lock_qty=1000, lock_reason="r")])
    sc.规则配置 = {}
    res = solve(sc, max_time_s=4.0, config=BUSINESS_RULES)
    assert res["status"] == "INFEASIBLE"
    assert res["business_status"] == "NOT_EXECUTABLE"
    assert any(i["severity"] == "ERROR" and "冲突" in i["message"] for i in res["issues"])


# 9) 求解超时返回当前可用状态
def test_timeout_returns_usable_status():
    _reset_store()
    r = client.post("/api/schedules/solve", json={"max_time_s": 0.2, "horizon_days": 14})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN")
    # 若返回了 results，应可解析为 JSON
    assert isinstance(json.loads(json.dumps(body)), dict)


# 10) JSON 时间与数值可被前端正确解析
def test_json_time_and_numbers_parseable():
    _reset_store()
    body = client.post("/api/schedules/solve", json={"max_time_s": 3, "horizon_days": 14}).json()
    assert body["schedule_start"].endswith("T00:00:00") or "T" in body["schedule_start"]
    for a in body["assignments"][:3]:
        assert isinstance(a["start_minute"], (int, float))
        assert isinstance(a["scheduled_quantity"], (int, float))
    if "scheduled_quantity" in body["kpi"]:
        assert isinstance(body["kpi"]["scheduled_quantity"], (int, float))
    # 重新序列化(前端 JSON.parse 等价)不出错
    json.loads(json.dumps(body, ensure_ascii=False))


# 11) 经轴品番主档接口
def test_warping_beams():
    r = client.get("/api/warping/beams")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 12
    assert len(body["beams"]) == 12
    b0 = body["beams"][0]
    for k in ("warp_beam_sku", "set_length", "warp_threads", "reed", "yarn_code",
              "unit_consumption_kg", "plan_dates", "target_loom_ids"):
        assert k in b0, f"缺字段 {k}"


# 12) 经轴实例接口
def test_warping_instances():
    r = client.get("/api/warping/instances")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 7
    assert body["virtual_count"] == 7
    assert body["real_count"] == 0
    i0 = body["instances"][0]
    assert i0["beam_instance_id"].startswith("BEAM-")
    assert i0["is_derived"] is True
    assert i0["warping_machine_id"] == ""


# 13) 经轴库存接口
def test_warping_inventory():
    r = client.get("/api/warping/inventory")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 12
    wp550 = next(x for x in body["inventory"] if x["warp_beam_sku"] == "WP550")
    daily = wp550["daily"]
    assert daily, "WP550 应有库存推移"
    # 2026-06-16: 基准 14400(源表库存行) + 9660(整经) - 4687.5(上轴) = 29032.5
    j16 = next(d for d in daily if d["date"] == "2026-06-16")
    assert j16["warp_complete_m"] == 9660
    assert j16["weave_mount_demand_m"] == 4687.5
    assert abs(j16["stock_m"] - 29032.5) < 1e-6


# 14) 任务池接口
def test_task_pool():
    r = client.get("/api/tasks/pool")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 0
    t0 = body["tasks"][0]
    for k in ("task_id", "product_id", "required_quantity", "scheduled_quantity",
              "unscheduled_quantity", "due_date", "priority", "status", "machine_id",
              "assign_start", "lateness_minutes", "data_source", "flow_id",
              "product_back_sku", "warp_beam_sku", "weaving_sku", "washing_sku",
              "beam_instance_id", "chain_status", "chain_missing_fields",
              "chain_reason", "mapping_source"):
        assert k in t0, f"缺字段 {k}"
    assert t0["status"] in ("已排程", "部分排程", "未排程", "锁定")
    # 统计对账：需求 = 已排 + 未排
    assert abs(body["sum_required"] - (body["sum_scheduled"] + body["sum_unscheduled"])) < 1e-6
    assert body["by_status"]
    assert body["chain_status_count"]
    for task in body["tasks"]:
        assert task["flow_id"] == f"FLOW-{task['product_id']}"
        beam_sku = task["warp_beam_sku"]
        assert beam_sku is None or beam_sku.startswith(("WP", "WN", "WS"))


# 15) 织机资源接口
def test_loom_resources():
    r = client.get("/api/looms/resource")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 108
    assert body["available_count"] > 0
    l0 = body["looms"][0]
    for k in ("loom_id", "region", "status", "available", "capacity_m_per_day",
              "waste_edge_disc", "edge_cut", "big_package", "water_filter", "yarn_frame",
              "reed", "full_width_edge_support", "used", "assigned_task_count",
              "tooling_note"):
        assert k in l0, f"缺字段 {k}"
    # 可用 + 不可用 = 总数
    assert body["available_count"] + body["unavailable_count"] == body["count"]
    # 已用 + 空闲 = 总数
    assert body["used_count"] + body["idle_count"] == body["count"]
    # 9 个区域
    assert len(body["by_region"]) == 9
