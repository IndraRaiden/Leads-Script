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
# Lista limpia CloudSH (separada del MASTER_leads.csv viejo, que se ignora).
MASTER_FILE = OUTPUT_DIR / "CLOUDSH_leads.csv"
HOT_FILE = OUTPUT_DIR / "CLOUDSH_hot.csv"

FIELDS = [
    "tier", "lead_score", "lead_reasons", "name", "category", "cat_fit", "address",
    "phone", "phone_e164", "phone_valid", "whatsapp", "wa_listed",
    "business_status", "has_hours", "last_review", "review_age_days", "photos",
    "website", "has_website", "formal_name", "rating", "reviews",
    "search_query", "search_location", "scraped_date", "maps_url",
]

# Scoring orientado a CloudSH: el lead ideal es un negocio VIVO, en operación,
# con volumen real de documentos y que usa WhatsApp como canal. (NO el viejo
# modelo de "presencia digital débil", que servía para vender sitios web.)
# Base = volumen de reseñas (proxy confiable y barato de "negocio en operación con
# clientes reales"). Bonus = WhatsApp publicado y actividad reciente si se capturan.
# Señales confiables que Maps SÍ expone para PyMEs MX: sitio web (formalidad),
# rating, teléfono válido, abierto/cerrado. El nº de reseñas casi nunca aparece
# para este segmento, así que es solo bonus cuando existe.
SCORE_RULES = {
    "has_website": 2,       # negocio formal/establecido → más probable que pague SaaS
    "formal_name": 2,       # razón social (S.C./S.A. de C.V./S. de R.L.) → constituido, factura
    "wa_listed": 3,         # WhatsApp publicado en Maps → ya usan WA para negocio
    "has_hours": 1,         # horario publicado → negocio gestionado activamente
    "photos_active": 1,     # >= 10 fotos → negocio gestionado/activo
    "off_category": -4,     # categoría fuera del vertical → probable falso positivo
    "volume_xl": 4,         # >= 50 reseñas → operación seria (bonus, raro)
    "volume_high": 3,       # 15–49
    "volume_mid": 2,        # 5–14
    "volume_low": 1,        # 1–4
    "rating_great": 2,      # >= 4.5
    "rating_ok": 1,         # >= 4.0 (negocio real con historia)
    "active_recent": 2,     # reseña en <= 90 días (bonus)
    "active_year": 1,       # reseña en <= 1 año (bonus)
}

# Razón social formal → negocio constituido (capacidad de pago + factura).
FORMAL_NAME_RE = re.compile(
    r"\b(s\.?\s?c\.?|s\.?a\.?\s?de\s?c\.?v\.?|s\.?\s?de\s?r\.?l\.?|a\.?\s?c\.?|s\.?a\.?\b|s\.?a\.?s\.?|despacho|asociados|y\s+asociados|corporativo|grupo|bufete)\b",
    re.IGNORECASE,
)


# Categorías de Maps (en inglés, por hl=en) que SÍ corresponden a cada vertical
# que engancha. Sirve para descartar falsos positivos (p.ej. "Construction
# company" cuando buscas administradoras de condominios).
VERTICAL_CATEGORIES = {
    "condominio": ["property management", "condominium", "homeowner", "property administ", "real estate"],
    "fletes": ["moving", "mover", "trucking", "transport", "logistic", "freight", "courier", "relocation"],
    "mudanzas": ["moving", "mover", "trucking", "transport", "logistic", "relocation"],
    "transporte": ["trucking", "transport", "logistic", "freight", "shipping", "cargo", "carrier"],
    "carga": ["trucking", "transport", "logistic", "freight", "shipping", "cargo", "carrier"],
    "juridico": ["legal", "lawyer", "attorney", "law firm", "notary", "barrister", "solicitor"],
    "abogado": ["legal", "lawyer", "attorney", "law firm", "barrister", "solicitor"],
    "despacho": ["legal", "lawyer", "attorney", "law firm", "accountant", "consultant"],
    "condominios": ["property management", "condominium", "homeowner", "property administ", "real estate"],
    # Verticales nuevos — gemelos del dolor de conciliación (cobran a muchos).
    "colegio": ["school", "private school", "education", "college", "kindergarten", "preschool"],
    "escuela": ["school", "private school", "education", "college", "kindergarten", "preschool"],
    "gimnasio": ["gym", "fitness", "health club", "sports club", "crossfit"],
    "club deportivo": ["sports club", "gym", "fitness", "club", "recreation"],
    "financiera": ["financial", "loan", "credit", "finance", "lender"],
    "prestamos": ["financial", "loan", "credit", "finance", "lender"],
    "casa de empeno": ["pawn", "loan", "financial"],
    "inmobiliaria": ["real estate", "property", "realtor", "realty", "broker"],
    "seguros": ["insurance", "insurance agency", "insurance broker", "insurance company"],
    "aseguradora": ["insurance", "insurance agency", "insurance company"],
    "agente de seguros": ["insurance", "insurance agency", "insurance broker"],
    "clinica": ["clinic", "medical", "doctor", "dental", "hospital", "laboratory", "diagnostic"],
    "laboratorio": ["laboratory", "medical", "diagnostic", "clinic"],
}


