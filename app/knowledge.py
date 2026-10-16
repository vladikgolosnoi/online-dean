"""Local lexical RAG with Russian normalization and immutable source hashes."""
import hashlib
import json
import math
import re
from collections import Counter
from .extraction import normalize

STOP = set('и в во на по к с со от до из за для при о об а но или это как что какой какая какие каких ли мне я у вы он она они его ее их же бы был быть если то'.split())


def tokens(text):
    words = re.findall(r'[а-яa-z0-9]+', normalize(text))
    # Small conservative suffix normalizer. No language model or online embeddings.
    return [re.sub(r'(иями|ями|ами|ого|ему|ому|ыми|ими|ость|ение|ения|ений|ать|ить|ять|ов|ев|ам|ям|ах|ях|ий|ый|ой|ая|яя|ое|ее|ые|ие|у|ю|а|я|ы|и|е|о)$', '', w) if len(w)>4 else w for w in words if w not in STOP and len(w)>1]


def fingerprint(rules):
    canonical = json.dumps(rules, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()


def retrieve(question, rules, document_type, limit=3):
    clauses = [c for c in rules['clauses'] if c.get('document_type') in {document_type, '*'}]
    if not clauses:
        return []
    query = set(tokens(question))
    docs = [tokens(c['text'] + ' ' + ' '.join(c.get('keywords', []))) for c in clauses]
    n, avg = len(docs), sum(map(len, docs)) / len(docs)
    df = Counter(t for doc in docs for t in set(doc))
    ranked = []
    q = normalize(question)
    for clause, doc in zip(clauses, docs):
        tf = Counter(doc)
        matched = sorted(query & tf.keys())
        score = 0.0
        for word in matched:
            idf = math.log(1 + (n - df[word] + .5) / (df[word] + .5))
            score += idf * tf[word] * 2.5 / (tf[word] + 1.5 * (.25 + .75 * len(doc) / max(avg, 1)))
        topics = [t for t in clause.get('topics', []) if t in q]
        if re.search(r'(?<![\d.])' + re.escape(clause['id']) + r'(?![\d.])', q):
            topics.append('explicit_clause_id')
            score += 10
        score += len(topics) * .7
        if matched or topics:
            ranked.append({'clause': clause, 'score': round(score, 4), 'matched_terms': matched, 'topic_matches': topics,
                           'coverage': len(matched) / max(len(query), 1)})
    return sorted(ranked, key=lambda r: (-r['score'], r['clause']['id']))[:limit]


def parse_regulation(text, filename):
    if len(text) > 150_000:
        raise ValueError('Положение длиннее 150 000 символов. Разделите его на части.')
    headers = list(re.finditer(r'(?m)^\s*(\d{1,3}(?:\.\d{1,3}){1,4})\.?\s+(.+)', text))
    if not headers:
        raise ValueError('Не найдены нумерованные пункты вида 1.1 Текст. Загрузите TXT/MD/JSON с пунктами.')
    clauses, ids = [], set()
    for i, match in enumerate(headers):
        key = match[1]
        if key in ids:
            raise ValueError('Повторяется номер пункта ' + key + '. Уточните нумерацию документа.')
        ids.add(key)
        end = headers[i+1].start() if i+1 < len(headers) else len(text)
        body = text[match.start():end].strip()
        clauses.append({'id': key, 'text': body, 'document_type': '*', 'topics': [], 'required_fields': [], 'source_file': filename})
    return {'title': filename, 'version': 'import-' + hashlib.sha256(text.encode()).hexdigest()[:12], 'demo': False,
            'notice': 'Загруженный источник. Ответы цитируют пункты; машинные условия для проверки комплектности не заданы.',
            'clauses': clauses}


def validate_rules(rules, schemas):
    if not isinstance(rules, dict):
        raise ValueError('База правил должна быть JSON-объектом.')
    if not isinstance(rules.get('title'), str) or not isinstance(rules.get('version'), str) or type(rules.get('demo')) is not bool:
        raise ValueError('Нужны title, version и логическое поле demo.')
    if not isinstance(rules.get('clauses'), list) or not 1 <= len(rules['clauses']) <= 500:
        raise ValueError('База должна содержать от 1 до 500 пунктов.')
    ids = set()
    for c in rules['clauses']:
        if not isinstance(c, dict) or not isinstance(c.get('id'), str) or not isinstance(c.get('text'), str) or not c['text'].strip():
            raise ValueError('Каждый пункт должен содержать id и непустой text.')
        if c['id'] in ids:
            raise ValueError('Повторный номер пункта: ' + c['id'])
        ids.add(c['id'])
        kind = c.get('document_type', '*')
        if kind != '*' and kind not in schemas:
            raise ValueError('Неизвестный тип документа: ' + str(kind))
        c['document_type'] = kind
        fields = schemas[kind]['fields'] if kind != '*' else {}
        required = c.get('required_fields', [])
        if not isinstance(required, list) or any(k not in fields for k in required):
            raise ValueError('Неизвестные обязательные поля в пункте ' + c['id'])
        for name in ('topics', 'keywords'):
            if not isinstance(c.get(name, []), list) or any(not isinstance(v, str) for v in c.get(name, [])):
                raise ValueError(name + ' должен быть списком строк.')
        if 'date_order' in c and (not isinstance(c['date_order'], list) or len(c['date_order']) != 2 or any(k not in fields or fields[k]['kind'] != 'date' for k in c['date_order'])):
            raise ValueError('date_order должен ссылаться на два поля дат.')
    rules.setdefault('notice', 'Пользовательская база правил.')
    return rules
