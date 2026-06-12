"""Backfill validation columns on output/MASTER_leads.csv and refresh HOT export.

For rows scraped before the validation columns existed: validates the phone
(phonenumbers), fills phone_e164/phone_valid/whatsapp, and rewrites both CSVs
with the current FIELDS layout. Closed businesses are excluded from HOT.

Usage: python enrich_master.py
"""

import csv

from leads_scraper import FIELDS, MASTER_FILE, HOT_FILE, validate_phone, whatsapp_link


def main():
    if not MASTER_FILE.exists():
        print("No master file yet.")
        return

    with open(MASTER_FILE, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    filled = 0
    for r in rows:
        loc = r.get("search_location", "")
        if not r.get("phone_e164"):
            e164, valid = validate_phone(r.get("phone", ""), loc)
            r["phone_e164"], r["phone_valid"] = e164, valid
            if valid and not r.get("whatsapp"):
                r["whatsapp"] = whatsapp_link(r["phone"], loc)
            filled += 1
        r.setdefault("business_status", "open")
        r.setdefault("last_review", "")

    rows.sort(key=lambda r: int(r["lead_score"] or 0), reverse=True)

    with open(MASTER_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)

    hot = [
        r for r in rows
        if int(r["lead_score"] or 0) >= 5
        and r.get("business_status", "open") != "permanently_closed"
    ]
    with open(HOT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(hot)

    valid_count = sum(1 for r in rows if str(r.get("phone_valid")) == "True")
    print(f"Enriched {filled} rows. Total {len(rows)}, valid phones {valid_count}, hot {len(hot)}.")


if __name__ == "__main__":
    main()
