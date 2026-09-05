# -*- coding: utf-8 -*-
"""test_process_gantt.py -- 按 整经/织造/水洗 三大工艺流程甘特图 后端单元测试。"""
import os

import pytest

from weaving_demo.process_gantt import build_process_gantt

EXCEL = r"C:\Users\Administrator\OneDrive\Desktop\副本【作成中整经织造】益丰生产管理表单260604.xlsx"
IS_XL = os.path.exists(EXCEL)


@pytest.mark.skipif(not IS_XL, reason="源 Excel 不存在")
def test_process_gantt_has_three_groups_in_order():
    data = build_process_gantt(EXCEL)
    assert data["process_order"] == ["整经", "织造", "水洗"]
    processes = [g["process"] for g in data["groups"]]
    assert processes == ["整经", "织造", "水洗"]


@pytest.mark.skipif(not IS_XL, reason="源 Excel 不存在")
def test_process_gantt_uses_warping_pool_without_machine_id():
    data = build_process_gantt(EXCEL)
    warp = next(g for g in data["groups"] if g["process"] == "整经")
    for b in warp["bars"]:
        assert b["warping_machine_id"] == ""
        assert b["machine_display"] == "整经计划池"
        assert b["machine_status"] == "按计划池管理"
        assert b["warping_resource_mode"] == "计划池"


@pytest.mark.skipif(not IS_XL, reason="源 Excel 不存在")
def test_process_gantt_stats():
    data = build_process_gantt(EXCEL)
    st = data["stats"]
    assert st["warp_task_count"] == 5
    assert st["warp_beam_sku_count"] == 12
    assert st["target_loom_count"] == 30
    assert st["master_product_count"] == 19
    assert st["chain_full_count"] == 11
    assert st["chain_broken_count"] == 8
    assert st["process_master_chain_full_count"] == 15
    assert st["process_master_chain_broken_count"] == 1
    assert st["wash_task_count"] == 0
    assert st["wash_unmatched_count"] == 1
    assert st["machine_pending_count"] == 0
    assert data["warping_resource_mode"] == "计划池"


@pytest.mark.skipif(not IS_XL, reason="源 Excel 不存在")
def test_process_gantt_weaving_bars_have_chain_sku():
    data = build_process_gantt(EXCEL)
    weave = next(g for g in data["groups"] if g["process"] == "织造")
    for b in weave["bars"]:
        # 每个织造条都有稳定 flow_id；来源表缺失的品番保持为空，不猜值。
        assert b["flow_id"] == f"FLOW-{b['product_id']}"
        assert "weaving_sku" in b
        assert "warp_beam_sku" in b
        assert "beam_instance_id" in b
        assert "chain_status" in b


@pytest.mark.skipif(not IS_XL, reason="源 Excel 不存在")
def test_product_reconciliation_covers_19_master_products():
    data = build_process_gantt(EXCEL, weaving_assigns=[])
    rows = data["product_reconciliation"]
    assert len(rows) == 19
    good = next(x for x in rows if x["product_id"] == "PH54512B")
    assert good["status"] == "完整串联"
    assert good["warp_beam_sku"] == "WP550"
    assert good["weaving_sku"] == "RP550"
    assert good["washing_sku"] == "SP550"
    missing = next(x for x in rows if x["product_id"] == "PH555120")
    assert missing["status"] == "未建档"
    assert missing["warp_beam_sku"] is None
    assert missing["mapping_confidence"] == "缺失，不推断"


@pytest.mark.skipif(not IS_XL, reason="源 Excel 不存在")
def test_unmatched_washing_row_is_not_formal_gantt_bar():
    data = build_process_gantt(EXCEL, weaving_assigns=[])
    wash = next(g for g in data["groups"] if g["process"] == "水洗")
    assert wash["bars"] == []
    assert len(data["unmatched_washing_rows"]) == 1
    assert data["unmatched_washing_rows"][0]["washing_sku"] == "A产品"


@pytest.mark.skipif(not IS_XL, reason="源 Excel 不存在")
def test_weekly_gantt_checks_weaving_against_last_beam_completion_time():
    weekly = {
        "tasks": [
            {"task_id": "W1", "warp_beam_sku": "WP551", "plan_date": "2026-04-01",
             "start": "2026-04-01T12:00:00", "end": "2026-04-01T16:00:00",
             "plan_meters": 4800, "plan_count": 1, "target_loom_id": [],
             "warping_machine_id": "", "is_derived": True, "data_source": "测试"},
        ]
    }
    assignments = [{
        "task_id": "T1", "part_index": 0, "loom_id": "#101", "product_id": "PH555140",
        "beam_id": "WB-WP551-001", "scheduled_quantity": 100,
        "start": "2026-04-01T16:00:00", "end": "2026-04-02T00:00:00",
        "start_minute": 960, "end_minute": 1440,
    }]
    data = build_process_gantt(EXCEL, weaving_assigns=assignments, warping_plan=weekly)
    assert data["order_warnings"] == []
    weave = next(g for g in data["groups"] if g["process"] == "织造")["bars"][0]
    assert weave["start"] == "2026-04-01T16:00:00"
