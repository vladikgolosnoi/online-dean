"""Explainable checks across a set of already analysed documents."""
from datetime import date
from .extraction import normalize


def present(field):
    return field and field.get('status') in {'found', 'confirmed'} and field.get('value') not in {None, False, ''}


def source(document, key):
    field = document['fields'].get(key, {})
    return {'document_id': document['id'], 'filename': document['filename'], 'document_type': document.get('type_label'),
            'field': key, 'label': field.get('label', key), 'value': field.get('value'), 'evidence': field.get('evidence', [])}


def dates(document, start_key, end_key):
    start, end = document['fields'].get(start_key), document['fields'].get(end_key)
    if not present(start) or not present(end):
        return None
    try:
        return date.fromisoformat(start['value']), date.fromisoformat(end['value'])
    except (TypeError, ValueError):
        return None


def build(documents, resolutions=None):
    resolutions = resolutions or {}
    checks, summaries = [], []
    for document in documents:
        answer = document.get('answer', {})
        summaries.append({'document_id': document['id'], 'filename': document['filename'], 'document_type': document.get('document_type'),
                          'type_label': document.get('type_label'), 'status': answer.get('status'),
                          'ready': answer.get('status') == 'complete'})

    def add(check):
        resolution = resolutions.get(check['id'])
        if resolution:
            check['resolution'] = resolution
            check['status'] = 'resolved'
        checks.append(check)

    for key, label in (('student_name', 'ФИО студента'), ('group', 'Группа'), ('program', 'Направление подготовки')):
        found = [source(d, key) for d in documents if present(d['fields'].get(key))]
        if len(found) < 2:
            continue
        values = {normalize(str(item['value'])) for item in found}
        add({'id': 'field:' + key, 'kind': 'field_match', 'label': label,
             'status': 'pass' if len(values) == 1 else 'review', 'sources': found,
             'message': label + (' совпадает во всех документах.' if len(values) == 1 else ' различается между документами.')})

    leave = next((d for d in documents if d.get('document_type') == 'academic_leave_application'), None)
    internship = next((d for d in documents if d.get('document_type') == 'internship_certificate'), None)
    if leave and internship:
        leave_period, internship_period = dates(leave, 'leave_start', 'leave_end'), dates(internship, 'internship_start', 'internship_end')
        if leave_period and internship_period:
            overlap = max(leave_period[0], internship_period[0]) <= min(leave_period[1], internship_period[1])
            add({'id': 'period:leave_internship', 'kind': 'period_overlap', 'label': 'Периоды отпуска и практики',
                 'status': 'review' if overlap else 'pass',
                 'sources': [source(leave, 'leave_start'), source(leave, 'leave_end'), source(internship, 'internship_start'), source(internship, 'internship_end')],
                 'message': 'Периоды пересекаются — требуется решение сотрудника.' if overlap else 'Периоды не пересекаются.'})

    incomplete = [item for item in summaries if not item['ready']]
    if incomplete:
        add({'id': 'completeness', 'kind': 'completeness', 'label': 'Комплектность документов', 'status': 'review',
             'sources': [{'document_id': item['document_id'], 'filename': item['filename'], 'document_type': item['type_label']} for item in incomplete],
             'message': 'Не все документы пакета содержат обязательные сведения.'})

    review = [check for check in checks if check['status'] == 'review']
    return {'documents': summaries, 'checks': checks,
            'summary': {'documents_total': len(summaries), 'documents_ready': sum(item['ready'] for item in summaries),
                        'checks_total': len(checks), 'needs_review': len(review),
                        'status': 'needs_review' if review else 'ready'}}
