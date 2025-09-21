# app/api.py
from __future__ import annotations

import os
from datetime import datetime
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

# Load env for dev/local; prod still uses systemd EnvironmentFile
try:
    from dotenv import load_dotenv

    load_dotenv(
        dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"),
        override=False,
    )
    if os.path.exists("/etc/mailminder.env"):
        load_dotenv("/etc/mailminder.env", override=False)
except Exception:
    pass

# Import your existing code
from mailminder import db, poller

API_KEY = os.getenv("MAILMINDER_API_KEY")  # optional; set in env for prod

app = FastAPI(title="MailMinder API", version="0.1.1")

# CORS: open for now. Lock to your origin(s) later.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_key(x_api_key: Optional[str] = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


@app.get("/health")
def health():
    # simple DB ping
    try:
        _ = db.fetch_one("SELECT 1")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/poll")
def api_poll(_: bool = Depends(require_key)):
    processed = poller.poll_once(verbose=True)
    return {"ok": True, "processed": processed}


# ---- Messages listing ----

LABEL_TO_SCORE = {"low": 1, "normal": 2, "high": 3}

# importance expression: override wins, else derive from summary_json->>'importance'
IMPORTANCE_EXPR = """
CASE
  WHEN importance_override IS NOT NULL THEN importance_override
  WHEN (summary_json->>'importance') = 'high'   THEN 3
  WHEN (summary_json->>'importance') = 'normal' THEN 2
  WHEN (summary_json->>'importance') = 'low'    THEN 1
  ELSE 0
END
"""


