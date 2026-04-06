import time

import requests

import claude_auth

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


def get_usage() -> dict:
    tokens = claude_auth.load_tokens()
    if not tokens:
        raise CredentialsNotFoundError("not_authenticated")

    if tokens.get("expires_at", 0) < time.time() + 300:
        if not tokens.get("refresh_token"):
            raise CredentialsNotFoundError("not_authenticated")
        tokens = claude_auth.refresh_tokens(tokens)

    resp = requests.get(
        USAGE_URL,
        headers={
            "Authorization":  f"Bearer {tokens['access_token']}",
            "anthropic-beta": "oauth-2025-04-20",
        },
        timeout=10,
    )
    if resp.status_code == 429:
        retry_after = resp.headers.get("retry-after") or resp.headers.get("x-ratelimit-reset-after")
        raise RateLimitedError(int(retry_after) if retry_after else None)
    resp.raise_for_status()
    result = resp.json()
    result["_meta"] = {}
    return result
