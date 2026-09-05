import sys, os, json, math
sys.path.insert(0, r"D:\dsh\cp_sat_demo\libs")
from PIL import Image, ImageDraw, ImageFont
BASE=r"D:\dsh\cp_sat_demo"; DATA=os.path.join(BASE,"data")
d=json.load(open(os.path.join(DATA,"finishing_schedule.json"),encoding="utf-8"))
FONTS=[r"C:\Windows\Fonts\msyh.ttc",r"C:\Windows\Fonts\msyhbd.ttc",r"C:\Windows\Fonts\simhei.ttf",r"C:\Windows\Fonts\simsun.ttc"]
def font(sz):
    for f in FONTS:
        try: return ImageFont.truetype(f,sz)
        except Exception: continue
    return ImageFont.load_default()
F_T=font(30);F_H=font(18);F_L=font(15);F_S=font(13);F_T12=font(12)
TXT=(231,236,245); MUT=(147,162,189)
# stage colors: wash blue, coat orange, inspect green
SC={"wash":(78,158,245),"coat":(242,142,43),"insp":(78,201,165)}

jobs=sorted(d["jobs"], key=lambda x:x["release_min"])
mk=d["statistics"].get("makespan_min") or 1
W,Hh=1740, 150+len(jobs)*22
img=Image.new("RGB",(W,Hh),(15,20,32)); dr=ImageDraw.Draw(img)
dr.text((44,26),"落布批次 水洗→涂层→验布 流转流水图",font=F_T,fill=TXT)
dr.text((46,72),"每行=一个落布批次; 三段色=该批次在 水洗/涂层/验布 的加工时段; 白色短竖线=落布释放时刻",font=F_S,fill=MUT)
ML,MR,MT=90,60,110; rowh=22
# time axis
mkM=d["statistics"].get("makespan_min") or 1
def x(m): return ML + (m/mkM)*(W-ML-MR)
step=2*1440
for t in range(0,int(mkM)+1,step):
    px=x(t); dr.line([(px,MT-6),(px,MT+len(jobs)*rowh)],fill=(30,39,64))
    dr.text((px-8,MT-26),"D%d"%math.ceil(t/1440),font=F_T12,fill=MUT)
# legend
lx=ML+90
for k,lab in [("wash","水洗"),("coat","涂层"),("insp","验布")]:
    c=SC[k];     # fix y
    yl=MT+len(jobs)*rowh+12
    dr.rectangle([lx,yl,lx+16,yl+16],fill=c)
    dr.text((lx+22,yl+2),lab,font=F_S,fill=TXT)
    lx+=80
# rows
for i,j in enumerate(jobs):
    y=MT+i*rowh
    dr.rectangle([ML,y,W-MR,y+rowh],fill=(21,29,47) if i%2 else (26,35,53))
    # release marker
    rx=x(j["release_min"]); dr.line([(rx,y),(rx,y+rowh)],fill=(255,255,255),width=2)
    # segments
    for o in j["operations"]:
        sc = {0:"wash",1:"coat",2:"insp"}[o["machine"]]
        sx=x(o["start"]); sw=max(4,(o["end"]-o["start"])/mkM*(W-ML-MR))
        dr.rectangle([sx,y+4,sx+sw,y+rowh-4],fill=SC[sc])
    # label (product/loom) on left
    dr.text((ML-6,y+rowh/2-7),"%s@%s"%(j["product"],j["loom"]),font=F_T12,fill=MUT,anchor="rm")
img.save(os.path.join(BASE,"vis_batch_flow.png"))
print("flow png saved", img.size)