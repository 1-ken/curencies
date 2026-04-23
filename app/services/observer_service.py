"""
Browser-based observer for real-time market data using Playwright.
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

logger = logging.getLogger(__name__)


class SiteObserver:
    def __init__(
        self,
        url: str,
        table_selector: str,
        pair_cell_selector: str,
        wait_selector: str = "body",
        inject_mutation_observer: bool = True,
        filter_by_majors: bool = True,
        source_name: str = "default",
    ) -> None:
        self.url = url
        self.table_selector = table_selector
        self.pair_cell_selector = pair_cell_selector
        self.wait_selector = wait_selector
        self.inject_mutation_observer = inject_mutation_observer
        self.filter_by_majors = filter_by_majors
        self.source_name = source_name

        self._pw = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        # Context recycling to prevent memory leaks
        self.snapshot_count = 0
        self.context_created_at: Optional[datetime] = None
        self.CONTEXT_RESET_INTERVAL = 3600  # 1 hour in seconds
        self.CONTEXT_RESET_SNAPSHOT_COUNT = 1200  # Reset after 1200 snapshots
        self.NAVIGATION_TIMEOUT_MS = 15000
        self.NAVIGATION_TIMEOUT_MAX_MS = 45000
        self.NAVIGATION_RETRY_ATTEMPTS = 3
        self._context_reset_lock = asyncio.Lock()
        self._snapshot_lock = asyncio.Lock()
        self._is_resetting_context = False

    @staticmethod
    def _is_consent_or_blocked(url: str, title: str) -> bool:
        marker = f"{(url or '').lower()}\n{(title or '').lower()}"
        return any(
            token in marker
            for token in (
                "consent.yahoo.com",
                "collectconsent",
                "privacy settings",
                "parametres de confidentialite",
                "parametres de confidentialit",
                "vos parametres de confidentialite",
                "access denied",
                "verify you are human",
                "captcha",
            )
        )

    async def _ensure_source_ready(self, *, force_navigate: bool = False) -> None:
        """Ensure page is on the expected source URL and data selectors are available."""
        if not self.page:
            return

        try:
            current_url = self.page.url
            current_title = await self.page.title()
        except Exception:
            current_url = ""
            current_title = ""

        if force_navigate or self._is_consent_or_blocked(current_url, current_title):
            logger.warning(
                "[%s] Page appears redirected/blocked (title=%s, url=%s); attempting recovery",
                self.source_name,
                current_title,
                current_url,
            )
            await self._handle_cookie_consent()
            await self._navigate_with_retry()
            await self._handle_cookie_consent()

        try:
            await self._wait_for_data_ready_selector()
        except Exception:
            await self._wait_for_table_selector_fallback()

    def _needs_context_reset(self) -> bool:
        if not self.context_created_at:
            return False
        age_seconds = (datetime.now() - self.context_created_at).total_seconds()
        return (
            self.snapshot_count >= self.CONTEXT_RESET_SNAPSHOT_COUNT
            or age_seconds >= self.CONTEXT_RESET_INTERVAL
        )

    async def _create_context_and_page(self) -> None:
        if not self.browser:
            raise RuntimeError("Browser not started")

        self.context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
        )
        self.context_created_at = datetime.now()
        await self.context.add_init_script(
            """{
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            }"""
        )
        self.page = await self.context.new_page()
        await self.page.route(
            "**/*",
            lambda route: (
                route.abort()
                if route.request.resource_type in {"image", "font", "media"}
                else route.continue_()
            ),
        )

    async def _navigate_with_retry(self) -> None:
        if not self.page:
            raise RuntimeError("Page not initialized")

        timeout_ms = self.NAVIGATION_TIMEOUT_MS
        for attempt in range(1, self.NAVIGATION_RETRY_ATTEMPTS + 1):
            try:
                await self.page.goto(
                    self.url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                return
            except PlaywrightTimeoutError as e:
                if attempt >= self.NAVIGATION_RETRY_ATTEMPTS:
                    raise
                logger.warning(
                    "Navigation timeout (%sms) on attempt %s/%s: %s; retrying",
                    timeout_ms,
                    attempt,
                    self.NAVIGATION_RETRY_ATTEMPTS,
                    e,
                )
                await asyncio.sleep(min(2 * attempt, 5))
                timeout_ms = min(timeout_ms + 10000, self.NAVIGATION_TIMEOUT_MAX_MS)

    async def _inject_mutation_observer_script(self) -> None:
        if not self.inject_mutation_observer or not self.page:
            return
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
            await self._create_context_and_page()
            await self._navigate_with_retry()
            
            # Check for and handle cookie consent popup (Yahoo Finance)
            await self._handle_cookie_consent()
            
            # Don't wait for networkidle - modern sites never reach it.
            # Instead, wait for source-specific selectors to appear.
            try:
                await self._wait_for_data_ready_selector()
            except Exception as e:
                logger.warning(f"Wait selector timeout: {e}. Continuing anyway...")
                # Still try to fall back to table selector
                try:
                    await self._wait_for_table_selector_fallback()
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
                        page_title = await self.page.title()
                        logger.info(f"Page title: {page_title}")
                        # Check if we likely got an anti-bot/access block page.
                        if self._looks_like_blocked_page(content, page_title):
                            logger.error("Page appears to show a bot-check or access denied page")
                    except Exception as e4:
                        logger.error(f"Failed to get page content: {e4}")
            logger.info("Browser started successfully")

            await self._inject_mutation_observer_script()
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            await self.shutdown()
            raise

    async def _handle_cookie_consent(self) -> None:
        """Handle cookie consent popup if it appears on page load."""
        if not self.page:
            return
        
        # Skip if context is being recycled to avoid race conditions
        if self._is_resetting_context:
            return
        
        try:
            # Wait briefly for the consent popup to appear
            # Try multiple possible selectors for the "Accept all" button
            selectors = [
                'button[name="agree"][value="agree"]',  # Yahoo Finance specific
                'button[name="agree"]',
                'button[value="agree"]',
                'button.accept-all',
                'button.consent_reject_all_2',
                'button:has-text("Accepter tout")',  # French version
                'button:has-text("Tout accepter")',
                'button:has-text("Accept all")',  # English version
                'button:has-text("I agree")',
                'button:has-text("Agree")',
                'button[type="submit"]',
            ]
            
            for selector in selectors:
                try:
                    # Check if the button exists with a short timeout
                    # Wrap in try/except to handle context closure during wait
                    try:
                        consent_button = await self.page.wait_for_selector(
                            selector, 
                            timeout=1500,
                            state="visible"
                        )
                    except Exception:
                        # Selector not found or wait failed, skip this one
                        continue
                    
                    if consent_button:
                        try:
                            logger.info(f"Cookie consent popup detected, clicking accept button: {selector}")
                            await consent_button.click()
                            # Wait a moment for the popup to disappear
                            await self.page.wait_for_timeout(500)
                            logger.info("Cookie consent accepted successfully")
                            return
                        except Exception as e:
                            logger.debug(f"Failed to click consent button: {e}")
                            continue
                        
                except Exception:
                    # Suppress error and try next selector
                    continue
            
            logger.debug("No cookie consent popup detected, continuing with normal flow")
            
        except Exception as e:
            logger.debug(f"Error while handling cookie consent: {e}. Continuing anyway...")

    async def _wait_for_data_ready_selector(self) -> None:
        """Wait for source-specific row selector(s) that indicate data is ready."""
        if not self.page:
            raise RuntimeError("Page not initialized")

        if self.source_name.lower() != "commodities":
            await self.page.wait_for_selector(self.wait_selector, timeout=30000)
            return

        selectors = [
            self.wait_selector,
            "table[id^='commodity-'] tbody tr[data-symbol]",
            "table.table-heatmap tbody tr[data-symbol]",
            "div.card table tbody tr[data-symbol]",
        ]
        for selector in selectors:
            try:
                await self.page.wait_for_selector(selector, timeout=10000)
                return
            except Exception:
                continue
        raise TimeoutError("No commodities row selector became available")

    async def _wait_for_table_selector_fallback(self) -> None:
        """Wait for source-specific table selector(s) as secondary readiness fallback."""
        if not self.page:
            raise RuntimeError("Page not initialized")

        if self.source_name.lower() != "commodities":
            await self.page.wait_for_selector(self.table_selector, timeout=10000)
            return

        selectors = [
            self.table_selector,
            "table[id^='commodity-']",
            "table.table-heatmap",
            "div.card table.table",
        ]
        for selector in selectors:
            try:
                await self.page.wait_for_selector(selector, timeout=5000)
                return
            except Exception:
                continue
        raise TimeoutError("No commodities table selector became available")

    @staticmethod
    def _looks_like_blocked_page(content: str, page_title: str) -> bool:
        """Heuristic to detect anti-bot/access-denied pages while avoiding noisy false positives."""
        haystack = f"{page_title}\n{content}".lower()
        indicators = [
            "access denied",
            "verify you are human",
            "are you a robot",
            "captcha challenge",
            "cf-challenge",
            "cloudflare ray id",
            "just a moment",
        ]
        return any(token in haystack for token in indicators)

    async def shutdown(self) -> None:
        """Clean up browser resources."""
        logger.info("Shutting down browser")
        try:
            if self.page:
                await self.page.close()
                self.page = None
        except Exception as e:
            if "has been closed" not in str(e):
                logger.error(f"Error closing page: {e}")

        try:
            if self.context:
                await self.context.close()
                self.context = None
        except Exception as e:
            if "has been closed" not in str(e):
                logger.error(f"Error closing context: {e}")

        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
        except Exception as e:
            logger.error(f"Error closing browser: {e}")
        finally:
            if self._pw:
                try:
                    await self._pw.stop()
                    self._pw = None
                except Exception as e:
                    logger.error(f"Error stopping playwright: {e}")

    async def _reset_context(self) -> None:
        """Recycle browser context to prevent memory leaks from accumulated metadata/cache."""
        async with self._context_reset_lock:
            if not self._needs_context_reset():
                return

            self._is_resetting_context = True
            try:
                logger.info(
                    "Recycling browser context (snapshot #%d or %.0fs old)",
                    self.snapshot_count,
                    (datetime.now() - self.context_created_at).total_seconds() if self.context_created_at else 0,
                )

                if self.page:
                    try:
                        await self.page.close()
                    except Exception as e:
                        logger.warning(f"Error closing page during context reset: {e}")
                    finally:
                        self.page = None

                if self.context:
                    try:
                        await self.context.close()
                    except Exception as e:
                        logger.warning(f"Error closing context during context reset: {e}")
                    finally:
                        self.context = None

                if self.browser:
                    await self._create_context_and_page()
                    await self._ensure_source_ready(force_navigate=True)
                    await self._inject_mutation_observer_script()

                    self.snapshot_count = 0
                    logger.info("Context recycled successfully")
            except Exception as e:
                logger.error(f"Failed to recycle context: {e}")
                raise
            finally:
                self._is_resetting_context = False

    async def _extract_pair_cells_text(self) -> List[str]:
        if not self.page:
            return []

        table = self.page.locator(self.table_selector)
        if await table.count() == 0:
            return []

        cells = table.locator(self.pair_cell_selector)
        texts = await cells.all_inner_texts()
        return [text.strip() for text in texts if text and text.strip()]

    async def _extract_pairs_with_prices(self) -> List[Dict[str, Any]]:
        """Extract currency pairs with current price and percentage change from the table."""
        if not self.page:
            return []

        if self.source_name.lower() == "commodities":
            return await self._extract_tradingeconomics_commodities()

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

                // Extract percentage change (e.g. +0.12%, -0.08%)
                const changeCandidates = [
                    cells[4]?.textContent || '',
                    cells[5]?.textContent || '',
                    priceText,
                    row.textContent || '',
                ];
                let change = null;
                for (const candidate of changeCandidates) {{
                    const normalized = String(candidate).replace(/,/g, '');
                    const pctMatch = normalized.match(/([+-]?\\d+(?:\\.\\d+)?)\\s*%/);
                    if (pctMatch) {{
                        change = pctMatch[1];
                        break;
                    }}
                }}

                return {{
                    pair: cells[1]?.textContent.trim() || '',
                    price: priceMatch ? priceMatch[1] : priceText,
                    change,
                }};
            }}).filter(item => item && item.pair && item.price);
        }})()
        """
        pairs_data: List[Dict[str, Any]] = await self.page.evaluate(js)
        return pairs_data

    async def _extract_tradingeconomics_commodities(self) -> List[Dict[str, Any]]:
        """Extract commodity rows from ALL TradingEconomics commodity tables.
        
        Handles multiple tables with dynamic CSS classes by:
        - Scanning all tables with data-symbol rows
        - Mapping tables to groups using hidden input[id$='_group'] elements
        - Extracting values using stable structural selectors (data-symbol, cell position)
        - Avoiding brittle ID-based selectors (#p, #pch) which repeat across tables
        """
        if not self.page:
            return []

        raw_rows: List[Dict[str, Any]] = await self.page.evaluate(
            """
            () => {
                const normalize = (value) => (value || '').toString().trim();
                
                // Build table-to-group map using hidden input[id$='_group'] elements
                const buildTableGroupMap = () => {
                    const map = new Map(); // table element -> group name
                    const groupInputs = Array.from(
                        document.querySelectorAll("input[id$='_group']")
                    );
                    
                    groupInputs.forEach((input) => {
                        const groupValue = normalize(input.value);
                        if (!groupValue) return;
                        
                        // Find the nearest table that follows this input
                        let current = input;
                        while (current && current !== document.body) {
                            current = current.nextElementSibling || current.parentElement?.nextElementSibling;
                            if (!current) break;
                            
                            const table = current.querySelector('table[id^="commodity-"]')
                                || current.querySelector('table.table-heatmap');
                            if (table && table.querySelectorAll('tbody tr[data-symbol]').length > 0) {
                                map.set(table, groupValue);
                                break;
                            }
                        }
                    });
                    
                    return map;
                };
                
                const tableGroupMap = buildTableGroupMap();
                
                // Collect all commodity tables (those with tbody tr[data-symbol])
                const allTables = Array.from(
                    document.querySelectorAll('table[id^="commodity-"], table.table-heatmap')
                ).filter(table => table.querySelectorAll('tbody tr[data-symbol]').length > 0);
                
                const allRows = [];
                
                allTables.forEach((table, tableIndex) => {
                    const group = tableGroupMap.get(table) || `Table${tableIndex}`;
                    const rows = Array.from(table.querySelectorAll('tbody tr[data-symbol]'));
                    
                    rows.forEach((row) => {
                        const dataSymbol = normalize(row.getAttribute('data-symbol'));
                        if (!dataSymbol) return;
                        
                        // Use positional cell access instead of brittle ID-based selectors
                        // IDs like 'p', 'pch', 'nch', 'date' repeat across rows and tables
                        const cells = row.querySelectorAll('td');
                        if (!cells || cells.length < 2) return;
                        
                        // Cell 0: name cell
                        const nameCell = cells[0];
                        const commonName = normalize(
                            nameCell?.querySelector('b')?.textContent
                            || nameCell?.querySelector('a')?.textContent
                            || nameCell?.textContent
                        );
                        
                        // Cell 1: price
                        const priceRaw = normalize(cells[1]?.textContent || '').replace(/,/g, '');
                        const priceMatch = priceRaw.match(/([+-]?\d+(?:\.\d+)?)/);
                        
                        // Cell 2: change (day change, usually right after price)
                        let changeText = '';
                        if (cells.length > 2) {
                            changeText = normalize(cells[2]?.textContent || '');
                        }
                        
                        allRows.push({
                            group,
                            group_rank: tableIndex,
                            pair: dataSymbol,
                            common_name: commonName,
                            price: priceMatch ? priceMatch[1] : priceRaw,
                            change_text: changeText,
                        });
                    });
                });
                
                return allRows;
            }
            """,
        )

        return self._normalize_tradingeconomics_commodities(raw_rows)

    async def _select_tradingeconomics_commodity_table(self) -> Optional[Any]:
        if not self.page:
            return None

        selectors = [
            self.table_selector,
            "table[id^='commodity-']",
            "table.table-heatmap",
            "div.card table.table",
        ]

        for selector in selectors:
            try:
                table = self.page.locator(selector)
                rows = table.locator("tbody tr[data-symbol]")
                if await rows.count() == 0:
                    continue

                headers = table.locator("thead th")
                header_count = await headers.count()
                header_texts = await headers.all_inner_texts() if header_count > 0 else []
                if any("metals" in str(text).strip().lower() for text in header_texts):
                    return table

                return table
            except Exception:
                continue

        return None

    @staticmethod
    def _normalize_tradingeconomics_commodities(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize TradingEconomics commodity rows into payload format.
        
        Filters for Metals group only, deduplicates by pair (preferring higher quality),
        and returns normalized shape compatible with downstream API.
        """
        # Keep only Metals group rows
        metals_rows = [
            row for row in (rows or [])
            if str(row.get("group", "")).strip().lower() == "metals"
        ]
        
        # Deduplicate by pair, preferring rows with valid numeric price and common name
        seen_pairs: Dict[str, Dict[str, Any]] = {}
        
        for row in metals_rows:
            pair = str(row.get("pair") or "").strip()
            price = str(row.get("price") or "").strip()
            common_name = str(row.get("common_name") or "").strip()
            change_text = str(row.get("change_text") or "").strip()
            
            if not pair or not price:
                continue
            
            # Score row quality: valid price + non-empty name + parseable change
            has_valid_price = bool(re.match(r"[+-]?\d+(?:\.\d+)?", price))
            has_name = len(common_name) > 0
            has_change = bool(re.search(r"[+-]?\d+", change_text))
            quality_score = sum([has_valid_price, has_name, has_change])
            
            # Extract numeric change percentage
            change = None
            change_match = re.search(
                r"([+-]?\d+(?:\.\d+)?)\s*%?",
                change_text.replace(",", ""),
            )
            if change_match:
                change = change_match.group(1)
            
            normalized_row = {
                "pair": pair,
                "common_name": common_name,
                "price": price,
                "change": change,
            }
            
            # Keep row if it's new or higher quality than existing
            if pair not in seen_pairs or quality_score > seen_pairs[pair].get("_quality", -1):
                normalized_row["_quality"] = quality_score
                seen_pairs[pair] = normalized_row
        
        # Remove internal quality marker and return
        result = [
            {k: v for k, v in row.items() if k != "_quality"}
            for row in seen_pairs.values()
        ]
        
        return result

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
        async with self._snapshot_lock:
            if not self.page:
                raise RuntimeError("Observer not started. Call startup() first.")

            if self._needs_context_reset():
                await self._reset_context()

            # Lightweight self-heal in case the tab gets redirected to consent page between cycles.
            try:
                current_url = self.page.url
                current_title = await self.page.title()
                if self._is_consent_or_blocked(current_url, current_title):
                    await self._ensure_source_ready(force_navigate=True)
            except Exception:
                pass

            pairs_with_prices = await self._extract_pairs_with_prices()
            self.snapshot_count += 1
            if not pairs_with_prices:
                try:
                    title = await self.page.title()
                    logger.warning(
                        "[%s] Snapshot returned no pairs; page title=%s, url=%s",
                        self.source_name,
                        title,
                        self.page.url,
                    )
                except Exception:
                    logger.warning("[%s] Snapshot returned no pairs and title fetch failed", self.source_name)
            texts = [item["pair"] for item in pairs_with_prices]
            majors_found = self._parse_majors_from_texts(texts, majors)

            if self.filter_by_majors and majors:
                selected_pairs = [
                    item for item in pairs_with_prices
                    if any(m.upper() in item["pair"].upper() for m in majors)
                ]
            else:
                selected_pairs = pairs_with_prices

            title = await self.page.title()
            changes: List[str] = await self.page.evaluate("() => (window.__changes || []).splice(0)")
            return {
                "source": self.source_name,
                "title": title,
                "majors": majors_found,
                "pairs": selected_pairs,
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
        filter_by_majors=bool(cfg.get("filterByMajors", True)),
        source_name=str(cfg.get("name", "default")),
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
    cfg_path = os.path.join(here, "..", "..", "config.json")

    async def _main():
        data = await observe_once_from_config(cfg_path)
        print(json.dumps(data, indent=2))

    asyncio.run(_main())
