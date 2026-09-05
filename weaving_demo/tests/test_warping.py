# -*- coding: utf-8 -*-
"""test_warping.py -- 整经数据口径修正 后端单元测试。

覆盖：
  1. 整经计划上半部分「织机」列是目标织机，不是整经机。
  2. 整经任务数(修正后)按 经轴品番×日期 计数，而非上半部分 60 行。
  3. 经轴品番/织造品番/水洗品番 的 SKU 识别(不把规格当实体号)。
  4. 库存 = 前日库存 + 当日整经计划 - 当日织造上轴需求 的推移计算。
  5. 整经机编号缺失 -> 置空 + 待补充，不用目标织机号代替。
  6. 多产品共用同一经轴品番(如 WP551 对应 PH54513B/PH545140/PH555140)。
  7. 虚拟经轴实例标记为推导数据。
  8. 工艺串联: PH54512B -> WP550 -> RP550 -> SP550。
  9. 无法串联数据(缺水洗品番)被如实记录。
  10. 真实 Excel 提取数量对账(12 SKU / 30 织机 / 5 任务 / 15 完整串联)。
"""
import os

import pytest

from weaving_demo import warping as wp

EXCEL = r"C:\Users\Administrator\OneDrive\Desktop\副本【作成中整经织造】益丰生产管理表单260604.xlsx"
IS_XL = os.path.exists(EXCEL)


@pytest.fixture(scope="module", autouse=True)
def _generate():
    if IS_XL:
        wp.run_warping(EXCEL)


# ---- 1. 上半部分「织机」列 = 目标织机 ----
def test_upper_loom_col_is_target_loom():
    if not IS_XL:
        pytest.skip("源 Excel 不存在")
    target = wp.read_target_looms(_wb())
    # 上半部分每行是一台织机(目标织机)，不是整经机
    assert all(t["target_loom_id"].startswith("LOOM-") for t in target)
    assert len(target) > 0


# ---- 2. 修正后整经任务数按 经轴品番×日期 计 ----
def test_warp_task_count_uses_beam_times_date():
    if not IS_XL:
        pytest.skip("源 Excel 不存在")
    report = wp.run_warping(EXCEL)
    # 上半部分约 60 行(30 台织机×2行)是 轴个数/上轴，不能当 60 个任务
    assert report["warp_task_count"] == 5
    assert report["warp_beam_sku_count"] == 12


# ---- 3. SKU 识别 ----
def test_sku_detection():
    assert wp._is_beam_sku("WP550")
    assert wp._is_beam_sku("WN453")
    assert not wp._is_beam_sku("RP550")
    assert wp._is_weaving_sku("RP550")
    assert wp._is_weaving_sku("RN453")
    assert wp._is_washing_sku("SP550")
    assert not wp._is_washing_sku("WP550")


# ---- 4. 库存推移 = 前日 + 当日整经计划 - 当日织造上轴需求 ----
def test_inventory_computation():
    beam = {"initial_inventory": 100, "warp_plan_m": {"2026-04-03": 4800},
            "weave_demand_m": {"2026-04-03": 800}}
    inv = wp.compute_inventory(beam)
    assert inv["2026-04-03"] == 100 + 4800 - 800


# ---- 5. 计划池模式不要求具体整经机编号 ----
def test_warping_machine_id_empty_not_fabricated():
    if not IS_XL:
        pytest.skip("源 Excel 不存在")
    tasks = json_load_named("warp_tasks.json")["warp_tasks"]
    for t in tasks:
        # 源表无整经机编号，绝不能用目标织机号代替
        assert t["warping_machine_id"] == ""
        assert t["machine_status"] == "按计划池管理"
        assert t["machine_placeholder"] == "整经计划池"
        assert t["warping_resource_mode"] == "计划池"


# ---- 6. 多产品共用同一经轴品番 ----
def test_multiple_products_share_beam_sku():
    if not IS_XL:
        pytest.skip("源 Excel 不存在")
    chains = json_load_named("warp_chain.json")["chain"]
    # WP551 被 PH54513B / PH545140 / PH555140 共用
    users = [c["product_id"] for c in chains if c["warp_beam_sku"] == "WP551"]
    assert len(users) >= 2


# ---- 7. 虚拟经轴实例标记为推导数据 ----
def test_beam_instances_marked_derived():
    if not IS_XL:
        pytest.skip("源 Excel 不存在")
    inst = json_load_named("warp_beam_instances.json")["beam_instances"]
    assert inst
    assert all(i["is_derived"] for i in inst)
    assert all(i["beam_instance_id"].startswith("BEAM-") for i in inst)
    assert all(i["data_source"] == "推导数据(源表无实体经轴编号)" for i in inst)


# ---- 8. 工艺串联 示例 ----
def test_chain_ph54512b():
    if not IS_XL:
        pytest.skip("源 Excel 不存在")
    chains = json_load_named("warp_chain.json")["chain"]
    c = next((x for x in chains if x["product_id"] == "PH54512B"), None)
    assert c is not None
    assert c["warp_beam_sku"] == "WP550"
    assert c["weaving_sku"] == "RP550"
    assert c["washing_sku"] == "SP550"
    assert c["link_status"] == "完整串联"


# ---- 9. 无法串联(缺水洗品番)被如实记录 ----
def test_broken_chain_recorded():
    if not IS_XL:
        pytest.skip("源 Excel 不存在")
    chains = json_load_named("warp_chain.json")["chain"]
    hard = next((x for x in chains if x["product_id"] == "PH55463N"), None)
    assert hard is not None
    assert hard["washing_sku"] is None
    assert hard["link_status"] == "缺水洗品番"


