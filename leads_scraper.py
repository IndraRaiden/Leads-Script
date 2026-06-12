"""Google Maps lead scraper for AI SaaS prospecting.

Finds businesses with weak digital presence (no website, few reviews) and
scores them as leads. Saves a timestamped CSV per run in output/runs/ and
maintains deduplicated output/MASTER_leads.csv + output/HOT_leads_only.csv.

Usage:
    python leads_scraper.py                                   # interactive
    python leads_scraper.py "trucking company" "Phoenix AZ" -n 20
    python leads_scraper.py --sweep sweeps/sweep_mega_run.txt -n 20
    python leads_scraper.py ... --show                        # visible browser

Sweep file format (one search per line):
    trucking company | Phoenix AZ
    machine shop | Detroit MI
"""

import argparse
import asyncio
import csv
import re
from datetime import datetime
from pathlib import Path

import phonenumbers
from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

console = Console()

OUTPUT_DIR = Path("output")
RUNS_DIR = OUTPUT_DIR / "runs"
MASTER_FILE = OUTPUT_DIR / "MASTER_leads.csv"
HOT_FILE = OUTPUT_DIR / "HOT_leads_only.csv"

FIELDS = [
    "lead_score", "lead_reasons", "name", "category", "address",
    "phone", "phone_e164", "phone_valid", "whatsapp",
    "business_status", "last_review",
    "website", "has_website", "rating", "reviews",
    "search_query", "search_location", "scraped_date", "maps_url",
]

SCORE_RULES = {
    "no_website": 5,
    "low_reviews": 2,      # < 50 reviews
    "medium_reviews": 1,   # 50–200 reviews
    "no_rating": 1,
    "low_rating": 1,       # < 3.5 stars
}


def score_lead(has_website: bool, reviews: int | None, rating: float | None) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    if not has_website:
        score += SCORE_RULES["no_website"]
        reasons.append("No website")

    if reviews is None:
        score += SCORE_RULES["no_rating"]
        reasons.append("No reviews")
    elif reviews < 50:
        score += SCORE_RULES["low_reviews"]
        reasons.append(f"Only {reviews} reviews")
    elif reviews <= 200:
        score += SCORE_RULES["medium_reviews"]
        reasons.append(f"{reviews} reviews")

    if rating is not None and rating < 3.5:
        score += SCORE_RULES["low_rating"]
        reasons.append(f"Low rating {rating}")

    return score, reasons


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def region_for(location: str) -> str:
    return "MX" if re.search(r"mexico|cdmx|méxico", location, re.IGNORECASE) else "US"


def validate_phone(phone: str, location: str) -> tuple[str, bool]:
    """Validate a scraped phone against the national numbering plan.

    Returns (e164, valid). Kills malformed, incomplete, or impossible numbers
    so wa.me links are only generated for numbers that can actually exist.
    """
    if not phone.strip():
        return "", False
    try:
        parsed = phonenumbers.parse(phone, region_for(location))
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164), True
    except phonenumbers.NumberParseException:
        pass
    return "", False


def whatsapp_link(phone: str, location: str) -> str:
    """Build a wa.me link from a scraped phone — only if the number is valid."""
    e164, valid = validate_phone(phone, location)
    return f"https://wa.me/{e164.lstrip('+')}" if valid else ""


def parse_reviews(text: str) -> int | None:
    text = text.replace(",", "").replace(".", "")
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else None


def parse_rating(text: str) -> float | None:
    match = re.search(r"(\d+[.,]\d+)", text)
    if match:
        return float(match.group(1).replace(",", "."))
    return None


