"""One-time OAuth sign-in that creates a read-only Gmail refresh token.

Runs on your own computer: it opens Google's sign-in page, receives the
answer on a local port, and writes GMAIL_REFRESH_TOKEN into .env. The token
is never printed.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from .config import ConfigError
from .gmail_api import SCOPE, TOKEN_URL

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def run_auth_flow(client_id: str, client_secret: str, env_file: Path, login_hint: str = "") -> None:
    if not client_id or not client_secret:
        raise ConfigError("set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env first (see README)")

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if params.get("state") != state:
                self.send_response(400)
                self.end_headers()
                return
            result.update(params)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>تم — تقدر تقفل الصفحة دي وترجع للـ Terminal.</h2>".encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **({"login_hint": login_hint} if login_hint else {}),
    })

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    print("Opening Google sign-in in your browser. If it doesn't open, visit:\n" + url)
    webbrowser.open(url)
    thread.join(timeout=300)
    server.server_close()

    if "code" not in result:
        raise PermissionError(f"sign-in did not complete ({result.get('error', 'timed out')})")

    data = urllib.parse.urlencode({
        "code": result["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data), timeout=30) as resp:
        body = json.load(resp)
    if body.get("scope") and body["scope"].split() != [SCOPE]:
        raise PermissionError("Google granted more than read-only access; aborting")
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        raise PermissionError("Google did not return a refresh token; try again")

    _set_env_value(env_file, "GMAIL_REFRESH_TOKEN", refresh_token)
    print(f"Saved GMAIL_REFRESH_TOKEN to {env_file.name} (read-only Gmail access).")


def _set_env_value(env_file: Path, key: str, value: str) -> None:
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    lines = [line for line in lines if not line.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_file.chmod(0o600)
