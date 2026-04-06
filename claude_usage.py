import json
import time
from pathlib import Path

import requests

import claude_auth

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
USAGE_URL        = "https://api.anthropic.com/api/oauth/usage"


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


def _load_from_credentials_file() -> tuple[str, dict]:
    """Load access token from ~/.claude/.credentials.json. Returns (token, meta)."""
    with CREDENTIALS_PATH.open() as f:
        data = json.load(f)
    oauth = data.get("claudeAiOauth", {})
    expires_at = oauth.get("expiresAt", 0)
    if expires_at > 1e12:
        expires_at /= 1000
    if expires_at < time.time():
        raise TokenExpiredError(
            "OAuth token has expired. Run `claude` in your terminal to refresh it."
        )
    return oauth["accessToken"], {
        "subscriptionType": oauth.get("subscriptionType", "unknown"),
        "rateLimitTier":    oauth.get("rateLimitTier", "unknown"),
    }


def _load_from_data_file() -> tuple[str, dict]:
    """Load access token from /data/claude_tokens.json, refreshing if needed."""
    tokens = claude_auth.load_tokens()
    if not tokens:
        raise CredentialsNotFoundError("not_authenticated")

    if tokens.get("expires_at", 0) < time.time() + 300:
        if not tokens.get("refresh_token"):
            raise CredentialsNotFoundError("not_authenticated")
        tokens = claude_auth.refresh_tokens(tokens)

    return tokens["access_token"], {"subscriptionType": "", "rateLimitTier": ""}


def get_access_token() -> tuple[str, dict]:
    """
    Returns (access_token, meta). Tries credentials file first, falls back
    to /data/claude_tokens.json.
    Raises CredentialsNotFoundError("not_authenticated") if neither exists.
    """
    if CREDENTIALS_PATH.exists():
        try:
            return _load_from_credentials_file()
        except (KeyError, TokenExpiredError):
            pass  # fall through to data file

    return _load_from_data_file()


def get_usage() -> dict:
    access_token, meta = get_access_token()

    resp = requests.get(
        USAGE_URL,
        headers={
            "Authorization":  f"Bearer {access_token}",
            "anthropic-beta": "oauth-2025-04-20",
        },
        timeout=10,
    )
    if resp.status_code == 429:
        retry_after = resp.headers.get("retry-after") or resp.headers.get("x-ratelimit-reset-after")
        raise RateLimitedError(int(retry_after) if retry_after else None)
    resp.raise_for_status()
    result = resp.json()
    result["_meta"] = meta
    return result
