# Remote Atlas

A personal remote-company directory and job-search tracker, built from your PDF. Runs locally with Python and SQLite; no accounts, API keys, npm install, or paid services.

## Run

Requires Python 3.10 or newer. In this folder:

```powershell
python app.py
```

Open http://127.0.0.1:8000 in your browser. Stop with Ctrl+C. For another port, use `python app.py --port 8001`. On Windows you can also double-click `Start Remote Atlas.cmd`.

## What you can do

- Browse all 735 companies extracted from the 25-page source PDF, including original regions and source page references. The PDF title says 640; the actual table contains 735 companies. Its final recruitment-adviser promotional link is excluded.
- Search by company, region, and personal notes. Filter by region and application stage; sort alphabetically, by visit count, latest visit, or follow-up date.
- Open company websites in a new tab. Every use of **Open website** records one click; revisits count again. **Companies explored** counts distinct companies with at least one click. Links opened outside this app are not tracked. A click records your intent to open the site, regardless of whether the destination loads.
- Bookmark companies, view unexplored companies, or pick a random unexplored company from your current filtered selection.
- Keep application stages, notes, and follow-up dates in the company notebook. Pipeline includes every stage except Not started. Applications sent counts Applied, Interviewing, and Offer. Due follow-ups uses your browser's local date, including today. Follow-up dates are shown in the app; there are no background notifications.
- See the latest 200 clicks with local timestamps. All historical clicks remain in SQLite and backups.
- Download a CSV of all companies and progress or a full JSON backup including all click events. CSV export includes protection against spreadsheet formula execution.

## Your data

All changes persist in `data/tracker.sqlite3`. Reopening the app preserves progress. New catalog entries are imported on startup without overwriting existing notes or tracking data. Keep this file backed up. To restore a raw database copy, stop the server and replace `data/tracker.sqlite3` with the saved copy; make database copies only with the server stopped. The JSON download is a portable data export; this version does not have a JSON import screen.

The app binds only to `127.0.0.1` and is intended for personal local use. Company URLs and hiring regions are faithfully imported source data, not verified current hiring information. Region filters match the PDF text; Worldwide is a separate option from India or Asia, and region labels do not guarantee work eligibility. No company websites are fetched until you choose to open one. The UI uses system fonts and requires no external assets.

## Development

Backend: Python standard library (`http.server`, `sqlite3`). Frontend: vanilla HTML, CSS, and JavaScript. Source catalog: `data/companies.json`. Tests use an isolated temporary database inside this project and never modify your tracker database.

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
