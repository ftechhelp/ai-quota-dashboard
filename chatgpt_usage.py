import json
import time
from pathlib import Path

import requests

CLIENT_ID   = "app_EMoamEEZ73f0CkXaXp7hrann"
ISSUER      = "https://auth.openai.com"
USAGE_URL   = "https://chatgpt.com/backend-api/wham/usage"
TOKENS_FILE = Path("/data/chatgpt_tokens.json")

HEADERS = {
    "User-Agent": "opencode/0.1.0",
}


class ChatGPTNotAuthenticatedError(Exception):
    pass


class ChatGPTAuthError(Exception):
    pass


def _load_tokens() -> dict:
    if not TOKENS_FILE.exists():
        raise ChatGPTNotAuthenticatedError(
            "Not authenticated. Run:\n"
            "docker compose run --rm dashboard python chatgpt_auth.py"
        )
    return json.loads(TOKENS_FILE.read_text())


def _refresh_tokens(tokens: dict) -> dict:
    resp = requests.post(
        f"{ISSUER}/oauth/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id":     CLIENT_ID,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    new = resp.json()
    updated = {
        **tokens,
        "access_token": new["access_token"],
        "expires_at":   int(time.time()) + int(new.get("expires_in", 3600)),
    }
    if "refresh_token" in new:
        updated["refresh_token"] = new["refresh_token"]
    TOKENS_FILE.write_text(json.dumps(updated))
    return updated


def _get_access_token() -> tuple[str, str | None]:
    tokens = _load_tokens()
    # Refresh if within 5 minutes of expiry
    if tokens.get("expires_at", 0) < time.time() + 300:
        tokens = _refresh_tokens(tokens)
    return tokens["access_token"], tokens.get("account_id")


def get_usage() -> dict:
    access_token, account_id = _get_access_token()

    hdrs = {**HEADERS, "Authorization": f"Bearer {access_token}"}
    if account_id:
        hdrs["ChatGPT-Account-Id"] = account_id

    resp = requests.get(USAGE_URL, headers=hdrs, timeout=15)
    if resp.status_code in (401, 403):
        # Token rejected — clear so next call triggers re-auth message
        TOKENS_FILE.unlink(missing_ok=True)
        raise ChatGPTAuthError(
            "Session expired. Re-authenticate:\n"
            "docker compose run --rm dashboard python chatgpt_auth.py"
        )
    resp.raise_for_status()

    raw = resp.json()
    rl  = raw.get("rate_limit", {})
    pw  = rl.get("primary_window") or {}
    sw  = rl.get("secondary_window") or {}
    cr  = (raw.get("code_review_rate_limit") or {}).get("primary_window") or {}

    return {
        "plan_type":     raw.get("plan_type", ""),
        "five_hour":     {"utilization": pw.get("used_percent"), "reset_at": pw.get("reset_at")},
        "seven_day":     {"utilization": sw.get("used_percent"), "reset_at": sw.get("reset_at")},
        "code_review":   {"utilization": cr.get("used_percent"), "reset_at": cr.get("reset_at")},
        "limit_reached": not rl.get("allowed", True),
        "_raw": raw,
    }
