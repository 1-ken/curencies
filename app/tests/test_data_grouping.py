"""Tests for API payload grouping behavior."""

from app.api.v1.endpoints import data as data_endpoints


class _EmptyAlertManager:
    def get_active_alerts(self):
        return []

    def get_all_alerts(self):
        return []


def test_attach_alerts_merges_bonds_under_commodities():
    data_endpoints.set_alert_manager(_EmptyAlertManager())

    payload = {
        "sources": {
            "currencies": [
                {"pair": "EUR/USD", "price": "1.1700", "change": "0.01"},
            ],
            "commodities": [
                {"pair": "XAUUSD", "price": "4570.82", "change": "24.8"},
            ],
            "bonds": [
                {
                    "pair": "US10Y",
                    "common_name": "United States",
                    "price": "4.3660",
                    "change": "0.063",
                },
            ],
        },
        "ts": "2026-05-06T14:00:00+00:00",
    }

    clean = data_endpoints._attach_alerts(payload)
    assert "pairs" in clean
    assert "currencies" in clean["pairs"]
    assert "commodities" in clean["pairs"]
    assert len(clean["pairs"]["currencies"]) == 1
    assert len(clean["pairs"]["commodities"]) == 2
    assert any(row.get("pair") == "US10Y" for row in clean["pairs"]["commodities"])


def test_attach_alerts_merges_usd_index_under_currencies():
    data_endpoints.set_alert_manager(_EmptyAlertManager())

    payload = {
        "sources": {
            "currencies": [
                {"pair": "EUR/USD", "price": "1.1700", "change": "0.01"},
            ],
            "usd-index": [
                {"pair": "DXY", "common_name": "DXY", "price": "98.83", "change": "-0.21"},
            ],
            "commodities": [],
        },
        "ts": "2026-05-06T14:00:00+00:00",
    }

    clean = data_endpoints._attach_alerts(payload)
    assert "pairs" in clean
    assert len(clean["pairs"]["currencies"]) == 2
    assert any(row.get("pair") == "DXY" for row in clean["pairs"]["currencies"])
