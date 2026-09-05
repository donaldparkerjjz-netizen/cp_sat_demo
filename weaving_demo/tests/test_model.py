# -*- coding: utf-8 -*-
"""test_model.py -- 领域数据模型单元测试。"""
import json

from weaving_demo.model import (
    Settings, Product, Loom, WarpBeam, WarpingTask, WeavingTask,
    ClothDropForecast, YarnMaterial, DueDate, WeavingScenario,
    date_matrix_to_list, as_jsonable,
)


def _sample_product():
    return Product(
        产品款号="PH555120",
        经轴款号="PH555120",
        客户款号="68616-0000Z",
        客户="AB",
        目前阶段="PV??",
        使用纱线="LS7056AB",
        整经设定长度=3600,
        织造效率=400,
        有效门幅=2.25,
        纱线单耗KG_M=0.63,
        纱线单耗KG_M2=0.25,
        钢筘型号="9.3钢筘",
    )


def _sample_loom():
    return Loom(
        织机号="#301",
        区域="区域3",
        当前状态="AB",
        目前对应产品="PH555120",
        产能设定=400,
        废边盘=True,
        切边=True,
        大卷装=True,
        纱架=True,
        钢筘="9.3钢筘",
        全幅边撑="2350",
        可对应产品=["PH555120"],
    )


def test_product_fields_roundtrip():
    p = _sample_product()
    d = p.to_dict()
    assert d["产品款号"] == "PH555120"
    assert d["使用纱线"] == "LS7056AB"
    assert d["织造效率"] == 400.0
    assert d["纱线单耗KG_M"] == 0.63
    # json 可序列化
    json.dumps(d, ensure_ascii=False)


def test_loom_tooling_fields():
    l = _sample_loom()
    assert l.织机号 == "#301"
    assert l.废边盘 is True
    assert l.钢筘 == "9.3钢筘"
    assert l.可对应产品 == ["PH555120"]
    assert l.状态可用 is True
    l2 = Loom(织机号="#911", 当前状态="NULL")
    assert l2.状态可用 is False


def test_scenario_holds_all_entities():
    sc = WeavingScenario(
        设置=Settings(当前日期="2026-05-18", 卷曲率=0.08),
        产品=[_sample_product()],
        织机=[_sample_loom()],
        经轴=[WarpBeam(经轴品番="PH555120", 设定米数=3600)],
        整经任务=[WarpingTask(织机="#301", 内容="上轴", 日常={"2026-04-01": 3600})],
        织造任务=[WeavingTask(织机="#301", 产能设定=400, 内容="落布数量", 日常={"2026-04-02": 100})],
        落布预测=[ClothDropForecast(织机="#301", 内容="落布数量", 日常={"2026-04-02": 100})],
        物料=[YarnMaterial(纱线名称="涤纶纱线", 纱线代码="LS7056AB", 期初库存=174042)],
        交期=[DueDate(产品款号="PH555120", 月份="2026-05", 预测数量=15000)],
    )
    d = sc.to_dict()
    assert len(d["产品"]) == 1
    assert len(d["织机"]) == 1
    assert len(d["物料"]) == 1
    assert d["整经任务"][0]["日常"]["2026-04-01"] == 3600
    # as_jsonable 可序列化
    json.dumps(as_jsonable(sc), ensure_ascii=False)


def test_date_matrix_to_list_sorted():
    dm = {"2026-04-03": 3, "2026-04-01": 1, "2026-04-02": 2}
    lst = date_matrix_to_list(dm)
    assert [x["date"] for x in lst] == ["2026-04-01", "2026-04-02", "2026-04-03"]
    assert [x["value"] for x in lst] == [1, 2, 3]
