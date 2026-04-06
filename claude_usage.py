import json
import time
from pathlib import Path

import requests

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


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


def load_credentials() -> dict:
    if not CREDENTIALS_PATH.exists():
        raise CredentialsNotFoundError(
            f"Credentials file not found at {CREDENTIALS_PATH}. "
            "Run `claude` once to authenticate."
        )
    with CREDENTIALS_PATH.open() as f:
        data = json.load(f)
    oauth = data.get("claudeAiOauth")
    if not oauth:
        raise CredentialsNotFoundError(
            "No claudeAiOauth entry in credentials file. "
            "Run `claude` to authenticate."
        )
    return oauth


def get_usage() -> dict:
    oauth = load_credentials()

    expires_at = oauth.get("expiresAt", 0)
    # expiresAt may be in seconds or milliseconds
    if expires_at > 1e12:
        expires_at /= 1000
    if expires_at < time.time():
        raise TokenExpiredError(
            "OAuth token has expired. Run `claude` in your terminal to refresh it."
        )

    access_token = oauth["accessToken"]
    resp = requests.get(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "anthropic-beta": "oauth-2025-04-20",
        },
        timeout=10,
    )
    if resp.status_code == 429:
        retry_after = resp.headers.get("retry-after") or resp.headers.get("x-ratelimit-reset-after")
        raise RateLimitedError(int(retry_after) if retry_after else None)
    resp.raise_for_status()
    result = resp.json()
    result["_meta"] = {
        "subscriptionType": oauth.get("subscriptionType", "unknown"),
        "rateLimitTier": oauth.get("rateLimitTier", "unknown"),
    }
    return result
