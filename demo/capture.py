"""Captura las pantallas del mockup CloudSH como PNG listos para WhatsApp."""
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
HTML = HERE / "mockup.html"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1480, "height": 1000}, device_scale_factor=2)
    page.goto(HTML.as_uri())
    page.wait_for_timeout(500)
    for i in range(1, 5):
        el = page.locator(f"#s{i}")
        out = HERE / f"cloudsh_demo_{i}.png"
        el.screenshot(path=str(out))
        print(f"OK {out.name}")
    browser.close()
