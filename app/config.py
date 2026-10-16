import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.getenv('DEAN_CONFIG_DIR', ROOT / 'config'))


def validate_schemas(schemas):
    if not isinstance(schemas, dict) or not schemas:
        raise ValueError('documents.json должен содержать хотя бы один тип документа.')
    allowed_kinds = {'text', 'date', 'number', 'period', 'visual'}
    for key, schema in schemas.items():
        if not isinstance(key, str) or not isinstance(schema, dict):
            raise ValueError('Идентификатор и описание типа документа должны быть объектами JSON.')
        if not isinstance(schema.get('label'), str) or not schema['label'].strip():
            raise ValueError('У типа ' + key + ' нет label.')
        if not isinstance(schema.get('markers', []), list) or any(not isinstance(item, str) for item in schema.get('markers', [])):
            raise ValueError('markers типа ' + key + ' должен быть списком строк.')
        fields = schema.get('fields')
        if not isinstance(fields, dict) or not fields:
            raise ValueError('У типа ' + key + ' нет полей.')
        for field_key, field in fields.items():
            if not isinstance(field, dict) or not isinstance(field.get('label'), str):
                raise ValueError('У поля ' + key + '.' + field_key + ' нет label.')
            if field.get('kind') not in allowed_kinds:
                raise ValueError('Некорректный kind поля ' + key + '.' + field_key + '.')
            if not isinstance(field.get('aliases', []), list) or any(not isinstance(item, str) for item in field.get('aliases', [])):
                raise ValueError('aliases поля ' + key + '.' + field_key + ' должен быть списком строк.')
    return schemas


def load_config():
    schemas = json.loads((CONFIG_DIR / 'documents.json').read_text(encoding='utf-8-sig'))
    rules = json.loads((CONFIG_DIR / 'rules.json').read_text(encoding='utf-8-sig'))
    validate_schemas(schemas)
    ids = set()
    for rule in rules['clauses']:
        if rule['id'] in ids:
            raise ValueError('Duplicate clause ID: ' + rule['id'])
        ids.add(rule['id'])
        schema = schemas[rule['document_type']] if rule['document_type'] != '*' else {'fields': {}}
        for field in rule.get('required_fields', []):
            if field not in schema['fields']:
                raise ValueError('Unknown required field: ' + field)
    return schemas, rules


SCHEMAS, RULES = load_config()
