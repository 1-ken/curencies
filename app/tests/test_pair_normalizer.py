"""Unit tests for :mod:`app.utils.pair_normalizer`."""

import unittest

from app.utils.pair_normalizer import (
    DEFAULT_ALLOWED_COMMODITY_SYMBOLS,
    PROVIDER_SUFFIXES,
    canonical_pair,
    is_canonical,
    normalize_allowlist,
    pair_variants,
)


class CanonicalPairTests(unittest.TestCase):
    def test_empty_inputs(self):
        self.assertEqual(canonical_pair(None), "")
        self.assertEqual(canonical_pair(""), "")
        self.assertEqual(canonical_pair("   "), "")

    def test_forex_pairs(self):
        self.assertEqual(canonical_pair("EUR/USD"), "EURUSD")
        self.assertEqual(canonical_pair("eur/usd"), "EURUSD")
        self.assertEqual(canonical_pair("EURUSD"), "EURUSD")
        self.assertEqual(canonical_pair("  eurusd  "), "EURUSD")

    def test_commodity_colon_suffix(self):
        self.assertEqual(canonical_pair("XAUUSD:CUR"), "XAUUSD")
        self.assertEqual(canonical_pair("xauusd:cur"), "XAUUSD")
        self.assertEqual(canonical_pair("HG1:COM"), "HG1")
        self.assertEqual(canonical_pair("CL1:COM"), "CL1")
        self.assertEqual(canonical_pair("CRYTR:IND"), "CRYTR")

    def test_commodity_concatenated_suffix(self):
        """Legacy form that earlier UIs persisted (``XAUUSDCUR``)."""
        self.assertEqual(canonical_pair("XAUUSDCUR"), "XAUUSD")
        self.assertEqual(canonical_pair("XAGUSDCUR"), "XAGUSD")
        self.assertEqual(canonical_pair("xagusdcur"), "XAGUSD")

    def test_does_not_chop_short_non_forex_bases(self):
        """Non-forex bases like CL1/HG1 should never be stripped."""
        self.assertEqual(canonical_pair("CL1"), "CL1")
        self.assertEqual(canonical_pair("HG1"), "HG1")
        # Looks like it could have a suffix but base is 3 chars, not 6.
        self.assertEqual(canonical_pair("CL1COM"), "CL1COM")

    def test_preserves_already_canonical(self):
        for symbol in ("XAUUSD", "XAGUSD", "CL1", "HG1", "EURUSD"):
            self.assertEqual(canonical_pair(symbol), symbol)

    def test_provider_suffix_constant_coverage(self):
        """All declared suffixes should round-trip through canonical_pair."""
        for suffix in PROVIDER_SUFFIXES:
            self.assertEqual(canonical_pair(f"XAUUSD:{suffix}"), "XAUUSD")


class IsCanonicalTests(unittest.TestCase):
    def test_canonical_inputs(self):
        self.assertTrue(is_canonical("XAUUSD"))
        self.assertTrue(is_canonical("EURUSD"))
        self.assertTrue(is_canonical("CL1"))

    def test_non_canonical_inputs(self):
        self.assertFalse(is_canonical("XAUUSD:CUR"))
        self.assertFalse(is_canonical("XAUUSDCUR"))
        self.assertFalse(is_canonical("EUR/USD"))
        self.assertFalse(is_canonical("xauusd"))
        self.assertFalse(is_canonical(""))


class PairVariantsTests(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(pair_variants(None), [])
        self.assertEqual(pair_variants(""), [])

    def test_forex_variants(self):
        variants = pair_variants("EURUSD")
        self.assertIn("EURUSD", variants)
        self.assertIn("EUR/USD", variants)

    def test_commodity_variants_include_legacy_spellings(self):
        variants = pair_variants("XAUUSD")
        # Canonical comes first for predictability.
        self.assertEqual(variants[0], "XAUUSD")
        # Legacy spellings are included so transitional historical rows
        # inserted between the migration and now are still found.
        self.assertIn("XAUUSD:CUR", variants)
        self.assertIn("XAUUSD:COM", variants)
        self.assertIn("XAUUSD:IND", variants)

    def test_commodity_input_with_suffix_is_canonicalized(self):
        variants = pair_variants("XAUUSD:CUR")
        self.assertIn("XAUUSD", variants)
        self.assertIn("XAUUSD:CUR", variants)

    def test_short_symbol_variants(self):
        variants = pair_variants("CL1")
        self.assertIn("CL1", variants)
        # CL1 has no forex equivalent, so no slash form.
        self.assertNotIn("CL/1", variants)
        # But suffixed legacy spellings are still enumerated.
        self.assertIn("CL1:COM", variants)


class NormalizeAllowlistTests(unittest.TestCase):
    def test_none_returns_default(self):
        self.assertEqual(normalize_allowlist(None), DEFAULT_ALLOWED_COMMODITY_SYMBOLS)

    def test_empty_returns_default(self):
        self.assertEqual(normalize_allowlist([]), DEFAULT_ALLOWED_COMMODITY_SYMBOLS)
        self.assertEqual(normalize_allowlist(["", None]), DEFAULT_ALLOWED_COMMODITY_SYMBOLS)

    def test_canonicalizes_entries(self):
        """Config entries spelled as ``XAUUSD:CUR`` still match canonical keys."""
        allowlist = normalize_allowlist(["XAUUSD:CUR", "hg1:com", "CL1"])
        self.assertEqual(allowlist, frozenset({"XAUUSD", "HG1", "CL1"}))

    def test_accepts_custom_set(self):
        allowlist = normalize_allowlist(["BTC", "ETH"])
        self.assertEqual(allowlist, frozenset({"BTC", "ETH"}))


if __name__ == "__main__":
    unittest.main()
