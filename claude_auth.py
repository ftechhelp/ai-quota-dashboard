"""
Claude PKCE OAuth flow.
Used by app.py to authenticate without requiring ~/.claude/.credentials.json.
Tokens are saved to /data/claude_tokens.json.
"""

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

CLIENT_ID    = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTH_URL     = "https://claude.ai/oauth/authorize"
TOKEN_URL    = "https://console.anthropic.com/v1/oauth/token"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPES       = "org:create_api_key user:profile user:inference"
PKCE_FILE    = Path("/data/claude_pkce.json")
TOKENS_FILE  = Path("/data/claude_tokens.json")


def start_pkce_auth() -> str:
    """Generate PKCE pair, save verifier, return the authorization URL."""
    code_verifier  = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    # state = verifier (Anthropic's convention — not a separate random value)
    PKCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PKCE_FILE.write_text(json.dumps({"code_verifier": code_verifier}))

    params = {
        "code":                  "true",
        "client_id":             CLIENT_ID,
        "response_type":         "code",
        "redirect_uri":          REDIRECT_URI,
        "scope":                 SCOPES,
        "code_challenge":        code_challenge,
        "code_challenge_method": "S256",
        "state":                 code_verifier,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange authorization code for tokens using the saved PKCE verifier."""
    if not PKCE_FILE.exists():
        raise RuntimeError("PKCE state not found. Start the auth flow again.")

    pkce          = json.loads(PKCE_FILE.read_text())
    code_verifier = pkce["code_verifier"]

    # Anthropic's callback page returns "authcode#state" — split to get the real code
    parts     = code.strip().split("#")
    auth_code = parts[0]
    state     = parts[1] if len(parts) > 1 else code_verifier

    resp = requests.post(
        TOKEN_URL,
        json={
            "grant_type":    "authorization_code",
            "code":          auth_code,
            "state":         state,
            "redirect_uri":  REDIRECT_URI,
            "client_id":     CLIENT_ID,
            "code_verifier": code_verifier,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    tokens = {
        "access_token":  data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_at":    int(time.time()) + int(data.get("expires_in", 28800)),
    }
    PKCE_FILE.unlink(missing_ok=True)
    return tokens


def refresh_tokens(tokens: dict) -> dict:
    resp = requests.post(
        TOKEN_URL,
        json={
            "grant_type":    "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id":     CLIENT_ID,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    updated = {
        **tokens,
        "access_token": data["access_token"],
        "expires_at":   int(time.time()) + int(data.get("expires_in", 28800)),
    }
    if "refresh_token" in data:
        updated["refresh_token"] = data["refresh_token"]
    save_tokens(updated)
    return updated


def save_tokens(tokens: dict) -> None:
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKENS_FILE.write_text(json.dumps(tokens))


def load_tokens() -> dict | None:
    if TOKENS_FILE.exists():
        try:
            return json.loads(TOKENS_FILE.read_text())
        except Exception:
            return None
    return None
