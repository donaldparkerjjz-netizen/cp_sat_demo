# -*- coding: utf-8 -*-
"""
run_diagnostics.py -- 阶段2.5 结果诊断 CLI
===============================================================================
运行：
  * 四方案对照：A(全约束) / B(关物料) / C(关经轴) / D(关物料+经轴)。
  * 三种适配模式：strict / balanced / simulation。
用法：
  python -m weaving_demo.run_diagnostics --excel 源 [--max-time 8]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
for p in (str(BASE / "libs"), str(Path(__file__).resolve().parent.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from weaving_demo import prep                                  # noqa: E402
from weaving_demo.solver import solve                          # noqa: E402
from weaving_demo.config import BUSINESS_RULES                 # noqa: E402
from weaving_demo.extract import extract_scenario              # noqa: E402
from weaving_demo.load import load_json                        # noqa: E402

SAMPLE = Path(__file__).resolve().parent / "sample_data" / "scenario.json"
DEFAULT_EXCEL = r"C:\Users\Administrator\OneDrive\Desktop\副本【作成中整经织造】益丰生产管理表单260604.xlsx"


def load_scenario(excel: str):
    if Path(SAMPLE).exists():
        try:
            sc = load_json(str(SAMPLE))
            if sc.产品:
                return sc
        except Exception:  # noqa: BLE001
            pass
    return extract_scenario(excel)


def _kpi_line(result: dict) -> str:
    return (f"scheduled={result.get('scheduled_quantity')} unscheduled={result.get('unscheduled_quantity')} "
            f"coverage={result.get('demand_coverage_rate')} delay={result.get('total_lateness_minutes')} "
            f"maxdelay={result.get('max_lateness_minutes')} used_loom={result.get('used_loom_count')} "
            f"util={result.get('utilization')} business={result.get('business_status')}")


def _num(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


def run_scheme_compare(sc, max_time: float) -> dict:
    schemes = [
        ("A_all_constraints", dict(material_enabled=True, beam_enabled=True)),
        ("B_no_material", dict(material_enabled=False, beam_enabled=True)),
        ("C_no_beam", dict(material_enabled=True, beam_enabled=False)),
        ("D_no_material_no_beam", dict(material_enabled=False, beam_enabled=False)),
    ]
    out = {}
    for name, opts in schemes:
        # 只用第一层"最小未排数量"，给充分时间；只有证明最优(OPTIMAL)才视为可比
        res = solve(sc, max_time_s=max_time, config=BUSINESS_RULES, max_layers=1, **opts)
        l1 = res["objective_levels"][0] if res["objective_levels"] else {}
        l1_best = l1.get("best_value")
        required = res["kpi"].get("required_quantity", 0.0) or 0.0
        l1_scheduled = (required - l1_best) if l1_best is not None else res["kpi"].get("scheduled_quantity")
        comparable = res["status"] == "OPTIMAL" and _bound_consistent(l1)
        out[name] = {
            "status": res["status"],
            "business_status": res["business_status"],
            "scheduled_quantity": round(l1_scheduled, 1),
            "unscheduled_quantity": l1_best,
            "total_lateness_minutes": res["kpi"].get("total_lateness_minutes"),
            "max_lateness_minutes": res["kpi"].get("max_lateness_minutes"),
            "used_loom_count": res["kpi"].get("used_loom_count"),
            "candidate_loom_count": res["diagnostics"].get("candidate_loom_count"),
            "utilization": res["kpi"].get("utilization"),
            "demand_coverage_rate": round(l1_scheduled / required, 4) if required else 0.0,
            "solve_time_s": res.get("solve_time_s"),
            "solver_status": res["status"],
            "best_value": l1.get("best_value"),
            "best_bound": l1.get("best_bound"),
            "gap": l1.get("gap"),
            "comparison_status": "COMPARABLE" if comparable else "INCONCLUSIVE",
        }
    return out


def _bound_consistent(l1: dict) -> bool:
    bv, bb = l1.get("best_value"), l1.get("best_bound")
    if bv is None or bb is None:
        return False
    return abs(bv - bb) <= 1


def run_mode_compare(sc, max_time: float) -> dict:
    out = {}
    for mode in ("strict", "balanced", "simulation"):
        res = solve(sc, max_time_s=max_time, config=BUSINESS_RULES, compatibility_mode=mode,
                    recompute_allowed=True)
        d = res["diagnostics"]
        out[mode] = {
            "status": res["status"],
            "business_status": res["business_status"],
            "coverage": res["kpi"].get("demand_coverage_rate"),
            "candidate_loom_count": d.get("candidate_loom_count"),
            "used_loom_count": res["kpi"].get("used_loom_count"),
            "scheduled_quantity": res["kpi"].get("scheduled_quantity"),
            "unscheduled_quantity": res["kpi"].get("unscheduled_quantity"),
            "reason_summary": d.get("unscheduled_reason_summary"),
        }
    return out


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    excel = DEFAULT_EXCEL
    max_time = 12.0
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--excel":
            excel = argv[i + 1]; i += 2; continue
        if a in ("--max-time", "--max_time"):
            max_time = float(argv[i + 1]); i += 2; continue
        i += 1
    sc = load_scenario(excel)
    sc.规则配置 = BUSINESS_RULES
    if not sc.生产任务:
        sc.生产任务 = prep.build_tasks(sc, BUSINESS_RULES)
    # 需要先用 balanced 生成任务(带 allowed_loom_ids)，再跑各种模式
    print("=" * 70)
    print("四方案对照 A/B/C/D（仅诊断，不对外发布）")
    print("=" * 70)
    scheme = run_scheme_compare(sc, max_time)
    for name, d in scheme.items():
        print(f"  [{name}] {_kpi_line(d)}")
    print("\n瓶颈判断：")
    all_comp = all(s["comparison_status"] == "COMPARABLE" for s in scheme.values())
    if not all_comp:
        print("  -> 当前求解时间内无法得出可靠对比（存在 INCONCLUSIVE 方案），不据此生成业务结论。")
        for name, s in scheme.items():
            print(f"     [{name}] solver={s['solver_status']} best_value={s['best_value']} "
                  f"best_bound={s['best_bound']} gap={s['gap']} comparison={s['comparison_status']}")
    else:
        sched_all = _num(scheme["A_all_constraints"]["scheduled_quantity"])
        sched_nomat = _num(scheme["B_no_material"]["scheduled_quantity"])
        sched_nobeam = _num(scheme["C_no_beam"]["scheduled_quantity"])
        sched_none = _num(scheme["D_no_material_no_beam"]["scheduled_quantity"])
        print(f"  A={sched_all}  B(去物料)={sched_nomat}  C(去经轴)={sched_nobeam}  D(都去)={sched_none}")
        if sched_all == sched_nomat == sched_nobeam == sched_none:
            print("  -> 物料与经轴均不是瓶颈（未排主要因兼容/能力）。")
        elif sched_all < sched_nomat:
            print("  -> 物料约束是瓶颈之一（去物料后已排增加）。")
        if sched_all < sched_nobeam:
            print("  -> 经轴约束是瓶颈之一（去经轴后已排增加）。")

    print("\n" + "=" * 70)
    print("三种适配模式 strict / balanced / simulation")
    print("=" * 70)
    modes = run_mode_compare(sc, max_time)
    for mode, d in modes.items():
        print(f"  [{mode}] coverage={d['coverage']} cand={d['candidate_loom_count']} "
              f"used={d['used_loom_count']} sched={d['scheduled_quantity']} "
              f"unsch={d['unscheduled_quantity']} status={d['status']}"
              f" reasons={d['reason_summary'][:2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
