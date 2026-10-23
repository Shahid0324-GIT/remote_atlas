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

Use the **AI research** switch in the directory banner to pause all new company-detail fetching, including manual refreshes. Saved profiles and your tracking remain available. The choice is stored in SQLite and survives restarts across browsers on this computer. Requests already sent to Groq may finish after you switch it off. Turn the switch on again to resume research.

1. Open **AI settings** in the header.
2. Paste your Groq key into the password field and select a model (default: `openai/gpt-oss-20b`).
3. Save the connection, then open a company card. Research starts automatically the first time; saved results load immediately on later visits.
4. Use **Refresh details** when you want updated research. Failed refreshes preserve the previous profile.

You can also copy `.env.example` to `.env` and enter your key there, or set `GROQ_API_KEY` and `GROQ_MODEL` as environment variables. Nonempty `.env` values take precedence. The app reads settings for each request, so changing your key does not require restarting the server. Keys stay on the Python backend in the Git-ignored `.env`, and are excluded from JSON backups and CSV exports. Anyone with filesystem access to this computer can read the file; do not share it. Replace a key that has been shared publicly or in chat.

Research uses two Groq calls: browser search for public source material, followed by structured extraction into the profile. Your Groq account must have access to browser search and the selected model. API usage may incur charges and is subject to Groq's rate limits. There is no bulk research: only the companies you open are researched, with at most two concurrent requests. First-time research can take 30–90 seconds or longer; you can close the profile and keep browsing while it finishes. Keep the server running until requests complete.

Profiles include a summary, industry, headquarters, founding year, company size, remote policy, hiring regions, tech stack, hiring activity, source links, an available careers-page link, and suggested next steps. Fields without a cited source show **Not found**. AI output is not verified hiring eligibility; confirm details on the source pages. Opening a profile itself does not increase your click count.

Profiles persist in `company_profiles` in the same SQLite database as your progress, and are included in full JSON backups. CSV continues to export company tracking fields only. No Groq key or private notes are sent to website research. Built-in browser search is provided through Groq; company identity is shared with that service. The app cannot retrieve restricted or paywalled company databases.

## Sharing a temporary demo

`python app.py --demo --port 8002` runs a separate demo using `data/demo.sqlite3`. AI research and key settings are disabled on the server, and visitors can experiment with the demo's shared bookmarks, click history and notes. The personal database is not copied or exposed. Pair this with a temporary Cloudflare Tunnel to `http://127.0.0.1:8002`; keep the computer awake while sharing. Anyone with the tunnel URL can use this demo. Demo notes are shared among all visitors, so do not enter private information there.

For the sharing session started by Codex, double-click **Stop Demo Sharing.cmd** to stop its tunnel and demo server. This leaves your personal tracker running. Local tunnel binaries and session logs live in Git-ignored `.local-tools/` and `.share/` folders. The generated public URL changes when a new quick tunnel is created.


## Experimental local job matching (feature/local-job-matching)

This feature is developed on its own branch. `main` is not merged or changed by the experiment. It uses public job feeds and local skill matching; scanning does not call Groq and is independent of the AI research toggle.

### Try it on Windows

1. Double-click **Setup Job Scanner.cmd** once. It creates an isolated `.venv-scanner`, installs Playwright and pypdf, and downloads a headless Chromium browser into the ignored `.local-tools` folder. Setup is already completed on the current development computer.
2. Double-click **Start Job Scanner.cmd**. It opens `http://127.0.0.1:8003` with a **separate** `data/scanner-experiment.sqlite3` database. Your existing `data/tracker.sqlite3` and the public demo database are not copied or edited. Groq research starts disabled in this experiment.
3. Open **Matching jobs (LAB)**. Paste your resume or import a text PDF / `.txt`, review the text, and save. Only extracted resume text is stored, not the original PDF. Scanned image PDFs and encrypted PDFs require pasted text.
4. Choose role keywords, preferred location, and optional experience. Bookmark companies in this experimental directory to scan a shortlist, or choose All companies. Start with 25 before scanning the entire directory. Verified starter career-board sources for 15Five and Acquia are included; they can be replaced with a manual override.
5. Click **Scan now**, or select a company under **Connect or correct a company careers page** and use **Save & scan this company**. The queue runs in the background; **Stop scan** stops between network operations. Keep the app's terminal running.
6. Filter job results by skill overlap, remote status, listed location, and detected experience requirements. **Company coverage** shows which companies have matches, which feeds were checked, partial coverage, failures, and companies not yet checked. Results and timestamps are saved in SQLite.

