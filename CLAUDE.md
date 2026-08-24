# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Streamlit dashboard that displays real-time quota/usage data for AI subscriptions. Currently supports Claude.ai Pro/Max via the OAuth token Claude Code stores at `~/.claude/.credentials.json`.

## Running

Everything runs in Docker — no local Python env needed:

```bash
docker compose up -d            # start
docker compose up -d --build    # rebuild after code changes
docker compose logs -f          # tail logs
```

App listens on port `8501` inside the `private` external Docker network (no host port exposed).

## Architecture

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI — layout, caching (`ttl=300s`), error handling |
| `claude_usage.py` | Reads `~/.claude/.credentials.json`, calls `https://api.anthropic.com/api/oauth/usage` with `anthropic-beta: oauth-2025-04-20` header |
| `openai_usage.py` | Reads `OPENAI_API_KEY` env var, probes `/v1/models` for rate limit headers, fetches `/v1/organization/usage/completions` and `/v1/organization/costs` |

### API response shape (Claude)
```json
{
  "five_hour":  { "utilization": 0-100, "resets_at": "<iso>" },
  "seven_day":  { "utilization": 0-100, "resets_at": "<iso>" },
  "extra_usage": { "is_enabled": bool, "monthly_limit": int, "used_credits": int }
}
```
`monthly_limit` and `used_credits` are in cents (divide by 100 for dollars).

### API response shape (OpenAI)
```python
{
  "rate_limits": {
    "rpm": {"limit": int, "remaining": int, "reset": str},  # reset is "60s" / "1m30s" duration
    "tpm": {"limit": int, "remaining": int, "reset": str},
  },
  "usage_today":  {"input_tokens": int, "output_tokens": int, "requests": int},
  "usage_month":  {"input_tokens": int, "output_tokens": int, "requests": int},
  "cost_today":   float,  # USD
  "cost_month":   float,  # USD
}
```

### Environment variables
| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENAI_API_KEY` | Optional | Project key (`sk-proj-...`) — used for RPM/TPM rate limit probe via `/v1/models` |
| `OPENAI_ADMIN_KEY` | Optional | Admin key (`sk-admin-...`) — used for token usage and cost via `/v1/organization/*` |

Either or both can be set. Missing keys = those sections are silently omitted from the card.

Add to `.env` (gitignored) in project root.

### Adding a new provider
1. Create `<provider>_usage.py` with a `get_usage() -> dict` function and a `KeyMissingError` class
2. Add a `@st.cache_data(ttl=300)` fetch wrapper and `st.container(border=True)` block in `app.py`
3. Reuse `quota_row()`, `credits_row()`, or `info_row()` helpers

## Linting

```bash
docker compose run --rm dashboard ruff check .
docker compose run --rm dashboard ruff format .
```
