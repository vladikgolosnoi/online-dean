from app.config import RULES as LEGACY_RULES
"""Small synthetic smoke benchmark, explicitly NOT a contest-quality estimate."""
import json
from pathlib import Path
from app.config import ROOT
from app.pipeline import analyze
from app.extraction import normalize


def main():
    fixtures = json.loads((ROOT / 'samples' / 'expected.json').read_text(encoding='utf-8'))
    cases = []
    for example in fixtures:
        result = analyze((ROOT / 'samples' / example['file']).read_bytes(), 'Проверьте комплектность документа', rules=LEGACY_RULES)
        correct, errors = 0, []
        for key, value in example['fields'].items():
            field = result['fields'].get(key, {})
            actual = field.get('value')
            # Normalize only whitespace, case and period separators, not OCR typos.
            expected = normalize(value).replace(' - ', ' — ')
            actual_norm = normalize(str(actual)).replace(' - ', ' — ')
            if actual_norm == expected and field.get('status') == 'found':
                correct += 1
            else:
                errors.append({'field': key, 'expected': value, 'actual': actual, 'status': field.get('status')})
        missing_ok = all(result['fields'][key]['status'] == 'not_found' for key in example['missing'])
        cases.append({'id': example['id'], 'correct': correct, 'total': len(example['fields']), 'type_correct': result['document_type'] == example['document_type'],
                      'missing_correct': missing_ok, 'errors': errors, 'timing_ms': result['timing_ms']})
    report = {'scope': 'Generated clean printed fixtures only. Not organizer or MWS evaluation.', 'cases': cases,
              'exact_field_accuracy': sum(c['correct'] for c in cases) / sum(c['total'] for c in cases)}
    folder = ROOT / 'output'
    folder.mkdir(exist_ok=True)
    (folder / 'smoke-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
