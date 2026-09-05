# -*- coding: utf-8 -*-
"""
run_stage2.py -- 阶段2 命令行演示：CP-SAT 排程
===============================================================================
流程: 装载/提取场景 -> build_tasks -> 7层字典序 CP-SAT 求解 -> 打印报告 + 示例结果。

用法:
  python -m weaving_demo.run_stage2 [--excel 源] [--max-time 30] [--out 结果json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
for p in (str(BASE / "libs"), str(Path(__file__).resolve().parent.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from weaving_demo import prep                                        # noqa: E402
from weaving_demo.solver import solve                                # noqa: E402
from weaving_demo.config import BUSINESS_RULES, STAGE2_PARAMS, TOOLING_SCOPE   # noqa: E402
from weaving_demo.extract import extract_scenario             # noqa: E402
from weaving_demo.load import load_json                       # noqa: E402

SAMPLE = Path(__file__).resolve().parent / "sample_data" / "scenario.json"
DEFAULT_EXCEL = r"C:\Users\Administrator\OneDrive\Desktop\副本【作成中整经织造】益丰生产管理表单260604.xlsx"


def load_scenario(excel: str):
    if Path(SAMPLE).exists():
        try:
            sc = load_json(str(SAMPLE))
            if sc.产品:
                return sc, "sample_data/scenario.json"
        except Exception:  # noqa: BLE001
            pass
    return extract_scenario(excel), "excel"


def _print(result: dict, conf: dict, sc) -> None:
    print("=" * 72)
    print("阶段2 · CP-SAT 排程演示")
    print("=" * 72)
    print(f"求解状态: {result['status']}  求解耗时: {result['solve_time_s']}s")
    print(f"模型规模: {result['model_stats']}")
    print(f"排程窗口: {result['schedule_start']} ~ {result['schedule_end']}")
    print("\n[每层优化目标结果]")
    for lv in result["objective_levels"]:
        print(f"  L{lv['level']} {lv['name']:<26} best={lv['best_value']}  {lv['status']}")
    kpi = result["kpi"]
    print("\n[KPI]")
    for k, v in kpi.items():
        print(f"  {k} = {v}")
    print(f"\n业务结果状态: {result['business_status']}  风险: {result.get('risk_reasons')}")
    dd = result.get("diagnostics", {})
    print(f"\n[诊断] 候选机台={dd.get('candidate_loom_count')} 已用机台={dd.get('used_loom_count')} "
          f"未用机台={dd.get('unused_loom_count')} 完全未排/部分未排="
          f"{dd.get('fully_unscheduled_task_count')}/{dd.get('partially_unscheduled_task_count')}")
    print("  未排原因拆解:")
    for rs in dd.get("unscheduled_reason_summary", []):
        print(f"    - {rs['reason_code']}: {rs['task_count']} 个任务 / {rs['quantity']} 米")
    print("\n[已排任务分配 - 前 12 条]")
    for a in result["assignments"][:12]:
        print(f"  {a['task_id']} {a['loom_id']} {a['start']} -> {a['end']} "
              f"量={a['scheduled_quantity']} 变更={a['changeover_type']} 逾期={a['lateness_minutes']}min")
    if len(result["assignments"]) > 12:
        print(f"  ... 共 {len(result['assignments'])} 条分配")
    print("\n[未排任务]")
    for u in result["unscheduled"]:
        if u["unscheduled_quantity"] > 0:
            print(f"  {u['task_id']} 需={u['required_quantity']} 已排={u['scheduled_quantity']} "
                  f"未排={u['unscheduled_quantity']} 原因={u['reason_codes']}")
    if not any(u["unscheduled_quantity"] > 0 for u in result["unscheduled"]):
        print("  (全部任务均已排完)")
    print("\n[问题/提示]")
    for i in result["issues"]:
        print(f"  [{i['severity']}] {i['code']}: {i['message']}")
    print("\n[结果校验]")
    print(f"  校验= {'通过' if result['validation']['ok'] else '不通过'}")
    for c in result["validation"]["checks"]:
        print(f"   - {c['message']}")

    print("\n[当前使用的临时业务参数]")
    sm = STAGE2_PARAMS["setup_minutes"]
    print(f"  落布={sm['drop_prep']} 上轴={sm['mount']} 穿综穿筘={sm['threading']} (分钟)")
    print(f"  安全库存={STAGE2_PARAMS['safety_stock']} 冻结期={STAGE2_PARAMS['freeze_days']}天 "
          f"虚拟经轴前缀={STAGE2_PARAMS['virtual_beam_prefix']} "
          f"拆分={{批量:{STAGE2_PARAMS['split_default']['min_batch_qty']}, 份数:{STAGE2_PARAMS['split_default']['max_parts']}}}")
    print("  仅已确认到货计入可用库存: " +
          str(STAGE2_PARAMS["confirmed_arrival_only"]))
    print("\n[因数据不足未启用的约束]")
    for reason in [
        "逐日物料库存推移(仅全局物料预算)",
        "机台×产品组合效率差异(用产品标准效率)",
        "仓库可调配工装数量(未建档, 仅校验机台已装配置)",
        "后整/水洗/涂层/验布/入库排程(阶段3+)",
        "休息日硬禁排(未硬约束化)",
        "真实实体经轴(用虚拟经轴 WB-XX-001)",
        "原计划一致性(依赖 original_loom_id, 数据缺时恒0)",
    ]:
        print(f"  - {reason}")


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    excel = DEFAULT_EXCEL
    max_time = 30.0
    out = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--excel":
            excel = argv[i + 1]; i += 2; continue
        if a in ("--max-time", "--max_time"):
            max_time = float(argv[i + 1]); i += 2; continue
        if a in ("-o", "--out"):
            out = argv[i + 1]; i += 2; continue
        if a in ("-h", "--help"):
            print(__doc__); return 0
        i += 1

    sc, src = load_scenario(excel)
    sc.规则配置 = BUSINESS_RULES
    if not sc.生产任务:
        sc.生产任务 = prep.build_tasks(sc, BUSINESS_RULES)
    sc.虚拟经轴 = prep.create_virtual_beams(sc, sc.生产任务, BUSINESS_RULES)
    print(f"[stage2] 场景来源={src}  产品={len(sc.产品)} 织机={len(sc.织机)} "
          f"生产任务={len(sc.生产任务)} 虚拟经轴={len(sc.虚拟经轴)}")
    result = solve(sc, objective="lexicographic", max_time_s=max_time, config=BUSINESS_RULES)
    _print(result, BUSINESS_RULES, sc)

    if out is None:
        out = str(Path(__file__).resolve().parent / "sample_data" / "solve_result.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"\n[stage2] 完整求解结果示例已写入: {out}")
    return 0 if result["status"] != "INFEASIBLE" else 1


if __name__ == "__main__":
    sys.exit(main())
