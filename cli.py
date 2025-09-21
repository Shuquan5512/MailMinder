"""Typer-powered CLI for MailMinder."""

from __future__ import annotations

import re

import rich
import typer

from mailminder import (auth, config, db, fetcher, formatter, poller,
                        preprocess, sender, summarizer)

app = typer.Typer(
    add_completion=False,
    help="MailMinder – summarize and digest your Gmail inbox",
)


# ---------------------------------------------------------------------
# optional helper (still used elsewhere in your codebase?)
def remove_tracking_links(text: str) -> str:
    return re.sub(r"https://[\\w.-]*indeed\\.com\\S+", "[job link]", text)


# ---------------------------------------------------------------------
def _bootstrap_user(read_srv) -> dict:
    """
    Look up Gmail profile ➜ ensure a row in `users` table ➜ return it.

    Assumes you can fetch or compute the refresh_token from your auth layer.
    """
    profile = read_srv.users().getProfile(userId="me").execute()
    gmail_user_id = profile.get("emailAddress")  # unique within Gmail
    email_address = profile.get("emailAddress")

    # You may already have the refresh_token cached locally
    refresh_token = (
        auth.get_refresh_token() if hasattr(auth, "get_refresh_token") else ""
    )

    return db.get_or_create_user(gmail_user_id, email_address, refresh_token)


# ---------------------------------------------------------------------
@app.command()
def summarize(
    send: bool = typer.Option(
        False, "--send", help="Send the digest via Gmail after summarizing"
    )
):
    """
    Fetch ➜ clean ➜ LLM summarise ➜ UPSERT to Postgres ➜ (optional) e-mail digest.
    """
    read_srv = auth.get_read_service()
    user_row = _bootstrap_user(read_srv)

    messages_raw = fetcher.fetch_recent(read_srv, config.QUERY, config.MAX_MSGS)
    if not messages_raw:
        typer.secho("No emails matched query.", fg="yellow")
        raise typer.Exit()

    messages_clean = preprocess.clean_gmail_batch(messages_raw)

    # --- per-email JSON summaries + DB insert --------------------------------
    for msg in messages_clean:
        msg["summary"] = summarizer.summarize_single(msg)  # ← new helper
        db.upsert_message(msg, user_row)  # ← foreign-key OK

    # --- build human-readable digest (Markdown) ------------------------------
    digest_md = summarizer.summarize(
        [(m["subject"], m["body"]) for m in messages_clean]
    )
    rich.print(rich.markdown.Markdown(digest_md))

    # --- optionally e-mail the digest ----------------------------------------
    if send:
        html = formatter.wrap_html_body(formatter.markdown_to_html(digest_md))
        send_srv = auth.get_send_service()
        sender.send_digest(send_srv, html)
        typer.secho("Digest emailed!", fg="green")


# ---------------------------------------------------------------------
@app.command()
def cron():
    """Entry point for schedulers/GitHub Actions (always sends)."""
    summarize(send=True)


# ---------------------------------------------------------------------
@app.command("ingest.poll")
def ingest_poll(
    every: int = typer.Option(
        0, help="Run forever; seconds between polls. 0 = run once."
    ),
    query: str | None = typer.Option(None, help="Override Gmail search query."),
    max_msgs: int | None = typer.Option(None, help="Override max messages per cycle."),
):
    """
    Poll Gmail, summarize, and upsert into Postgres.
    Uses MAILMINDER_QUERY / MAILMINDER_MAX_MSGS from config unless overridden.
    """
    if every and every > 0:
        poller.run_forever(every=every, query=query, max_msgs=max_msgs)
    else:
        n = poller.poll_once(query=query, max_msgs=max_msgs, verbose=True)
        typer.secho(f"Processed {n} messages.", fg="green")


# ---------------------------------------------------------------------
if __name__ == "__main__":
    app()
