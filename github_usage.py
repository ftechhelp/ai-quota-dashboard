import os

import requests

API_URL = "https://api.github.com"


class GithubTokenMissingError(Exception):
    pass


class GithubAuthError(Exception):
    pass


def get_usage() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise GithubTokenMissingError("GITHUB_TOKEN not set")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    resp = requests.get(f"{API_URL}/user", headers=headers, timeout=10)
    if resp.status_code in (401, 403):
        raise GithubAuthError("GitHub token invalid or expired")
    resp.raise_for_status()
    user = resp.json()

    plan = (user.get("plan") or {}).get("name", "")

    # Manual override wins; otherwise try the API (requires 'copilot' scope)
    copilot_plan = os.environ.get("COPILOT_PLAN", "").strip().lower() or None
    copilot_raw  = {}
    if not copilot_plan:
        cr = requests.get(f"{API_URL}/user/copilot", headers=headers, timeout=10)
        if cr.status_code == 200:
            copilot_raw  = cr.json()
            copilot_plan = (copilot_raw.get("copilot_plan") or "").replace("_", " ") or None

    return {
        "login":        user.get("login", ""),
        "name":         user.get("name") or user.get("login", ""),
        "github_plan":  plan,
        "copilot_plan": copilot_plan,
        "_copilot_raw": copilot_raw,
        "_user_raw":    user,
    }
