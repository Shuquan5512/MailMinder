import os

from fastapi.testclient import TestClient

# Ensure defaults for CI (no external creds)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/mailminder?sslmode=disable",
)
os.environ.setdefault("MAILMINDER_API_KEY", "dev-key")

from app.api import app  # noqa: E402

client = TestClient(app)


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    assert "ok" in r.json()
