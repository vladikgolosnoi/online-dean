"""Official Meridian v1 contract. No reference answers, IDs or network in inference."""
import json
import re
from datetime import datetime
from .config import CONFIG_DIR
from .extraction import extract, normalize
from .knowledge import fingerprint

SCHEMAS = json.loads((CONFIG_DIR / 'official-documents.json').read_text(encoding='utf-8'))
RULES = json.loads((CONFIG_DIR / 'official-rules.json').read_text(encoding='utf-8'))


def positioned_marks(ocr, field_key, kind):
    """Only accept a graphical mark located near its own document field.

    The competition FAQ explicitly treats a seal or signature in a wrong place as
    invalid. A page-level detector therefore is not sufficient for the official
    profile: each proposal must be close to a printed label such as ``Подпись``
    or ``М.П.`` on the same page.
    """
    aliases = [item.casefold() for item in SCHEMAS[ocr['document_type']]['fields'][field_key]['aliases']]
    pages = {page.get('number', index + 1): page for index, page in enumerate(ocr['pages'])}
    accepted = []
    for page in ocr['pages']:
        number = page.get('number', 1)
        marks = [mark for mark in page.get('visual_marks', []) if mark['kind'] == kind]
        labels = [line for line in ocr['lines'] if line.get('page') == number and
                  any(alias in line.get('text', '').casefold() for alias in aliases)]
        height = page.get('height', 1800)
        for mark in marks:
            mx1, my1, mx2, my2 = mark['bbox']
            mark_y = (my1 + my2) / 2
            # A label can be printed below a stamp but should remain in the
            # same signature block.  This is deliberately generous for scans
            # while rejecting marks placed elsewhere on the page.
            if any(abs(mark_y - ((line['bbox'][1] + line['bbox'][3]) / 2)) <= height * .16
                   for line in labels):
                accepted.append(mark)
    return accepted


def extract_official(ocr, document_type):
    ocr = {**ocr, 'document_type': document_type}
    fields = extract(ocr['lines'], document_type, SCHEMAS)
    for key, f in fields.items():
        if f['kind'] == 'date' and f['value'] and f['status'] == 'found':
            f['value'] = datetime.strptime(f['value'], '%d.%m.%Y').strftime('%Y-%m-%d')
        if f['kind'] == 'visual':
            kind = 'stamp' if key == 'seal_present' else 'signature'
            marks = positioned_marks(ocr, key, kind)
            f.update(value=bool(marks), status='found' if marks else 'not_found', source='visual_presence', confidence=None,
                     evidence=[{'page':m['page'],'bbox':m['bbox'],'confidence':None,'text':m['explanation']} for m in marks])
    return fields


def values(fields):
    return {k: (bool(f['value']) if f['kind']=='visual' else str(f['value']) if f['status'] in ('found','confirmed') and f['value'] else 'не найдено') for k,f in fields.items()}


def validation(fields, document_type, rules=RULES):
    data = values(fields)
    requirements = [c for c in rules['clauses'] if c['document_type']==document_type and c.get('required_fields')]
    missing = [k for k,v in data.items() if v is False or v=='не найдено']
    sources = ['rule:'+c['id'] for c in requirements if not missing or any(k in missing for k in c['required_fields'])]
    return {'status':'missing_fields' if missing else 'document_ok','missing_fields':missing,'sources':sources}


