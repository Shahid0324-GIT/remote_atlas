"""Rebuild the seed catalog from the source PDF (requires pdfplumber)."""
import json
import re
import sys
from pathlib import Path
import pdfplumber

source = Path(sys.argv[1] if len(sys.argv) > 1 else r'D:\Shahid\640 remote first companies.pdf')
rows = []
with pdfplumber.open(source) as pdf:
    for page_number, page in enumerate(pdf.pages, 1):
        for table in page.extract_tables():
            for raw in table:
                cells = [cell for cell in raw if cell is not None and cell.strip()]
                if len(cells) not in (2, 3) or not re.match(r'https?://', cells[1]):
                    continue
                rows.append(dict(name=' '.join(cells[0].split()), url=re.sub(r'\s+', '', cells[1]),
                                 region=' '.join(cells[2].split()) if len(cells) == 3 else 'Not specified', source_page=page_number))
target = Path(__file__).resolve().parents[1] / 'data' / 'companies.json'
target.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'Extracted {len(rows)} companies from {len(pdf.pages)} pages to {target}')
