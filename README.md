# Gmail document reader (read-only)

A small command-line tool. It connects to Gmail over IMAP in **read-only** mode, searches emails, saves their attachments by date and pulls out the text of PDF, Excel (`.xlsx`, `.xls`) and Word (`.docx`) files, with OCR for scanned PDF pages. It can also summarize each document in Egyptian Arabic.

There's no size limit: attachments come straight from Gmail to your Mac, so large reports such as the night reports download in full.

## Safety

- **Encrypted connection:** it uses IMAP over SSL only (`imap.gmail.com:993`) and checks Google's certificate.
- **Read-only mailbox:** the mailbox is opened with `EXAMINE`, never `SELECT`, so Gmail itself refuses any change.
- **Emails stay unread:** messages are fetched with `BODY.PEEK[]`, which doesn't mark them as read.
- **Changes are blocked in the code too:** commands that move, copy, delete, flag or expunge are refused before they reach Gmail (see `mailtool/imap_client.py`).
- **Credentials:** they're read only from `.env`. They're never printed or logged, and `.env` is git-ignored.
- **Safe file names:** attachment names are cleaned so a file can't be written outside `attachments/`.
- **Summaries use the Anthropic API:** `--summarize` sends the document (the PDF itself, or the text extracted from an Excel or Word file) to Anthropic to be summarized. Nothing else leaves your computer.

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

# Download the documents and extract their text
python mail_tool.py fetch --subject "Daily Morning Briefing Minutes" --days 2

# Same, plus an Egyptian Arabic summary of each document
python mail_tool.py fetch --subject "Daily Morning Briefing Minutes" --days 2 --summarize

# Night reports: Excel + Word attachments, any size
python mail_tool.py fetch --subject "Night reports" --days 1 --summarize

# Every document that arrived today
python mail_tool.py fetch --days 1 --summarize

# Other filters
python mail_tool.py search --from exec.secretary@sunnydaysegypt.com --since 2026-10-01 --before 2026-10-15
python mail_tool.py search --subject "Briefing" --mailbox "[Gmail]/All Mail"

# Work on files you already have
python mail_tool.py extract "attachments/2026-10-22/Daily Beriefing 22102026.pdf" --ocr always
python mail_tool.py summarize "attachments/2026-10-23/Communication Sheet October 2026 - Copy.xlsx"
```

### Output

```
attachments/
  2026-10-22/
    Daily Beriefing 22102026.pdf              # the attachment
    Daily Beriefing 22102026.pdf.txt          # extracted text (page-by-page, with method used)
    Daily Beriefing 22102026.pdf.summary.md   # Egyptian Arabic summary (with --summarize)
  2026-10-23/
    Communication Sheet October 2026 - Copy.xlsx
    Communication Sheet October 2026 - Copy.xlsx.txt         # every sheet, cells tab-separated
    Communication Sheet October 2026 - Copy.xlsx.summary.md
```

- `fetch` saves documents (PDF, Excel, Word) by default and skips logos and other images. Add `--all-types` to save every attachment.
- Older Word files (`.doc`) aren't read yet; save them as `.docx` first.
- Re-running a command doesn't create duplicates: an identical file that's already saved is skipped.

### How the text is extracted

**Excel and Word**
- **Excel:** every sheet is read, using the values Excel last calculated (not the formulas). Empty rows are dropped.
- **Word:** paragraphs and tables are read in document order. Images inside the document aren't read.
- **Monthly workbooks:** the summary focuses on the latest day and compares it with the day before.
- **Very long files:** above 500,000 characters, only the first part is summarized, and the summary says so.

**PDF**
- **Normal pages:** the PDF's own text layer is used.
- **OCR:** Tesseract (Arabic and English) reads a page when it has almost no text (a scan) or when its Arabic text layer is scrambled. Scrambled Arabic is common in PDFs exported from Word.
- **Forcing it:** `--ocr always` OCRs every page, and `--ocr never` turns OCR off.
- **Known issue:** Tesseract sometimes misreads Arabic-Indic digits (٢٨). The summary isn't affected, because Claude reads the PDF pages directly rather than the extracted text.

## Tests

```bash
pip install pytest
python -m pytest -q
```
