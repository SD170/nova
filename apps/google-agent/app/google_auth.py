"""Google OAuth token handling. The one-time login is scripts/google_login.py; after that
this refreshes the access token automatically. The token file lives in data/ (gitignored)."""

import asyncio
import logging
import os

from .config import GOOGLE_SCOPES, Settings
from .models import GoogleLoginExpired

log = logging.getLogger(__name__)


class GoogleAuth:
    def __init__(self, settings: Settings):
        self.token_path = settings.token_path
        self.expired = False
        self._creds = None
        self._lock = asyncio.Lock()

    def status(self) -> str:
        """'ok' | 'not_set_up' | 'expired' (expired is only known after a failed refresh)."""
        if not self.token_path.exists():
            return "not_set_up"
        return "expired" if self.expired else "ok"

    def _load(self):
        from google.oauth2.credentials import Credentials

        return Credentials.from_authorized_user_file(str(self.token_path), GOOGLE_SCOPES)

    def _refresh_sync(self):
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request

        creds = self._creds or self._load()
        if not creds.valid:
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                self.expired = True
                raise GoogleLoginExpired(
                    "Google login expired or was revoked. Run `python -m scripts.google_login` "
                    f"again ({exc}).") from exc
            tmp = self.token_path.with_suffix(".tmp")
            tmp.write_text(creds.to_json())
            os.chmod(tmp, 0o600)
            tmp.replace(self.token_path)
        self._creds = creds
        self.expired = False
        return creds.token

    async def access_token(self) -> str:
        if not self.token_path.exists():
            raise GoogleLoginExpired(
                "Google is not connected yet. Run `python -m scripts.google_login` once.")
        async with self._lock:
            return await asyncio.to_thread(self._refresh_sync)
