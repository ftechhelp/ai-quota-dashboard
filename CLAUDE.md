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

### API response shape (Claude)
```json
{
  "five_hour":  { "utilization": 0-100, "resets_at": "<iso>" },
  "seven_day":  { "utilization": 0-100, "resets_at": "<iso>" },
  "extra_usage": { "is_enabled": bool, "monthly_limit": int, "used_credits": int }
}
```
`monthly_limit` and `used_credits` are in cents (divide by 100 for dollars).

### Adding a new provider
1. Create `<provider>_usage.py` with a `get_usage() -> dict` function
2. Add a `st.container(border=True)` block in `app.py` using the existing `quota_row()` / `credits_row()` helpers

## Linting

```bash
docker compose run --rm dashboard ruff check .
docker compose run --rm dashboard ruff format .
```