def category_fit(query: str, category: str) -> bool | None:
    """True/False si la categoría del negocio corresponde al vertical buscado.
    None si no tenemos categoría o no hay reglas para ese query (no penaliza)."""
    if not category:
        return None
    q = query.lower()
    expected = []
    for key, cats in VERTICAL_CATEGORIES.items():
        if key in q:
            expected.extend(cats)
    if not expected:
        return None
    cat = category.lower()
    return any(exp in cat for exp in expected)


def score_lead(
    reviews: int | None,
    rating: float | None,
    wa_listed: bool,
    review_age_days: int | None,
    business_status: str = "open",
    has_website: bool = False,
    photos: int | None = None,
    cat_fit: bool | None = None,
    formal_name: bool = False,
    has_hours: bool = False,
) -> tuple[int, list[str]]:
    """Puntúa el ajuste a CloudSH. Mayor = mejor prospecto (formal, real, usa WA)."""
    if business_status == "permanently_closed":
        return 0, ["Cerrado permanentemente"]

    score = 0
    reasons = []

    # Categoría fuera del vertical → penaliza fuerte (probable falso positivo).
    if cat_fit is False:
        score += SCORE_RULES["off_category"]
        reasons.append("Fuera de vertical")

    if has_website:
        score += SCORE_RULES["has_website"]; reasons.append("Sitio web (formal)")

    if formal_name:
        score += SCORE_RULES["formal_name"]; reasons.append("Razón social formal")

    if has_hours:
        score += SCORE_RULES["has_hours"]; reasons.append("Horario publicado")

    if photos is not None and photos >= 10:
        score += SCORE_RULES["photos_active"]; reasons.append(f"{photos}+ fotos (activo)")

    if reviews is not None and reviews >= 50:
        score += SCORE_RULES["volume_xl"]; reasons.append(f"{reviews} reseñas (operación seria)")
    elif reviews is not None and reviews >= 15:
        score += SCORE_RULES["volume_high"]; reasons.append(f"{reviews} reseñas")
    elif reviews is not None and reviews >= 5:
        score += SCORE_RULES["volume_mid"]; reasons.append(f"{reviews} reseñas")
    elif reviews is not None and reviews >= 1:
        score += SCORE_RULES["volume_low"]; reasons.append(f"Solo {reviews} reseñas")

    if rating is not None and rating >= 4.5:
        score += SCORE_RULES["rating_great"]; reasons.append(f"Rating {rating}")
    elif rating is not None and rating >= 4.0:
        score += SCORE_RULES["rating_ok"]; reasons.append(f"Rating {rating}")

    if wa_listed:
        score += SCORE_RULES["wa_listed"]; reasons.append("WhatsApp en Maps")

    if review_age_days is not None and review_age_days <= 90:
        score += SCORE_RULES["active_recent"]; reasons.append("Activo (<90d)")
    elif review_age_days is not None and review_age_days <= 365:
        score += SCORE_RULES["active_year"]; reasons.append("Activo (<1 año)")

    return score, reasons


def lead_tier(score: int, phone_valid: bool, cat_fit: bool | None) -> str:
    """Prioridad para el outreach. A = escribir primero, C = no vale la pena."""
    if not phone_valid or cat_fit is False:
        return "C"      # sin teléfono usable o fuera de vertical
    if score >= 6:
        return "A"      # negocio formal, real, del vertical → tiro de alta calidad
    if score >= 4:
        return "B"      # decente, vale el intento
    return "C"


# Convierte la fecha relativa de la última reseña ("2 weeks ago", "hace 3 meses")
# a una edad aproximada en días — la señal más fuerte de "negocio vivo".
_AGE_UNITS = {
    "day": 1, "día": 1, "dia": 1, "week": 7, "semana": 7,
    "month": 30, "mes": 30, "year": 365, "año": 365, "ano": 365,
    "hour": 0, "hora": 0, "minute": 0, "minuto": 0,
}