You can instead run:

```powershell
.\.venv-scanner\Scripts\python.exe app.py --scanner-experiment --port 8003
```

`python app.py` still uses the original tracker database. Without Playwright, supported public APIs and regular HTML extraction still work; leave browser fallback unchecked. Enabling browser fallback alone does not call an AI service or consume Groq quota.

### How scanning works

- Read an explicit careers override, a previously researched careers URL, or discover careers links on the company's official website. Provider tenants are derived from observed links, not guessed from company names.
- Fetch public Greenhouse, Lever (global and EU), and Ashby feeds. These return published openings, not applications or private candidate data. The implementation performs no application submission, sign-in or CAPTCHA solving.
- Try public careers-page JSON-LD `JobPosting` records and bounded HTML job-detail pages whose title matches their main heading. Playwright is a fallback for rendering JavaScript and a maximum of two visible Load more / Show more actions. Arbitrary layouts, infinite scrolling, login walls and unsupported ATS platforms are not guaranteed to work.
- Respect robots.txt for website navigation and stop when access is restricted. Requests are paced; each company has a bounded discovery budget (up to five discovery pages, three job-detail pages and one browser session), response-size limits and network timeouts. Private-network destinations, credentials in URLs and unusual ports are rejected; redirects are checked too. A slow final network request may overrun the nominal 65-second company budget.
- Cache successful / partial checks for 24 hours and failed checks for 4 hours. Unchecked and oldest checks go first. Refresh cached checks explicitly when required. Changing a careers override invalidates its previous check. A failed refresh preserves old jobs and labels them as older results. A complete public feed with no openings deactivates previous listings. Partial HTML scans never claim exhaustive coverage.

### Matching and scheduling

The score is the percentage of recognized posting skills that appear in your resume. Matching uses a local alias dictionary with word boundaries; it is explainable keyword overlap, **not semantic AI evaluation, a qualification guarantee or a hiring probability**. It does not decide whether any applicant is hired. Role title keywords are checked separately. Experience signals and seniority are warnings; location and remote flags are taken only from listing evidence, and missing information remains unknown. The company PDF's region is not used to assume an individual job permits work from India. Confirm source requirements before applying.

Changing the resume or role preferences rematches already stored jobs without fetching websites. Unscored jobs can be included with a separate checkbox. Only 10,000 recent active postings are evaluated per results request, with the top 3,000 title-matching rows returned; the UI reports when this limit is reached. View job opens the stored listing URL and records a company visit. Scan fetches themselves do not increase the click count.

Daily scanning is optional and disabled initially. When enabled it checks every minute while this app process is running and starts a scan when the previous scan started at least 24 hours ago (or on the first tick if no scan exists). It does not wake a sleeping computer or run when the app is closed. On restart, interrupted scans are marked interrupted rather than silently resumed. Public demo mode blocks all scanner APIs and resume settings, so the shared internet demo cannot access your personal resume or start scans.

Resume text, preferences, source overrides, collected jobs and scan history live in the local SQLite database. Existing CSV and JSON exports cover the tracker data, not the scanner resume/preferences/jobs; to back up the complete experiment, stop it and copy `data/scanner-experiment.sqlite3`. Do not upload this file to Git. The resume can be cleared by saving empty text with daily scanning disabled.

### Validate or discard

```powershell
.\.venv-scanner\Scripts\python.exe -m unittest discover -s tests -v
node --check static/matcher.js
```

Tests cover all three feed adapters, discovery, private-URL rejection, partial and failed checks, skill matching, cache invalidation, cancellation, tracked job visits, demo privacy, and a real headless Chromium fixture that renders job JSON-LD through JavaScript and a Load more button. Live smoke checks verified Lever, Greenhouse and Ashby feeds; coverage of all 735 companies has not been verified.

To abandon the experiment, stop its server with Ctrl+C and switch back to `main`. Restart the normal launcher. The branch, ignored virtual environment/browser downloads, and separate experiment database can remain without changing your original tracker.
