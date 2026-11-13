"""GitHub Copilot account quota snapshots, as used by VS Code."""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

USAGE_URL = "https://api.github.com/copilot_internal/user"
TOKEN_FILE = Path("/data/copilot_token.json")
TIMEOUT_S = 15


class CopilotTokenMissingError(Exception):
    pass


class CopilotAuthError(Exception):
    pass


def load_token() -> str | None:
    try:
        return json.loads(TOKEN_FILE.read_text()).get("token") or None
    except (OSError, ValueError, AttributeError):
        return None


def save_token(token: str) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Create the file with restricted permissions from the outset.
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        json.dump({"token": token.strip()}, f)


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def _reset(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()
    except ValueError:
        return None


def parse_usage(raw: dict) -> dict:
    snapshots = raw.get("quota_snapshots") or {}
    if not isinstance(snapshots, dict):
        snapshots = {}
    quotas = {}
    for name, snapshot in snapshots.items():
        if not isinstance(snapshot, dict):
            continue
        remaining = _number(snapshot.get("percent_remaining"))
        entitlement = _number(snapshot.get("entitlement"))
        unlimited = snapshot.get("unlimited") is True
        # Some managed accounts receive zero-entitlement placeholders only.
        if unlimited and entitlement == 0:
            continue
        if remaining is None and not unlimited:
            continue
        reset = snapshot.get("reset_at") or snapshot.get("reset_date")
        if name not in ("session", "weekly"):
            reset = (reset or raw.get("quota_reset_date_utc")
                     or raw.get("quota_reset_date"))
        quotas[name] = {
            "utilization": None if unlimited else max(0, 100 - remaining),
            "unlimited": unlimited,
            "reset_at": _reset(reset),
        }
    return {"plan": raw.get("copilot_plan") or "", "quotas": quotas}


def validate_token(token: str) -> dict:
    response = requests.get(
        USAGE_URL,
        headers={"Authorization": f"Bearer {token.strip()}",
                 "Accept": "application/json", "User-Agent": "ai-quota-dashboard",
                 "X-GitHub-Api-Version": "2025-05-01"},
        timeout=TIMEOUT_S,
    )
    if response.status_code in (401, 403):
        raise CopilotAuthError(
            "GitHub rejected the token or it cannot access Copilot usage"
        )
    response.raise_for_status()
    return parse_usage(response.json())


def get_usage() -> dict:
    token = load_token()
    if not token:
        raise CopilotTokenMissingError("GitHub token not configured")
    return validate_token(token)
