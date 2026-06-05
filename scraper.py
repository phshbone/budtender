import asyncio
import json
import os
from datetime import datetime
from playwright.async_api import async_playwright

MAX_PRICE = 20  # Change to 25 if you want the wider net

DISPENSARIES = [
    {
        "name": "RISE Paterson",
        "type": "medical",
        "label": "Medical",
        "badge": "med",
        "url_flower": "https://risecannabis.com/dispensaries/new-jersey/paterson/1317/medical-menu/?category=flower",
        "url_vape": "https://risecannabis.com/dispensaries/new-jersey/paterson/1317/medical-menu/?category=vaporizers",
        "base_url": "https://risecannabis.com",
        "color": "#2d7a4f",
    },
    {
        "name": "AYR Union",
        "type": "medical",
        "label": "Medical",
        "badge": "med",
        "url_flower": "https://dutchie.com/dispensary/garden-state-dispensary-union",
        "url_vape": "https://dutchie.com/dispensary/garden-state-dispensary-union",
        "base_url": "https://dutchie.com",
        "color": "#1a5276",
    },
    {
        "name": "Apothecarium Maplewood",
        "type": "medical",
        "label": "Medical",
        "badge": "med",
        "url_flower": "https://shop.apothecarium.com/maplewood/medical/menu/flower-6816",
        "url_vape": "https://shop.apothecarium.com/maplewood/medical/menu/vaporizers-6819",
        "base_url": "https://shop.apothecarium.com",
        "color": "#6b3a2a",
    },
    {
        "name": "Ascend Wharton",
        "type": "medical",
        "label": "Medical",
        "badge": "med",
        "url_flower": "https://dutchie.com/dispensary/wharton-new-jersey",
        "url_vape": "https://dutchie.com/dispensary/wharton-new-jersey",
        "base_url": "https://dutchie.com",
        "color": "#4a235a",
    },
    {
        "name": "Kind Kush Rockaway",
        "type": "adult_use",
        "label": "Adult Use (Med Discount)",
        "badge": "adult",
        "url_flower": "https://www.kindkushdispensary.com/menu",
        "url_vape": "https://www.kindkushdispensary.com/menu",
        "base_url": "https://www.kindkushdispensary.com",
        "color": "#7d6608",
    },
]


