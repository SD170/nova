"""One-time Google login. Run from apps/google-agent/:

    .venv/bin/python -m scripts.google_login

Opens your browser; sign in with the Google account you added as a test user and click
Allow. The token is saved to data/google_token.json (gitignored, chmod 600).
Revoke later at https://myaccount.google.com/permissions
"""

import os
import sys

import httpx

from app.config import GOOGLE_SCOPES, get_settings


def main() -> int:
    settings = get_settings()
    if not settings.client_secret_path.exists():
        print(f"Missing {settings.client_secret_path}\n"
              "Download the OAuth 'Desktop app' client JSON from Google Cloud and save it "
              "there (see README, step 1).")
        return 1

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(settings.client_secret_path),
                                                     GOOGLE_SCOPES)
    print("A browser window will open. If Google says 'hasn't verified this app', click "
          "Advanced -> Continue (it's your own app, in Testing mode).")
    creds = flow.run_local_server(port=0, prompt="consent",
                                  authorization_prompt_message="",
                                  success_message="Nova is connected. You can close this tab.")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.token_path.write_text(creds.to_json())
    os.chmod(settings.token_path, 0o600)

    resp = httpx.get("https://gmail.googleapis.com/gmail/v1/users/me/profile",
                     headers={"Authorization": f"Bearer {creds.token}"}, timeout=20)
    if resp.status_code == 200:
        print(f"Connected Gmail account: {resp.json().get('emailAddress')}")
    else:
        print(f"Saved the token, but Gmail returned HTTP {resp.status_code}: {resp.text[:200]}\n"
              "Check that the Gmail API is enabled in your Google Cloud project.")
    print(f"Token saved to {settings.token_path} (never commit it).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
