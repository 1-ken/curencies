"""Tests for candle-close alert functionality."""
import pytest
from datetime import datetime, timezone, timedelta
from app.services.alert_service import AlertManager, Alert


class TestCandleAlertCreation:
    """Test creating candle-close alerts."""
    
    def test_create_candle_alert_above(self, tmp_path):
        """Test creating a candle-close alert with 'above' direction."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval="15m",
            direction="above",
            threshold=1.0850,
            email="test@example.com",
            channel="email",
        )
        
        assert alert.alert_type == "candle_close"
        assert alert.pair == "EURUSD"
        assert alert.interval == "15m"
        assert alert.direction == "above"
        assert alert.threshold == 1.0850
        assert alert.status == "active"
        assert alert.email == "test@example.com"
        assert alert.channel == "email"
    
    def test_create_candle_alert_below(self, tmp_path):
        """Test creating a candle-close alert with 'below' direction."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_candle_alert(
            pair="GBPUSD",
            interval="5m",
            direction="below",
            threshold=1.2500,
            phone="+1234567890",
            channel="sms",
        )
        
        assert alert.alert_type == "candle_close"
        assert alert.pair == "GBPUSD"
        assert alert.interval == "5m"
        assert alert.direction == "below"
        assert alert.threshold == 1.2500
        assert alert.phone == "+1234567890"
        assert alert.channel == "sms"

    def test_create_candle_alert_all_intervals(self, tmp_path):
        """Test creating candle alerts for all supported intervals."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
        
        for interval in intervals:
            alert = manager.create_candle_alert(
                pair="EURUSD",
                interval=interval,
                direction="above",
                threshold=1.0850,
                email="test@example.com",
                channel="email",
            )
            assert alert.interval == interval
            assert alert.alert_type == "candle_close"

    def test_create_candle_alert_normalizes_interval(self, tmp_path):
        """Test candle interval normalization (case/whitespace)."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval=" 4H ",
            direction="above",
            threshold=1.0850,
            email="test@example.com",
            channel="email",
        )

        assert alert.interval == "4h"

    def test_candle_alert_has_required_fields(self, tmp_path):
        """Test that candle alert has all required fields."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval="15m",
            direction="above",
            threshold=1.0850,
            email="test@example.com",
            channel="email",
        )
        
        # Check required fields
        assert alert.id is not None
        assert alert.pair == "EURUSD"
        assert alert.alert_type == "candle_close"
        assert alert.status == "active"
        assert alert.interval == "15m"
        assert alert.direction == "above"
        assert alert.threshold == 1.0850
        assert alert.created_at is not None
        assert alert.channel == "email"
        assert alert.email == "test@example.com"


class TestCandleAlertEvaluation:
    """Test candle-close alert evaluation logic."""
    
    def test_check_candle_alerts_above_triggers(self, tmp_path):
        """Test that candle alert triggers when close >= threshold (above)."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval="15m",
            direction="above",
            threshold=1.0850,
            email="test@example.com",
            channel="email",
        )
        
        # Create OHLC data with close above threshold
        candle_data = [
            {
                "pair": "EURUSD",
                "interval": "15m",
                "timestamp": datetime.now(timezone.utc),
                "open": 1.0820,
                "high": 1.0860,
                "low": 1.0815,
                "close": 1.0855,  # Above threshold
                "volume": 100,
            }
        ]
        
        triggered = manager.check_candle_alerts(candle_data)
        
        assert len(triggered) == 1
        assert triggered[0]["alert"]["id"] == alert.id
        assert triggered[0]["current_price"] == 1.0855
        assert triggered[0]["close_price"] == 1.0855
        assert triggered[0]["candle"]["expected_open"] is not None
        assert triggered[0]["candle"]["expected_close"] is not None
    
    def test_check_candle_alerts_below_triggers(self, tmp_path):
        """Test that candle alert triggers when close <= threshold (below)."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_candle_alert(
            pair="GBPUSD",
            interval="5m",
            direction="below",
            threshold=1.2500,
            email="test@example.com",
            channel="email",
        )
        
        # Create OHLC data with close below threshold
        candle_data = [
            {
                "pair": "GBPUSD",
                "interval": "5m",
                "timestamp": datetime.now(timezone.utc),
                "open": 1.2510,
                "high": 1.2520,
                "low": 1.2495,
                "close": 1.2490,  # Below threshold
                "volume": 150,
            }
        ]
        
        triggered = manager.check_candle_alerts(candle_data)
        
        assert len(triggered) == 1
        assert triggered[0]["alert"]["id"] == alert.id
        assert triggered[0]["current_price"] == 1.2490
    
    def test_check_candle_alerts_does_not_trigger_when_condition_not_met(self, tmp_path):
        """Test that candle alert does not trigger when condition is not met."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval="15m",
            direction="above",
            threshold=1.0850,
            email="test@example.com",
            channel="email",
        )
        
        # Create OHLC data with close below threshold
        candle_data = [
            {
                "pair": "EURUSD",
                "interval": "15m",
                "timestamp": datetime.now(timezone.utc),
                "open": 1.0820,
                "high": 1.0840,
                "low": 1.0815,
                "close": 1.0840,  # Below threshold
                "volume": 100,
            }
        ]
        
        triggered = manager.check_candle_alerts(candle_data)
        
        assert len(triggered) == 0

    def test_check_candle_alerts_accepts_z_timestamp_string(self, tmp_path):
        """Test candle timestamp parsing for ISO strings ending in 'Z'."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        alert = manager.create_candle_alert(
            pair="XAUUSD",
            interval="15m",
            direction="above",
            threshold=3000.0,
            email="test@example.com",
            channel="email",
        )

        candle_ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        candle_data = [
            {
                "pair": "XAUUSD:CUR",
                "interval": "15m",
                "timestamp": candle_ts,
                "open": 2999.0,
                "high": 3011.0,
                "low": 2998.0,
                "close": 3005.0,
                "volume": 100,
            }
        ]

        triggered = manager.check_candle_alerts(candle_data)

        assert len(triggered) == 1
        assert triggered[0]["alert"]["id"] == alert.id
        assert triggered[0]["close_price"] == 3005.0
    
    def test_check_candle_alerts_skips_if_candle_already_evaluated(self, tmp_path):
        """Test that candle alert doesn't trigger twice for same candle."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval="15m",
            direction="above",
            threshold=1.0850,
            email="test@example.com",
            channel="email",
        )
        
        candle_time = datetime.now(timezone.utc)
        candle_data = [
            {
                "pair": "EURUSD",
                "interval": "15m",
                "timestamp": candle_time,
                "open": 1.0820,
                "high": 1.0860,
                "low": 1.0815,
                "close": 1.0855,  # Above threshold
                "volume": 100,
            }
        ]
        
        # First check should trigger
        triggered1 = manager.check_candle_alerts(candle_data)
        assert len(triggered1) == 1
        
        # Second check with same candle should not trigger (already evaluated)
        triggered2 = manager.check_candle_alerts(candle_data)
        assert len(triggered2) == 0

    def test_candle_alert_does_not_use_pre_creation_closed_candle(self, tmp_path):
        """A newly-created alert must ignore candles that closed before creation time."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval="1h",
            direction="below",
            threshold=1.1627,
            email="test@example.com",
            channel="email",
        )

        created_at = datetime.fromisoformat(alert.created_at)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # This candle closes 1 second BEFORE alert creation.
        stale_candle_start = created_at - timedelta(hours=1, seconds=1)
        stale_candle_data = [
            {
                "pair": "EURUSD",
                "interval": "1h",
                "timestamp": stale_candle_start,
                "open": 1.1700,
                "high": 1.1710,
                "low": 1.1600,
                "close": 1.1600,
                "volume": 100,
            }
        ]

        triggered = manager.check_candle_alerts(stale_candle_data)
        assert len(triggered) == 0

    def test_candle_alert_strict_close_boundary_excludes_equal_timestamp(self, tmp_path):
        """If candle close time equals creation time, it should NOT be eligible."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval="1h",
            direction="below",
            threshold=1.1627,
            email="test@example.com",
            channel="email",
        )

        created_at = datetime.fromisoformat(alert.created_at)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # Candle close time == created_at (start + 1h == created_at).
        boundary_candle_start = created_at - timedelta(hours=1)
        boundary_candle_data = [
            {
                "pair": "EURUSD",
                "interval": "1h",
                "timestamp": boundary_candle_start,
                "open": 1.1700,
                "high": 1.1710,
                "low": 1.1600,
                "close": 1.1600,
                "volume": 100,
            }
        ]

        triggered = manager.check_candle_alerts(boundary_candle_data)
        assert len(triggered) == 0

    def test_candle_alert_triggers_for_first_post_creation_close(self, tmp_path):
        """A candle that closes after creation time should be eligible to trigger."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval="1h",
            direction="below",
            threshold=1.1627,
            email="test@example.com",
            channel="email",
        )

        created_at = datetime.fromisoformat(alert.created_at)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # Candle close time is 1 second AFTER creation.
        eligible_candle_start = created_at - timedelta(hours=1) + timedelta(seconds=1)
        eligible_candle_data = [
            {
                "pair": "EURUSD",
                "interval": "1h",
                "timestamp": eligible_candle_start,
                "open": 1.1700,
                "high": 1.1710,
                "low": 1.1600,
                "close": 1.1600,
                "volume": 100,
            }
        ]

        triggered = manager.check_candle_alerts(eligible_candle_data)
        assert len(triggered) == 1
        assert triggered[0]["alert"]["id"] == alert.id

    def test_candle_alert_at_exact_threshold(self, tmp_path):
        """Test that alert triggers when close equals threshold exactly."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        # Above direction
        alert_above = manager.create_candle_alert(
            pair="EURUSD",
            interval="15m",
            direction="above",
            threshold=1.0850,
            email="test@example.com",
            channel="email",
        )
        
        candle_data = [
            {
                "pair": "EURUSD",
                "interval": "15m",
                "timestamp": datetime.now(timezone.utc),
                "open": 1.0820,
                "high": 1.0860,
                "low": 1.0815,
                "close": 1.0850,  # Exactly at threshold
                "volume": 100,
            }
        ]
        
        triggered = manager.check_candle_alerts(candle_data)
        assert len(triggered) == 1  # Should trigger (close >= threshold)

    def test_multiple_candle_alerts_simultaneous(self, tmp_path):
        """Test multiple candle alerts evaluated at same time."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert1 = manager.create_candle_alert(
            pair="EURUSD",
            interval="15m",
            direction="above",
            threshold=1.0850,
            email="test@example.com",
            channel="email",
        )
        
        alert2 = manager.create_candle_alert(
            pair="GBPUSD",
            interval="5m",
            direction="below",
            threshold=1.2500,
            email="test@example.com",
            channel="email",
        )
        
        candle_data = [
            {
                "pair": "EURUSD",
                "interval": "15m",
                "timestamp": datetime.now(timezone.utc),
                "close": 1.0855,
            },
            {
                "pair": "GBPUSD",
                "interval": "5m",
                "timestamp": datetime.now(timezone.utc),
                "close": 1.2490,
            }
        ]
        
        triggered = manager.check_candle_alerts(candle_data)
        assert len(triggered) == 2


class TestCandleAlertBackwardCompatibility:
    """Test backward compatibility with legacy price alerts."""
    
    def test_create_legacy_price_alert(self, tmp_path):
        """Test that legacy price alerts still work."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_alert(
            pair="EURUSD",
            target_price=1.0850,
            condition="above",
            email="test@example.com",
            channel="email",
        )
        
        assert alert.alert_type == "price"
        assert alert.target_price == 1.0850
        assert alert.condition == "above"
    
    def test_load_legacy_alerts_without_alert_type(self, tmp_path):
        """Test that alerts without alert_type field default to 'price'."""
        import json
        
        alert_file = tmp_path / "alerts.json"
        
        # Write legacy alert data (without alert_type field)
        legacy_data = {
            "alert-123": {
                "id": "alert-123",
                "pair": "EURUSD",
                "target_price": 1.0850,
                "condition": "above",
                "status": "active",
                "created_at": "2024-01-15T10:30:00",
                "email": "test@example.com",
                "channel": "email",
                "phone": "",
                "custom_message": "",
                "triggered_at": None,
                "last_checked_price": None,
                # Note: no alert_type field
            }
        }
        
        with open(alert_file, "w") as f:
            json.dump(legacy_data, f)
        
        # Load with AlertManager
        manager = AlertManager(str(alert_file))
        
        assert len(manager.alerts) == 1
        alert = manager.alerts["alert-123"]
        assert alert.alert_type == "price"  # Should default to "price"

    def test_price_alert_evaluation_still_works(self, tmp_path):
        """Test that price alerts are still evaluated correctly."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_alert(
            pair="EURUSD",
            target_price=1.0850,
            condition="above",
            email="test@example.com",
            channel="email",
        )
        
        pairs_data = [
            {"pair": "EURUSD", "price": "1.0860"},
            {"pair": "GBPUSD", "price": "1.2500"}
        ]
        
        triggered = manager.check_alerts(pairs_data)
        assert len(triggered) == 1
        assert triggered[0]["alert"]["id"] == alert.id


class TestCandleAlertNormalization:
    """Test pair name normalization in candle alerts."""
    
    def test_pair_normalization_in_candle_alerts(self, tmp_path):
        """Test that pair names are normalized consistently."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_candle_alert(
            pair="EUR/USD",  # With slash
            interval="15m",
            direction="above",
            threshold=1.0850,
            email="test@example.com",
            channel="email",
        )
        
        candle_data = [
            {
                "pair": "EURUSD",  # Without slash
                "interval": "15m",
                "timestamp": datetime.now(timezone.utc),
                "open": 1.0820,
                "high": 1.0860,
                "low": 1.0815,
                "close": 1.0855,
                "volume": 100,
            }
        ]
        
        triggered = manager.check_candle_alerts(candle_data)
        
        # Should match despite different pair formats
        assert len(triggered) == 1

    def test_normalize_pair_strips_commodity_suffixes(self, tmp_path):
        """Commodity suffixes like :CUR/:COM should normalize to base symbol."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        assert manager._normalize_pair("xauusd:cur") == "XAUUSD"
        assert manager._normalize_pair("CL1:COM") == "CL1"

    def test_normalize_pair_strips_legacy_concatenated_suffixes(self, tmp_path):
        """Legacy alerts stored concatenated names like XAUUSDCUR (no colon);
        these must normalize to the same canonical base symbol as ``XAUUSD:CUR``.
        """
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        assert manager._normalize_pair("XAUUSDCUR") == "XAUUSD"
        assert manager._normalize_pair("XAGUSDCUR") == "XAGUSD"
        assert manager._normalize_pair("xagusdcur") == "XAGUSD"
        # Short non-forex bases like CL1/HG1 are NOT stripped.
        assert manager._normalize_pair("CL1") == "CL1"
        assert manager._normalize_pair("HG1") == "HG1"

    def test_normalize_pair_keeps_forex_compatibility(self, tmp_path):
        """Forex symbols should still normalize slash/no-slash variants."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        assert manager._normalize_pair("eur/usd") == "EURUSD"
        assert manager._normalize_pair("EURUSD") == "EURUSD"

    def test_price_alert_matches_legacy_concatenated_commodity(self, tmp_path):
        """An alert stored as ``XAGUSDCUR`` must trigger against a normalized
        snapshot emitting ``XAGUSD``.
        """
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        alert = manager.create_alert(
            pair="XAGUSDCUR",
            target_price=75.0,
            condition="below",
            channel="sms",
            phone="+1234567890",
        )

        pairs_data = [
            {"pair": "XAGUSD", "price": "72.603"},
            {"pair": "XAUUSD", "price": "4570.82"},
        ]

        triggered = manager.check_alerts(pairs_data)

        assert len(triggered) == 1
        assert triggered[0]["alert"]["id"] == alert.id
        assert triggered[0]["current_price"] == 72.603

    def test_candle_alert_matches_legacy_concatenated_commodity(self, tmp_path):
        """Candle-close alerts stored as ``XAUUSDCUR`` must trigger against
        candle data emitted with the canonical ``XAUUSD`` symbol.
        """
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        alert = manager.create_candle_alert(
            pair="XAUUSDCUR",
            interval="1m",
            direction="below",
            threshold=4700.0,
            channel="sms",
            phone="+1234567890",
        )

        created_at = datetime.fromisoformat(alert.created_at)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        # Use a candle that closed strictly after alert creation.
        candle_start = created_at - timedelta(minutes=1) + timedelta(seconds=1)

        candle_data = [
            {
                "pair": "XAUUSD",
                "interval": "1m",
                "timestamp": candle_start,
                "open": 4720.0,
                "high": 4725.0,
                "low": 4680.0,
                "close": 4690.0,
                "volume": 60,
            }
        ]

        triggered = manager.check_candle_alerts(candle_data)

        assert len(triggered) == 1
        assert triggered[0]["alert"]["id"] == alert.id
        assert triggered[0]["close_price"] == 4690.0

    def test_price_alert_matches_snapshot_symbol_with_suffix(self, tmp_path):
        """Price alerts should match snapshot pairs that carry provider suffixes."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        alert = manager.create_alert(
            pair="xauusd",
            target_price=1.0,
            condition="above",
            email="test@example.com",
            channel="email",
        )

        pairs_data = [
            {"pair": "XAUUSD:CUR", "price": "4000.0"},
            {"pair": "CL1:COM", "price": "79.5"},
        ]

        triggered = manager.check_alerts(pairs_data)

        assert len(triggered) == 1
        assert triggered[0]["alert"]["id"] == alert.id
        assert triggered[0]["current_price"] == 4000.0


class TestAlertCanonicalization:
    """Alert creation and load should produce canonical pair spellings."""

    def test_create_alert_canonicalizes_pair_on_write(self, tmp_path):
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        alert = manager.create_alert(
            pair="EUR/USD",
            target_price=1.10,
            condition="above",
            email="test@example.com",
            channel="email",
        )
        assert alert.pair == "EURUSD"

        # Also for commodity legacy spellings.
        commodity_alert = manager.create_alert(
            pair="XAUUSDCUR",
            target_price=3000.0,
            condition="above",
            channel="sms",
            phone="+1234567890",
        )
        assert commodity_alert.pair == "XAUUSD"

    def test_create_candle_alert_canonicalizes_pair_on_write(self, tmp_path):
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))

        alert = manager.create_candle_alert(
            pair="xauusd:cur",
            interval="15m",
            direction="above",
            threshold=3000.0,
            channel="sms",
            phone="+1234567890",
        )
        assert alert.pair == "XAUUSD"

    def test_load_alerts_migrates_noncanonical_pairs(self, tmp_path):
        """Loading an ``alerts.json`` with legacy spellings migrates them in-place."""
        import json

        alert_file = tmp_path / "alerts.json"
        legacy_data = {
            "a1": {
                "id": "a1",
                "pair": "xauusd",                # lowercase forex-style metal
                "status": "active",
                "created_at": "2026-01-01T00:00:00+00:00",
                "alert_type": "price",
                "channel": "sms",
                "phone": "+1",
                "target_price": 3000.0,
                "condition": "above",
            },
            "a2": {
                "id": "a2",
                "pair": "XAGUSDCUR",             # legacy concatenated form
                "status": "active",
                "created_at": "2026-01-01T00:00:00+00:00",
                "alert_type": "candle_close",
                "channel": "sms",
                "phone": "+1",
                "interval": "15m",
                "direction": "below",
                "threshold": 75.0,
            },
            "a3": {
                "id": "a3",
                "pair": "EUR/USD",               # slash form
                "status": "triggered",
                "created_at": "2026-01-01T00:00:00+00:00",
                "alert_type": "price",
                "channel": "email",
                "email": "test@example.com",
                "target_price": 1.10,
                "condition": "above",
            },
            "a4": {
                "id": "a4",
                "pair": "XAUUSD",                # already canonical - must not move
                "status": "active",
                "created_at": "2026-01-01T00:00:00+00:00",
                "alert_type": "price",
                "channel": "sms",
                "phone": "+1",
                "target_price": 3000.0,
                "condition": "above",
            },
        }
        alert_file.write_text(json.dumps(legacy_data))

        manager = AlertManager(str(alert_file))

        assert manager.alerts["a1"].pair == "XAUUSD"
        assert manager.alerts["a2"].pair == "XAGUSD"
        assert manager.alerts["a3"].pair == "EURUSD"
        assert manager.alerts["a4"].pair == "XAUUSD"

        # Persisted state should reflect the migration.
        persisted = json.loads(alert_file.read_text())
        assert persisted["a1"]["pair"] == "XAUUSD"
        assert persisted["a2"]["pair"] == "XAGUSD"
        assert persisted["a3"]["pair"] == "EURUSD"
        assert persisted["a4"]["pair"] == "XAUUSD"

    def test_load_alerts_skips_save_when_nothing_to_migrate(self, tmp_path):
        """No unnecessary writes when alerts are already canonical."""
        import json

        alert_file = tmp_path / "alerts.json"
        canonical_data = {
            "a1": {
                "id": "a1",
                "pair": "XAUUSD",
                "status": "active",
                "created_at": "2026-01-01T00:00:00+00:00",
                "alert_type": "price",
                "channel": "sms",
                "phone": "+1",
                "target_price": 3000.0,
                "condition": "above",
            }
        }
        alert_file.write_text(json.dumps(canonical_data))
        mtime_before = alert_file.stat().st_mtime_ns

        AlertManager(str(alert_file))

        mtime_after = alert_file.stat().st_mtime_ns
        # File must not be rewritten when nothing needs migrating.
        assert mtime_after == mtime_before


class TestPersistenceAndRecovery:
    """Test alert persistence and recovery."""
    
    def test_candle_alert_persistence(self, tmp_path):
        """Test that candle alerts are persisted to file."""
        alert_file = tmp_path / "alerts.json"
        
        # Create alert
        manager1 = AlertManager(str(alert_file))
        alert1 = manager1.create_candle_alert(
            pair="EURUSD",
            interval="15m",
            direction="above",
            threshold=1.0850,
            email="test@example.com",
            channel="email",
        )
        
        # Load in new manager
        manager2 = AlertManager(str(alert_file))
        loaded_alert = manager2.get_alert(alert1.id)
        
        assert loaded_alert is not None
        assert loaded_alert.alert_type == "candle_close"
        assert loaded_alert.interval == "15m"
        assert loaded_alert.threshold == 1.0850

    def test_alert_triggered_state_persisted(self, tmp_path):
        """Test that triggered alert state is persisted."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval="15m",
            direction="above",
            threshold=1.0850,
            email="test@example.com",
            channel="email",
        )
        
        candle_data = [
            {
                "pair": "EURUSD",
                "interval": "15m",
                "timestamp": datetime.now(timezone.utc),
                "close": 1.0855,
            }
        ]
        
        triggered = manager.check_candle_alerts(candle_data)
        assert len(triggered) == 1
        
        # Reload and verify state
        manager2 = AlertManager(str(alert_file))
        reloaded = manager2.get_alert(alert.id)
        assert reloaded.status == "triggered"
        assert reloaded.last_checked_price == 1.0855


class TestAlertChannels:
    """Test alert channels for candle alerts."""
    
    def test_candle_alert_email_channel(self, tmp_path):
        """Test candle alert with email channel."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval="15m",
            direction="above",
            threshold=1.0850,
            email="test@example.com",
            channel="email",
        )
        
        assert alert.channel == "email"
        assert alert.email == "test@example.com"
        assert alert.phone == ""

    def test_candle_alert_sms_channel(self, tmp_path):
        """Test candle alert with SMS channel."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval="15m",
            direction="above",
            threshold=1.0850,
            channel="sms",
            phone="+1234567890",
        )
        
        assert alert.channel == "sms"
        assert alert.phone == "+1234567890"

    def test_candle_alert_call_channel(self, tmp_path):
        """Test candle alert with call channel."""
        alert_file = tmp_path / "alerts.json"
        manager = AlertManager(str(alert_file))
        
        alert = manager.create_candle_alert(
            pair="EURUSD",
            interval="15m",
            direction="above",
            threshold=1.0850,
            channel="call",
            phone="+1234567890",
        )
        
        assert alert.channel == "call"
        assert alert.phone == "+1234567890"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
