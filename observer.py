import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright, Browser, Page


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
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(headless=True)
        context = await self.browser.new_context()
        self.page = await context.new_page()
        await self.page.goto(self.url)
        await self.page.wait_for_selector(self.wait_selector, timeout=30000)

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

    async def shutdown(self) -> None:
        try:
            if self.browser:
                await self.browser.close()
        finally:
            if self._pw:
                await self._pw.stop()

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

        texts = await self._extract_pair_cells_text()
        majors_found = self._parse_majors_from_texts(texts, majors)
        title = await self.page.title()
        changes: List[str] = await self.page.evaluate("() => (window.__changes || []).splice(0)")
        return {
            "title": title,
            "majors": majors_found,
            "pairsSample": texts[:10],
            "changes": changes,
            "ts": datetime.now(timezone.utc).isoformat(),
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
