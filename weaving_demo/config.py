# -*- coding: utf-8 -*-
"""
config.py -- 整经织造排工排产 Demo · 可配置业务规则参数
===============================================================================
把本项目所有「关键业务规则」集中为独立、可配置的参数，避免散落在排程代码里。
本文件只定义「规则及其参数常量」，不包含任何求解逻辑。

所有字段均使用中文业务名称，键名用英文（机器可读），值即业务语义。
"""
from __future__ import annotations

from typing import Any, Dict, List

# 配置 / 代码版本（用于结果追溯字段）
CONFIG_VERSION: str = "3.3.0"
CODE_VERSION: str = "3.3.0"


# ============================================================================
# 一、硬约束规则（CP-SAT 必须满足，违反则不可解）
# ============================================================================
# 每条规则给出: 开关、说明、以及该规则涉及的参数。
HARD_RULES: Dict[str, Dict[str, Any]] = {
    # 1) 产品只能安排到满足工艺和硬件条件的织机（产品-机台适配）
    "product_loom_compatibility": {
        "enabled": True,
        "desc": "产品只能安排到满足工艺与硬件条件的织机。适配判定依据 "
                "可对应产品/钢筘/全幅边撑 + 工装(废边盘/切边/纱架/大卷装/水过滤)。",
        # 适配判定只按该列表里列出的工装逐项匹配；某织机缺任一必需工装则不可用。
        "compat_check_fields": [
            "reed",              # 钢筘
            "full_width_edge_support",  # 全幅边撑
            "waste_edge_disc",   # 废边盘
            "edge_cut",          # 切边
            "yarn_frame",        # 纱架
            "big_package",       # 大卷装
            "water_filter",      # 水过滤
        ],
        # 若产品没有明确写「可对应产品」，则按工装匹配；若写明则优先按清单硬匹配。
        "allow_compat_fallback_by_tooling": True,
    },

    # 2) 一台织机同一时间只能执行一个生产任务（机台独占）
    "loom_exclusive": {
        "enabled": True,
        "desc": "一台织机同一时间只能执行一个生产任务；通过 AddNoOverlap 对每台织机上的任务区间建立独占。",
        "per_loom_capacity": 1,   # 单台织机同一时刻可并行执行的任务数（通常为 1）
    },

    # 3) 同一根经轴不能同时供给多台织机（经轴独占）
    "beam_exclusive": {
        "enabled": True,
        "desc": "同一根经轴(经轴品番的实体)同一时间只能上在一台织机上。",
        "per_beam_capacity": 1,
    },

    # 4) 经轴完成并上轴后，织造任务才能开始（上轴先于织造）
    "beam_mounted_before_weave": {
        "enabled": True,
        "desc": "织造任务开始前，其对应经轴必须已完成整经并完成上轴(轴已上机)。",
        # 上轴到织造之间允许的最短准备时间(天)，用于建模换轴/装轴。
        "beam_mount_lead_days": 0,
    },

    # 5) 物料库存不能出现负数
    "no_negative_material": {
        "enabled": True,
        "desc": "纱线等物料库存逐日推移，任何一天净库存不得为负；需求超出期初库存即约束不可行。",
        "allow_negative": False,
    },

    # 6) 已经开工、已经上轴或人工锁定的任务不能随意移动（任务锁定）
    "locked_task_immobile": {
        "enabled": True,
        "desc": "已开工/已上轴/人工锁定的任务在排程中固定其织机与(或)时间窗口，不得移动。",
        "lock_domains": ["loom", "start_time", "end_time"],  # 可分别锁定机台/开始/结束
    },

    # 7) 工装条件（废边盘/切边/钢筘/边撑/纱架等）必须满足
    "tooling_required": {
        "enabled": True,
        "desc": "织造任务要求的工装，织机必须具备；缺任一项不可排。工装清单见下。",
        "tooling_names": [
            "waste_edge_disc",         # 废边盘
            "edge_cut",                # 切边
            "reed",                    # 钢筘
            "full_width_edge_support", # 全幅边撑
            "yarn_frame",              # 纱架
        ],
    },
}


# ============================================================================
# 二、软目标（优化目标，按优先级从高到低）
# ============================================================================
# 业务要求: 优先降低交期延误 -> 再减少换款/换轴 -> 再减少计划变动。
OBJECTIVE_PRIORITY: List[str] = [
    "minimize_tardiness",    # 1st: 优先降低交期延误
    "minimize_changeover",   # 2nd: 换款/换轴/清机 最少
    "minimize_plan_change",  # 3rd: 计划变动(相对上次方案)最少
    "maximize_utilization",  # 4th: 利用率(辅助)
]

