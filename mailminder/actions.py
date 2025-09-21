# mailminder/actions.py
from __future__ import annotations

import re
from typing import Any, Dict, List

# Very simple bullet/numbered line detector for fallback extraction
_ACTION_RE = re.compile(r"^(?:[-*]\s+|\d+\.\s+)(?P<title>.+)$")


def normalize_items(items: List[Any]) -> List[Dict[str, Any]]:
    """
    Accepts a list that may contain strings or dicts and normalizes to:
      [{"title": str, "importance": int}, ...]
    Unknown fields are ignored.
    """
    norm: List[Dict[str, Any]] = []
    for it in items or []:
        if isinstance(it, str):
            title = it.strip()
            if title:
                norm.append({"title": title, "importance": 2})
        elif isinstance(it, dict):
            title = (it.get("title") or it.get("task") or "").strip()
            if title:
                imp = it.get("importance")
                if isinstance(imp, str):
                    imp = {"low": 1, "normal": 2, "high": 3}.get(imp.lower(), 2)
                if not isinstance(imp, int) or not (0 <= imp <= 3):
                    imp = 2
                norm.append({"title": title, "importance": imp})
    # de‑dupe by lowercase title (preserve first importance)
    seen = set()
    out = []
    for n in norm:
        k = n["title"].lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(n)
    return out


# Keep your existing normalize_items(...) import/definition

_QUOTED_LINE = re.compile(r"^\s*>+")  # replies/quotes
_SIG_LINE = re.compile(r"^\s*--\s*$")  # signature delimiter
_URL = re.compile(r"https?://\S+")
_WHITESPACE = re.compile(r"\s+")


# Fast, naive sentence splitter: periods, question marks, exclamations, or line breaks
def _split_sentences(text: str) -> List[str]:
    text = _URL.sub("", text or "")
    text = _WHITESPACE.sub(" ", text)
    # preserve hard breaks as sentence cuts
    text = text.replace("\r", "\n")
    parts = re.split(r"(?<=[\.\?!])\s+|\n+", text)
    return [p.strip() for p in parts if p and len(p.strip()) >= 4]


# Looser heuristics for “could be an action”
_ACTION_TRIGGERS = (
    # polite/requests
    "please",
    "could you",
    "can you",
    "would you",
    "let me know",
    "follow up",
    "circle back",
    "confirm",
    "review",
    "share",
    "send",
    "provide",
    "update",
    "schedule",
    "book",
    "set up",
    "arrange",
    "reply",
    "respond",
    "sign",
    "approve",
    # deadlines / time
    "by eod",
    "by tomorrow",
    "by monday",
    "by friday",
    "today",
    "this week",
    "deadline",
    "due",
    "asap",
    "urgent",
    # files/tasks
    "attach",
    "attachment",
    "draft",
    "doc",
    "invoice",
    "payment",
    "pay",
    "ticket",
    "bug",
    "fix",
    "implement",
)

# Importance bumpers
_HIGH_HINTS = ("asap", "urgent", "by eod", "deadline", "due ", "tomorrow")


def _is_candidate(s: str) -> bool:
    s_low = s.lower()
    if len(s) < 8:
        return False
    if s.count("@") > 2:  # likely a footer
        return False
    if s.endswith(("thanks", "thank you", "best")):
        return False
    if s.startswith(("On ", "From:", "To:", "Subject:")):
        return False
    if _QUOTED_LINE.match(s):
        return False
    # imperative-ish: starts with a verb-like word
    if re.match(r"^(please|let\'?s|kindly)\b", s_low):
        return True
    if re.match(
        r"^[A-Za-z]+(e|)r\b", s
    ):  # rough: words ending with r (Review/Consider/Follow etc.) – generous
        pass
    # contains any trigger or is a direct question request
    if any(t in s_low for t in _ACTION_TRIGGERS):
        return True
    if s_low.endswith("?") and any(
        k in s_low for k in ("can", "could", "would", "will", "do you", "are you")
    ):
        return True
    # colon sections like "Action items:", "Next steps:"
    if re.match(r"^(action items?|next steps?|todo|to-do)\s*:?", s_low):
        return True
    return False


def _importance_from_text(s: str) -> int:
    s_low = s.lower()
    if any(h in s_low for h in _HIGH_HINTS):
        return 3
    # mild bump if it has a date-like pattern
    if re.search(
        r"\b(?:mon|tue|wed|thu|fri|sat|sun|today|tomorrow)\b", s_low
    ) or re.search(r"\b\d{1,2}/\d{1,2}\b", s_low):
        return 2
    return 2


def fallback_extract_from_body(body: str) -> List[Dict[str, Any]]:
    """
    Loose extraction: split into sentences, keep anything that looks like a request,
    deadline, or instruction. Return up to 5 unique items.
    """
    if not body:
        return []

    # stop at signature or heavily quoted blocks
    lines = []
    for ln in body.splitlines():
        if _SIG_LINE.match(ln):
            break
        if _QUOTED_LINE.match(ln):
            continue
        lines.append(ln)
    text = "\n".join(lines).strip()

    candidates = [s for s in _split_sentences(text) if _is_candidate(s)]
    # De-dup by lowercase sentence
    seen = set()
    items = []
    for s in candidates:
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({"title": s, "importance": _importance_from_text(s)})
        if len(items) >= 5:
            break

    # If still nothing, fall back to first informative sentence
    if not items:
        for s in _split_sentences(text):
            if len(s.split()) >= 6:
                items.append({"title": s, "importance": 2})
                break

    return normalize_items(items)


def extract_actions(
    summary_json: Dict[str, Any], *, body: str = ""
) -> List[Dict[str, Any]]:
    """
    Primary entrypoint. Prefer items from summary_json['action_items'].
    If empty, try a naive body extractor so dev runs still show something.
    """
    items = summary_json.get("action_items") or []
    norm = normalize_items(items)
    if norm:
        return norm
    # fallback only if nothing from the model
    return fallback_extract_from_body(body)
