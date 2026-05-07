# Гипотеза: Inline + purge + async (v5)

**ID:** exp_1778150783
**Дата:** 2026-05-07 13:46

## Формулировка
HTML+CSS+JS в одном файле, FontAwesome purge, dead CSS removal, Jivo/Metrika async

## Обоснование
Предыдущий эксперимент дал 29%. Остался 1% запас

## Метрики

## План
1. **measure_original** — Замерить оригинал (3 файла, gzip). Ожидание: 12720B
2. **inline_minify** — Встроить CSS+JS в HTML, минифицировать. Ожидание: HTML < 38KB raw
3. **purge_dead_css** — Удалить CSS для неиспользуемых на главной разделов. Ожидание: CSS < 11KB
4. **add_async** — Jivo, Metrika, LiveInternet — async/defer. Ожидание: Страница не блокируется
5. **measure_result** — Замерить gzip-размер. Ожидание: ≤ 8900B (30% reduction)
