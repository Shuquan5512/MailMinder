"""Gmail OAuth authentication helpers."""

import os
import pickle

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from . import config


def _ensure_credentials(token_path: os.PathLike, scopes: list[str]):
    """Returns a valid Credentials object, refreshing or running OAuth flow as needed."""
    creds = None
    token_path = os.fspath(token_path)
    if os.path.exists(token_path):
        # token.pkl or token.json both supported
        if token_path.endswith(".pkl"):
            with open(token_path, "rb") as f:
                creds = pickle.load(f)
        else:
            creds = Credentials.from_authorized_user_file(token_path, scopes)
    # Run flow or refresh token if necessary
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                config.CREDENTIALS_FILE, scopes
            )
            creds = flow.run_local_server(port=0)
        # Persist refreshed/new creds
        if token_path.endswith(".pkl"):
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)
        else:
            with open(token_path, "w") as f:
                f.write(creds.to_json())
    return creds


def get_read_service():
    creds = _ensure_credentials(
        config.TOKEN_READ_FILE, [config.SCOPE_READONLY, config.SCOPE_SEND]
    )
    return build("gmail", "v1", credentials=creds)


def get_send_service():
    creds = _ensure_credentials(
        config.TOKEN_SEND_FILE, [config.SCOPE_SEND, config.SCOPE_READONLY]
    )
    return build("gmail", "v1", credentials=creds)
