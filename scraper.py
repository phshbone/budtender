import asyncio
import json
from datetime import datetime
from playwright.async_api import async_playwright

MAX_PRICE = 20  # Change to 25 if you want the wider net

DISPENSARIES = [
    {
        "name": "Kind Kush Rockaway",
        "badge": "adult",
        "label": "Adult Use (Med Discount)",
        "color": "#e8c84a",
        "base_url": "https://www.kindkushdispensary.com",
        "menus": [
            {"category": "flower", "url": "https://www.kindkushdispensary.com/menu/flower"},
            {"category": "vape",   "url": "https://www.kindkushdispensary.com/menu/vaporizers"},
        ],
    },
    {
        "name": "RISE Paterson",
        "badge": "med",
        "label": "Medical",
        "color": "#5dba7d",
        "base_url": "https://risecannabis.com",
        "menus": [
            {"category": "flower", "url": "https://risecannabis.com/dispensary-menu/new-jersey/paterson/?category=flower&consumer_type=medical"},
            {"category": "vape",   "url": "https://risecannabis.com/dispensary-menu/new-jersey/paterson/?category=vaporizers&consumer_type=medical"},
        ],
    },
    {
        "name": "AYR Union",
        "badge": "med",
        "label": "Medical",
        "color": "#5b9bd5",
        "base_url": "https://ayrwellness.com",
        "menus": [
            {"category": "flower", "url": "https://ayrwellness.com/dispensary/new-jersey/union/#menu/flower"},
            {"category": "vape",   "url": "https://ayrwellness.com/dispensary/new-jersey/union/#menu/vaporizers"},
        ],
    },
    {
        "name": "Apothecarium Maplewood",
        "badge": "med",
        "label": "Medical",
        "color": "#c1845a",
        "base_url": "https://shop.apothecarium.com",
        "menus": [
            {"category": "flower", "url": "https://shop.apothecarium.com/maplewood/medical/menu/flower-6816"},
            {"category": "vape",   "url": "https://shop.apothecarium.com/maplewood/medical/menu/vaporizers-6819"},
        ],
    },
    {
        "name": "Ascend Wharton",
        "badge": "med",
        "label": "Medical",
        "color": "#9b7fd4",
        "base_url": "https://ascendwellness.com",
        "menus": [
            {"category": "flower", "url": "https://ascendwellness.com/dispensary/wharton-nj/#menu/flower"},
            {"category": "vape",   "url": "https://ascendwellness.com/dispensary/wharton-nj/#menu/vaporizers"},
        ],
    },
]

# All the CSS selector patterns we try across different menu platforms
PRODUCT_CARD_SELECTORS = [
    "[class*='ProductCard']",
    "[class*='product-card']",
    "[class*='product_card']",
    "[class*='MenuItem']",
    "[class*='menu-item']",
    "[class*='menu_item']",
    "[class*='ProductTile']",
    "[class*='product-tile']",
    "[data-testid*='product']",
    "[data-testid*='menu-item']",
    ".product",
    "li[class*='product']",
]

PRICE_SELECTORS = [
    "[class*='price']",
    "[class*='Price']",
    "[class*='cost']",
    "[data-testid*='price']",
    "span[class*='dollar']",
]

NAME_SELECTORS = [
    "[class*='name']",
    "[class*='Name']",
    "[class*='title']",
    "[class*='Title']",
    "h1", "h2", "h3", "h4", "p[class*='name']",
]


async def dismiss_age_gate(page):
    for selector in [
        "button:has-text('Yes')",
        "button:has-text('YES')",
        "button:has-text('I am 21')",
        "button:has-text('Enter')",
        "button:has-text('Continue')",
        "a:has-text('Yes, I am')",
        "[data-testid='age-gate-confirm']",
        ".age-gate__confirm",
        "#age-gate-yes",
        "button:has-text('I\\'m 21')",
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                await page.wait_for_timeout(2000)
                print("    ✅ Age gate dismissed")
                return
        except Exception:
            continue


async def scroll_to_load_all(page):
    """Scroll down the full page to trigger lazy-loaded products."""
    prev_height = 0
    for _ in range(12):  # max 12 scroll attempts
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)
        height = await page.evaluate("document.body.scrollHeight")
        if height == prev_height:
            break  # nothing new loaded
        prev_height = height
    # Scroll back to top
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(500)