# 各软目标在加权目标函数中的相对权重（数值越大越优先）。
# 权重必须保证满足优先级顺序: tardiness 权重远大于 changeover，再大于 plan_change。
OBJECTIVE_WEIGHTS: Dict[str, float] = {
    "minimize_tardiness": 100.0,
    "minimize_changeover": 10.0,
    "minimize_plan_change": 1.0,
    "maximize_utilization": 0.1,
}

# 换款/换轴的定义 —— 触发一次换型的判据（用于统计与建模惩罚）。
CHANGEOVER_PENALTY: Dict[str, float] = {
    "style_change": 1.0,       # 同一织机相邻任务产品不同(换款)
    "beam_change": 1.0,        # 同一织机相邻任务经轴不同(换轴)
    "warp_reset": 0.5,         # 连续生产但需清机/重穿筘的附加惩罚
}


# ============================================================================
# 三、排程与时间相关参数
# ============================================================================
TIME_PARAMS: Dict[str, Any] = {
    # 排程的时间粒度与窗口
    "time_unit": "day",              # 排程基本时间单位：天
    "plan_horizon_start": "2026-04-01",  # 排程规划起点
    "plan_horizon_end": "2026-08-31",    # 排程规划终点(不含)
    "current_date": "2026-05-18",        # 数据当前日期(织造计划表头)
    # 织机停机/休息日(硬禁止排产)。取自织造计划表头的"休"标记，可由数据覆盖。
    "rest_days": [6, 7],                 # 周日=7, 周六=6 (星期)。默认周日休。
    # 求解器
    "solver": "ortools-cp-sat",
    "max_solve_time_s": 30.0,
    "num_workers": 8,
    "random_seed": 20260518,
}


# ============================================================================
# 四、产能与效率参数
# ============================================================================
CAPACITY_PARAMS: Dict[str, Any] = {
    # 织造效率口径: 米/天 (来自①基础资料"织造效率"，或②织机状态"产能设定")。
    # 若产品与织机两侧都给出，取小者并考虑折算系数。
    "weave_capacity_source": ["product.weave_efficiency", "loom.capacity_setting"],
    "efficiency_factor": 1.0,        # 综合效率折算系数
    "capacity_unit": "米/天",
    "loom_daily_hours": 24.0,        # 织机每日运行小时数
    "warping_capacity_m_per_day": None,  # 整经机每日可整经米数；未提供则建模时按数据推算
    "warp_beam_max_meters": None,        # 单只经轴最大可缠米数；未提供则用产品"整经设定长度"
}


# ============================================================================
# 五、交期与订单参数
# ============================================================================
DUE_DATE_PARAMS: Dict[str, Any] = {
    # 数据源中没有逐单交期，交期来源可由以下任一口径推导，可配置。
    "due_source": "customer_monthly_forecast",  # customer_monthly_forecast | sample_order | manual
    # 交期从客户月度预测按月份映射为当月月末。
    "due_by_month_end": True,
    # 由客户预测的月份（如 5月=15000 米）折算为交期，仅在缺明细订单时使用。
    "forecast_to_order": True,
    "forecast_unit": "米",
    # 若找不到交期，使用的兜底交期(相对排程起点之后的第 N 天)。
    "default_due_days_from_current": 60,
}


# ============================================================================
# 六、物料非负与库存推移参数
# ============================================================================
MATERIAL_PARAMS: Dict[str, Any] = {
    # 用于整经消耗的纱线单耗口径(KG/M 或 KG/㎡)。取①基础资料"纱线单耗 KG/M"。
    "yarn_consumption_unit": "KG/M",
    "inventory_boundary_check": "cumulative",  # cumulative | per_day
    "safety_stock_days": 0,                    # 预留安全库存天数
    "allow_arrival_planning": False,           # 是否允许把"到货"作为可调度资源(默认否)
}


# ============================================================================
# 七、汇总：把以上分组打包成一个可直接序列化/检查的配置对象
# ============================================================================
def build_business_rules() -> Dict[str, Any]:
    """把所有业务规则与参数汇总为一个字典，供排程/校验模块读取。

    返回的字典是纯数据（可 JSON 序列化），便于前端展示"当前规则配置"。
    """
    return {
        "hard_rules": HARD_RULES,
        "objective_priority": OBJECTIVE_PRIORITY,
        "objective_weights": OBJECTIVE_WEIGHTS,
        "changeover_penalty": CHANGEOVER_PENALTY,
        "time_params": TIME_PARAMS,
        "capacity_params": CAPACITY_PARAMS,
        "due_date_params": DUE_DATE_PARAMS,
        "material_params": MATERIAL_PARAMS,
        "stage2_params": STAGE2_PARAMS,
    }


