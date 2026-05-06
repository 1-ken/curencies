"""Async tests for US10Y alert compatibility."""

import pytest

from app.services.alert_service import AlertManager


@pytest.mark.asyncio
async def test_price_alert_triggers_for_us10y_symbol(tmp_path):
    alert_file = tmp_path / "alerts.json"
    manager = AlertManager(str(alert_file))

    alert = await manager.create_alert(
        pair="US10Y",
        target_price=4.40,
        condition="below",
        channel="email",
        email="test@example.com",
    )

    pairs_data = [
        {"pair": "US10Y", "price": "4.3660"},
        {"pair": "EURUSD", "price": "1.1700"},
    ]

    triggered = await manager.check_alerts(pairs_data)

    assert len(triggered) == 1
    assert triggered[0]["alert"]["id"] == alert.id
    assert triggered[0]["current_price"] == 4.366
