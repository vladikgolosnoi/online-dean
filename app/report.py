"""Self-contained, escaped HTML protocol suitable for viewing and printing."""
from datetime import datetime, timezone
from html import escape

FIELD_STATUS = {
    'found': ('Найдено', 'good'), 'confirmed': ('Подтверждено вручную', 'good'),
    'not_found': ('Не найдено', 'alert'), 'needs_review': ('Нужна сверка', 'review'),
    'conflict': ('Есть расхождение', 'alert'),
}
WORKFLOW_STATUS = {
    'ready_for_decision': 'Готов к рассмотрению', 'needs_completion': 'Нужно дополнить документ',
    'needs_review': 'Нужна ручная сверка', 'unclassified': 'Не определён тип документа',
}


def report_value(field):
    value = field.get('value')
    if value is None:
        return 'Не найдено' if field.get('status') == 'not_found' else 'Нужна ручная сверка'
    if isinstance(value, bool):
        return 'Есть' if value else 'Нет'
    return str(value)


def render_report(result):
    e = lambda value: escape(str(value))
    rows, ready = [], 0
    for field in result['fields'].values():
        status, tone = FIELD_STATUS.get(field.get('status'), ('Не определено', 'neutral'))
        ready += tone == 'good'
        value = report_value(field)
        if field.get('source') == 'visual_heuristic' and field.get('value') is True:
            value += ' · требуется подтверждение'
        source = '; '.join(f"стр. {item['page']}: {item['text']}" for item in field.get('evidence', [])) or 'Источник не определён'
        rows.append(f'<tr><th scope="row">{e(field["label"])}</th><td>{e(value)}</td><td><span class="tag {tone}">{e(status)}</span></td><td class="source">{e(source)}</td></tr>')
    answer = result.get('answer', {})
    citations = ''.join(f'<article class="citation"><b>§ {e(item["id"])} · {e(item["title"])}</b><p>{e(item["text"])}</p></article>' for item in answer.get('citations', [])) or '<p class="muted">Для этого ответа нет отдельной ссылки на пункт Положения.</p>'
    audit = ''.join(f'<li><b>{e(result["fields"].get(item["field"], {}).get("label", item["field"]))}</b>: {e(item.get("before") or "не найдено")} → {e(item.get("after") or "не найдено")}</li>' for item in result.get('audit', [])) or '<li>Ручные изменения не вносились.</li>'
    workflow = result.get('workflow', {})
    status = WORKFLOW_STATUS.get(workflow.get('status'), 'Предварительная проверка завершена')
    notice = ('<div class="notice warning"><b>Демонстрационные правила</b><span>Этот отчёт не является решением деканата.</span></div>' if result['rules'].get('demo') else '<div class="notice"><b>Предварительная проверка</b><span>Окончательное решение принимает сотрудник деканата.</span></div>')
    pages = len(result.get('ocr', {}).get('pages', []))
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Протокол проверки документа</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f7f3;color:#20372b;font:14px/1.55 Arial,sans-serif}}.page{{max-width:1080px;margin:32px auto;background:#fff;box-shadow:0 10px 30px #173c2c12}}header{{display:flex;justify-content:space-between;gap:24px;padding:30px 38px 25px;border-bottom:1px solid #dce8df}}.brand{{color:#4bab43;font-size:12px;font-weight:700;line-height:1.05}}.brand strong{{display:block;font-size:17px;letter-spacing:-.5px}}.eyebrow{{margin:18px 0 7px;color:#67806e;font-size:10px;font-weight:700;letter-spacing:.1em}}h1{{margin:0;font-size:29px;letter-spacing:-.8px}}.document-name{{margin:6px 0 0;color:#607167;font-size:14px}}.protocol-id{{color:#77857b;font-size:11px;text-align:right}}main{{padding:30px 38px 38px}}.notice{{display:flex;gap:13px;margin:0 0 22px;padding:13px 15px;border:1px solid #d7e7d8;border-left:4px solid #50b848;background:#f5faf5;font-size:12px}}.notice b,.notice span{{display:block}}.notice span{{color:#64746a}}.notice.warning{{border-color:#eedcbb;border-left-color:#bd8b37;background:#fffaf1}}.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:0 0 30px}}.summary article{{padding:14px;border:1px solid #e0e9e1;background:#fcfefc}}.summary span{{display:block;color:#7c897f;font-size:10px;text-transform:uppercase;letter-spacing:.08em}}.summary b{{display:block;margin-top:6px;color:#244b34;font-size:14px}}section{{margin-top:28px}}h2{{margin:0 0 12px;font-size:18px;letter-spacing:-.25px}}.answer{{padding:18px 20px;border-left:4px solid #50b848;background:#f6fbf5}}.question{{margin:0 0 9px;color:#607168;font-size:12px}}.text{{margin:0;font-size:15px;line-height:1.65}}.citations{{display:grid;gap:8px;margin-top:12px}}.citation{{padding:11px 13px;border:1px solid #e0e9e1;background:#fff}}.citation b{{color:#397344;font-size:12px}}.citation p{{margin:4px 0 0;color:#65766b;font-size:12px}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:11px 10px;border:1px solid #dce6dd;text-align:left;vertical-align:top;overflow-wrap:anywhere}}thead th{{background:#edf4ea;color:#3b5845;font-size:10px;text-transform:uppercase;letter-spacing:.06em}}tbody th{{width:17%;font-weight:700;color:#294c37;background:#fbfdfb}}.source{{width:34%;color:#617268}}.tag{{display:inline-block;padding:4px 7px;border-radius:10px;font-size:10px;font-weight:700;white-space:nowrap}}.tag.good{{background:#e5f3e2;color:#347637}}.tag.review{{background:#fff1d5;color:#916b20}}.tag.alert{{background:#fbe9e2;color:#9b4c2b}}.tag.neutral{{background:#edf0ed;color:#607066}}.history{{margin:0;padding-left:19px;color:#637369;font-size:12px}}.history li{{margin:5px 0}}.repro{{display:grid;grid-template-columns:1fr 1fr;gap:10px;color:#6b796f;font-size:11px}}.repro div{{padding:11px;background:#f8faf8;overflow-wrap:anywhere}}code{{font:10px/1.45 Consolas,monospace;color:#526259}}footer{{margin-top:30px;padding-top:16px;border-top:1px solid #e2e9e3;color:#7a877e;font-size:10px}}.muted{{color:#758279;font-size:12px}}@media(max-width:700px){{.page{{margin:0}}header,main{{padding:24px 20px}}header{{display:block}}.protocol-id{{margin-top:14px;text-align:left}}.summary{{grid-template-columns:1fr 1fr}}.repro{{grid-template-columns:1fr}}.source{{min-width:180px}}}}@media print{{@page{{margin:13mm}}body{{background:#fff;font-size:11px}}.page{{max-width:none;margin:0;box-shadow:none}}header{{padding:0 0 16px}}main{{padding:20px 0 0}}section,article,tr{{break-inside:avoid}}.summary article{{padding:9px}}}}
</style></head><body><div class="page"><header><div><div class="brand">БАНК <strong>ЦЕНТР-ИНВЕСТ</strong></div><p class="eyebrow">ОНЛАЙН-ДЕКАНАТ · ПРОТОКОЛ ПРЕДВАРИТЕЛЬНОЙ ПРОВЕРКИ</p><h1>{e(result['type_label'])}</h1><p class="document-name">{e(result['filename'])}</p></div><div class="protocol-id">Идентификатор проверки<br><code>{e(result.get('id', '—'))}</code><br><br>Сформировано<br>{e(datetime.now(timezone.utc).strftime('%d.%m.%Y, %H:%M UTC'))}</div></header><main>{notice}<div class="summary"><article><span>Статус</span><b>{e(status)}</b></article><article><span>Реквизиты</span><b>{ready} из {len(result['fields'])} найдены</b></article><article><span>Страницы</span><b>{pages or '—'}</b></article><article><span>Обработка</span><b>Локальный контур</b></article></div><section><h2>Ответ на вопрос</h2><div class="answer"><p class="question">{e(result['question'])}</p><p class="text">{e(answer.get('text', 'Ответ не сформирован.'))}</p></div><div class="citations">{citations}</div></section><section><h2>Реквизиты и источники</h2><table><thead><tr><th>Поле</th><th>Значение</th><th>Статус</th><th>Источник в документе</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section><section><h2>Ручные уточнения</h2><ul class="history">{audit}</ul></section><section><h2>Воспроизводимость проверки</h2><div class="repro"><div>Правила<br><b>{e(result['rules']['title'])} · {e(result['rules']['version'])}</b></div><div>SHA-256 документа<br><code>{e(result['sha256'])}</code></div><div>SHA-256 правил<br><code>{e(answer.get('rules_sha256', '—'))}</code></div><div>Граница ответственности<br>Подпись и печать оцениваются по визуальным признакам; подлинность не устанавливается.</div></div></section><footer>Протокол сформирован сервисом «Онлайн-деканат». Он фиксирует результат предварительной проверки и не заменяет решение уполномоченного сотрудника.</footer></main></div></body></html>'''
