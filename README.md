# Leads Script — Google Maps Lead Scraper

Finds businesses with weak digital presence (no website, few reviews) on Google Maps
and scores them as prospects for AI SaaS / web development outreach.

## Project structure

```
Leads Script/
├── leads_scraper.py        # The scraper
├── sweeps/                 # Sweep definitions (one "business type | location" per line)
│   ├── sweep_rich_veins.txt
│   └── sweep_mega_run.txt
└── output/
    ├── MASTER_leads.csv    # All leads ever scraped, deduped, sorted by score
    ├── HOT_leads_only.csv  # Score >= 5 only (no website) — outreach-ready
    ├── runs/               # Raw timestamped CSV per run
    └── archive/            # Old/superseded files
```

## Usage

```bash
# Single search
python leads_scraper.py "welding shop" "El Paso TX" -n 20

# Multi-search sweep (recommended)
python leads_scraper.py --sweep sweeps/sweep_mega_run.txt -n 20

# Interactive (no args)
python leads_scraper.py

# Flags
-n / --max-results   Listings per search (default 50)
--show               Show the browser window while scraping
--no-master          Don't update MASTER_leads.csv
```

Every run automatically merges into `output/MASTER_leads.csv` (deduped by name+phone)
and refreshes `output/HOT_leads_only.csv`. Long sweeps checkpoint-save after each
search, so a crash never loses scraped data.

## Lead scoring

| Signal | Points |
|---|---|
| No website | +5 |
| < 50 reviews | +2 |
| 50–200 reviews | +1 |
| No reviews at all | +1 |
| Rating below 3.5 | +1 |

**Hot lead = score >= 5** (i.e. no website). These are the prime prospects.

## What we've learned (hot-rate intel)

- **Best verticals:** welding shops (up to 55%), machine shops (up to 40%),
  auto repair (25–45%), small manufacturing (25–30%).
- **Best cities:** El Paso TX (55% welding / 45% auto repair), Knoxville TN,
  Oklahoma City OK, Cincinnati OH, Bakersfield CA, Tulsa OK, Detroit MI.
- **Avoid:** staffing agencies and white-collar services (~0%), Kansas City MO,
  Tucson AZ, Albuquerque NM (~5%).
- **Pattern:** small owner-operated trade shops in southern/midwest industrial
  cities are the richest vein. Average hot rate ~20% when targeting proven verticals.

## Setup (already done on this machine)

```bash
pip install playwright pandas rich python-dotenv
playwright install chromium
```

**Windows note:** set `$env:PYTHONIOENCODING = "utf-8"` before running, or rich's
output can crash on cp1252 encoding.
