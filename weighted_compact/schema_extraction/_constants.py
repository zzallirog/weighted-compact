"""schema_extraction — shared constants, prompts, model defaults.

Models default to local gemma3:4b for both extraction and judging.
Override with $WC_SCHEMA_EXTRACT_MODEL / $WC_SCHEMA_JUDGE_MODEL.
"""

from __future__ import annotations

import os

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")

EXTRACT_MODEL = os.environ.get("WC_SCHEMA_EXTRACT_MODEL", "gemma3:4b")
JUDGE_MODEL = os.environ.get("WC_SCHEMA_JUDGE_MODEL", "gemma3:4b")

MAX_CONTEXT_CHARS = int(os.environ.get("WC_SCHEMA_MAX_CONTEXT_CHARS", "16000"))
OLLAMA_TIMEOUT_S = int(os.environ.get("WC_SCHEMA_OLLAMA_TIMEOUT_S", "120"))

EXTRACT_PROMPT = """Ты извлекаешь правила (rules) из истории дебага и фиксов в инфраструктурном проекте. Правило = когда применять + что делать + чего НЕ делать.

Контент (выдержка из проектных заметок):
---
{context}
---

Извлеки ОДНО правило ровно в этом формате (строки на русском или английском, без markdown):
TRIGGER: <короткая фраза описывающая ситуацию когда применять>
RULE: <конкретное действие или конфиг которое решает>
ANTI: <типичная неверная попытка / что НЕ делать>

Если в контенте нет ясного правила — верни одну строку: NO_RULE"""

EXTRACT_PROMPT_GUIDED = """Ты извлекаешь правила (rules) из истории дебага. Правило = когда применять + что делать + чего НЕ делать.

В этом контексте есть несколько фиксов и обсуждений. Тебе нужно найти **одно конкретное правило**, которое отвечает на следующую ситуацию:

QUERY: {trigger}

Контент:
---
{context}
---

Найди правило в контенте, которое адресует именно QUERY (не первое попавшееся, не самое заметное — именно то, что про QUERY). Верни ровно в этом формате (на том же языке что QUERY):
TRIGGER: <короткая фраза описывающая когда применять — должна совпадать с QUERY по смыслу>
RULE: <конкретное действие или конфиг которое решает QUERY>
ANTI: <типичная неверная попытка по этому QUERY / что НЕ делать>

Если в контенте нет правила про QUERY — верни одну строку: NO_RULE
Не выдавай несколько правил. Не выдавай правило про другую ситуацию."""

JUDGE_PROMPT = """Сравни два правила. Описывают ли они одну и ту же ситуацию с одним и тем же решением?

EXPECTED:
trigger: {expected_trigger}
rule: {expected_rule}
anti: {expected_anti}

GENERATED:
{generated}

Ответь ОДНОЙ строкой и одним словом:
- MATCH если описывают одну ситуацию и решение в той же сути
- NEAR если ситуация та же но решение сформулировано иначе или не полное
- MISMATCH если разные ситуации или решения

Только одно слово на ответ."""

BANK_BUILD_PROMPT = """Ты помогаешь собрать case-bank для regression-testing memory retrieval.

Прочти эту заметку из персональной памяти оператора и реши: содержит ли она устойчивое правило/фикс/решение?

Заметка:
---
{content}
---

Если правило ЕСТЬ — верни ровно эти 4 строки:
TRIGGER: <короткая фраза, когда применять>
RULE: <что делать>
ANTI: <чего НЕ делать>
STABLE_SINCE: <дата YYYY-MM-DD если есть в заметке "DONE 2026-X-Y" или "SHIPPED" / null если нет>

Если правила нет (заметка про план, обсуждение, незакрытый дефект) — верни одну строку: NO_RULE"""

CANDIDATE_PATTERNS = [
    r"\bDONE\s+\d{4}-\d{2}-\d{2}\b",
    r"\bSHIPPED\b",
    r"\bRESOLVED\b",
    r"\bACHIEVED\b",
    r"\bCUTOVER\s+(DONE|LIVE)\b",
    r"21\s+(дн|day)",
    r"стабиль",
    r"no-touch",
]

DATE_RE = r"(\d{4}-\d{2}-\d{2})"
