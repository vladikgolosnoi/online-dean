"""Offline preflight: python -m scripts.doctor [--smoke]."""
import argparse
import copy
import json
import re
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke', action='store_true', help='Also recognize one synthetic document')
    args = parser.parse_args()
    checks = []
    def record(name, ok, detail):
        checks.append({'check': name, 'ok': bool(ok), 'detail': detail})
    record('python', sys.version_info >= (3, 12), sys.version.split()[0])
    try:
        from app.config import ROOT
        from app.official import RULES, SCHEMAS
        from app.knowledge import validate_rules
        from app.ocr import health
        validate_rules(copy.deepcopy(RULES), SCHEMAS)
        for schema in SCHEMAS.values():
            for field in schema['fields'].values():
                for pattern in field.get('patterns', []):
                    re.compile(pattern)
        record('configuration', True, f'{len(SCHEMAS)} types; {len(RULES["clauses"])} clauses; demo={RULES["demo"]}')
        engine = health()
        record('ocr', engine['ready'], engine)
        for name in ('open-002.png', 'open-011.png', 'open-021.png'):
            record('sample/' + name, (ROOT / 'official' / 'participants-v1' / 'documents' / name).is_file(), 'Official participant documents required')
        if args.smoke and engine['ready']:
            from app.pipeline import analyze
            result = analyze((ROOT / 'official' / 'participants-v1' / 'documents' / 'open-002.png').read_bytes(), 'Проверь комплектность справки')
            record('end_to_end', result['document_type'] == 'study_certificate' and result['answer']['status'] == 'missing_data',
                   {'type': result['document_type'], 'answer': result['answer']['status'], 'ms': result['timing_ms']})
    except Exception as exc:
        record('startup', False, f'{type(exc).__name__}: {exc}')
    report = {'ready': all(c['ok'] for c in checks), 'checks': checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
