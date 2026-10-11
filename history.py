"""Usage history: timestamped samples of each provider's numbers in SQLite.

Samples are written by collector.py (in the background) and by the dashboard
whenever it fetches fresh data. Rows older than RETENTION_S are pruned on write.
"""

import fcntl
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path

DATA_DIR    = Path("/data")
DB_FILE     = DATA_DIR / "history.db"
RETENTION_S = 90 * 86400


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS samples ("
        " ts REAL NOT NULL, provider TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS samples_provider_ts ON samples (provider, ts)")
    return conn


def record(provider: str, values: dict[str, float | None]) -> None:
    now = time.time()
    rows = [(now, provider, metric, float(v)) for metric, v in values.items() if v is not None]
    if not rows:
        return
    with closing(_connect()) as conn, conn:
        conn.executemany("INSERT INTO samples VALUES (?, ?, ?, ?)", rows)
        conn.execute("DELETE FROM samples WHERE ts < ?", (now - RETENTION_S,))


def load(provider: str, since: float) -> list[tuple[float, str, float]]:
    """Return (ts, metric, value) rows for a provider since a unix timestamp, oldest first."""
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT ts, metric, value FROM samples WHERE provider = ? AND ts >= ? ORDER BY ts",
            (provider, since),
        ).fetchall()


def last_ts(provider: str) -> float | None:
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT MAX(ts) FROM samples WHERE provider = ?", (provider,)
        ).fetchone()[0]


@contextmanager
def fetch_lock(provider: str):
    """Serialize a provider's API calls across the dashboard and collector processes,
    so two concurrent OAuth refreshes can't invalidate each other's rotated token."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / f".{provider}.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
