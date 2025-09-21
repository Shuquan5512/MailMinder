"""
summarizer
~~~~~~~~~~

Two entry-points:

    summarize_single(msg_dict)  -> Dict
        • Takes *one* cleaned Gmail message dict (see preprocess.clean_gmail_message).
        • Returns a small JSON-serialisable dict:
              {
                 "summary": "…",
                 "importance": "high" | "normal" | "low",
                 "action_items": [ "…", … ]   # can be empty list
              }

    summarize(list[(subject, body)]) -> str
        • Your original batch-digest function.  Returns Markdown.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Tuple

import openai

logger = logging.getLogger(__name__)

openai.api_key = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # default; override via env
# ---------------------------------------------------------------------
SYSTEM_SINGLE = {
    "role": "system",
    "content": (
        "You are an e-mail summarisation assistant. "
        "Return a *JSON object only*, no markdown or commentary. "
        "Schema:\n"
        "{\n"
        '  "summary":   string   # concise, one-sentence summary\n'
        '  "importance": "high" | "normal" | "low",\n'
        '  "action_items": string[]  # may be empty if none\n'
        "}\n\n"
        "Use importance=high for anything that looks personal, deadline-driven, "
        "job-related or requiring quick action."
    ),
}

SYSTEM_BATCH = {
    "role": "system",
    "content": (
        "You are a personal e-mail assistant.\n\n"
        "For each email:\n"
        "• Identify the sender and summarise subject + body concisely.\n"
        "• Decide if it's important (personal, deadline, job-related). "
        "List important ones first and be more detailed; non-important "
        "ones (promos, alerts) briefly at the end.\n\n"
        "Deliver a clear, ranked digest of what's worth reading today."
    ),
}


def fake_summary(subject: str, body: str) -> dict:
    return {
        "summary": f"[FAKE] {subject or '(no subject)'} — {body[:150]}...",
        "importance": "normal",
        "action_items": [],
    }


def _heuristic_importance(subject: str, body: str) -> str:
    s = (subject or "").lower()
    b = (body or "").lower()
    high_terms = ("urgent", "asap", "action required", "payment", "invoice", "deadline")
    if any(t in s or t in b for t in high_terms):
        return "high"
    return "normal"


def summarize_single(msg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Dev-mode summarizer: returns a fake summary (no OpenAI/HF calls).
    Output schema:
      {"summary": str, "importance": "low|normal|high", "action_items": []}
    """
    # Gather inputs safely
    subject = (msg.get("subject") or "").strip()
    body = (msg.get("body") or msg.get("body_text") or "").strip()

    # Keep bodies bounded so UIs don't explode
    MAX_BODY = 2000
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY]

    # Generate fake summary
    out = fake_summary(subject, body)

    # Optional: bump importance by heuristic so your UI can demo filters
    out["importance"] = _heuristic_importance(subject, body)

    # Always ensure required keys exist
    out.setdefault("summary", "[FAKE] Summary unavailable.")
    out.setdefault("importance", "normal")
    out.setdefault("action_items", [])

    return out


# ---------------------------------------------------------------------
def summarize_single_openai(msg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Summarise ONE cleaned message (subject/body already stripped) and return JSON.

    Returns a dict like:
    {
        "summary": str,
        "importance": "low" | "normal" | "high",
        "action_items": [ ... ]
    }
    """
    # Always initialize things you might log in except blocks
    raw: str = ""
    subject = (msg.get("subject") or "").strip()
    body = (msg.get("body") or msg.get("body_text") or "").strip()

    # Keep token usage in check
    MAX_BODY = 2000
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY]

    user_content = (
        f"Subject: {subject}\n" f"Body: {body}\n\n" "Respond using the schema exactly."
    )
    messages = [SYSTEM_SINGLE, {"role": "user", "content": user_content}]

    try:
        resp = openai.ChatCompletion.create(
            model=MODEL,
            messages=messages,
            temperature=0.3,
        )
        raw = resp["choices"][0]["message"]["content"] or ""
        summary_json = json.loads(raw)

        # minimal schema hardening
        if not isinstance(summary_json, dict):
            raise json.JSONDecodeError("not a JSON object", raw, 0)

        # ensure keys exist with sane defaults
        summary = summary_json.get("summary")
        importance = (summary_json.get("importance") or "normal").lower()
        action_items = summary_json.get("action_items")

        if importance not in {"low", "normal", "high"}:
            importance = "normal"
        if not isinstance(action_items, list):
            action_items = []

        if not isinstance(summary, str) or not summary.strip():
            # treat as malformed -> trigger fallback below
            raise json.JSONDecodeError("missing/empty 'summary'", raw, 0)

        return {
            "summary": summary.strip(),
            "importance": importance,
            "action_items": action_items,
        }

    except (json.JSONDecodeError, KeyError, openai.error.OpenAIError, TypeError) as exc:
        # Log safely—don't assume raw exists
        preview = raw[:200] if raw else user_content[:200]
        logger.warning("LLM JSON parse/call failed: %s\nPreview: %s", exc, preview)

        # Fallback: wrap plain text into minimal dict
        fallback_summary = (
            raw.strip()
            if isinstance(raw, str) and raw.strip()
            else (
                f"**{subject or '(no subject)'}**\n\n"
                f"{(body[:400] + '…') if body else '(No body content)'}"
            )
        )
        return {
            "summary": fallback_summary,
            "importance": "normal",
            "action_items": [],
        }


# ---------------------------------------------------------------------
def summarize(emails: List[Tuple[str, str]]) -> str:
    """
    Build a single digest Markdown string from a list of (subject, body) tuples.

    This preserves your existing CLI contract.
    """
    user_content = "\n\n".join(
        f"Email {i+1}:\nSubject: {s}\nBody: {b[:2000]}"
        for i, (s, b) in enumerate(emails)
    )
    messages = [SYSTEM_BATCH, {"role": "user", "content": user_content}]
    resp = openai.ChatCompletion.create(
        model=MODEL,
        messages=messages,
        temperature=0.4,
    )
    return resp["choices"][0]["message"]["content"]
