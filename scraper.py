import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

STORE_NAME = "AYR — Union Medical"
STORE_URL = "https://ayrdispensaries.com/stores/ayr-nj-union-med"
SHOP_URLS = [
    "https://ayrdispensaries.com/new-jersey/union-medical/shop/",
    "https://app.jointcommerce.com/dispensaries/6090/",
]

OUTPUT_FILE = Path("deals.json")

PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")
SIZE_35_RE = re.compile(r"\b(3\.5\s*g|3\.5g|1/8|eighth|eighths)\b", re.I)
SIZE_1G_RE = re.compile(r"\b(1\s*g|1g|1000\s*mg|1000mg)\b", re.I)
FLOWER_RE = re.compile(r"\b(flower|bud|buds|eighth|3\.5g|3\.5\s*g|1/8)\b", re.I)
VAPE_RE = re.compile(r"\b(vape|vaporizer|vaporizers|cart|cartridge|disposable|all-in-one|aio)\b", re.I)
BAD_WORDS = re.compile(r"\b(pre[- ]?roll|edible|gummy|tincture|topical|concentrate|extract|dab|wax|shatter|rosin|resin)\b", re.I)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def first_price(text: str):
    prices = [float(x) for x in PRICE_RE.findall(text or "")]
    return min(prices) if prices else None


def classify(text: str):
    if FLOWER_RE.search(text) and SIZE_35_RE.search(text) and not BAD_WORDS.search(text):
        return "flower_3.5g"
    if VAPE_RE.search(text) and SIZE_1G_RE.search(text):
        return "vape_1g"
    return None


def product_name_from_text(text: str) -> str:
    parts = [p.strip() for p in re.split(r"\s{2,}|\n", text or "") if p.strip()]
    for p in parts[:8]:
        if "$" not in p and len(p) > 2:
            return clean(p)[:120]
    return clean(parts[0] if parts else text)[:120]


async def accept_age_gate(page):
    for label in ["Yes", "I am 21", "Enter", "Accept", "Agree", "Continue", "I'm over 21"]:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I)).first
            if await btn.count():
                await btn.click(timeout=1200)
                await page.wait_for_timeout(800)
        except Exception:
            pass


async def auto_scroll(page):
    for _ in range(8):
        await page.mouse.wheel(0, 1800)
        await page.wait_for_timeout(900)


async def scrape_url(browser, url: str):
    page = await browser.new_page(viewport={"width": 1400, "height": 2200})
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await accept_age_gate(page)
    await page.wait_for_timeout(5000)
    await auto_scroll(page)

    items = await page.evaluate("""
    () => {
      const selectors = [
        '[data-testid*=product]', '[class*=Product]', '[class*=product]',
        '[class*=MenuItem]', '[class*=menu-item]', 'article', 'li', 'a'
      ];
      const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
      const seen = new Set();
      return nodes.map(el => {
        const text = (el.innerText || el.textContent || '').trim();
        const href = el.href || el.querySelector('a')?.href || '';
        return { text, href };
      }).filter(x => {
        const key = x.text.slice(0, 220);
        if (!x.text || x.text.length < 15 || seen.has(key)) return false;
        seen.add(key);
        return /\$/.test(x.text);
      });
    }
    """)
    await page.close()
    return items


async def main():
    products = []
    errors = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for url in SHOP_URLS:
            try:
                for item in await scrape_url(browser, url):
                    text = clean(item.get("text", ""))
                    price = first_price(text)
                    kind = classify(text)
                    if not price or not kind:
                        continue
                    products.append({
                        "store": STORE_NAME,
                        "category": "Flower" if kind == "flower_3.5g" else "Vape",
                        "filter_size": "3.5g / 1/8" if kind == "flower_3.5g" else "1g",
                        "name": product_name_from_text(item.get("text", "")),
                        "price": price,
                        "price_display": f"${price:.2f}".replace(".00", ""),
                        "source_url": item.get("href") or url,
                    })
            except Exception as e:
                errors.append(f"{url}: {type(e).__name__}: {e}")
        await browser.close()

    deduped = {}
    for item in products:
        key = (item["store"], item["category"], item["name"].lower(), item["price"])
        deduped[key] = item

    products = sorted(deduped.values(), key=lambda x: (x["category"], x["price"], x["name"].lower()))

    data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "store": STORE_NAME,
        "store_url": STORE_URL,
        "filters": {
            "program": "medical",
            "categories": ["Flower", "Vape"],
            "flower_size": "3.5g / 1/8",
            "vape_size": "1g",
            "sort": "price_low_to_high",
        },
        "total_deals": len(products),
        "products": products,
        "errors": errors,
    }

    OUTPUT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {len(products)} products to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
