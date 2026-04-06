import os
from datetime import datetime, time, timezone

import requests

BASE = "https://api.openai.com/v1"


class OpenAIKeyMissingError(Exception):
    pass


class RateLimitedError(Exception):
    def __init__(self, retry_after: int | None = None):
        self.retry_after = retry_after
        msg = "OpenAI usage endpoint is rate-limited."
        if retry_after:
            msg += f" Retry after {retry_after}s."
        super().__init__(msg)


def _keys() -> tuple[str | None, str | None]:
    """Return (project_key, admin_key). Either may be None."""
    return (
        os.environ.get("OPENAI_API_KEY") or None,
        os.environ.get("OPENAI_ADMIN_KEY") or None,
    )


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _today_midnight_utc() -> int:
    now = datetime.now(timezone.utc)
    return int(datetime.combine(now.date(), time.min, tzinfo=timezone.utc).timestamp())


def _days_ago_utc(days: int) -> int:
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    return int(datetime.combine((now - timedelta(days=days)).date(), time.min, tzinfo=timezone.utc).timestamp())


def _aggregate_usage(data: dict) -> dict:
    input_tokens = output_tokens = requests_count = 0
    for bucket in data.get("data", []):
        for result in bucket.get("results", []):
            input_tokens  += result.get("input_tokens", 0) or 0
            output_tokens += result.get("output_tokens", 0) or 0
            requests_count += result.get("num_model_requests", 0) or 0
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "requests": requests_count}


def _aggregate_cost(data: dict) -> float:
    total = 0.0
    for bucket in data.get("data", []):
        for result in bucket.get("results", []):
            amount = result.get("amount") or {}
            total += float(amount.get("value", 0) or 0)
    return total


def get_usage() -> dict:
    project_key, admin_key = _keys()

    if not project_key and not admin_key:
        raise OpenAIKeyMissingError(
            "No OpenAI key set. Add OPENAI_API_KEY (project key) and/or "
            "OPENAI_ADMIN_KEY (admin key) to your .env file."
        )

    now         = int(datetime.now(timezone.utc).timestamp())
    today       = _today_midnight_utc()
    month_start = _days_ago_utc(30)

    # ── Rate limits — project key only, via cheap inference probe ────────────
    # Rate limit headers are only returned on inference endpoints, not /v1/models.
    rate_limits = {"rpm": {}, "tpm": {}}
    if project_key:
        probe = requests.post(
            f"{BASE}/chat/completions",
            headers={**_headers(project_key), "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "."}],
                "max_tokens": 1,
            },
            timeout=15,
        )
        if probe.status_code == 429:
            retry = probe.headers.get("retry-after")
            raise RateLimitedError(int(retry) if retry else None)
        probe.raise_for_status()
        ph = probe.headers

        def _rl(h: str) -> int | None:
            v = ph.get(h)
            return int(v) if v and v.isdigit() else None

        rate_limits = {
            "rpm": {
                "limit":     _rl("x-ratelimit-limit-requests"),
                "remaining": _rl("x-ratelimit-remaining-requests"),
                "reset":     ph.get("x-ratelimit-reset-requests"),
            },
            "tpm": {
                "limit":     _rl("x-ratelimit-limit-tokens"),
                "remaining": _rl("x-ratelimit-remaining-tokens"),
                "reset":     ph.get("x-ratelimit-reset-tokens"),
            },
        }

    # ── Usage & costs — admin key only ────────────────────────────────────────
    usage_today_raw = usage_month_raw = {}
    cost_today = cost_month = None

    if admin_key:
        hdrs = _headers(admin_key)

        def _fetch_usage(start: int) -> dict:
            resp = requests.get(
                f"{BASE}/organization/usage/completions",
                headers=hdrs,
                params={"start_time": start, "end_time": now, "interval": "1d"},
                timeout=10,
            )
            if resp.status_code in (403, 404):
                return {}
            if resp.status_code == 429:
                retry = resp.headers.get("retry-after")
                raise RateLimitedError(int(retry) if retry else None)
            resp.raise_for_status()
            return resp.json()

        def _fetch_cost(start: int) -> float | None:
            resp = requests.get(
                f"{BASE}/organization/costs",
                headers=hdrs,
                params={"start_time": start, "end_time": now},
                timeout=10,
            )
            if resp.status_code in (400, 403, 404):
                return None
            if resp.status_code == 429:
                retry = resp.headers.get("retry-after")
                raise RateLimitedError(int(retry) if retry else None)
            resp.raise_for_status()
            return _aggregate_cost(resp.json())

        usage_today_raw = _fetch_usage(today)
        usage_month_raw = _fetch_usage(month_start)
        cost_today      = _fetch_cost(today)
        cost_month      = _fetch_cost(month_start)

    return {
        "rate_limits":  rate_limits,
        "usage_today":  _aggregate_usage(usage_today_raw),
        "usage_month":  _aggregate_usage(usage_month_raw),
        "cost_today":   cost_today,
        "cost_month":   cost_month,
        "_raw": {
            "usage_today": usage_today_raw,
            "usage_month": usage_month_raw,
        },
    }