async def extract_price(text):
    """Pull the first dollar amount out of a text string."""
    import re
    matches = re.findall(r'\$?(\d+\.?\d*)', text.replace(',', ''))
    for m in matches:
        try:
            val = float(m)
            if 1 < val < 500:  # sanity check — skip weight/thc % numbers
                return val
        except Exception:
            continue
    return None


async def scrape_dispensary(page, dispensary):
    products = []

    for menu in dispensary["menus"]:
        category = menu["category"]
        url = menu["url"]
        print(f"    → {category}: {url}")

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(4000)
            await dismiss_age_gate(page)
            await page.wait_for_timeout(3000)

            # Scroll to load all lazy content
            await scroll_to_load_all(page)

            # Try each card selector until we find products
            cards = []
            for selector in PRODUCT_CARD_SELECTORS:
                try:
                    found = await page.query_selector_all(selector)
                    if len(found) > 2:
                        cards = found
                        print(f"      Found {len(cards)} cards with: {selector}")
                        break
                except Exception:
                    continue

            if not cards:
                print(f"      ⚠️  No cards found — page may need a different selector")
                continue

            for card in cards:
                try:
                    # ── PRICE ──
                    price_num = None
                    for sel in PRICE_SELECTORS:
                        try:
                            el = await card.query_selector(sel)
                            if el:
                                text = await el.inner_text()
                                price_num = await extract_price(text)
                                if price_num:
                                    break
                        except Exception:
                            continue

                    if not price_num:
                        continue
                    if price_num > MAX_PRICE:
                        continue

                    # ── NAME ──
                    name = "Unknown Product"
                    for sel in NAME_SELECTORS:
                        try:
                            el = await card.query_selector(sel)
                            if el:
                                t = (await el.inner_text()).strip()
                                if t and len(t) > 2 and "$" not in t:
                                    name = t
                                    break
                        except Exception:
                            continue

                    # ── IMAGE ──
                    img_src = ""
                    try:
                        img_el = await card.query_selector("img")
                        if img_el:
                            src = await img_el.get_attribute("src") or ""
                            srcset = await img_el.get_attribute("srcset") or ""
                            # prefer srcset first image if available
                            if srcset:
                                src = srcset.split(",")[0].strip().split(" ")[0]
                            if src and src.startswith("/"):
                                src = dispensary["base_url"] + src
                            img_src = src
                    except Exception:
                        pass

                    # ── LINK ──
                    href = url
                    try:
                        link_el = await card.query_selector("a")
                        if link_el:
                            h = await link_el.get_attribute("href") or ""
                            if h:
                                if h.startswith("/"):
                                    h = dispensary["base_url"] + h
                                href = h
                    except Exception:
                        pass

                    products.append({
                        "name": name[:80],  # cap length
                        "price": price_num,
                        "category": category,
                        "image": img_src,
                        "link": href,
                        "dispensary": dispensary["name"],
                        "badge": dispensary["badge"],
                        "label": dispensary["label"],
                        "color": dispensary["color"],
                    })

                except Exception:
                    continue

            print(f"      ✅ {len([p for p in products if p['category']==category])} products under ${MAX_PRICE}")

        except Exception as e:
            print(f"      ❌ Error: {e}")

    return products


async def main():
    all_products = []
    print(f"🌿 Budtender scrape started — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   Price ceiling: ${MAX_PRICE}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            viewport={"width": 390, "height": 844},
        )

        for dispensary in DISPENSARIES:
            print(f"\n📍 {dispensary['name']}")
            page = await context.new_page()
            try:
                found = await scrape_dispensary(page, dispensary)
                all_products.extend(found)
            except Exception as e:
                print(f"  ❌ Dispensary failed: {e}")
            finally:
                await page.close()

        await browser.close()

    # Deduplicate by name+dispensary
    seen = set()
    unique = []
    for p in all_products:
        key = (p["dispensary"], p["name"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(p)

    # Sort cheapest first
    unique.sort(key=lambda x: x["price"])

    output = {
        "last_updated": datetime.now().strftime("%b %d, %Y · %I:%M %p"),
        "max_price": MAX_PRICE,
        "total_deals": len(unique),
        "products": unique,
    }

    with open("deals.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Done — {len(unique)} products saved to deals.json")
    for d in DISPENSARIES:
        count = len([p for p in unique if p["dispensary"] == d["name"]])
        print(f"   {d['name']}: {count} products")


if __name__ == "__main__":
    asyncio.run(main())
