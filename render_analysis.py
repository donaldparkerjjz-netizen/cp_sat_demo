import sys, os, json, math, datetime
sys.path.insert(0, r"D:\dsh\cp_sat_demo\libs")
from PIL import Image, ImageDraw, ImageFont
BASE=r"D:\dsh\cp_sat_demo"; DATA=os.path.join(BASE,"data")
d=json.load(open(os.path.join(DATA,"finishing_schedule.json"),encoding="utf-8"))
ml=d["analysis"]["machine_load"]
FONTS=[r"C:\Windows\Fonts\msyh.ttc",r"C:\Windows\Fonts\msyhbd.ttc",r"C:\Windows\Fonts\simhei.ttf",r"C:\Windows\Fonts\simsun.ttc"]
def font(sz):
    for f in FONTS:
        try: return ImageFont.truetype(f,sz)
        except Exception: continue
    return ImageFont.load_default()
F_T=font(30);F_H=font(20);F_L=font(16);F_S=font(13);F_T12=font(12)
TXT=(231,236,245); MUT=(147,162,189); ACC=(78,158,245); ACC2=(78,201,165)

# ------- daily 落布 -------
daily={}
for it in d["schedule"]: daily[it["date"]]=daily.get(it["date"],0)
# read actual qty per date from jobs
daily={}
for j in d["jobs"]: daily[j["date"]]=daily.get(j["date"],0)+j["qty"]
dates=sorted(daily); maxd=max(daily.values())
cap12={"水洗机":12000,"涂层机":9000,"验布机":7000}

W,Hh=1740,900
img=Image.new("RGB",(W,Hh),(15,20,32)); dr=ImageDraw.Draw(img)
dr.text((44,30),"织造后整链 · 排产分析",font=F_T,fill=TXT)
dr.text((46,76),"数据: 益丰生产管理表单260604.xlsx 落布预测(6月) · CP-SAT 最优排程 · 45批次/%.0f米"%(d["meta"]["total_qty_m"]),font=F_S,fill=MUT)

# ---- KPI row ----
kpis=[("落布批次","45"),("6月落布量","%.0f 米"%d["meta"]["total_qty_m"]),("后整完工","%.1f h"%d["statistics"].get("makespan_h",0)),("平均流转","%.0f min/批"%(d["statistics"].get("total_flow_time_min",0)/45)),("求解状态",d["statistics"]["status"])]
kx=46; ky=104
for i,(k,v) in enumerate(kpis):
    dr.rounded_rectangle([kx,ky,kx+300,ky+70],radius=12,fill=(30,39,64),outline=(42,53,80))
    dr.text((kx+16,ky+10),k,font=F_S,fill=MUT)
    dr.text((kx+16,ky+36),v,font=F_H,fill=TXT)
    kx+=312

# ---- Panel 1: utilization bars ----
y0=210
dr.text((46,y0),"一、后整工序利用率（相对完工时间）",font=F_H,fill=ACC2)
rows=[("水洗机",ml["水洗机"]["utilization_pct"]),("涂层机",ml["涂层机"]["utilization_pct"]),("验布机",ml["验布机"]["utilization_pct"]),("织造(估算)",0)]
total_q=d["meta"]["total_qty_m"]; weave_cap=30*400*30
rows[-1]=("织造(估算)",100*total_q/weave_cap)
ry=y0+40; maxbar=500
dr.rounded_rectangle([46,ry,46+maxbar+20,ry+4*52],radius=8,fill=(20,28,44),outline=(42,53,80))
for i,(name,pct) in enumerate(rows):
    by=ry+i*52
    w=max(6,pct/100*maxbar)
    dr.rounded_rectangle([46,by+8,46+w,by+40],radius=8,fill=(78,158,245) if pct<10 else (226,87,89))
    dr.text((46+w+12,by+14),"%s  %.1f%%"%(name,pct),font=F_L,fill=TXT)

# ---- Panel 2: daily demand vs capacity ----
py=y0+40+4*52+30
dr.text((46,py),"二、每日落布(织造产出) vs 后整班产能",font=F_H,fill=ACC2)
chart_top=py+36; chart_h=250; left=80; right=W-60
ycap=8000  # y-axis max
def yy(v): return chart_top+chart_h-(v/ycap)*chart_h
# capacity lines
caps=[("水洗 12000",12000,ACC2),("涂层 9000",9000,(226,87,89)),("验布 7000",7000,(255,204,102))]
# draw grid
for gv in [2000,4000,6000,8000]:
    dr.line([(left,yy(gv)),(right,yy(gv))],fill=(30,39,64))
    dr.text((left-6,yy(gv)-7),"%d"%gv,font=F_T12,fill=MUT,anchor="rm")
# bars
nb=len(dates); bw=(right-left)/nb
for i,dt in enumerate(dates):
    bx=left+i*bw+bw*0.15
    h=yy(daily[dt])
    dr.rectangle([bx,h,bx+bw*0.7,yy(0)],fill=(78,158,245))
    if i%5==0: dr.text((left+i*bw+bw/2-10,yy(0)+8),str(int(dt[8:10])),font=F_T12,fill=MUT)
# capacity lines (labels)
for name,val,c in caps:
    yv=yy(val)
    dr.line([(left,yv),(right,yv)],fill=c,width=2)
    dr.text((right+6,yv-8),name,font=F_T12,fill=c)
# caption
dr.text((46,yy(0)+30),"单日最大落布 %.0f 米(%s)  <  最紧的验布班产能 7000 米 → 后整可即时消化(拉动式)"%(maxd,max(daily,key=daily.get)),font=F_S,fill=MUT)

# ---- Panel 3: conclusion ----
cy=yy(0)+72
dr.text((46,cy),"三、瓶颈结论",font=F_H,fill=ACC2)
dr.text((46,cy+36),"各环节利用率均 < 10%, 后整三工序 4.6% / 6.1% / 7.9%",font=F_L,fill=TXT)
dr.text((46,cy+62),"→ 当前约束在需求端(订单/市场), 不在产能",font=F_H,fill=(255,204,102))
img.save(os.path.join(BASE,"vis_analysis.png"))
print("analysis png saved", img.size)