def review_age_days(text: str) -> int | None:
    if not text:
        return None
    low = text.lower()
    if re.search(r"\b(a|an|una?|hace un[ao]?)\b", low) and not re.search(r"\d", low):
        n = 1
    else:
        m = re.search(r"(\d+)", low)
        n = int(m.group(1)) if m else None
    if n is None:
        return None
    for unit, mult in _AGE_UNITS.items():
        if unit in low:
            return n * mult
    return None


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
        "tier": "C",
        "name": "",
        "category": "",
        "cat_fit": None,
        "photos": None,
        "formal_name": False,
        "has_hours": False,
        "address": "",
        "phone": "",
        "phone_e164": "",
        "phone_valid": False,
        "whatsapp": "",
        "wa_listed": False,
        "business_status": "open",
        "last_review": "",
        "review_age_days": None,
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

        # Rating + nº de reseñas viven en el bloque div.F7nice (Maps actual):
        #   <div class="F7nice"><span><span aria-hidden>4.5</span>..</span>
        #                       <span><span aria-hidden>(123)</span>..</span></div>
        try:
            nums = await page.locator('div.F7nice span[aria-hidden="true"]').all_inner_texts()
            if nums:
                result["rating"] = parse_rating(nums[0])
            if len(nums) > 1:
                result["reviews"] = parse_reviews(nums[1])
        except Exception:
            pass

        # Respaldo del conteo por aria-label (varía por idioma).
        if result["reviews"] is None:
            try:
                rev = page.locator(
                    'div.F7nice span[aria-label*="review"], div.F7nice span[aria-label*="reseña"], '
                    'button[aria-label*="review"], button[aria-label*="reseña"]'
                ).first
                if await rev.count() > 0:
                    label = await rev.get_attribute("aria-label", timeout=2000)
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
                    result["wa_listed"] = True  # publicado en Maps = usan WA para negocio
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
            review_date = page.locator(
                'div[data-review-id] span:text-matches("ago$"), '
                'div[data-review-id] span:text-matches("hace")'
            ).first
            if await review_date.count() > 0:
                result["last_review"] = clean_text(await review_date.inner_text(timeout=2000))
                result["review_age_days"] = review_age_days(result["last_review"])
        except Exception:
            pass

        # Nº de fotos del negocio (señal de listing gestionado/activo). El botón
        # del hero suele traer un aria-label tipo "Photo of X · 1 of 42".
        try:
            hero = page.locator('button[jsaction*="heroHeaderImage"], div[role="img"][aria-label*="Photo"]').first
            if await hero.count() > 0:
                label = await hero.get_attribute("aria-label", timeout=1500) or ""
                m = re.search(r"of\s+(\d+)", label) or re.search(r"(\d+)\s+photo", label, re.IGNORECASE)
                if m:
                    result["photos"] = int(m.group(1))
        except Exception:
            pass

        # Horario publicado → negocio gestionado activamente.
        try:
            hours = page.locator(
                'button[data-item-id*="oh"], [aria-label*="Hours"], [jsaction*="openhours"], '
                'span:has-text("Open"), span:has-text("Closed"), span:has-text("Abierto"), span:has-text("Cerrado")'
            ).first
            if await hours.count() > 0:
                result["has_hours"] = True
        except Exception:
            pass

    except Exception as e:
        console.print(f"[yellow]Warning scraping {url}: {e}[/yellow]")

    result["phone_e164"], result["phone_valid"] = validate_phone(result["phone"], location)
    if not result["whatsapp"] and result["phone_valid"]:
        result["whatsapp"] = whatsapp_link(result["phone"], location)

    result["cat_fit"] = category_fit(query, result["category"])
    result["formal_name"] = bool(FORMAL_NAME_RE.search(result["name"]))
    score, reasons = score_lead(
        result["reviews"], result["rating"], result["wa_listed"],
        result["review_age_days"], result["business_status"], result["has_website"],
        result["photos"], result["cat_fit"], result["formal_name"], result["has_hours"],
    )
    result["lead_score"] = score
    result["lead_reasons"] = " | ".join(reasons)
    result["tier"] = lead_tier(score, result["phone_valid"], result["cat_fit"])

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
                        signals = []
                        if data["wa_listed"]:
                            signals.append("[green]WA[/green]")
                        if data["review_age_days"] is not None and data["review_age_days"] <= 90:
                            signals.append("[cyan]activo[/cyan]")
                        if data["reviews"]:
                            signals.append(f"[dim]{data['reviews']}rev[/dim]")
                        status = " ".join(signals) or "[dim]sin señales[/dim]"
                        score_color = "green" if data["lead_score"] >= 6 else "yellow" if data["lead_score"] >= 4 else "dim"
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

    # Hot = listo para outreach: tier A o B (teléfono usable, en vertical, formal).
    # Ordenado por tier (A primero) y luego por score.
    hot = [r for r in combined if r.get("tier") in ("A", "B")]
    hot.sort(key=lambda r: (r.get("tier", "C"), -int(r["lead_score"] or 0)))
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
