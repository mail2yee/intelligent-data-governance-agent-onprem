# Eval run log

Manually-appended record of `pytest evals/` runs (see `evals/test_chat_eval.py`
and `README.md`'s "Evals" section for what this actually measures and its
honest limitations - this log is a history of *scores*, not a claim that
higher is always better than the documented `PASS_RATE_FLOOR`).

Newest entries at the top. Append a new entry each time a run's result is
worth keeping (e.g. after a real change to `chat.py`/`wrenai_client.py`/the
judge or trial config) - not every ad-hoc local run.

---

## 2026-07-28

- Config: `DGO_EVAL_TRIALS=2`, judge model `qwen2.5:latest` (local Ollama,
  `http://localhost:11434`), app models: `LLM_MODEL=qwen2.5:latest`,
  `LLM_SQL_MODEL=llama3-groq-tool-use:8b`.
- Context: first real run of the eval suite, right after adding the
  `search_text` dual-script (Traditional/Simplified Chinese) column fix
  (see HANDOFF.md). Command: `DGO_EVAL_TRIALS=2 pytest evals/ -v -s`.
- Result: **6/6 golden queries passed** the (deliberately low) 0.3 pass-rate
  floor. All hard structural assertions held (matched products were always
  real catalog ids across every trial - no fabricated ids observed).

| Golden query | Pass rate | Metrics evaluated |
|---|---|---|
| `zh-capacity` | 0.83 | 6 |
| `zh-demand-orders` | 0.67 | 6 |
| `zh-move-forecast` | 0.50 | 6 |
| `zh-out-of-catalog-salary` | 1.00 | 2 |
| `en-capacity` | 1.00 | 6 |
| `en-out-of-catalog-weather` | 1.00 | 2 |

- Reading: the two out-of-catalog (zero-hallucination) queries and the
  English in-catalog query scored perfectly. The three Traditional-Chinese
  in-catalog queries scored lower (0.50-0.83) - consistent with, not a
  contradiction of, the keyword-specificity limitation already documented
  in HANDOFF.md ("客戶" and similarly generic extracted keywords matching
  more than one catalog row). Total run time ~4m50s for 6 queries x 2
  trials x up to 3 judge metrics each.
