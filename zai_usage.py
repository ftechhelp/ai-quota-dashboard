"""Z.ai GLM Coding Plan usage.

Z.ai exposes coding-plan quota via the monitor API its own console uses:
``GET https://api.z.ai/api/monitor/usage/quota/limit``. The API key is sent
directly in the ``Authorization`` header (no ``Bearer`` prefix).

Required environment variable (add to ``.env``):

* ``ZAI_API_KEY`` — coding-plan API key from https://z.ai/manage-apikey/apikey-list
"""

import os
from datetime import datetime, timezone

import requests

QUOTA_URL = "https://api.z.ai/api/monitor/usage/quota/limit"
TIMEOUT_S = 15

# The limits array distinguishes token windows by (unit, number):
# unit=3, number=5 → rolling 5-hour window; unit=6, number=1 → weekly window.
_TOKEN_WINDOWS = {
    (3, 5): "five_hour",
    (6, 1): "weekly",
}


class ZaiKeyMissingError(Exception):
    pass


class ZaiAuthError(Exception):
    pass


def _iso_from_ms(ms) -> str | None:
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def get_usage() -> dict:
    api_key = os.environ.get("ZAI_API_KEY", "").strip()
    if not api_key:
        raise ZaiKeyMissingError("ZAI_API_KEY not set")

    resp = requests.get(
        QUOTA_URL,
        headers={
            "Authorization": api_key,
            "Accept-Language": "en-US,en",
            "Content-Type": "application/json",
        },
        timeout=TIMEOUT_S,
    )
    if resp.status_code in (401, 403):
        raise ZaiAuthError("Z.ai API key invalid or expired")
    resp.raise_for_status()

    payload = resp.json()
    data = payload.get("data") or payload
    limits = data.get("limits")
    if not isinstance(limits, list):
        raise ZaiAuthError(
            f"Unexpected Z.ai quota response: {payload.get('msg') or payload}"
        )

    result = {
        "five_hour": None,
        "weekly": None,
        "mcp_monthly": None,
        "level": data.get("level"),
    }

    for limit in limits:
        if not isinstance(limit, dict):
            continue
        pct = float(limit.get("percentage") or 0)

        if limit.get("type") == "TOKENS_LIMIT":
            window = _TOKEN_WINDOWS.get((limit.get("unit"), limit.get("number")))
            if window:
                result[window] = {
                    "utilization": pct,
                    "resets_at": _iso_from_ms(limit.get("nextResetTime")),
                }
        elif limit.get("type") == "TIME_LIMIT":
            result["mcp_monthly"] = {
                "utilization": pct,
                "current": limit.get("currentValue"),
                "total": limit.get("usage"),
            }

    if not any((result["five_hour"], result["weekly"], result["mcp_monthly"])):
        raise ZaiAuthError("No quota windows found in Z.ai response")

    return result
