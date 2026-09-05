import zipfile, re, os, sys
import xml.etree.ElementTree as ET
P = r"D:\dsh\cp_sat_demo\需求文档.docx"
print("exists:", os.path.exists(P), "size:", os.path.getsize(P) if os.path.exists(P) else "-")
NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
z = zipfile.ZipFile(P)
names = z.namelist()
print("docx parts:", names[:20])
xml = z.read("word/document.xml").decode("utf-8", errors="replace")
root = ET.fromstring(xml)
body = root.find(NS+"body")
out = []
def para_text(p):
    texts=[]
    for t in p.iter(NS+"t"):
        texts.append(t.text or "")
    return "".join(texts)
def walk(elem, depth=0):
    for child in elem:
        tag = child.tag.replace(NS,"")
        if tag=="p":
            txt=para_text(child)
            if txt.strip():
                out.append(txt)
        elif tag=="tbl":
            out.append("[表格]")
            for tr in child.iter(NS+"tr"):
                cells=[]
                for tc in tr.iter(NS+"tc"):
                    ctxt="".join(para_text(p) for p in tc.iter(NS+"p"))
                    cells.append(ctxt.strip())
                out.append(" | ".join(cells))
            out.append("[/表格]")
        else:
            walk(child, depth+1)
walk(body)
text="\n".join(out)
open(r"D:\dsh\cp_sat_demo\_req.txt","w",encoding="utf-8").write(text)
print("text chars:", len(text))
print("---- first 300 ----")
print(text[:300])
