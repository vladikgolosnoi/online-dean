from app.dossier import build


def document(identifier, typ, name, ready=True, fields=None):
    data = {}
    for key, value in (fields or {}).items():
        data[key] = {'label': key, 'value': value, 'status': 'found', 'evidence': []}
    return {'id': identifier, 'filename': identifier + '.png', 'document_type': typ, 'type_label': typ,
            'fields': data, 'answer': {'status': 'complete' if ready else 'missing_data'}}


def test_dossier_reports_conflict_and_manual_resolution():
    study = document('study', 'study_certificate', 'Анна Иванова', fields={'student_name': 'Анна Иванова'})
    leave = document('leave', 'academic_leave_application', 'Анна Петрова', fields={'student_name': 'Анна Петрова'})
    result = build([study, leave])
    check = next(c for c in result['checks'] if c['id'] == 'field:student_name')
    assert check['status'] == 'review'
    resolved = build([study, leave], {'field:student_name': {'note': 'Подтверждено по оригиналу'}})
    assert next(c for c in resolved['checks'] if c['id'] == 'field:student_name')['status'] == 'resolved'


def test_dossier_detects_overlapping_leave_and_internship():
    leave = document('leave', 'academic_leave_application', 'Анна', fields={'leave_start': '2026-01-10', 'leave_end': '2026-03-10'})
    practice = document('practice', 'internship_certificate', 'Анна', fields={'internship_start': '2026-02-01', 'internship_end': '2026-02-20'})
    result = build([leave, practice])
    check = next(c for c in result['checks'] if c['id'] == 'period:leave_internship')
    assert check['status'] == 'review'
