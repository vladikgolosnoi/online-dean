import copy
import asyncio
import json
import threading
import time
import uuid
import hashlib
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .config import ROOT
from .official import RULES, SCHEMAS, submission_document
from .extraction import parse_date, DATE
import re
from .ocr import health, run_ocr
from .knowledge import parse_regulation, validate_rules, fingerprint
from .pipeline import analyze
from .reasoning import answer
from .report import render_report
from .bundle import evidence_bundle
from .dossier import build as build_dossier
from .redaction import redact_analysis
from .workflow import route

sessions = {}
knowledge = {}
dossiers = {}
lock = threading.Lock()
workers = threading.BoundedSemaphore(2)
TTL = 1800
MAX_UPLOAD = 15 * 1024 * 1024
PUBLIC_DEMO = os.getenv('DEAN_PUBLIC_DEMO', '').strip().casefold() in {'1', 'true', 'yes'}


@asynccontextmanager
async def lifespan(app):
    validate_rules(copy.deepcopy(RULES), SCHEMAS)
    async def expire_sessions():
        while True:
            await asyncio.sleep(30)
            with lock:
                now = time.monotonic()
                for key in list(sessions):
                    if now - sessions[key][0] > TTL:
                        del sessions[key]
                for key in list(knowledge):
                    if now - knowledge[key][0] > TTL:
                        del knowledge[key]
                for key in list(dossiers):
                    if now - dossiers[key][0] > TTL:
                        del dossiers[key]
    cleanup = asyncio.create_task(expire_sessions())
    yield
    cleanup.cancel()
    try:
        await cleanup
    except asyncio.CancelledError:
        pass
    sessions.clear()
    knowledge.clear()
    dossiers.clear()


