"""Prototype manifest runner. Legacy format; use scripts.official_batch for the contest."""
import argparse
import json
from pathlib import Path
from app.pipeline import analyze
from app.config import SCHEMAS, RULES
from app.knowledge import validate_rules, fingerprint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path, help='JSON array: id, file, question, optional document_type')
    parser.add_argument('--output', type=Path, default=Path('output/results.prototype.json'))
    parser.add_argument('--rules', type=Path, help='Validated structured JSON regulations; default is DEMO rules')
    args = parser.parse_args()
    rules = validate_rules(json.loads(args.rules.read_text(encoding='utf-8-sig')), SCHEMAS) if args.rules else RULES
    results = []
    for item in json.loads(args.manifest.read_text(encoding='utf-8')):
        path = args.manifest.parent / item['file']
        r = analyze(path.read_bytes(), item['question'], item.get('document_type', 'auto'), path.name, rules)
        results.append({'id': item['id'], 'document_type': r['document_type'],
                        'fields': {k: f['value'] if f['status'] == 'found' else None for k, f in r['fields'].items()},
                        'field_statuses': {k: f['status'] for k, f in r['fields'].items()},
                        'rules_sha256': fingerprint(r['knowledge_snapshot']),
                        'answer': r['answer'], 'sha256': r['sha256'], 'timing_ms': r['timing_ms']})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'schema_version': 'prototype-1', 'not_official_submission_format': True, 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
