# Gmail PDF reader (read-only)

A small command-line tool. It connects to Gmail over IMAP in **read-only** mode, searches emails, saves their PDF attachments by date, pulls out the text (with OCR for scanned pages) and can summarize each PDF in Egyptian Arabic.

## Safety

- **Encrypted connection:** it uses IMAP over SSL only (`imap.gmail.com:993`) and checks Google's certificate.
- **Read-only mailbox:** the mailbox is opened with `EXAMINE`, never `SELECT`, so Gmail itself refuses any change.
- **Emails stay unread:** messages are fetched with `BODY.PEEK[]`, which doesn't mark them as read.
- **Changes are blocked in the code too:** commands that move, copy, delete, flag or expunge are refused before they reach Gmail (see `mailtool/imap_client.py`).
- **Credentials:** they're read only from `.env`. They're never printed or logged, and `.env` is git-ignored.
- **Safe file names:** attachment names are cleaned so a file can't be written outside `attachments/`.
- **Summaries use the Anthropic API:** `--summarize` sends the PDF to Anthropic to be summarized. Nothing else leaves your computer.

## Setup on a Mac (one time)

```bash
# 1. Install the tools for OCR (needs Homebrew: https://brew.sh)
brew install python tesseract tesseract-lang poppler

# 2. Get the code and install the Python packages
git clone https://github.com/r7dc785np8-sudo/Claude-email.git
cd Claude-email
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Add your credentials
cp .env.example .env
chmod 600 .env
open -e .env        # paste your App Password (and an Anthropic API key if you want summaries)
```

Before this works, Gmail needs IMAP enabled, 2-Step Verification turned on and an App Password created at https://myaccount.google.com/apppasswords. Your Workspace admin must also allow IMAP and App Passwords.

## Usage

Run `source .venv/bin/activate` in each new Terminal window first.

```bash
# List matching emails
python mail_tool.py search --subject "Daily Morning Briefing Minutes" --days 2

# Download the PDFs and extract their text
python mail_tool.py fetch --subject "Daily Morning Briefing Minutes" --days 2

# Same, plus an Egyptian Arabic summary of each PDF
python mail_tool.py fetch --subject "Daily Morning Briefing Minutes" --days 2 --summarize

# Other filters
python mail_tool.py search --from exec.secretary@sunnydaysegypt.com --since 2026-10-01 --before 2026-10-15
python mail_tool.py search --subject "Briefing" --mailbox "[Gmail]/All Mail"

# Work on PDFs you already have
python mail_tool.py extract "attachments/2026-10-22/Daily Beriefing 22102026.pdf" --ocr always
python mail_tool.py summarize "attachments/2026-10-22/Daily Beriefing 22102026.pdf"
```

### Output

```
attachments/
  2026-10-22/
    Daily Beriefing 22102026.pdf          # the attachment
    Daily Beriefing 22102026.txt          # extracted text (page-by-page, with method used)
    Daily Beriefing 22102026.summary.md   # Egyptian Arabic summary (with --summarize)
```

- `fetch` saves only PDFs by default. Add `--all-types` to save every attachment.
- Re-running a command doesn't create duplicates: an identical file that's already saved is skipped.

### How the text is extracted

- **Normal pages:** the PDF's own text layer is used.
- **OCR:** Tesseract (Arabic and English) reads a page when it has almost no text (a scan) or when its Arabic text layer is scrambled. Scrambled Arabic is common in PDFs exported from Word.
- **Forcing it:** `--ocr always` OCRs every page, and `--ocr never` turns OCR off.
- **Known issue:** Tesseract sometimes misreads Arabic-Indic digits (٢٨). The summary isn't affected, because Claude reads the PDF pages directly rather than the extracted text.

## Tests

```bash
pip install pytest
python -m pytest -q
```
