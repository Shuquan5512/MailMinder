"""
Thin Postgres helper for MailMinder.
Requires env var DATABASE_URL, e.g.
postgresql://postgres:postgres@localhost:5432/mailminder
"""

import json
import os  # ≈ psycopg3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import psycopg
from psycopg.rows import dict_row

_CONN = None


def _get_conn() -> psycopg.Connection:
    global _CONN
    if _CONN is None or _CONN.closed:  # lazy singleton
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError("Set DATABASE_URL before using db.py")
        _CONN = psycopg.connect(dsn, autocommit=True)
    return _CONN


GET_OR_CREATE_USER = """
INSERT INTO users (gmail_user_id, email_address, refresh_token)
VALUES (%(gmail_user_id)s, %(email)s, %(refresh)s)
ON CONFLICT (gmail_user_id) DO UPDATE
   SET refresh_token = EXCLUDED.refresh_token
RETURNING id, gmail_user_id, email_address;
"""


def fetch(sql: str, params: Optional[dict] = None) -> list[dict]:
    """Return all rows as dicts."""
    with _get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params or {})
            return cur.fetchall()


def fetch_one(sql: str, params: Optional[dict] = None) -> Optional[dict]:
    """Return a single row as dict or None."""
    with _get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params or {})
            return cur.fetchone()


def execute(sql: str, params: Optional[dict] = None) -> int:
    """Execute a statement; return affected row count."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            return cur.rowcount


def executemany(sql: str, seq_params: Iterable[dict]) -> int:
    """Execute many; return total affected rows."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, seq_params)
            return cur.rowcount


def get_or_create_user(gmail_user_id: str, email: str, refresh: str) -> dict:
    """Return the users row as a dict, inserting if it doesn't exist yet."""
    conn = _get_conn()
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            GET_OR_CREATE_USER,
            {
                "gmail_user_id": gmail_user_id,
                "email": email,
                "refresh": refresh,
            },
        )
        return cur.fetchone()


UPSERT_SQL = """
INSERT INTO messages (
  message_id, user_id, thread_id, subject, sender, received_at,
  summary_json, is_read, gmail_permalink
)
VALUES (
  %(message_id)s, %(user_id)s, %(thread_id)s, %(subject)s, %(sender)s, %(received_at)s,
  %(summary_json)s::jsonb, %(is_read)s, %(gmail_permalink)s
)
ON CONFLICT (message_id) DO UPDATE
SET
  subject         = EXCLUDED.subject,
  sender          = EXCLUDED.sender,
  received_at     = EXCLUDED.received_at,
  summary_json    = EXCLUDED.summary_json,
  is_read         = EXCLUDED.is_read,
  gmail_permalink = COALESCE(EXCLUDED.gmail_permalink, messages.gmail_permalink),
  processed_at    = now();
"""


def upsert_message(msg_simple: dict, user_row):
    """
    Persist one Gmail message + its summary.
    `msg_simple` is the *cleaned* dict produced by preprocess.clean_gmail_batch.
    """
    conn = _get_conn()
    with conn.cursor() as cur:
        # internalDate is ms; convert robustly to timestamptz
        internal_ms = (
            int(msg_simple["internalDate"])
            if msg_simple.get("internalDate")
            else int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        )
        received_at = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc)

        cur.execute(
            UPSERT_SQL,
            {
                "message_id": msg_simple["id"],
                "user_id": user_row["id"],
                "thread_id": msg_simple.get("threadId"),
                "subject": msg_simple.get("subject") or "",
                "sender": msg_simple.get("from") or "",
                "received_at": received_at,
                "summary_json": json.dumps(msg_simple["summary"]),
                "is_read": bool(msg_simple.get("is_read", False)),
                "gmail_permalink": msg_simple.get("gmail_permalink")
                or f"https://mail.google.com/mail/u/0/#inbox/{msg_simple['id']}",
            },
        )


def upsert_action_items(message_id: str, items: List[Dict[str, Any]]) -> int:
    """
    Insert new action items for message_id, skipping duplicates by (message_id, lower(title)).
    Returns number of inserted rows.
    """
    if not items:
        return 0

    # get existing titles (lowercased) to avoid duplicates
    existing = fetch(
        """
        SELECT lower(title) AS t FROM action_items WHERE message_id = %(mid)s
    """,
        {"mid": message_id},
    )
    have = {r["t"] for r in existing}

    to_add = []
    for it in items:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        if title.lower() in have:
            continue
        imp = it.get("importance", 2)
        if not isinstance(imp, int) or not (0 <= imp <= 3):
            imp = 2
        to_add.append({"mid": message_id, "title": title, "imp": imp})

    if not to_add:
        return 0

    # executemany insert
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO action_items (message_id, title, importance)
                VALUES (%(mid)s, %(title)s, %(imp)s)
            """,
                to_add,
            )
            return cur.rowcount or 0
