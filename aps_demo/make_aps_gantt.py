import json, os
BASE=r"D:\dsh\cp_sat_demo\aps_demo"
d=json.load(open(os.path.join(BASE,"aps_schedule.json"),encoding="utf-8"))
tpl=open(os.path.join(BASE,"aps_gantt_template.html"),encoding="utf-8").read()
tpl=tpl.replace("window.__APS__=null;","window.__APS__="+json.dumps(d,ensure_ascii=False)+";")
open(os.path.join(BASE,"aps_gantt.html"),"w",encoding="utf-8").write(tpl)
print("aps_gantt.html written")
