# ◌ Page Peek - Website Change Detector

A small Python + HTML/CSS project that checks public webpages and saves a new version only when the cleaned page text changes.

## Features

- Add a public URL, friendly name, and check interval (15 minutes to 24 hours).
- Render pages in a headless Chromium browser using Playwright.
- Background scheduler and a manual “Check now” button.
- Save text and screenshot for the first baseline and changed versions only.
- Ignore noisy page regions with CSS selectors; optionally watch only selected regions.
- Basic noise cleanup for clocks, scripts, styles, and token-like text.
- Per-page status, last-checked time, version count, and timeline.
- Unified text diff, saved screenshots, side-by-side comparison, and a highlighted pixel-difference image.
- Optional webhook and email notifications using environment variables.
- SQLite database, no account or stored website credentials.
- Public URL validation rejects localhost and non-public IP addresses.

## Run locally

Python 3.10+ recommended. Use a terminal in this folder:

```bash
python -m venv .venv
```

Windows:
```bash
.venv\Scripts\activate
```

macOS/Linux:
```bash
source .venv/bin/activate
```

Install Python packages and browser:
```bash
pip install -r requirements.txt
playwright install chromium
python app.py
```

Open http://127.0.0.1:5000

If the browser installation command fails, see Playwright's official installation notes and install Chromium for your OS.

## How to use

1. Enter a name and a public URL such as `https://example.com`.
2. Choose a check interval between 15 minutes and 24 hours.
3. Optionally add CSS selectors to watch only, such as `main` or `.announcement`.
4. Optionally add ignored selectors, one per line, such as `.ad-banner` or `#visitor-count`.
5. Click Start watching. The first visit creates the baseline.
6. Use Check now to test the detector, and open View timeline to see versions and diffs.

## Optional notifications

Copy `.env.example` to `.env` and set the values in your environment before starting the app. For this beginner demo, values are read from environment variables; the app does not automatically parse `.env`, so you can set them in your terminal or add `python-dotenv` and load it if you want. Discord webhook payloads include a `content` field. Email requires SMTP details and a sender/recipient.

## How the main logic works

- **Avoid fetching the same URL for every visitor:** checks are per monitored page, not per dashboard viewer. A database uniqueness rule prevents duplicate URL entries.
- **Noise filtering:** scripts/styles are removed, clock-like values and token-like strings are normalized, and user-provided CSS selectors can be removed from the HTML before hashing.
- **Avoid repeated alerts:** the app only creates a new saved version and sends a notification when the normalized text hash changes. Repeated identical checks do not trigger duplicates.
- **Avoid hammering websites:** minimum interval is 15 minutes, one scheduled job per page, checks run serially, and browser navigation has timeouts. Please monitor sites respectfully.
- **Outage or CAPTCHA:** HTTP errors and blocked/rate-limited statuses are shown as `error` or `blocked`, not recorded as a content change. Some CAPTCHA pages may look like normal HTML; inspect the status/error and site behavior.
- **Screenshots:** screenshots are stored only for the first baseline and when normalized text changes. Temporary screenshots from unchanged checks are deleted.
- **Change summary:** the timeline shows a word-level unified diff; optional webhook/email messages include a short diff.
- **Storage:** page data and version text live in `data/page_peek.db`; screenshots are in `data/`. These are local runtime files and are ignored by Git.

## Limits (honest demo scope)

- The scheduler is a lightweight in-process scheduler, not a distributed job queue. If the app is stopped, checks pause.
- A single local app is intended for coursework/demo use, not a public multi-user deployment.
- A CAPTCHA can sometimes return a normal-looking HTML page, so this version cannot identify every CAPTCHA perfectly.
- Region selection is done by entering CSS selectors, not by clicking directly on a screenshot.
- This is a text-change detector with screenshot history, not a pixel-level highlighted image-diff engine.
- The dashboard does not yet implement a daily digest, keyword-only alert mode, charts, or RSS feeds. Region selection uses CSS selector fields rather than a click-on-screenshot picker. Those are bonus features, not required for the basic workflow.

## Project layout

```text
page_peek_detector/
├── app.py
├── database.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── templates/
│   ├── index.html
│   ├── detail.html
│   └── compare.html
├── static/
│   └── style.css
└── data/             # created at runtime; local database/screenshots
```

## Creative touch

The app is named **Page Peek**. The design uses warm cream, muted rose, and sage green, with friendly wording and a tiny magnifying-glass motif. The dashboard feels like a small personal notebook rather than a large monitoring console.
