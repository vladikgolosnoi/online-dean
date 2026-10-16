import base64
import io
import math
import os
import re
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError
from .config import ROOT

Image.MAX_IMAGE_PIXELS = 25_000_000
MAX_PAGES = 5
MAX_OCR_SECONDS = 120
WINDOWS_TESSERACT = Path(r'C:\Program Files\Tesseract-OCR\tesseract.exe')
if os.getenv('TESSERACT_CMD'):
    pytesseract.pytesseract.tesseract_cmd = os.environ['TESSERACT_CMD']
elif WINDOWS_TESSERACT.exists():
    pytesseract.pytesseract.tesseract_cmd = str(WINDOWS_TESSERACT)
TESSDATA = Path(os.getenv('TESSDATA_DIR', ROOT / '.runtime' / 'tessdata'))
if TESSDATA.exists():
    os.environ['TESSDATA_PREFIX'] = os.path.relpath(TESSDATA) if os.name == 'nt' else str(TESSDATA)


def tess_config(psm=6):
    # TESSDATA_PREFIX avoids quote handling differences in pytesseract on Windows.
    return f'--oem 1 --psm {psm}'


def health():
    try:
        version = str(pytesseract.get_tesseract_version()).splitlines()[0]
        args = [pytesseract.pytesseract.tesseract_cmd, '--list-langs']
        if TESSDATA.exists():
            args += ['--tessdata-dir', os.path.relpath(TESSDATA) if os.name == 'nt' else str(TESSDATA)]
        output = subprocess.run(args, capture_output=True, timeout=10, check=True)
        languages = [s.strip() for s in output.stdout.decode('utf-8', errors='replace').splitlines()[1:]]
        return {'ready': 'rus' in languages and 'eng' in languages, 'version': version, 'languages': languages}
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, OSError, subprocess.SubprocessError) as e:
        return {'ready': False, 'error': 'Установите Tesseract и языки rus+eng. См. README.', 'detail': type(e).__name__}


def decode(data):
    if data.startswith(b'%PDF-'):
        try:
            document = pdfium.PdfDocument(data)
            with document:
                if not 1 <= len(document) <= MAX_PAGES:
                    raise ValueError(f'Допускается от 1 до {MAX_PAGES} страниц PDF.')
                images = []
                for page in document:
                    try:
                        w, h = page.get_size()
                        scale = min(2.5, 2400 / max(w, h))
                        bitmap = page.render(scale=scale)
                        try:
                            images.append(bitmap.to_pil().convert('RGB').copy())
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
                return images
        except pdfium.PdfiumError as e:
            raise ValueError('Не удалось открыть PDF. Проверьте, не защищён ли он паролем.') from e
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {'PNG', 'JPEG'}:
                raise ValueError('Поддерживаются только JPG, PNG и PDF.')
            if source.width * source.height > Image.MAX_IMAGE_PIXELS:
                raise ValueError('Изображение слишком большое: максимум 25 мегапикселей.')
            rgba = ImageOps.exif_transpose(source).convert('RGBA')
            background = Image.new('RGBA', rgba.size, 'white')
            background.alpha_composite(rgba)
            return [background.convert('RGB')]
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as e:
        raise ValueError('Файл не удалось прочитать как изображение.') from e


def prepare(image):
    arr = np.array(image)
    h, w = arr.shape[:2]
    scale = min(2.0, 2200 / max(h, w))
    if abs(scale - 1) > .05:
        arr = cv2.resize(arr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    edges = cv2.Canny(gray, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, 80, minLineLength=arr.shape[1] // 8, maxLineGap=25)
    angles = []
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0]:
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
            if -31 <= angle <= 31:
                angles.append(angle)
    angle = float(np.median(angles)) if len(angles) >= 3 else 0.0
    if 0.3 < abs(angle) <= 31:
        h, w = arr.shape[:2]
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1)
        cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
        nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
        matrix[0, 2] += (nw - w) / 2
        matrix[1, 2] += (nh - h) / 2
        arr = cv2.warpAffine(arr, matrix, (nw, nh), borderValue=(255, 255, 255))
    return Image.fromarray(arr), {'deskew_degrees': round(angle, 2), 'sharpness': round(blur, 1),
                                 'warnings': ['Снимок может быть размыт. Проверьте значения.'] if blur < 45 else []}


def recognize(image, page_number, psm=6, timeout=40, language='rus+eng'):
    data = pytesseract.image_to_data(image, lang=language, config=tess_config(psm),
                                     output_type=pytesseract.Output.DICT, timeout=timeout)
    groups = {}
    for i, text in enumerate(data['text']):
        if not text.strip() or float(data['conf'][i]) < 0:
            continue
        group = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
        groups.setdefault(group, []).append(i)
    result = []
    for ids in groups.values():
        x = min(data['left'][i] for i in ids)
        y = min(data['top'][i] for i in ids)
        right = max(data['left'][i] + data['width'][i] for i in ids)
        bottom = max(data['top'][i] + data['height'][i] for i in ids)
        words, offset = [], 0
        for i in ids:
            token = data['text'][i]
            words.append({'text': token, 'start': offset, 'end': offset + len(token),
                          'bbox': [data['left'][i], data['top'][i], data['left'][i] + data['width'][i], data['top'][i] + data['height'][i]],
                          'confidence': float(data['conf'][i])})
            offset += len(token) + 1
        result.append({'text': ' '.join(data['text'][i] for i in ids), 'page': page_number,
                       'bbox': [x, y, right, bottom], 'confidence': float(np.mean([float(data['conf'][i]) for i in ids])), 'words': words})
    return result


