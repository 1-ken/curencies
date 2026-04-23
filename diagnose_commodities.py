#!/usr/bin/env python3
"""Diagnostic script to verify commodities alerts configuration and functionality."""
import json
import sys
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.services.alert_service import AlertManager
from app.services.postgres_service import PostgresService
from app.core.config import get_config


async def check_alerts_configuration():
    """Check if commodity alerts are properly configured."""
    print("\n" + "=" * 60)
    print("COMMODITY ALERTS CONFIGURATION CHECK")
    print("=" * 60)
    
    alert_manager = AlertManager()
    active_alerts = alert_manager.get_active_alerts()
    
    # Separate commodity and currency alerts
    commodity_alerts = [a for a in active_alerts if ":" in a.pair]
    currency_alerts = [a for a in active_alerts if ":" not in a.pair]
    
    print(f"\n✓ Total alerts: {len(active_alerts)}")
    print(f"  - Currency pairs: {len(currency_alerts)}")
    print(f"  - Commodity pairs: {len(commodity_alerts)}")
    
    if not commodity_alerts:
        print("\n⚠ WARNING: No commodity alerts configured!")
        print("  Create commodity alerts using:")
        print("  - Price alerts via POST /alerts with pair like 'XAUUSD:CUR'")
        print("  - Candle alerts via POST /alerts with interval like '15m'")
        return False
    
    print("\n📊 Commodity Alerts Details:")
    commodities_by_pair = {}
    for alert in commodity_alerts:
        pair = alert.pair
        if pair not in commodities_by_pair:
            commodities_by_pair[pair] = {"price": [], "candle": []}
        
        if alert.alert_type == "candle_close":
            commodities_by_pair[pair]["candle"].append({
                "interval": alert.interval,
                "direction": alert.direction,
                "threshold": alert.threshold,
                "status": alert.status,
            })
        else:
            commodities_by_pair[pair]["price"].append({
                "condition": alert.condition,
                "target_price": alert.target_price,
                "status": alert.status,
            })
    
    for pair in sorted(commodities_by_pair.keys()):
        print(f"\n  {pair}:")
        alerts = commodities_by_pair[pair]
        
        if alerts["price"]:
            print(f"    Price Alerts ({len(alerts['price'])}):")
            for p_alert in alerts["price"]:
                print(f"      - {p_alert['condition']} {p_alert['target_price']} [{p_alert['status']}]")
        
        if alerts["candle"]:
            print(f"    Candle Alerts ({len(alerts['candle'])}):")
            for c_alert in alerts["candle"]:
                print(f"      - {c_alert['interval']} {c_alert['direction']} {c_alert['threshold']} [{c_alert['status']}]")
    
    return True


async def check_observer_configuration():
    """Check if commodities observer is enabled."""
    print("\n" + "=" * 60)
    print("OBSERVER CONFIGURATION CHECK")
    print("=" * 60)
    
    config = get_config()
    commodities_source = next((s for s in config.sources if s.get("name") == "commodities"), None)
    
    if not commodities_source:
        print("\n❌ FAILED: Commodities observer not configured in config.json")
        return False
    
    enabled = commodities_source.get("enabled", True)
    if not enabled:
        print("\n❌ FAILED: Commodities observer is disabled in config.json")
        return False
    
    print("\n✓ Commodities observer is enabled")
    print(f"  URL: {commodities_source.get('url')}")
    print(f"  Filter by majors: {commodities_source.get('filterByMajors', False)}")
    
    return True


async def check_postgres_data():
    """Check if commodity data exists in PostgreSQL."""
    print("\n" + "=" * 60)
    print("DATABASE CHECK")
    print("=" * 60)
    
    config = get_config()
    
    try:
        postgres_service = PostgresService(config.postgres_dsn)
        await postgres_service.connect()
        
        # Check if historical_prices table has commodity data
        history = await postgres_service.query_history(
            pair="XAUUSD:CUR",
            start=None,
            end=None,
            limit=10,
            descending=True
        )
        
        if history:
            print(f"\n✓ Found {len(history)} recent prices for XAUUSD:CUR (Gold)")
            latest = history[0]
            print(f"  Latest: ${latest.price} at {latest.observed_at}")
        else:
            print("\n⚠ No data found for XAUUSD:CUR in PostgreSQL")
            print("  This might be expected if commodities haven't streamed yet")
        
        # Check all unique commodity pairs in database
        from sqlalchemy import text
        async with postgres_service._sessionmaker() as session:
            result = await session.execute(
                text("SELECT DISTINCT pair FROM historical_prices WHERE pair LIKE '%:%' LIMIT 10")
            )
            commodity_pairs = [row[0] for row in result]
        
        if commodity_pairs:
            print(f"\n✓ Found {len(commodity_pairs)} commodity pairs in database:")
            for pair in sorted(commodity_pairs):
                print(f"    - {pair}")
        else:
            print("\n⚠ No commodity pairs found in PostgreSQL")
            print("  Commodities observer may not be returning data")
        
        await postgres_service.close()
        return True
        
    except Exception as e:
        print(f"\n❌ PostgreSQL check failed: {e}")
        return False


