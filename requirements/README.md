# Зависимости Logos

Профили разбивают тяжёлые опции (ML, браузер, UI) от ядра на стандартной библиотеке.

## Файлы

| Файл | Назначение |
|------|------------|
| `kernel-min.txt` | Ядро без ML: `memory`, `boot`, этика, цели, планировщик и т.д. — **без pip-пакетов** (только Python 3.10+). |
| `kernel-ml.txt` | Эмбеддинги для `kernel/external.py`, `kernel/journal.py` (`numpy`, `torch`, `transformers`). |
| `kernel-browser.txt` | `playwright` для `kernel/browser.py`. После установки: `playwright install`. |
| `kernel-dashboard.txt` | `streamlit` для `dashboard/app.py`. |
| `cli.txt` | Нативный CLI: минимум ядра + HTTP-клиент (`httpx`). |
| `dev.txt` | Тесты и линтинг: `pytest`, `ruff`, `mypy`. |
| `full-local.txt` | Агрегат: `dev` + `kernel-ml` + браузер + дашборд + `cli`. |

## Примеры установки

```bash
# Только ядро без сторонних пакетов (ничего ставить не нужно)
pip install -r requirements/kernel-min.txt

# Ядро + ML (векторный поиск журнала / external memory)
pip install -r requirements/kernel-ml.txt

# Разработка ядра + ML + тесты
pip install -r requirements/dev.txt -r requirements/kernel-ml.txt

# Всё опциональное для локальной машины одной командой
pip install -r requirements/full-local.txt
```

Версии заданы **нижними границами** для совместимости; для воспроизводимых билдов можно сделать `pip freeze > requirements-lock.txt` в вашем окружении.
