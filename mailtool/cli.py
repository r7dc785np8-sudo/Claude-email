"""Command-line interface.

Examples:
  python mail_tool.py search --subject "Daily Morning Briefing Minutes" --days 2
  python mail_tool.py fetch  --subject "Daily Morning Briefing Minutes" --days 2 --summarize
  python mail_tool.py extract "attachments/2026-10-22/Daily Beriefing 22102026.pdf"
  python mail_tool.py summarize "attachments/2026-10-22/Daily Beriefing 22102026.pdf"
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .config import PROJECT_ROOT, ConfigError, Settings, load_settings
from .imap_client import GmailReader, SearchCriteria, message_date, summarize_message

DEFAULT_OUTPUT = PROJECT_ROOT / "attachments"


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from None


def _add_search_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--from", dest="sender", help="sender address or name (substring)")
    p.add_argument("--subject", help="text in the subject")
    when = p.add_mutually_exclusive_group()
    when.add_argument("--days", type=int, help="only the last N days, including today")
    when.add_argument("--since", type=_parse_date, help="on or after YYYY-MM-DD")
    p.add_argument("--before", type=_parse_date, help="before YYYY-MM-DD")
    p.add_argument("--mailbox", default="INBOX",
                   help='mailbox to search (default INBOX; e.g. "[Gmail]/All Mail")')
    p.add_argument("--limit", type=int, default=50, help="max emails to process (newest first)")


def _add_pdf_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ocr", choices=("auto", "always", "never"), default="auto",
                   help="OCR scanned pages (auto), every page (always) or none (never)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mail_tool", description="Read-only Gmail attachment reader")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="list matching emails")
    _add_search_args(p)

    p = sub.add_parser("fetch", help="download attachments of matching emails and extract PDF text")
    _add_search_args(p)
    _add_pdf_args(p)
    p.add_argument("--all-types", action="store_true", help="save every attachment, not only PDFs")
    p.add_argument("--summarize", action="store_true",
                   help="summarize each PDF in Egyptian Arabic (needs ANTHROPIC_API_KEY)")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="attachments folder")

    p = sub.add_parser("extract", help="extract text from local PDFs")
    p.add_argument("pdfs", nargs="+", type=Path)
    _add_pdf_args(p)

    p = sub.add_parser("summarize", help="summarize local PDFs in Egyptian Arabic")
    p.add_argument("pdfs", nargs="+", type=Path)
    return parser


def _criteria(args: argparse.Namespace) -> SearchCriteria:
    return SearchCriteria(sender=args.sender, subject=args.subject,
                          since=args.since, before=args.before, days=args.days)


def cmd_search(args: argparse.Namespace, settings: Settings) -> None:
    with GmailReader(settings, args.mailbox) as reader:
        uids = reader.search(_criteria(args))[-args.limit:]
        print(f"{len(uids)} matching email(s)")
        for uid in reversed(uids):
            s = summarize_message(uid, reader.fetch(uid))
            print(f"\n[{s.uid}] {s.date}\n  From:    {s.sender}\n  Subject: {s.subject}")
            for name in s.attachments:
                print(f"  📎 {name}")


def cmd_fetch(args: argparse.Namespace, settings: Settings) -> None:
    from .attachments import save_attachments

    pdfs: list[tuple[Path, str]] = []
    with GmailReader(settings, args.mailbox) as reader:
        uids = reader.search(_criteria(args))[-args.limit:]
        print(f"{len(uids)} matching email(s)")
        for uid in reversed(uids):
            msg = reader.fetch(uid)
            subject = str(msg.get("Subject", ""))
            print(f"\n{subject}  ({msg.get('Date', '')})")
            for item in save_attachments(msg, message_date(msg), args.output, pdf_only=not args.all_types):
                state = "already saved" if item.skipped_existing else "saved"
                print(f"  {state}: {_display(item.path)}")
                if item.path.suffix.lower() == ".pdf":
                    pdfs.append((item.path, subject))

    for path, subject in pdfs:
        _extract_one(path, args.ocr)
        if args.summarize:
            _summarize_one(path, settings, subject)


def _extract_one(path: Path, ocr: str) -> None:
    from .pdf_extract import extract_pdf, write_text

    pages = extract_pdf(path, ocr=ocr)
    out = write_text(pages, path.with_suffix(".txt"))
    methods = ", ".join(f"p{p.number}:{p.method}" for p in pages)
    print(f"  text → {_display(out)}  [{methods}]")


def _summarize_one(path: Path, settings: Settings, subject: str = "") -> None:
    from .summarize import summarize_pdf

    print(f"  summarizing {path.name} …")
    summary = summarize_pdf(path, settings, subject)
    out = path.with_suffix(".summary.md")
    out.write_text(f"# {subject or path.stem}\n\n{summary}\n", encoding="utf-8")
    print(f"  summary → {_display(out)}\n")
    print(summary)


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extract":
            for pdf in args.pdfs:
                _extract_one(pdf, args.ocr)
            return 0
        if args.command == "summarize":
            settings = _summary_settings()
            for pdf in args.pdfs:
                _summarize_one(pdf, settings)
            return 0

        settings = load_settings()
        if args.command == "search":
            cmd_search(args, settings)
        elif args.command == "fetch":
            cmd_fetch(args, settings)
        return 0
    except (ConfigError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        import anthropic
        if isinstance(exc, anthropic.AuthenticationError):
            print("error: the Anthropic API key was rejected; check ANTHROPIC_API_KEY in .env", file=sys.stderr)
        elif isinstance(exc, anthropic.APIConnectionError):
            print("error: could not reach the Anthropic API; check your internet connection", file=sys.stderr)
        elif isinstance(exc, anthropic.APIStatusError):
            print(f"error: Anthropic API returned {exc.status_code}", file=sys.stderr)
        elif isinstance(exc, anthropic.AnthropicError):
            print("error: set ANTHROPIC_API_KEY in .env to use summaries", file=sys.stderr)
        else:
            raise
        return 1


def _summary_settings() -> Settings:
    """Summaries don't need the IMAP password, so don't require it."""
    try:
        return load_settings()
    except ConfigError:
        import os
        return Settings(imap_user="", imap_password="",
                        my_name=os.getenv("MY_NAME", Settings.my_name),
                        my_role=os.getenv("MY_ROLE", Settings.my_role),
                        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None)
