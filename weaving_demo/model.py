# -*- coding: utf-8 -*-
"""
model.py -- 整经织造排工排产 Demo · 领域数据模型
===============================================================================
定义整经织造业务的领域实体（产品、织机、工艺条件、经轴、整经任务、织造任务、
落布预测、物料、交期、全局设置）。全部为可 JSON 序列化的 dataclass，
字段名用英文（机器可读，便于交换），字段含义用中文注释/字段说明标注。

本模块只负责「数据承载 + 基本类型校验」，不包含排程逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Union


# ============================================================================
# 全局设置
# ============================================================================
@dataclass
class Settings:
    """排程/数据的全局设置。"""
    当前日期: Optional[str] = None          # 如 2026-05-18（织造计划表头“当前日期”）
    数据节点: Optional[str] = None          # 数据节点备注
    卷曲率: Optional[float] = None          # 经纱卷曲率，如 0.08
    休日: List[int] = field(default_factory=lambda: [7])  # 星期几休（7=周日）
    排程起点: Optional[str] = None          # 规划期起点
    排程终点: Optional[str] = None          # 规划期终点(不含)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 产品（织造/后整的对象）
# ============================================================================
@dataclass
class Product:
    """产品与工艺资料。来源：①基础资料；织造参数由“工艺汇总背番号”补充。"""
    产品款号: str                        # 产品款号（如 PH555120）
    经轴款号: str                        # 经轴款号（通常与产品款号同）
    客户款号: Optional[str] = None       # 客户款号
    客户: Optional[str] = None           # 客户（AB/TG/YFSS…）
    目前阶段: Optional[str] = None       # 目前阶段（PV??/SOP/暂停）
    使用纱线: Optional[str] = None       # 使用纱线（如 LS7056AB）
    整经设定长度: Optional[float] = None  # 整经设定长度（米/卷）
    织造效率: Optional[float] = None     # 织造效率（米/天）
    水洗速度: Optional[float] = None     # 水洗速度（米/分钟）
    涂层速度: Optional[float] = None     # 涂层速度（米/分钟）
    验布速度: Optional[float] = None     # 验布速度（米/分钟）
    有效门幅: Optional[float] = None     # 有效门幅（米）
    经密: Optional[float] = None         # 经密（根/英寸或根/厘米，按数据口径）
    纬密: Optional[float] = None         # 纬密
    幅宽: Optional[float] = None         # 织造幅宽（米）
    钢筘型号: Optional[str] = None       # 钢筘型号（如 8.4、9.3钢筘）
    纱线单耗KG_M: Optional[float] = None  # 纱线单耗（KG/米）
    纱线单耗KG_M2: Optional[float] = None  # 纱线单耗（KG/平方米）
    硅胶: Optional[str] = None           # 硅胶型号
    硅胶单耗KG_M: Optional[float] = None  # 硅胶单耗（KG/米）
    硅胶单耗KG_M2: Optional[float] = None  # 硅胶单耗（KG/平方米）
    工装要求: List[str] = field(default_factory=list)  # 该产品要求的工装清单
    allowed_loom_ids: List[str] = field(default_factory=list)  # 明确允许的织机清单(空=按能力匹配)
    备注: Optional[str] = None

    @property
    def 名称(self) -> str:
        return self.产品款号

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 织机（含机台能力/工装）
# ============================================================================
@dataclass
class Loom:
    """织机状态及机台能力。来源：②织机状态（区域1~9），能力列即工装条件。"""
    织机号: str                          # 如 #301
    区域: Optional[str] = None           # 区域（区域1…区域9）
    当前状态: Optional[str] = None       # 当前状态（未安排/AB/YFSS/AB开发用/TG爬坡/YFSS量产/NULL）
    目前对应产品: Optional[str] = None   # 目前对应产品（可空/0）
    产能设定: Optional[float] = None     # 产能设定（米/天）
    # ---- 工装/能力（0/1 布尔） ----
    废边盘: Optional[bool] = None        # 是否具备废边盘
    废边盘安装孔位: Optional[str] = None  # 废边盘安装孔位
    切边: Optional[bool] = None          # 是否可切边
    大卷装: Optional[bool] = None        # 是否大卷装
    水过滤: Optional[bool] = None        # 是否水过滤
    纱架: Optional[bool] = None          # 是否纱架
    齿轮或铝轮: Optional[bool] = None    # 是否具备齿轮或铝轮
    综丝: Optional[bool] = None          # 是否具备综丝
    # ---- 其它工装/能力 ----
    钢筘: Optional[str] = None           # 钢筘（如 9.3钢筘）
    全幅边撑: Optional[str] = None       # 全幅边撑（如 2350、2.55M）
    可对应产品: List[str] = field(default_factory=list)  # 可对应产品清单
    备注: Optional[str] = None
    切边配置简述: Optional[str] = None   # 切边配置简述（可切边/无）
    废边盘备注: Optional[str] = None
    纱架备注: Optional[str] = None

    @property
    def 状态可用(self) -> bool:
        """是否处于可排产状态（未安排/量产/开发用等）；NULL 或 0 视为不可用/待确认。"""
        s = (self.当前状态 or "").strip()
        if s in ("NULL", "0", "未安装"):
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 工艺条件（后整）
# ============================================================================
@dataclass
class ProcessCondition:
    """水洗/涂层等后整工艺条件。来源：工艺条件。"""
    品番: str
    客户品番: Optional[str] = None
    工艺合并: Optional[str] = None
    水洗1号温度: Optional[float] = None
    水洗2号温度: Optional[float] = None
    水洗1号张力: Optional[float] = None
    水洗2号张力: Optional[float] = None
    烘房温度: Optional[float] = None
    烘桶温度: Optional[float] = None
    速度: Optional[float] = None
    备注: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 经轴
# ============================================================================
@dataclass
class WarpBeam:
    """经轴（整经产物）。来源：整经预测辅助表 / ①基础资料。"""
    经轴品番: str                        # 如 WN446
    产品款号: Optional[str] = None       # 对应产品
    经纱: Optional[str] = None           # 经纱（使用纱线）
    设定米数: Optional[float] = None     # 设定米数（整经设定长度）
    整经根数: Optional[float] = None     # 整经根数（经纱根数）
    钢筘: Optional[str] = None           # 钢筘型号
    使用纱线: Optional[str] = None       # 使用纱线
    单耗KG: Optional[float] = None       # 单耗（KG）
    初始库存: Optional[float] = None     # 初始库存（轴/米）
    状态: Optional[str] = None           # 可空；如 已上轴/库存/整经中
    备注: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 任务类（带按日期矩阵的数值）
# ============================================================================
# 一种通用的“按日期推移”数值载体：content 表示该行含义（如 落布数量/上轴/轴个数），
# daily 为 {日期ISO: 数值}。
DateMatrix = Dict[str, float]


@dataclass
class WarpingTask:
    """整经任务（整经计划）。来源：整经计划。"""
    织机: str                            # 织机（整经机位）
    当前生产品番: Optional[str] = None
    产品背番号: Optional[str] = None
    织造品番: Optional[str] = None
    经轴品番: Optional[str] = None
    整经基础设定数量: Optional[float] = None
    内容: Optional[str] = None           # 轴个数 / 上轴
    期初库存: Optional[float] = None     # 期初库存5/30
    日常: DateMatrix = field(default_factory=dict)  # {日期: 数值}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WeavingTask:
    """织造任务（织造计划）。来源：织造计划。"""
    织机: str
    织机当前状态: Optional[str] = None
    当前生产品番: Optional[str] = None
    产品背番号: Optional[str] = None
    织造品番: Optional[str] = None
    经轴品番: Optional[str] = None
    产能设定: Optional[float] = None
    门幅: Optional[float] = None
    纱线规格: Optional[str] = None
    单耗50: Optional[float] = None
    内容: Optional[str] = None           # 落布数量 等
    日常: DateMatrix = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClothDropForecast:
    """落布预测。来源：落布预测（每织机 落布数量/上轴 两行）。"""
    织机: str
    织机当前状态: Optional[str] = None
    当前生产品番: Optional[str] = None
    产品背番号: Optional[str] = None
    织造品番: Optional[str] = None
    经轴品番: Optional[str] = None
    内容: Optional[str] = None           # 落布数量 / 上轴
    期初库存: Optional[float] = None
    日常: DateMatrix = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 物料（纱线等）
# ============================================================================
@dataclass
class YarnMaterial:
    """纱线等物料库存与推移。来源：材料需求。"""
    纱线名称: str                        # 如 涤纶纱线
    纱线代码: str                        # 使用纱线（如 LS7056AB）
    规格: Optional[str] = None           # 规格（如 PET550dtex）
    期初库存: Optional[float] = None
    内容: Optional[str] = None           # 库存/到货kg/到货托/整经计划/织布计划
    日常: DateMatrix = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 交期（客户需求 → 生产任务；数据源未给逐单交期，由客户月度预测或样例推导）
# ============================================================================
@dataclass
class DueDate:
    """交期与客户需求。"""
    产品款号: str
    客户: Optional[str] = None
    月份: Optional[str] = None           # 如 2026-05
    预测数量: Optional[float] = None     # 该月客户预测（米）
    交期: Optional[str] = None           # 交期（ISO 日期）
    优先级: Optional[float] = None       # 优先级（越大越优先，可配置）
    来源: Optional[str] = None           # customer_monthly_forecast / sample_order / manual

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 生产任务（阶段2 排程对象）
# ============================================================================
@dataclass
class ProductionTask:
    """织造生产任务：阶段2 CP-SAT 排程的最小调度单元。
       需求数量、交期、优先级可分派到兼容织机；可拆分或不拆分。"""
    task_id: str
    product_id: str                      # 产品款号
    required_quantity: float             # 需求数量(米)
    scheduled_quantity: float = 0.0      # 已排数量(米, 诊断用)
    unscheduled_quantity: float = 0.0    # 未排数量(米, 诊断用)
    due_date: Optional[str] = None       # 交期(ISO)
    due_minute: Optional[int] = None     # 交期(分钟偏移)
    priority: float = 1.0                # 优先级(越大越优先)
    split_allowed: bool = False          # 是否允许拆分
    min_batch_qty: Optional[float] = None  # 最小拆分批量(米)
    max_parts: Optional[int] = None      # 最大拆分份数
    # 变更判据(同即不需重穿综穿筘)
    process: Optional[str] = None        # 工艺合并
    reed: Optional[str] = None           # 钢筘
    # 兼容织机清单(由 compat 计算; 空=无兼容->不可排)
    allowed_loom_ids: List[str] = field(default_factory=list)
    # 来源业务表的目标织机。非空时必须与工装兼容清单取交集。
    source_target_loom_ids: List[str] = field(default_factory=list)
    # mapped / missing_trial / missing_blocked / invalid_blocked
    target_mapping_status: Optional[str] = None
    # 经轴需求
    beam_code: Optional[str] = None      # 经轴品番(可为空)
    # 原计划(用于 计划变动 目标)
    original_loom_id: Optional[str] = None
    original_start_minute: Optional[int] = None
    # 锁定
    locked: bool = False
    locked_machine_id: Optional[str] = None
    locked_start: Optional[str] = None
    locked_end: Optional[str] = None
    locked_start_minute: Optional[int] = None
    locked_end_minute: Optional[int] = None
    locked_quantity: Optional[float] = None
    lock_reason: Optional[str] = None
    来源: Optional[str] = None           # 数据来源(derive/sample/import)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 虚拟经轴实体（阶段2 数据无实体经轴时生成）
# ============================================================================
@dataclass
class VirtualBeam:
    """虚拟经轴实体。编号如 WB-PH54512B-001。"""
    beam_id: str                         # 实体编号 WB-PH54512B-001
    beam_code: str                       # 经轴品番
    product_id: Optional[str] = None
    total_length: Optional[float] = None   # 总长度(米)
    remaining_length: Optional[float] = None  # 剩余长度(米)
    earliest_available_minute: int = 0   # 最早可用时间(分钟偏移)
    earliest_available: Optional[str] = None  # ISO
    status: Optional[str] = None         # 库存/已上轴/整经中
    current_loom_id: Optional[str] = None  # 当前所在机台
    is_derived: bool = True              # 是否为推导(虚拟)数据

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 滚动车间状态（阶段一）
# ============================================================================
@dataclass
class LoomRuntimeSnapshot:
    """滚动窗口起点的一台织机及机上经轴状态。"""
    loom_id: str
    current_product_id: Optional[str] = None
    current_task_id: Optional[str] = None
    current_beam_id: Optional[str] = None
    remaining_beam_m: float = 0.0
    edge_support_uses: int = 0
    edge_support_limit: int = 5
    available_minute: int = 0
    available_at: Optional[str] = None
    status: str = "available"
    expected_completion_at: Optional[str] = None
    expected_dooff_at: Optional[str] = None
    expected_recovery_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BeamInstance:
    """可追溯的实体或推导经轴实例，以及其当前库存位置。"""
    beam_id: str
    beam_code: str
    product_id: Optional[str] = None
    total_meters: Optional[float] = None
    remaining_meters: float = 0.0
    location_type: str = "warehouse"  # warehouse / loom / line_side / warping / threading
    location_id: Optional[str] = None
    status: str = "available"
    quality_status: str = "qualified"
    ready_at: Optional[str] = None
    is_derived: bool = False
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionEvent:
    """实际生产或异常事件；阶段一先作为快照证据保存。"""
    event_id: str
    event_type: str
    occurred_at: str
    loom_id: Optional[str] = None
    task_id: Optional[str] = None
    product_id: Optional[str] = None
    beam_id: Optional[str] = None
    quantity_m: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ShopFloorSnapshot:
    """一次可版本化、可追溯的滚动车间状态快照。"""
    snapshot_id: str
    version: int
    captured_at: str
    source: str = "manual"
    schedule_id: Optional[str] = None
    parent_snapshot_id: Optional[str] = None
    looms: List[LoomRuntimeSnapshot] = field(default_factory=list)
    beams: List[BeamInstance] = field(default_factory=list)
    events: List[ExecutionEvent] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScheduleVersion:
    """排程版本与输入车间快照之间的追溯关系。"""
    schedule_version_id: str
    schedule_id: str
    version: int
    snapshot_id: str
    created_at: str
    status: str = "draft"
    parent_schedule_version_id: Optional[str] = None
    trigger_event_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 整个场景（一次排程的完整输入）
# ============================================================================
@dataclass
class WeavingScenario:
    """整经织造场景：一次排程所需的全部领域数据。"""
    设置: Optional[Settings] = None
    产品: List[Product] = field(default_factory=list)
    织机: List[Loom] = field(default_factory=list)
    工艺条件: List[ProcessCondition] = field(default_factory=list)
    经轴: List[WarpBeam] = field(default_factory=list)
    整经任务: List[WarpingTask] = field(default_factory=list)
    织造任务: List[WeavingTask] = field(default_factory=list)
    落布预测: List[ClothDropForecast] = field(default_factory=list)
    物料: List[YarnMaterial] = field(default_factory=list)
    交期: List[DueDate] = field(default_factory=list)
    生产任务: List[ProductionTask] = field(default_factory=list)  # 阶段2 排程任务(可显式给定)
    虚拟经轴: List[VirtualBeam] = field(default_factory=list)      # 阶段2 生成的虚拟经轴
    维护区间: List[Dict[str, Any]] = field(default_factory=list)    # [{loom_id,start_minute,end_minute}]
    规则配置: Dict[str, Any] = field(default_factory=dict)  # 来自 config.BUSINESS_RULES
    数据来源: Optional[str] = None        # 源文件名
    提取时间: Optional[str] = None
    校验报告: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 便利函数
# ============================================================================
def date_matrix_to_list(dm: DateMatrix) -> List[Dict[str, Any]]:
    """把 {日期: 数值} 转换为有序列表 [{date, value}]（按日期升序）。"""
    return [{"date": k, "value": v} for k, v in sorted(dm.items())]


def as_jsonable(obj: Any) -> Any:
    """递归转换为可 JSON 序列化的纯 Python 对象。"""
    if hasattr(obj, "to_dict"):
        return as_jsonable(obj.to_dict())
    if isinstance(obj, dict):
        return {k: as_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [as_jsonable(v) for v in obj]
    return obj