async def scrape_listing(page, url: str, query: str, location: str) -> dict:
    result = {
        "name": "",
        "category": "",
        "address": "",
        "phone": "",
        "phone_e164": "",
        "phone_valid": False,
        "whatsapp": "",
        "business_status": "open",
        "last_review": "",
        "website": "",
        "has_website": False,
        "rating": None,
        "reviews": None,
        "search_query": query,
        "search_location": location,
        "scraped_date": datetime.now().strftime("%Y-%m-%d"),
        "maps_url": url,
        "lead_score": 0,
        "lead_reasons": "",
    }

    try:
        await page.goto(f"{url}?hl=en", wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)

        try:
            result["name"] = clean_text(await page.locator("h1").first.inner_text(timeout=5000))
        except Exception:
            pass

        try:
            cat = page.locator('button[jsaction*="category"]').first
            if await cat.count() > 0:
                result["category"] = clean_text(await cat.inner_text(timeout=3000))
        except Exception:
            pass

        try:
            rating_el = page.locator('div[jsaction*="rating"] span[aria-hidden="true"]').first
            if await rating_el.count() > 0:
                result["rating"] = parse_rating(await rating_el.inner_text(timeout=3000))
        except Exception:
            pass

        try:
            reviews_el = page.locator('span[aria-label*="review"], span[aria-label*="reseña"]').first
            if await reviews_el.count() > 0:
                label = await reviews_el.get_attribute("aria-label", timeout=3000)
                if label:
                    result["reviews"] = parse_reviews(label)
        except Exception:
            pass

        try:
            addr = page.locator('button[data-item-id="address"]').first
            if await addr.count() > 0:
                result["address"] = clean_text(await addr.inner_text(timeout=3000))
        except Exception:
            pass

        try:
            phone = page.locator('button[data-item-id*="phone"]').first
            if await phone.count() > 0:
                raw = clean_text(await phone.inner_text(timeout=3000))
                match = re.search(r"[+\d][\d\s\-().]*\d", raw)
                result["phone"] = match.group(0) if match else raw
        except Exception:
            pass

        try:
            web = page.locator('a[data-item-id="authority"]').first
            if await web.count() > 0:
                href = await web.get_attribute("href", timeout=3000)
                if href and not href.startswith("https://maps.google"):
                    result["website"] = href
                    result["has_website"] = True
        except Exception:
            pass

        try:
            wa = page.locator('a[href*="wa.me"], a[href*="api.whatsapp.com"]').first
            if await wa.count() > 0:
                href = await wa.get_attribute("href", timeout=2000)
                if href:
                    result["whatsapp"] = href
        except Exception:
            pass

        try:
            closed = page.locator(
                'span:has-text("Permanently closed"), span:has-text("Temporarily closed")'
            ).first
            if await closed.count() > 0:
                txt = clean_text(await closed.inner_text(timeout=2000)).lower()
                result["business_status"] = "permanently_closed" if "permanently" in txt else "temporarily_closed"
        except Exception:
            pass

        try:
            # Relative date of the most recent visible review ("2 weeks ago") —
            # activity signal that the listing (and its phone) is current.
            review_date = page.locator('div[data-review-id] span:text-matches("ago$")').first
            if await review_date.count() > 0:
                result["last_review"] = clean_text(await review_date.inner_text(timeout=2000))
        except Exception:
            pass

    except Exception as e:
        console.print(f"[yellow]Warning scraping {url}: {e}[/yellow]")

    result["phone_e164"], result["phone_valid"] = validate_phone(result["phone"], location)
    if not result["whatsapp"] and result["phone_valid"]:
        result["whatsapp"] = whatsapp_link(result["phone"], location)

    score, reasons = score_lead(result["has_website"], result["reviews"], result["rating"])
    result["lead_score"] = score
    result["lead_reasons"] = " | ".join(reasons)

    return result


