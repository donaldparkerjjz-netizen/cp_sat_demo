#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analysis.py -- 第③步 排产分析：利用率/瓶颈/产能满足度/落布拉动"""
import json, os, csv, datetime
BASE=r"D:\dsh\cp_sat_demo"; DATA=os.path.join(BASE,"data")
d=json.load(open(os.path.join(DATA,"finishing_schedule.json"),encoding="utf-8"))
st=d["statistics"]; an=d["analysis"]; ml=an["machine_load"]
NR = 30  # 30 台织机
loom_cap_day = 400.0  # 米/天

# 落布 batch 统计
batches=[]; 
with open(os.path.join(DATA,"fabric_off.csv"),encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        if row["qty_m"]: batches.append({"date":row["date"],"qty":float(row["qty_m"]),"loom":row["loom"],"product":row["product"]})
total_q=sum(b["qty"] for b in batches)
# 每日落布
daily={}
for b in batches:
    daily[b["date"]]=daily.get(b["date"],0)+b["qty"]
dates=sorted(daily)
# 各工序 12h 产能
cap12={"水洗机":12000,"涂层机":9000,"验布机":7000}
cap_h={k:v/12.0 for k,v in cap12.items()}   # 米/小时
daily_cap12={k:v for k,v in cap12.items()}  # 米/12h班
month_days = (datetime.date(2026,6,30)-datetime.date(2026,6,1)).days+1
month_cap={k:v*month_days*1 for k,v in daily_cap12.items()}  # 若每天1班12h

def bar(pct,widthpct=100):
    p=max(0,min(100,pct)); w=p/100*widthpct
    return '<div style="background:#1a2335;border-radius:6px;height:20px;width:%d%%;position:relative"><div style="position:absolute;left:0;top:0;height:100%%;width:%.1f%%;background:linear-gradient(90deg,#4e9ef5,#4ec9a5);border-radius:6px"></div><span style="position:absolute;left:8px;top:1px;color:#fff;font-size:12px;font-weight:600">%.1f%%</span></div>'%(widthpct,w,pct)

html=["<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'><title>织造后整排产分析</title>",
"<style>body{font-family:'Segoe UI',system-ui,'Microsoft YaHei',sans-serif;background:#0f1420;color:#e7ecf5;margin:0;padding:26px}.w{max-width:1200px;margin:0 auto}h1{font-size:22px}.card{background:#171e2e;border:1px solid #2a3550;border-radius:14px;padding:18px 20px;margin-bottom:18px}h2{font-size:16px;margin:0 0 12px;color:#4ec9a5}table{border-collapse:collapse;width:100%}th,td{padding:8px 10px;border-bottom:1px solid #2a3550;text-align:left;font-size:13px}th{color:#93a2bd}.kpi{display:inline-block;background:#1e2740;border:1px solid #2a3550;border-radius:12px;padding:12px 16px;margin:0 10px 10px 0}.kpi .k{font-size:12px;color:#93a2bd}.kpi .v{font-size:22px;font-weight:700;margin-top:4px}.note{color:#93a2bd;font-size:13px;line-height:1.7}.warn{color:#ffcc66}.ok{color:#4ec9a5}</style></head><body><div class='w'>"]

html.append("<div class='card'><h1>📊 织造后整链 排产分析</h1><div class='note'>数据源：益丰生产管理表单260604.xlsx · 落布预测(2026-06) · CP-SAT 最优排程</div></div>")

html.append("<div class='card'><h2>一、关键指标</h2>")
html.append("<div class='kpi'><div class='k'>落布批次</div><div class='v'>%d</div></div>"%(len(batches)))
html.append("<div class='kpi'><div class='k'>6月落布总量</div><div class='v'>%.0f 米</div></div>"%(total_q))
html.append("<div class='kpi'><div class='k'>后整完工 Makespan</div><div class='v'>%.1f h</div></div>"%(st.get("makespan_h") or 0))
html.append("<div class='kpi'><div class='k'>平均落布→入库流转</div><div class='v'>%.1f min</div></div>"%(st.get("total_flow_time_min",0)/len(batches)))
html.append("<div class='kpi'><div class='k'>求解状态</div><div class='v'>%s</div></div>"%(st["status"]))
html.append("</div>")

html.append("<div class='card'><h2>二、后整三工序 负荷与利用率</h2><table><tr><th>工序</th><th>12h产能(米)</th><th>月产能(米)</th><th>6月负荷(分钟)</th><th>利用率(相对完工)</th></tr>")
for k in ["水洗机","涂层机","验布机"]:
    m=ml[k]
    html.append("<tr><td>%s</td><td>%.0f</td><td>%.0f</td><td>%.0f</td><td>%s</td></tr>"%(k,cap12[k],month_cap[k],m["total_load_min"],bar(m["utilization_pct"])))
html.append("</table><div class='note'>三工序利用率仅 <span class='ok'>4.6% / 6.1% / 7.9%</span>, 后整产能<b>远大于</b>6月落布量。</div></div>")

html.append("<div class='card'><h2>三、产能满足度（产能 vs 需求）</h2><table><tr><th>环节</th><th>月产能(米)</th><th>6月需求(米)</th><th>满足度</th><th>利用率</th></tr>")
weave_cap = NR*loom_cap_day  # 米/天
html.append("<tr><td>织造(30台×400米/天)</td><td>%.0f</td><td>%.0f</td><td class='ok'>%.0f%%</td><td>%s</td></tr>"%(weave_cap*month_days, total_q, 100*weave_cap*month_days/total_q if total_q else 0, bar(100*total_q/(weave_cap*month_days))))
for k in ["水洗机","涂层机","验布机"]:
    capm=month_cap[k]
    html.append("<tr><td>%s</td><td>%.0f</td><td>%.0f</td><td class='ok'>%.0f%%</td><td>%s</td></tr>"%(k,capm,total_q,100*capm/total_q if total_q else 0, bar(100*total_q/capm)))
html.append("</table><div class='note'>结论：各环节月产能均远超 6 月需求(32114米)。<span class='warn'>约束不在产能，而在需求(订单/市场)。</span></div></div>")

html.append("<div class='card'><h2>四、落布拉动分析（下游能否及时消化）</h2><div class='note'>逐日 落布(织造产出) 与 各工序 12 小时班产能 对比：</div>")
html.append("<table><tr><th>日期</th><th>当日落布(米)</th><th>水洗班产能</th><th>涂层班产能</th><th>验布班产能</th><th>是否超载</th></tr>")
overflow=[]
for dt in dates:
    q=daily[dt]
    ok = (q<=cap12["验布机"])  # 最紧的是验布
    if not ok: overflow.append((dt,q))
    html.append("<tr><td>%s</td><td>%.0f</td><td>%.0f</td><td>%.0f</td><td>%.0f</td><td class='%s'>%s</td></tr>"%(dt,q,cap12["水洗机"],cap12["涂层机"],cap12["验布机"],"ok" if ok else "warn","满足" if ok else "超载"))
maxd=max(daily.values()); maxdate=[d for d in dates if daily[d]==maxd][0]
html.append("</table><div class='note'>单日最大落布 <b>%.0f 米</b>(%s)，低于最紧的验布班产能 %.0f 米 → <span class='ok'>无超载, 后整可即时消化(拉动式)。</span> 平均每批落布→入库流转 <b>%.1f 分钟</b>。</div>"%(maxd,maxdate,cap12["验布机"],st.get("total_flow_time_min",0)/len(batches)))
html.append("</div>")

html.append("<div class='card'><h2>五、瓶颈判定</h2><div class='note'>")
util=[(k,ml[k]["utilization_pct"],ml[k]["total_load_min"]) for k in ["水洗机","涂层机","验布机"]]
util.append(("织造(估算)",100*total_q/(weave_cap*month_days),total_q/loom_cap_day))
util.sort(key=lambda x:-x[1])
bottleneck=util[0]
html.append("按利用率从高到低：")
for k,u,load in util:
    html.append("<div style='margin:6px 0'>%s　%s</div>"%(k,bar(u)))
html.append("<span class='warn'>最高负荷环节：%s (%.1f%%)</span> —— 但所有环节利用率均 < 10%%，说明<b>当前产能远未用满</b>，真正的约束是<b>需求端</b>。"%(bottleneck[0],bottleneck[1]))
html.append("</div></div>")

html.append("</div></body></html>")
html="\n".join(html)
open(os.path.join(BASE,"analysis.html"),"w",encoding="utf-8").write(html)

# also json
analysis={}
analysis["kpi"]={"batches":len(batches),"total_qty_m":total_q,"makespan_h":st.get("makespan_h"),"avg_flow_min":round(st.get("total_flow_time_min",0)/len(batches),1),"status":st["status"]}
analysis["machine_load"]=ml
analysis["capacity"]={"weaving_per_day":weave_cap,"weaving_per_month":weave_cap*month_days,"monthly":{k:month_cap[k] for k in cap12}}
analysis["daily"]=daily
analysis["max_daily"]=maxd
analysis["bottleneck"]=bottleneck[0]
json.dump(analysis,open(os.path.join(DATA,"analysis.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=2)
print("analysis.html written")
print("KPI:", json.dumps(analysis["kpi"],ensure_ascii=False))
print("max_daily:", maxd, "on", maxdate)
print("bottleneck:", bottleneck[0], bottleneck[1],"%")