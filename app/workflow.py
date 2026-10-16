"""Turn verification facts into a conservative next action for a dean's office."""


def route(document_type, answer, fields):
    if not document_type:
        return {'status': 'unclassified', 'title': 'Определите тип документа',
                'summary': 'Без типа документа нельзя применить схему проверки и правила.',
                'reasons': ['Тип документа не определён.'],
                'actions': ['Выберите тип документа вручную и повторите проверку.']}

    checks = answer.get('checks', [])
    missing = [check['label'] for check in checks if check['status'] == 'missing']
    invalid = [check['label'] for check in checks if check['status'] == 'invalid']
    review = [check['label'] for check in checks if check['status'] == 'review']
    visual_review = [field['label'] for field in fields.values()
                     if field.get('kind') == 'visual' and field.get('status') not in {'found', 'confirmed'}]
    if missing or invalid:
        reasons = (['Не найдены: ' + ', '.join(missing) + '.'] if missing else [])
        reasons += (['Требуют исправления: ' + ', '.join(invalid) + '.'] if invalid else [])
        return {'status': 'needs_completion', 'title': 'Запросить дополнение',
                'summary': 'Документ не готов к передаче на итоговое решение.', 'reasons': reasons,
                'actions': ['Запросите недостающие или исправленные сведения.', 'После получения новой версии запустите проверку повторно.']}
    if review or visual_review:
        reasons = ['Поля для визуальной сверки: ' + ', '.join(dict.fromkeys(review + visual_review)) + '.']
        return {'status': 'needs_review', 'title': 'Провести ручную сверку',
                'summary': 'Автоматическая проверка не выявила критической ошибки, но часть сведений требует подтверждения.',
                'reasons': reasons,
                'actions': ['Сверьте отмеченные поля с оригиналом.', 'Подтвердите или исправьте значение в карточке документа.']}
    return {'status': 'ready_for_decision', 'title': 'Передать на итоговое решение',
            'summary': 'По подключённым правилам обязательные сведения найдены. Окончательное решение остаётся за сотрудником.',
            'reasons': ['Обязательные проверки завершены без найденных расхождений.'],
            'actions': ['Проверьте оригинал документа при необходимости.', 'Зафиксируйте решение сотрудника в принятом в вузе процессе.']}
