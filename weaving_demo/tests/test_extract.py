# -*- coding: utf-8 -*-
"""test_extract.py -- 从真实 Excel 提取的集成测试（文件不存在时自动跳过）。
确保提取管道产物是一致、可校验通过的场景。"""
import os
from pathlib import Path

import pytest

from weaving_demo.extract import extract_scenario
from weaving_demo.load import scenario_from_dict
from weaving_demo.validate import validate_scenario

EXCEL = r"C:\Users\Administrator\OneDrive\Desktop\副本【作成中整经织造】益丰生产管理表单260604.xlsx"


@pytest.mark.skipif(not os.path.exists(EXCEL), reason="源 Excel 不存在，跳过真实提取测试")
def test_extract_real_excel_produces_valid_scenario():
    sc = extract_scenario(EXCEL)
    # 关键实体均应有数据
    assert len(sc.产品) > 0
    assert len(sc.织机) > 0
    assert len(sc.工艺条件) > 0
    assert len(sc.整经任务) > 0
    assert len(sc.织造任务) > 0
    assert len(sc.落布预测) > 0
    assert len(sc.物料) > 0
    # 校验通过
    rep = validate_scenario(sc)
    assert rep["ok"] is True
    assert rep["errors"] == []


@pytest.mark.skipif(not os.path.exists(EXCEL), reason="源 Excel 不存在，跳过真实提取测试")
def test_extract_json_roundtrip():
    sc = extract_scenario(EXCEL)
    d = sc.to_dict()
    # JSON 往返
    import json
    roundtrip = json.loads(json.dumps(d, ensure_ascii=False))
    reloaded = scenario_from_dict(roundtrip)
    assert len(reloaded.产品) == len(sc.产品)
    assert len(reloaded.织机) == len(sc.织机)
    assert len(reloaded.织造任务) == len(sc.织造任务)
    # 某个织机的产能设定保留
    l = next((x for x in reloaded.织机 if x.织机号 == "#301"), None)
    assert l is not None and l.产能设定 is not None
