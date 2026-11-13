# AI Quota Dashboard

A compact Streamlit dashboard that displays usage and quota data across Claude, ChatGPT, OpenRouter, and GitHub Copilot accounts.

While open, the dashboard automatically refreshes usage data every 10 seconds. Use **↻ Refresh** to fetch an update immediately.

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

### Production deployment with GitHub Actions

Pushing a new Git tag builds and deploys that tagged commit to production on the repository's self-hosted runner. Branch pushes and pull requests do not deploy. For example, after committing and pushing the changes to `main`:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The tag must point to a commit containing the tag-based workflow. Pushing an existing tag again or deleting a tag does not deploy. The project calls the independent [Server Deploy Actions](https://github.com/ftechhelp/server-deploy-actions) reusable workflow, pinned to a reviewed commit. Its host engine has no Murphy dependency.

The engine plans changes, verifies approvals and drift, builds and tests images, publishes unique Docker Hub tags, deploys immutable digests, checks ZFS capacity and boot mounts, verifies migrations, retains recovery snapshots, manages NPM proxy/TLS settings, and records release history. Failed application activation restores the exact prior Compose artifact and protected environment snapshot. Persistent data is never rolled back automatically.

The [project manifest](deploy/app.json) declares `/data` as database storage because it contains SQLite. The engine's intended destination is `/SSD/databases/ai-quota-dashboard/dashboard/data`; adoption/migration of the existing HDD data requires explicit approval before the first release. Original data remains at `/HDD/docker-data/apps/ai-quota-dashboard/dashboard/data` for recovery. The engine's production environment file is `/etc/server-deploy/apps/ai-quota-dashboard.env`; credentials and policy remain protected on the host. Development keeps its own Compose project and volume.

Use **Actions → Production maintenance → Run workflow** for inspection, adoption, environment recreation, rollback to a saved release, recovery, and migration acceptance. `plan_only` defaults to true. Read the generated plan, then enter its `id` in `plan_id` and run with `plan_only: false` and the listed approval categories. Plans expire after 15 minutes and reject configuration/source/runtime drift. Initial reconciliation needs `deployment,downtime,adoption,data-migration`; ordinary subsequent tagged releases need only deployment and downtime. Rollback requires a saved release ID and downtime approval.

The repository is public. Only trusted users should be able to change workflows, create release tags, or run jobs on this deployment runner; see [GitHub's self-hosted runner security guidance](https://docs.github.com/en/actions/reference/security/secure-use#self-hosted-runners). The runner invokes a root-owned deployment engine through a restricted sudo entry. Keep pull request workflows off this runner.

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

## Pace and history

Each quota bar has a tick showing how much of the window has passed. A bar ahead of its tick is burning faster than the window allows: it turns amber and shows when it will run out at the current rate. It turns red once the limit is hit.

A background collector (started with the app) records every provider's numbers about every 10 minutes to `/data/history.db`, even when the dashboard isn't open. Each card's **History** section charts the last 7 days (OpenRouter: month-to-date spend). History is kept for 90 days.

## OpenRouter setup

On first load the OpenRouter card asks you to paste a key. It's checked against OpenRouter, then saved to `/data/openrouter_key.json` (in the `chatgpt_data` volume). Use **change key** on the card to replace it.

- **Management key** ([settings → management keys](https://openrouter.ai/settings/management-keys)): spend this UTC month summed across all keys in the default workspace, plus the most recently used model.
- **Regular API key**: spend this UTC month for that key only. OpenRouter only exposes model activity to management keys, so the last model isn't shown.

## GitHub Copilot setup

Create a [classic GitHub personal access token](https://github.com/settings/tokens) for the account with Copilot access, and paste it into the GitHub Copilot card. The dashboard verifies the token before saving it to `/data/copilot_token.json` in the persistent `chatgpt_data` volume. Use **change token** to replace it.

The card shows the quota percentages, reset dates, and unlimited allowances GitHub returns for the account, with seven days of history. GitHub's internal Copilot account endpoint is also used by VS Code, but is undocumented and can change. The available quotas depend on the plan; some organization-managed accounts do not expose usable quota details. This card does not show organization-wide billing usage.

## Project structure

```
app.py              # Streamlit UI
claude_usage.py     # Anthropic OAuth usage API client
openai_usage.py     # OpenAI usage API client
openrouter_usage.py # OpenRouter spend + last-used model
copilot_usage.py    # GitHub Copilot account quotas
history.py          # SQLite usage history
collector.py        # Background history sampler
Dockerfile
docker-compose.yml
pyproject.toml
.env                # Not committed — holds OPENAI_API_KEY etc.
```

## Adding providers

Each provider is a `st.container(border=True)` block in `app.py`. The helper functions `quota_row()`, `credits_row()`, and `info_row()` render compact rows and can be reused for any provider.
