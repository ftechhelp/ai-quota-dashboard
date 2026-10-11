#!/usr/bin/env python3
"""Background sampler that keeps usage history filling while the dashboard is closed.

Started next to Streamlit by the Dockerfile CMD. Each provider is sampled at most
once per SAMPLE_INTERVAL_S: if the dashboard recorded a sample more recently, the
collector skips that provider, so having the page open doesn't double the API calls.

The dashboard fetches through fetch() as well, so both paths record the same metrics.
"""

import time

import chatgpt_usage
import claude_usage
import history
import openrouter_usage

SAMPLE_INTERVAL_S = 600
TICK_S            = 60


def _claude_metrics(data: dict) -> dict:
    if (data.get("_meta") or {}).get("stale"):
        return {}  # cached copy served during a rate-limit cooldown, already recorded
    extra = data.get("extra_usage") or {}
    return {
        "5h":      (data.get("five_hour") or {}).get("utilization"),
        "7d":      (data.get("seven_day") or {}).get("utilization"),
        "credits": (extra.get("used_credits") or 0) / 100 if extra.get("is_enabled") else None,
    }


def _chatgpt_metrics(data: dict) -> dict:
    cred = data.get("credits") or {}
    try:
        balance = None if cred.get("unlimited") else float(cred.get("balance"))
    except (TypeError, ValueError):
        balance = None
    return {
        "5h":          (data.get("five_hour") or {}).get("utilization"),
        "7d":          (data.get("seven_day") or {}).get("utilization"),
        "code_review": (data.get("code_review") or {}).get("utilization"),
        "credits":     balance,
    }


def _openrouter_metrics(data: dict) -> dict:
    return {"spend_month": data.get("spend_month")}


PROVIDERS = {
    "claude":     (claude_usage, _claude_metrics),
    "chatgpt":    (chatgpt_usage, _chatgpt_metrics),
    "openrouter": (openrouter_usage, _openrouter_metrics),
}


def fetch(provider: str) -> dict:
    """Fetch a provider's usage and record a history sample."""
    module, metrics = PROVIDERS[provider]
    with history.fetch_lock(provider):
        data = module.get_usage()
    history.record(provider, metrics(data))
    return data


def main() -> None:
    last_attempt: dict[str, float] = {}
    last_error: dict[str, str] = {}
    while True:
        now = time.time()
        for provider in PROVIDERS:
            latest = max(history.last_ts(provider) or 0, last_attempt.get(provider, 0))
            if now - latest < SAMPLE_INTERVAL_S:
                continue
            last_attempt[provider] = now
            try:
                fetch(provider)
                last_error.pop(provider, None)
            except Exception as e:
                # Log each distinct failure once (e.g. a provider that isn't connected)
                msg = f"{type(e).__name__}: {e}"
                if last_error.get(provider) != msg:
                    print(f"collector: {provider}: {msg}", flush=True)
                    last_error[provider] = msg
        time.sleep(TICK_S)


if __name__ == "__main__":
    main()
