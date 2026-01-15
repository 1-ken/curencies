#!/usr/bin/env python
"""
Debug script to inspect the website and find correct CSS selectors.
Run this to see what elements are available on the target site.
"""
import asyncio
from playwright.async_api import async_playwright


async def inspect_page():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page()
    
    url = "https://finance.yahoo.com/markets/currencies/"
    print(f"Loading {url}...")
    await page.goto(url, wait_until="networkidle")
    
    # Wait a bit for JS to render
    await asyncio.sleep(3)
    
    # Get page title
    title = await page.title()
    print(f"\nPage Title: {title}")
    
    # Look for tables
    tables = await page.query_selector_all("table")
    print(f"\nFound {len(tables)} tables on the page")
    
    # Look for currency pairs
    print("\n--- Looking for currency pair elements ---")
    
    # Try different selectors
    selectors_to_try = [
        ("tr", "All rows"),
        ("table", "All tables"),
        ("[data-symbol]", "Elements with data-symbol"),
        (".data-row", "Elements with data-row class"),
        ("tbody tr", "Table body rows"),
        ("td", "All table cells (first 20)"),
    ]
    
    for selector, description in selectors_to_try:
        elements = await page.query_selector_all(selector)
        print(f"\n{description} (selector: {selector}): {len(elements)} found")
        if elements and len(elements) > 0:
            # Show first few elements
            for i, elem in enumerate(elements[:3]):
                text = await elem.text_content()
                if text and text.strip():
                    print(f"  [{i}] {text[:80]}")
    
    # Get all visible text from page (first 2000 chars)
    all_text = await page.text_content()
    print(f"\n--- Page Text Sample (first 500 chars) ---")
    print(all_text[:500])
    
    await browser.close()
    await p.stop()


if __name__ == "__main__":
    asyncio.run(inspect_page())
