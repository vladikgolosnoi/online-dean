"""Layout-aware extraction; every candidate preserves its OCR evidence."""
import re
from datetime import datetime
from difflib import SequenceMatcher
from .config import SCHEMAS

MONTHS = dict(zip('января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split(), range(1,13)))
DATE = r'(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{4}|[«"]?\d{1,2}[»"]?\s+(?:' + '|'.join(MONTHS) + r')\s+\d{4})'
NAME = r'[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+'


def normalize(text):
    return re.sub(r'\s+', ' ', text.casefold().replace('ё', 'е')).strip()


def parse_date(value):
    match = re.search(DATE, value, re.I)
    if not match:
        return None
    raw = match.group().casefold()
    try:
        words = re.search(r'(\d{1,2})[»"]?\s+([а-я]+)\s+(\d{4})', raw)
        if words:
            date = datetime(int(words[3]), MONTHS[words[2]], int(words[1]))
        elif re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):
            date = datetime.strptime(raw, '%Y-%m-%d')
        else:
            date = datetime.strptime(re.sub(r'[/-]', '.', raw), '%d.%m.%Y')
        return date.strftime('%d.%m.%Y')
    except (ValueError, KeyError):
        return None


def classify_detail(lines, schemas=None):
    text = normalize(' '.join(line['text'] for line in lines))
    scores, matched = {}, {}
    for key, schema in (schemas or SCHEMAS).items():
        markers = [m for m in schema['markers'] if normalize(m) in text]
        score = len(markers)
        if not markers:
            for line in lines[:8]:
                header = normalize(line['text'])
                for m in schema['markers']:
                    if .65 <= len(header) / max(len(m), 1) <= 1.5 and SequenceMatcher(None, header, normalize(m)).ratio() >= .89:
                        markers.append(line['text'])
                        score = .8
        scores[key], matched[key] = score, markers
    ranked = sorted(scores, key=scores.get, reverse=True)
    chosen = None
    if ranked and scores[ranked[0]] > 0 and (len(ranked) == 1 or scores[ranked[0]] > scores[ranked[1]]):
        chosen = ranked[0]
    return {'type': chosen, 'scores': scores, 'markers': matched.get(chosen, []), 'method': 'header_and_markers'}


def classify(lines):
    return classify_detail(lines)['type']


def evidence_for(line, start=0, end=None):
    end = len(line['text']) if end is None else end
    evidence = {k: line[k] for k in ['text', 'page', 'bbox', 'confidence']}
    words = [w for w in line.get('words', []) if w['end'] > start and w['start'] < end]
    if words:
        evidence['bbox'] = [min(w['bbox'][0] for w in words), min(w['bbox'][1] for w in words), max(w['bbox'][2] for w in words), max(w['bbox'][3] for w in words)]
        evidence['confidence'] = min(w['confidence'] for w in words)
        evidence['text'] = line['text'][start:end].strip()
    return evidence


def validate_value(raw, kind):
    value, valid = raw, True
    if kind == 'date':
        value = parse_date(raw)
        valid = value is not None
    elif kind == 'period':
        parsed = [parse_date(d) for d in re.findall(DATE, raw, re.I)]
        valid = len(parsed) == 2 and all(parsed)
        if valid:
            value = ' — '.join(parsed)
            valid = datetime.strptime(parsed[0], '%d.%m.%Y') <= datetime.strptime(parsed[1], '%d.%m.%Y')
    elif kind == 'number':
        match = re.fullmatch(r'\s*(\d{1,2})(?:\s*курс)?\s*', raw, re.I)
        valid = bool(match)
        value = match[1] if match else raw
    return value if value is not None else raw, bool(valid)


def extract(lines, document_type, schemas=None):
    specs = (schemas or SCHEMAS)[document_type]['fields']
    ordered = sorted(lines, key=lambda line: (line['page'], line['bbox'][1], line['bbox'][0]))
    labels = sorted({a for s in specs.values() for a in s['aliases']}, key=len, reverse=True)
    label_re = re.compile(r'(?<![\w])(' + '|'.join(re.escape(a).replace(r'\ ', r'\s+') for a in labels) + r')\s*(?:[:：]|(?=\s|$))', re.I)
    fields = {}
    for key, spec in specs.items():
        field = {'key': key, 'label': spec['label'], 'kind': spec['kind'], 'value': None, 'status': 'not_found', 'confidence': None, 'evidence': [], 'source': 'ocr'}
        aliases = {normalize(a) for a in spec['aliases']}
        if spec['kind'] == 'visual':
            field.update(status='needs_review', source='visual_review_required')
            field['evidence'] = [evidence_for(line) for line in ordered if any(normalize(a) in normalize(line['text']) for a in spec['aliases'])][:2]
            fields[key] = field
            continue
        candidates = []
        for index, line in enumerate(ordered):
            matches = [m for m in label_re.finditer(line['text'])
                       if not line['text'][:m.start()].strip() or ':' in m[0] or '：' in m[0]]
            labeled = False
            for position, match in enumerate(matches):
                if normalize(match[1]) not in aliases:
                    continue
                labeled = True
                prefix = line['text'][:match.start()].strip(' ;|,')
                if prefix and ':' not in match[0] and position == 0:
                    continue
                end = matches[position + 1].start() if position + 1 < len(matches) else len(line['text'])
                raw = line['text'][match.end():end].strip(' :;_|—–')
                if raw and not re.fullmatch(r'[_\s.\-]+', raw):
                    candidates.append((raw, evidence_for(line, match.end(), end), 'label'))
                else:
                    for following in ordered[index + 1:index + 4]:
                        if following['page'] != line['page']:
                            break
                        x1, y1, x2, y2 = line['bbox']
                        fx, fy, _, _ = following['bbox']
                        if 0 <= fy - y2 <= max(55, (y2-y1)*2.2) and abs(fx-x1) <= max(100, x2-x1):
                            if not label_re.search(following['text']):
                                candidates.append((following['text'].strip(), evidence_for(following), 'adjacent_line'))
                            break
            for pattern in spec.get('patterns', []):
                if labeled:
                    continue
                pattern = pattern.replace('{DATE}', DATE).replace('{NAME}', NAME)
                for match in re.finditer(pattern, line['text'], re.I):
                    raw = match.group('value').strip(' :;_|—–')
                    if raw:
                        candidates.append((raw, evidence_for(line, *match.span('value')), 'pattern'))
        values = []
        for raw, evidence, method in candidates:
            if normalize(raw) in {'не найдено', 'нет', 'отсутствует', '-', 'не указано'} or not re.search(r'\w', raw):
                continue
            if key in {'student_name', 'supervisor', 'supervisor_name'}:
                match = re.match(NAME, raw)
                if match:
                    raw = match.group()
                elif any(t in normalize(raw) for t in ['от ', 'дата', 'справка']):
                    continue
            if key == 'document_number':
                raw = re.split(r'\s+от\s+', raw, maxsplit=1, flags=re.I)[0].strip(' №')
            value, valid = validate_value(raw, spec['kind'])
            values.append((value, evidence, valid, method))
        if values:
            value, evidence, valid, method = max(values, key=lambda v: (v[2], v[1]['confidence']))
            distinct = {normalize(v[0]) for v in values}
            unique = []
            for _, e, _, _ in values:
                if e not in unique:
                    unique.append(e)
            field.update(value=value, confidence=round(evidence['confidence'], 1), evidence=unique, extraction_method=method)
            field['status'] = 'conflict' if len(distinct)>1 else ('found' if valid and evidence['confidence']>=60 else 'needs_review')
        fields[key] = field
    return fields
