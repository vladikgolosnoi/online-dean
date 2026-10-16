from app.report import render_report


def test_printable_report_translates_internal_field_statuses():
    result = {
        'id': 'check-1', 'type_label': 'Справка об обучении', 'filename': 'study.png',
        'question': 'Проверить комплектность?', 'workflow': {'status': 'ready_for_decision'},
        'fields': {
            'student_name': {'label': 'ФИО студента', 'value': 'Иванов Иван', 'status': 'found', 'evidence': []},
            'issue_date': {'label': 'Дата выдачи', 'value': None, 'status': 'not_found', 'evidence': []},
        },
        'answer': {'text': 'Нужно дополнить документ.', 'citations': [], 'rules_sha256': 'rules-hash'},
        'rules': {'demo': False, 'title': 'Положение', 'version': '1.0'},
        'audit': [], 'ocr': {'pages': []}, 'sha256': 'document-hash',
    }
    html = render_report(result)
    assert '>found<' not in html
    assert 'Найдено' in html
    assert 'Не найдено' in html
    assert '<title>Протокол проверки документа</title>' in html
