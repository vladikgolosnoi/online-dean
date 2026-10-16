from app.redaction import redact_analysis


def test_redacted_export_excludes_document_content_and_masks_identifiers():
    result = {
        'filename': 'Иванов-справка.png', 'sha256': 'secret',
        'ocr': {'text': 'Иванов Иван Иванович № АБ-7394', 'pages': [{'number': 1, 'width': 100, 'height': 200, 'image': 'data:secret', 'quality': {'warnings': []}}]},
        'fields': {
            'student_name': {'value': 'Иванов Иван Иванович', 'evidence': [{'text': 'Иванов'}]},
            'document_number': {'value': 'АБ-7394', 'evidence': [{'text': '7394'}]},
            'program': {'value': '09.03.02', 'evidence': [{'text': '09.03.02'}]},
        },
        'audit': [{'field': 'student_name', 'before': 'Иванов Иван Иванович', 'after': 'Петров Пётр Петрович'}]
    }
    export = redact_analysis(result)
    assert export['filename'] == 'document-redacted'
    assert 'sha256' not in export
    assert export['ocr']['text'].startswith('[содержимое')
    assert export['ocr']['pages'][0].get('image') is None
    assert export['fields']['student_name']['value'] == 'И*** И*** И***'
    assert export['fields']['student_name']['evidence'] == []
    assert export['fields']['document_number']['value'].endswith('94')
    assert export['fields']['program']['value'] == '09.03.02'
    assert export['audit'][0]['after'] == 'П*** П*** П***'
