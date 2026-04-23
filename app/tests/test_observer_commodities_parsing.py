"""Tests for TradingEconomics commodity row normalization."""

import unittest

from app.services.observer_service import SiteObserver


class _FakeLocator:
    def __init__(self, page, selector: str):
        self._page = page
        self._selector = selector

    def locator(self, nested_selector: str):
        return _FakeLocator(self._page, f"{self._selector} >> {nested_selector}")

    async def count(self):
        if self._selector in self._page.selector_counts:
            return self._page.selector_counts[self._selector]
        return self._page.selector_counts.get(self._selector.split(" >> ")[-1], 0)

    async def all_inner_texts(self):
        return self._page.selector_texts.get(self._selector, [])


class _FakePage:
    def __init__(self, selector_counts=None, selector_texts=None):
        self.selector_counts = selector_counts or {}
        self.selector_texts = selector_texts or {}
        self.seen_selectors = []

    def locator(self, selector: str):
        self.seen_selectors.append(selector)
        return _FakeLocator(self, selector)


class TradingEconomicsCommodityParsingTests(unittest.TestCase):
    def test_extracts_symbol_price_and_change(self):
        rows = [
            {
                "group": "Metals",
                "pair": "XAUUSD:CUR",
                "common_name": "Gold",
                "price": "4833.56",
                "change_text": "0.94%",
            },
            {
                "group": "Metals",
                "pair": "HG1:COM",
                "common_name": "Copper",
                "price": "6.1035",
                "change_text": "-0.61%",
            },
        ]

        parsed = SiteObserver._normalize_tradingeconomics_commodities(rows)

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["pair"], "XAUUSD:CUR")
        self.assertEqual(parsed[0]["common_name"], "Gold")
        self.assertEqual(parsed[0]["price"], "4833.56")
        self.assertEqual(parsed[0]["change"], "0.94")

        self.assertEqual(parsed[1]["pair"], "HG1:COM")
        self.assertEqual(parsed[1]["common_name"], "Copper")
        self.assertEqual(parsed[1]["price"], "6.1035")
        self.assertEqual(parsed[1]["change"], "-0.61")

    def test_filters_for_metals_group_only(self):
        """Verify that only Metals group rows are returned."""
        rows = [
            {
                "group": "Energy",
                "pair": "CL1:COM",
                "common_name": "Crude Oil",
                "price": "93.37",
                "change_text": "0.41%",
            },
            {
                "group": "Metals",
                "pair": "XAUUSD:CUR",
                "common_name": "Gold",
                "price": "4833.56",
                "change_text": "0.94%",
            },
            {
                "group": "Agricultural",
                "pair": "S 1:COM",
                "common_name": "Soybeans",
                "price": "11.78",
                "change_text": "1.23%",
            },
            {
                "group": "Metals",
                "pair": "HG1:COM",
                "common_name": "Copper",
                "price": "6.1035",
                "change_text": "-0.61%",
            },
        ]

        parsed = SiteObserver._normalize_tradingeconomics_commodities(rows)\n\n        self.assertEqual(len(parsed), 2)\n        # Should only contain Metals\n        pairs = {row[\"pair\"] for row in parsed}\n        self.assertEqual(pairs, {\"XAUUSD:CUR\", \"HG1:COM\"})\n        # Verify non-Metals are excluded\n        self.assertNotIn(\"CL1:COM\", pairs)  # Energy\n        self.assertNotIn(\"S 1:COM\", pairs)  # Agricultural\n\n    def test_deduplicates_by_pair_preferring_quality(self):\n        \"\"\"Verify that duplicate pairs are deduplicated, keeping higher quality row.\"\"\"\n        rows = [\n            {\n                \"group\": \"Metals\",\n                \"pair\": \"XAUUSD:CUR\",\n                \"common_name\": \"\",  # Lower quality: missing name\n                \"price\": \"4833.56\",\n                \"change_text\": \"\",  # Lower quality: missing change\n            },\n            {\n                \"group\": \"Metals\",\n                \"pair\": \"XAUUSD:CUR\",  # Duplicate pair\n                \"common_name\": \"Gold\",  # Higher quality: has name\n                \"price\": \"4833.56\",\n                \"change_text\": \"0.94%\",  # Higher quality: has change\n            },\n        ]\n\n        parsed = SiteObserver._normalize_tradingeconomics_commodities(rows)\n\n        # Should contain only one row (deduplicated)\n        self.assertEqual(len(parsed), 1)\n        # Should keep the higher-quality row\n        self.assertEqual(parsed[0][\"pair\"], \"XAUUSD:CUR\")\n        self.assertEqual(parsed[0][\"common_name\"], \"Gold\")\n        self.assertEqual(parsed[0][\"change\"], \"0.94\")\n\n    def test_drops_incomplete_rows(self):\n        rows = [\n            {\n                \"group\": \"Metals\",\n                \"pair\": \"\",\n                \"common_name\": \"Invalid\",\n                \"price\": \"10.0\",\n                \"change_text\": \"1.00%\",\n            },\n            {\n                \"group\": \"Metals\",\n                \"pair\": \"XAGUSD:CUR\",\n                \"common_name\": \"Silver\",\n                \"price\": \"\",\n                \"change_text\": \"2.99%\",\n            },\n            {\n                \"group\": \"Metals\",\n                \"pair\": \"XPTUSD:CUR\",\n                \"common_name\": \"Platinum\",\n                \"price\": \"2141.70\",\n                \"change_text\": \"n/a\",\n            },\n        ]

        parsed = SiteObserver._normalize_tradingeconomics_commodities(rows)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0][\"pair\"], \"XPTUSD:CUR\")
        self.assertEqual(parsed[0][\"common_name\"], \"Platinum\")
        self.assertEqual(parsed[0][\"price\"], \"2141.70\")
        self.assertIsNone(parsed[0][\"change\"])

    def test_blocked_page_heuristic_detects_real_indicators(self):
        blocked = SiteObserver._looks_like_blocked_page(
            content="Please verify you are human before continuing",
            page_title="Just a moment...",
        )
        self.assertTrue(blocked)

    def test_blocked_page_heuristic_ignores_generic_captcha_word(self):
        blocked = SiteObserver._looks_like_blocked_page(
            content="This script contains captcha telemetry token for analytics only",
            page_title="Commodities - Live Quote Price Trading Data",
        )
        self.assertFalse(blocked)


class TradingEconomicsCommoditySelectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_selects_quoted_commodity_selector_without_js_interpolation(self):
        page = _FakePage(
            selector_counts={
                "table[id^='commodity-']": 1,
                "table[id^='commodity-'] >> tbody tr[data-symbol]": 1,
                "table[id^='commodity-'] >> thead th": 1,
            },
            selector_texts={
                "table[id^='commodity-'] >> thead th": ["Metals"],
            },
        )
        observer = SiteObserver(
            url="https://example.com",
            table_selector="table[id^='commodity-']",
            pair_cell_selector="tbody tr td.datatable-item-first b",
            source_name="commodities",
        )
        observer.page = page

        table = await observer._select_tradingeconomics_commodity_table()

        self.assertIsNotNone(table)
        self.assertIn("table[id^='commodity-']", page.seen_selectors)


if __name__ == "__main__":
    unittest.main()
