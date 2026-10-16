$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) { throw 'Сначала создайте .venv и установите зависимости по README.' }
& '.\.venv\Scripts\python.exe' -m scripts.generate_samples
if ($LASTEXITCODE -ne 0) { throw 'Не удалось подготовить примеры.' }
& '.\.venv\Scripts\python.exe' -X utf8 -m scripts.doctor
if ($LASTEXITCODE -ne 0) { throw 'Проверка запуска не пройдена. Исправьте ошибки выше; инструкция в README.md.' }
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000
