from app.workflow import route


def fields():
    return {'signature_present': {'label': 'Подпись', 'kind': 'visual', 'status': 'found'}}


def test_workflow_requests_missing_data_before_final_decision():
    result = route('study_certificate', {'checks': [{'label': 'ФИО студента', 'status': 'missing'}]}, fields())
    assert result['status'] == 'needs_completion'
    assert 'ФИО студента' in result['reasons'][0]


def test_workflow_routes_clean_document_to_employee_not_auto_acceptance():
    result = route('study_certificate', {'checks': [{'label': 'ФИО студента', 'status': 'pass'}]}, fields())
    assert result['status'] == 'ready_for_decision'
    assert 'сотрудником' in result['summary']
