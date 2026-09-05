#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_server.py -- 工厂排工排产系统 Demo 后端 (FastAPI)
================================================================================
按《PRD_工厂排工排产系统.md》Phase 1 范围提供在线演示:
  * GET  /                 返回前端单页 (demo_static/demo.html)
  * GET  /api/data         返回基础数据(机台/产品/适配/换模/工价/订单/班次)
  * GET  /api/solve        用 CP-SAT 求解并返回排程 + 分析 JSON
  * POST /api/insert       插入急单并重排, 返回前后对比 + P1/P2/P3 调剂建议
  * POST /api/reset        恢复默认场景(重排)

运行:
  python demo_server.py
  浏览器打开: http://127.0.0.1:8080
"""
import sys
import os
import json
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
for p in (str(BASE), str(BASE / "libs")):
    if p not in sys.path:
        sys.path.insert(0, p)

import demo_engine as eng  # noqa: E402
import demo_constraint_nlu as nlu  # noqa: E402
import demo_excel_io as xlsx  # noqa: E402
import demo_ingest as ingest_mod  # noqa: E402
import base64
from fastapi.responses import Response  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402
import uvicorn  # noqa: E402

app = FastAPI(title="工厂排工排产系统 Demo", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HOST, PORT = "127.0.0.1", 8080
STATIC = BASE / "demo_static"

# 当前工作场景(内存中, 可被插单/重置修改)
_state = {"scenario": json.loads(json.dumps(eng.DEFAULT_SCENARIO))}


@app.get("/")
def index():
    return FileResponse(str(STATIC / "demo.html"))


@app.get("/api/data")
def get_data():
    """返回当前场景的基础数据。"""
    return _state["scenario"]


# 多目标权重预设(来自引擎)
WEIGHT_PRESETS = eng.WEIGHT_PRESETS
OBJ_LABELS = eng.OBJ_LABELS


def _weights(objective: str):
    return WEIGHT_PRESETS.get(objective, WEIGHT_PRESETS["balanced"])


@app.get("/api/solve")
def solve(objective: str = "balanced", max_time_s: float = 30.0):
    """求解当前场景。"""
    t0 = time.time()
    try:
        max_time_s = max(1.0, min(60.0, float(max_time_s)))
        res = eng.solve_scenario(_state["scenario"], objective=objective,
                                 max_time_s=max_time_s, weights=_weights(objective))
        res["meta"]["api_wall_time_s"] = round(time.time() - t0, 4)
        res["meta"]["objective_label"] = OBJ_LABELS.get(objective, objective)
        return res
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


class NluModel(BaseModel):
    text: str


@app.post("/api/nlu")
def nlu_parse(body: NluModel):
    """解析操作员的自然语言约束, 返回结构化约束列表(不应用)。"""
    return nlu.parse_constraints(body.text, _state["scenario"])


class ApplyModel(BaseModel):
    text: str
    objective: str = "balanced"
    max_time_s: float = 30.0


@app.post("/api/apply")
def apply_constraints(body: ApplyModel):
    """解析自然语言约束 -> 应用到当前场景 -> 重新求解, 返回解析/应用/排程结果。"""
    t0 = time.time()
    parsed = nlu.parse_constraints(body.text, _state["scenario"])
    if not parsed["parsed"]:
        return {"parsed": parsed["parsed"], "errors": parsed["errors"], "applied": [],
                "result": None,
                "summary": {"text": "未解析到任何可应用的约束，请调整措辞。",
                            "applied_ok": [], "failed": parsed["errors"]},
                "api_wall_time_s": round(time.time() - t0, 4)}
    new_sc, summary = eng.apply_constraints(_state["scenario"], parsed["parsed"])
    _state["scenario"] = new_sc
    try:
        result = eng.solve_scenario(new_sc, objective=body.objective,
                                    max_time_s=float(body.max_time_s),
                                    weights=_weights(body.objective))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}", "parsed": parsed["parsed"],
                             "applied": summary}, status_code=500)
    result["meta"]["objective_label"] = OBJ_LABELS.get(body.objective, body.objective)
    result["meta"]["api_wall_time_s"] = round(time.time() - t0, 4)
    ok_sum = [s for s in summary if s.get("ok")]
    bad_sum = [s for s in summary if not s.get("ok")]
    text = parsed["summary"]["text"]
    if bad_sum:
        text += f" 其中{len(bad_sum)}条应用失败/未识别。"
    return {"parsed": parsed["parsed"], "errors": parsed["errors"],
            "applied": summary, "result": result,
            "summary": {"text": text, "applied_ok": ok_sum, "failed": bad_sum},
            "api_wall_time_s": round(time.time() - t0, 4)}


@app.get("/api/excel/template")
def excel_template():
    """下载排产数据 Excel 模板。"""
    data = xlsx.export_template()
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=aps_template.xlsx"})


class ExcelImportModel(BaseModel):
    data_base64: str
    objective: str = "balanced"
    max_time_s: float = 30.0


@app.post("/api/excel/import")
def excel_import(body: ExcelImportModel):
    """解析上传的 Excel(含产品/机台/适配/订单/换模/日历) -> 覆盖场景 -> 重新求解。"""
    t0 = time.time()
    try:
        data = base64.b64decode(body.data_base64)
        # 每次导入以默认场景为基底(覆盖式): 未匹配页回退默认值, 结果可预期
        sc, summary, errors = xlsx.parse_excel(data, eng.DEFAULT_SCENARIO)
        if sc is None:
            return JSONResponse({"error": summary["text"], "errors": errors}, status_code=400)
        _state["scenario"] = sc
        result = eng.solve_scenario(sc, objective=body.objective,
                                    max_time_s=float(body.max_time_s),
                                    weights=_weights(body.objective))
        result["meta"]["objective_label"] = OBJ_LABELS.get(body.objective, body.objective)
        result["meta"]["api_wall_time_s"] = round(time.time() - t0, 4)
        return {"summary": summary, "errors": errors, "result": result}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


class ExcelExportModel(BaseModel):
    objective: str = "balanced"
    max_time_s: float = 30.0


@app.post("/api/excel/export")
def excel_export(body: ExcelExportModel):
    """把当前场景的排产结果(机台 x 班次矩阵)写回 Excel 下载。"""
    try:
        result = eng.solve_scenario(_state["scenario"], objective=body.objective,
                                    max_time_s=float(body.max_time_s),
                                    weights=_weights(body.objective))
        data = xlsx.export_result(result)
        return Response(content=data,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename=aps_schedule.xlsx"})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


class IngestModel(BaseModel):
    files: list  # [{name, data_base64}]
    objective: str = "balanced"
    max_time_s: float = 30.0


@app.post("/api/ingest")
def ingest_files(body: IngestModel):
    """通用数据接入: 解析多个(多页)文件( xlsx/csv ) -> 组装场景 -> 重新求解。
       逐页自动识别, 无模板要求; 返回逐文件/逐页处理报告。"""
    t0 = time.time()
    try:
        sc, report = ingest_mod.ingest(body.files, eng.DEFAULT_SCENARIO)
        _state["scenario"] = sc
        result = eng.solve_scenario(sc, objective=body.objective,
                                    max_time_s=float(body.max_time_s),
                                    weights=_weights(body.objective))
        result["meta"]["objective_label"] = OBJ_LABELS.get(body.objective, body.objective)
        result["meta"]["api_wall_time_s"] = round(time.time() - t0, 4)
        return {"report": report, "result": result}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


class InsertOrderModel(BaseModel):
    order: dict
    objective: str = "balanced"
    max_time_s: float = 30.0


@app.post("/api/insert")
def insert_order(body: InsertOrderModel):
    """插入急单并重排, 返回 baseline/result/comparison/recommendation/kpi_compare。"""
    t0 = time.time()
    try:
        new_order = body.order
        max_time_s = max(1.0, min(60.0, float(body.max_time_s)))
        r = eng.insert_order(_state["scenario"], new_order,
                             objective=body.objective, max_time_s=max_time_s)
        # 提交: 之后 /api/solve 基于新场景
        _state["scenario"] = r["new_scenario"]
        r["api_wall_time_s"] = round(time.time() - t0, 4)
        return r
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.post("/api/reset")
def reset():
    """恢复默认场景。"""
    _state["scenario"] = json.loads(json.dumps(eng.DEFAULT_SCENARIO))
    return {"ok": True, "msg": "已恢复默认场景"}


@app.get("/api/meta")
def meta():
    return {"title": "工厂排工排产系统 Demo", "engine": "OR-Tools CP-SAT", "version": "1.0"}


if __name__ == "__main__":
    print("工厂排工排产系统 Demo running on http://%s:%d" % (HOST, PORT))
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")