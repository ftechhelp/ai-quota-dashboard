from datetime import datetime, timezone

import streamlit as st

from claude_usage import CredentialsNotFoundError, RateLimitedError, TokenExpiredError, get_usage

st.set_page_config(page_title="AI Quota Dashboard", page_icon="📊", layout="wide")

st.markdown("""
<style>
  /* Page chrome */
  .block-container { padding-top: 1rem; }
  header[data-testid="stHeader"] { background: transparent; }

  /* Tighten vertical gaps inside cards */
  [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] {
    gap: 0.3rem;
  }
  /* Smaller progress bar label */
  [data-testid="stProgressBar"] p { font-size: 0.75rem; margin: 0; }

</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def fetch_usage():
    return get_usage()


def format_reset_time(value) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            ts = value / 1000 if value > 1e12 else value
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.astimezone().strftime("%-H:%M %Z")
    except Exception:
        return str(value)


def quota_row(label: str, pct: float, reset_value=None):
    """One compact row: label | progress bar | pct + reset."""
    c1, c2, c3 = st.columns([1, 5, 2])
    c1.markdown(f"<small><b>{label}</b></small>", unsafe_allow_html=True)
    c2.progress(min(max(pct / 100, 0.0), 1.0))
    reset = format_reset_time(reset_value)
    note = f"{pct:.0f}%"
    if reset:
        note += f"  resets {reset}"
    c3.markdown(f"<small>{note}</small>", unsafe_allow_html=True)


def credits_row(label: str, used: float, limit: float):
    """One compact row for dollar-denominated credits."""
    pct = (used / limit * 100) if limit else 0
    c1, c2, c3 = st.columns([1, 5, 2])
    c1.markdown(f"<small><b>{label}</b></small>", unsafe_allow_html=True)
    c2.progress(min(max(pct / 100, 0.0), 1.0))
    c3.markdown(
        f"<small>${used:,.2f} / ${limit:,.2f}</small>",
        unsafe_allow_html=True,
    )


# ── Header ────────────────────────────────────────────────────────────────────

_, refresh_col = st.columns([9, 1])
with refresh_col:
    if st.button("↻ Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── Claude ────────────────────────────────────────────────────────────────────

try:
    data = fetch_usage()
    meta = data.get("_meta", {})
    sub_type = meta.get("subscriptionType", "")
    tier = meta.get("rateLimitTier", "")
    five_hour = data.get("five_hour") or {}
    seven_day = data.get("seven_day") or {}
    extra = data.get("extra_usage") or {}

    with st.container(border=True):
        badge = f"`{sub_type}`" if sub_type else ""
        st.markdown(f"**Claude** &nbsp; {badge}", unsafe_allow_html=True)

        quota_row(
            "5 h",
            float(five_hour.get("utilization") or 0),
            five_hour.get("resets_at"),
        )
        quota_row(
            "7 d",
            float(seven_day.get("utilization") or 0),
            seven_day.get("resets_at"),
        )

        if extra.get("is_enabled"):
            monthly_limit = (extra.get("monthly_limit") or 0) / 100
            used_credits = (extra.get("used_credits") or 0) / 100
            credits_row("credits", used_credits, monthly_limit)

    with st.expander("Raw · Claude"):
        st.json({k: v for k, v in data.items() if k != "_meta"})

    st.caption(f"Updated {datetime.now().strftime('%H:%M:%S')}")

except RateLimitedError as e:
    msg = "Rate-limited by usage endpoint."
    if e.retry_after:
        msg += f" Retry in {e.retry_after}s."
    st.warning(msg)
except TokenExpiredError as e:
    st.error(str(e))
except CredentialsNotFoundError as e:
    st.error(str(e))
except Exception as e:
    st.error(f"Claude: {e}")
    st.exception(e)
