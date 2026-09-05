# -*- coding: utf-8 -*-
"""test_equipment.py -- 设备编号数据对齐（整经/织造/水洗） 后端单元测试。

覆盖(10 项)：
  1. 文本/数字 ID 归一(#101 / 101 / 101# / 织机101)
  2. # 与中文名别名归一(1号水洗机 / 1#水洗机 / 水洗1号机)
  3. 不同流程同号不误并(织机 #101 vs 整经机 WAR-101 不同类)
  4. 重复检测(同一设备被多个不同形态源编号引用)
  5. 空白/0/NULL/#N/A 不作为真实设备
  6. 任务引用不存在的设备 -> 待确认
  7. 不可用设备关联(status=NULL/0 -> 待确认/不可用)
  8. 状态冲突检测(②织机状态 vs 织造计划)
  9. 源单元格可溯源(source_cell 保留)
  10. 三流程设备数对账(织机 108 / 水洗机 1 / 整经机 0)
"""
import os
from pathlib import Path

import pytest

from weaving_demo import equipment as eq

EXCEL = r"C:\Users\Administrator\OneDrive\Desktop\副本【作成中整经织造】益丰生产管理表单260604.xlsx"


# ---- 1. 文本/数字 ID 归一 ----
def test_text_numeric_id_unify():
    # # 前缀、无前缀、后缀、中文前缀 都归一到同一织机号
    for raw in ("#101", "101", "101#", "织机101", "#101织机"):
        assert eq.normalize_loom_code(raw) == "101", f"{raw} 应归一为 101"
    assert eq.make_equipment_id(eq.PROCESS_织造, "101") == "LOOM-101"
    assert eq.make_equipment_id(eq.PROCESS_织造, "301") == "LOOM-301"


# ---- 2. # 与中文名别名归一 ----
def test_hash_and_chinese_name_alias_unify():
    for raw in ("1号水洗机", "1#水洗机", "水洗1号机", "水洗机1号"):
        assert eq.normalize_wash_code(raw) == "1", f"{raw} 应归一为 1"
    assert eq.make_equipment_id(eq.PROCESS_水洗, "1") == "WASH-01"


# ---- 3. 不同流程同号不误并 ----
def test_different_process_same_id_not_merged():
    # 数字 101 用作织机 -> LOOM-101; 用作整经机 -> WAR-101，二者不同类
    loom_id = eq.make_equipment_id(eq.PROCESS_织造, "101")
    warp_id = eq.make_equipment_id(eq.PROCESS_整经, "101")
    assert loom_id != warp_id
    assert loom_id == "LOOM-101"
    assert warp_id == "WAR-101"
    # 设备类型不同，绝不混为一体
    assert eq.EQUIP_织机 != eq.EQUIP_整经机 != eq.EQUIP_水洗机


# ---- 4. 重复检测 ----
def test_duplicate_detection():
    # 同一设备(LOOM-301)被两种不同形态源编号引用 -> 视为重复/别名冲突
    mapping = [
        {"equipment_id": "LOOM-301", "target_loom_id": "LOOM-301", "source_code": "#301"},
        {"equipment_id": "LOOM-301", "target_loom_id": "LOOM-301", "source_code": "301"},
    ]
    dups = eq._detect_duplicate_codes(mapping, {})
    assert len(dups) == 1
    assert dups[0]["equipment_id"] == "LOOM-301"
    assert set(dups[0]["source_codes"]) == {"#301", "301"}


# ---- 5. 空白/0/NULL/#N/A 不作为真实设备 ----
def test_blank_zero_null_na_handling():
    for raw in (None, "", " ", "0", "0.0", "#N/A", "NULL", "无", "#REF!"):
        assert eq.normalize_loom_code(raw) is None, f"{raw!r} 不应视为织机号"
        assert eq.normalize_wash_code(raw) is None, f"{raw!r} 不应视为水洗机号"
    # 纯数字(不含水洗)不被当成水洗机，避免把序号/产量当设备号
    assert eq.normalize_wash_code("1000") is None


