import pytest
from fastapi.testclient import TestClient
from app.main import app, sessions, dossiers
from app.extraction import extract
from app.config import RULES as LEGACY_RULES


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def test_home_and_security_headers(client):
    r = client.get('/')
    assert r.status_code == 200
    assert 'no-store' in r.headers['cache-control']
    assert "frame-ancestors 'none'" in r.headers['content-security-policy']


def test_local_host_and_origin_boundary(client):
    assert client.get('/', headers={'host': 'attacker.example'}).status_code == 400
    assert client.get('/api/ready', headers={'host': 'online-dean-demo.onrender.com'}).status_code == 200
    assert client.post('/api/demo/study', headers={'origin': 'https://attacker.example'}).status_code == 403
    # A same-origin request reaches the route (unknown demo returns 404).
    assert client.post('/api/demo/no-such-demo', headers={'origin': 'http://testserver'}).status_code == 404


def test_session_access_refreshes_expiration(client):
    import time
    from app.main import get_session, TTL
    sessions['refresh'] = (time.monotonic() - TTL + 1, {'value': 42})
    assert get_session('refresh')['value'] == 42
    assert time.monotonic() - sessions['refresh'][0] < 1


def test_upload_empty_and_unknown_type(client):
    assert client.post('/api/analyze', files={'file': ('x.png', b'')}, data={'question': 'Что здесь?'}).status_code == 422
    assert client.post('/api/analyze', files={'file': ('x.png', b'abc')}, data={'question': 'Что здесь?', 'document_type': 'unknown'}).status_code == 422


def test_invalid_review_does_not_partially_mutate(client):
    import time
    f = extract([], 'study_certificate')
    sessions['test'] = (time.monotonic(), {'fields': f, 'audit': [], 'knowledge_snapshot': LEGACY_RULES, 'document_type': 'study_certificate', 'question': 'Хватит ли справки?'})
    r = client.post('/api/review/test', json={'corrections': {'student_name': 'Новое имя', 'issue_date': '31.02.2026'}})
    assert r.status_code == 422
    assert sessions['test'][1]['fields']['student_name']['value'] is None
    assert sessions['test'][1]['audit'] == []


def test_manual_visual_review_and_delete(client):
    import time
    sessions['test'] = (time.monotonic(), {'fields': extract([], 'study_certificate'), 'audit': [], 'knowledge_snapshot': LEGACY_RULES, 'document_type': 'study_certificate', 'question': 'Хватит ли справки?'})
    assert client.post('/api/review/test', json={'corrections': {'stamp': 'да'}}).status_code == 422
    r = client.post('/api/review/test', json={'corrections': {'stamp': True}})
    assert r.status_code == 200
    assert r.json()['fields']['stamp']['source'] == 'manual_review'
    client.delete('/api/session/test')
    assert client.post('/api/review/test', json={'question': 'Дата выдачи?'}).status_code == 404


def test_appeal_draft_is_available_only_after_preliminary_readiness(client):
    import time
    sessions['appeal-ready'] = (time.monotonic(), {
        'type_label': 'Справка об обучении',
        'workflow': {'status': 'ready_for_decision'},
        'fields': {'student_name': {'value': 'Иванов Иван Иванович'}},
        'answer': {'checks': [{'label': 'ФИО студента', 'status': 'pass'}]},
    })
    sessions['appeal-blocked'] = (time.monotonic(), {
        'type_label': 'Справка об обучении',
        'workflow': {'status': 'needs_completion'},
        'fields': {},
        'answer': {'checks': [{'label': 'Дата выдачи', 'status': 'missing'}]},
    })
    ready = client.get('/api/appeal/appeal-ready').json()
    blocked = client.get('/api/appeal/appeal-blocked').json()
    assert ready['ready'] is True
    assert 'Иванов Иван Иванович' in ready['body']
    assert blocked['ready'] is False
    assert blocked['issues'] == ['Дата выдачи']
    download = client.get('/api/appeal/appeal-ready/download')
    assert download.status_code == 200
    assert 'В деканат' in download.text
    sessions.pop('appeal-ready', None)
    sessions.pop('appeal-blocked', None)


def test_dossier_api_keeps_explainable_conflict(client):
    import time
    first = {'id': 'd1', 'filename': 'study.png', 'document_type': 'study_certificate', 'type_label': 'Справка',
             'fields': {'student_name': {'label': 'ФИО студента', 'value': 'Иванов Иван Иванович', 'status': 'found', 'evidence': []}},
             'answer': {'status': 'complete'}}
    second = {'id': 'd2', 'filename': 'leave.png', 'document_type': 'academic_leave_application', 'type_label': 'Заявление',
              'fields': {'student_name': {'label': 'ФИО студента', 'value': 'Иванов Пётр Иванович', 'status': 'found', 'evidence': []}},
              'answer': {'status': 'complete'}}
    sessions['d1'] = (time.monotonic(), first)
    sessions['d2'] = (time.monotonic(), second)
    response = client.post('/api/dossiers', json={'name': 'Проверка студента', 'document_ids': ['d1', 'd2']})
    assert response.status_code == 200
    dossier = response.json()
    check = next(item for item in dossier['checks'] if item['id'] == 'field:student_name')
    assert check['status'] == 'review'
    resolved = client.post('/api/dossiers/' + dossier['id'] + '/resolve', json={'check_id': check['id'], 'note': 'Сверено с оригиналом'})
    assert resolved.status_code == 200
    assert next(item for item in resolved.json()['checks'] if item['id'] == check['id'])['status'] == 'resolved'
    dossiers.pop(dossier['id'], None)
    sessions.pop('d1', None)
    sessions.pop('d2', None)