async def collect_listing_urls(page, query: str, location: str, max_results: int) -> list[str]:
    urls = []
    search_term = f"{query} in {location}"

    console.print(f"\n[cyan]Searching Google Maps:[/cyan] {search_term}")
    await page.goto(
        f"https://www.google.com/maps/search/{search_term.replace(' ', '+')}?hl=en",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(3000)

    # Accept cookies if prompted
    for label in ("Accept all", "Aceptar todo"):
        try:
            await page.click(f'button:has-text("{label}")', timeout=2000)
            break
        except Exception:
            pass

    await page.wait_for_timeout(1500)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Collecting listing URLs...", total=max_results)

        last_count = 0
        stall_count = 0
        seen = set()

        while len(urls) < max_results:
            links = await page.locator('a[href*="/maps/place/"]').all()
            for link in links:
                href = await link.get_attribute("href")
                if not href or "/maps/place/" not in href:
                    continue
                clean = href.split("?")[0]
                if clean not in seen:
                    urls.append(clean)
                    seen.add(clean)
                    progress.update(task, completed=min(len(urls), max_results))
                    if len(urls) >= max_results:
                        break

            if len(urls) >= max_results:
                break

            panel = page.locator('div[role="feed"]').first
            if await panel.count() > 0:
                await panel.evaluate("el => el.scrollTop += 1200")
            else:
                await page.keyboard.press("End")

            await page.wait_for_timeout(1500)

            if len(urls) == last_count:
                stall_count += 1
                if stall_count >= 4:
                    console.print("[yellow]No more results found.[/yellow]")
                    break
            else:
                stall_count = 0
                last_count = len(urls)

    return urls[:max_results]


async def run_searches(searches: list[tuple[str, str]], max_results: int, show_browser: bool,
                       checkpoint_file: str | None = None) -> list[dict]:
    leads = []
    seen_keys = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not show_browser)
        context = await browser.new_context(
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        for i, (query, location) in enumerate(searches, 1):
            console.rule(f"[bold]Search {i}/{len(searches)}: {query} in {location}[/bold]")

            urls = await collect_listing_urls(page, query, location, max_results)
            console.print(f"[green]Found {len(urls)} listings.[/green]\n")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                console=console,
            ) as progress:
                task = progress.add_task("Scraping business details...", total=len(urls))

                for url in urls:
                    data = await scrape_listing(page, url, query, location)
                    key = (data["name"].lower(), data["phone"])
                    if data["name"] and key not in seen_keys:
                        seen_keys.add(key)
                        leads.append(data)
                        status = "[red]No website[/red]" if not data["has_website"] else "[dim]Has website[/dim]"
                        score_color = "green" if data["lead_score"] >= 5 else "yellow" if data["lead_score"] >= 3 else "dim"
                        console.print(
                            f"  [{score_color}]Score {data['lead_score']}[/{score_color}] | {status} | {data['name']}"
                        )
                    progress.update(task, advance=1)
                    await page.wait_for_timeout(500)

            if checkpoint_file:
                save_csv(sorted(leads, key=lambda x: x["lead_score"], reverse=True), checkpoint_file)
                console.print(f"[dim]Checkpoint saved: {len(leads)} leads so far.[/dim]")

        await browser.close()

    return leads


def save_csv(leads: list[dict], filename: str):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(leads)