# ============================================================================
# 八、阶段2（CP-SAT 排程）临时/可配置参数
# ============================================================================
# 时间单位统一为“分钟”；以下均为临时参数（结果/文档中须标明）。
STAGE2_PARAMS: Dict[str, Any] = {
    # ---- 变更/准备时间（分钟，临时参数）----
    "setup_minutes": {
        "drop_prep": 10,       # 落布准备时间
        "mount": 330,          # 普通上轴时间
        "threading": 480,      # 穿综穿筘时间
    },
    # 同产品、同工艺、同钢筘且不需重新穿综时，只计算落布 + 上轴；
    # 产品或工艺变化、需重新穿综时，增加 threading。
    "setup_rule": {
        "same_product_process_reed_only_drop_mount": True,
    },

    # ---- 物料 ----
    "safety_stock": 0,             # 安全库存(可配置，暂为 0)
    "confirmed_arrival_only": True,  # 仅"已确认到货"计入可用库存
    "allow_unscheduled_on_material_shortage": True,  # 物料不足时保留未排数量(而非直接INFEASIBLE)

    # ---- 锁定 ----
    "freeze_days": 3,              # 排程开始后 N 天为冻结期(锁定)
    "lock_conditions": ["started", "beam_mounted", "manual", "frozen"],

    # ---- 任务拆分 ----
    "split_default": {
        "enabled_default": False,   # 默认不允许拆分
        "min_batch_qty": 500.0,     # 最小拆分批量(米)
        "max_parts": 3,             # 最大拆分份数
    },

    # ---- 虚拟经轴实体 ----
    "virtual_beam_prefix": "WB",   # 虚拟经轴编号前缀 WB-<品番>-001
    "virtual_beam_enabled": True,  # 数据无实体经轴，允许生成虚拟实体

    # ---- 求解 ----
    "horizon_start": "2026-04-01",
    "horizon_end": "2026-08-31",
    "horizon_minutes": None,       # 运行时按终止日-起点计算(分钟)
    "lexicographic_tolerances": {   # 各层允许的小容差
        "unscheduled_quantity": 0,
        "weighted_tardiness": 0,
        "max_tardiness": 0,
        "task_split_count": 0,
        "machine_spread_count": 0,
        "changeover_count": 0,
        "plan_change_count": 0,
        "utilization": 0,
    },
    # 8 层字典序目标（先后顺序即优先级）。启用机台成本不得高于交期目标。
    "objective_layers": [
        "unscheduled_quantity",     # L1 未排数量
        "weighted_tardiness",       # L2 加权交期延误
        "max_tardiness",            # L3 最大交期延误
        "task_split_count",         # L4 任务拆分份数
        "machine_spread_count",     # L5 启用机台数量 + 任务分散
        "changeover_count",         # L6 换款/换轴/穿综穿筘
        "plan_change_count",        # L7 相对原计划变动
        "utilization",              # L8 提高利用率(结果不变时)
    ],
    # 启用机台/任务分散的成本(仅作为 L5/L4 层目标，不得高于交期层)
    "machine_spread_penalty": {"loom_activation": 1.0, "task_dispersion": 0.5},
    # 适配模式
    "compatibility_mode": "balanced",   # strict | balanced | simulation
    # 物料/经轴诊断开关(用于 A/B/C/D 对照)
    "material_enabled": True,
    "beam_enabled": True,
    # 利用率分子/分母口径
    "available_machine_deduct": {
        "maintenance": True,        # 扣除维修时间
        "stop": True,               # 扣除停机(状态不可用/锁定占用)
        "forbidden": True,          # 扣除禁排时间
        "outside_shift": False,     # 扣除班次外时间(未提供班次，暂不扣)
    },
    "max_solve_time_s": 30.0,
    "random_seed": 20260518,
    "num_workers": 1,       # 1 保证可复现
}

# 阶段2 工装范围（机台已安装能力 vs 仓库可调配工装 vs 产品要求）
TOOLING_SCOPE: Dict[str, Any] = {
    # 机台已安装能力(boolean) 字段名
    "installed_capability_keys": [
        "waste_edge_disc",        # 废边盘(类型)
        "waste_edge_hole_pos",    # 废边盘安装孔位
        "edge_cut",               # 切边装置
        "reed",                   # 钢筘
        "full_width_edge_support",# 全幅边撑
        "gear_or_aluminum_wheel", # 齿轮或铝轮
        "heald",                  # 综丝
        "yarn_frame",             # 纱架
        "big_package",            # 大卷装
        "water_filter",           # 水过滤
    ],
    # 仓库可调配工装数量(尚未建档 -> 校验时产生"工装库存未建档"警告)
    "warehouse_stock_keys": [
        "waste_edge_disc", "edge_cut", "reed", "full_width_edge_support",
        "gear_or_aluminum_wheel", "heald", "yarn_frame",
    ],
    "warehouse_stock_available": {},   # 暂为空 -> 仅校验机台已安装配置
}

# 全局唯一的规则配置对象（其它模块统一从这里读参数）
BUSINESS_RULES: Dict[str, Any] = build_business_rules()
