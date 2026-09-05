# -*- coding: utf-8 -*-
"""滚动车间状态快照：版本化持久化、校验及模拟状态转换。"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from weaving_demo.model import (
    BeamInstance,
    ExecutionEvent,
    LoomRuntimeSnapshot,
    ShopFloorSnapshot,
    WeavingScenario,
)


DEFAULT_STORE_PATH = Path(__file__).resolve().parent / "runtime_data" / "shopfloor_snapshots.json"
DEFAULT_SIMULATION_SEED = 20260604


def _now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"


def _filtered(cls, payload: Mapping[str, Any]):
    return cls(**{k: copy.deepcopy(v) for k, v in payload.items()
                  if k in cls.__dataclass_fields__})


def snapshot_from_dict(payload: Mapping[str, Any]) -> ShopFloorSnapshot:
    return ShopFloorSnapshot(
        snapshot_id=str(payload.get("snapshot_id") or ""),
        version=int(payload.get("version") or 0),
        captured_at=str(payload.get("captured_at") or _now_iso()),
        source=str(payload.get("source") or "manual"),
        schedule_id=payload.get("schedule_id"),
        parent_snapshot_id=payload.get("parent_snapshot_id"),
        looms=[_filtered(LoomRuntimeSnapshot, row) for row in payload.get("looms", [])],
        beams=[_filtered(BeamInstance, row) for row in payload.get("beams", [])],
        events=[_filtered(ExecutionEvent, row) for row in payload.get("events", [])],
        metadata=copy.deepcopy(payload.get("metadata") or {}),
    )


def build_default_snapshot(scenario: WeavingScenario) -> ShopFloorSnapshot:
    """从织机主档生成版本0种子；只有显式保存后才成为版本1。"""
    captured_at = _now_iso()
    return ShopFloorSnapshot(
        snapshot_id="bootstrap",
        version=0,
        captured_at=captured_at,
        source="loom_master_bootstrap",
        looms=[
            LoomRuntimeSnapshot(
                loom_id=loom.织机号,
                current_product_id=_clean_product(loom.目前对应产品),
                status="available" if loom.状态可用 else "unavailable",
                updated_at=captured_at,
            )
            for loom in scenario.织机
        ],
        metadata={"is_bootstrap": True, "note": "缺少现场快照，按织机主档保守初始化"},
    )


def build_simulated_snapshot(
    scenario: WeavingScenario,
    *,
    seed: int = DEFAULT_SIMULATION_SEED,
    captured_at: Optional[str] = None,
) -> ShopFloorSnapshot:
    """按Excel主档生成确定性的合理模拟期初状态。

    模拟只补齐现场暂缺的实体轴号、余轴、边撑次数、报工及少量异常；
    机台、当前产品、经轴长度和日产能仍来自当前场景主档。
    """
    rng = random.Random(seed)
    captured_at = captured_at or _simulation_capture_time(scenario)
    captured_dt = dt.datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    products = {product.产品款号: product for product in scenario.产品}
    beams_by_product = {
        beam.产品款号: beam for beam in scenario.经轴 if beam.产品款号
    }

    active = [
        loom for loom in scenario.织机
        if loom.状态可用 and _clean_product(loom.目前对应产品) in products
    ]
    fault_loom_id = active[5].织机号 if len(active) > 5 else None
    shortage_loom_id = active[11].织机号 if len(active) > 11 else None
    maintenance_loom = next(
        (loom for loom in scenario.织机
         if loom.状态可用 and not _clean_product(loom.目前对应产品)),
        None,
    )

    looms: List[LoomRuntimeSnapshot] = []
    beams: List[BeamInstance] = []
    events: List[ExecutionEvent] = []
    line_side_targets: Dict[str, str] = {}

    for index, loom in enumerate(scenario.织机):
        product_id = _clean_product(loom.目前对应产品)
        product = products.get(product_id or "")
        status = "idle" if loom.状态可用 else "unavailable"
        available_minute = 0
        expected_recovery_at = None
        current_task_id = None
        current_beam_id = None
        remaining_m = 0.0
        expected_completion_at = None
        expected_dooff_at = None
        edge_support_uses = 0

        if maintenance_loom and loom.织机号 == maintenance_loom.织机号:
            status = "maintenance"
            available_minute = 480
            expected_recovery_at = _add_minutes(captured_dt, available_minute)
            events.append(ExecutionEvent(
                event_id=f"SIM-EVT-MAINT-{_id_token(loom.织机号)}",
                event_type="maintenance_started",
                occurred_at=captured_at,
                loom_id=loom.织机号,
                details={
                    "reason": "模拟预防性保养",
                    "expected_recovery_at": expected_recovery_at,
                    "data_source": "simulated",
                },
            ))
        elif product is not None:
            status = "running"
            current_task_id = f"SIM-WIP-{_id_token(loom.织机号)}-{product_id}"
            current_beam_id = f"SIM-BEAM-{_id_token(loom.织机号)}-001"
            source_beam = beams_by_product.get(product_id or "")
            total_m = float(
                (source_beam.设定米数 if source_beam else None)
                or product.整经设定长度
                or 3600.0
            )
            # 保留18%～88%的余轴，并取整到10米，覆盖续产、接经和临近落布场景。
            remaining_ratio = 0.18 + ((index * 17 + rng.randint(0, 12)) % 71) / 100.0
            remaining_m = min(total_m, max(100.0, round(total_m * remaining_ratio / 10.0) * 10.0))
            daily_capacity = float(loom.产能设定 or product.织造效率 or 400.0)
            production_minutes = max(1, int(round(remaining_m / daily_capacity * 1440)))
            edge_support_uses = (index + seed) % 6

            if loom.织机号 == fault_loom_id:
                status = "fault"
                available_minute = 360
                expected_recovery_at = _add_minutes(captured_dt, available_minute)
                events.append(ExecutionEvent(
                    event_id=f"SIM-EVT-FAULT-{_id_token(loom.织机号)}",
                    event_type="fault_started",
                    occurred_at=captured_at,
                    loom_id=loom.织机号,
                    task_id=current_task_id,
                    product_id=product_id,
                    beam_id=current_beam_id,
                    details={
                        "reason": "模拟纬停传感器故障",
                        "expected_recovery_at": expected_recovery_at,
                        "data_source": "simulated",
                    },
                ))
            elif loom.织机号 == shortage_loom_id:
                status = "material_shortage"
                available_minute = 240
                expected_recovery_at = _add_minutes(captured_dt, available_minute)
                events.append(ExecutionEvent(
                    event_id=f"SIM-EVT-SHORTAGE-{_id_token(loom.织机号)}",
                    event_type="material_shortage",
                    occurred_at=captured_at,
                    loom_id=loom.织机号,
                    task_id=current_task_id,
                    product_id=product_id,
                    beam_id=current_beam_id,
                    details={
                        "reason": "模拟纬纱补料等待",
                        "expected_recovery_at": expected_recovery_at,
                        "data_source": "simulated",
                    },
                ))

            expected_completion_at = _add_minutes(
                captured_dt, available_minute + production_minutes
            )
            expected_dooff_at = expected_completion_at
            beam_code = (
                source_beam.经轴品番 if source_beam else product.经轴款号
            ) or product_id
            beams.append(BeamInstance(
                beam_id=current_beam_id,
                beam_code=beam_code,
                product_id=product_id,
                total_meters=total_m,
                remaining_meters=remaining_m,
                location_type="loom",
                location_id=loom.织机号,
                status="on_loom",
                quality_status="qualified",
                ready_at=captured_at,
                is_derived=True,
                updated_at=captured_at,
            ))
            line_side_targets.setdefault(product_id, loom.织机号)

            performance = 0.82 + ((index * 7 + rng.randint(0, 8)) % 20) / 100.0
            reported_m = round(daily_capacity * performance, 1)
            events.append(ExecutionEvent(
                event_id=f"SIM-EVT-REPORT-{_id_token(loom.织机号)}",
                event_type="production_report",
                occurred_at=captured_at,
                loom_id=loom.织机号,
                task_id=current_task_id,
                product_id=product_id,
                beam_id=current_beam_id,
                quantity_m=reported_m,
                details={
                    "period": "previous_24h",
                    "planned_capacity_m": daily_capacity,
                    "performance_ratio": round(performance, 2),
                    "data_source": "simulated",
                },
            ))

        looms.append(LoomRuntimeSnapshot(
            loom_id=loom.织机号,
            current_product_id=product_id if product is not None else None,
            current_task_id=current_task_id,
            current_beam_id=current_beam_id,
            remaining_beam_m=remaining_m,
            edge_support_uses=edge_support_uses,
            edge_support_limit=5,
            available_minute=available_minute,
            status=status,
            expected_completion_at=expected_completion_at,
            expected_dooff_at=expected_dooff_at,
            expected_recovery_at=expected_recovery_at,
            updated_at=captured_at,
        ))

    # 每个在产产品补一根合格线边备轴，供备轴/FIFO流程演示。
    for product_id, loom_id in sorted(line_side_targets.items()):
        product = products[product_id]
        source_beam = beams_by_product.get(product_id)
        total_m = float(
            (source_beam.设定米数 if source_beam else None)
            or product.整经设定长度
            or 3600.0
        )
        beams.append(BeamInstance(
            beam_id=f"SIM-LS-{_id_token(product_id)}-001",
            beam_code=(source_beam.经轴品番 if source_beam else product.经轴款号) or product_id,
            product_id=product_id,
            total_meters=total_m,
            remaining_meters=total_m,
            location_type="line_side",
            location_id=loom_id,
            status="available",
            quality_status="qualified",
            ready_at=captured_at,
            is_derived=True,
            updated_at=captured_at,
        ))

    status_counts: Dict[str, int] = {}
    for loom in looms:
        status_counts[loom.status] = status_counts.get(loom.status, 0) + 1
    return ShopFloorSnapshot(
        snapshot_id="simulated-bootstrap",
        version=0,
        captured_at=captured_at,
        source="simulated_seed",
        looms=looms,
        beams=beams,
        events=events,
        metadata={
            "is_bootstrap": True,
            "data_source": "simulated",
            "simulation_seed": seed,
            "based_on": "当前Excel场景中的织机、产品、经轴设定长度和产能",
            "status_counts": status_counts,
            "assumptions": [
                "仅对Excel已有当前产品的织机模拟机上经轴",
                "机上经轴余量按设定长度的18%至88%确定性生成",
                "每个在产产品配置一根合格线边备轴",
                "边撑累计使用次数在0至5之间分布",
                "设置1台预防性保养、1台故障和1台缺料等待",
                "实际报工按日产能的82%至101%模拟",
            ],
        },
    )


def merge_snapshot(
    base: Optional[ShopFloorSnapshot],
    payload: Mapping[str, Any],
    *,
    scenario: Optional[WeavingScenario] = None,
) -> ShopFloorSnapshot:
    """把部分现场更新合并成一个完整的新版本快照。"""
    if base is None:
        base = build_default_snapshot(scenario or WeavingScenario())

    looms = {row.loom_id: row.to_dict() for row in base.looms}
    for incoming in payload.get("looms", []) or []:
        loom_id = str(incoming.get("loom_id") or "").strip()
        if not loom_id:
            raise ValueError("车间快照存在空 loom_id")
        merged = {**looms.get(loom_id, {}), **copy.deepcopy(incoming), "loom_id": loom_id}
        merged.setdefault("updated_at", payload.get("captured_at") or _now_iso())
        looms[loom_id] = merged

    beams = {row.beam_id: row.to_dict() for row in base.beams}
    for incoming in payload.get("beams", []) or []:
        beam_id = str(incoming.get("beam_id") or "").strip()
        if not beam_id:
            raise ValueError("车间快照存在空 beam_id")
        merged = {**beams.get(beam_id, {}), **copy.deepcopy(incoming), "beam_id": beam_id}
        merged.setdefault("updated_at", payload.get("captured_at") or _now_iso())
        beams[beam_id] = merged

    # 允许第一轮只录入机上状态；缺少经轴主档时生成明确标记的推导实例。
    for loom in looms.values():
        beam_id = loom.get("current_beam_id")
        if not beam_id or beam_id in beams:
            continue
        product_id = loom.get("current_product_id")
        remaining = float(loom.get("remaining_beam_m") or 0.0)
        beams[beam_id] = BeamInstance(
            beam_id=beam_id,
            beam_code=f"UNMAPPED-{product_id or beam_id}",
            product_id=product_id,
            total_meters=remaining or None,
            remaining_meters=remaining,
            location_type="loom",
            location_id=loom["loom_id"],
            status="on_loom",
            is_derived=True,
            updated_at=loom.get("updated_at"),
        ).to_dict()

    event_rows = [row.to_dict() for row in base.events]
    if payload.get("replace_events"):
        event_rows = []
    known_event_ids = {row.get("event_id") for row in event_rows}
    for incoming in payload.get("events", []) or []:
        event_id = str(incoming.get("event_id") or "").strip() or _new_id("event")
        if event_id in known_event_ids:
            continue
        event_type = str(incoming.get("event_type") or "").strip()
        if not event_type:
            raise ValueError("执行事件缺少 event_type")
        event_rows.append({
            **copy.deepcopy(incoming),
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": incoming.get("occurred_at") or payload.get("captured_at") or _now_iso(),
        })
        known_event_ids.add(event_id)

    parent_id = None if base.version == 0 else base.snapshot_id
    metadata = {**copy.deepcopy(base.metadata), **copy.deepcopy(payload.get("metadata") or {})}
    metadata.pop("is_bootstrap", None)
    snapshot = ShopFloorSnapshot(
        snapshot_id=str(payload.get("snapshot_id") or _new_id("sfs")),
        version=base.version + 1,
        captured_at=str(payload.get("captured_at") or _now_iso()),
        source=str(payload.get("source") or "manual"),
        schedule_id=payload.get("schedule_id", base.schedule_id),
        parent_snapshot_id=payload.get("parent_snapshot_id", parent_id),
        looms=[_filtered(LoomRuntimeSnapshot, row) for row in looms.values()],
        beams=[_filtered(BeamInstance, row) for row in beams.values()],
        events=[_filtered(ExecutionEvent, row) for row in event_rows],
        metadata=metadata,
    )
    validate_snapshot(snapshot, scenario=scenario)
    return snapshot


def validate_snapshot(snapshot: ShopFloorSnapshot,
                      scenario: Optional[WeavingScenario] = None) -> None:
    if snapshot.version < 0:
        raise ValueError("snapshot version 不能为负数")
    try:
        dt.datetime.fromisoformat(snapshot.captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("captured_at 必须是 ISO 时间") from exc

    known_looms = {loom.织机号 for loom in scenario.织机} if scenario else set()
    loom_ids: set[str] = set()
    for loom in snapshot.looms:
        if loom.loom_id in loom_ids:
            raise ValueError(f"织机状态重复: {loom.loom_id}")
        loom_ids.add(loom.loom_id)
        if known_looms and loom.loom_id not in known_looms:
            raise ValueError(f"车间快照引用不存在的织机: {loom.loom_id}")
        if loom.remaining_beam_m < 0:
            raise ValueError(f"织机 {loom.loom_id} 的经轴余量不能为负数")
        if loom.edge_support_uses < 0 or loom.edge_support_limit <= 0:
            raise ValueError(f"织机 {loom.loom_id} 的边撑次数无效")
        if loom.available_minute < 0:
            raise ValueError(f"织机 {loom.loom_id} 的可用时间不能为负数")

    beam_ids: set[str] = set()
    for beam in snapshot.beams:
        if beam.beam_id in beam_ids:
            raise ValueError(f"经轴实例重复: {beam.beam_id}")
        beam_ids.add(beam.beam_id)
        if beam.remaining_meters < 0:
            raise ValueError(f"经轴 {beam.beam_id} 的剩余米数不能为负数")
        if beam.total_meters is not None and beam.total_meters < beam.remaining_meters:
            raise ValueError(f"经轴 {beam.beam_id} 的剩余米数超过总米数")
        if beam.location_type == "loom" and beam.location_id and known_looms \
                and beam.location_id not in known_looms:
            raise ValueError(f"经轴 {beam.beam_id} 所在织机不存在: {beam.location_id}")

    for event in snapshot.events:
        if event.quantity_m is not None and event.quantity_m < 0:
            raise ValueError(f"事件 {event.event_id} 的数量不能为负数")


def runtime_states_from_snapshot(snapshot: ShopFloorSnapshot,
                                 schedule_start: Optional[str] = None):
    """转换成事件模拟器使用的运行状态，保持模拟模块向后兼容。"""
    from weaving_demo.simulation import LoomRuntimeState

    beam_by_id = {beam.beam_id: beam for beam in snapshot.beams}
    schedule_ref = None
    if schedule_start:
        try:
            schedule_ref = dt.datetime.fromisoformat(str(schedule_start).replace("Z", "+00:00"))
        except ValueError:
            schedule_ref = None
    states = {}
    for loom in snapshot.looms:
        beam = beam_by_id.get(loom.current_beam_id or "")
        remaining = loom.remaining_beam_m
        if beam is not None and remaining <= 1e-6:
            remaining = beam.remaining_meters
        available_minute = int(loom.available_minute)
        if schedule_ref is not None and loom.available_at:
            try:
                available_at = dt.datetime.fromisoformat(loom.available_at.replace("Z", "+00:00"))
                available_minute = max(0, int((available_at - schedule_ref).total_seconds() // 60))
            except ValueError:
                pass
        states[loom.loom_id] = LoomRuntimeState(
            loom_id=loom.loom_id,
            current_product_id=loom.current_product_id,
            current_beam_id=loom.current_beam_id,
            remaining_beam_m=float(remaining),
            edge_support_uses=int(loom.edge_support_uses),
            available_minute=available_minute,
        )
    return states


def final_snapshot_from_simulation(
    base: ShopFloorSnapshot,
    simulation_result: Mapping[str, Any],
    *,
    source: str = "simulation_preview",
) -> ShopFloorSnapshot:
    """根据模拟期末状态构建下一版本；是否落盘由调用方明确决定。"""
    final_states = simulation_result.get("final_runtime_states") or {}
    loom_updates: List[Dict[str, Any]] = []
    beam_updates: List[Dict[str, Any]] = []
    updated_at = _now_iso()
    schedule_ref = None
    if simulation_result.get("schedule_start"):
        try:
            schedule_ref = dt.datetime.fromisoformat(
                str(simulation_result["schedule_start"]).replace("Z", "+00:00")
            )
        except ValueError:
            schedule_ref = None
    existing_beams = {beam.beam_id: beam for beam in base.beams}

    for loom_id, state in final_states.items():
        beam_id = state.get("current_beam_id")
        remaining = float(state.get("remaining_beam_m") or 0.0)
        available_minute = int(state.get("available_minute") or 0)
        available_at = ((schedule_ref + dt.timedelta(minutes=available_minute)).isoformat()
                        if schedule_ref is not None else None)
        loom_updates.append({
            "loom_id": loom_id,
            "current_product_id": state.get("current_product_id"),
            "current_beam_id": beam_id,
            "remaining_beam_m": remaining,
            "edge_support_uses": int(state.get("edge_support_uses") or 0),
            "available_minute": available_minute,
            "available_at": available_at,
            "updated_at": updated_at,
        })
        if beam_id:
            previous = existing_beams.get(beam_id)
            beam_updates.append({
                "beam_id": beam_id,
                "beam_code": previous.beam_code if previous else f"UNMAPPED-{state.get('current_product_id') or beam_id}",
                "product_id": state.get("current_product_id"),
                "total_meters": previous.total_meters if previous else (remaining or None),
                "remaining_meters": remaining,
                "location_type": "loom",
                "location_id": loom_id,
                "status": "on_loom" if remaining > 1e-6 else "consumed",
                "quality_status": previous.quality_status if previous else "unverified",
                "is_derived": previous.is_derived if previous else True,
                "updated_at": updated_at,
            })

    completed_event = ExecutionEvent(
        event_id=_new_id("simulation"),
        event_type="simulation_completed",
        occurred_at=updated_at,
        quantity_m=float((simulation_result.get("kpi") or {}).get("simulated_quantity") or 0.0),
        details={
            "solver_schedule_id": simulation_result.get("solver_schedule_id"),
            "simulation_status": simulation_result.get("status"),
            "committed": source == "simulation_final",
        },
    )
    return merge_snapshot(base, {
        "source": source,
        "schedule_id": simulation_result.get("solver_schedule_id"),
        "looms": loom_updates,
        "beams": beam_updates,
        "events": [completed_event.to_dict()],
        "metadata": {
            "generated_from_simulation": True,
            "simulation_validation_ok": bool((simulation_result.get("validation") or {}).get("ok")),
        },
    })


class ShopFloorSnapshotStore:
    """小规模Demo使用的版本化JSON存储；写入采用临时文件原子替换。"""

    def __init__(self, path: Optional[Path] = None):
        configured = os.environ.get("WEAVING_SHOPFLOOR_STORE")
        self.path = Path(configured) if configured else Path(path or DEFAULT_STORE_PATH)
        self._lock = threading.RLock()
        self._data: Dict[str, ShopFloorSnapshot] = {}
        self._latest_id: Optional[str] = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        snapshots = raw.get("snapshots") or {}
        self._data = {sid: snapshot_from_dict(row) for sid, row in snapshots.items()}
        latest_id = raw.get("latest_snapshot_id")
        self._latest_id = latest_id if latest_id in self._data else None

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "latest_snapshot_id": self._latest_id,
            "snapshots": {sid: snapshot.to_dict() for sid, snapshot in self._data.items()},
        }
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp_path.replace(self.path)

    def save(self, snapshot: ShopFloorSnapshot,
             expected_version: Optional[int] = None) -> ShopFloorSnapshot:
        with self._lock:
            latest = self._data.get(self._latest_id or "")
            current_version = latest.version if latest else 0
            if expected_version is not None and int(expected_version) != current_version:
                raise ValueError(
                    f"车间状态版本冲突：当前版本为 {current_version}，提交基于 {expected_version}"
                )
            if snapshot.version != current_version + 1:
                raise ValueError(
                    f"新快照版本必须为 {current_version + 1}，实际为 {snapshot.version}"
                )
            self._data[snapshot.snapshot_id] = copy.deepcopy(snapshot)
            self._latest_id = snapshot.snapshot_id
            self._persist()
            return copy.deepcopy(snapshot)

    def get(self, snapshot_id: str) -> Optional[ShopFloorSnapshot]:
        with self._lock:
            snapshot = self._data.get(snapshot_id)
            return copy.deepcopy(snapshot) if snapshot else None

    def latest(self) -> Optional[ShopFloorSnapshot]:
        with self._lock:
            snapshot = self._data.get(self._latest_id or "")
            return copy.deepcopy(snapshot) if snapshot else None

    def all(self) -> List[ShopFloorSnapshot]:
        with self._lock:
            return [copy.deepcopy(row) for row in sorted(
                self._data.values(), key=lambda item: item.version
            )]


SHOPFLOOR_STORE = ShopFloorSnapshotStore()


def _clean_product(value: Optional[str]) -> Optional[str]:
    if value is None or str(value).strip() in ("", "0", "NULL"):
        return None
    return str(value).strip()


def _id_token(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in ("-", "_"))


def _add_minutes(value: dt.datetime, minutes: int) -> str:
    return (value + dt.timedelta(minutes=int(minutes))).isoformat(timespec="seconds")


def _simulation_capture_time(scenario: WeavingScenario) -> str:
    raw = None
    if scenario.设置 is not None:
        raw = scenario.设置.当前日期 or scenario.设置.排程起点
    if raw:
        try:
            parsed = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if "T" not in str(raw) and " " not in str(raw):
                parsed = parsed.replace(hour=8, minute=0, second=0, microsecond=0)
            return parsed.isoformat(timespec="seconds")
        except ValueError:
            pass
    return _now_iso()
