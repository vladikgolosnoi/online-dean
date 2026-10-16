"""Replay exactly the previously downloaded diagnostic set; no new selection."""
import json
import time
from app.config import ROOT
from app.ocr import run_ocr
from scripts.evaluate_mws import norm, edit_distance

folder=ROOT/'output'/'mws-diagnostic'
report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
cases=[]
for old in report['cases']:
    start=time.perf_counter()
    result=run_ocr((folder/(str(old['id'])+'.image')).read_bytes())
    elapsed=round((time.perf_counter()-start)*1000)
    actual=norm(result['text'])
    best=min(((edit_distance(actual,norm(ref)),len(norm(ref))) for ref in old['references']),key=lambda p:p[0]/max(p[1],1))
    row={**old,'cer':best[0]/max(best[1],1),'edit_distance':best[0],'reference_characters':best[1],'prediction':result['text'],'ocr_ms':elapsed}
    row.pop('timing_ms',None)
    cases.append(row)
    print(json.dumps({'id':row['id'],'cer':row['cer'],'ocr_ms':elapsed}),flush=True)
report.update(cases=cases,micro_cer=sum(c['edit_distance'] for c in cases)/sum(c['reference_characters'] for c in cases),version='dean-2')
(folder/'report-v2.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