app = FastAPI(title='Онлайн-деканат | Проверка студенческих документов', version='3.0.0', lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver', '*.onrender.com'])
app.mount('/static', StaticFiles(directory=ROOT / 'web'), name='static')


@app.middleware('http')
async def private_responses(request, call_next):
    # The local product has no remote clients: reject cross-site mutations.
    origin = request.headers.get('origin')
    if request.method not in {'GET', 'HEAD', 'OPTIONS'} and origin:
        from urllib.parse import urlsplit
        source = urlsplit(origin)
        if source.scheme not in {'http', 'https'} or source.netloc != request.headers.get('host'):
            return JSONResponse({'detail': 'Запрос должен быть отправлен из локального интерфейса.'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    return response


@app.get('/')
def index():
    return FileResponse(ROOT / 'web' / 'index.html')


@app.get('/docs', include_in_schema=False)
def api_docs():
    return FileResponse(ROOT / 'web' / 'api.html')


@app.get('/api/health')
def status():
    return {'ocr': health(), 'offline': True, 'demo_rules': RULES['demo'], 'version': app.version}


@app.get('/api/ready')
def readiness():
    engine = health()
    return JSONResponse({'ready': engine['ready'], 'version': app.version, 'ocr': engine},
                        status_code=200 if engine['ready'] else 503)


@app.get('/api/config')
def config():
    return {'documents': {k: {'label': v['label']} for k, v in SCHEMAS.items()}, 'rules': RULES, 'public_demo': PUBLIC_DEMO}


def prune():
    now = time.monotonic()
    for key in list(sessions):
        if now - sessions[key][0] > TTL:
            del sessions[key]
    while len(sessions) >= 12:
        del sessions[min(sessions, key=lambda k: sessions[k][0])]
    for key in list(dossiers):
        if now - dossiers[key][0] > TTL:
            del dossiers[key]
    while len(dossiers) >= 8:
        del dossiers[min(dossiers, key=lambda k: dossiers[k][0])]


def process(data, question, document_type, filename, rules=None):
    if not workers.acquire(blocking=False):
        raise HTTPException(429, 'Сейчас обрабатываются два документа. Попробуйте чуть позже.')
    try:
        result = analyze(data, question, document_type, filename, rules)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    finally:
        workers.release()
    result['id'] = uuid.uuid4().hex
    result['created_at'] = datetime.now(timezone.utc).isoformat()
    result['workflow'] = route(result['document_type'], result['answer'], result['fields'])
    with lock:
        prune()
        sessions[result['id']] = (time.monotonic(), result)
    return result


@app.post('/api/analyze')
async def analyze_file(file: UploadFile = File(...), question: str = Form(..., min_length=3, max_length=2000),
                       document_type: str = Form('auto'), knowledge_id: str = Form('default')):
    if PUBLIC_DEMO:
        raise HTTPException(403, 'В публичной демонстрации доступны только подготовленные примеры без персональных данных.')
    if document_type != 'auto' and document_type not in SCHEMAS:
        raise HTTPException(422, 'Неизвестный тип документа.')
    data = await file.read(MAX_UPLOAD + 1)
    await file.close()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, 'Максимальный размер файла — 15 МБ.')
    if not data:
        raise HTTPException(422, 'Файл пуст.')
    rules = get_knowledge(knowledge_id)
    return await run_in_threadpool(process, data, question, document_type, file.filename or 'document', rules)


def get_knowledge(key):
    if key == 'default':
        return copy.deepcopy(RULES)
    with lock:
        if key not in knowledge or time.monotonic() - knowledge[key][0] > TTL:
            knowledge.pop(key, None)
            raise HTTPException(404, 'Сессия базы правил истекла. Загрузите Положение снова.')
        rules = knowledge[key][1]
        knowledge[key] = (time.monotonic(), rules)
        return copy.deepcopy(rules)


def import_knowledge(data, filename):
    if not workers.acquire(blocking=False):
        raise HTTPException(429, 'Обработчики заняты. Повторите загрузку позже.')
    try:
        if filename.casefold().endswith('.json'):
            rules = json.loads(data.decode('utf-8-sig'))
        else:
            text = run_ocr(data)['text'] if data.startswith(b'%PDF-') else data.decode('utf-8-sig')
            rules = parse_regulation(text, filename)
        rules = validate_rules(rules, SCHEMAS)
        rules['source_sha256'] = hashlib.sha256(data).hexdigest()
    except (ValueError, UnicodeError, KeyError, TypeError) as e:
        raise HTTPException(422, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    finally:
        workers.release()
    key = uuid.uuid4().hex
    with lock:
        while len(knowledge) >= 8:
            del knowledge[min(knowledge, key=lambda k: knowledge[k][0])]
        knowledge[key] = (time.monotonic(), rules)
    return {'id': key, 'rules': rules, 'sha256': fingerprint(rules),
            'mode': 'structured' if any(c.get('required_fields') for c in rules['clauses']) else 'extractive'}


@app.post('/api/knowledge')
async def upload_knowledge(file: UploadFile = File(...)):
    if PUBLIC_DEMO:
        raise HTTPException(403, 'Импорт Положения отключён в публичной демонстрации.')
    filename = file.filename or 'Положение.txt'
    if not filename.casefold().endswith(('.txt', '.md', '.json', '.pdf')):
        raise HTTPException(422, 'Положение: TXT, MD, JSON или PDF.')
    data = await file.read(MAX_UPLOAD + 1)
    await file.close()
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(413, 'Пустой файл или превышен лимит 15 МБ.')
    return await run_in_threadpool(import_knowledge, data, filename)


DEMOS = {
    'study': ('open-002.png', 'Содержит ли документ все обязательные сведения по Положению?'),
    'leave': ('open-011.png', 'Содержит ли документ все обязательные сведения по Положению?'),
    'internship': ('open-021.png', 'Содержит ли документ все обязательные сведения по Положению?'),
    'unknown': ('open-001.png', 'Какова стоимость обучения за следующий семестр?'),
}


@app.post('/api/demo/{name}')
async def demo(name: str, knowledge_id: str = 'default'):
    if name not in DEMOS:
        raise HTTPException(404, 'Пример не найден.')
    filename, question = DEMOS[name]
    path = ROOT / 'official' / 'participants-v1' / 'documents' / filename
    if not path.exists():
        raise HTTPException(503, 'Сначала выполните python -m scripts.generate_samples.')
    return await run_in_threadpool(process, path.read_bytes(), question, 'auto', filename, get_knowledge(knowledge_id))


def get_session(key):
    entry = sessions.get(key)
    if entry is None or time.monotonic() - entry[0] > TTL:
        sessions.pop(key, None)
        raise HTTPException(404, 'Сессия истекла. Загрузите документ повторно.')
    sessions[key] = (time.monotonic(), entry[1])
    return entry[1]


def session_summary(result):
    """Return an employee-queue card without OCR text, images or field values."""
    fields = list(result.get('fields', {}).values())
    confirmed = sum(field.get('status') in {'found', 'confirmed'} and field.get('value') is not False
                    for field in fields)
    decision = result.get('employee_decision')
    return {
        'id': result['id'],
        'filename': result.get('filename', 'Документ'),
        'type_label': result.get('type_label', 'Тип не определён'),
        'document_type': result.get('document_type'),
        'created_at': result.get('created_at'),
        'workflow': result.get('workflow', {}),
        'answer_status': result.get('answer', {}).get('status'),
        'fields_ready': confirmed,
        'fields_total': len(fields),
        'manual_changes': len(result.get('audit', [])),
        # The queue does not expose the employee's free-text rationale. It is
        # available only after opening the existing session card.
        'employee_decision': ({key: decision[key] for key in ('action', 'title', 'at')}
                              if decision else None),
    }


def comparison_value(field):
    value = field.get('value')
    if field.get('kind') == 'visual':
        return 'есть' if value is True else ('нет' if value is False else 'нужна проверка')
    return value if value not in (None, '') else 'не найдено'


def field_is_ready(field):
    return field.get('status') in {'found', 'confirmed'} and field.get('value') not in (None, False, '')


def compare_sessions(before, after):
    if before.get('document_type') != after.get('document_type'):
        return {'comparable': False, 'reason': 'Типы документов отличаются; сравнение полей недоступно.', 'changes': []}
    changes = []
    for key, old in before.get('fields', {}).items():
        new = after.get('fields', {}).get(key)
        if new is None:
            continue
        old_value, new_value = comparison_value(old), comparison_value(new)
        old_ready, new_ready = field_is_ready(old), field_is_ready(new)
        if not old_ready and new_ready:
            state = 'fixed'
        elif old_ready and not new_ready:
            state = 'regressed'
        elif old_value != new_value:
            state = 'changed'
        else:
            continue
        changes.append({'field': key, 'label': new.get('label', key), 'before': old_value, 'after': new_value, 'state': state})
    counts = {state: sum(item['state'] == state for item in changes) for state in ('fixed', 'regressed', 'changed')}
    return {'comparable': True, 'changes': changes, 'counts': counts,
            'before': {'id': before['id'], 'filename': before.get('filename', 'Предыдущая версия')},
            'after': {'id': after['id'], 'filename': after.get('filename', 'Исправленная версия')}}


@app.get('/api/queue')
def queue():
    """Active work queue for the employee cabinet in the current short-lived session."""
    with lock:
        prune()
        items = [session_summary(entry[1]) for entry in sessions.values()]
    order = {'needs_completion': 0, 'needs_review': 1, 'unclassified': 2, 'ready_for_decision': 3}
    items.sort(key=lambda item: (order.get(item['workflow'].get('status'), 9), item.get('created_at') or ''), reverse=False)
    return {'items': items, 'ttl_minutes': TTL // 60, 'persistent': False}


@app.get('/api/session/{key}')
def session_view(key: str):
    """Open an existing item from the local employee queue."""
    with lock:
        return copy.deepcopy(get_session(key))


@app.get('/api/compare/{before_key}/{after_key}')
def compare_session_versions(before_key: str, after_key: str):
    """Compare two short-lived document versions without OCR or image payloads."""
    with lock:
        before = copy.deepcopy(get_session(before_key))
        after = copy.deepcopy(get_session(after_key))
    return compare_sessions(before, after)


class Review(BaseModel):
    question: str | None = Field(default=None, min_length=3, max_length=2000)
    corrections: dict[str, str | bool | None] = Field(default_factory=dict, max_length=40)


class EmployeeDecision(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    note: str = Field(min_length=3, max_length=500)


class DossierCreate(BaseModel):
    name: str = Field(default='Досье студента', min_length=1, max_length=120)
    document_ids: list[str] = Field(min_length=1, max_length=8)


class DossierResolution(BaseModel):
    check_id: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=500)


@app.post('/api/review/{key}')
def review(key: str, body: Review):
    with lock:
        result = copy.deepcopy(get_session(key))
        for field_key, value in body.corrections.items():
            if field_key not in result['fields']:
                raise HTTPException(422, 'Неизвестное поле: ' + field_key)
            f = result['fields'][field_key]
            if f['kind'] == 'visual' and value is not None and not isinstance(value, bool):
                raise HTTPException(422, 'Подпись и печать: true, false или null.')
            if f['kind'] != 'visual' and isinstance(value, bool):
                raise HTTPException(422, 'Текстовое поле не может иметь логическое значение.')
            if isinstance(value, str):
                value = value.strip()
                if len(value) > 1000:
                    raise HTTPException(422, 'Значение слишком длинное.')
                if f['kind'] == 'date' and value:
                    normalized = parse_date(value)
                    if normalized is None:
                        raise HTTPException(422, 'Введите корректную дату ДД.ММ.ГГГГ.')
                    value = datetime.strptime(normalized, "%d.%m.%Y").strftime("%Y-%m-%d") if result.get("knowledge_snapshot", {}).get("profile") == "meridian-v1" else normalized
                if f['kind'] == 'number' and value and not re.fullmatch(r'\d{1,2}', value):
                    raise HTTPException(422, 'Введите число от 0 до 99.')
                if f['kind'] == 'period' and value:
                    dates = [parse_date(d) for d in re.findall(DATE, value)]
                    if len(dates) != 2 or not all(dates) or datetime.strptime(dates[0], '%d.%m.%Y') > datetime.strptime(dates[1], '%d.%m.%Y'):
                        raise HTTPException(422, 'Введите период ДД.ММ.ГГГГ — ДД.ММ.ГГГГ с корректным порядком дат.')
                    value = ' — '.join(dates)
                value = value or None
            result['audit'].append({'field': field_key, 'before': f['value'], 'after': value,
                                    'source': 'manual_review', 'at': datetime.now(timezone.utc).isoformat()})
            f.update(value=value, status='confirmed' if value is not None else ('needs_review' if f['kind'] == 'visual' else 'not_found'), source='manual_review', confidence=None)
        if body.question is not None:
            result['question'] = body.question
        if result['document_type']:
            result['answer'] = answer(result['question'], result['fields'], result['document_type'], result.get('knowledge_snapshot', RULES))
            result['workflow'] = route(result['document_type'], result['answer'], result['fields'])
        sessions[key] = (time.monotonic(), result)
        return result


@app.post('/api/decision/{key}')
def employee_decision(key: str, body: EmployeeDecision):
    """Record a human routing decision; this endpoint never accepts a document."""
    decisions = {
        'return_for_completion': 'Вернуть на доработку',
        'send_to_review': 'Направить на дальнейшее рассмотрение',
    }
    if body.action not in decisions:
        raise HTTPException(422, 'Неизвестное решение сотрудника.')
    note = body.note.strip()
    if len(note) < 3:
        raise HTTPException(422, 'Укажите основание решения не короче трёх символов.')
    with lock:
        result = copy.deepcopy(get_session(key))
        workflow = result.get('workflow', {})
        if body.action == 'send_to_review' and workflow.get('status') != 'ready_for_decision':
            raise HTTPException(422, 'Направить на дальнейшее рассмотрение можно после устранения замечаний.')
        decision = {
            'action': body.action,
            'title': decisions[body.action],
            'note': note,
            'at': datetime.now(timezone.utc).isoformat(),
        }
        result['employee_decision'] = decision
        result.setdefault('employee_decision_history', []).append(decision)
        sessions[key] = (time.monotonic(), result)
        return result


@app.get('/api/export/{key}')
def export(key: str):
    with lock:
        result = copy.deepcopy(get_session(key))
    for page in result['ocr']['pages']:
        page.pop('image', None)
    return Response(json.dumps(result, ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="analysis.json"'})


@app.get('/api/export/{key}/redacted')
def export_redacted(key: str):
    with lock:
        result = copy.deepcopy(get_session(key))
    return Response(json.dumps(redact_analysis(result), ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="analysis-redacted.json"'})


@app.get('/api/report/{key}')
def report(key: str):
    with lock:
        result = copy.deepcopy(get_session(key))
    return Response(render_report(result), media_type='text/html', headers={'Content-Disposition': 'attachment; filename="document-report.html"'})


def appeal_draft(result):
    """Create a conservative student-facing draft from an already checked document."""
    workflow = result.get('workflow', {})
    fields = result.get('fields', {})
    student = fields.get('student_name', {}).get('value') or 'студент'
    document = result.get('type_label') or 'документ'
    checks = result.get('answer', {}).get('checks', [])
    issues = [item.get('label', 'обязательное сведение') for item in checks if item.get('status') != 'pass']
    ready = workflow.get('status') == 'ready_for_decision'
    if ready:
        subject = f'Предварительная подача: {document}'
        body = (
            'В деканат\n\n'
            f'От: {student}\n\n'
            f'Тема: {subject}\n\n'
            f'Прошу принять к предварительному рассмотрению приложенный документ: «{document}». '
            'Документ проверен сервисом на наличие обязательных сведений по подключённому Положению.\n\n'
            'Приложение: проверенный документ.\n\n'
            'Дата: ____________    Подпись: ____________'
        )
        return {'ready': True, 'title': 'Черновик обращения готов', 'subject': subject, 'body': body,
                'note': 'Проверьте адресата, дату и текст перед отправкой. Сервис не отправляет обращение и не принимает документ автоматически.',
                'issues': []}
    subject = f'Подготовка документа: {document}'
    items = '; '.join(issues) if issues else 'результат предварительной проверки'
    body = (
        f'Документ: {document}\n\n'
        'Перед обращением в деканат требуется доработать документ.\n'
        f'На предварительной проверке отмечено: {items}.\n\n'
        'После исправления загрузите новую версию и сравните результаты.'
    )
    return {'ready': False, 'title': 'Сначала подготовьте документ', 'subject': subject, 'body': body,
            'note': 'Черновик обращения будет доступен после устранения замечаний или ручной сверки.', 'issues': issues}


@app.get('/api/appeal/{key}')
def appeal(key: str):
    with lock:
        result = copy.deepcopy(get_session(key))
    return appeal_draft(result)


@app.get('/api/appeal/{key}/download')
def download_appeal(key: str):
    with lock:
        result = copy.deepcopy(get_session(key))
    draft = appeal_draft(result)
    return Response(draft['body'], media_type='text/plain; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="appeal-draft.txt"'})


@app.delete('/api/session/{key}')
def delete_session(key: str):
    with lock:
        sessions.pop(key, None)
    return {'deleted': True}


def dossier_view(key):
    entry = dossiers.get(key)
    if entry is None or time.monotonic() - entry[0] > TTL:
        dossiers.pop(key, None)
        raise HTTPException(404, 'Досье истекло. Создайте его снова.')
    dossier = entry[1]
    documents = [copy.deepcopy(get_session(document_id)) for document_id in dossier['document_ids']]
    dossier['updated_at'] = datetime.now(timezone.utc).isoformat()
    dossiers[key] = (time.monotonic(), dossier)
    return {'id': key, 'name': dossier['name'], 'created_at': dossier['created_at'], 'updated_at': dossier['updated_at'],
            **build_dossier(documents, dossier['resolutions'])}


@app.post('/api/dossiers')
def create_dossier(body: DossierCreate):
    document_ids = list(dict.fromkeys(body.document_ids))
    with lock:
        documents = [copy.deepcopy(get_session(document_id)) for document_id in document_ids]
        if any(not document.get('document_type') for document in documents):
            raise HTTPException(422, 'Добавьте только документы с определённым типом.')
        prune()
        key = uuid.uuid4().hex
        dossier = {'name': body.name.strip(), 'document_ids': document_ids, 'resolutions': {},
                   'created_at': datetime.now(timezone.utc).isoformat()}
        dossiers[key] = (time.monotonic(), dossier)
        view = dossier_view(key)
    return view


@app.get('/api/dossiers/{key}')
def get_dossier(key: str):
    with lock:
        return dossier_view(key)


@app.post('/api/dossiers/{key}/resolve')
def resolve_dossier_check(key: str, body: DossierResolution):
    with lock:
        view = dossier_view(key)
        if body.check_id not in {check['id'] for check in view['checks']}:
            raise HTTPException(422, 'Проверка не найдена в этом досье.')
        dossier = dossiers[key][1]
        dossier['resolutions'][body.check_id] = {'note': body.note.strip(), 'at': datetime.now(timezone.utc).isoformat()}
        dossiers[key] = (time.monotonic(), dossier)
        return dossier_view(key)


@app.get('/api/dossiers/{key}/export')
def export_dossier(key: str):
    with lock:
        view = dossier_view(key)
    return Response(json.dumps(view, ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="student-dossier.json"'})


@app.get('/api/bundle/{key}')
def bundle(key: str):
    with lock:
        result = copy.deepcopy(get_session(key))
    return Response(evidence_bundle(result), media_type='application/zip',
                    headers={'Content-Disposition': 'attachment; filename="document-evidence.zip"'})


@app.get('/api/submission/{key}')
def submission(key: str):
    with lock:
        result = copy.deepcopy(get_session(key))
    if result.get('knowledge_snapshot', {}).get('profile') != 'meridian-v1' or not result['document_type']:
        raise HTTPException(422, 'Экспорт требует правил кейса и выбранного типа документа.')
    doc = submission_document(result['id'], result['document_type'], result['fields'],
                              [{'question_id':result['id']+'-Q1','question':result['question']}], result['knowledge_snapshot'])
    return Response(json.dumps({'version':'1.0','documents':[doc]}, ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition':'attachment; filename="results.json"'})
