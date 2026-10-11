import time
from datetime import datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

import chatgpt_auth
import chatgpt_usage as cgpt
import claude_auth
import collector
import history
import openrouter_usage as orouter
from claude_usage import CredentialsNotFoundError, RateLimitedError, TokenExpiredError

st.set_page_config(page_title="AI Quota Dashboard", page_icon="📊", layout="wide")

st.markdown("""
<style>
  .block-container { padding-top: 1rem; }
  header[data-testid="stHeader"] { background: transparent; }
  [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] { gap: 0.3rem; }
</style>
""", unsafe_allow_html=True)


# ── Cached fetchers ───────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_claude():
    return collector.fetch("claude")

@st.cache_data(ttl=300)
def fetch_chatgpt():
    return collector.fetch("chatgpt")

@st.cache_data(ttl=300)
def fetch_openrouter():
    return collector.fetch("openrouter")


# ── Helpers ───────────────────────────────────────────────────────────────────

# Colors from the dataviz reference palette: accent fill for meters, status colors
# when a window is over pace or exhausted, categorical slots for history series.
ACCENT   = {"light": "#2a78d6", "dark": "#3987e5"}
WARNING  = "#fab219"
CRITICAL = "#d03b3b"
SERIES   = {"light": ["#2a78d6", "#eb6834", "#1baf7a"], "dark": ["#3987e5", "#d95926", "#199e70"]}

HISTORY_DAYS = 7
CLAUDE_5H_S  = 5 * 3600
CLAUDE_7D_S  = 7 * 86400


def theme_mode() -> str:
    return "dark" if st.context.theme.type == "dark" else "light"


def parse_time(value) -> datetime | None:
    """ISO string, unix timestamp (s or ms) or datetime → aware datetime."""
    try:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 1e12 else value, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


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
                dt = datetime.now(timezone.utc) + timedelta(seconds=secs)
                return dt.astimezone().strftime("%-H:%M:%S %Z")
        local = parse_time(value).astimezone()
        now   = datetime.now(local.tzinfo)
        if local.date() == now.date():
            return local.strftime("%-H:%M %Z")
        elif local.date() == (now + timedelta(days=1)).date():
            return local.strftime("tomorrow %-H:%M %Z")
        else:
            return local.strftime("%a %-H:%M %Z")
    except Exception:
        return str(value)


def grey(text: str) -> str:
    return f"<span style='color:grey'>{text}</span>"


