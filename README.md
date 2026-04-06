# AI Quota Dashboard

A compact Streamlit dashboard that displays real-time usage and quota data across AI subscriptions. Currently supports **Claude.ai Pro/Max**.

## How it works

Claude Code stores an OAuth token at `~/.claude/.credentials.json` after you authenticate. The dashboard reads that token and calls Anthropic's internal usage endpoint (`/api/oauth/usage`) to fetch:

- **5-hour rolling window** — utilization % and reset time
- **7-day rolling window** — utilization % and reset time
- **Extra usage credits** — used vs. monthly credit limit (if enabled)

No separate API key or manual token entry needed.

## Running

```bash
docker compose up -d
```

The app runs on port `8501` inside the `private` Docker network (no ports exposed to the host). Proxy it through your reverse proxy of choice.

### Reverse proxy (Nginx example)

WebSocket proxying is required for Streamlit:

```nginx
location / {
    proxy_pass http://dashboard:8501;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

Traefik and Caddy handle WebSocket upgrades automatically.

### Rebuilding after code changes

```bash
docker compose up -d --build
```

## OpenAI setup

Create a `.env` file in the project root (gitignored):

```
OPENAI_API_KEY=sk-...
```

The OpenAI card shows:
- **RPM / TPM** — rate limit utilization from response headers (via a cheap `/v1/models` probe)
- **Tokens** — input/output token totals for today and the last 30 days
- **Cost** — USD spend for today and the last 30 days

If `OPENAI_API_KEY` is missing, the OpenAI card shows a config prompt and the Claude card still works normally.

## Project structure

```
app.py              # Streamlit UI
claude_usage.py     # Anthropic OAuth usage API client
openai_usage.py     # OpenAI usage API client
Dockerfile
docker-compose.yml
pyproject.toml
.env                # Not committed — holds OPENAI_API_KEY
```

## Adding providers

Each provider is a `st.container(border=True)` block in `app.py`. The helper functions `quota_row()`, `credits_row()`, and `info_row()` render compact rows and can be reused for any provider.
