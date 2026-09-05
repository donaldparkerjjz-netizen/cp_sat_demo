# -*- coding: utf-8 -*-
"""test_validate.py -- 数据校验与产品-织机静态适配单元测试。"""
from weaving_demo.model import Product, Loom, YarnMaterial, WeavingScenario
from weaving_demo.validate import (
    is_loom_compatible, product_required_tooling,
    validate_material_non_negative, validate_scenario,
)


def _product(钢筘="9.3钢筘", 门幅=2.25, 纱线="LS7056AB", 工装要求=None):
    return Product(
        产品款号="PH555120",
        经轴款号="PH555120",
        使用纱线=纱线,
        整经设定长度=3600,
        织造效率=400,
        有效门幅=门幅,
        钢筘型号=钢筘,
        工装要求=工装要求 or [],
    )


def _loom(可对应=None, 钢筘="9.3钢筘", 边撑="2350", 废边盘=True, 切边=True, 纱架=True, 状态="AB"):
    return Loom(
        织机号="#301",
        当前状态=状态,
        废边盘=废边盘,
        切边=切边,
        大卷装=True,
        水过滤=True,
        纱架=纱架,
        钢筘=钢筘,
        全幅边撑=边撑,
        可对应产品=可对应 if 可对应 is not None else [],
    )


def test_compatible_loom():
    ok, reasons = is_loom_compatible(_product(), _loom())
    assert ok is True
    assert reasons == []


def test_incompatible_missing_yarn_frame():
    # 产品显式要求纱架，织机没有纱架 -> 不可行
    ok, reasons = is_loom_compatible(_product(工装要求=["yarn_frame"]), _loom(纱架=False))
    assert ok is False
    assert any("纱架" in r for r in reasons)


def test_incompatible_missing_reed():
    # 产品要求钢筘，织机没有钢筘 -> 不可行
    ok, reasons = is_loom_compatible(_product(), _loom(钢筘=None))
    assert ok is False
    assert any("钢筘" in r for r in reasons)


def test_incompatible_width_exceeds_edge_support():
    ok, reasons = is_loom_compatible(_product(门幅=2.6), _loom(边撑="2350"))
    assert ok is False
    assert any("门幅" in r for r in reasons)


def test_incompatible_loom_not_available():
    ok, reasons = is_loom_compatible(_product(), _loom(状态="NULL"))
    assert ok is False
    assert any("不可用" in r for r in reasons)


def test_incompatible_applicable_list_strict():
    ok, reasons = is_loom_compatible(_product(), _loom(可对应=["NW44463N"]))
    assert ok is False
    assert any("可对应产品" in r for r in reasons)


def test_product_required_tooling_defaults():
    p = _product()
    tooling = product_required_tooling(p)
    assert "reed" in tooling
    assert "full_width_edge_support" in tooling


def test_material_negative_detected():
    mats = [
        YarnMaterial(纱线名称="涤纶纱线", 纱线代码="LS7056AB", 内容="库存", 日常={"2026-04-01": 100, "2026-04-02": -5}),
        YarnMaterial(纱线名称="涤纶纱线", 纱线代码="ZSCA", 内容="库存", 日常={"2026-04-01": 50}),
    ]
    errs = validate_material_non_negative(mats)
    assert len(errs) == 1
    assert "LS7056AB" in errs[0]
    assert "2026-04-02" in errs[0]


def test_scenario_duplicate_detection():
    sc = WeavingScenario(
        产品=[_product(), _product()],          # 重复产品款号
        织机=[_loom(), _loom()],                # 重复织机号
        物料=[YarnMaterial(纱线名称="涤纶纱线", 纱线代码="LS7056AB", 内容="库存", 日常={"2026-04-01": -1})],
    )
    rep = validate_scenario(sc)
    assert rep["ok"] is False
    assert any("重复" in e for e in rep["errors"])
    assert any("为负" in e for e in rep["errors"])


def test_scenario_valid():
    sc = WeavingScenario(
        产品=[_product()],
        织机=[_loom()],
        物料=[YarnMaterial(纱线名称="涤纶纱线", 纱线代码="LS7056AB", 内容="库存", 日常={"2026-04-01": 100})],
    )
    rep = validate_scenario(sc)
    assert rep["ok"] is True
    assert rep["errors"] == []
    assert rep["stats"]["产品数"] == 1
