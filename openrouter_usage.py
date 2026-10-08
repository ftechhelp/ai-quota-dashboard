"""OpenRouter month-to-date spend and last-used model.

The key is pasted into the dashboard and saved to ``/data/openrouter_key.json``.

* Regular key (``sk-or-v1-...``) → ``GET /api/v1/key``: spend for that key only.
  The last-used model is unavailable, since OpenRouter only exposes model
  activity to management keys.
* Management key → ``GET /api/v1/keys``: spend summed across every key in the
  default workspace, plus ``POST /api/v1/analytics/query`` (falling back to
  ``GET /api/v1/activity``, which only covers completed UTC days) for the most
  recently used model.

All spend figures are OpenRouter credits in USD for the current UTC month.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API_BASE  = "https://openrouter.ai/api/v1"
KEY_FILE  = Path("/data/openrouter_key.json")
TIMEOUT_S = 15


class OpenRouterKeyMissingError(Exception):
    pass


class OpenRouterAuthError(Exception):
    pass


# ── Key storage ───────────────────────────────────────────────────────────────

def load_key() -> str | None:
    if not KEY_FILE.exists():
        return None
    try:
        return json.loads(KEY_FILE.read_text()).get("api_key") or None
    except Exception:
        return None


def save_key(api_key: str) -> None:
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(json.dumps({"api_key": api_key.strip()}))
    KEY_FILE.chmod(0o600)


def clear_key() -> None:
    KEY_FILE.unlink(missing_ok=True)


def validate_key(api_key: str) -> dict:
    """Return the key's info, or raise OpenRouterAuthError if it is rejected."""
    return _request("GET", "/key", api_key.strip())["data"]


# ── API helpers ───────────────────────────────────────────────────────────────

def _request(method: str, path: str, api_key: str, **kwargs) -> dict:
    resp = requests.request(
        method,
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=TIMEOUT_S,
        **kwargs,
    )
    if resp.status_code == 401:
        raise OpenRouterAuthError("OpenRouter rejected the API key")
    resp.raise_for_status()
    return resp.json()


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _list_keys(api_key: str) -> list[dict]:
    keys: list[dict] = []
    for _ in range(50):  # hard stop in case pagination never runs dry
        page = _request(
            "GET", "/keys", api_key,
            params={"include_disabled": "true", "include_expired": "true", "offset": len(keys)},
        ).get("data") or []
        if not page:
            break
        keys.extend(page)
    return keys


def _last_model_from_analytics(api_key: str) -> dict | None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    body = {
        "metrics":     ["request_count"],
        "dimensions":  ["model"],
        "granularity": "hour",
        "time_range":  {
            "start": (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end":   now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "order_by":    {"field": "date", "direction": "desc"},
        "limit":       1000,
    }
    resp = _request("POST", "/analytics/query", api_key, json=body)
    rows = (resp.get("data") or {}).get("data") or []

    best = None
    for row in rows:
        date_key = next((k for k in row if k.startswith("date")), None)
        if not date_key or not row.get("model") or float(row.get("request_count") or 0) <= 0:
            continue
        candidate = (_parse_ts(row[date_key]), float(row["request_count"]), row["model"])
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        return None
    return {"model": best[2], "at": best[0].isoformat(), "precision": "hour"}


def _last_model_from_activity(api_key: str) -> dict | None:
    rows = _request("GET", "/activity", api_key).get("data") or []
    rows = [r for r in rows if r.get("model") and (r.get("requests") or 0) > 0]
    if not rows:
        return None
    row = max(rows, key=lambda r: (r.get("date", ""), r.get("requests") or 0))
    return {"model": row["model"], "at": row.get("date"), "precision": "day"}


# ── Public API ────────────────────────────────────────────────────────────────

def get_usage() -> dict:
    api_key = load_key()
    if not api_key:
        raise OpenRouterKeyMissingError("OpenRouter API key not configured")

    info = _request("GET", "/key", api_key)["data"]
    is_management = bool(info.get("is_management_key") or info.get("is_provisioning_key"))

    result = {
        "label":         info.get("label"),
        "is_management": is_management,
        "spend_month":   float(info.get("usage_monthly") or 0),
        "byok_month":    float(info.get("byok_usage_monthly") or 0),
        "key_count":     1,
        "last_model":    None,
        "last_model_error": None,
        "_raw":          {"key": info},
    }

    if is_management:
        keys = _list_keys(api_key)
        result["spend_month"] = sum(float(k.get("usage_monthly") or 0) for k in keys)
        result["byok_month"]  = sum(float(k.get("byok_usage_monthly") or 0) for k in keys)
        result["key_count"]   = len(keys)
        result["_raw"]["keys"] = keys

        # Analytics is beta and has hourly buckets; activity is stable but skips today.
        errors = []
        sources = (
            ("analytics", _last_model_from_analytics),
            ("activity", _last_model_from_activity),
        )
        for source, fetch in sources:
            try:
                result["last_model"] = fetch(api_key)
            except Exception as e:
                errors.append(f"{source}: {e}")
                continue
            if result["last_model"]:
                break
        if not result["last_model"] and errors:
            result["last_model_error"] = "; ".join(errors)

    return result
