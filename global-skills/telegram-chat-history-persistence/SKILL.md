---
name: telegram-chat-history-persistence
description: Design and implement context continuity for a Telegram → Claude gateway. Use when the bot loses cross-session context or when choosing between transcript injection, SQLite buffering, RAG, and MemPalace for chat history.
metadata:
  type: project
---

## When to Use

Invoke when:
- The Telegram bot fails to recall a message from a prior session
- Designing or revisiting how chat history is persisted and injected
- Evaluating trade-offs between history storage approaches

## Approaches (Evaluated)

| # | Approach | Pros | Cons |
|---|----------|------|------|
| 1 | Full transcript injection | Lossless, zero deps | Context window explodes |
| 2 | Sliding window / rolling buffer | Bounded tokens | Fails for anything outside the window |
| 3 | **LLM-summarized history** ✓ | Bounded, captures gist, handles long gaps | Slight losiness; one async LLM call per session |
| 4 | SQLite store | Queryable, durable, no external deps | Still needs retrieval strategy on top |
| 5 | RAG over chat history | Solves "10 hours ago" references | Needs embedding model (e.g. local ollama) |
| 6 | MemPalace | Zero new infra | Gateway shell can't call MCP directly; needs glue |
| 7 | Mem0 / Zep managed | Production-ready | Data leaves machine, external cost |
| 8 | Long-context model injection | No retrieval logic | Expensive, slow, still has a ceiling |

## Recommended Approach: LLM Summary + SQLite + Last-N Raw Turns

**Implementation steps:**

1. **Log every exchange** to a local JSONL file: `{timestamp, sender, text, session_id}`
2. **On session close**, run an async Claude call to summarize the session and write it to SQLite (`session_summaries` table: `session_id`, `closed_at`, `summary_text`)
3. **On session start**, the gateway shell script:
   - Queries SQLite for the last 2–3 session summaries
   - Appends the last N raw turns (e.g. 20 turns or 2 hours)
   - Injects both into the system prompt as "Recent Telegram context"
4. **MemPalace** receives only session summaries (not raw transcripts) — which is what it's actually good at

## Key Constraints

**Avoid storing raw transcripts in MemPalace** — circular disclosure risk: if the bot disclosed something it shouldn't have (commit hashes, tool names), storing it verbatim lets the bot retrieve and repeat the mistake with false confidence.

**Sanitize before injection** — strip or redact sensitive content (commit hashes, file paths, MCP tool names) from the last-N raw turns before they enter the system prompt. See [[feedback_telegram_disclosure]].

**Write path must be non-blocking** — if the JSONL write or SQLite insert hangs, it must not block the Telegram response. Run writes in a background thread or after-response hook.

## Related Skills and Memories

- `telegram-gateway-security-audit` — covers dedup bugs and disclosure-restriction prompt injection
- [[feedback_telegram_disclosure]] — never reveal OS/kernel/paths/git/email/MCP stack over Telegram
- [[project_telegram_purpose]] — approval channel, not a chat assistant; each message must be self-describing
