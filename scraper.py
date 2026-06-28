import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

OUTPUT_FILE = Path("deals.json")

STORES = [
    {
        "store": "AYR — Union Medical",
        "program": "medical",
        "store_url": "https://ayrdispensaries.com/stores/ayr-nj-union-med",
        # Important: do NOT use the old /new-jersey/union-medical/shop/ URL.
        # It currently tends to push/redirect into the rec flow. JointCommerce 6090 is the Union Med listing.
        "urls": [
            "https://app.jointcommerce.com/dispensaries/6090/",
        ],
    },
    {
        "store": "RISE — Paterson Medical",
        "program": "medical",
        "store_url": "https://risecannabis.com/dispensaries/new-jersey/paterson/1317/medical-menu/",
        # These links open the medical menu already filtered and sorted.
        "urls": [
            "https://risecannabis.com/dispensaries/new-jersey/paterson/1317/medical-menu/?refinementList[root_types][]=flower&refinementList[available_weights][]=eighth%20ounce&currentSort=price-asc",
            "https://risecannabis.com/dispensaries/new-jersey/paterson/1317/medical-menu/?refinementList[root_types][]=vape&refinementList[available_weights][]=gram&currentSort=price-asc",
        ],
    },
]

PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")
SIZE_35_RE = re.compile(r"\b(3\.5\s*g|3\.5g|1/8|⅛|eighth|eighths|eighth ounce)\b", re.I)
SIZE_1G_RE = re.compile(r"\b(1\s*g|1g|gram|1 gram|1000\s*mg|1000mg)\b", re.I)
FLOWER_RE = re.compile(r"\b(flower|bud|buds|eighth|3\.5g|3\.5\s*g|1/8|⅛)\b", re.I)
VAPE_RE = re.compile(r"\b(vape|vaporizer|vaporizers|cart|carts|cartridge|disposable|all[- ]?in[- ]?one|aio)\b", re.I)
BAD_FLOWER_WORDS = re.compile(r"\b(pre[- ]?roll|preroll|edible|gummy|tincture|topical|concentrate|extract|dab|wax|shatter|rosin|resin|cart|cartridge|vape|disposable)\b", re.I)
BAD_VAPE_WORDS = re.compile(r"\b(edible|gummy|tincture|topical|flower|pre[- ]?roll|preroll|eighth|3\.5g|3\.5\s*g|1/8|⅛)\b", re.I)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def first_price(text: str) -> Optional[float]:
    prices = [float(x) for x in PRICE_RE.findall(text or "")]
    return min(prices) if prices else None


def classify(text: str, url: str = "") -> Optional[str]:
    combined = f"{text} {url}"

    # URL hints are trusted, but item text still has to contain matching size/category evidence.
    url_flower = "root_types][]=flower" in url or "root_types%5D%5B%5D=flower" in url
    url_vape = "root_types][]=vape" in url or "root_types%5D%5B%5D=vape" in url

    if (url_flower or FLOWER_RE.search(combined)) and SIZE_35_RE.search(combined) and not BAD_FLOWER_WORDS.search(text):
        return "flower_3.5g"
    if (url_vape or VAPE_RE.search(combined)) and SIZE_1G_RE.search(combined) and not BAD_VAPE_WORDS.search(text):
        return "vape_1g"
    return None


def product_name_from_text(text: str) -> str:
    raw_parts = re.split(r"\n|\s{2,}", text or "")
    parts = [clean(p) for p in raw_parts if clean(p)]
    skip = re.compile(r"^(add|cart|pickup|medical|recreational|sale|flower|vape|hybrid|indica|sativa|thc|cbd|\$)", re.I)
    for p in parts[:12]:
        if "$" not in p and len(p) > 2 and not skip.search(p):
            return p[:140]
    for p in parts[:12]:
        if "$" not in p and len(p) > 2:
            return p[:140]
    return clean(text)[:140]


