[LEGEND]
SKILL = The Browser MCP effective-use skill definition.
SKILL_PATH = The Codex skills directory path for installation.
INSTALL = Copy the skill file to the Codex skills directory.
SKILL_YAML = The YAML front-matter definition required by Codex.
USE_CASES = When to use this skill in agent runs.

[CONTENT]
This doc packages the [SKILL] so it can be versioned in the repo while keeping Codex's loader format intact.

## [INSTALL]
Copy the YAML below into the Codex skills directory at [SKILL_PATH]:
```
[SKILL_PATH]=/home/amir/.codex/skills/browser-mcp-effective/SKILL.md
```

## [SKILL_YAML]
```
---
name: browser-mcp-effective
description: >
  Эффективное использование Browser MCP: минимальное число вызовов, устойчивые
  multi-step сценарии (run/flow/macros/runbooks), работа со сложными сайтами,
  вкладками, диалогами, загрузками и фреймами.
---

# Browser MCP — Effective Use

Цель: сделать длинные последовательности действий устойчивыми и дешёвыми по контексту.
Фокус: 1–3 вызова на задачу, fail-closed, минимальный шум.

## Golden path (по умолчанию)
1) `run(actions=[...])` вместо десятков отдельных вызовов.
2) Если нужно понять структуру: `page(detail="map")` → `run(...)`.
3) Для повторяемых сценариев: `run(..., record_memory_key="runbook_x")` → `runbook(action="run")`.

## Decision tree (минимум вызовов)
- Простая задача (1–2 шага) → `run(actions=[...])`.
- Сложная страница → `page(detail="map")` → `run(...)`.
- Canvas/нестандартные UI (Miro/Figma и т.п.) → `app(...)` или `run(actions=[{"tool":"app",...}])`.
- Многоразовый сценарий → запись runbook → запуск через `runbook`.
- Нужна только выжимка контента → `auto_expand_scroll_extract` в одном `run(...)`.

## Extract decision tree (быстрое решение)
- Если неясно что извлекать → `extract.content_type="overview"` (получить подсказки).
- Длинный текст/статья → `content_type="main"` (лимит 8–12).
- Таблицы/данные → `content_type="table"` (затем при необходимости `table_index=N`).
- Листинги/ленты → `content_type="links"` (лимит 12–30, больше `scroll.max_iters`).
- Если видишь “There was an error while loading” → включи `retry_on_error`.

## Стратегия устойчивости (встроенная)
- Вкладки: ставь `auto_tab=true` на click/type/form, если ожидаешь новую вкладку.
- Диалоги: `auto_dialog="dismiss"` для read-ish шагов.
- Стабильность локаторов: `auto_affordances=true` (по умолчанию).

## One-call extract pack (runbooks)
Article:
```
runbook(action="save", key="runbook_extract_article", steps=[
  {"macro": {"name": "auto_expand_scroll_extract", "args": {
    "url": "{{param:url}}",
    "expand": true,
    "scroll": {"max_iters": 8, "stop_on_url_change": true},
    "extract": {"content_type": "main", "limit": 60}
  }}}
])
```

Tables (list + table_index):
```
runbook(action="save", key="runbook_extract_table_index", steps=[
  {"macro": {"name": "auto_expand_scroll_extract", "args": {
    "url": "{{param:url}}",
    "expand": true,
    "scroll": {"max_iters": 10, "stop_on_url_change": true},
    "extract": {"content_type": "table", "limit": 12}
  }}},
  {"extract_content": {"content_type": "table", "table_index": "{{param:table_index}}"}}
])
```

Listings with pagination (bounded):
```
runbook(action="save", key="runbook_extract_listings_paginated", steps=[
  {"navigate": {"url": "{{param:url}}"}},
  {"repeat": {"max_iters": 6, "steps": [
    {"macro": {"name": "paginate_next", "args": {"next_text": "{{param:next_text}}"}}},
    {"extract_content": {"content_type": "links", "limit": 80}}
  ]}}
])
```

## Login runbook (sanitized recorder + anti-flakiness)
```
run(actions=[
  {"navigate": {"url": "{{param:url}}"}},
  {"macro": {"name": "login_basic", "args": {
    "username": "{{param:username}}",
    "password": "{{mem:pwd}}"
  }}}
], record_memory_key="runbook_login", record_mode="sanitized",
   auto_dialog="auto", auto_tab=true, auto_affordances=true, report="none")
```
```

## [USE_CASES]
- Длинные цепочки действий, где важна минимальная шумность и устойчивость.
- Повторяемые сценарии для runbook-переиспользования.
- Сложные сайты: SPA, ленивые загрузки, вкладки, диалоги, пагинация.
