"""Run local OCR on a participant manifest; references are never loaded here."""
import argparse,json,hashlib,time
from pathlib import Path
from app.ocr import run_ocr
from app.official import extract_official, submission_document


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,default=Path('official/participants-v1'))
    p.add_argument('--output',type=Path,default=Path('output/official/results.json'))
    p.add_argument('--format',choices=['image','pdf'],default='image')
    p.add_argument('--cache',type=Path,help='Optional OCR-only cache; keyed by file content, never labels')
    args=p.parse_args()
    docs=json.loads((args.package/'documents.json').read_text(encoding='utf-8'))
    questions=json.loads((args.package/'questions.json').read_text(encoding='utf-8'))
    results=[]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.cache: args.cache.mkdir(parents=True,exist_ok=True)
    for doc in docs:
        start=time.perf_counter()
        path=(args.package/doc[args.format]).resolve()
        if not path.is_relative_to(args.package.resolve()): raise ValueError('Document outside package')
        data=path.read_bytes();digest=hashlib.sha256(b'ocr-3.0.0-r3\0'+data).hexdigest()
        cache=args.cache/(digest+'.json') if args.cache else None
        if cache and cache.exists():ocr=json.loads(cache.read_text(encoding='utf-8'))
        else:
            ocr=run_ocr(data)
            if cache:
                for page in ocr['pages']:page.pop('image',None)
                cache.write_text(json.dumps(ocr,ensure_ascii=False),encoding='utf-8')
        fields=extract_official(ocr,doc['document_type'])
        result=submission_document(doc['document_id'],doc['document_type'],fields,[q for q in questions if q['document_id']==doc['document_id']])
        results.append(result)
        print(doc['document_id'],result['validation']['status'],round(time.perf_counter()-start,2),flush=True)
    args.output.write_text(json.dumps({'version':'1.0','documents':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
