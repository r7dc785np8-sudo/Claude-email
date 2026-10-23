"""Read-only Gmail IMAP access.

Safety rules enforced here:
- TLS only (IMAP4_SSL with a verified certificate).
- Mailboxes are opened with EXAMINE (select(readonly=True)), so the server
  refuses any change to flags or messages for the whole session.
- Messages are fetched with BODY.PEEK[], which never sets the \\Seen flag.
- Every command that could change the mailbox is blocked client-side too.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import re
import ssl
from dataclasses import dataclass
from datetime import date, timedelta
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from .config import IMAP_HOST, IMAP_PORT, ConfigError, Settings


class ReadOnlyViolation(Exception):
    pass


class ReadOnlyIMAP4_SSL(imaplib.IMAP4_SSL):
    """IMAP4_SSL that refuses every command able to modify the mailbox."""

    _BLOCKED = {
        "APPEND", "COPY", "CREATE", "DELETE", "EXPUNGE", "MOVE", "RENAME",
        "STORE", "SUBSCRIBE", "UNSUBSCRIBE", "SETACL", "DELETEACL", "SETQUOTA",
        "SELECT",  # SELECT opens read-write; only EXAMINE is allowed.
    }
    # FETCH items that set \Seen: BODY[...], RFC822, RFC822.TEXT. BODY.PEEK[...] is safe.
    _SEEN_SETTING_FETCH = re.compile(r"\bBODY\[|\bRFC822(?!\.(?:HEADER|SIZE))\b", re.I)

    def _command(self, name, *args):
        command, params = name.upper(), args
        if command == "UID" and args:  # UID FETCH / UID STORE / ...
            command, params = str(args[0]).upper(), args[1:]
        if command in self._BLOCKED:
            raise ReadOnlyViolation(f"IMAP command {command} is not allowed (read-only tool)")
        if command == "FETCH":
            items = " ".join(p.decode() if isinstance(p, bytes) else str(p) for p in params)
            if self._SEEN_SETTING_FETCH.search(items):
                raise ReadOnlyViolation("FETCH must use BODY.PEEK[] so messages stay unread")
        return super()._command(name, *args)

    def select(self, mailbox="INBOX", readonly=True):
        if not readonly:
            raise ReadOnlyViolation("mailboxes may only be opened read-only")
        return super().select(mailbox, readonly=True)  # sends EXAMINE


@dataclass
class SearchCriteria:
    sender: str | None = None
    subject: str | None = None
    since: date | None = None
    before: date | None = None
    days: int | None = None

    def resolved_since(self, today: date | None = None) -> date | None:
        if self.days is not None:
            # "last 2 days" = today and the day before.
            return (today or date.today()) - timedelta(days=max(self.days - 1, 0))
        return self.since


@dataclass
class MailSummary:
    uid: str
    subject: str
    sender: str
    date: str
    attachments: list[str]


def _imap_date(d: date) -> str:
    return d.strftime("%d-%b-%Y")  # IMAP wants e.g. 22-Oct-2026 (English month names)


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_search(criteria: SearchCriteria, today: date | None = None) -> tuple[list[str], bytes | None]:
    """Return (search tokens, optional UTF-8 literal) for IMAP SEARCH.

    IMAP can only carry non-ASCII text as a literal, and imaplib supports one
    literal per command, so at most one of sender/subject may be non-ASCII.
    """
    tokens: list[str] = []
    literal: bytes | None = None
    for key, value in (("FROM", criteria.sender), ("SUBJECT", criteria.subject)):
        if not value:
            continue
        if value.isascii():
            tokens += [key, _quote(value)]
        elif literal is None:
            literal = value.encode("utf-8")
            literal_key = key
        else:
            raise ValueError("Only one of --from/--subject may contain non-English text")
    since = criteria.resolved_since(today)
    if since:
        tokens += ["SINCE", _imap_date(since)]
    if criteria.before:
        tokens += ["BEFORE", _imap_date(criteria.before)]
    if literal is not None:
        tokens.append(literal_key)  # the literal is appended by imaplib after this key
    if not tokens:
        tokens = ["ALL"]
    return tokens, literal


class GmailReader:
    def __init__(self, settings: Settings, mailbox: str = "INBOX"):
        if not settings.has_imap:
            raise ConfigError("IMAP_USER and IMAP_APP_PASSWORD must be set in .env "
                              "(copy .env.example to .env and fill it in).")
        self._settings = settings
        self._mailbox = mailbox
        self._conn: ReadOnlyIMAP4_SSL | None = None

    def __enter__(self) -> "GmailReader":
        ctx = ssl.create_default_context()
        self._conn = ReadOnlyIMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx, timeout=60)
        try:
            self._conn.login(self._settings.imap_user, self._settings.imap_password)
        except imaplib.IMAP4.error:
            # Don't echo server text; it can include the username/auth details.
            raise PermissionError(
                "Gmail rejected the login. Check IMAP is enabled, the App Password is correct, "
                "and your admin allows IMAP/App Passwords."
            ) from None
        status, _ = self._conn.select(_quote(self._mailbox), readonly=True)
        if status != "OK":
            raise RuntimeError(f"Could not open mailbox {self._mailbox!r}")
        return self

    def __exit__(self, *exc) -> None:
        if self._conn is not None:
            try:
                self._conn.close()  # CLOSE after EXAMINE does not expunge anything
            except Exception:
                pass
            try:
                self._conn.logout()
            except Exception:
                pass

    def search(self, criteria: SearchCriteria, limit: int = 50) -> list[str]:
        tokens, literal = build_search(criteria)
        assert self._conn is not None
        if literal is not None:
            self._conn.literal = literal
            status, data = self._conn.uid("SEARCH", "CHARSET", "UTF-8", *tokens)
        else:
            status, data = self._conn.uid("SEARCH", *tokens)
        if status != "OK":
            raise RuntimeError("IMAP search failed")
        uids = data[0].decode().split() if data and data[0] else []
        return uids[-limit:]

    def fetch(self, uid: str) -> EmailMessage:
        assert self._conn is not None
        status, data = self._conn.uid("FETCH", uid, "(BODY.PEEK[])")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            raise RuntimeError(f"Could not fetch message UID {uid}")
        return email.message_from_bytes(data[0][1], policy=email.policy.default)


def summarize_message(uid: str, msg: EmailMessage) -> MailSummary:
    names = [part.get_filename() or "(unnamed)" for part in msg.iter_attachments()]
    return MailSummary(
        uid=uid,
        subject=str(msg.get("Subject", "")),
        sender=str(msg.get("From", "")),
        date=str(msg.get("Date", "")),
        attachments=names,
    )


def message_date(msg: EmailMessage) -> date:
    try:
        return parsedate_to_datetime(str(msg["Date"])).date()
    except (TypeError, ValueError):
        return date.today()
