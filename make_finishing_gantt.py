import json, os
BASE=r"D:\dsh\cp_sat_demo"; DATA=os.path.join(BASE,"data")
with open(os.path.join(DATA,"finishing_schedule.json"),encoding="utf-8") as f:
    d=json.load(f)
tpl=open(os.path.join(BASE,"gantt_template.html"),encoding="utf-8").read()
data_json=json.dumps(d,ensure_ascii=False)
out=tpl.replace("window.__SCHEDULE__ = null;","window.__SCHEDULE__ = "+data_json+";")
dst=os.path.join(BASE,"finishing_gantt.html")
open(dst,"w",encoding="utf-8").write(out)
print("written", dst, "size", len(out))
