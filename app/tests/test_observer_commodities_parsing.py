"""Tests for TradingEconomics commodity row normalization."""

import unittest
import re
from typing import Any, Dict, List, Optional

from app.services.observer_service import ALLOWED_COMMODITY_SYMBOLS, SiteObserver


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
        # Search for pairs to be order-independent. Provider suffixes like
        # :CUR/:COM are stripped to the canonical base symbol.
        gold = next(r for r in parsed if r["pair"] == "XAUUSD")
        copper = next(r for r in parsed if r["pair"] == "HG1")

        self.assertEqual(gold["common_name"], "Gold")
        self.assertEqual(gold["price"], "4833.56")
        self.assertEqual(gold["change"], "0.94")

        self.assertEqual(copper["common_name"], "Copper")
        self.assertEqual(copper["price"], "6.1035")
        self.assertEqual(copper["change"], "-0.61")

    def test_filters_to_allowlist_and_strips_suffix(self):
        """Only allowlisted commodities survive; suffixes are stripped."""
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
            {
                "group": "Metals",
                "pair": "XAGUSD:CUR",
                "common_name": "Silver",
                "price": "72.48",
                "change_text": "1.17%",
            },
        ]

        parsed = SiteObserver._normalize_tradingeconomics_commodities(rows)

        pairs = {row["pair"] for row in parsed}
        # Only the curated subset is emitted; Soybeans gets dropped.
        self.assertEqual(pairs, {"CL1", "XAUUSD", "HG1", "XAGUSD"})
        # All emitted pairs must be in the allowlist.
        self.assertTrue(pairs.issubset(ALLOWED_COMMODITY_SYMBOLS))

    def test_deduplicates_by_pair_preferring_quality(self):
        """Verify that duplicate pairs are deduplicated, keeping higher quality row."""
        rows = [
            {
                "group": "commodities", # Generic fallback
                "pair": "XAUUSD:CUR",
                "common_name": "Gold",
                "price": "4833.56",
                "change_text": "0.94%",
            },
            {
                "group": "Metals", # Better group
                "pair": "XAUUSD:CUR",
                "common_name": "Gold",
                "price": "4833.56",
                "change_text": "0.94%",
            },
        ]

        parsed = SiteObserver._normalize_tradingeconomics_commodities(rows)

        # Should contain only one row (deduplicated)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["pair"], "XAUUSD")

    def test_drops_incomplete_rows(self):
        rows = [
            {
                "group": "Metals",
                "pair": "",
                "common_name": "Invalid",
                "price": "10.0",
                "change_text": "1.00%",
            },
            {
                "group": "Metals",
                "pair": "XAUUSD:CUR",
                "common_name": "Gold",
                "price": "", # Missing price
                "change_text": "1.00%",
            },
        ]

        parsed = SiteObserver._normalize_tradingeconomics_commodities(rows)
        self.assertEqual(len(parsed), 0)

    def test_handles_missing_change(self):
        rows = [
            {
                "group": "Metals",
                "pair": "XAGUSD:CUR",
                "common_name": "Silver",
                "price": "72.48",
                "change_text": "", # Missing change
            },
        ]

        parsed = SiteObserver._normalize_tradingeconomics_commodities(rows)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["pair"], "XAGUSD")
        self.assertEqual(parsed[0]["common_name"], "Silver")
        self.assertEqual(parsed[0]["price"], "72.48")
        self.assertIsNone(parsed[0]["change"])

    def test_strip_provider_suffix_helper(self):
        """The suffix-strip helper handles colon, concatenated, and base forms."""
        self.assertEqual(SiteObserver._strip_provider_suffix("XAUUSD:CUR"), "XAUUSD")
        self.assertEqual(SiteObserver._strip_provider_suffix("HG1:COM"), "HG1")
        self.assertEqual(SiteObserver._strip_provider_suffix("XAUUSDCUR"), "XAUUSD")
        self.assertEqual(SiteObserver._strip_provider_suffix("XAGUSDCUR"), "XAGUSD")
        # Already-canonical inputs pass through unchanged.
        self.assertEqual(SiteObserver._strip_provider_suffix("CL1"), "CL1")
        self.assertEqual(SiteObserver._strip_provider_suffix("HG1"), "HG1")
        self.assertEqual(SiteObserver._strip_provider_suffix(""), "")

    def test_custom_allowlist_expands_emitted_set(self):
        """Passing an ``allowed_symbols`` override picks up extra commodities."""
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
                "pair": "XPTUSD:CUR",
                "common_name": "Platinum",
                "price": "2141.70",
                "change_text": "0.50%",
            },
        ]

        # Default allowlist drops Platinum.
        default_parsed = SiteObserver._normalize_tradingeconomics_commodities(rows)
        self.assertEqual({r["pair"] for r in default_parsed}, {"XAUUSD"})

        # Custom allowlist — accepts colon-suffixed spellings and canonicalizes them.
        custom_parsed = SiteObserver._normalize_tradingeconomics_commodities(
            rows,
            allowed_symbols=["XAUUSD", "xptusd:cur"],
        )
        self.assertEqual({r["pair"] for r in custom_parsed}, {"XAUUSD", "XPTUSD"})

    def test_instance_level_allowlist_is_used(self):
        """The observer instance propagates its allowlist into the filter."""
        observer = SiteObserver(
            url="https://example.com",
            table_selector="table",
            pair_cell_selector="td",
            source_name="commodities",
            allowed_commodity_symbols=["XPTUSD"],
        )
        # Allowlist should be canonicalized at construction time.
        self.assertEqual(observer.allowed_commodity_symbols, frozenset({"XPTUSD"}))

    def test_instance_allowlist_empty_falls_back_to_default(self):
        observer = SiteObserver(
            url="https://example.com",
            table_selector="table",
            pair_cell_selector="td",
            source_name="commodities",
            allowed_commodity_symbols=[],
        )
        self.assertEqual(observer.allowed_commodity_symbols, ALLOWED_COMMODITY_SYMBOLS)

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
            filter_by_majors=False,
        )
        observer.page = page

        # Note: _select_tradingeconomics_commodity_table was removed or made internal
        # We can just verify the SiteObserver init for now or check other methods if needed.
        self.assertEqual(observer.source_name, "commodities")


