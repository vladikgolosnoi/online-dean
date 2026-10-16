"""Evidence-only answers backed by versioned declarative rules, no remote model."""
import re
from datetime import datetime
from .config import RULES
from .extraction import normalize
from .knowledge import retrieve, fingerprint

CHECK_INTENT = ['хват', 'достаточ', 'подход', 'провер', 'поряд', 'комплект', 'зачт', 'приня', 'перевест', 'перевод', 'оформ', 'можно', 'полнот', 'треб', 'нужн']
SPECIFIC_TOPICS = [(['стоим', 'оплат', 'сколько стоит', 'цена', 'цену', 'платн'], ['стоим', 'оплат', 'рубл', 'цена', 'платн']),
                   (['стипенд'], ['стипенд']), (['общежит'], ['общежит']), (['бюджет'], ['бюджет']),
                   (['расписан'], ['расписан']), (['телефон'], ['телефон']), (['адрес'], ['адрес'])]


def evaluate(fields, document_type, rules=None):
    rules = rules or RULES
    checks = []
    for clause in rules['clauses']:
        if clause['document_type'] != document_type:
            continue
        for key in clause.get('required_fields', []):
            f = fields[key]
            status = 'pass' if f['status'] in {'found', 'confirmed'} and f['value'] is not False else 'review'
            if f['status'] == 'not_found' or f['value'] is False:
                status = 'missing'
            checks.append({'field': key, 'label': f['label'], 'status': status, 'clause_id': clause['id']})
        if 'date_order' in clause:
            a, b = clause['date_order']
            if fields[a]['status'] in {'found', 'confirmed'} and fields[b]['status'] in {'found', 'confirmed'}:
                try:
                    ok = datetime.strptime(fields[a]['value'], '%d.%m.%Y') <= datetime.strptime(fields[b]['value'], '%d.%m.%Y')
                    checks.append({'field': b, 'label': 'Порядок дат', 'status': 'pass' if ok else 'invalid', 'clause_id': clause['id']})
                except (ValueError, TypeError):
                    checks.append({'field': b, 'label': 'Порядок дат', 'status': 'review', 'clause_id': clause['id']})
    return checks


