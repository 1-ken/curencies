"""Test script for forex market hours utility."""
from datetime import datetime, timezone
from app.utils.forex_market_hours import (
    is_forex_market_open,
    get_time_until_market_opens,
    get_time_until_market_closes
)


def test_forex_market_hours():
    """Test various scenarios for forex market hours."""
    
    print("=" * 60)
    print("TESTING FOREX MARKET HOURS UTILITY")
    print("=" * 60)
    
    # Test scenarios with specific dates/times
    test_cases = [
        # (description, datetime, expected_open)
        ("Monday 10:00 UTC", datetime(2024, 2, 19, 10, 0, tzinfo=timezone.utc), True),
        ("Tuesday 15:30 UTC", datetime(2024, 2, 20, 15, 30, tzinfo=timezone.utc), True),
        ("Wednesday 23:00 UTC", datetime(2024, 2, 21, 23, 0, tzinfo=timezone.utc), True),
        ("Thursday 06:15 UTC", datetime(2024, 2, 22, 6, 15, tzinfo=timezone.utc), True),
        ("Friday 21:59 UTC", datetime(2024, 2, 23, 21, 59, tzinfo=timezone.utc), True),
        ("Friday 22:00 UTC (closing)", datetime(2024, 2, 23, 22, 0, tzinfo=timezone.utc), False),
        ("Friday 23:00 UTC", datetime(2024, 2, 23, 23, 0, tzinfo=timezone.utc), False),
        ("Saturday 10:00 UTC", datetime(2024, 2, 24, 10, 0, tzinfo=timezone.utc), False),
        ("Saturday 22:00 UTC", datetime(2024, 2, 24, 22, 0, tzinfo=timezone.utc), False),
        ("Sunday 10:00 UTC", datetime(2024, 2, 25, 10, 0, tzinfo=timezone.utc), False),
        ("Sunday 21:59 UTC", datetime(2024, 2, 25, 21, 59, tzinfo=timezone.utc), False),
        ("Sunday 22:00 UTC (opening)", datetime(2024, 2, 25, 22, 0, tzinfo=timezone.utc), True),
        ("Sunday 23:00 UTC", datetime(2024, 2, 25, 23, 0, tzinfo=timezone.utc), True),
    ]
    
    print("\n📊 Test Cases:")
    print("-" * 60)
    
    passed = 0
    failed = 0
    
    for description, test_time, expected in test_cases:
        result = is_forex_market_open(test_time)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        weekday = weekday_names[test_time.weekday()]
        
        print(f"{status} | {description:30s} ({weekday}) | "
              f"Expected: {'OPEN' if expected else 'CLOSED':6s} | "
              f"Got: {'OPEN' if result else 'CLOSED':6s}")
    
    print("-" * 60)
    print(f"\n📈 Results: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    
    # Test current time
    print("\n" + "=" * 60)
    print("CURRENT TIME CHECK")
    print("=" * 60)
    
    now = datetime.now(timezone.utc)
    is_open = is_forex_market_open()
    
    print(f"\n🕐 Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"📅 Day of week: {now.strftime('%A')}")
    
    if is_open:
        print("✅ Forex market is currently OPEN")
        time_until_close = get_time_until_market_closes()
        print(f"⏱️  Market closes in: {time_until_close}")
    else:
        print("🔒 Forex market is currently CLOSED")
        time_until_open = get_time_until_market_opens()
        print(f"⏱️  Market opens in: {time_until_open}")
    
    print("\n" + "=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = test_forex_market_hours()
    exit(0 if success else 1)
