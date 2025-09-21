# mailminder/poller.py
"""
Polling worker for MailMinder (Option A).
Fetches recent Gmail messages, cleans them, summarizes, and upserts into Postgres.

Usage (via CLI entry added in cli.py):
    python cli.py ingest.poll           # run once
    python cli.py ingest.poll --every 30  # run forever, every 30s
"""
from __future__ import annotations

import time
from typing import Dict, List

from googleapiclient.discovery import build

from mailminder.actions import extract_actions

from . import config, db, preprocess, summarizer
from .auth import _ensure_credentials  # reuse your existing helper


def _get_profile(service):
    return service.users().getProfile(userId="me").execute()


def _fetch_recent(service, query: str, max_msgs: int) -> List[dict]:
    from . import fetcher

    return fetcher.fetch_recent(service, query=query, max_msgs=max_msgs)


def poll_once(
    query: str | None = None, max_msgs: int | None = None, verbose: bool = True
) -> int:
    """Run one polling cycle. Returns number of messages processed."""
    query = query or config.QUERY
    max_msgs = max_msgs or config.MAX_MSGS

    # 1) Auth (grab refresh token so we can (up)sert the user)
    creds = _ensure_credentials(
        config.TOKEN_READ_FILE, [config.SCOPE_READONLY, config.SCOPE_SEND]
    )
    service = build("gmail", "v1", credentials=creds)

    profile = _get_profile(service)
    email_addr = profile.get("emailAddress", "unknown@example.com")
    gmail_user_id = email_addr  # stable enough for our schema

    user_row = db.get_or_create_user(
        gmail_user_id=gmail_user_id,
        email=email_addr,
        refresh=creds.refresh_token or "",
    )

    # 2) Pull most recent messages (bounded window from config)
    full_msgs = _fetch_recent(service, query=query, max_msgs=max_msgs)
    if verbose:
        print(
            f"Fetched {len(full_msgs)} Gmail messages (query='{query}', max={max_msgs})."
        )

    # 3) Clean → summarize → upsert message → extract+upsert action items
    cleaned: List[Dict] = preprocess.clean_gmail_batch(full_msgs)
    processed = 0
    for msg in cleaned:
        try:
            # Build summary (fake or OpenAI, depending on your summarize_single)
            summary = summarizer.summarize_single(msg)

            # Upsert the message first
            msg_with_summary = dict(msg)
            msg_with_summary["summary"] = summary
            db.upsert_message(msg_with_summary, user_row)
            processed += 1

            # Extract actions from summary_json (fallback to body bullets if empty)
            body_for_fallback = msg.get("body") or msg.get("body_text") or ""
            items = extract_actions(summary, body=body_for_fallback)
            if items:
                try:
                    inserted = db.upsert_action_items(msg_with_summary["id"], items)
                    if verbose and inserted:
                        print(
                            f"  • Inserted {inserted} action item(s) for {msg_with_summary['id']}"
                        )
                except Exception as ae:
                    if verbose:
                        print(
                            f"! Failed to upsert action items for {msg_with_summary['id']}: {ae}"
                        )

        except Exception as e:
            if verbose:
                print(f"! Failed to process message id={msg.get('id')}: {e}")
            continue

    if verbose:
        print(f"Upserted {processed} messages into DB for {email_addr}.")
    return processed


def run_forever(every: int = 30, query: str | None = None, max_msgs: int | None = None):
    """Run poll loop; sleep `every` seconds between cycles."""
    assert every > 0, "every must be > 0 when running forever"
    while True:
        try:
            poll_once(query=query, max_msgs=max_msgs, verbose=True)
        except Exception as e:
            print("[poll] cycle error:", e)
        time.sleep(every)
