# scripts/demo_seed.py
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from mailminder import db
from mailminder.actions import extract_actions
from mailminder.summarizer import fake_summary

load_dotenv()


def _mk_fake_email(i: int):
    subjects = [
        "Project Zephyr — next steps",
        "Invoice #2025-{:04d} due Friday".format(i),
        "Please review the draft PRD",
        "Reminder: book travel for conference",
        "Welcome to MailMinder — try the UI",
    ]
    senders = ["alice@acme.com", "billing@vendor.com", "pm@acme.com", "me@example.com"]
    bodies = [
        "- Review the attached doc and leave comments by EOD.\n- Schedule a quick sync tomorrow?\nContext: Need sign-off.",
        "Invoice attached. Please arrange payment by Friday. Thanks!",
        "Could you book the flight and share itinerary by tomorrow?",
        "Please confirm the agenda and send to the team.",
        "Kick the tires: open the UI, toggle read, add an action, mark it done.",
    ]
    return {
        "subject": random.choice(subjects),
        "from": random.choice(senders),
        "body": random.choice(bodies),
    }


def main(n: int = 25):
    # Create or fetch a demo user row (your api uses user_id foreign key)
    user = db.get_or_create_user(
        gmail_user_id="demo@local", email="demo@local", refresh="demo-refresh-token"
    )

    now = datetime.now(tz=timezone.utc)
    added = 0
    for i in range(n):
        e = _mk_fake_email(i)
        mid = f"demo-{i:04d}"
        thread_id = mid
        internal_ms = int((now - timedelta(hours=i)).timestamp() * 1000)

        # Build a “cleaned” message like preprocess.clean_gmail_message would
        cleaned = {
            "id": mid,
            "threadId": thread_id,
            "subject": e["subject"],
            "from": e["from"],
            "internalDate": internal_ms,  # ms epoch
            "body": e["body"],
            "is_read": bool(i % 3 == 0),  # some read, some unread
            "headers": {},
        }

        # Use your fake summarizer and loose action extractor
        summary = fake_summary(cleaned["subject"], cleaned["body"])
        actions = extract_actions(summary, body=cleaned["body"])

        # Upsert message (your db.upsert_message expects summary under 'summary')
        cleaned["summary"] = summary
        db.upsert_message(cleaned, user)

        # Upsert action items
        db.upsert_action_items(cleaned["id"], actions)
        added += 1

    print(f"Seeded {added} demo messages + actions.")


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    main(n)
