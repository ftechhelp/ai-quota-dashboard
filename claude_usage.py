import json
import time
from pathlib import Path

import requests

import claude_auth

USAGE_URL  = "https://api.anthropic.com/api/oauth/usage"
CACHE_FILE = Path("/data/claude_usage_cache.json")

# Default cooldown (seconds) to wait before re-hitting the endpoint after a 429
# that didn't include a retry-after header.
DEFAULT_COOLDOWN = 300


class TokenExpiredError(Exception):
    pass


class CredentialsNotFoundError(Exception):
    pass


class RateLimitedError(Exception):
    def __init__(self, retry_after: int | None = None):
        self.retry_after = retry_after
        msg = "Usage endpoint is rate-limited."
        if retry_after:
            msg += f" Retry after {retry_after}s."
        super().__init__(msg)


def _load_cache() -> dict | None:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            return None
    return None


def _save_cache(result: dict, cooldown_until: float = 0.0) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({
            "fetched_at":     time.time(),
            "cooldown_until": cooldown_until,
            "result":         result,
        }))
    except Exception:
        pass


def _mark_cooldown(cooldown_until: float) -> None:
    """Persist a cooldown timestamp without overwriting the cached result."""
    cache = _load_cache() or {}
    cache["cooldown_until"] = cooldown_until
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache))
    except Exception:
        pass


def get_usage() -> dict:
    # If we're within a rate-limit cooldown, serve stale data instead of
    # re-hitting the endpoint (which would just keep us rate-limited).
    cache = _load_cache()
    if cache and time.time() < cache.get("cooldown_until", 0):
        if cache.get("result"):
            stale = dict(cache["result"])
            meta = dict(stale.get("_meta") or {})
            meta["stale"] = True
            meta["fetched_at"] = cache.get("fetched_at")
            stale["_meta"] = meta
            return stale
        remaining = int(cache["cooldown_until"] - time.time())
        raise RateLimitedError(max(remaining, 1))

    tokens = claude_auth.load_tokens()
    if not tokens:
        raise CredentialsNotFoundError("not_authenticated")

    if tokens.get("expires_at", 0) < time.time() + 300:
        if not tokens.get("refresh_token"):
            raise CredentialsNotFoundError("not_authenticated")
        tokens = claude_auth.refresh_tokens(tokens)

    def _request(tok: dict) -> requests.Response:
        return requests.get(
            USAGE_URL,
            headers={
                "Authorization":  f"Bearer {tok['access_token']}",
                "anthropic-beta": "oauth-2025-04-20",
            },
            timeout=10,
        )

    resp = _request(tokens)

    # Access token may be rejected even though expires_at hasn't passed
    # (revoked/stale). Refresh once and retry before giving up.
    if resp.status_code == 401 and tokens.get("refresh_token"):
        try:
            tokens = claude_auth.refresh_tokens(tokens)
        except requests.HTTPError:
            raise TokenExpiredError("token_expired")
        resp = _request(tokens)

    if resp.status_code == 401:
        raise TokenExpiredError("token_expired")
    if resp.status_code == 429:
        retry_after = resp.headers.get("retry-after") or resp.headers.get("x-ratelimit-reset-after")
        retry_after = int(retry_after) if retry_after else None
        _mark_cooldown(time.time() + (retry_after or DEFAULT_COOLDOWN))
        # Prefer serving stale data over erroring out.
        if cache and cache.get("result"):
            stale = dict(cache["result"])
            meta = dict(stale.get("_meta") or {})
            meta["stale"] = True
            meta["fetched_at"] = cache.get("fetched_at")
            stale["_meta"] = meta
            return stale
        raise RateLimitedError(retry_after)
    resp.raise_for_status()
    result = resp.json()
    result["_meta"] = {}
    _save_cache(result)
    return result
