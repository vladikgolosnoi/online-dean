"""Public MWS OCR diagnostic. Not the official benchmark and never training data."""
import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from app.config import ROOT
from app.ocr import run_ocr

DATASET = 'MTSAIR/MWS-Vision-Bench'


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'OnlineDean-Hackathon-OCR-Diagnostic/0.1'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def norm(text):
    return re.sub(r'\s+', ' ', text).strip()


def edit_distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--max-rows', type=int, default=400)
    args = parser.parse_args()
    if not 1 <= args.limit <= 50 or not 1 <= args.max_rows <= 1400:
        parser.error('limit: 1..50; max-rows: 1..1400')
    folder = ROOT / 'output' / 'mws-diagnostic'
    folder.mkdir(parents=True, exist_ok=True)
    cases, seen, scanned = [], set(), 0
    for offset in range(0, args.max_rows, 100):
        query = urllib.parse.urlencode({'dataset': DATASET, 'config': 'default', 'split': 'train', 'offset': offset, 'length': min(100, args.max_rows - offset)})
        payload = json.loads(fetch('https://datasets-server.huggingface.co/rows?' + query))
        for item in payload['rows']:
            scanned += 1
            row = item['row']
            q = row['question'].lower()
            if row['type'] != 'full-page OCR ru':
                continue
            whole_page_phrases = ['весь текст', 'весь документ', 'полный текст', 'текст с изображения', 'текст на этой картинке', 'текст с картинки', 'текст в этом изображении']
            if not any(phrase in q for phrase in whole_page_phrases):
                continue
            # Only whole-document transcription requests; skip cropped-paragraph tasks.
            if any(s in q for s in ['абзац', 'пункт', 'только услов', 'последн', 'первых', 'первый', 'столб', 'заголов', 'только текст']):
                continue
            image = fetch(row['image']['src'])
            sha = hashlib.sha256(image).hexdigest()
            if sha in seen:
                continue
            seen.add(sha)
            file_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(row['id']))
            (folder / f'{file_id}.image').write_bytes(image)
            start = time.perf_counter()
            result = run_ocr(image)
            actual = norm(result['text'])
            references = [norm(s) for s in row['answers'] if s]
            best = min(((edit_distance(actual, reference), len(reference)) for reference in references), key=lambda pair: pair[0] / max(pair[1], 1))
            case = {'id': row['id'], 'question': row['question'], 'type': row['type'], 'sha256': sha,
                    'cer': round(best[0] / max(best[1], 1), 4), 'edit_distance': best[0], 'reference_characters': best[1],
                    'timing_ms': round((time.perf_counter() - start) * 1000), 'prediction': result['text'], 'references': row['answers']}
            cases.append(case)
            print(json.dumps({k: case[k] for k in ['id', 'cer', 'timing_ms']}, ensure_ascii=False), flush=True)
            if len(cases) >= args.limit:
                break
        if len(cases) >= args.limit or not payload['rows']:
            break
    report = {'dataset': DATASET, 'source': 'https://huggingface.co/datasets/' + DATASET,
              'license': 'CC BY 4.0', 'attribution': 'MTS AI Research / MTSAIR', 'fetched_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'First qualifying full-page OCR rows. Not random. Whitespace-normalized CER; NOT official benchmark Overall.',
              'selection': 'full-page OCR ru; whitelist whole-page transcription phrases; exclude paragraph/section/header-specific instructions; deduplicate image SHA-256',
              'rows_scanned': scanned, 'count': len(cases),
              'micro_cer': sum(c['edit_distance'] for c in cases) / max(1, sum(c['reference_characters'] for c in cases)), 'cases': cases}
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Saved ' + str(folder / 'report.json'))


if __name__ == '__main__':
    main()
