# Remote Atlas

A personal remote-company directory and job-search tracker, built from your PDF. Runs locally with Python and SQLite. The tracker needs no accounts or dependencies; optional AI company research connects to your Groq account.

## Run

Requires Python 3.10 or newer. In this folder:

```powershell
python app.py
```

Open http://127.0.0.1:8000 in your browser. Stop with Ctrl+C. For another port, use `python app.py --port 8001`. On Windows you can also double-click `Start Remote Atlas.cmd`.

## What you can do

- Switch between dark and light mode with the header toggle. Dark mode is the default; your choice is remembered in this browser.
- Browse all 735 companies extracted from the 25-page source PDF, including original regions and source page references. The PDF title says 640; the actual table contains 735 companies. Its final recruitment-adviser promotional link is excluded.
- Search by company, region, and personal notes. Filter by region and application stage; sort alphabetically, by visit count, latest visit, or follow-up date.
- Open company websites in a new tab. Every use of **Open website** records one click; revisits count again. **Companies explored** counts distinct companies with at least one click. Links opened outside this app are not tracked. A click records your intent to open the site, regardless of whether the destination loads.
- Bookmark companies, view unexplored companies, or pick a random unexplored company from your current filtered selection.
- Keep application stages, notes, and follow-up dates in the company notebook. Pipeline includes every stage except Not started. Applications sent counts Applied, Interviewing, and Offer. Due follow-ups uses your browser's local date, including today. Follow-up dates are shown in the app; there are no background notifications.
- See the latest 200 clicks with local timestamps. All historical clicks remain in SQLite and backups.
- Download a CSV of all companies and progress or a full JSON backup including all click events. CSV export includes protection against spreadsheet formula execution.

## Your data

All changes persist in `data/tracker.sqlite3`. Reopening the app preserves progress. New catalog entries are imported on startup without overwriting existing notes or tracking data. Keep this file backed up. To restore a raw database copy, stop the server and replace `data/tracker.sqlite3` with the saved copy; make database copies only with the server stopped. The JSON download is a portable data export; this version does not have a JSON import screen.

The app binds only to `127.0.0.1` and is intended for personal local use. Company URLs and hiring regions are faithfully imported source data, not verified current hiring information. Region filters match the PDF text; Worldwide is a separate option from India or Asia, and region labels do not guarantee work eligibility. AI research uses Groq browser search when you open an uncached company profile. Personal notes, application status, and visit history are never sent to Groq. Source links in AI profiles open normally; the Open website and Explore their careers page buttons record company visits. The UI uses system fonts and requires no external assets.

## Development

Backend: Python standard library (`http.server`, `sqlite3`, `urllib`). Frontend: vanilla HTML, CSS, and JavaScript. Source catalog: `data/companies.json`. Tests use an isolated temporary database inside this project and never modify your tracker database.

```powershell
python -m unittest discover -s tests -v
node --check static/app.js
```

Only re-extracting the PDF requires an optional dependency:

```powershell
python -m pip install pdfplumber
python scripts/import_pdf.py "D:\Shahid\640 remote first companies.pdf"
```

Wrapped URL fragments are joined during extraction. The company with an empty region is labeled Not specified. The import script reads table data only and does not execute document content.


## AI company profiles

Click a company card or company name to open its profile. **Company profile** holds sourced research; **My tracking & notes** holds your private application details. The card's Notes & tracking button goes straight to your notebook without starting AI research.

1. Open **AI settings** in the header.
2. Paste your Groq key into the password field and select a model (default: `openai/gpt-oss-20b`).
3. Save the connection, then open a company card. Research starts automatically the first time; saved results load immediately on later visits.
4. Use **Refresh details** when you want updated research. Failed refreshes preserve the previous profile.

You can also copy `.env.example` to `.env` and enter your key there, or set `GROQ_API_KEY` and `GROQ_MODEL` as environment variables. Nonempty `.env` values take precedence. The app reads settings for each request, so changing your key does not require restarting the server. Keys stay on the Python backend in the Git-ignored `.env`, and are excluded from JSON backups and CSV exports. Anyone with filesystem access to this computer can read the file; do not share it. Replace a key that has been shared publicly or in chat.

Research uses two Groq calls: browser search for public source material, followed by structured extraction into the profile. Your Groq account must have access to browser search and the selected model. API usage may incur charges and is subject to Groq's rate limits. There is no bulk research: only the companies you open are researched, with at most two concurrent requests. First-time research can take 30–90 seconds or longer; you can close the profile and keep browsing while it finishes. Keep the server running until requests complete.

Profiles include a summary, industry, headquarters, founding year, company size, remote policy, hiring regions, tech stack, hiring activity, source links, an available careers-page link, and suggested next steps. Fields without a cited source show **Not found**. AI output is not verified hiring eligibility; confirm details on the source pages. Opening a profile itself does not increase your click count.

Profiles persist in `company_profiles` in the same SQLite database as your progress, and are included in full JSON backups. CSV continues to export company tracking fields only. No Groq key or private notes are sent to website research. Built-in browser search is provided through Groq; company identity is shared with that service. The app cannot retrieve restricted or paywalled company databases.
