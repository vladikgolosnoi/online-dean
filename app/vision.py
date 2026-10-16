"""Explainable visual mark proposals. Detects appearance, never authenticity."""
import cv2
import numpy as np


def detect_marks(image, lines, page_number):
    arr = np.asarray(image.convert('RGB'))
    h, w = arr.shape[:2]
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    # Colored ink, excluding near-black printed text and low-saturation shadows.
    ink = cv2.inRange(hsv, np.array([85, 50, 30]), np.array([145, 255, 235]))
    proposals = []
    contours, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    stamp_boxes = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if y < h * .38 or min(bw, bh) < w * .055 or max(bw, bh) > w * .36:
            continue
        area, perimeter = cv2.contourArea(contour), cv2.arcLength(contour, True)
        circularity = 4 * np.pi * area / max(perimeter ** 2, 1)
        aspect = bw / bh
        # Require ring geometry AND interior ink (a plain empty circle is not a seal).
        inner = ink[y + int(bh*.25):y + int(bh*.75), x + int(bw*.25):x + int(bw*.75)]
        interior = np.count_nonzero(inner) / max(inner.size, 1)
        if .7 <= aspect <= 1.35 and circularity > .67 and .012 < interior < .55:
            box = [x, y, x + bw, y + bh]
            stamp_boxes.append(box)
            proposals.append({'kind': 'stamp', 'value': True, 'score': round(float(min(.96, .7 + circularity*.25)), 3),
                              'page': page_number, 'bbox': box, 'method': 'colored_ring_with_interior',
                              'explanation': 'Круглый оттиск: цветные чернила, замкнутый контур и элементы внутри. Подлинность не устанавливается.'})
    # Signature search is limited to a visible signature label; no guessed whole-page region.
    for line in lines:
        if 'подпис' not in line['text'].casefold():
            continue
        x1, y1, x2, y2 = line['bbox']
        label_words = [t for t in line.get('words', []) if 'подпис' in t['text'].casefold()]
        label_right = max(t['bbox'][2] for t in label_words) if label_words else x1 + min((x2-x1)*.4, w*.14)
        left = int(label_right + w*.005)
        top = max(0, int(y1 - h*.018))
        right = min(w, int(left + w*.35))
        bottom = min(h, int(y2 + h*.025))
        if right <= left or bottom <= top:
            continue
        crop = ink[top:bottom, left:right].copy()
        for sx1, sy1, sx2, sy2 in stamp_boxes:
            crop[max(0, sy1-top):max(0, sy2-top), max(0, sx1-left):max(0, sx2-left)] = 0
        count, _, stats, _ = cv2.connectedComponentsWithStats(crop)
        for x, y, bw, bh, area in stats[1:]:
            density = int(area) / max(int(bw)*int(bh), 1)
            if bw < w*.045 or bh < h*.009 or not 1.4 <= bw/max(bh,1) <= 12 or not .025 <= density <= .55:
                continue
            box = [int(left+x), int(top+y), int(left+x+bw), int(top+y+bh)]
            proposals.append({'kind': 'signature', 'value': True, 'score': .90,
                              'page': page_number, 'bbox': box, 'method': 'connected_ink_by_signature_label',
                              'explanation': 'Связный цветной штрих рядом с полем подписи. Это визуальный признак, не проверка личности или подлинности.'})
    return proposals


def apply_visual(fields, pages):
    for key in ('stamp', 'signature'):
        if key not in fields:
            continue
        marks = [m for page in pages for m in page.get('visual_marks', []) if m['kind'] == key]
        if not marks:
            fields[key]['visual_analysis'] = {'result': 'uncertain', 'explanation': 'Уверенных визуальных признаков не найдено. Это не доказывает отсутствие: чёрные чернила, слабый оттиск или другое расположение требуют проверки.'}
            continue
        best = max(marks, key=lambda m: m['score'])
        f = fields[key]
        # Proposals remain reviewable: a drawn circle/logo can resemble a seal.
        f.update(value=True, status='needs_review', source='visual_heuristic', confidence=None,
                 evidence=[{'page': m['page'], 'bbox': m['bbox'], 'confidence': None, 'text': m['explanation']} for m in marks],
                 visual_analysis={'result': 'detected', 'score': best['score'], 'explanation': best['explanation']})