def format_last_used(value, precision: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if precision == "day":
        return dt.strftime("%b %-d")
    local = dt.astimezone()
    if local.date() == datetime.now(local.tzinfo).date():
        return local.strftime("today %-H:%M %Z")
    return local.strftime("%b %-d %-H:%M %Z")


def pace(pct: float, reset_value, window_s) -> dict | None:
    """Compare usage with how much of the window has elapsed, and project when
    the window runs out if usage continues at its average rate so far."""
    reset = parse_time(reset_value)
    if not reset or not window_s:
        return None
    now = datetime.now(timezone.utc)
    remaining = (reset - now).total_seconds()
    elapsed = window_s - remaining
    # ChatGPT reports an unstarted window as resetting one full window from now
    if remaining <= 0 or elapsed < 60:
        return None
    result = {
        "elapsed_pct":  elapsed / window_s * 100,
        "projected":    pct * window_s / elapsed,  # % used by reset at the current rate
        "runs_out":     None,
    }
    # Don't project from the first 5% of a window, where one burst dominates the rate
    if 0 < pct < 100 and elapsed >= window_s * 0.05:
        secs_to_full = (100 - pct) * elapsed / pct
        if secs_to_full < remaining:
            result["runs_out"] = now + timedelta(seconds=secs_to_full)
    return result


def meter(pct: float, color: str, marker_pct: float | None = None, tooltip: str = "") -> str:
    """Thin bar with an optional tick marking how much of the window has elapsed."""
    marker = ""
    if marker_pct is not None:
        marker = (
            f"<div style='position:absolute;left:calc({min(marker_pct, 100):.1f}% - 1px);"
            "top:-3px;bottom:-3px;width:2px;border-radius:1px;"
            "background:currentColor;opacity:.55'></div>"
        )
    return (
        f"<div title='{tooltip}' style='position:relative;height:8px;margin-top:7px;"
        f"border-radius:4px;background:color-mix(in srgb, {color} 22%, transparent)'>"
        f"<div style='width:{min(max(pct, 0), 100):.1f}%;height:100%;border-radius:4px;"
        f"background:{color}'></div>{marker}</div>"
    )


def quota_row(label: str, pct: float, reset_value=None, window_s=None):
    c1, c2, c3 = st.columns([1, 5, 2])
    c1.markdown(f"<small><b>{label}</b></small>", unsafe_allow_html=True)

    p = pace(pct, reset_value, window_s)
    color, status = ACCENT[theme_mode()], ""
    tooltip = f"{pct:.0f}% used"
    if p:
        tooltip += (
            f" · {p['elapsed_pct']:.0f}% of window elapsed"
            f" · on track for {p['projected']:.0f}% by reset"
        )
    if pct >= 100:
        color, status = CRITICAL, "✖ limit reached"
    elif p and p["runs_out"]:
        color, status = WARNING, f"⚠ over pace, out ~{format_reset_time(p['runs_out'])}"
    c2.markdown(meter(pct, color, p and p["elapsed_pct"], tooltip), unsafe_allow_html=True)

    reset = format_reset_time(reset_value)
    note = f"{pct:.0f}%"
    if reset:
        note += f"  resets {reset}"
    if status:
        note += f"<br>{status}"
    c3.markdown(f"<small>{note}</small>", unsafe_allow_html=True)


def credits_row(label: str, used: float, limit: float):
    pct = (used / limit * 100) if limit else 0
    c1, c2, c3 = st.columns([1, 5, 2])
    c1.markdown(f"<small><b>{label}</b></small>", unsafe_allow_html=True)
    color = CRITICAL if pct >= 100 else ACCENT[theme_mode()]
    c2.markdown(meter(pct, color, tooltip=f"{pct:.0f}% used"), unsafe_allow_html=True)
    # "\$" stops Streamlit's markdown from reading "$…$" as LaTeX math
    c3.markdown(f"<small>\\${used:,.2f} / \\${limit:,.2f}</small>", unsafe_allow_html=True)


def history_chart(provider: str, series: dict[str, str], since: float, unit: str = "%",
                  x_format: str = "%a %-d"):
    """Line chart of recorded samples from `since` to now. `series` maps metric → label;
    its order fixes each series' color."""
    rows = [r for r in history.load(provider, since) if r[1] in series]
    if len({r[0] for r in rows}) < 2:
        st.caption("Not enough history yet. A sample is recorded every 10 minutes.")
        return

    df = pd.DataFrame(rows, columns=["ts", "metric", "value"])
    df["time"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    df["series"] = df["metric"].map(series)
    labels = list(series.values())
    present = [label for label in labels if label in set(df["series"])]
    palette = SERIES[theme_mode()]

    if unit == "%":
        df["value"] /= 100
        y = alt.Y("value:Q", title=None, scale=alt.Scale(domain=[0, 1]),
                  axis=alt.Axis(values=[0, 0.5, 1], format=".0%"))
        fmt = ".0%"
    else:
        y = alt.Y("value:Q", title=None, axis=alt.Axis(tickCount=4, format="$,.2f"))
        fmt = "$,.2f"
    color = alt.Color(
        "series:N",
        scale=alt.Scale(domain=present, range=[palette[labels.index(lb)] for lb in present]),
        legend=alt.Legend(orient="top", title=None) if len(present) > 1 else None,
    )

    nearest = alt.selection_point(nearest=True, on="pointerover", fields=["time"], empty=False)
    x = alt.X(
        "time:T", title=None,
        scale=alt.Scale(domain=[pd.Timestamp(since, unit="s", tz="UTC").isoformat(),
                                pd.Timestamp.now(tz="UTC").isoformat()]),
        axis=alt.Axis(format=x_format, tickCount={"interval": "day", "step": 1}, grid=False),
    )
    base = alt.Chart(df).encode(x=x, y=y, color=color)
    lines = base.mark_line(strokeWidth=2, strokeCap="round", strokeJoin="round")
    points = base.mark_circle(size=64).encode(
        opacity=alt.condition(nearest, alt.value(1), alt.value(0))
    )
    rule = (
        alt.Chart(df)
        .transform_pivot("series", value="value", groupby=["time"])
        .mark_rule(color="#898781")
        .encode(
            x="time:T",
            opacity=alt.condition(nearest, alt.value(0.6), alt.value(0)),
            tooltip=[alt.Tooltip("time:T", title="time", format="%a %b %-d %H:%M")]
            + [alt.Tooltip(f"{label}:Q", format=fmt) for label in present],
        )
        .add_params(nearest)
    )
    st.altair_chart(alt.layer(lines, points, rule).properties(height=160), width="stretch")


def info_row(label: str, value: str):
    c1, c2 = st.columns([1, 7])
    c1.markdown(f"<small><b>{label}</b></small>", unsafe_allow_html=True)
    c2.markdown(f"<small>{value}</small>", unsafe_allow_html=True)



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
        if meta.get("stale"):
            fetched = meta.get("fetched_at")
            when = ""
            if fetched:
                mins = int((time.time() - fetched) // 60)
                when = f" ({mins} min old)" if mins else ""
            st.caption(f"⚠ rate-limited — showing cached data{when}")
        quota_row("5 h", float(five_hour.get("utilization") or 0), five_hour.get("resets_at"),
                  CLAUDE_5H_S)
        quota_row("7 d", float(seven_day.get("utilization") or 0), seven_day.get("resets_at"),
                  CLAUDE_7D_S)
        if extra.get("is_enabled"):
            credits_row(
                "credits",
                (extra.get("used_credits") or 0) / 100,
                (extra.get("monthly_limit") or 0) / 100,
            )
        with st.expander(f"History · {HISTORY_DAYS} days"):
            history_chart("claude", {"5h": "5 h", "7d": "7 d"}, time.time() - HISTORY_DAYS * 86400)

    with st.expander("Raw · Claude"):
        st.json({k: v for k, v in data.items() if k != "_meta"})

except RateLimitedError as e:
    st.warning(f"Claude rate-limited.{f' Retry in {e.retry_after}s.' if e.retry_after else ''}")
except TokenExpiredError:
    st.warning("Claude token expired — please reconnect.")
    _render_claude_login()
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
    cred  = cdata.get("credits", {})

    with st.container(border=True):
        st.markdown(f"**ChatGPT** &nbsp; `{plan}`", unsafe_allow_html=True)

        quota_row("5 h", float(fh.get("utilization") or 0), fh.get("reset_at"), fh.get("window_s"))
        quota_row("7 d", float(sd.get("utilization") or 0), sd.get("reset_at"), sd.get("window_s"))
        if cr.get("utilization") is not None:
            quota_row("code review", float(cr.get("utilization") or 0), cr.get("reset_at"),
                      cr.get("window_s"))

        if cred:
            if cred.get("unlimited"):
                info_row("credits", "unlimited")
            else:
                try:
                    bal = float(cred.get("balance") or 0)
                except (TypeError, ValueError):
                    bal = 0.0
                # Balance is Codex credits, not USD; message counts are [min, max] estimates
                value = f"{bal:,.0f} credits"
                loc = cred.get("local_messages") or [0, 0]
                cld = cred.get("cloud_messages") or [0, 0]
                if loc[1] or cld[1]:
                    value += " &nbsp;" + grey(
                        f"~{loc[0]}–{loc[1]} local / {cld[0]}–{cld[1]} cloud msgs"
                    )
                info_row("credits", value)

        with st.expander(f"History · {HISTORY_DAYS} days"):
            history_chart(
                "chatgpt", {"5h": "5 h", "7d": "7 d", "code_review": "code review"},
                time.time() - HISTORY_DAYS * 86400,
            )

    with st.expander("Raw · ChatGPT"):
        st.json(raw)

except (cgpt.ChatGPTNotAuthenticatedError, cgpt.ChatGPTAuthError):
    _render_chatgpt_login()
except Exception as e:
    st.error(f"ChatGPT: {e}")
    st.exception(e)

# ── OpenRouter key entry ──────────────────────────────────────────────────────

def _render_openrouter_setup(error: str | None = None, cancellable: bool = False):
    with st.container(border=True):
        st.markdown("**OpenRouter**", unsafe_allow_html=True)
        if error:
            st.caption(f"⚠ {error}")
        st.markdown(
            "<small>Paste a <a href='https://openrouter.ai/settings/management-keys' "
            "target='_blank'>management key</a> for total spend + last model, "
            "or a regular API key for that key's spend only:</small>",
            unsafe_allow_html=True,
        )
        key_input = st.text_input(
            "OpenRouter API key", key="openrouter_key_input", type="password",
            label_visibility="collapsed", placeholder="sk-or-v1-…",
        )
        col_save, col_cancel, _ = st.columns([1, 1, 5])
        if col_save.button("Save", key="openrouter_save") and key_input:
            try:
                orouter.validate_key(key_input)
            except orouter.OpenRouterAuthError:
                st.error("OpenRouter rejected that key.")
            except Exception as ex:
                st.error(f"Could not verify key: {ex}")
            else:
                orouter.save_key(key_input)
                st.session_state.pop("openrouter_editing", None)
                fetch_openrouter.clear()
                st.rerun()
        if cancellable and col_cancel.button("Cancel", key="openrouter_cancel"):
            st.session_state.pop("openrouter_editing", None)
            st.rerun()


# ── OpenRouter ────────────────────────────────────────────────────────────────

if st.session_state.get("openrouter_editing"):
    _render_openrouter_setup(cancellable=True)
else:
    try:
        odata = fetch_openrouter()

        with st.container(border=True):
            header_col, change_col = st.columns([7, 1])
            badge = "`management key`" if odata.get("is_management") else "`api key`"
            header_col.markdown(f"**OpenRouter** &nbsp; {badge}", unsafe_allow_html=True)
            if change_col.button("change key", key="openrouter_change", type="tertiary"):
                st.session_state.openrouter_editing = True
                st.rerun()

            notes = [f"{datetime.now(timezone.utc):%B} UTC"]
            if odata.get("key_count", 1) > 1:
                notes.append(f"{odata['key_count']} keys")
            if odata.get("byok_month"):
                notes.append(f"+\\${odata['byok_month']:,.2f} BYOK")
            spend = odata.get("spend_month") or 0
            info_row("spent", f"\\${spend:,.2f} &nbsp;{grey(' · '.join(notes))}")

            last = odata.get("last_model")
            if last:
                when = format_last_used(last.get("at"), last.get("precision"))
                info_row("last model", f"{last['model']} &nbsp;{grey(when)}")
            elif not odata.get("is_management"):
                info_row("last model", grey("needs a management key"))
            elif odata.get("last_model_error"):
                info_row("last model", grey(f"unavailable — {odata['last_model_error']}"))
            else:
                info_row("last model", grey("no requests in the last 30 days"))

            month_start = datetime.now(timezone.utc).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            with st.expander("History · this month"):
                history_chart("openrouter", {"spend_month": "spent"}, month_start.timestamp(),
                              unit="$", x_format="%b %-d")

        with st.expander("Raw · OpenRouter"):
            st.json(odata.get("_raw", {}))

    except orouter.OpenRouterKeyMissingError:
        _render_openrouter_setup()
    except orouter.OpenRouterAuthError as e:
        _render_openrouter_setup(error=f"{e} — paste a new one.")
    except Exception as e:
        st.error(f"OpenRouter: {e}")
        st.exception(e)

# ── Footer ────────────────────────────────────────────────────────────────────

st.caption(f"Updated {datetime.now().strftime('%H:%M:%S')}")
