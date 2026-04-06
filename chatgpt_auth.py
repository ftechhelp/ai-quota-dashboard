#!/usr/bin/env python3
"""
ChatGPT device-code OAuth flow.
Can be used as a library (by app.py) or run standalone:

    docker compose run --rm dashboard python chatgpt_auth.py
"""

import base64
import json
import sys
import time
from pathlib import Path

import requests

CLIENT_ID   = "app_EMoamEEZ73f0CkXaXp7hrann"
ISSUER      = "https://auth.openai.com"
TOKENS_FILE = Path("/data/chatgpt_tokens.json")


# ── Library API ───────────────────────────────────────────────────────────────

def start_device_auth() -> dict:
    """Step 1: request a device code. Returns {device_id, user_code, interval}."""
    resp = requests.post(
        f"{ISSUER}/api/accounts/deviceauth/usercode",
        json={"client_id": CLIENT_ID},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "device_id": data["device_auth_id"],
        "user_code": data["user_code"],
        "interval":  max(1, int(data.get("interval", 5))) + 3,
    }


def poll_device_auth(device_id: str, user_code: str) -> dict | None:
    """
    Step 2: poll once. Returns token dict on success, None if still pending.
    Raises on unexpected errors.
    """
    resp = requests.post(
        f"{ISSUER}/api/accounts/deviceauth/token",
        json={"device_auth_id": device_id, "user_code": user_code},
        timeout=15,
    )
    if resp.status_code in (403, 404):
        return None  # still pending
    resp.raise_for_status()
    result = resp.json()
    if not result.get("authorization_code"):
        return None
    return result


def exchange_code(authorization_code: str, code_verifier: str) -> dict:
    """Step 3: exchange authorization code for access + refresh tokens."""
    resp = requests.post(
        f"{ISSUER}/oauth/token",
        data={
            "grant_type":    "authorization_code",
            "code":          authorization_code,
            "redirect_uri":  f"{ISSUER}/deviceauth/callback",
            "client_id":     CLIENT_ID,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    tokens = resp.json()

    access_token = tokens["access_token"]
    account_id   = _extract_account_id(access_token)

    return {
        "access_token":  access_token,
        "refresh_token": tokens["refresh_token"],
        "expires_at":    int(time.time()) + int(tokens.get("expires_in", 3600)),
        "account_id":    account_id,
    }


def save_tokens(tokens: dict) -> None:
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKENS_FILE.write_text(json.dumps(tokens))


def _extract_account_id(access_token: str) -> str | None:
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return (
            claims.get("chatgpt_account_id")
            or (claims.get("https://api.openai.com/auth") or {}).get("chatgpt_account_id")
            or (claims.get("organizations") or [{}])[0].get("id")
        )
    except Exception:
        return None


# ── CLI fallback ──────────────────────────────────────────────────────────────

def main():
    print()
    auth = start_device_auth()

    print("  ┌─────────────────────────────────────────────────┐")
    print("  │         ChatGPT Device Authorization            │")
    print("  ├─────────────────────────────────────────────────┤")
    print("  │  Visit:  https://auth.openai.com/codex/device   │")
    print(f"  │  Code:   {auth['user_code']:<41}│")
    print("  └─────────────────────────────────────────────────┘")
    print()
    print("  Waiting for authorization… (Ctrl-C to cancel)")

    deadline = time.time() + 300
    while time.time() < deadline:
        time.sleep(auth["interval"])
        result = poll_device_auth(auth["device_id"], auth["user_code"])
        if result:
            tokens = exchange_code(result["authorization_code"], result["code_verifier"])
            save_tokens(tokens)
            print(f"\n  Done! Tokens saved to {TOKENS_FILE}")
            return
        print("  Still waiting…")

    print("  Timed out.")
    sys.exit(1)


if __name__ == "__main__":
    main()
