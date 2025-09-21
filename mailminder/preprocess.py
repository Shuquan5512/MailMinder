"""
preprocess.py
-------------
Utilities to clean raw Gmail messages so the LLM sees only the
signal, not the noise.

Key API:

    clean_email(subject, body, headers?)            -> {'subject', 'body'}
    clean_email_batch(list[(subj, body)], headers?) -> list[(subj, body)]

New helpers for pipeline v2:

    clean_gmail_message(msg_dict)   -> dict with id/threadId/…/body/headers
    clean_gmail_batch(msgs)         -> list of those dicts
"""

from __future__ import annotations

import base64
import email.utils as eut
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from email_reply_parser import EmailReplyParser

# ---------------------------------------------------------------------
# 1. shared cleaning primitives
_MAX_CHARS = 1500
_URL_RE = re.compile(r"https?://\S+")
_PROMO_HINTS = ("unsubscribe", "newsletter", "/u/0/w", "/r/?r=")


def _truncate(text: str, limit: int = _MAX_CHARS) -> str:
    if len(text) <= limit:
        return text.strip()
    return text[: limit - 1].rstrip() + "…"


def _simplify_urls(text: str) -> str:
    return _URL_RE.sub("[link]", text)


def _looks_like_promo(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in _PROMO_HINTS)


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------------
# 2. high-level cleaning used by *both* tuple & Gmail helpers
def clean_email(
    subject: str,
    body: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Return a dict with cleaned 'subject' and 'body'."""
    # 1. Skip obvious promos -- uncomment if desired
    # if _looks_like_promo(body):
    #     return {"subject": subject.strip(), "body": "(automated promo skipped)"}

    # 2. Strip quoted replies / sig
    body_clean = EmailReplyParser.parse_reply(body or "")

    # 3. Convert HTML to text if needed
    if "<html" in body_clean.lower() or "</" in body_clean[:200]:
        body_clean = _html_to_text(body_clean)

    # 4. Replace URLs then truncate
    body_clean = _simplify_urls(body_clean)
    body_clean = _truncate(body_clean)

    # 5. Normalise subject
    subject_clean = subject.strip() or "(no subject)"

    # 6. Prepend sender if headers provided
    if headers:
        sender = headers.get("From", "")
        if sender:
            subject_clean = f"{sender}: {subject_clean}"

    return {"subject": subject_clean, "body": body_clean}


# ---------------------------------------------------------------------
# 3. **original** batch helper (tuple-in / tuple-out) – stays unchanged
def clean_email_batch(
    emails: List[Tuple[str, str]],
    headers_list: Optional[List[Optional[Dict[str, str]]]] = None,
) -> List[Tuple[str, str]]:
    cleaned: List[Tuple[str, str]] = []
    for i, (subject, body) in enumerate(emails):
        headers = headers_list[i] if headers_list and i < len(headers_list) else None
        result = clean_email(subject, body, headers)
        cleaned.append((result["subject"], result["body"]))
    return cleaned


# ---------------------------------------------------------------------
# 4. 🔥 NEW — helpers for raw Gmail message dicts
_HEADER_MAP_CACHE: Dict[str, Dict[str, str]] = {}


def _headers_to_dict(headers: List[Dict[str, str]]) -> Dict[str, str]:
    # Gmail repeats identical header lists → cache for speed
    hdr_tuple = tuple(sorted((h["name"], h["value"]) for h in headers))
    key = str(hdr_tuple)
    if key not in _HEADER_MAP_CACHE:
        _HEADER_MAP_CACHE[key] = {h["name"]: h["value"] for h in headers}
    return _HEADER_MAP_CACHE[key]


def _decode_part(part: Dict[str, Any]) -> str:
    """Recursively walk MIME parts and return the first text/plain body."""
    mime_type = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    if data and (mime_type == "text/plain" or mime_type.startswith("text/")):
        try:
            return base64.urlsafe_b64decode(data.encode()).decode(
                "utf-8", errors="replace"
            )
        except Exception:
            return ""
    # Dive into sub-parts
    for sub in part.get("parts", []):
        text = _decode_part(sub)
        if text:
            return text
    return ""  # fallthrough


def _parse_received_at(internal_date: str | None, headers: Dict[str, str]) -> int:
    """
    Return epoch milliseconds (int) for received time.
    Prefer Gmail internalDate; fall back to Date header.
    """
    if internal_date:
        try:
            return int(internal_date)  # Gmail gives ms since epoch as string
        except Exception:
            pass
    # Fallback: Date header -> epoch ms
    dt_hdr = headers.get("Date") or headers.get("date")
    if dt_hdr:
        try:
            dt = eut.parsedate_to_datetime(dt_hdr)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            pass
    # Last resort: now
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def clean_gmail_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simplify a raw Gmail API `users.messages.get` response
    and return cleaned text ready for LLM & DB insert.
    """
    payload = msg.get("payload", {}) or {}
    headers_raw = payload.get("headers", []) or []
    headers = _headers_to_dict(headers_raw)

    subject = headers.get("Subject", "") or ""
    sender = headers.get("From", "") or ""
    # Prefer decoded text/plain; fall back to HTML->text inside _decode_part; then Gmail snippet
    body_raw = _decode_part(payload) or (msg.get("snippet") or "")

    cleaned = clean_email(subject, body_raw, headers)

    labels = msg.get("labelIds", []) or []
    is_read = "UNREAD" not in labels

    # Correct permalink uses the MESSAGE id, not the thread id
    gmail_message_id = msg["id"]
    gmail_permalink = f"https://mail.google.com/mail/u/0/#inbox/{gmail_message_id}"

    internal_ms = _parse_received_at(msg.get("internalDate"), headers)

    return {
        "id": gmail_message_id,
        "threadId": msg.get("threadId"),
        "subject": cleaned["subject"],
        "from": sender,
        "internalDate": str(internal_ms),
        "body": cleaned["body"],
        "headers": headers,
        "is_read": is_read,
        "gmail_permalink": gmail_permalink,
        "labels": labels,
        "historyId": msg.get("historyId"),
    }


def clean_gmail_batch(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Vectorised version of `clean_gmail_message`."""
    return [clean_gmail_message(m) for m in msgs]