def structured_answer(question, fields, document_type, rules=RULES):
    q=normalize(question)
    result={'answerable':False,'value':None,'answer':'В документе и в Положении нет информации для ответа на этот вопрос. Обратитесь в деканат.','sources':[]}
    if any(t in q for t in ('игнорируй','выдумай','забудь правила')): return result
    explicit = re.search(r'пункт\w*\s+(\d+\.\d+)', q)
    policy_ids = [explicit[1]] if explicit else []
    if any(t in q for t in ('нужна ли', 'нужен ли', 'требуется ли', 'обязательна ли')):
        if 'печат' in q:
            policy_ids = ['4.3'] if document_type == 'academic_leave_application' else [c['id'] for c in rules['clauses'] if c['document_type']==document_type and 'seal_present' in c.get('required_fields', [])]
        elif 'подпис' in q:
            policy_ids = [c['id'] for c in rules['clauses'] if c['document_type']==document_type and 'signature_present' in c.get('required_fields', [])]
    if any(t in q for t in ('какие поля обязательны', 'какие сведения обязательны')):
        policy_ids = [c['id'] for c in rules['clauses'] if c['document_type']==document_type and c.get('required_fields')]
    policy = [c for c in rules['clauses'] if c['id'] in policy_ids]
    if policy:
        text = ' '.join(c['text'] for c in policy)
        return {'answerable':True, 'value':text, 'answer':text, 'sources':['rule:'+c['id'] for c in policy]}
    if ('кто' in q or 'кем' in q) and any(t in q for t in ('решение','принимает документ','принятии')):
        return {'answerable':True,'value':'сотрудник деканата','answer':'Окончательное решение принимает сотрудник деканата (пункт 1.3).','sources':['rule:1.3']}
    completeness = any(t in q for t in ('все обязательные','комплектност','все ли поля','чего не хватает','каких полей не хватает','проверь документ','документ в порядке','достаточно ли данных для проверки'))
    if completeness:
        v=validation(fields,document_type,rules)
        text=('Не хватает обязательных сведений: '+', '.join(fields[k]['label'] for k in v['missing_fields'])+'.') if v['missing_fields'] else 'Документ содержит все обязательные сведения.'
        text+=' Пункты '+', '.join(s.removeprefix('rule:') for s in v['sources'])+' Положения. Окончательное решение примет сотрудник деканата.'
        return {'answerable':True,'value':v['status'],'answer':text,'sources':v['sources']}
    if any(t in q for t in ('стипенд', 'стоим', 'телефон', 'срок рассмотрения', 'перезач', 'задолжен', 'перевод', 'размер выплат', 'максимальн')):
        return result
    # Exact labels and conservative natural synonyms; no answers to unrelated policy questions.
    aliases={'student_name':['кому выдан','как зовут студента'], 'issue_date':['когда выдан'],
             'organization':['где проходил','где проходила'], 'course':['на каком курсе'],
             'group':['в какой группе'],'grade':['какая оценка'],'supervisor_name':['кто руководитель'],
             'study_start':['когда начинается обучение'],'study_end':['когда заканчивается обучение'],
             'internship_start':['когда начинается практика'],'internship_end':['когда заканчивается практика'],
             'seal_present':['есть ли печать'],'signature_present':['есть ли подпись']}
    quoted=re.search(r'[«“"]([^»”"]+)[»”"]',question)
    candidates=[]
    specificity={}
    for key,spec in SCHEMAS[document_type]['fields'].items():
        terms=[spec['label'],*spec['aliases'],*aliases.get(key,[])]
        if quoted:
            hit=any(normalize(quoted[1])==normalize(t) for t in terms)
        else:
            matched=[t for t in terms if len(t)>2 and re.search(r'(?<!\w)'+re.escape(normalize(t))+r'(?!\w)',q)]
            hit=bool(matched)
            specificity[key]=max(map(len,matched),default=0)
        if hit: candidates.append(key)
    if not quoted and candidates:
        best=max(specificity[k] for k in candidates)
        candidates=[k for k in candidates if specificity[k]==best]
    if len(candidates)==1:
        key=candidates[0];value=values(fields)[key]
        if value=='не найдено':
            result['answer']=fields[key]['label']+': не найдено. Обратитесь в деканат.'
        else:
            value=('есть' if value else 'нет') if isinstance(value,bool) else value
            result.update(answerable=True,value=value,answer=fields[key]['label']+': '+value+'.',sources=['field:'+key])
    return result


def ui_answer(question, fields, document_type, rules=RULES):
    a=structured_answer(question,fields,document_type,rules)
    v=validation(fields,document_type,rules)
    required={k:c['id'] for c in rules['clauses'] if c['document_type']==document_type for k in c.get('required_fields',[])}
    status='insufficient_data'
    if a['answerable']:
        status={'document_ok':'complete','missing_fields':'missing_data'}.get(a['value'],'document_answer' if any(s.startswith('field:') for s in a['sources']) else 'rule_answer')
    return {'status':status,'text':a['answer'],'citations':[{'id':c['id'],'text':c['text'],'title':rules['title'],'version':rules['version'],'source_file':c.get('source_file')} for c in rules['clauses'] if 'rule:'+c['id'] in a['sources']],
            'field_sources':[s[6:] for s in a['sources'] if s.startswith('field:')],
            'checks':[{'field':k,'label':fields[k]['label'],'status':'missing' if k in v['missing_fields'] else 'pass','clause_id':cid} for k,cid in required.items()],
            'next_steps':[] if a['answerable'] else ['Обратитесь в деканат.'],
            'rules_version':rules['version'],'rules_sha256':fingerprint(rules),'demo_rules':False,'retrieval':[], 'structured':a}


def submission_document(document_id, document_type, fields, questions, rules=RULES):
    return {'document_id':document_id,'document_type':document_type,'fields':values(fields),'validation':validation(fields,document_type,rules),
            'answers':[{'question_id':q['question_id'],**structured_answer(q['question'],fields,document_type,rules)} for q in questions]}
