import asyncio
import json
import re
from datetime import datetime
from playwright.async_api import async_playwright

MAX_PRICE = 30  # Hard ceiling — we filter to 20/25/30 in the dashboard

DISPENSARIES = [
    {
        "name": "Kind Kush Rockaway",
        "badge": "adult",
        "label": "Adult Use (Med Discount)",
        "color": "#e8c84a",
        "base_url": "https://www.kindkushdispensary.com",
        "menus": [
            {"category": "flower", "url": "https://www.kindkushdispensary.com/collection/flower?sort=customMinPriceAsc&page=1&customSize=3.5+G"},
            {"category": "vape",   "url": "https://www.kindkushdispensary.com/collection/cartridge?page=1&sort=customMinPriceAsc"},
        ],
    },
    {
        "name": "RISE Bloomfield",
        "badge": "med",
        "label": "Medical",
        "color": "#4dab6d",
        "base_url": "https://risecannabis.com",
        "menus": [
            {"category": "flower", "url": "https://risecannabis.com/dispensaries/new-jersey/bloomfield/3422/medical-menu/?refinementList[root_types][]=flower&refinementList[available_weights][]=eighth%20ounce&currentSort=by-price-"},
            {"category": "vape",   "url": "https://risecannabis.com/dispensaries/new-jersey/bloomfield/3422/medical-menu/?refinementList[root_types][]=vape&refinementList[available_weights][]=gram&currentSort=by-price-"},
        ],
    },
    {
        "name": "RISE Paterson",
        "badge": "med",
        "label": "Medical",
        "color": "#5dba7d",
        "base_url": "https://risecannabis.com",
        "menus": [
            {"category": "flower", "url": "https://risecannabis.com/dispensaries/new-jersey/paterson/1317/medical-menu/?refinementList[root_types][]=flower&refinementList[available_weights][]=eighth%20ounce&currentSort=by-price-"},
            {"category": "vape",   "url": "https://risecannabis.com/dispensaries/new-jersey/paterson/1317/medical-menu/?refinementList[root_types][]=vape&refinementList[available_weights][]=gram&currentSort=by-price-"},
        ],
    },
    {
        "name": "AYR Union",
        "badge": "med",
        "label": "Medical",
        "color": "#5b9bd5",
        "base_url": "https://ayrdispensaries.com",
        "menus": [
            {"category": "flower", "url": "https://ayrdispensaries.com/new-jersey/union-medical/shop/?dtche%5Bweight%5D=1-8oz&dtche%5Bsortby%5D=pricelowtohigh&dtche%5Bcategory%5D=flower"},
            {"category": "vape",   "url": "https://ayrdispensaries.com/new-jersey/union-medical/shop/?dtche%5Bweight%5D=1g&dtche%5Bsortby%5D=pricelowtohigh&dtche%5Bcategory%5D=vaporizers"},
        ],
    },
    {
        "name": "Apothecarium Maplewood",
        "badge": "med",
        "label": "Medical",
        "color": "#c1845a",
        "base_url": "https://shop.apothecarium.com",
        "menus": [
            {"category": "flower", "url": "https://shop.apothecarium.com/maplewood/medical/menu/flower-17?filters=%7B%22category%22%3A%5B17%5D%2C%22totalSize%22%3A%5B243139977%5D%7D&sorting=2"},
            {"category": "vape",   "url": "https://shop.apothecarium.com/maplewood/medical/menu?filters=%7B%22category%22%3A%5B18%5D%2C%22totalSize%22%3A%5B-1627035471%5D%7D&sorting=2"},
        ],
    },
    {
        "name": "Apothecarium Lodi",
        "badge": "med",
        "label": "Medical",
        "color": "#d4956a",
        "base_url": "https://shop.apothecarium.com",
        "menus": [
            {"category": "flower", "url": "https://shop.apothecarium.com/lodi/medical/menu/flower-17?filters=%7B%22category%22%3A%5B17%5D%2C%22totalSize%22%3A%5B243139977%5D%7D&sorting=2"},
            {"category": "vape",   "url": "https://shop.apothecarium.com/lodi/medical/menu?filters=%7B%22category%22%3A%5B18%5D%2C%22totalSize%22%3A%5B-1627035471%5D%7D&sorting=2"},
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

PRODUCT_CARD_SELECTORS = [
    "[class*='ProductCard']",
    "[class*='product-card']",
    "[class*='product_card']",
    "[class*='MenuItem']",
    "[class*='menu-item']",
    "[class*='ProductTile']",
    "[class*='product-tile']",
    "[class*='ProductItem']",
    "[class*='product-item']",
    "[data-testid*='product']",
    "[data-testid*='menu-item']",
    "li[class*='product']",
    "div[class*='card']",
]

PRICE_SELECTORS = [
    "[class*='price']",
    "[class*='Price']",
    "[class*='cost']",
    "[data-testid*='price']",
    "span[class*='dollar']",
    "[class*='amount']",
]

NAME_SELECTORS = [
    "[class*='name']",
    "[class*='Name']",
    "[class*='title']",
    "[class*='Title']",
    "h3", "h4", "h2",
    "p[class*='name']",
]


async def dismiss_age_gate(page):
    for selector in [
        "button:has-text('Yes')",
        "button:has-text('YES')",
        "button:has-text('I am 21')",
        "button:has-text('Enter')",
        "button:has-text('Continue')",
        "button:has-text('Confirm')",
        "a:has-text('Yes, I am')",
        "[data-testid='age-gate-confirm']",
        ".age-gate__confirm",
        "#age-gate-yes",
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
    """Scroll down repeatedly to trigger lazy-loaded products."""
    prev_height = 0
    for _ in range(15):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        height = await page.evaluate("document.body.scrollHeight")
        if height == prev_height:
            break
        prev_height = height
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(500)


async def extract_price(text):
    """Pull the first reasonable dollar amount from text."""
    matches = re.findall(r'\$?(\d+\.?\d*)', text.replace(',', ''))
    for m in matches:
        try:
            val = float(m)
            if 1 < val < 500:
                return val
        except Exception:
            continue
    return None


async def scrape_page(page, dispensary, category, url):
    products = []
    print(f"    → {category}: {url[:80]}...")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(5000)
        await dismiss_age_gate(page)
        await page.wait_for_timeout(3000)

        # Check for iframes (Dutchie / iHeartJane embed pattern)
        frames = page.frames
        target_frame = page  # default to main page
        for frame in frames:
            frame_url = frame.url
            if any(x in frame_url for x in ["iheartjane", "dutchie", "jane-embed"]):
                print(f"      📦 Found embedded frame: {frame_url[:60]}")
                target_frame = frame
                break

        await scroll_to_load_all(target_frame)

        # Try each card selector
        cards = []
        matched_selector = ""
        for selector in PRODUCT_CARD_SELECTORS:
            try:
                found = await target_frame.query_selector_all(selector)
                if len(found) > 2:
                    cards = found
                    matched_selector = selector
                    break
            except Exception:
                continue

        if not cards:
            # Fallback: dump page text for debugging
            print(f"      ⚠️  No product cards found on this page")
            try:
                body = await target_frame.inner_text("body")
                snippet = body[:300].replace('\n', ' ')
                print(f"      Page preview: {snippet}")
            except Exception:
                pass
            return products

        print(f"      Found {len(cards)} cards with selector: {matched_selector}")

        for card in cards:
            try:
                # PRICE
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

                # NAME
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

                # IMAGE
                img_src = ""
                try:
                    img_el = await card.query_selector("img")
                    if img_el:
                        src = await img_el.get_attribute("src") or ""
                        srcset = await img_el.get_attribute("srcset") or ""
                        if srcset:
                            src = srcset.split(",")[0].strip().split(" ")[0]
                        if src and src.startswith("/"):
                            src = dispensary["base_url"] + src
                        img_src = src
                except Exception:
                    pass

                # LINK
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
                    "name": name[:80],
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

        print(f"      ✅ {len(products)} products under ${MAX_PRICE}")

    except Exception as e:
        print(f"      ❌ Error: {e}")

    return products


async def main():
    all_products = []
    print(f"🌿 Budtender scrape — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   Grabbing everything under ${MAX_PRICE}\n")

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
            print(f"📍 {dispensary['name']}")
            for menu in dispensary["menus"]:
                page = await context.new_page()
                try:
                    found = await scrape_page(page, dispensary, menu["category"], menu["url"])
                    all_products.extend(found)
                except Exception as e:
                    print(f"  ❌ Page failed: {e}")
                finally:
                    await page.close()
            print()

        await browser.close()

    # Deduplicate
    seen = set()
    unique = []
    for p in all_products:
        key = (p["dispensary"], p["name"].lower(), p["price"])
        if key not in seen:
            seen.add(key)
            unique.append(p)

    unique.sort(key=lambda x: x["price"])

    output = {
        "last_updated": datetime.now().strftime("%b %d, %Y · %I:%M %p"),
        "max_price": MAX_PRICE,
        "total_deals": len(unique),
        "products": unique,
    }

    with open("deals.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Done — {len(unique)} total products saved")
    for d in DISPENSARIES:
        count = len([p for p in unique if p["dispensary"] == d["name"]])
        print(f"   {d['name']}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
