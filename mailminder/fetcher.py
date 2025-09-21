"""
fetcher.py
~~~~~~~~~~

Gmail helpers.

• fetch_recent()        → list[dict]  ← **preferred** (full message objects)
• fetch_recent_legacy() → list[(subj, body)]  ← backwards-compat shim
"""

from __future__ import annotations

import base64
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------
# low-level helpers
def _headers_to_dict(headers: List[Dict[str, str]]) -> Dict[str, str]:
    return {h["name"]: h["value"] for h in headers}


def _extract_plain_body(part: Dict) -> str:
    """
    Walk MIME tree (already from format='full') and return first text/plain part.
    """
    if part.get("mimeType", "").startswith("text/") and "data" in part.get("body", {}):
        try:
            return base64.urlsafe_b64decode(part["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
        except Exception:
            return ""

    for sub in part.get("parts", []):
        text = _extract_plain_body(sub)
        if text:
            return text
    return ""


# ---------------------------------------------------------------------
# main API
def fetch_recent(service, query: str, max_msgs: int = 50) -> List[Dict]:
    """
    Return **full Gmail message dicts** (format='full').
    This is what preprocess.clean_gmail_batch expects.
    """
    results = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_msgs)
        .execute()
    )
    metas = results.get("messages", [])
    out: List[Dict] = []

    for meta in metas:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=meta["id"], format="full")
            .execute()
        )
        out.append(msg)
    return out


# ---------------------------------------------------------------------
# backwards-compat shim
def fetch_recent_legacy(
    service, query: str, max_msgs: int = 50
) -> List[Tuple[str, str]]:
    """
    Return list of (subject, body) tuples for any code that still relies on it.
    Internally uses the new fetch_recent() so we call Gmail only once.
    """
    full_msgs = fetch_recent(service, query, max_msgs)
    tuples: List[Tuple[str, str]] = []

    for msg in full_msgs:
        headers = _headers_to_dict(msg["payload"].get("headers", []))
        subj = headers.get("Subject", "(no subject)")
        body = _extract_plain_body(msg["payload"]) or msg.get("snippet", "")
        tuples.append((subj, body))
    return tuples
