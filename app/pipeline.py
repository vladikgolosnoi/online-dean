import hashlib
import copy
import time
from .config import SCHEMAS, RULES
from .ocr import run_ocr
from .extraction import classify_detail, extract
from .vision import apply_visual
from .reasoning import answer
from .knowledge import fingerprint
from .official import RULES as OFFICIAL_RULES, SCHEMAS as OFFICIAL_SCHEMAS, extract_official


def template_fit(classification, fields, selected, schemas):
    """Explain structural fit; deliberately does not assert document authenticity."""
    if not selected:
        return {'status': 'unknown', 'title': 'Структура не определена', 'detail': 'Выберите тип документа для проверки структуры.'}
    total = len(schemas[selected]['fields'])
    recognized = sum(field.get('status') in {'found', 'confirmed'} for field in fields.values())
    detected = classification.get('type')
    if detected and detected != selected:
        return {'status': 'attention', 'title': 'Проверьте выбранный тип', 'detail': 'Заголовок снимка похож на другой тип документа.'}
    if recognized / max(total, 1) >= .8:
        return {'status': 'matched', 'title': 'Структура документа распознана', 'detail': f'Найдены заголовок и {recognized} из {total} ожидаемых реквизитов.'}
    return {'status': 'attention', 'title': 'Нестандартная структура', 'detail': f'Найдены только {recognized} из {total} ожидаемых реквизитов; сверьте оригинал.'}


def analyze(data, question, document_type='auto', filename='document', rules=None):
    rules = copy.deepcopy(rules or OFFICIAL_RULES)
    # `demo` describes publication status, not the schema family.  Imported
    # regulations also have demo=False, but must keep using the generic
    # configurable schemas instead of Meridian's fixed competition contract.
    official = rules.get("profile") == "meridian-v1"
    schemas = OFFICIAL_SCHEMAS if official else SCHEMAS
    started = time.perf_counter()
    ocr = run_ocr(data)
    classification = classify_detail(ocr['lines'], schemas)
    detected = classification['type']
    selected = detected if document_type == 'auto' else document_type
    if selected is not None and selected not in schemas:
        raise ValueError('Неизвестный тип документа.')
    fields = (extract_official(ocr, selected) if official else extract(ocr['lines'], selected)) if selected else {}
    if not official:
        apply_visual(fields, ocr['pages'])
    response = answer(question, fields, selected, rules) if selected else {
        'status': 'unknown_type', 'text': 'Не удалось уверенно определить тип документа. Выберите тип вручную и повторите проверку.',
        'citations': [], 'field_sources': [], 'checks': [], 'next_steps': ['Выберите тип документа.'], 'demo_rules': rules['demo'], 'rules_sha256': fingerprint(rules)}
    return {'schema_version': 'dean-2', 'filename': filename, 'sha256': hashlib.sha256(data).hexdigest(), 'classification': classification,
            'question': question, 'document_type': selected, 'detected_type': detected,
            'type_label': schemas[selected]['label'] if selected else 'Тип не определён',
            'template_fit': template_fit(classification, fields, selected, schemas),
            'fields': fields, 'ocr': ocr, 'answer': response, 'audit': [],
            'rules': {k: rules[k] for k in ['title', 'version', 'demo', 'notice']}, 'knowledge_snapshot': rules,
            'timing_ms': round((time.perf_counter() - started) * 1000)}
