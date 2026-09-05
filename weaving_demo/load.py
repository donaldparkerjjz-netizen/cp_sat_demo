# -*- coding: utf-8 -*-
"""
load.py -- 整经织造排工排产 Demo · 场景装载（JSON <-> 领域模型）
===============================================================================
把 extract.py 产出的 JSON（即 WeavingScenario.to_dict()）反向装载为领域对象，
供后续排程/校验/前端使用；并做基础容器构建与校验。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from weaving_demo.model import (
    Settings, Product, Loom, ProcessCondition, WarpBeam,
    WarpingTask, WeavingTask, ClothDropForecast, YarnMaterial, DueDate,
    ProductionTask, VirtualBeam, WeavingScenario,
)


def _settings_from(d: Dict[str, Any]) -> Settings:
    return Settings(**{k: v for k, v in d.items() if k in Settings.__dataclass_fields__})


def _products_from(items: List[Dict[str, Any]]) -> List[Product]:
    return [Product(**{k: v for k, v in it.items() if k in Product.__dataclass_fields__}) for it in items]


def _looms_from(items: List[Dict[str, Any]]) -> List[Loom]:
    return [Loom(**{k: v for k, v in it.items() if k in Loom.__dataclass_fields__}) for it in items]


def _process_from(items: List[Dict[str, Any]]) -> List[ProcessCondition]:
    return [ProcessCondition(**{k: v for k, v in it.items() if k in ProcessCondition.__dataclass_fields__}) for it in items]


def _beams_from(items: List[Dict[str, Any]]) -> List[WarpBeam]:
    return [WarpBeam(**{k: v for k, v in it.items() if k in WarpBeam.__dataclass_fields__}) for it in items]


def _warping_from(items: List[Dict[str, Any]]) -> List[WarpingTask]:
    return [WarpingTask(**{k: v for k, v in it.items() if k in WarpingTask.__dataclass_fields__}) for it in items]


def _weaving_from(items: List[Dict[str, Any]]) -> List[WeavingTask]:
    return [WeavingTask(**{k: v for k, v in it.items() if k in WeavingTask.__dataclass_fields__}) for it in items]


def _drop_from(items: List[Dict[str, Any]]) -> List[ClothDropForecast]:
    return [ClothDropForecast(**{k: v for k, v in it.items() if k in ClothDropForecast.__dataclass_fields__}) for it in items]


def _materials_from(items: List[Dict[str, Any]]) -> List[YarnMaterial]:
    return [YarnMaterial(**{k: v for k, v in it.items() if k in YarnMaterial.__dataclass_fields__}) for it in items]


def _dues_from(items: List[Dict[str, Any]]) -> List[DueDate]:
    return [DueDate(**{k: v for k, v in it.items() if k in DueDate.__dataclass_fields__}) for it in items]


def _tasks_from(items: List[Dict[str, Any]]) -> List[ProductionTask]:
    return [ProductionTask(**{k: v for k, v in it.items() if k in ProductionTask.__dataclass_fields__}) for it in items]


def _beams_virtual_from(items: List[Dict[str, Any]]) -> List[VirtualBeam]:
    return [VirtualBeam(**{k: v for k, v in it.items() if k in VirtualBeam.__dataclass_fields__}) for it in items]


def scenario_from_dict(d: Dict[str, Any]) -> WeavingScenario:
    """从 extract.py 输出的 dict（to_dict()）重建 WeavingScenario。"""
    return WeavingScenario(
        设置=_settings_from(d.get("设置") or {}),
        产品=_products_from(d.get("产品") or []),
        织机=_looms_from(d.get("织机") or []),
        工艺条件=_process_from(d.get("工艺条件") or []),
        经轴=_beams_from(d.get("经轴") or []),
        整经任务=_warping_from(d.get("整经任务") or []),
        织造任务=_weaving_from(d.get("织造任务") or []),
        落布预测=_drop_from(d.get("落布预测") or []),
        物料=_materials_from(d.get("物料") or []),
        交期=_dues_from(d.get("交期") or []),
        生产任务=_tasks_from(d.get("生产任务") or []),
        虚拟经轴=_beams_virtual_from(d.get("虚拟经轴") or []),
        维护区间=list(d.get("维护区间") or []),
        规则配置=dict(d.get("规则配置") or {}),
        数据来源=d.get("数据来源"),
        提取时间=d.get("提取时间"),
        校验报告=dict(d.get("校验报告") or {}),
    )


def load_json(path: str) -> WeavingScenario:
    with open(path, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    return scenario_from_dict(d)