@app.get("/api/messages")
def list_messages(
    q: Optional[str] = Query(None, description="search subject/sender/summary"),
    min_importance: int = Query(0, ge=0, le=3),
    # NEW:
    sort: Literal["received_at", "importance"] = Query("received_at"),
    order: Literal["asc", "desc"] = Query("desc"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    newer_than: Optional[str] = Query(None, description="ISO date e.g. 2025-08-01"),
):
    where = ["1=1"]
    params = {"limit": limit, "offset": offset}

    if newer_than:
        where.append("received_at >= %(newer)s")
        params["newer"] = datetime.fromisoformat(newer_than)

    if q:
        where.append(
            "(subject ILIKE %(q)s OR sender ILIKE %(q)s OR (summary_json->>'summary') ILIKE %(q)s)"
        )
        params["q"] = f"%{q}%"

    if min_importance > 0:
        where.append(f"({IMPORTANCE_EXPR}) >= %(minimp)s")
        params["minimp"] = min_importance

    where_sql = " AND ".join(where)

    # total
    row = db.fetch_one(f"SELECT COUNT(*) AS c FROM messages WHERE {where_sql}", params)
    total = row["c"] if row else 0

    # NEW: build ORDER BY
    order_kw = order.upper()
    if sort == "importance":
        order_by = f"({IMPORTANCE_EXPR}) {order_kw}, received_at DESC"
    else:
        order_by = f"received_at {order_kw}"

    # page
    rows = db.fetch(
        f"""
        SELECT
          message_id AS id,
          subject,
          sender AS from_addr,
          received_at,
          is_read,
          importance_override,
          ({IMPORTANCE_EXPR}) AS importance_num,
          summary_json->>'importance'  AS importance_label,
          summary_json->>'summary'     AS summary_text,
          gmail_permalink,
          thread_id
        FROM messages
        WHERE {where_sql}
        ORDER BY {order_by}
        OFFSET %(offset)s LIMIT %(limit)s
    """,
        params,
    )

    items = []
    for r in rows:
        label = (r["importance_label"] or "normal").lower()
        items.append(
            {
                "id": r["id"],
                "subject": r["subject"],
                "from": r["from_addr"],
                "ts": r["received_at"].isoformat() if r["received_at"] else None,
                "is_read": bool(r["is_read"]),
                "importance": int(r["importance_num"]),
                "importance_label": label,
                "importance_override": r["importance_override"],
                "summary_md": r["summary_text"] or "",
                "thread_id": r["thread_id"],
                "gmail_permalink": r["gmail_permalink"],
            }
        )

    return {"total": total, "count": len(items), "items": items}


# ---- Single message ----


@app.get("/api/messages/{msg_id}")
def get_message(msg_id: str):
    row = db.fetch_one(
        """
      SELECT
        message_id AS id,
        subject,
        sender AS from_addr,
        received_at,
        is_read,
        importance_override,
        ({imp}) AS importance_num,
        summary_json->>'importance'  AS importance_label,
        summary_json->>'summary'     AS summary_text,
        gmail_permalink,
        thread_id
      FROM messages
      WHERE message_id = %(id)s
      LIMIT 1
    """.format(
            imp=IMPORTANCE_EXPR
        ),
        {"id": msg_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")

    label = (row["importance_label"] or "normal").lower()
    return {
        "id": row["id"],
        "subject": row["subject"],
        "from": row["from_addr"],
        "ts": row["received_at"].isoformat() if row["received_at"] else None,
        "is_read": bool(row["is_read"]),
        "importance": int(row["importance_num"]),
        "importance_label": label,
        "importance_override": row["importance_override"],
        "summary_md": row["summary_text"] or "",
        "thread_id": row["thread_id"],
        "gmail_permalink": row["gmail_permalink"],
    }


class MessagePatch(BaseModel):
    # all optional; send only what you want to change
    is_read: Optional[bool] = None
    # 0..3 or null to clear the override
    importance_override: Optional[int] = None

    @field_validator("importance_override")
    @classmethod
    def _check_imp(cls, v):
        if v is None:
            return v
        if not (0 <= v <= 3):
            raise ValueError("importance_override must be 0..3 or null")
        return v


@app.patch("/api/messages/{msg_id}")
def update_message(msg_id: str, patch: MessagePatch, _: bool = Depends(require_key)):
    # Build dynamic SET/params
    sets = []
    params = {"id": msg_id}

    if patch.is_read is not None:
        sets.append("is_read = %(is_read)s")
        params["is_read"] = bool(patch.is_read)

    if "importance_override" in patch.model_fields_set:
        # allow NULL to clear
        sets.append("importance_override = %(imp)s")
        params["imp"] = patch.importance_override

    if not sets:
        raise HTTPException(status_code=400, detail="No fields to update")

    sql = f"""
        UPDATE messages
        SET {", ".join(sets)}, processed_at = now()
        WHERE message_id = %(id)s
        RETURNING
          message_id AS id,
          subject,
          sender AS from_addr,
          received_at,
          is_read,
          importance_override,
          ({IMPORTANCE_EXPR}) AS importance_num,
          summary_json->>'importance' AS importance_label,
          summary_json->>'summary'    AS summary_text,
          gmail_permalink,
          thread_id
    """
    row = db.fetch_one(sql, params)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")

    label = (row["importance_label"] or "normal").lower()
    return {
        "id": row["id"],
        "subject": row["subject"],
        "from": row["from_addr"],
        "ts": row["received_at"].isoformat() if row["received_at"] else None,
        "is_read": bool(row["is_read"]),
        "importance": int(row["importance_num"]),
        "importance_label": label,
        "importance_override": row["importance_override"],
        "summary_md": row["summary_text"] or "",
        "thread_id": row["thread_id"],
        "gmail_permalink": row["gmail_permalink"],
    }


# --------- Models ---------
class ActionItemCreate(BaseModel):
    message_id: str = Field(..., description="messages.message_id")
    title: str
    importance: int = Field(2, ge=0, le=3)


class ActionItemPatch(BaseModel):
    title: Optional[str] = None
    importance: Optional[int] = Field(None, ge=0, le=3)
    is_done: Optional[bool] = None


# --------- List ---------
@app.get("/api/action-items")
def list_action_items(
    is_done: Optional[str] = Query(None, description="0,1 or omit"),
    min_importance: int = Query(0, ge=0, le=3),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    message_id: Optional[str] = None,
):
    where = ["1=1"]
    params = {"limit": limit, "offset": offset}

    if message_id:
        where.append("message_id = %(mid)s")
        params["mid"] = message_id

    if is_done in ("0", "1"):
        where.append("is_done = %(done)s")
        params["done"] = is_done == "1"

    if min_importance > 0:
        where.append("importance >= %(minimp)s")
        params["minimp"] = min_importance

    where_sql = " AND ".join(where)

    total = db.fetch_one(
        f"SELECT COUNT(*) AS c FROM action_items WHERE {where_sql}", params
    )["c"]

    rows = db.fetch(
        f"""
      SELECT id, message_id, title, importance, is_done, created_at, done_at
      FROM action_items
      WHERE {where_sql}
      ORDER BY is_done ASC, importance DESC, created_at DESC
      OFFSET %(offset)s LIMIT %(limit)s
    """,
        params,
    )

    return {"total": total, "count": len(rows), "items": rows}


# --------- Create ---------
@app.post("/api/action-items")
def create_action_item(body: ActionItemCreate, _: bool = Depends(require_key)):
    row = db.fetch_one(
        """
      INSERT INTO action_items (message_id, title, importance)
      VALUES (%(message_id)s, %(title)s, %(importance)s)
      RETURNING id, message_id, title, importance, is_done, created_at, done_at
    """,
        body.model_dump(),
    )
    return row


# --------- Update ---------
@app.patch("/api/action-items/{ai_id}")
def update_action_item(
    ai_id: str, patch: ActionItemPatch, _: bool = Depends(require_key)
):
    sets, params = [], {"id": ai_id}
    if patch.title is not None:
        sets.append("title = %(title)s")
        params["title"] = patch.title
    if patch.importance is not None:
        sets.append("importance = %(imp)s")
        params["imp"] = patch.importance
    if patch.is_done is not None:
        sets.append("is_done = %(done)s")
        params["done"] = patch.is_done
        sets.append("done_at = (CASE WHEN %(done)s THEN now() ELSE NULL END)")

    if not sets:
        raise HTTPException(400, "No fields to update")

    row = db.fetch_one(
        f"""
      UPDATE action_items
      SET {", ".join(sets)}
      WHERE id = %(id)s
      RETURNING id, message_id, title, importance, is_done, created_at, done_at
    """,
        params,
    )
    if not row:
        raise HTTPException(404, "Not found")
    return row


# --------- Delete ---------
@app.delete("/api/action-items/{ai_id}")
def delete_action_item(ai_id: str, _: bool = Depends(require_key)):
    n = db.execute("DELETE FROM action_items WHERE id = %(id)s", {"id": ai_id})
    if n == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True, "deleted": ai_id}
