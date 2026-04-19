"""Tests for TradingEconomics commodity row normalization."""

import unittest

from app.services.observer_service import SiteObserver


class TradingEconomicsCommodityParsingTests(unittest.TestCase):
    def test_extracts_symbol_price_and_change(self):
        rows = [
            {
                "pair": "XAUUSD:CUR",
                "common_name": "Gold",
                "price": "4833.56",
                "change_text": "0.94%",
            },
            {
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

    def test_drops_incomplete_rows(self):
        rows = [
            {
                "pair": "",
                "common_name": "Invalid",
                "price": "10.0",
                "change_text": "1.00%",
            },
            {
                "pair": "XAGUSD:CUR",
                "common_name": "Silver",
                "price": "",
                "change_text": "2.99%",
            },
            {
                "pair": "XPTUSD:CUR",
                "common_name": "Platinum",
                "price": "2141.70",
                "change_text": "n/a",
            },
        ]

        parsed = SiteObserver._normalize_tradingeconomics_commodities(rows)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["pair"], "XPTUSD:CUR")
        self.assertEqual(parsed[0]["common_name"], "Platinum")
        self.assertEqual(parsed[0]["price"], "2141.70")
        self.assertIsNone(parsed[0]["change"])

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


if __name__ == "__main__":
    unittest.main()
