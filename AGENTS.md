# Notes For Future Agents

## Commit policy
- **Авто-коммиты разрешены.** Делай коммит после каждого значимого изменения: новый модуль, фича, багфикс. Сообщение на русском или английском, формат: `session N: краткое описание`.

## Улучшения памяти Эйдоса из RESEARCH.md

- **Контекстные энграммы и pattern completion.**
  1. Биологический принцип: энграмма как распределенный ансамбль; CA3 pattern completion восстанавливает эпизод по частичному ключу.
  2. Сейчас в Logos: `EpisodicMemory` хранит `tags`, `summary`, `raw_text`, `linked_episodes`; `ExternalMemory.search()` умеет content-addressable retrieval только для внешних документов.
  3. Изменить: в `kernel/memory.py` расширить схему `episodes` полями `context_keys`, `project`, `task`, `outcome`, `tools`, `valid_until`; добавить `EpisodicMemory.link_related()` и `EpisodicMemory.recall_by_cues(cues, limit)`; в `Memory.record_episode()` автоматически извлекать ключи из `tags`, `summary`, `moral_context`; в `kernel/boot.py::boot_context()` подмешивать эпизоды не только по recency, но и по cue-match к текущему контексту.
  4. Сложность: **1 день**.

- **Интерливированный sleep replay вместо прохода по последним 1000 эпизодам.**
  1. Биологический принцип: NREM replay смешивает новые и старые похожие следы, снижая катастрофическую интерференцию; TMR усиливает следы по ключам.
  2. Сейчас в Logos: `Memory.sleep()` делает salience/compression и promotion в `SemanticMemory` по recency/tag frequency; replay старых похожих эпизодов нет.
  3. Изменить: в `kernel/memory.py::sleep()` перед шагом promotion добавить выборку `recent + related + high_salience + low_confidence`; реализовать helper `_select_replay_batch()`; использовать `EpisodicMemory.recall_by_cues()` для старых похожих эпизодов; в `SemanticMemory.store_principle()` учитывать несколько source ids и повышать confidence только при повторном подтверждении.
  4. Сложность: **1 день**.

- **Spaced retrieval и reconsolidation для семантических принципов.**
  1. Биологический принцип: spaced repetition и retrieval practice; при извлечении память реконсолидируется и может обновлять уверенность.
  2. Сейчас в Logos: `SemanticMemory.principles` имеет `confidence`, `created_at`, `updated_at`; `boot_context()` берет top-5 принципов с `confidence >= 0.7`, без расписания повторного извлечения.
  3. Изменить: в `SemanticMemory._init_db()` добавить `last_retrieved_at`, `retrieval_count`, `success_count`, `next_review_at`, `decay`; добавить методы `due_for_review()`, `record_retrieval(principle_id, success)`; в `Memory.respond()` после успешной верификации отмечать использованные принципы; в `Memory.sleep()` планировать reviews и понижать confidence у давно неиспользуемых неподтвержденных принципов.
  4. Сложность: **1 день**.

- **Адаптивное забывание с архивированием, а не только compression.**
  1. Биологический принцип: active/adaptive forgetting; забывание снижает шум и сохраняет гибкость, но редкие критичные ошибки держатся дольше.
  2. Сейчас в Logos: `evaluate_salience()` считает свежесть, длину, важные теги и ссылки; `compress_episode()` сжимает только низкозначимые длинные записи, но результат сейчас не записывается обратно в БД в `sleep()`.
  3. Изменить: в `EpisodicMemory` добавить `update_episode()` и поля `access_count`, `last_accessed_at`, `archived_at`, `forget_reason`; в `kernel/salience.py::evaluate_salience()` учесть успешное применение, ошибки, пользовательскую оценку, конфликт/устаревание; в `Memory.sleep()` сохранять `compressed`, архивировать низкополезный шум, удерживать эпизоды с тегами `ошибка`, `решение`, `архитектура`.
  4. Сложность: **1 день**.

- **Ограниченная рабочая память с chunking и attention slots.**
  1. Биологический принцип: рабочая память держит около 3-4 chunks; эксперты обходят лимит через chunking, а не через бесконечный буфер.
  2. Сейчас в Logos: `WorkingMemory` хранит неструктурированный JSON `events`; sleep запускается после `AUTO_SLEEP_THRESHOLD = 50`; `compress.summarize_working()` существует, но не используется.
  3. Изменить: в `WorkingMemory` добавить `attention_slots` с максимумом 4 активных chunks и метод `update_attention(event)`; использовать `kernel/compress.py::summarize_working()` перед `save()`/`sleep()`; в `kernel/boot.py::boot_context()` сначала показывать active slots, затем recent events; в `Memory.respond()` перед планированием передавать planner'у `recent_topics` из slots.
  4. Сложность: **1 день**.
