"""OpenCode Go usage.

OpenCode Go (https://opencode.ai/docs/go) is a low-cost subscription that bundles
usage limits across a rolling 5-hour, weekly, and monthly window. There is no public
usage API, so this module scrapes the authenticated workspace console at
``https://opencode.ai/workspace/<id>/go``.

Required environment variables (add to ``.env``):

* ``OPENCODE_GO_WORKSPACE_ID`` — the ``<id>`` from the console URL.
* ``OPENCODE_GO_AUTH_COOKIE`` — value of the ``auth`` cookie (starts with ``Fe26.2**``)
  copied from browser devtools → Application → Cookies → opencode.ai.
"""

import os
import re
from datetime import datetime, timedelta, timezone

import requests

DASHBOARD_URL = "https://opencode.ai/workspace/{workspace_id}/go"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "Gecko/20100101 Firefox/148.0"
)
TIMEOUT_S = 15

# Documented OpenCode Go limits, in USD of usage per window.
PLAN_LIMITS = {
    "five_hour": 12.0,
    "weekly": 30.0,
    "monthly": 60.0,
}

# Console is a Qwik app; usage is serialised inline as e.g.
#   rollingUsage:$R[7]={usagePercent:42.5,resetInSec:1234,...}
# Field order is not guaranteed, so we grab the object block and pull each
# field out independently.
_WINDOW_KEYS = {
    "five_hour": "rollingUsage",
    "weekly": "weeklyUsage",
    "monthly": "monthlyUsage",
}
_NUM = r"-?\d+(?:\.\d+)?"
_FIELD_BEFORE_NUM = re.compile(
    rf"(?P<field>usagePercent|resetInSec):(?P<n>{_NUM})"
)


class OpenCodeGoKeyMissingError(Exception):
    pass


class OpenCodeGoAuthError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_in(seconds: float) -> str:
    return (_now() + timedelta(seconds=seconds)).isoformat()


def _parse_window(html: str, marker: str) -> dict | None:
    """Extract ``{usagePercent, resetInSec}`` for one window marker."""
    block = re.search(rf"{re.escape(marker)}:\$R\[\d+\]=\{{([^}}]*)\}}", html)
    if not block:
        return None

    usage_pct = None
    reset_secs = None
    for field_match in _FIELD_BEFORE_NUM.finditer(block.group(1)):
        value = float(field_match.group("n"))
        if field_match.group("field") == "usagePercent":
            usage_pct = value
        else:
            reset_secs = value

    if usage_pct is None and reset_secs is None:
        return None

    return {
        "utilization": usage_pct or 0.0,
        "resets_at": _iso_in(reset_secs) if reset_secs is not None else None,
    }


def get_usage() -> dict:
    workspace_id = os.environ.get("OPENCODE_GO_WORKSPACE_ID", "").strip()
    auth_cookie = os.environ.get("OPENCODE_GO_AUTH_COOKIE", "").strip()
    if not workspace_id or not auth_cookie:
        raise OpenCodeGoKeyMissingError(
            "OPENCODE_GO_WORKSPACE_ID and/or OPENCODE_GO_AUTH_COOKIE not set"
        )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html",
        "Cookie": f"auth={auth_cookie}",
    }
    resp = requests.get(
        DASHBOARD_URL.format(workspace_id=workspace_id),
        headers=headers,
        timeout=TIMEOUT_S,
    )
    if resp.status_code in (401, 403):
        raise OpenCodeGoAuthError("OpenCode Go auth cookie invalid or expired")
    resp.raise_for_status()
    html = resp.text

    windows = {
        name: _parse_window(html, marker)
        for name, marker in _WINDOW_KEYS.items()
    }

    if not any(windows.values()):
        raise OpenCodeGoAuthError(
            "Could not parse any usage window from OpenCode Go dashboard "
            "(cookie may be invalid or dashboard HTML changed)"
        )

    return {
        "five_hour": windows["five_hour"],
        "weekly": windows["weekly"],
        "monthly": windows["monthly"],
        "limits": PLAN_LIMITS,
    }
