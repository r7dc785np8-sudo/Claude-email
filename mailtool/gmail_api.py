"""Read-only Gmail access through the Gmail REST API (HTTPS).

Used where IMAP (port 993) is blocked, e.g. cloud sessions that only allow
HTTPS. The OAuth token is limited to the gmail.readonly scope, so Google
itself refuses any change to the mailbox; this module also only issues GET
requests to the Gmail API.

One-time setup: `python mail_tool.py auth` (see README).
"""

from __future__ import annotations

import base64
import email
import email.policy
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from email.message import EmailMessage

from .config import ConfigError, Settings
from .imap_client import MailSummary, SearchCriteria

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"


def build_query(criteria: SearchCriteria, mailbox: str = "INBOX", raw_query: str | None = None) -> str:
    """Translate the CLI filters to Gmail search syntax."""
    terms: list[str] = []
    if mailbox.upper() == "INBOX":
        terms.append("in:inbox")
    elif mailbox not in ("[Gmail]/All Mail", "ALL"):
        terms.append(f'label:"{mailbox}"')
    if criteria.sender:
        terms.append(f"from:({criteria.sender})")
    if criteria.subject:
        terms.append(f'subject:("{criteria.subject}")')
    since = criteria.resolved_since()
    if since:
        # Gmail's after: is exclusive of the date given, so step back one day.
        terms.append(f"after:{(since - timedelta(days=1)):%Y/%m/%d}")
    if criteria.before:
        terms.append(f"before:{criteria.before:%Y/%m/%d}")
    if raw_query:
        terms.append(raw_query)
    return " ".join(terms)


class GmailApiReader:
    """Same interface as imap_client.GmailReader: search() then fetch()."""

    def __init__(self, settings: Settings, mailbox: str = "INBOX", raw_query: str | None = None):
        if not (settings.gmail_client_id and settings.gmail_client_secret and settings.gmail_refresh_token):
            raise ConfigError(
                "GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN must be set "
                "(run `python mail_tool.py auth` once; see README)."
            )
        self._settings = settings
        self._mailbox = mailbox
        self._raw_query = raw_query
        self._token: str | None = None

    def __enter__(self) -> "GmailApiReader":
        self._token = self._access_token()
        return self

    def __exit__(self, *exc) -> None:
        self._token = None

    def _access_token(self) -> str:
        data = urllib.parse.urlencode({
            "client_id": self._settings.gmail_client_id,
            "client_secret": self._settings.gmail_client_secret,
            "refresh_token": self._settings.gmail_refresh_token,
            "grant_type": "refresh_token",
        }).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data), timeout=30) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as exc:
            # Don't echo the response; report only Google's error code.
            code = _error_code(exc)
            raise PermissionError(
                f"Google refused the Gmail token ({code}). Run `python mail_tool.py auth` again."
            ) from None
        scopes = body.get("scope", "").split()
        if scopes and any(s != SCOPE for s in scopes):
            # Refuse tokens that could modify the mailbox.
            raise PermissionError("the Gmail token has more than read-only access; create it with `auth`")
        return body["access_token"]

    def _get(self, path: str, **params) -> dict:
        url = f"{API}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._token}"})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Gmail API error {exc.code} ({_error_code(exc)}) for {path.split('?')[0]}") from None

    def search(self, criteria: SearchCriteria, limit: int = 50) -> list[str]:
        query = build_query(criteria, self._mailbox, self._raw_query)
        ids: list[str] = []
        page_token = None
        while len(ids) < limit:
            params = {"q": query, "maxResults": min(500, limit - len(ids))}
            if page_token:
                params["pageToken"] = page_token
            data = self._get("messages", **params)
            ids += [m["id"] for m in data.get("messages", [])]
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return list(reversed(ids))  # oldest first, like IMAP UIDs

    def describe(self, message_id: str) -> MailSummary:
        """Headers and attachment names only, without downloading the attachments."""
        data = self._get(f"messages/{urllib.parse.quote(message_id)}", format="full")
        headers = {h["name"].lower(): h["value"] for h in data.get("payload", {}).get("headers", [])}
        names: list[str] = []
        stack = [data.get("payload", {})]
        while stack:
            part = stack.pop()
            stack.extend(part.get("parts", []))
            if part.get("filename"):
                size = part.get("body", {}).get("size", 0)
                names.append(f"{part['filename']}  ({size / 2**20:.1f} MB)")
        return MailSummary(uid=message_id, subject=headers.get("subject", ""),
                           sender=headers.get("from", ""), date=headers.get("date", ""),
                           attachments=names)

    def fetch(self, message_id: str) -> EmailMessage:
        # format=raw returns the whole MIME message, attachments included, in one response.
        data = self._get(f"messages/{urllib.parse.quote(message_id)}", format="raw")
        raw = base64.urlsafe_b64decode(data["raw"] + "=" * (-len(data["raw"]) % 4))
        return email.message_from_bytes(raw, policy=email.policy.default)


def _error_code(exc: urllib.error.HTTPError) -> str:
    try:
        err = json.load(exc).get("error")
        return err if isinstance(err, str) else (err or {}).get("status", str(exc.code))
    except Exception:
        return str(exc.code)
