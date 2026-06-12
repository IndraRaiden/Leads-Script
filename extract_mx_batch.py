"""Extract the next batch of MX hot leads pending WhatsApp verification.

Reads output/HOT_leads_only.csv and keeps rows that are: in Mexico, with a
valid phone, and whose phone_e164 has never appeared in any previous
output/HOT_leads_MX*.csv batch (so no number is ever validated or messaged
twice). Writes the result to the given output file.

Usage: python extract_mx_batch.py output/HOT_leads_MX_batch3.csv
"""

import csv
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
HOT_FILE = OUTPUT_DIR / "HOT_leads_only.csv"


def main():
    if len(sys.argv) < 2:
        print("Uso: python extract_mx_batch.py <output.csv>")
        sys.exit(1)
    out = Path(sys.argv[1])

    processed = set()
    for prev in OUTPUT_DIR.glob("HOT_leads_MX*.csv"):
        if prev.resolve() == out.resolve():
            continue
        with open(prev, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("phone_e164"):
                    processed.add(r["phone_e164"])

    with open(HOT_FILE, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    batch, seen = [], set()
    for r in rows:
        if "Mexico" not in r.get("search_location", ""):
            continue
        if r.get("phone_valid") != "True":
            continue
        e164 = r.get("phone_e164", "")
        if not e164 or e164 in processed or e164 in seen:
            continue
        seen.add(e164)
        batch.append(r)

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(batch)
    print(f"{len(batch)} leads nuevos -> {out} (excluidos {len(processed)} ya procesados)")


if __name__ == "__main__":
    main()
