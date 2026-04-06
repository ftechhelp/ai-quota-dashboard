import time
from datetime import datetime, timezone

import streamlit as st

import chatgpt_auth
import chatgpt_usage as cgpt
import claude_auth
import github_usage as gh
from claude_usage import CredentialsNotFoundError, RateLimitedError, TokenExpiredError, get_usage

st.set_page_config(page_title="AI Quota Dashboard", page_icon="📊", layout="wide")

st.markdown("""
<style>
  .block-container { padding-top: 1rem; }
  header[data-testid="stHeader"] { background: transparent; }
  [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] { gap: 0.3rem; }
  [data-testid="stProgressBar"] p { font-size: 0.75rem; margin: 0; }
</style>
""", unsafe_allow_html=True)


# ── Cached fetchers ───────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_claude():
    return get_usage()

@st.cache_data(ttl=300)
def fetch_chatgpt():
    return cgpt.get_usage()

@st.cache_data(ttl=300)
def fetch_github():
    return gh.get_usage()


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_reset_time(value) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, str):
            # Handle OpenAI's "60s" / "1m30s" duration format
            if value.endswith("s") and not value.endswith("+00:00"):
                secs = 0
                for part in value.replace("m", " ").replace("s", "").split():
                    secs = secs * 60 + int(part)
                from datetime import timedelta
                dt = datetime.now(timezone.utc) + timedelta(seconds=secs)
                return dt.astimezone().strftime("%-H:%M:%S %Z")
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            ts = value / 1000 if value > 1e12 else value
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        local = dt.astimezone()
        now   = datetime.now(local.tzinfo)
        if local.date() == now.date():
            return local.strftime("%-H:%M %Z")
        elif local.date() == (now + __import__("datetime").timedelta(days=1)).date():
            return local.strftime("tomorrow %-H:%M %Z")
        else:
            return local.strftime("%a %-H:%M %Z")
    except Exception:
        return str(value)


def quota_row(label: str, pct: float, reset_value=None):
    c1, c2, c3 = st.columns([1, 5, 2])
    c1.markdown(f"<small><b>{label}</b></small>", unsafe_allow_html=True)
    c2.progress(min(max(pct / 100, 0.0), 1.0))
    reset = format_reset_time(reset_value)
    note = f"{pct:.0f}%"
    if reset:
        note += f"  resets {reset}"
    c3.markdown(f"<small>{note}</small>", unsafe_allow_html=True)


def credits_row(label: str, used: float, limit: float):
    pct = (used / limit * 100) if limit else 0
    c1, c2, c3 = st.columns([1, 5, 2])
    c1.markdown(f"<small><b>{label}</b></small>", unsafe_allow_html=True)
    c2.progress(min(max(pct / 100, 0.0), 1.0))
    c3.markdown(f"<small>${used:,.2f} / ${limit:,.2f}</small>", unsafe_allow_html=True)



# ── Header ────────────────────────────────────────────────────────────────────

