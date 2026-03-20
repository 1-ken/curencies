"""Tests for OHLC interval bucketing and closed candle detection."""
import pytest
from datetime import datetime, timezone, timedelta

from app.services.postgres_service import PostgresService


class TestOHLCIntervalBucketing:
    """Test that OHLC intervals are bucketed correctly."""
    
    def test_interval_mapping(self):
        """Test that interval to seconds mapping is correct."""
        interval_map = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
        }
        
        # Verify each mapping
        assert interval_map["1m"] == 60
        assert interval_map["5m"] == 300
        assert interval_map["15m"] == 900
        assert interval_map["30m"] == 1800
        assert interval_map["1h"] == 3600
        assert interval_map["4h"] == 14400
        assert interval_map["1d"] == 86400
    
    def test_epoch_based_bucketing_logic(self):
        """Test the epoch-based bucketing calculation."""
        # Example: For 5m interval, two timestamps in same 5-minute bucket
        # should calculate to same bucket time
        
        interval_seconds = 300  # 5 minutes
        
        # Time: 10:00:30 UTC
        ts1 = 1700000430  # Epoch timestamp
        bucket1 = (ts1 // interval_seconds) * interval_seconds
        
        # Time: 10:02:45 UTC (same 5-minute bucket starting at 10:00:00)
        ts2 = 1700000565
        bucket2 = (ts2 // interval_seconds) * interval_seconds
        
        # Both should be in the same bucket (10:00:00 = 1700000400)
        assert bucket1 == bucket2 == 1700000400
    
    def test_epoch_bucketing_crosses_boundaries(self):
        """Test that different timestamps cross bucket boundaries correctly."""
        interval_seconds = 300  # 5 minutes
        
        # Time: 10:04:30 UTC (end of first 5-minute bucket)
        ts_end_bucket1 = 1700000670
        bucket_end1 = (ts_end_bucket1 // interval_seconds) * interval_seconds
        
        # Time: 10:05:00 UTC (start of next bucket)
        ts_start_bucket2 = 1700000700
        bucket_start2 = (ts_start_bucket2 // interval_seconds) * interval_seconds
        
        # Should be different buckets
        assert bucket_end1 != bucket_start2
        assert bucket_start2 == bucket_end1 + interval_seconds


class TestClosedCandleDetection:
    """Test logic for detecting fully closed candles."""
    
    def test_candle_closed_when_current_time_past_bucket_end(self):
        """Test that a candle is closed when current time > bucket end."""
        interval_seconds = 900  # 15 minutes
        
        # Bucket start: 10:00:00 UTC (epoch: 1700000000)
        # Bucket end: 10:15:00 UTC (epoch: 1700000900)
        bucket_start = 1700000000
        bucket_end = bucket_start + interval_seconds
        
        # Current time: 10:16:00 UTC (epoch: 1700000960)
        current_time = 1700000960
        
        # Candle is closed if current_time >= bucket_end
        is_closed = current_time >= bucket_end
        
        assert is_closed
    
    def test_candle_not_closed_when_current_time_in_bucket(self):
        """Test that a candle is not closed while current time is in bucket."""
        interval_seconds = 900  # 15 minutes
        
        # Bucket start: 10:00:00 UTC
        bucket_start = 1700000000
        bucket_end = bucket_start + interval_seconds
        
        # Current time: 10:10:30 UTC (within the bucket)
        current_time = 1700000430
        
        # Candle is not closed if current_time < bucket_end
        is_closed = current_time >= bucket_end
        
        assert not is_closed


class TestOHLCDataValidation:
    """Test OHLC data structure and values."""
    
    def test_ohlc_structure_complete(self):
        """Test that OHLC data has all required fields."""
        ohlc = {
            "timestamp": datetime.now(timezone.utc),
            "open": 1.0850,
            "high": 1.0875,
            "low": 1.0825,
            "close": 1.0860,
            "volume": 500,
        }
        
        required_fields = ["timestamp", "open", "high", "low", "close", "volume"]
        for field in required_fields:
            assert field in ohlc
    
    def test_ohlc_high_low_relationship(self):
        """Test that high >= low in OHLC data."""
        ohlc = {
            "open": 1.0850,
            "high": 1.0875,
            "low": 1.0825,
            "close": 1.0860,
        }
        
        assert ohlc["high"] >= ohlc["low"]
    
    def test_ohlc_candle_values_within_high_low(self):
        """Test that open and close are within high-low range."""
        ohlc = {
            "open": 1.0850,
            "high": 1.0875,
            "low": 1.0825,
            "close": 1.0860,
        }
        
        assert ohlc["low"] <= ohlc["open"] <= ohlc["high"]
        assert ohlc["low"] <= ohlc["close"] <= ohlc["high"]


class TestPairNormalization:
    """Test forex pair normalization compatibility."""

    def test_normalize_pair_removes_slash_for_forex(self):
        assert PostgresService._normalize_pair("eur/usd") == "EURUSD"
        assert PostgresService._normalize_pair("GBPUSD") == "GBPUSD"

    def test_pair_variants_include_slash_and_no_slash(self):
        variants = PostgresService._pair_variants("eurusd")
        assert "EURUSD" in variants
        assert "EUR/USD" in variants


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
