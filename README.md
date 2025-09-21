# MailMinder

MailMinder is a lightweight pipeline + API + UI that summarizes emails and extracts action items.  
It stores messages in Postgres, serves them via a FastAPI backend, and provides a simple modern HTML UI.

> This repository ships with a demo mode — you do not need Gmail, Supabase, or any API keys to try it out.

---

## Features

- Inbox view: list emails with summaries, importance, read/unread state  
- Action items: extracted tasks per email, mark done/undo, change importance, delete  
- Search and filters: filter by importance, date, sender, subject, keywords  
- Inline editing: toggle read/unread, override importance  
- Demo data: generate fake emails with realistic subjects and bodies  
- Single-file UI: open `web/index.html` in your browser  

---

## Quickstart (Demo mode)

This mode runs locally with Docker Postgres and fake emails.  
No Gmail, no Supabase, no OpenAI required.

```bash
git clone https://github.com/Shuquan5512/mailminder.git
cd mailminder

# Python environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Start Postgres (in Docker)
docker compose up -d

# Configure environment
cp .env.example .env

# Create schema
alembic upgrade head

# Seed fake emails and action items
python demo_seed.py   # add optional number, e.g. python demo_seed.py 50

# Run API
uvicorn app.api:app --port 8080 --reload
```

Open `web/index.html` in your browser.  

1. Set API base to `http://localhost:8080` (already default).  
2. Save, then hit Refresh.  
3. Explore Inbox and Action Items tabs.  

---

## Configuration

Edit `.env` (copied from `.env.example`):

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mailminder?sslmode=disable
MAILMINDER_API_KEY=dev-key
MAILMINDER_MAX_MSGS=25
OPENAI_MODEL=gpt-4o-mini
```

- `MAILMINDER_API_KEY` — required for write endpoints (PATCH/POST/DELETE).  
- `DATABASE_URL` — use local Postgres by default; can point to Supabase in real deployments.  
- `OPENAI_*` — unused in demo (summarizer runs in fake mode).  

---

## Project Structure

```
app/          # FastAPI app (api.py)
mailminder/   # core logic (db, poller, summarizer, actions, preprocess)
web/          # frontend (index.html)
migrations/   # alembic migrations
demo_seed.py  # fake email generator for demo mode
```

---

## LLM Support (planned)

The summarizer in this demo uses a fake / heuristic mode so the project runs out of the box without any API keys or GPU setup.

The architecture is already prepared for real LLMs — the `summarizer.py` module can route to:
- OpenAI API (e.g. GPT-4o)  
- Hugging Face models via `transformers`  
- Local models via [Ollama](https://ollama.com)  

We have chosen not to enable this by default because:
- Local models can be slow or unstable without GPU support  
- Cloud APIs require personal keys and may incur cost  

Adding real LLM summarization and action-item extraction is part of the roadmap, but for now the demo ships in stable, cred-free mode so anyone can try it instantly.

---

## Roadmap

- Retention job (auto-clean read emails older than 30 days)  
- HTTPS and domain proxy (Caddy/Nginx in front of FastAPI)  
- Search polish (fuzzy search, include action items)  
- Resummarize and batch operations  
- UI polish (refresh after operations, sidebar layout, notifications)  
- Multi-user support (Google OAuth, per-user inboxes)  
- Real model integration (OpenAI/HuggingFace/Ollama)  
- Improved summaries, action items, and email categorization  

---

## License

MIT License — see [LICENSE](LICENSE).

---