async def accept_popups(page):
    labels = [
        "Yes", "I am 21", "I am over 21", "Enter", "Accept", "Agree", "Continue",
        "Shop Medical", "Medical", "I understand", "Close", "No thanks",
    ]
    for label in labels:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I)).first
            if await btn.count():
                await btn.click(timeout=1200)
                await page.wait_for_timeout(700)
        except Exception:
            pass


async def auto_scroll(page, passes: int = 10):
    for _ in range(passes):
        await page.mouse.wheel(0, 1800)
        await page.wait_for_timeout(700)


async def scrape_url(browser, url: str) -> List[Dict[str, str]]:
    page = await browser.new_page(viewport={"width": 1440, "height": 2400})
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=70000)
        await accept_popups(page)
        await page.wait_for_timeout(6000)
        await accept_popups(page)
        await auto_scroll(page)

        items = await page.evaluate("""
        () => {
          const selectors = [
            '[data-testid*=product]', '[data-test*=product]', '[class*=Product]', '[class*=product]',
            '[class*=MenuItem]', '[class*=menu-item]', '[class*=menuItem]', '[class*=Card]',
            'article', 'li', 'a'
          ];
          const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
          const seen = new Set();
          return nodes.map(el => {
            const text = (el.innerText || el.textContent || '').trim();
            const href = el.href || el.querySelector('a')?.href || '';
            return { text, href };
          }).filter(x => {
            const key = x.text.slice(0, 260);
            if (!x.text || x.text.length < 15 || seen.has(key)) return false;
            seen.add(key);
            return /\$/.test(x.text);
          });
        }
        """)
        return items
    finally:
        await page.close()


async def main():
    products: List[Dict] = []
    errors: List[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for store in STORES:
            for url in store["urls"]:
                try:
                    scraped = await scrape_url(browser, url)
                    for item in scraped:
                        text = clean(item.get("text", ""))
                        price = first_price(text)
                        kind = classify(text, url)
                        if not price or not kind:
                            continue
                        products.append({
                            "store": store["store"],
                            "program": store["program"],
                            "category": "Flower" if kind == "flower_3.5g" else "Vape",
                            "filter_size": "3.5g / 1/8" if kind == "flower_3.5g" else "1g",
                            "name": product_name_from_text(item.get("text", "")),
                            "price": price,
                            "price_display": f"${price:.2f}".replace(".00", ""),
                            "source_url": item.get("href") or url,
                            "menu_url": url,
                        })
                except Exception as e:
                    errors.append(f"{store['store']} | {url}: {type(e).__name__}: {e}")
        await browser.close()

    deduped = {}
    for item in products:
        key = (item["store"], item["category"], item["name"].lower(), item["price"])
        deduped[key] = item

    products = sorted(
        deduped.values(),
        key=lambda x: (x["store"], x["category"], x["price"], x["name"].lower())
    )

    by_store = {}
    for item in products:
        by_store.setdefault(item["store"], {"total": 0, "flower": 0, "vape": 0})
        by_store[item["store"]]["total"] += 1
        if item["category"] == "Flower":
            by_store[item["store"]]["flower"] += 1
        if item["category"] == "Vape":
            by_store[item["store"]]["vape"] += 1

    data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "program": "medical",
            "categories": ["Flower", "Vape"],
            "flower_size": "3.5g / 1/8",
            "vape_size": "1g",
            "sort": "price_low_to_high",
        },
        "stores": [
            {"name": s["store"], "program": s["program"], "store_url": s["store_url"], "menu_urls": s["urls"]}
            for s in STORES
        ],
        "summary_by_store": by_store,
        "total_deals": len(products),
        "products": products,
        "errors": errors,
    }

    OUTPUT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {len(products)} products to {OUTPUT_FILE}")
    if errors:
        print("Errors:")
        for err in errors:
            print(" -", err)


if __name__ == "__main__":
    asyncio.run(main())
