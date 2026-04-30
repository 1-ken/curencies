"""Single source of truth for pair-name canonicalization.

The raw commodities feed (TradingEconomics) emits provider-tagged symbols like
``XAUUSD:CUR``, ``HG1:COM``, ``XAGUSD:CUR``. Earlier versions of the alert
creation UI also stored concatenated forms without the colon (``XAUUSDCUR``).
Forex pairs arrive with or without a slash (``EUR/USD`` / ``EURUSD``).

Every pair that moves through the system (observer snapshot, Redis payload,
PostgreSQL row, alert config, candle lookup) should agree on the same
canonical spelling. This module is the one place where that rule lives.

Rules:

- Strip whitespace, uppercase.
- Remove any ``:<SUFFIX>`` where ``SUFFIX`` is in :data:`PROVIDER_SUFFIXES`.
- If the result ends with a provider suffix and the base is a 6-letter
  forex-style symbol (``XAUUSDCUR`` -> base ``XAUUSD``), strip the trailing
  suffix too. Short non-forex bases like ``CL1`` / ``HG1`` are left alone
  because stripping could corrupt them.
- For 6-letter currency pairs, collapse the slash form (``EUR/USD`` ->
  ``EURUSD``).
- Any other input is returned uppercased and otherwise unchanged.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

# Provider tags the commodities feed and legacy UI entries can carry.
PROVIDER_SUFFIXES: tuple[str, ...] = ("CUR", "COM", "IND")

# The curated subset of commodities the observer actually emits. Consumers
# should import this constant rather than hardcoding their own allowlist.
# Can be overridden by the caller (e.g. loaded from config.json) via
# ``SiteObserver(allowed_commodity_symbols=...)``.
DEFAULT_ALLOWED_COMMODITY_SYMBOLS: frozenset[str] = frozenset(
    {"CL1", "XAUUSD", "XAGUSD", "HG1"}
)


def canonical_pair(value: Optional[str]) -> str:
    """Return the canonical spelling of ``value``.

    Empty / ``None`` input returns the empty string so callers can safely use
    this as a dict key.
    """
    if not value:
        return ""

    normalized = str(value).strip().upper()
    if not normalized:
        return ""

    if ":" in normalized:
        normalized = normalized.split(":", 1)[0]
    else:
        for suffix in PROVIDER_SUFFIXES:
            if len(normalized) > len(suffix) and normalized.endswith(suffix):
                base = normalized[: -len(suffix)]
                # Only strip when the base is a 6-letter forex-style symbol.
                # Leaves CL1 / HG1 / etc. untouched.
                if len(base) == 6 and base.isalpha():
                    normalized = base
                    break

    compact = normalized.replace("/", "")
    if len(compact) == 6 and compact.isalpha():
        return compact
    return normalized


def pair_variants(value: Optional[str]) -> List[str]:
    """Return every equivalent spelling of ``value`` for a DB lookup.

    Includes the canonical symbol, the slash form for 6-letter forex pairs,
    and the provider-tagged forms (``XAUUSD``, ``XAUUSD:CUR``, ``XAUUSD:COM``,
    ``XAUUSD:IND``) so queries bridge old and new row spellings during the
    historical-data transition window.
    """
    canonical = canonical_pair(value)
    if not canonical:
        return []

    variants: List[str] = [canonical]
    compact = canonical.replace("/", "")

    if len(compact) == 6 and compact.isalpha():
        slash = f"{compact[:3]}/{compact[3:]}"
        if slash not in variants:
            variants.append(slash)
        if compact not in variants:
            variants.append(compact)

    # Legacy provider-tagged spellings for commodities / indices.
    if ":" not in canonical:
        for suffix in PROVIDER_SUFFIXES:
            tagged = f"{canonical}:{suffix}"
            if tagged not in variants:
                variants.append(tagged)

    return variants


def is_canonical(value: Optional[str]) -> bool:
    """Return ``True`` if ``value`` is already in canonical form."""
    return bool(value) and canonical_pair(value) == value


def normalize_allowlist(symbols: Optional[Iterable[str]]) -> frozenset[str]:
    """Canonicalize an iterable of allowlist symbols.

    Callers loading the allowlist from configuration should run it through
    this so the comparison inside :mod:`observer_service` always matches the
    canonical output of :func:`canonical_pair`.
    """
    if symbols is None:
        return DEFAULT_ALLOWED_COMMODITY_SYMBOLS
    canonicals = {canonical_pair(s) for s in symbols if s}
    canonicals.discard("")
    if not canonicals:
        return DEFAULT_ALLOWED_COMMODITY_SYMBOLS
    return frozenset(canonicals)
