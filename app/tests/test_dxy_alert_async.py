"""Async tests for DXY alert compatibility."""

import pytest

from app.services.alert_service import AlertManager


@pytest.mark.asyncio
async def test_price_alert_triggers_for_dxy_symbol(tmp_path):
    alert_file = tmp_path / "alerts.json"
    manager = AlertManager(str(alert_file))

    alert = await manager.create_alert(
        pair="DXY",
        target_price=99.00,
        condition="below",
        channel="email",
        email="test@example.com",
    )

    pairs_data = [
        {"pair": "DXY", "price": "98.83"},
        {"pair": "EURUSD", "price": "1.1700"},
    ]

    triggered = await manager.check_alerts(pairs_data)

    assert len(triggered) == 1
    assert triggered[0]["alert"]["id"] == alert.id
    assert triggered[0]["current_price"] == 98.83
