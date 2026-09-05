#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""schedule_finishing.py -- CP-SAT 对真实织造后整链排产
流程: 落布(织造产出) -> 水洗 -> 涂层 -> 验布 -> 入库
时间单位: 分钟(整数)
"""
import sys, os, json, csv, math, time, datetime
sys.path.insert(0, r"D:\dsh\cp_sat_demo\libs")
from ortools.sat.python import cp_model

BASE = r"D:\dsh\cp_sat_demo"; DATA = os.path.join(BASE,"data")
with open(os.path.join(DATA,"finishing_capacity.json"),encoding="utf-8") as f:
    cap = json.load(f)["per_12h_m"]
# 每 12 小时产能(米)  -> 每分钟产能 = cap/(12*60)
STAGES = [("wash","水洗机", cap.get("水洗",12000)), ("coat","涂层机", cap.get("涂层",9000)),
          ("insp","验布机", cap.get("验布",7000))]
M_IDX = {s[0]:i for i,s in enumerate(STAGES)}

# 载入批次
batches=[]
with open(os.path.join(DATA,"fabric_off.csv"),encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        if not row["qty_m"]: continue
        batches.append({"id":len(batches),"loom":row["loom"],"date":row["date"],
                        "product":row["product"],"qty":float(row["qty_m"])})
REF = datetime.date(2026,6,1)
def release_min(d): return (datetime.date.fromisoformat(d)-REF).days*1440
for b in batches: b["release"]=release_min(b["date"])

def dur_min(sk,qty):
    cap12 = dict((s[0],s[2]) for s in STAGES)[sk]
    return max(1, int(math.ceil(qty*12*60/cap12)))   # 分钟, 向上取整

num=len(batches); max_rel=max((b["release"] for b in batches),default=0)
worst_batch_tot = max(sum(dur_min(sk,b["qty"]) for sk in ["wash","coat","insp"]) for b in batches)
horizon = int(max_rel + worst_batch_tot*num + 24*60)

model=cp_model.CpModel(); S={};E={};IV={}
for b in batches:
    for sk,_,_ in STAGES:
        s=model.NewIntVar(0,horizon,"s%d_%s"%(b["id"],sk))
        e=model.NewIntVar(0,horizon,"e%d_%s"%(b["id"],sk))
        iv=model.NewIntervalVar(s,dur_min(sk,b["qty"]),e,"iv%d_%s"%(b["id"],sk))
        S[(b["id"],sk)]=s;E[(b["id"],sk)]=e;IV[(b["id"],sk)]=iv
for b in batches:
    model.Add(S[(b["id"],"wash")] >= b["release"])
    model.Add(S[(b["id"],"coat")] >= E[(b["id"],"wash")])
    model.Add(S[(b["id"],"insp")] >= E[(b["id"],"coat")])
for sk,_,_ in STAGES:
    model.AddNoOverlap([IV[(b["id"],sk)] for b in batches])
makespan=model.NewIntVar(0,horizon,"makespan")
for b in batches: model.Add(makespan>=E[(b["id"],"insp")])
model.Minimize(makespan)

solver=cp_model.CpSolver(); solver.parameters.max_time_in_seconds=45; solver.parameters.num_workers=8
t0=time.time(); st=solver.Solve(model)
status_name=solver.StatusName(st); feasible=st in (cp_model.OPTIMAL,cp_model.FEASIBLE)

res={"meta":{"title":"织造后整链 CP-SAT 排产 (落布→水洗→涂层→验布→入库)",
             "data":"益丰生产管理表单260604.xlsx(落布预测)","reference":str(REF),
             "unit":"分钟","batches":num,"total_qty_m":round(sum(b["qty"] for b in batches),0)},
     "statistics":{"status":status_name,"num_operations":num*len(STAGES),"num_jobs":num,
                   "num_machines":len(STAGES),"solve_time_s":0},
     "machines":[s[1] for s in STAGES], "jobs":[], "schedule":[], "analysis":{}}
if feasible:
    mk=0; flow=0
    for b in batches:
        for sk,_,_ in STAGES:
            s=solver.Value(S[(b["id"],sk)]);e=solver.Value(E[(b["id"],sk)])
        comp=solver.Value(E[(b["id"],"insp")]); mk=max(mk,comp); flow+=comp-b["release"]
        res["schedule"].append({"job":b["id"],"product":b["product"],"loom":b["loom"],
                                "date":b["date"],"release_min":b["release"]})
    for b in batches:
        ops=[{"job":b["id"],"op":M_IDX[sk],"machine":M_IDX[sk],
              "start":solver.Value(S[(b["id"],sk)]),"end":solver.Value(E[(b["id"],sk)]),
              "duration":dur_min(sk,b["qty"])} for sk,_,_ in STAGES]
        res["jobs"].append({"id":b["id"],"name":"%s@%s"%(b["product"],b["loom"]),
                            "product":b["product"],"loom":b["loom"],"date":b["date"],
                            "qty":b["qty"],"release_min":b["release"],
                            "operations":ops,"completion":ops[-1]["end"]})
    res["statistics"]["objective_value"]=round(solver.ObjectiveValue(),1)
    res["statistics"]["makespan_min"]=mk
    res["statistics"]["makespan_h"]=round(mk/60,1)
    res["statistics"]["total_flow_time_min"]=round(flow,1)
res["statistics"]["solve_time_s"]=round(solver.WallTime(),3)

load={}
for sk,label,cap12 in STAGES:
    tot=sum(dur_min(sk,b["qty"]) for b in batches)
    mk=res["statistics"].get("makespan_min") or 1
    load[label]={"total_load_min":tot,"makespan_min":mk,"utilization_pct":round(100*tot/mk,1)}
res["analysis"]["machine_load"]=load
res["analysis"]["num_batches"]=num
res["analysis"]["total_qty_m"]=round(sum(b["qty"] for b in batches),0)
with open(os.path.join(DATA,"finishing_schedule.json"),"w",encoding="utf-8") as f:
    json.dump(res,f,ensure_ascii=False,indent=2)
print("="*60)
print("状态:",status_name,"| 批次:",num,"| 总米数:",round(sum(b['qty'] for b in batches),0))
print("Makespan(完工):",res["statistics"].get("makespan_min"),"min =",res["statistics"].get("makespan_h"),"h")
print("总流转时间:",res["statistics"].get("total_flow_time_min"),"min")
print("各工序负载(分钟/利用率):")
for k,v in load.items(): print("  %-6s 负载%7d min  完工%7d min  利用率 %5.1f%%"%(k,v["total_load_min"],v["makespan_min"],v["utilization_pct"]))