_, refresh_col = st.columns([9, 1])
with refresh_col:
    if st.button("↻ Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── Claude login flow ─────────────────────────────────────────────────────────

def _render_claude_login():
    with st.container(border=True):
        st.markdown("**Claude**", unsafe_allow_html=True)

        pending = st.session_state.get("claude_pending")

        if pending is None:
            if st.button("Connect Claude", key="claude_connect"):
                auth_url = claude_auth.start_pkce_auth()
                st.session_state.claude_pending = {"auth_url": auth_url}
                st.rerun()
        else:
            auth_url = pending["auth_url"]
            st.markdown(
                f"**1.** [Click here to authorize Claude]({auth_url})  \n"
                "**2.** Sign in, then paste the code shown on the page:",
                unsafe_allow_html=True,
            )
            code_input = st.text_input("Authorization code", key="claude_code_input", label_visibility="collapsed", placeholder="Paste code here…")
            col_ok, col_cancel, _ = st.columns([1, 1, 5])
            if col_ok.button("Connect", key="claude_code_submit") and code_input:
                try:
                    tokens = claude_auth.exchange_code(code_input)
                    claude_auth.save_tokens(tokens)
                    del st.session_state.claude_pending
                    st.cache_data.clear()
                    st.rerun()
                except Exception as ex:
                    st.error(f"Failed to exchange code: {ex}")
            if col_cancel.button("Cancel", key="claude_cancel"):
                del st.session_state.claude_pending
                st.rerun()


# ── Claude ────────────────────────────────────────────────────────────────────

try:
    data = fetch_claude()
    meta = data.get("_meta", {})
    sub_type = meta.get("subscriptionType", "")
    five_hour = data.get("five_hour") or {}
    seven_day = data.get("seven_day") or {}
    extra = data.get("extra_usage") or {}

    with st.container(border=True):
        badge = f"`{sub_type}`" if sub_type else ""
        st.markdown(f"**Claude** &nbsp; {badge}", unsafe_allow_html=True)
        quota_row("5 h", float(five_hour.get("utilization") or 0), five_hour.get("resets_at"))
        quota_row("7 d", float(seven_day.get("utilization") or 0), seven_day.get("resets_at"))
        if extra.get("is_enabled"):
            credits_row(
                "credits",
                (extra.get("used_credits") or 0) / 100,
                (extra.get("monthly_limit") or 0) / 100,
            )

    with st.expander("Raw · Claude"):
        st.json({k: v for k, v in data.items() if k != "_meta"})

except RateLimitedError as e:
    st.warning(f"Claude rate-limited.{f' Retry in {e.retry_after}s.' if e.retry_after else ''}")
except TokenExpiredError as e:
    st.error(str(e))
except CredentialsNotFoundError as e:
    if str(e) == "not_authenticated":
        _render_claude_login()
    else:
        st.error(str(e))
except Exception as e:
    st.error(f"Claude: {e}")
    st.exception(e)


# ── ChatGPT login flow ────────────────────────────────────────────────────────

def _render_chatgpt_login():
    with st.container(border=True):
        st.markdown("**ChatGPT** &nbsp; `plus`", unsafe_allow_html=True)

        pending = st.session_state.get("chatgpt_pending")

        if pending is None:
            if st.button("Connect ChatGPT", key="chatgpt_connect"):
                with st.spinner("Requesting device code…"):
                    st.session_state.chatgpt_pending = chatgpt_auth.start_device_auth()
                st.rerun()
        else:
            st.markdown(
                f"**1.** Visit &nbsp; `https://auth.openai.com/codex/device`  \n"
                f"**2.** Enter code:",
                unsafe_allow_html=True,
            )
            st.code(pending["user_code"], language=None)

            col_cancel, _ = st.columns([1, 4])
            if col_cancel.button("Cancel", key="chatgpt_cancel"):
                del st.session_state.chatgpt_pending
                st.rerun()

            # Poll once then rerun automatically
            with st.spinner("Waiting for authorization…"):
                result = chatgpt_auth.poll_device_auth(pending["device_id"], pending["user_code"])

            if result:
                tokens = chatgpt_auth.exchange_code(
                    result["authorization_code"], result["code_verifier"]
                )
                chatgpt_auth.save_tokens(tokens)
                del st.session_state.chatgpt_pending
                st.cache_data.clear()
                st.rerun()
            else:
                time.sleep(pending["interval"])
                st.rerun()


# ── ChatGPT ───────────────────────────────────────────────────────────────────

try:
    cdata = fetch_chatgpt()
    raw   = cdata.get("_raw", cdata)

    plan  = cdata.get("plan_type", "plus")
    fh    = cdata.get("five_hour", {})
    sd    = cdata.get("seven_day", {})
    cr    = cdata.get("code_review", {})

    with st.container(border=True):
        st.markdown(f"**ChatGPT** &nbsp; `{plan}`", unsafe_allow_html=True)

        quota_row("5 h", float(fh.get("utilization") or 0), fh.get("reset_at"))
        quota_row("7 d", float(sd.get("utilization") or 0), sd.get("reset_at"))
        if cr.get("utilization") is not None:
            quota_row("code review", float(cr.get("utilization") or 0), cr.get("reset_at"))

    with st.expander("Raw · ChatGPT"):
        st.json(raw)

except (cgpt.ChatGPTNotAuthenticatedError, cgpt.ChatGPTAuthError):
    _render_chatgpt_login()
except Exception as e:
    st.error(f"ChatGPT: {e}")
    st.exception(e)

# ── GitHub Copilot ────────────────────────────────────────────────────────────

try:
    gdata = fetch_github()
    copilot_badge = f"`{gdata['copilot_plan']}`" if gdata.get("copilot_plan") else ""
    github_badge  = f"`{gdata['github_plan']}`"  if gdata.get("github_plan")  else ""

    COPILOT_LIMITS = {
        "copilot pro": [
            ("completions", "Unlimited"),
            ("chat",        "Unlimited"),
            ("premium req", "300 / month"),
        ],
        "copilot free": [
            ("completions", "2,000 / month"),
            ("chat",        "50 / month"),
            ("premium req", "0"),
        ],
    }
    plan_key = (gdata.get("copilot_plan") or "").lower()
    limits   = COPILOT_LIMITS.get(plan_key, [])

    with st.container(border=True):
        header_col, link_col = st.columns([5, 1])
        header_col.markdown(f"**GitHub Copilot** &nbsp; {copilot_badge or github_badge}", unsafe_allow_html=True)
        link_col.markdown(
            "<small>"
            "<a href='https://github.com/settings/copilot/features' target='_blank'>quota →</a>"
            " &nbsp; "
            "<a href='https://github.com/settings/billing/summary' target='_blank'>billing →</a>"
            "</small>",
            unsafe_allow_html=True,
        )
        for label, value in limits:
            c1, c2, c3 = st.columns([1, 5, 2])
            c1.markdown(f"<small><b>{label}</b></small>", unsafe_allow_html=True)
            c2.markdown("<small style='color:grey'>no live data — GitHub API unavailable</small>", unsafe_allow_html=True)
            c3.markdown(f"<small>{value}</small>", unsafe_allow_html=True)
        st.markdown(f"<small>Signed in as &nbsp;<b>{gdata['login']}</b></small>", unsafe_allow_html=True)

except gh.GithubTokenMissingError:
    with st.container(border=True):
        st.markdown("**GitHub Copilot**", unsafe_allow_html=True)
        st.caption("Add `GITHUB_TOKEN` to `.env` to enable this card.")
except gh.GithubAuthError as e:
    with st.container(border=True):
        st.markdown("**GitHub Copilot**", unsafe_allow_html=True)
        st.error(str(e))
except Exception as e:
    st.error(f"GitHub: {e}")
    st.exception(e)


# ── Footer ────────────────────────────────────────────────────────────────────

st.caption(f"Updated {datetime.now().strftime('%H:%M:%S')}")
