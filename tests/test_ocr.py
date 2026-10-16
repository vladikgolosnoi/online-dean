import io
from pathlib import Path
import pytest
from PIL import Image
from app.config import ROOT
from app.ocr import decode, health
from app.pipeline import analyze


def test_reject_non_image_and_six_page_pdf():
    with pytest.raises(ValueError):
        decode(b'not an image')
    image = Image.new('RGB', (100, 100), 'white')
    stream = io.BytesIO()
    image.save(stream, format='PDF', save_all=True, append_images=[image] * 5)
    with pytest.raises(ValueError, match='5'):
        decode(stream.getvalue())


@pytest.mark.skipif(not health()['ready'], reason='Tesseract rus+eng unavailable')
def test_real_ocr_image_pdf_and_tilt():
    path = ROOT / 'samples' / 'study.png'
    if not path.exists():
        pytest.skip('Generate samples first')
    pdf = io.BytesIO()
    with Image.open(path) as image:
        image.save(pdf, format='PDF', resolution=100)
    for data in [path.read_bytes(), pdf.getvalue(), (ROOT / 'samples' / 'study_tilt20.png').read_bytes()]:
        from app.config import RULES as LEGACY_RULES
        r = analyze(data, 'Хватит ли справки для перевода?', rules=LEGACY_RULES)
        assert r['document_type'] == 'study_certificate'
        assert r['fields']['student_name']['value'] == 'Иванов Иван Иванович'
        assert r['fields']['issue_date']['status'] == 'not_found'
        assert r['answer']['status'] == 'missing_data'
        for f in r['fields'].values():
            for evidence in f['evidence']:
                x1, y1, x2, y2 = evidence['bbox']
                page = r['ocr']['pages'][evidence['page'] - 1]
                assert 0 <= x1 < x2 <= page['width']
                assert 0 <= y1 < y2 <= page['height']
