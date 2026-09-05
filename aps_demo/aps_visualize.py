import sys, os, json, math
sys.path.insert(0, r"D:\dsh\cp_sat_demo\libs")
from PIL import Image, ImageDraw, ImageFont
BASE=r"D:\dsh\cp_sat_demo\aps_demo"
d=json.load(open(os.path.join(BASE,"aps_schedule.json"),encoding="utf-8"))
FONTS=[r"C:\Windows\Fonts\msyh.ttc",r"C:\Windows\Fonts\msyhbd.ttc",r"C:\Windows\Fonts\simhei.ttf",r"C:\Windows\Fonts\simsun.ttc"]
def font(sz):
    for f in FONTS:
        try: return ImageFont.truetype(f,sz)
        except Exception: continue
    return ImageFont.load_default()
F_T=font(28);F_H=font(18);F_L=font(15);F_S=font(13);F_T12=font(12)
TXT=(231,236,245);MUT=(147,162,189)
PALETTE=["#4e79a7","#f28e2b","#e15759","#76b7b2","#59a14f","#edc949","#af7aa1","#ff9da7"]
def hx(s): s=s.lstrip("#");return tuple(int(s[i:i+2],16) for i in (0,2,4))
prods=[]
for s in d["schedule"]:
    if s["product"] not in prods: prods.append(s["product"])
pcolor={p:hx(PALETTE[i%len(PALETTE)]) for i,p in enumerate(prods)}
M=d["machines"]; T=d["meta"]["num_slots"]; SPD=d["meta"]["shifts_per_day"]
CW,CH=72,58; ML,MT=210,140; MR=30
W=ML+ T*CW + MR; H=MT+ len(M)*CH + 130
img=Image.new("RGB",(W,H),(15,20,32)); dr=ImageDraw.Draw(img)
dr.text((44,28),"减振车间 APS 排产甘特图 (机台 × 班次)",font=F_T,fill=TXT)
dr.text((46,74),"7天×2班(白/夜)=14槽 · CP-SAT OPTIMAL · 16 订单 · 换模8次 · 正常机台工资已均衡",font=F_S,fill=MUT)
occ={}  # (m,t)->job
for s in d["schedule"]: occ[(s["machine"],s["slot"])]=s
# header slot labels
for t in range(T):
    day=t//SPD+1; shift="白" if t%2==0 else "夜"
    x=ML+t*CW; dr.rectangle([x,MT-40,x+CW,MT],fill=(26,35,53))
    dr.text((x+CW/2,MT-33),"%d天%s"%(day,shift),font=F_S,fill=MUT,anchor="ma")
# rows
for mi,m in enumerate(M):
    y=MT+mi*CH
    dr.rectangle([ML-2,y,W-MR,y+CH],fill=(21,29,47) if mi%2 else (26,35,53))
    dr.text((ML-12,y+CH/2-8),m,font=F_H,fill=TXT,anchor="rm")
    for t in range(T):
        x=ML+t*CW; s=occ.get((m,t))
        if s:
            c=pcolor[s["product"]]
            dr.rounded_rectangle([x+3,y+3,x+CW-3,y+CH-3],radius=7,fill=c)
            dr.text((x+CW/2,y+CH/2-10),s["job"],font=F_T12,fill=(255,255,255),anchor="ma")
            dr.text((x+CW/2,y+CH/2+8),s["product"],font=F_T12,fill=(255,255,255),anchor="ma")
        else:
            dr.rectangle([x+3,y+3,x+CW-3,y+CH-3],fill=(30,39,64))
# changeover markers between adjacent occupied diff-product
for mi,m in enumerate(M):
    y=MT+mi*CH
    for t in range(T-1):
        a=occ.get((m,t)); b=occ.get((m,t+1))
        if a and b and a["product"]!=b["product"]:
            x=ML+(t+1)*CW; dr.polygon([(x,y+CH/2-8),(x-8,y+CH/2),(x,y+CH/2+8)],fill=(255,204,102))
# legend
ly=MT+len(M)*CH+16
dr.text((ML,ly),"产品:",font=F_S,fill=MUT)
lx=ML+50
for i,p in enumerate(prods):
    if lx+120>W-MR: lx=ML+50; ly+=24
    dr.rectangle([lx,ly+2,lx+14,ly+16],fill=pcolor[p])
    dr.text((lx+20,ly+1),p,font=F_T12,fill=(199,210,230)); lx+=120
# notes
dr.text((ML,ly+26),"黄色三角=换模/清机(不同产品连续需空档) · 空槽=未排产",font=F_T12,fill=MUT)
img.save(os.path.join(BASE,"aps_gantt.png"))
print("aps gantt png saved", img.size)
