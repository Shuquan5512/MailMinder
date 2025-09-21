"""Centralised configuration.

Environment variables (via a .env file) override defaults so the code
can run locally and in CI without edits.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env if present (ignored in production where secrets come from the environment)
load_dotenv()

# --- Google API scopes ---
SCOPE_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_SEND = "https://www.googleapis.com/auth/gmail.send"

# --- Gmail query defaults ---
QUERY = os.getenv("MAILMINDER_QUERY", "newer_than:3d is:unread category:primary")
MAX_MSGS = int(os.getenv("MAILMINDER_MAX_MSGS", 10))

# --- OAuth credential & token file paths ---
CREDENTIALS_FILE = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json"))
TOKEN_READ_FILE = Path(os.getenv("GOOGLE_TOKEN_READ", "token.json"))
TOKEN_SEND_FILE = Path(os.getenv("GOOGLE_TOKEN_SEND", "token.json"))

# --- LLM settings ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# --- Digest delivery ---
SUMMARY_RECIPIENT = os.getenv("SUMMARY_RECIPIENT", "loganwang5512@gmail.com")
