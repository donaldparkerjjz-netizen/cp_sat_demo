import sys, os, json, math
sys.path.insert(0, r"D:\dsh\cp_sat_demo\libs")
from PIL import Image, ImageDraw, ImageFont

BASE=r"D:\dsh\cp_sat_demo"; DATA=os.path.join(BASE,"data")
d=json.load(open(os.path.join(DATA,"finishing_schedule.json"),encoding="utf-8"))

# ---- Chinese font ----
FONTS = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf",
         r"C:\Windows\Fonts\simsun.ttc", r"C:\Windows\Fonts\msyh.ttf"]
def font(size, bold=False):
    for f in FONTS:
        try: return ImageFont.truetype(f, size)
        except Exception: continue
    return ImageFont.load_default()
F_TITLE=font(30,bold=True); F_H=font(20,bold=True); F_L=font(16); F_S=font(13); F_T=font(12)

PALETTE=["#4e79a7","#f28e2b","#e15759","#76b7b2","#59a14f","#edc949","#af7aa1","#ff9da7","#9c755f","#49b8c4","#b6992d","#d37295","#499894","#86bcb6","#7f7f7f","#c3c6c7"]
def hx(s):
    s=s.lstrip("#"); return tuple(int(s[i:i+2],16) for i in (0,2,4))

# color per product
products=[]
for it in d["schedule"]:
    if it["product"] not in products: products.append(it["product"])
pcolor={p:hx(PALETTE[i%len(PALETTE)]) for i,p in enumerate(products)}

# ================= GANTT PNG =================
W,Hh=1680,760
img=Image.new("RGB",(W,Hh),(15,20,32)); dr=ImageDraw.Draw(img)
ML,MR,MT,MB=210,70,140,120
rows=d["machines"]
rowh=(Hh-MT-MB)/len(rows)
mk=d["statistics"].get("makespan_min") or 1
def x(m): return ML + (m/mk)*(W-ML-MR)
ymin=min(it["release_min"] if "release_min" in it else 0 for it in d["jobs"]) if d["jobs"] else 0
# title
dr.text((40,34),"织造后整链 CP-SAT 排产甘特图",font=F_TITLE,fill=(231,236,245))
dr.text((42,80),"落布(织造产出) → 水洗 → 涂层 → 验布 · %d 批次, %.0f 米, 完工 %.1f h (%.1f%%利用率)"%(d["meta"]["batches"],d["meta"]["total_qty_m"],d["statistics"].get("makespan_h",0),0),font=F_S,fill=(147,162,189))
dr.text((42,102),"每行=一道工序(机器), 色块=一个落布批次(按产品着色)",font=F_T,fill=(147,162,189))
# grid days
step=2*1440
for t in range(0, int(mk)+1, step):
    px=x(t)
    dr.line([(px,MT),(px,MT+len(rows)*rowh)],fill=(42,53,80),width=1)
    day=math.ceil(t/1440)
    dr.text((px-8,MT-26),"D%d"%day,font=F_T,fill=(147,162,189))
# rows + bars
for r,label in enumerate(rows):
    y0=MT+r*rowh
    dr.rectangle([ML,y0,W-MR,y0+rowh],fill=(26,35,53) if r%2==0 else (21,29,47))
    dr.text((ML-14,y0+rowh/2-9),label,font=F_H,fill=(199,210,230),anchor="rm")
    # bar for each batch on this machine
    for it in d["schedule"]:
        job=d["jobs"][it["job"]]
        op=None
        for o in job["operations"]:
            if o["machine"]==r: op=o;break
        if not op: continue
        bx=x(op["start"]); bw=max(4,(op["end"]-op["start"])/mk*(W-ML-MR))
        c=pcolor.get(it["product"],(200,200,200))
        dr.rounded_rectangle([bx,y0+10,bx+bw,y0+rowh-10],radius=6,fill=c,outline=(0,0,0))
# machine bottom line
dr.line([(ML,MT+len(rows)*rowh),(W-MR,MT+len(rows)*rowh)],fill=(42,53,80),width=2)
# legend
ly=MT+len(rows)*rowh+16
dr.text((ML,ly),"产品图例:",font=F_S,fill=(147,162,189))
lx=ML+80
cols=3
for i,p in enumerate(products):
    if i%cols==0: pass
    while lx+150>W-MR: lx=ML+80; ly+=24
    c=pcolor[p]
    dr.rectangle([lx,ly,lx+16,ly+16],fill=c)
    dr.text((lx+22,ly+1),p,font=F_T,fill=(199,210,230))
    lx+=150
img.save(os.path.join(BASE,"vis_finishing_gantt.png"))
print("gantt png saved", img.size)