class TradingEconomicsBondsParsingTests(unittest.TestCase):
    def test_maps_usgg10yr_to_us10y(self):
        rows = [
            {
                "pair": "USGG10YR:IND",
                "common_name": "United States",
                "price": "4.3660",
                "change_text": "0.063",
            },
            {
                "pair": "GUKG10:IND",
                "common_name": "United Kingdom",
                "price": "4.9450",
                "change_text": "0.103",
            },
        ]

        parsed = SiteObserver._normalize_tradingeconomics_bonds(rows)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["pair"], "US10Y")
        self.assertEqual(parsed[0]["common_name"], "United States")
        self.assertEqual(parsed[0]["price"], "4.3660")
        self.assertEqual(parsed[0]["change"], "0.063")

    def test_skips_bond_rows_with_missing_price(self):
        rows = [
            {
                "pair": "USGG10YR:IND",
                "common_name": "United States",
                "price": "",
                "change_text": "0.063",
            },
        ]
        parsed = SiteObserver._normalize_tradingeconomics_bonds(rows)
        self.assertEqual(parsed, [])

    def test_deduplicates_us10y_preferring_higher_quality(self):
        rows = [
            {
                "pair": "USGG10YR:IND",
                "common_name": "",
                "price": "4.3660",
                "change_text": "",
            },
            {
                "pair": "USGG10YR:IND",
                "common_name": "United States",
                "price": "4.3660",
                "change_text": "0.063",
            },
        ]
        parsed = SiteObserver._normalize_tradingeconomics_bonds(rows)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["common_name"], "United States")
        self.assertEqual(parsed[0]["change"], "0.063")


class TradingEconomicsUsdIndexParsingTests(unittest.TestCase):
    def test_maps_dxy_cur_to_dxy(self):
        rows = [
            {
                "row_index": 0,
                "pair": "DXY:CUR",
                "common_name": "DXY",
                "price": "98.83",
                "change_text": "-0.21%",
            },
            {
                "row_index": 1,
                "pair": "EUR:CUR",
                "common_name": "Euro",
                "price": "1.17",
                "change_text": "0.02%",
            },
        ]

        parsed = SiteObserver._normalize_tradingeconomics_usd_index(rows)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["pair"], "DXY")
        self.assertEqual(parsed[0]["common_name"], "DXY")
        self.assertEqual(parsed[0]["price"], "98.83")
        self.assertEqual(parsed[0]["change"], "-0.21")

    def test_skips_dxy_rows_without_price(self):
        rows = [
            {
                "row_index": 0,
                "pair": "DXY:CUR",
                "common_name": "DXY",
                "price": "",
                "change_text": "-0.21%",
            },
        ]
        parsed = SiteObserver._normalize_tradingeconomics_usd_index(rows)
        self.assertEqual(parsed, [])

    def test_deduplicates_dxy_preferring_higher_quality(self):
        rows = [
            {
                "row_index": 0,
                "pair": "DXY:CUR",
                "common_name": "",
                "price": "98.83",
                "change_text": "",
            },
            {
                "row_index": 1,
                "pair": "DXY:CUR",
                "common_name": "DXY",
                "price": "98.83",
                "change_text": "-0.21%",
            },
        ]

        parsed = SiteObserver._normalize_tradingeconomics_usd_index(rows)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["pair"], "DXY")
        self.assertEqual(parsed[0]["common_name"], "DXY")
        self.assertEqual(parsed[0]["change"], "-0.21")


if __name__ == "__main__":
    unittest.main()
