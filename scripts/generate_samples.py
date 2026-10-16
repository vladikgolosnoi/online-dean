"""Generate openly labeled synthetic fixtures. No real student information."""
import json
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from app.config import ROOT

SAMPLES = {
    'study': {'type': 'study_certificate', 'title': 'СПРАВКА ОБ ОБУЧЕНИИ', 'fields': {
        'student_name': ('ФИО студента', 'Иванов Иван Иванович'),
        'university': ('Название вуза', 'Донской учебный университет'),
        'program': ('Направление подготовки', '09.03.01 Информатика'),
        'study_mode': ('Форма обучения', 'Очная'),
        'study_period': ('Период обучения', '01.09.2025 - 30.06.2026'),
        'document_number': ('Номер документа', '142/26')}, 'missing': ['issue_date']},
    'leave': {'type': 'academic_leave', 'title': 'ЗАЯВЛЕНИЕ НА АКАДЕМИЧЕСКИЙ ОТПУСК', 'fields': {
        'student_name': ('ФИО студента', 'Петрова Анна Сергеевна'),
        'group': ('Группа', 'ИС-201'), 'course': ('Курс', '2'),
        'reason': ('Причина отпуска', 'По семейным обстоятельствам'),
        'start_date': ('Дата начала отпуска', '01.11.2026'),
        'end_date': ('Дата окончания отпуска', '31.08.2027'),
        'application_date': ('Дата заявления', '14.10.2026')}, 'missing': []},
    'internship': {'type': 'internship_certificate', 'title': 'СПРАВКА О ПРАКТИКЕ', 'fields': {
        'student_name': ('ФИО студента', 'Смирнов Алексей Олегович'),
        'organization': ('Организация', 'ООО Учебные технологии'),
        'internship_period': ('Сроки практики', '01.07.2026 - 28.07.2026'),
        'supervisor': ('Руководитель практики', 'Соколова Елена Викторовна'),
        'grade': ('Оценка', 'Отлично'),
        'document_number': ('Номер документа', '78/26'),
        'issue_date': ('Дата выдачи', '30.07.2026')}, 'missing': []},
}


def font(size):
    candidates = [os.getenv('DEAN_FONT', ''), r'C:\Windows\Fonts\arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for path in candidates:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    raise RuntimeError('Install DejaVu Sans or set DEAN_FONT to a Cyrillic TTF font.')


def main():
    folder = ROOT / 'samples'
    folder.mkdir(exist_ok=True)
    expected = []
    for name, sample in SAMPLES.items():
        im = Image.new('RGB', (1654, 2100), 'white')
        draw = ImageDraw.Draw(im)
        draw.text((110, 95), 'УЧЕБНЫЙ ПРИМЕР · СИНТЕТИЧЕСКИЕ ДАННЫЕ', font=font(27), fill='#787878')
        draw.text((110, 175), 'ДОНСКОЙ УЧЕБНЫЙ УНИВЕРСИТЕТ', font=font(40), fill='#222222')
        draw.line((110, 250, 1540, 250), fill='#333333', width=2)
        draw.text((110, 320), sample['title'], font=font(40 if name != 'leave' else 33), fill='#181818')
        for i, (_, (label, value)) in enumerate(sample['fields'].items()):
            draw.text((110, 455 + i * 110), f'{label}: {value}', font=font(35), fill='#171717')
        y = 455 + len(sample['fields']) * 110 + 100
        draw.text((110, y), 'Подпись: __________________', font=font(32), fill='#222222')
        draw.line([(315,y+27),(340,y-15),(333,y+28),(360,y+10),(379,y+27),(402,y+2),(425,y+16),(450,y-10)], fill='#2e4278', width=3)
        if name != 'leave':
            draw.ellipse((1050, y - 50, 1360, y + 260), outline='#547eae', width=6)
            draw.ellipse((1070, y - 30, 1340, y + 240), outline='#547eae', width=2)
            draw.text((1105, y + 40), 'ОБРАЗЕЦ', font=font(32), fill='#547eae')
            draw.text((1124, y + 90), 'ПЕЧАТИ', font=font(30), fill='#547eae')
        draw.text((110, 1970), 'Вымышленный документ. Не имеет юридической силы.', font=font(25), fill='#888888')
        im.save(folder / f'{name}.png')
        expected.append({'id': name, 'file': f'{name}.png', 'document_type': sample['type'],
                         'fields': {key: value for key, (_, value) in sample['fields'].items()}, 'missing': sample['missing']})
    (folder / 'expected.json').write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding='utf-8')
    # Controlled robustness fixture: same source, 20-degree tilt and reduced resolution.
    with Image.open(folder / 'study.png') as source:
        source.resize((1103, 1400)).rotate(20, expand=True, fillcolor='white').save(folder / 'study_tilt20.png')
    print('Created 3 synthetic documents and 1 tilted variant in samples/.')


if __name__ == '__main__':
    main()
