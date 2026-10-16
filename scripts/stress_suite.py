from app.config import RULES as LEGACY_RULES
"""Reproducible synthetic robustness suite with different text/layouts and distortions."""
import io
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from app.config import ROOT
from app.pipeline import analyze
from app.extraction import normalize
from scripts.generate_samples import font

CASES = [
    {'id':'study', 'type':'study_certificate', 'lines':[
        'Северный технический университет', 'СПРАВКА ОБ ОБУЧЕНИИ', '№ 509/26 от «12» октября 2026 года',
        'Настоящая справка выдана Козлову Максиму Андреевичу',
        'Направление подготовки: 09.03.02 Информационные системы',
        'Форма обучения: Заочная', 'Период обучения: 01.09.2024 - 30.06.2026'],
     'fields':{'student_name':'Козлову Максиму Андреевичу','university':'Северный технический университет',
               'program':'09.03.02 Информационные системы','study_mode':'Заочная','study_period':'01.09.2024 — 30.06.2026','document_number':'509/26','issue_date':'12.10.2026'}},
    {'id':'leave', 'type':'academic_leave', 'lines':[
        'ЗАЯВЛЕНИЕ НА АКАДЕМИЧЕСКИЙ ОТПУСК','ФИО студента:', 'Волкова Мария Петровна',
        'Группа: ПИ-31 Курс: 3', 'Причина отпуска: По состоянию здоровья',
        'Дата начала отпуска: 01 ноября 2026', 'Дата окончания отпуска: 31 августа 2027', 'Дата заявления: 12 октября 2026'],
     'fields':{'student_name':'Волкова Мария Петровна','group':'ПИ-31','course':'3','reason':'По состоянию здоровья',
               'start_date':'01.11.2026','end_date':'31.08.2027','application_date':'12.10.2026'}},
    {'id':'internship', 'type':'internship_certificate', 'lines':[
        'СПРАВКА О ПРАКТИКЕ', 'ФИО: Орлова Дарья Николаевна', 'Организация: ООО Горизонт',
        'Сроки практики: 01.08.2026 - 28.08.2026', 'Руководитель практики: Лебедев Павел Иванович',
        'Оценка: Хорошо', '№ 92/26 от 31 августа 2026'],
     'fields':{'student_name':'Орлова Дарья Николаевна','organization':'ООО Горизонт','internship_period':'01.08.2026 — 28.08.2026',
               'supervisor':'Лебедев Павел Иванович','grade':'Хорошо','document_number':'92/26','issue_date':'31.08.2026'}}]


def fixture(case):
    im=Image.new('RGB',(1800,2200),'white');d=ImageDraw.Draw(im)
    try:
        face=ImageFont.truetype(r'C:\Windows\Fonts\times.ttf',42)
    except OSError:
        face=font(42)
    y=140
    for line in case['lines']:
        d.text((120,y),line,font=face,fill='#161616')
        y += 62 if line.endswith(':') else 125
    # Footer is deliberately printed, empty; no synthetic signature or stamp.
    d.text((120,y+130),'Подпись: ____________________',font=face,fill='#161616')
    d.text((120,2050),'СИНТЕТИЧЕСКИЙ ДОКУМЕНТ ДЛЯ ТЕСТИРОВАНИЯ',font=font(25),fill='#606060')
    return im


def variants(im):
    yield 'clean', im
    yield 'tilt_minus30', im.rotate(-30,expand=True,fillcolor='white')
    yield 'tilt_plus30', im.rotate(30,expand=True,fillcolor='white')
    arr=np.array(im).astype(float)
    shadow=np.linspace(.44,1,im.width)[None,:,None]
    yield 'shadow', Image.fromarray(np.clip(arr*shadow,0,255).astype('uint8'))
    buf=io.BytesIO();im.resize((900,1100)).save(buf,format='JPEG',quality=40)
    yield 'jpeg_lowres', Image.open(io.BytesIO(buf.getvalue())).convert('RGB')
    yield 'orientation90', im.rotate(90,expand=True,fillcolor='white')


def main():
    folder=ROOT/'output'/'stress';folder.mkdir(parents=True,exist_ok=True)
    results=[]
    for case in CASES:
        for variant, image in variants(fixture(case)):
            name=case['id']+'_'+variant
            path=folder/(name+'.png');image.save(path)
            r=analyze(path.read_bytes(),'Проверьте комплектность документа', rules=LEGACY_RULES)
            errors=[]
            for key,value in case['fields'].items():
                f=r['fields'].get(key,{})
                if normalize(str(f.get('value'))) != normalize(value) or f.get('status')!='found':
                    errors.append({'field':key,'expected':value,'actual':f.get('value'),'status':f.get('status')})
            marks=sum(len(p.get('visual_marks',[])) for p in r['ocr']['pages'])
            row={'id':name,'variant':variant,'correct':len(case['fields'])-len(errors),'total':len(case['fields']),
                 'type_correct':r['document_type']==case['type'],'false_visual_proposals':marks,
                 'timing_ms':r['timing_ms'],'errors':errors,'quality':r['ocr']['pages'][0]['quality']}
            results.append(row)
            print(json.dumps({k:row[k] for k in ['id','correct','total','type_correct','timing_ms']},ensure_ascii=False),flush=True)
            (folder/(name+'.json')).write_text(json.dumps({'fields':r['fields'],'text':r['ocr']['text'],'answer':r['answer']},ensure_ascii=False,indent=2),encoding='utf-8')
    times=[r['timing_ms'] for r in results]
    report={'scope':'Synthetic alternate layouts; 3 templates x 6 controlled variants. Not organizer data or independent holdout.',
            'count':len(results),'field_exact_match':sum(r['correct'] for r in results)/sum(r['total'] for r in results),
            'type_accuracy':sum(r['type_correct'] for r in results)/len(results),
            'latency_p50_ms':float(np.percentile(times,50)),'latency_p95_ms':float(np.percentile(times,95)),
            'false_visual_proposals':sum(r['false_visual_proposals'] for r in results),'cases':results}
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
