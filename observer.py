import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright, Browser, Page

logger = logging.getLogger(__name__)


class SiteObserver:
    def __init__(
        self,
        url: str,
        table_selector: str,
        pair_cell_selector: str,
        wait_selector: str = "body",
        inject_mutation_observer: bool = True,
    ) -> None:
        self.url = url
        self.table_selector = table_selector
        self.pair_cell_selector = pair_cell_selector
        self.wait_selector = wait_selector
        self.inject_mutation_observer = inject_mutation_observer

        self._pw = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    async def startup(self) -> None:
        """Initialize the browser and navigate to the target URL."""
        try:
            logger.info(f"Starting browser and navigating to {self.url}")
            self._pw = await async_playwright().start()
            self.browser = await self._pw.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                ]
            )
            context = await self.browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                viewport={'width': 1920, 'height': 1080},
                extra_http_headers={
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                }
            )
            # Override navigator.webdriver flag
            await context.add_init_script("""{
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            }""")
            self.page = await context.new_page()
            # Block heavy assets, keep stylesheets and scripts
            await self.page.route("**/*", lambda route: (
                route.abort()
                if route.request.resource_type in {"image", "font", "media"}
                else route.continue_()
            ))
            await self.page.goto(self.url, wait_until="domcontentloaded")
            
            # Check for and handle cookie consent popup (Yahoo Finance)
            await self._handle_cookie_consent()
            
            # Don't wait for networkidle - modern sites never reach it
            # Instead, wait for the specific table element to appear
            try:
                await self.page.wait_for_selector(self.wait_selector, timeout=30000)
            except Exception as e:
                logger.warning(f"Wait selector timeout: {e}. Continuing anyway...")
                # Still try to fall back to table selector
                try:
                    await self.page.wait_for_selector(self.table_selector, timeout=10000)
                except Exception as e2:
                    logger.warning(f"Table selector also not found: {e2}. Proceeding with extraction...")
                    # Take a screenshot for debugging
                    try:
                        screenshot_path = f"debug_screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                        await self.page.screenshot(path=screenshot_path, full_page=True)
                        logger.info(f"Screenshot saved to {screenshot_path}")
                    except Exception as e3:
                        logger.error(f"Failed to take screenshot: {e3}")
                    # Log page content for debugging
                    try:
                        content = await self.page.content()
                        logger.info(f"Page HTML length: {len(content)} characters")
                        logger.info(f"Page title: {await self.page.title()}")
                        # Check if we got an error page or captcha
                        if "captcha" in content.lower() or "access denied" in content.lower():
                            logger.error("Page appears to show captcha or access denied message")
                    except Exception as e4:
                        logger.error(f"Failed to get page content: {e4}")
            logger.info("Browser started successfully")

            if self.inject_mutation_observer:
                await self.page.evaluate(
                    """
                    () => {
                        window.__changes = [];
                        const observer = new MutationObserver(mutations => {
                            mutations.forEach(m => window.__changes.push(m.type));
                        });
                        observer.observe(document.body, { childList: true, subtree: true });
                        window.__observer = observer;
                    }
                    """
                )
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            raise

    async def _handle_cookie_consent(self) -> None:
        """Handle cookie consent popup if it appears on page load."""
        if not self.page:
            return
        
        try:
            # Wait briefly for the consent popup to appear
            # Try multiple possible selectors for the "Accept all" button
            selectors = [
                'button[name="agree"][value="agree"]',  # Yahoo Finance specific
                'button.accept-all',
                'button.consent_reject_all_2',
                'button:has-text("Accepter tout")',  # French version
                'button:has-text("Accept all")',  # English version
            ]
            
            for selector in selectors:
                try:
                    # Check if the button exists with a short timeout
                    consent_button = await self.page.wait_for_selector(
                        selector, 
                        timeout=3000,
                        state="visible"
                    )
                    
                    if consent_button:
                        logger.info(f"Cookie consent popup detected, clicking accept button: {selector}")
                        await consent_button.click()
                        # Wait a moment for the popup to disappear
                        await self.page.wait_for_timeout(1000)
                        logger.info("Cookie consent accepted successfully")
                        return
                        
                except Exception:
                    # This selector didn't match, try the next one
                    continue
            
            logger.debug("No cookie consent popup detected, continuing with normal flow")
            
        except Exception as e:
            logger.warning(f"Error while handling cookie consent: {e}. Continuing anyway...")

    async def shutdown(self) -> None:
        """Clean up browser resources."""
        logger.info("Shutting down browser")
        try:
            if self.browser:
                await self.browser.close()
        except Exception as e:
            logger.error(f"Error closing browser: {e}")
        finally:
            if self._pw:
                try:
                    await self._pw.stop()
                except Exception as e:
                    logger.error(f"Error stopping playwright: {e}")

    async def _extract_pair_cells_text(self) -> List[str]:
        if not self.page:
            return []
        js = f"""
        (() => {{
            const table = document.querySelector('{self.table_selector}');
            if (!table) return [];
            const cells = table.querySelectorAll('{self.pair_cell_selector}');
            return Array.from(cells).map(td => td.textContent.trim()).filter(Boolean);
        }})()
        """
        texts: List[str] = await self.page.evaluate(js)
        return texts

    async def _extract_pairs_with_prices(self) -> List[Dict[str, str]]:
        """Extract currency pairs with their current prices from the table."""
        if not self.page:
            return []
        js = f"""
        (() => {{
            const table = document.querySelector('{self.table_selector}');
            if (!table) return [];
            const rows = table.querySelectorAll('tbody tr');
            return Array.from(rows).map(row => {{
                const cells = row.querySelectorAll('td');
                if (cells.length < 4) return null;
                const priceText = cells[3]?.textContent.trim() || '';
                // Extract just the price (first number before any +/- change)
                const priceMatch = priceText.match(/^([\\d,\\.]+)/);
                return {{
                    pair: cells[1]?.textContent.trim() || '',
                    price: priceMatch ? priceMatch[1] : priceText
                }};
            }}).filter(item => item && item.pair && item.price);
        }})()
        """
        pairs_data: List[Dict[str, str]] = await self.page.evaluate(js)
        return pairs_data

    @staticmethod
    def _parse_majors_from_texts(texts: List[str], majors: List[str]) -> List[str]:
        majors_set = set(m.upper() for m in majors)
        found = set()
        for txt in texts:
            # Extract 3-letter codes split by common separators
            tokens = re.split(r"[\s/\-:]+", txt.upper())
            for tok in tokens:
                if len(tok) == 3 and tok.isalpha() and tok in majors_set:
                    found.add(tok)
        return sorted(found)

    async def snapshot(self, majors: List[str]) -> Dict[str, Any]:
        if not self.page:
            raise RuntimeError("Observer not started. Call startup() first.")

        pairs_with_prices = await self._extract_pairs_with_prices()
        if not pairs_with_prices:
            # Extra logging to understand why stream is empty on VPS
            try:
                title = await self.page.title()
                logger.warning(
                    "Snapshot returned no pairs; page title=%s, url=%s", title, self.page.url
                )
            except Exception:
                logger.warning("Snapshot returned no pairs and title fetch failed")
        texts = [item["pair"] for item in pairs_with_prices]
        majors_found = self._parse_majors_from_texts(texts, majors)
        
        # Filter pairs to only include those with majors
        major_pairs = [
            item for item in pairs_with_prices
            if any(m.upper() in item["pair"].upper() for m in majors)
        ]
        
        title = await self.page.title()
        changes: List[str] = await self.page.evaluate("() => (window.__changes || []).splice(0)")
        return {
            "title": title,
            "majors": majors_found,
            "pairs": major_pairs,
            "pairsSample": texts[:10],
            "changes": changes,
            "ts": datetime.now().isoformat(),
        }


async def observe_once_from_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    observer = SiteObserver(
        url=cfg.get("url", "https://example.com"),
        table_selector=cfg.get("tableSelector", "#pairs-table"),
        pair_cell_selector=cfg.get("pairCellSelector", "tbody tr td:first-child"),
        wait_selector=cfg.get("waitSelector", "body"),
        inject_mutation_observer=bool(cfg.get("injectMutationObserver", True)),
    )

    try:
        await observer.startup()
        data = await observer.snapshot(cfg.get("majors", []))
        return data
    finally:
        await observer.shutdown()


if __name__ == "__main__":
    # Quick manual test: prints a single snapshot
    here = os.path.dirname(__file__)
    cfg_path = os.path.join(here, "config.json")

    async def _main():
        data = await observe_once_from_config(cfg_path)
        print(json.dumps(data, indent=2))

    asyncio.run(_main())