# ---- 10. 数量对账 ----
def test_warping_counts_reconcile():
    if not IS_XL:
        pytest.skip("源 Excel 不存在")
    report = wp.run_warping(EXCEL)
    assert report["warp_beam_sku_count"] == 12
    assert report["target_loom_count"] == 30
    assert report["warp_task_count"] == 5
    assert report["beam_instance_virtual"] >= 5
    assert report["chain_full_count"] == 15
    assert report["chain_broken_count"] == 1
    assert report["master_product_count"] == 19
    assert report["master_chain_full_count"] == 11
    assert report["master_chain_broken_count"] == 8


# ---- 11. 产品级对账: 19 个产品逐一对账(完整/未建档/未投产/缺水洗) ----
def test_product_reconciliation_over_all_master():
    if not IS_XL:
        pytest.skip("源 Excel 不存在")
    recon = json_load_named("warp_reconciliation.json")
    assert recon["master_product_count"] == 19
    rows = recon["product_rows"]
    assert len(rows) == 19
    sc = recon["status_count"]
    assert sc["完整串联"] == 11
    assert sc["缺水洗品番"] == 1
    assert sc["未建档"] == 6
    assert sc["未投产"] == 1
    # 每个产品都有 flow_id 且唯一
    fids = [r["flow_id"] for r in rows]
    assert len(set(fids)) == len(fids)
    # 缺水洗品番的产品停在织造节点
    mw = next(r for r in rows if r["link_status"] == "缺水洗品番")
    assert mw["product_id"] == "PH55463N"


# ---- 12. 整经任务 ↔ 虚拟经轴 对应表 ----
def test_task_beam_instance_table():
    if not IS_XL:
        pytest.skip("源 Excel 不存在")
    recon = json_load_named("warp_reconciliation.json")
    table = recon["task_instance_table"]
    assert len(table) == 5
    total_inst = sum(t["beam_instance_count"] for t in table)
    assert total_inst == 7
    for t in table:
        assert t["plan_date"] and t["warp_beam_sku"]
        assert t["plan_src_cell"]  # 源表单元格可溯源
        assert t["beam_instance_ids"]


# ---- 13. 时间来源: 整经/水洗为来源表计划, 织造为 CP-SAT ----
def test_time_source_is_cp_sat_only_for_weave():
    if not IS_XL:
        pytest.skip("源 Excel 不存在")
    from weaving_demo.process_gantt import build_process_gantt
    data = build_process_gantt(EXCEL, weaving_assigns=_fixed_assigns())
    groups = {g["process"]: g["bars"] for g in data["groups"]}
    assert groups["整经"] and all(b["time_source"] == "来源表计划(非CP-SAT约束)" for b in groups["整经"])
    assert all(b["time_source"] == "来源表计划(非CP-SAT约束)" for b in groups["水洗"])
    assert groups["织造"] and all(b["time_source"] == "CP-SAT求解结果" for b in groups["织造"])
    assert data["time_source_summary"]["CP-SAT求解结果"] == len(groups["织造"])


# ---- 14. 缺水洗品番产品停在织造节点且显示原因 ----
def test_missing_washing_stops_at_weave_node():
    if not IS_XL:
        pytest.skip("源 Excel 不存在")
    from weaving_demo.process_gantt import build_process_gantt
    data = build_process_gantt(EXCEL, weaving_assigns=_fixed_assigns())
    weave = next(g for g in data["groups"] if g["process"] == "织造")
    flagged = [b for b in weave["bars"] if b.get("missing_washing")]
    assert len(flagged) == 1
    assert flagged[0]["product_id"] == "PH55463N"
    assert flagged[0]["chain_status"] == "缺水洗品番"
    assert flagged[0]["missing_reason"]
    # flow_id 串联
    for b in weave["bars"]:
        assert "flow_id" in b


def _fixed_assigns():
    """固定一段织造 assignment(含缺水洗品番的 PH55463N)，使测试不依赖求解。"""
    return [
        {"task_id": "T-PH55463N", "part_index": 0, "loom_id": "#406", "product_id": "PH55463N",
         "beam_id": "WB-PH55463N-001", "start": "2026-04-01T00:00:00", "end": "2026-04-05T00:00:00",
         "start_minute": 0, "end_minute": 5760, "scheduled_quantity": 3600, "locked": False,
         "lock_reason": None, "changeover_type": "same", "lateness_minutes": 0},
        {"task_id": "T-PH54512B", "part_index": 0, "loom_id": "#305", "product_id": "PH54512B",
         "beam_id": "WB-PH54512B-001", "start": "2026-04-01T00:00:00", "end": "2026-04-06T00:00:00",
         "start_minute": 0, "end_minute": 7200, "scheduled_quantity": 4800, "locked": False,
         "lock_reason": None, "changeover_type": "same", "lateness_minutes": 0},
    ]



# ---- 工具 ----
def _wb():
    from openpyxl import load_workbook
    return load_workbook(EXCEL, data_only=True, read_only=True)


def json_load_named(name):
    import json
    p = wp.OUT_DIR / name
    assert p.exists(), f"缺少 {name}，先运行 python weaving_demo/warping.py"
    return json.loads(p.read_text(encoding="utf-8"))
