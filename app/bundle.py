"""Portable evidence package: processed pages, machine result and review receipt."""
import base64
import copy
import hashlib
import io
import json
from zipfile import ZipFile, ZIP_DEFLATED
from .report import render_report


def evidence_bundle(result):
    portable = copy.deepcopy(result)
    files = {}
    for page in portable['ocr']['pages']:
        image = page.pop('image', None)
        if image:
            filename = f"pages/page-{page['number']:03d}.jpg"
            files[filename] = base64.b64decode(image.split(',', 1)[1], validate=True)
            page['image_file'] = filename
    files['analysis.json'] = json.dumps(portable, ensure_ascii=False, indent=2).encode('utf-8')
    files['report.html'] = render_report(result).encode('utf-8')
    files['README.txt'] = ('Онлайн-деканат — пакет проверки\n\n'
        'report.html — печатный протокол; analysis.json — поля, цитаты и история исправлений.\n'
        'pages/ — обработанные страницы после коррекции, НЕ исходный файл загрузки.\n'
        'Координаты evidence.bbox относятся к соответствующей обработанной странице.\n'
        'SHA-256 исходного документа находится в analysis.json. Сам оригинал в пакет не входит.\n'
        'knowledge_snapshot содержит точную базу правил, использованную для анализа.\n'
        'MANIFEST.json позволяет проверить целостность файлов, но не удостоверяет их подлинность.\n'
        'Пакет может содержать персональные данные. Храните его как исходный документ.\n'
        'Окончательное решение принимает сотрудник деканата.\n').encode('utf-8')
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    stream = io.BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr('MANIFEST.json', json.dumps(manifest, indent=2))
    return stream.getvalue()
