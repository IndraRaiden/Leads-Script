import asyncio
import csv
import os
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich import print as rprint

console = Console()

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

    if rating is None:
        pass
    elif rating < 3.5:
        score += SCORE_RULES["low_rating"]
        reasons.append(f"Low rating {rating}")

    return score, reasons


def parse_reviews(text: str) -> int | None:
    text = text.replace(",", "").replace(".", "")
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else None


def parse_rating(text: str) -> float | None:
    match = re.search(r"(\d+[.,]\d+)", text)
    if match:
        return float(match.group(1).replace(",", "."))
    return None


async def scrape_listing(page, url: str) -> dict:
    result = {
        "name": "",
        "category": "",
        "address": "",
        "phone": "",
        "website": "",
        "has_website": False,
        "rating": None,
        "reviews": None,
        "maps_url": url,
        "lead_score": 0,
        "lead_reasons": "",
    }

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)

        # Name
        try:
            result["name"] = await page.locator("h1").first.inner_text(timeout=5000)
        except Exception:
            pass

        # Category
        try:
            cat = page.locator('button[jsaction*="category"]').first
            if await cat.count() > 0:
                result["category"] = await cat.inner_text(timeout=3000)
        except Exception:
            pass

        # Rating + reviews
        try:
            rating_el = page.locator('div[jsaction*="rating"] span[aria-hidden="true"]').first
            if await rating_el.count() > 0:
                result["rating"] = parse_rating(await rating_el.inner_text(timeout=3000))
        except Exception:
            pass

        try:
            reviews_el = page.locator('span[aria-label*="reseña"], span[aria-label*="review"]').first
            if await reviews_el.count() > 0:
                label = await reviews_el.get_attribute("aria-label", timeout=3000)
                if label:
                    result["reviews"] = parse_reviews(label)
        except Exception:
            pass

        # Address
        try:
            addr = page.locator('button[data-item-id="address"], [data-tooltip="Copiar dirección"], [data-tooltip="Copy address"]').first
            if await addr.count() > 0:
                result["address"] = await addr.inner_text(timeout=3000)
        except Exception:
            pass

        # Phone
        try:
            phone = page.locator('button[data-item-id*="phone"]').first
            if await phone.count() > 0:
                result["phone"] = await phone.inner_text(timeout=3000)
        except Exception:
            pass

        # Website
        try:
            web = page.locator('a[data-item-id="authority"], a[aria-label*="sitio web"], a[aria-label*="website"]').first
            if await web.count() > 0:
                href = await web.get_attribute("href", timeout=3000)
                if href and not href.startswith("https://maps.google"):
                    result["website"] = href
                    result["has_website"] = True
        except Exception:
            pass

    except Exception as e:
        console.print(f"[yellow]Warning scraping {url}: {e}[/yellow]")

    score, reasons = score_lead(result["has_website"], result["reviews"], result["rating"])
    result["lead_score"] = score
    result["lead_reasons"] = " | ".join(reasons)

    return result


async def search_google_maps(query: str, location: str, max_results: int) -> list[str]:
    urls = []
    search_term = f"{query} in {location}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=50)
        context = await browser.new_context(
            locale="en-US",
            geolocation=None,
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        console.print(f"\n[cyan]Searching Google Maps:[/cyan] {search_term}")
        await page.goto(
            f"https://www.google.com/maps/search/{search_term.replace(' ', '+')}",
            wait_until="domcontentloaded",
        )
        await page.wait_for_timeout(3000)

        # Accept cookies if prompted
        try:
            await page.click('button:has-text("Accept all")', timeout=3000)
            await page.click('button:has-text("Aceptar todo")', timeout=3000)
        except Exception:
            pass

        await page.wait_for_timeout(2000)

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

            while len(urls) < max_results:
                # Collect all visible listing links
                links = await page.locator('a[href*="/maps/place/"]').all()
                seen = set(urls)
                for link in links:
                    href = await link.get_attribute("href")
                    if href and href not in seen and "/maps/place/" in href:
                        # Clean URL to canonical form
                        clean = href.split("?")[0] if "?" in href else href
                        if clean not in seen:
                            urls.append(clean)
                            seen.add(clean)
                            progress.update(task, completed=min(len(urls), max_results))
                            if len(urls) >= max_results:
                                break

                if len(urls) >= max_results:
                    break

                # Scroll results panel
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

        await browser.close()

    return urls[:max_results]


async def scrape_leads(query: str, location: str, max_results: int) -> list[dict]:
    console.print(f"\n[bold green]Step 1:[/bold green] Finding business listings...")
    urls = await search_google_maps(query, location, max_results)
    console.print(f"[green]Found {len(urls)} listings.[/green]")

    leads = []

    console.print(f"\n[bold green]Step 2:[/bold green] Scraping details for each business...\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task = progress.add_task("Scraping business details...", total=len(urls))

            for url in urls:
                data = await scrape_listing(page, url)
                if data["name"]:
                    leads.append(data)
                    status = "[red]No website[/red]" if not data["has_website"] else "[dim]Has website[/dim]"
                    score_color = "green" if data["lead_score"] >= 5 else "yellow" if data["lead_score"] >= 3 else "dim"
                    console.print(
                        f"  [{score_color}]Score {data['lead_score']}[/{score_color}] | {status} | {data['name']}"
                    )
                progress.update(task, advance=1)
                await page.wait_for_timeout(500)

        await browser.close()

    return leads


def save_csv(leads: list[dict], filename: str):
    fields = [
        "lead_score", "lead_reasons", "name", "category", "address",
        "phone", "website", "has_website", "rating", "reviews", "maps_url",
    ]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(leads)


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
        console.print("\n[bold green]Top 5 Hot Leads:[/bold green]")
        for lead in sorted(hot, key=lambda x: x["lead_score"], reverse=True)[:5]:
            console.print(
                f"  [green]*[/green] {lead['name']} | {lead['address']} | "
                f"Phone: {lead['phone'] or 'N/A'} | Score: {lead['lead_score']}"
            )


def main():
    console.rule("[bold cyan]Google Maps Lead Scraper - AI SaaS[/bold cyan]")
    console.print("[dim]Finds businesses without websites or weak digital presence[/dim]\n")

    query = console.input("[bold]Business type[/bold] (e.g. 'accounting firm', 'auto repair', 'dental clinic'): ").strip()
    location = console.input("[bold]Location[/bold] (e.g. 'Miami FL', 'New York', 'Chicago IL'): ").strip()
    max_str = console.input("[bold]Max results[/bold] (default 50): ").strip()
    max_results = int(max_str) if max_str.isdigit() else 50

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_query = re.sub(r"[^\w]", "_", query)
    safe_location = re.sub(r"[^\w]", "_", location)
    output_file = f"leads_{safe_query}_{safe_location}_{timestamp}.csv"

    leads = asyncio.run(scrape_leads(query, location, max_results))

    if not leads:
        console.print("[red]No leads found. Try a different query or location.[/red]")
        return

    leads.sort(key=lambda x: x["lead_score"], reverse=True)
    save_csv(leads, output_file)
    print_summary(leads)

    console.print(f"\n[bold green]Saved {len(leads)} leads to:[/bold green] {output_file}\n")


if __name__ == "__main__":
    main()
