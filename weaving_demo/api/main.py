# -*- coding: utf-8 -*-
"""weaving_demo/api/main.py -- 排程后端 FastAPI 应用。
运行：python -m weaving_demo.api.main   (或 uvicorn weaving_demo.api.main:app)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

BASE = Path(__file__).resolve().parent.parent.parent
for p in (str(BASE / "libs"), str(BASE), str(Path(__file__).resolve().parent.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from weaving_demo import prep  # noqa: E402
from weaving_demo.config import BUSINESS_RULES, STAGE2_PARAMS  # noqa: E402
from weaving_demo.api import service  # noqa: E402
from weaving_demo.api.store import STORE  # noqa: E402
from weaving_demo.solver import solve  # noqa: E402
from weaving_demo.api.service import VALID_MODES, VALID_HORIZON_DAYS  # noqa: E402

app = FastAPI(title="益丰整经织造排程中心 API", version="3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


class SolveRequest(BaseModel):
    compatibility_mode: str = "balanced"
    max_time_s: float = 30.0
    schedule_start: Optional[str] = None
    horizon_days: Optional[int] = 7
    enable_material_constraint: bool = True
    enable_beam_constraint: bool = True
    freeze_days: int = 3
    objective_mode: str = "lexicographic"
    optimize_rules: bool = True


class DiagnosticCompareRequest(BaseModel):
    max_time_s: float = 20.0
    compatibility_mode: str = "balanced"


class SimulationRequest(BaseModel):
    schedule_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    commit_final_state: bool = False
    lead_time_minutes: int = 120
    edge_support_use_limit: int = 5
    warping_minutes_per_beam: int = 240
    threading_minutes: int = 480


class ShopFloorSnapshotRequest(BaseModel):
    base_version: Optional[int] = None
    captured_at: Optional[str] = None
    source: str = "manual"
    schedule_id: Optional[str] = None
    looms: list[Dict[str, Any]] = Field(default_factory=list)
    beams: list[Dict[str, Any]] = Field(default_factory=list)
    events: list[Dict[str, Any]] = Field(default_factory=list)
    replace_events: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DataImportPreviewRequest(BaseModel):
    filename: str
    content_base64: str


class DataSnapshotSaveRequest(BaseModel):
    preview_id: str
    note: str = ""


@app.get("/api/health")
def health():
    from weaving_demo import solver as _s
    d = service.scenario_summary()
    return {
        "service": "益丰整经织造排程中心 API",
        "status": "ok",
        "engine": "google-or-tools-cp-sat",
        "algorithm_module": _s.__name__,
        "data_status": {"warnings": d["data_warnings"], "errors": d["data_errors"],
                        "info": d["data_info"]},
        "scenario": {"products": d["products"], "looms": d["looms"],
                     "available_looms": d["available_looms"], "tasks": d["tasks"]},
        "schedule_count": len(STORE.all()),
    }


@app.get("/api/scenarios/current")
def current_scenario():
    return service.scenario_summary()


@app.post("/api/data/import-preview")
def preview_data_import(body: DataImportPreviewRequest):
    try:
        return service.preview_data_import(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/api/data/snapshots")
def list_data_snapshots():
    return service.list_data_snapshots()


@app.post("/api/data/snapshots")
def save_data_snapshot(body: DataSnapshotSaveRequest):
    try:
        return service.save_data_snapshot(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=409 if "阻断" in str(e) else 400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/api/shopfloor/snapshot/latest")
def latest_shopfloor_snapshot():
    try:
        return service.get_shopfloor_snapshot()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/api/shopfloor/snapshot/{snapshot_id}")
def get_shopfloor_snapshot(snapshot_id: str):
    try:
        return service.get_shopfloor_snapshot(snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.post("/api/shopfloor/snapshot")
def save_shopfloor_snapshot(body: ShopFloorSnapshotRequest):
    try:
        return service.save_shopfloor_snapshot(body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=409 if "版本冲突" in str(e) else 400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.post("/api/schedules/solve")
def solve_schedule(body: SolveRequest):
    try:
        payload = service.run_solve(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    return payload


@app.get("/api/schedules/latest")
def latest_schedule():
    r = STORE.latest()
    if r is None:
        raise HTTPException(status_code=404, detail="暂无排程结果，请先运行排程")
    return r


@app.get("/api/schedules/{schedule_id}")
def get_schedule(schedule_id: str):
    r = STORE.get(schedule_id)
    if r is None:
        raise HTTPException(status_code=404, detail=f"未找到排程 {schedule_id}")
    return r


@app.get("/api/schedules/{schedule_id}/diagnostics")
def schedule_diagnostics(schedule_id: str):
    r = STORE.get(schedule_id)
    if r is None:
        raise HTTPException(status_code=404, detail=f"未找到排程 {schedule_id}")
    return {
        "schedule_id": schedule_id,
        "diagnostics": r.get("diagnostics", {}),
        "model_stats": r.get("model_stats", {}),
        "objective_levels": r.get("objective_levels", []),
        "business_status": r.get("business_status"),
        "comparison_status": r.get("comparison_status"),
    }


@app.post("/api/schedules/diagnostic-compare")
def diagnostic_compare(body: DiagnosticCompareRequest):
    if body.compatibility_mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"invalid compatibility_mode: {body.compatibility_mode}")
    try:
        payload = service.run_diagnostic_compare(body.model_dump())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    return payload


@app.get("/api/process/overview")
def process_overview():
    return service.process_overview()


@app.get("/api/process/tasks")
def process_tasks():
    return service.process_tasks()


@app.get("/api/process/progress")
def process_progress():
    return service.homepage_progress()


@app.get("/api/process/cases")
def process_cases():
    return service.process_cases()


@app.get("/api/process/gantt")
def process_gantt():
    return service.process_gantt()


@app.get("/api/warping/beams")
def warping_beams():
    return service.warping_beams()


@app.get("/api/warping/instances")
def warping_instances():
    return service.warping_instances()


@app.get("/api/warping/inventory")
def warping_inventory():
    return service.warping_inventory()


@app.get("/api/warping/weekly-plan")
def warping_weekly_plan():
    return service.weekly_warping_plan()


@app.get("/api/weaving/weekly-plan")
def weaving_weekly_plan():
    return service.weekly_weaving_plan()


@app.post("/api/simulation/run")
def run_simulation(body: SimulationRequest):
    try:
        return service.run_weekly_simulation(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/api/tasks/pool")
def task_pool():
    return service.task_pool()


@app.get("/api/looms/resource")
def loom_resources():
    return service.loom_resources()


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
