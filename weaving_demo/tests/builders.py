# -*- coding: utf-8 -*-
"""test 场景构建辅助。"""
from typing import List, Optional

from weaving_demo.model import (
    Product, Loom, WeavingScenario, ProductionTask, Settings, VirtualBeam, YarnMaterial,
)


def mk_product(code: str, effic=400.0, width=2.25, reed="9.3钢筘",
               yarn="LS7056AB", consump=0.63, beam=None, allowed_looms=None) -> Product:
    return Product(
        产品款号=code, 经轴款号=beam or code, 使用纱线=yarn, 整经设定长度=3600,
        织造效率=effic, 有效门幅=width, 钢筘型号=reed, 纱线单耗KG_M=consump,
        allowed_loom_ids=allowed_looms or [],
    )


def mk_loom(code: str, status="未安排", current=None, reed="9.3钢筘", edge="2350",
            edge_disc=True, edge_cut=True, yarn_frame=True, big=True, water=True,
            gear=False, heald=False, applicable=None) -> Loom:
    return Loom(
        织机号=code, 区域=None, 当前状态=status, 目前对应产品=current,
        废边盘=edge_disc, 废边盘安装孔位="1", 切边=edge_cut, 大卷装=big, 水过滤=water,
        纱架=yarn_frame, 齿轮或铝轮=gear, 综丝=heald, 钢筘=reed, 全幅边撑=edge,
        可对应产品=applicable or [],
    )


def mk_task(tid, product, qty, due_minute=500000, priority=1.0, split=False,
            min_batch=None, parts=None, beam=None, allowed=None, original=None,
            locked=False, lock_machine=None, lock_start=None, lock_end=None,
            lock_qty=None, lock_reason=None, process=None, reed=None) -> ProductionTask:
    return ProductionTask(
        task_id=tid, product_id=product, required_quantity=float(qty),
        due_minute=due_minute, priority=priority, split_allowed=split,
        min_batch_qty=min_batch, max_parts=parts, process=process, reed=reed,
        beam_code=beam, allowed_loom_ids=allowed or [], original_loom_id=original,
        locked=locked, locked_machine_id=lock_machine, locked_start_minute=lock_start,
        locked_end_minute=lock_end, locked_quantity=lock_qty, lock_reason=lock_reason,
    )


def mk_scenario(products=None, looms=None, tasks=None, materials=None, beams=None,
                maints=None, start="2026-04-01", end="2026-05-01") -> WeavingScenario:
    return WeavingScenario(
        设置=Settings(当前日期=start, 排程起点=start, 排程终点=end),
        产品=products or [], 织机=looms or [], 生产任务=tasks or [],
        物料=materials or [], 虚拟经轴=beams or [], 维护区间=maints or [],
    )


def mk_material(code, avail=1000.0, spec="PET550dtex", name="涤纶纱线") -> YarnMaterial:
    return YarnMaterial(纱线名称=name, 纱线代码=code, 规格=spec,
                        内容="库存", 期初库存=avail, 日常={"2026-04-01": avail})