def update_master(leads: list[dict]) -> tuple[int, int, int]:
    """Merge new leads into the master CSV, deduped by (name, phone).

    Also refreshes the hot-leads-only export. Returns (new, total, hot) counts.
    """
    existing = []
    if MASTER_FILE.exists():
        with open(MASTER_FILE, encoding="utf-8") as f:
            existing = list(csv.DictReader(f))

    seen = {(row["name"].lower(), row.get("phone", "")) for row in existing}
    new_rows = []
    for lead in leads:
        key = (lead["name"].lower(), lead["phone"])
        if key not in seen:
            seen.add(key)
            new_rows.append(lead)

    combined = existing + [{k: str(v) for k, v in lead.items()} for lead in new_rows]
    combined.sort(key=lambda r: int(r["lead_score"] or 0), reverse=True)

    with open(MASTER_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(combined)

    hot = [
        r for r in combined
        if int(r["lead_score"] or 0) >= 5
        and r.get("business_status", "open") != "permanently_closed"
    ]
    with open(HOT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(hot)

    return len(new_rows), len(combined), len(hot)


def print_summary(leads: list[dict]):
    hot = [l for l in leads if l["lead_score"] >= 5]
    warm = [l for l in leads if 3 <= l["lead_score"] < 5]
    cold = [l for l in leads if l["lead_score"] < 3]
    no_web = [l for l in leads if not l["has_website"]]

    table = Table(title="Lead Summary", show_header=True, header_style="bold cyan")
    table.add_column("Category", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("[green]Hot leads (score >= 5)[/green]", str(len(hot)))
    table.add_row("[yellow]Warm leads (score 3-4)[/yellow]", str(len(warm)))
    table.add_row("[dim]Cold leads (score < 3)[/dim]", str(len(cold)))
    table.add_row("-" * 20, "-" * 5)
    table.add_row("[red]No website[/red]", str(len(no_web)))
    table.add_row("Total", str(len(leads)))

    console.print()
    console.print(table)

    if hot:
        console.print("\n[bold green]Hot Leads:[/bold green]")
        for lead in sorted(hot, key=lambda x: x["lead_score"], reverse=True):
            console.print(
                f"  [green]*[/green] {lead['name']} ({lead['search_location']}) | "
                f"Phone: {lead['phone'] or 'N/A'} | Score: {lead['lead_score']}"
            )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrape Google Maps for business leads with weak digital presence."
    )
    parser.add_argument("query", nargs="?", help="Business type, e.g. 'trucking company'")
    parser.add_argument("location", nargs="?", help="City/state, e.g. 'Phoenix AZ'")
    parser.add_argument("-n", "--max-results", type=int, default=50,
                        help="Max listings per search (default 50)")
    parser.add_argument("--sweep", metavar="FILE",
                        help="File with one 'business type | location' per line")
    parser.add_argument("--show", action="store_true",
                        help="Show the browser window while scraping")
    parser.add_argument("--no-master", action="store_true",
                        help="Don't update MASTER_leads.csv")
    return parser.parse_args()


def main():
    args = parse_args()

    console.rule("[bold cyan]Google Maps Lead Scraper - AI SaaS[/bold cyan]")
    console.print("[dim]Finds businesses without websites or weak digital presence[/dim]\n")

    if args.sweep:
        searches = []
        for line in Path(args.sweep).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            query, location = (part.strip() for part in line.split("|", 1))
            searches.append((query, location))
        if not searches:
            console.print(f"[red]No valid searches in {args.sweep}.[/red]")
            return
    elif args.query and args.location:
        searches = [(args.query, args.location)]
    else:
        query = console.input("[bold]Business type[/bold] (e.g. 'auto repair', 'trucking company'): ").strip()
        location = console.input("[bold]Location[/bold] (e.g. 'Miami FL', 'Chicago IL'): ").strip()
        max_str = console.input("[bold]Max results[/bold] (default 50): ").strip()
        if max_str.isdigit():
            args.max_results = int(max_str)
        searches = [(query, location)]

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if len(searches) == 1:
        safe = re.sub(r"[^\w]+", "_", f"{searches[0][0]}_{searches[0][1]}").strip("_")
        output_file = str(RUNS_DIR / f"leads_{safe}_{timestamp}.csv")
    else:
        output_file = str(RUNS_DIR / f"leads_sweep_{len(searches)}searches_{timestamp}.csv")

    leads = asyncio.run(run_searches(searches, args.max_results, args.show,
                                     checkpoint_file=output_file))

    if not leads:
        console.print("[red]No leads found. Try a different query or location.[/red]")
        return

    leads.sort(key=lambda x: x["lead_score"], reverse=True)
    save_csv(leads, output_file)
    print_summary(leads)
    console.print(f"\n[bold green]Saved {len(leads)} leads to:[/bold green] {output_file}")

    if not args.no_master:
        new_count, total, hot_count = update_master(leads)
        console.print(
            f"[bold green]Master file updated:[/bold green] {MASTER_FILE} "
            f"(+{new_count} new, {total} total, {hot_count} hot)\n"
            f"[bold green]Hot leads export:[/bold green] {HOT_FILE}\n"
        )


if __name__ == "__main__":
    main()