def answer(question, fields, document_type, rules=None):
    rules = rules or RULES
    if rules.get("profile") == "meridian-v1":
        from .official import ui_answer
        return ui_answer(question, fields, document_type, rules)
    q = normalize(question)
    checks = evaluate(fields, document_type, rules)
    result = {'status': 'insufficient_data', 'text': 'В документе и в подключённом Положении нет достаточных данных для ответа. Обратитесь в деканат.',
              'citations': [], 'field_sources': [], 'checks': checks, 'next_steps': ['Уточните вопрос у сотрудника деканата.'],
              'rules_version': rules['version'], 'rules_sha256': fingerprint(rules), 'demo_rules': rules['demo'], 'retrieval': []}
    # Out-of-scope questions must not receive a generic completeness answer.
    if any(t in q for t in ['игнорируй', 'забудь правила', 'выдумай']):
        return result
    wants_check = any(t in q for t in CHECK_INTENT)
    field_hits = []
    if not wants_check:
        for key, f in fields.items():
            label_words = [w for w in re.findall(r'[а-яa-z]+', normalize(f['label'])) if len(w) > 3]
            if normalize(f['label']) in q or (label_words and all(w[:5] in q for w in label_words)):
                field_hits.append(key)
        # Common natural questions, without teaching field names to the user.
        aliases = {'issue_date': ['когда выдан', 'дата выдачи'],
                   'document_number': ['номер справки', 'номер документ'], 'stamp': ['печать', 'печати'], 'signature': ['подпись', 'подписи'],
                   'grade': ['оценка', 'оценку', 'оценкой'], 'supervisor': ['кто руководитель', 'руководитель практики'],
                   'student_name': ['фио', 'кого выдан', 'кому выдан', 'имя студента', 'как зовут'],
                   'group': ['какой группе', 'какая группа'], 'course': ['на каком курсе', 'какой курс'],
                   'organization': ['где проходил', 'где проходила', 'какая организация'],
                   'study_mode': ['форма обучения', 'форме обучения']}
        field_hits += [k for k, terms in aliases.items() if k in fields and any(t in q for t in terms)]
        field_hits = list(dict.fromkeys(field_hits))
    if field_hits:
        parts = []
        for key in field_hits:
            f = fields[key]
            if f['status'] in {'found', 'confirmed'}:
                value = ('есть' if f['value'] else 'нет') if isinstance(f['value'], bool) else f['value']
                parts.append(f"{f['label']}: {value}.")
            else:
                parts.append(f"{f['label']}: {'не найдено' if f['status'] == 'not_found' else 'нужна проверка по изображению'}.")
        result.update(status='document_answer', text=' '.join(parts), field_sources=field_hits, next_steps=[])
        return result
    ranked = retrieve(question, rules, document_type)
    for triggers, required in SPECIFIC_TOPICS:
        if any(t in q for t in triggers):
            ranked = [r for r in ranked if any(t in normalize(r['clause']['text']) for t in required)]
    result['retrieval'] = [{'clause_id': r['clause']['id'], 'score': r['score'], 'matched_terms': r['matched_terms'], 'coverage': r['coverage']} for r in ranked]
    clauses = [r['clause'] for r in ranked if r['topic_matches'] or (len(r['matched_terms']) >= 2 and r['coverage'] >= .5)]
    if not clauses:
        return result
    citations = [{'id': c['id'], 'text': c['text'], 'title': rules['title'], 'source_file': c.get('source_file'), 'version': rules['version']} for c in clauses]
    asks_policy = any(t in q for t in ['какие поля', 'какие документы', 'требования', 'обязательно', 'нужна ли', 'нужен ли', 'какие сведения', 'что требует'])
    if asks_policy or not wants_check or not any(c.get('required_fields') for c in clauses):
        result.update(status='rule_answer', text='В подключённом источнике найдены следующие положения. Они приведены дословно ниже; окончательное решение по документу принимает сотрудник деканата.', citations=citations, next_steps=[])
        return result
    # Retrieval ranks quotations, but must never truncate a completeness audit.
    # Include every declarative requirement of this document type before saying complete.
    selected_ids = {c['id'] for c in clauses}
    clauses += [c for c in rules['clauses'] if c['document_type'] == document_type
                and (c.get('required_fields') or c.get('date_order')) and c['id'] not in selected_ids]
    citations = [{'id': c['id'], 'text': c['text'], 'title': rules['title'], 'source_file': c.get('source_file'), 'version': rules['version']} for c in clauses]
    applicable = [c for c in checks if c['clause_id'] in {r['id'] for r in clauses}]
    if not applicable:
        return result
    missing = list(dict.fromkeys(c['label'] for c in applicable if c['status'] == 'missing'))
    review = list(dict.fromkeys(c['label'] for c in applicable if c['status'] == 'review'))
    invalid = list(dict.fromkeys(c['label'] for c in applicable if c['status'] == 'invalid'))
    parts, actions = [], []
    if missing:
        parts.append('Не найдены обязательные данные: ' + ', '.join(missing) + '.')
        actions.append('Проверьте оригинал и предоставьте недостающие данные: ' + ', '.join(missing) + '.')
    if review:
        parts.append('Нужна ручная проверка: ' + ', '.join(review) + '.')
        actions.append('Подтвердите сомнительные поля по изображению документа.')
    if invalid:
        parts.append('Обнаружено противоречие: дата окончания раньше даты начала.')
        actions.append('Уточните даты в заявлении.')
    status = 'missing_data' if missing or invalid else ('needs_review' if review else 'complete')
    if status == 'complete':
        parts.append('Все обязательные поля по подключённому Положению заполнены.')
        actions.append('Передайте документ сотруднику деканата для окончательного решения.')
    parts.append('Основание: ' + ', '.join('п. ' + c['id'] for c in clauses) + '.')
    if 'перев' in q:
        parts.append('Комплектность справки не подтверждает возможность перевода на конкретный курс.')
    parts.append('Окончательное решение принимает сотрудник деканата.')
    result.update(status=status, text=' '.join(parts), citations=citations,
                  next_steps=actions, field_sources=list(dict.fromkeys(c['field'] for c in applicable)))
    return result
