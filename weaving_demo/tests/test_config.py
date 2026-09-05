# -*- coding: utf-8 -*-
"""test_config.py -- 可配置业务规则参数的单元测试。"""
from weaving_demo.config import (
    BUSINESS_RULES, HARD_RULES, OBJECTIVE_PRIORITY, OBJECTIVE_WEIGHTS,
    TIME_PARAMS, build_business_rules,
)


def test_hard_rules_present_and_enabled():
    assert "product_loom_compatibility" in HARD_RULES
    assert "loom_exclusive" in HARD_RULES
    assert "beam_exclusive" in HARD_RULES
    assert "beam_mounted_before_weave" in HARD_RULES
    assert "no_negative_material" in HARD_RULES
    assert "locked_task_immobile" in HARD_RULES
    assert "tooling_required" in HARD_RULES
    # 每条规则都应可配置（enabled 开关）
    for name, rule in HARD_RULES.items():
        assert name, "规则必须有键"
        assert rule["enabled"] in (True, False), f"{name} 缺少 enabled 开关"
        assert rule.get("desc"), "规则缺中文说明"


def test_objective_priority_order():
    # 优先降低交期延误 -> 再减少换款/换轴 -> 再减少计划变动
    assert OBJECTIVE_PRIORITY.index("minimize_tardiness") < OBJECTIVE_PRIORITY.index("minimize_changeover")
    assert OBJECTIVE_PRIORITY.index("minimize_changeover") < OBJECTIVE_PRIORITY.index("minimize_plan_change")


def test_objective_weights_prioritize_tardiness():
    assert OBJECTIVE_WEIGHTS["minimize_tardiness"] > OBJECTIVE_WEIGHTS["minimize_changeover"]
    assert OBJECTIVE_WEIGHTS["minimize_changeover"] > OBJECTIVE_WEIGHTS["minimize_plan_change"]


def test_time_params_have_horizon():
    assert TIME_PARAMS["time_unit"] == "day"
    assert TIME_PARAMS["plan_horizon_start"] <= TIME_PARAMS["plan_horizon_end"]
    assert TIME_PARAMS["current_date"]
    # 默认周日(7)休
    assert 7 in TIME_PARAMS["rest_days"]


def test_build_business_rules_serializable():
    rules = build_business_rules()
    assert rules["hard_rules"] is HARD_RULES
    assert "objective_priority" in rules
    assert "objective_weights" in rules
    assert "due_date_params" in rules
    assert "material_params" in rules
    assert rules == BUSINESS_RULES