async def check_pair_normalization():
    """Verify pair normalization works correctly."""
    print("\n" + "=" * 60)
    print("PAIR NORMALIZATION CHECK")
    print("=" * 60)
    
    test_cases = [
        ("EUR/USD", "EURUSD", "currency pair with slash"),
        ("EURUSD", "EURUSD", "currency pair without slash"),
        ("XAUUSD:CUR", "XAUUSD:CUR", "gold commodity"),
        ("HG1:COM", "HG1:COM", "copper commodity"),
        ("XAG/USD:CUR", "XAG/USD:CUR", "silver commodity"),
    ]
    
    print("\nTesting pair normalization:")
    all_passed = True
    
    for input_pair, expected, description in test_cases:
        normalized = AlertManager._normalize_pair(input_pair)
        passed = normalized == expected
        status = "✓" if passed else "❌"
        print(f"  {status} {description}")
        print(f"      Input: {input_pair} → {normalized}")
        if not passed:
            print(f"      Expected: {expected}")
            all_passed = False
    
    return all_passed


async def check_alert_matching():
    """Check if alerts would match commodity data."""
    print("\n" + "=" * 60)
    print("ALERT MATCHING CHECK")
    print("=" * 60)
    
    alert_manager = AlertManager()
    
    # Simulate commodity price data
    simulated_data = [
        {"pair": "XAUUSD:CUR", "price": "2451.50"},
        {"pair": "HG1:COM", "price": "5.45"},
    ]
    
    # Get active commodity alerts
    active_alerts = [a for a in alert_manager.get_active_alerts() if ":" in a.pair and a.alert_type == "price"]
    
    print(f"\nChecking {len(active_alerts)} commodity price alerts against simulated data...")
    
    # Test check_alerts logic
    triggered = alert_manager.check_alerts(simulated_data)
    
    if triggered:
        print(f"\n✓ Found {len(triggered)} alerts that would trigger:")
        for alert_data in triggered:
            alert = alert_data["alert"]
            print(f"    - {alert['pair']} {alert['condition']} {alert['target_price']}")
    else:
        print("\n✓ No simulated data triggered alerts (expected if conditions not met)")
    
    return True


async def main():
    """Run all diagnostics."""
    print("\n" + "╔" + "=" * 58 + "╗")
    print("║" + " COMMODITIES ALERTS DIAGNOSTIC REPORT ".center(58) + "║")
    print("║" + f" Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ".ljust(59) + "║")
    print("╚" + "=" * 58 + "╝")
    
    try:
        checks = [
            ("Alerts Configuration", check_alerts_configuration),
            ("Observer Configuration", check_observer_configuration),
            ("PostgreSQL Data", check_postgres_data),
            ("Pair Normalization", check_pair_normalization),
            ("Alert Matching", check_alert_matching),
        ]
        
        results = []
        for check_name, check_func in checks:
            try:
                result = await check_func()
                results.append((check_name, result))
            except Exception as e:
                print(f"\n❌ {check_name} check failed with exception: {e}")
                results.append((check_name, False))
        
        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for check_name, result in results:
            status = "✓ PASS" if result else "❌ FAIL"
            print(f"  {status}: {check_name}")
        
        print(f"\nOverall: {passed}/{total} checks passed")
        
        if passed == total:
            print("\n✅ All checks passed! Commodities alerts are properly configured.")
        else:
            print(f"\n⚠ {total - passed} check(s) failed. See details above.")
        
        return 0 if passed == total else 1
        
    except Exception as e:
        print(f"\n❌ Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
