"""Create a shareable analysis without document content or direct identifiers."""
import copy


DIRECT_IDENTIFIERS = {'student_name', 'supervisor_name', 'supervisor', 'document_number'}


def mask_name(value):
    if not isinstance(value, str):
        return value
    return ' '.join(part[:1] + '***' for part in value.split()) or None


def mask_number(value):
    if not isinstance(value, str):
        return value
    return '••••' + value[-2:] if len(value) > 2 else '••••'


def mask_value(key, value):
    if key in {'student_name', 'supervisor_name', 'supervisor'}:
        return mask_name(value)
    if key == 'document_number':
        return mask_number(value)
    return value


def redact_analysis(result):
    """Return verification facts while removing OCR, images and direct identifiers."""
    redacted = copy.deepcopy(result)
    redacted['filename'] = 'document-redacted'
    redacted.pop('sha256', None)
    redacted['ocr'] = {
        'pages': [{'number': page.get('number'), 'width': page.get('width'), 'height': page.get('height'),
                   'quality': page.get('quality', {})} for page in result.get('ocr', {}).get('pages', [])],
        'text': '[содержимое документа исключено из обезличенной выгрузки]'
    }
    for key, field in redacted.get('fields', {}).items():
        if key in DIRECT_IDENTIFIERS:
            field['value'] = mask_value(key, field.get('value'))
            field['evidence'] = []
            field['source'] = 'redacted'
    for entry in redacted.get('audit', []):
        key = entry.get('field')
        entry['before'] = mask_value(key, entry.get('before'))
        entry['after'] = mask_value(key, entry.get('after'))
    redacted['privacy'] = {
        'mode': 'redacted',
        'excluded': ['исходный файл', 'изображения страниц', 'OCR-текст', 'координаты источников'],
        'masked_fields': sorted(DIRECT_IDENTIFIERS),
        'notice': 'Выгрузка предназначена для демонстрации качества проверки и не заменяет исходный протокол.'
    }
    return redacted
