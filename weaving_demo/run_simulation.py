# -*- coding: utf-8 -*-
"""运行织造滚动排产模拟样例。

用法（项目根目录 D:\\dsh\\cp_sat_demo）：

    python -m weaving_demo.run_simulation
    python -m weaving_demo.run_simulation --with-fault --out weaving_demo/sample_data/simulation_result.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Tuple

from weaving_demo.config import BUSINESS_RULES
from weaving_demo.model import Loom, Product, ProductionTask, Settings, WeavingScenario
from weaving_demo.simulation import LoomRuntimeState, SimulationConfig, run_schedule_simulation


def build_demo_scenario(with_fault: bool = False) -> Tuple[WeavingScenario, Dict[str, LoomRuntimeState]]:
    """构造能覆盖四类准备方式的最小演示场景。"""
    products = [
        Product(产品款号="P-A", 经轴款号="WA", 整经设定长度=3600,
                织造效率=3600, 钢筘型号="R-A"),
        Product(产品款号="P-B", 经轴款号="WB", 整经设定长度=3600,
                织造效率=3000, 钢筘型号="R-B"),
        Product(产品款号="P-C", 经轴款号="WC", 整经设定长度=3600,
                织造效率=3200, 钢筘型号="R-C"),
    ]
    looms = [
        Loom(织机号="L-01", 当前状态="量产", 目前对应产品="P-A", 钢筘="R-A"),
        Loom(织机号="L-02", 当前状态="量产", 目前对应产品="P-B", 钢筘="R-B"),
        Loom(织机号="L-03", 当前状态="量产", 目前对应产品="P-A", 钢筘="R-A"),
    ]
    # 固定候选织机，让样例稳定呈现：余轴续产、接经、原品番仕挂、改品番仕挂。
    tasks = [
        ProductionTask("T-A-01", "P-A", 800, due_minute=12 * 60,
                       allowed_loom_ids=["L-01"], beam_code="WA"),
        ProductionTask("T-B-01", "P-B", 3600, due_minute=2 * 1440,
                       allowed_loom_ids=["L-02"], beam_code="WB"),
        ProductionTask("T-C-01", "P-C", 3600, due_minute=3 * 1440,
                       allowed_loom_ids=["L-03"], beam_code="WC"),
        ProductionTask("T-A-02", "P-A", 3600, due_minute=4 * 1440,
                       allowed_loom_ids=["L-01"], beam_code="WA"),
        ProductionTask("T-A-03", "P-A", 3600, due_minute=6 * 1440,
                       allowed_loom_ids=["L-01"], beam_code="WA"),
    ]
    maint = []
    if with_fault:
        maint.append({"loom_id": "L-03", "start_minute": 24 * 60, "end_minute": 36 * 60,
                      "reason": "模拟突发故障"})
    scenario = WeavingScenario(
        设置=Settings(当前日期="2026-09-02", 排程起点="2026-09-02", 排程终点="2026-09-10"),
        产品=products,
        织机=looms,
        生产任务=tasks,
        维护区间=maint,
        规则配置=BUSINESS_RULES,
        数据来源="rolling-simulation-demo",
    )
    states = {
        # 先消耗 800m 余轴，下一只经轴执行接经；接经后边撑次数达到 5，后续执行原品番仕挂。
        "L-01": LoomRuntimeState("L-01", "P-A", "LINE-L01-WA", 800, 4),
        # 同品番但边撑已达上限 -> 原品番仕挂。
        "L-02": LoomRuntimeState("L-02", "P-B", None, 0, 5),
        # 从 P-A 切到 P-C -> 改品番仕挂 + 穿综穿筘。
        "L-03": LoomRuntimeState("L-03", "P-A", None, 0, 2),
    }
    return scenario, states


def _print_summary(result: dict) -> None:
    print("=" * 72)
    print("织造滚动排产模拟")
    print("=" * 72)
    print(f"状态: {result['status']}  CP-SAT: {result['solver_status']}")
    kpi = result["kpi"]
    print(f"已排/模拟产量: {kpi['solver_scheduled_quantity']} / {kpi['simulated_quantity']} 米")
    print(f"模拟完成时间: 第 {round(kpi['simulated_completion_minute'] / 1440, 2)} 天")
    print("准备方式:")
    for name, count in kpi["setup_type_counts"].items():
        print(f"  {name}: {count}")
    print(f"整经任务={kpi['warping_task_count']}  穿综穿筘任务={kpi['threading_task_count']}")
    print("\n未来工况:")
    for row in result["forecasts"]:
        print(f"  {row['cutoff']}: 产出={row['produced_meters']}m  "
              f"机台状态={row['loom_state_count']}  延期任务={row['late_task_count']}")
    print("\n织造段:")
    for e in result["weaving_plan"]:
        print(f"  {e['loom_id']} {e['task_id']} {e['product_id']} {e['quantity']}m  "
              f"{e['start']} -> {e['end']}  {e['setup_label']}")
    print("\n校验:", "通过" if result["validation"]["ok"] else "不通过")
    for check in result["validation"]["checks"]:
        print(f"  [{'OK' if check['pass'] else 'FAIL'}] {check['check']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="织造滚动排产模拟")
    parser.add_argument("--with-fault", action="store_true", help="加入 L-03 第1天至第1.5天的故障窗口")
    parser.add_argument("--max-time", type=float, default=8.0, help="CP-SAT 求解时间上限（秒）")
    parser.add_argument("--out", default=None, help="JSON 输出路径")
    args = parser.parse_args(argv)

    scenario, states = build_demo_scenario(with_fault=args.with_fault)
    cfg = SimulationConfig(cp_sat_time_limit_s=args.max_time)
    result = run_schedule_simulation(scenario, runtime_states=states, config=cfg)
    _print_summary(result)

    out = Path(args.out) if args.out else Path(__file__).resolve().parent / "sample_data" / "simulation_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果已写入: {out}")
    return 0 if result["validation"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

