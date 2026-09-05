# -*- coding: utf-8 -*-
"""
run_stage1.py -- 阶段1 数据管道入口
===============================================================================
流程: Excel -> 提取/清洗/映射(extract) -> 保存样例 JSON(sample_data/scenario.json)
      -> 数据级校验(validate) -> 打印校验报告。

用法:
  python -m weaving_demo.run_stage1
          或
  python weaving_demo/run_stage1.py [excel路径] [-o 输出json] [--no-write]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
for p in (str(BASE / "libs"), str(Path(__file__).resolve().parent.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from weaving_demo.extract import extract_scenario  # noqa: E402
from weaving_demo.load import scenario_from_dict  # noqa: E402
from weaving_demo.validate import validate_scenario  # noqa: E402
from weaving_demo.config import BUSINESS_RULES  # noqa: E402

DEFAULT_EXCEL = r"C:\Users\Administrator\OneDrive\Desktop\副本【作成中整经织造】益丰生产管理表单260604.xlsx"
SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"


def run(excel_path: str = DEFAULT_EXCEL, out_path: str = None,
        write: bool = True) -> dict:
    sc = extract_scenario(excel_path)
    sc.规则配置 = BUSINESS_RULES
    data = sc.to_dict()

    if write:
        out = Path(out_path) if out_path else SAMPLE_DIR / "scenario.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    else:
        out = None

    # 重新装载并以模型校验（验证 JSON 往返）
    reloaded = scenario_from_dict(scenario_from_dict(data).to_dict())
    report = validate_scenario(reloaded)

    return {
        "data": data,
        "out_path": str(out) if out else None,
        "report": report,
        "rules": BUSINESS_RULES,
    }


def _print_report(report: dict) -> None:
    stats = report.get("stats", {})
    print("== 数据级校验报告 ==")
    print("  概览: " + ", ".join(f"{k}={v}" for k, v in stats.items() if isinstance(v, (int, str))))
    sev = report.get("severity", {})
    print(f"  状态: {'可运行 OK' if report.get('ok') else '存在错误 FAIL'} "
          f"(ERROR={sev.get('error', 0)}, WARNING={sev.get('warning', 0)}, INFO={sev.get('info', 0)})")
    if report.get("errors"):
        print("  ERROR(数据导致模型无法运行):")
        for e in report["errors"]:
            print("    -", e)
    if report.get("warnings"):
        print("  WARNING(可运行, 但结果用临时假设/数据缺口):")
        for w in report["warnings"]:
            print("    -", w)
    if report.get("info"):
        print("  INFO(普通数据说明):")
        for i in report["info"]:
            print("    -", i)


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    excel = DEFAULT_EXCEL
    out = None
    write = True
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-o", "--out"):
            out = argv[i + 1]; i += 2; continue
        if a == "--no-write":
            write = False; i += 1; continue
        if a in ("-h", "--help"):
            print(__doc__); return 0
        excel = a; i += 1

    result = run(excel, out_path=out, write=write)
    if result["out_path"]:
        print(f"[stage1] 样例数据已写入: {result['out_path']}")
    _print_report(result["report"])
    return 0 if result["report"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