async def dismiss_age_gate(page):
    """Try to click through common age gate patterns."""
    for selector in [
        "button:has-text('Yes')",
        "button:has-text('YES')",
        "button:has-text('I am 21')",
        "button:has-text('Enter')",
        "a:has-text('Yes')",
        "[data-testid='age-gate-confirm']",
        ".age-gate__confirm",
        "#age-gate-yes",
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                await page.wait_for_timeout(1500)
                break
        except Exception:
            continue


async def scrape_rise(page, dispensary):
    """Scrape RISE using iHeartJane embed — cleaner than HTML parse."""
    products = []
    categories = [
        ("flower", dispensary["url_flower"]),
        ("vape", dispensary["url_vape"]),
    ]
    for category, url in categories:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            await dismiss_age_gate(page)
            await page.wait_for_timeout(3000)

            # Wait for product cards
            await page.wait_for_selector(
                "[class*='product'], [class*='Product'], .jane-product, [data-testid*='product']",
                timeout=15000,
            )

            cards = await page.query_selector_all(
                "[class*='ProductCard'], [class*='product-card'], .product-card, [data-testid*='product-card']"
            )

            for card in cards:
                try:
                    # Price
                    price_el = await card.query_selector(
                        "[class*='price'], [class*='Price']"
                    )
                    if not price_el:
                        continue
                    price_text = await price_el.inner_text()
                    price_num = float(
                        price_text.replace("$", "").replace(",", "").strip().split()[0]
                    )
                    if price_num > MAX_PRICE:
                        continue

                    # Name
                    name_el = await card.query_selector(
                        "[class*='name'], [class*='Name'], h3, h4"
                    )
                    name = await name_el.inner_text() if name_el else "Unknown Product"

                    # Image
                    img_el = await card.query_selector("img")
                    img_src = await img_el.get_attribute("src") if img_el else ""

                    # Link
                    link_el = await card.query_selector("a")
                    href = await link_el.get_attribute("href") if link_el else ""
                    if href and not href.startswith("http"):
                        href = dispensary["base_url"] + href

                    products.append(
                        {
                            "name": name.strip(),
                            "price": price_num,
                            "category": category,
                            "image": img_src,
                            "link": href,
                            "dispensary": dispensary["name"],
                            "badge": dispensary["badge"],
                            "label": dispensary["label"],
                            "color": dispensary["color"],
                        }
                    )
                except Exception:
                    continue
        except Exception as e:
            print(f"  Error scraping {dispensary['name']} {category}: {e}")
    return products


async def scrape_dutchie(page, dispensary):
    """Scrape Dutchie-powered dispensaries (AYR, Ascend)."""
    products = []
    try:
        await page.goto(dispensary["url_flower"], wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        await dismiss_age_gate(page)
        await page.wait_for_timeout(3000)

        # Dutchie uses category filters in URL or sidebar
        for category_name, category_filter in [("flower", "Flower"), ("vape", "Vaporizers")]:
            try:
                # Click category filter
                filter_btn = page.locator(f"text={category_filter}").first
                if await filter_btn.is_visible(timeout=5000):
                    await filter_btn.click()
                    await page.wait_for_timeout(2000)

                cards = await page.query_selector_all(
                    "[class*='product-card'], [class*='ProductCard'], [data-testid*='product']"
                )

                for card in cards:
                    try:
                        price_el = await card.query_selector(
                            "[class*='price'], [class*='Price']"
                        )
                        if not price_el:
                            continue
                        price_text = await price_el.inner_text()
                        price_num = float(
                            price_text.replace("$", "").replace(",", "").strip().split()[0]
                        )
                        if price_num > MAX_PRICE:
                            continue

                        name_el = await card.query_selector(
                            "[class*='name'], [class*='Name'], h3, h4, p"
                        )
                        name = await name_el.inner_text() if name_el else "Unknown"

                        img_el = await card.query_selector("img")
                        img_src = await img_el.get_attribute("src") if img_el else ""

                        link_el = await card.query_selector("a")
                        href = await link_el.get_attribute("href") if link_el else dispensary["url_flower"]
                        if href and not href.startswith("http"):
                            href = dispensary["base_url"] + href

                        products.append({
                            "name": name.strip(),
                            "price": price_num,
                            "category": category_name,
                            "image": img_src,
                            "link": href,
                            "dispensary": dispensary["name"],
                            "badge": dispensary["badge"],
                            "label": dispensary["label"],
                            "color": dispensary["color"],
                        })
                    except Exception:
                        continue
            except Exception as e:
                print(f"  Dutchie category error {category_name}: {e}")
    except Exception as e:
        print(f"  Dutchie error {dispensary['name']}: {e}")
    return products


async def scrape_apothecarium(page, dispensary):
    """Scrape Apothecarium's custom shop."""
    products = []
    for category_name, url in [
        ("flower", dispensary["url_flower"]),
        ("vape", dispensary["url_vape"]),
    ]:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
            await dismiss_age_gate(page)
            await page.wait_for_timeout(3000)

            cards = await page.query_selector_all(
                "[class*='product'], [class*='Product'], .product-item, [data-product]"
            )

            for card in cards:
                try:
                    price_el = await card.query_selector(
                        "[class*='price'], [class*='Price'], .price"
                    )
                    if not price_el:
                        continue
                    price_text = await price_el.inner_text()
                    digits = "".join(c for c in price_text if c.isdigit() or c == ".")
                    if not digits:
                        continue
                    price_num = float(digits)
                    if price_num > MAX_PRICE:
                        continue

                    name_el = await card.query_selector(
                        "[class*='name'], [class*='title'], h3, h4, h2"
                    )
                    name = await name_el.inner_text() if name_el else "Unknown"

                    img_el = await card.query_selector("img")
                    img_src = await img_el.get_attribute("src") if img_el else ""
                    if img_src and img_src.startswith("/"):
                        img_src = dispensary["base_url"] + img_src

                    link_el = await card.query_selector("a")
                    href = await link_el.get_attribute("href") if link_el else url
                    if href and href.startswith("/"):
                        href = dispensary["base_url"] + href

                    products.append({
                        "name": name.strip(),
                        "price": price_num,
                        "category": category_name,
                        "image": img_src,
                        "link": href,
                        "dispensary": dispensary["name"],
                        "badge": dispensary["badge"],
                        "label": dispensary["label"],
                        "color": dispensary["color"],
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"  Apothecarium error {category_name}: {e}")
    return products


async def scrape_kindkush(page, dispensary):
    """Scrape Kind Kush's own site."""
    products = []
    for category_name, url in [
        ("flower", dispensary["url_flower"]),
        ("vape", dispensary["url_vape"]),
    ]:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
            await dismiss_age_gate(page)
            await page.wait_for_timeout(3000)

            # Try to filter by category
            for filter_text in ["Flower", "Vape", "Vaporizer", "Cartridge"]:
                if (category_name == "flower" and filter_text == "Flower") or \
                   (category_name == "vape" and filter_text in ["Vape", "Vaporizer", "Cartridge"]):
                    try:
                        btn = page.locator(f"text={filter_text}").first
                        if await btn.is_visible(timeout=2000):
                            await btn.click()
                            await page.wait_for_timeout(1500)
                    except Exception:
                        pass

            cards = await page.query_selector_all(
                "[class*='product'], [class*='Product'], .menu-item, [data-testid*='product']"
            )

            for card in cards:
                try:
                    price_el = await card.query_selector(
                        "[class*='price'], [class*='Price'], .price"
                    )
                    if not price_el:
                        continue
                    price_text = await price_el.inner_text()
                    digits = "".join(c for c in price_text if c.isdigit() or c == ".")
                    if not digits:
                        continue
                    price_num = float(digits)
                    if price_num > MAX_PRICE:
                        continue

                    name_el = await card.query_selector(
                        "[class*='name'], [class*='title'], h3, h4"
                    )
                    name = await name_el.inner_text() if name_el else "Unknown"

                    img_el = await card.query_selector("img")
                    img_src = await img_el.get_attribute("src") if img_el else ""

                    link_el = await card.query_selector("a")
                    href = await link_el.get_attribute("href") if link_el else url
                    if href and href.startswith("/"):
                        href = dispensary["base_url"] + href

                    products.append({
                        "name": name.strip(),
                        "price": price_num,
                        "category": category_name,
                        "image": img_src,
                        "link": href,
                        "dispensary": dispensary["name"],
                        "badge": dispensary["badge"],
                        "label": dispensary["label"],
                        "color": dispensary["color"],
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"  Kind Kush error {category_name}: {e}")
    return products


async def main():
    all_products = []
    print(f"🌿 Budtender scrape started at {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844},
        )

        for dispensary in DISPENSARIES:
            print(f"\n📍 Scraping {dispensary['name']}...")
            page = await context.new_page()

            try:
                name = dispensary["name"]
                if "RISE" in name:
                    products = await scrape_rise(page, dispensary)
                elif "AYR" in name or "Ascend" in name:
                    products = await scrape_dutchie(page, dispensary)
                elif "Apothecarium" in name:
                    products = await scrape_apothecarium(page, dispensary)
                elif "Kind Kush" in name:
                    products = await scrape_kindkush(page, dispensary)
                else:
                    products = []

                print(f"  ✅ Found {len(products)} deals under ${MAX_PRICE}")
                all_products.extend(products)
            except Exception as e:
                print(f"  ❌ Failed: {e}")
            finally:
                await page.close()

        await browser.close()

    # Sort by price ascending
    all_products.sort(key=lambda x: x["price"])

    output = {
        "last_updated": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
        "max_price": MAX_PRICE,
        "total_deals": len(all_products),
        "products": all_products,
    }

    with open("deals.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Done! {len(all_products)} total deals saved to deals.json")


if __name__ == "__main__":
    asyncio.run(main())