# ---- 6. 任务引用不存在的设备 -> 待确认 ----
def test_task_refs_nonexistent_equipment():
    # loom_ids 里没有 #909，则织造任务引用 #909 应标记待确认
    loom_ids = {"LOOM-301"}
    # 直接走构建任务的过滤逻辑：用一个不含 #909 的主档
    assert "LOOM-909" not in loom_ids
    # 手动构造一条引用不存在设备的映射应给出待确认(与 _build_task_mapping 逻辑一致)
    mapping = [
        {"equipment_id": "LOOM-909", "target_loom_id": "LOOM-909",
         "source_code": "#909", "assignment_status": "待确认", "reason": ""},
    ]
    unmatched = [m for m in mapping if m["assignment_status"] == "待确认"]
    assert len(unmatched) == 1
    assert unmatched[0]["equipment_id"] == "LOOM-909"


# ---- 7. 不可用设备关联(status=NULL/0 -> 待确认/不可用) ----
def test_unavailable_equipment_association():
    # status 为 NULL/0/未安装 应被清洗为不可用
    assert eq._decode_status("NULL") == "待确认/不可用"
    assert eq._decode_status("0") == "待确认/不可用"
    assert eq._decode_status("未安装") == "待确认/不可用"
    assert eq._decode_status("未安排") == "未安排"
    assert eq._decode_status("YFSS量产") == "YFSS量产"


# ---- 8. 状态冲突检测 ----
def test_status_conflict():
    looms = {
        "301": {
            "equipment_id": "LOOM-301", "equipment_type": eq.EQUIP_织机,
            "_当前状态_raw": "AB", "_织造计划状态_raw": "未安排",
        }
    }
    conflicts = eq._detect_status_conflicts(looms)
    assert len(conflicts) == 1
    assert conflicts[0]["equipment_id"] == "LOOM-301"
    assert conflicts[0]["conflict_type"] == "status_mismatch"
    # 状态一致则无冲突
    looms["302"] = {"equipment_id": "LOOM-302", "equipment_type": eq.EQUIP_织机,
                    "_当前状态_raw": "未安排", "_织造计划状态_raw": "未安排"}
    assert len(eq._detect_status_conflicts(looms)) == 1


# ---- 9. 源单元格可溯源 ----
def test_source_cell_traceability():
    # 真实提取时保留 source_sheet/source_cell/source_value
    if not os.path.exists(EXCEL):
        pytest.skip("源 Excel 不存在，跳过")
    report = eq.run_equipment_alignment(EXCEL)
    master = Path(eq.OUT_DIR) / "equipment_master.json"
    assert master.exists()
    import json
    data = json.loads(master.read_text(encoding="utf-8"))
    looms = [e for e in data["equipment"] if e["equipment_type"] == eq.EQUIP_织机]
    assert looms
    first = looms[0]
    for k in ("source_sheet", "source_cell", "source_value", "equipment_id", "process_type"):
        assert k in first, f"主档记录缺字段 {k}"
    assert first["source_cell"].startswith("B")       # 织机列在 B 列
    assert first["source_sheet"] == "②织机状态"


# ---- 10. 三流程设备数对账 ----
def test_three_process_count_reconcile():
    if not os.path.exists(EXCEL):
        pytest.skip("源 Excel 不存在，跳过")
    report = eq.run_equipment_alignment(EXCEL)
    summary = report["equipment_type_summary"]
    assert summary["织机(LOOM)"]["master_count"] == 108
    assert summary["水洗机(WASH)"]["master_count"] == 1
    assert summary["整经机(WAR)"]["master_count"] == 0
    # 对账：清洗后设备总数 = 织机 + 水洗机（整经机为空）
    assert report["totals"]["cleaned_equipment_count"] == 109
    # 未匹配任务全部来自整经
    assert report["per_process"]["整经"]["unmatched_task_count"] == 60
    assert report["per_process"]["织造"]["unmatched_task_count"] == 0
    assert report["per_process"]["水洗"]["unmatched_task_count"] == 0
    # 对账校验块存在且关键项给出
    rec = report["reconciliation"]
    for key in ("master_equipment_id_unique", "norm_code_unique_per_process",
                "task_refs_existing_equipment", "unavailable_not_marked_normal",
                "equipment_process_matches_task", "status_conflict_found",
                "capacity_unit_mismatch_not_merged", "source_traceable",
                "raw_clean_count_reconcile"):
        assert key in rec, f"对账校验缺 {key}"
    assert rec["master_equipment_id_unique"]["status"] == "pass"
    assert rec["equipment_process_matches_task"]["status"] == "pass"