def run_ocr(data):
    if not health()['ready']:
        raise RuntimeError('Tesseract с языками rus+eng не установлен. См. README.')
    deadline = time.monotonic() + MAX_OCR_SECONDS
    def timed_recognize(image, index, psm=6, language='rus+eng'):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError('Превышено время OCR (120 секунд). Разделите PDF или загрузите более чёткий снимок.')
        try:
            return recognize(image, index, psm, timeout=min(40, remaining), language=language)
        except RuntimeError as exc:
            if 'timeout' in str(exc).lower():
                raise RuntimeError('OCR не успел обработать страницу. Разделите PDF или загрузите более чёткий снимок.') from exc
            raise
    pages, all_lines = [], []
    for index, image in enumerate(decode(data), 1):
        image, quality = prepare(image)
        lines = timed_recognize(image, index)
        quality['orientation_degrees'] = 0
        def mean_conf(candidate):
            return float(np.mean([line['confidence'] for line in candidate])) if candidate else 0
        def rank(candidate):
            return mean_conf(candidate) * math.log1p(sum(len(line['text']) for line in candidate))
        gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
        background = cv2.GaussianBlur(gray, (0, 0), 25)
        uneven = float(np.percentile(background, 95) - np.percentile(background, 5))
        ocr_image = image
        if uneven > 35 or mean_conf(lines) < 75 or sum(len(line['text']) for line in lines) < 60:
            corrected = Image.fromarray(cv2.divide(gray, background, scale=255))
            candidate = timed_recognize(corrected, index)
            if rank(candidate) > rank(lines) * 1.02:
                lines, ocr_image = candidate, corrected
                quality['warnings'].append('Применена коррекция неравномерного освещения.')
        if mean_conf(lines) < 75 or sum(len(line['text']) for line in lines) < 35:
            best_rank = rank(lines)
            source, ocr_source = image, ocr_image
            for rotation in (90, 180, 270):
                rotated = ocr_source.rotate(rotation, expand=True, fillcolor='white')
                candidate = timed_recognize(rotated, index)
                if rank(candidate) > best_rank * 1.08:
                    best_rank, lines, ocr_image = rank(candidate), candidate, rotated
                    image = source.rotate(rotation, expand=True, fillcolor='white')
                    quality['orientation_degrees'] = rotation
            if quality['orientation_degrees']:
                quality['warnings'].append('Исправлена ориентация страницы на ' + str(quality['orientation_degrees']) + '°.')
        if mean_conf(lines) < 65:
            alternate = timed_recognize(ocr_image, index, psm=3)
            if rank(alternate) > rank(lines) * 1.02:
                lines = alternate
                quality['warnings'].append('Применён альтернативный анализ структуры страницы.')
        # Re-read ambiguous Latin/Cyrillic document IDs in a tighter line crop.
        # The replacement still comes from pixels; never translate letters by a lookup table.
        for position, line in enumerate(lines):
            if not re.search(r'номер\s+(?:справки|документа)\s*:', line['text'], re.I):
                continue
            original = line['text'].split(':', 1)[-1].strip()
            if not re.search(r'[A-Za-z]', original):
                continue
            x, y, right, bottom = line['bbox']
            left, top = max(0, x-12), max(0, y-12)
            crop = ocr_image.crop((left, top, min(ocr_image.width, right+12), min(ocr_image.height, bottom+12)))
            candidate = timed_recognize(crop, index, psm=7)
            # Russian-labelled identifiers can lose non-Latin letter details in bilingual OCR.
            russian = timed_recognize(crop, index, psm=7, language='rus')
            distinct_cyrillic = len(russian) == 1 and re.search(r'[БГДЖЗИЙЛПФЦЧШЩЪЫЬЭЮЯ]', russian[0]['text'].split(':')[-1])
            if len(russian) == 1 and (not candidate or russian[0]['confidence'] >= candidate[0]['confidence'] or
                                     (distinct_cyrillic and russian[0]['confidence'] >= 90 and russian[0]['confidence'] >= candidate[0]['confidence']-1)):
                candidate = russian
            if len(candidate) != 1 or ':' not in candidate[0]['text']:
                continue
            replacement = candidate[0]['text'].split(':', 1)[-1].strip()
            if re.findall(r'\d+', original) != re.findall(r'\d+', replacement) or candidate[0]['confidence'] < line['confidence']-5:
                continue
            corrected = candidate[0]
            for item in [corrected, *corrected.get('words', [])]:
                bx, by, br, bb = item['bbox']
                item['bbox'] = [bx+left, by+top, br+left, bb+top]
            corrected['ocr_method'] = 'identifier_line_crop'
            lines[position] = corrected
        quality['ocr_mean_confidence'] = round(mean_conf(lines), 1)
        quality['text_characters'] = sum(len(line['text']) for line in lines)
        if quality['text_characters'] < 35:
            quality['warnings'].append('Недостаточно читаемого текста. Снимите страницу целиком при ровном освещении.')
        elif quality['ocr_mean_confidence'] < 65:
            quality['warnings'].append('Низкая оценка распознавания. Сверьте все поля с оригиналом или загрузите более чёткий снимок.')
        buf = io.BytesIO()
        from .vision import detect_marks
        visual = detect_marks(image, lines, index)
        image.save(buf, format='JPEG', quality=83)
        pages.append({'number': index, 'width': image.width, 'height': image.height,
                      'image': 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode(), 'quality': quality, 'visual_marks': visual})
        all_lines.extend(lines)
    return {'pages': pages, 'lines': all_lines, 'text': '\n'.join(line['text'] for line in all_lines)}
