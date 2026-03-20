#!/usr/bin/env python3
"""Diagnostic script to test OHLC queries."""
import asyncio
import os
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://myuser:mypassword@localhost:5432/commodities")
# Convert to async database URL
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

async def main():
    engine = create_async_engine(ASYNC_DATABASE_URL, echo=False)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_delete=False)
    
    try:
        async with SessionLocal() as session:
            # Check total rows
            result = await session.execute(text("SELECT COUNT(*) as cnt FROM historical_prices"))
            total = result.scalar()
            print(f"Total rows: {total}")
            
            # Get unique pairs
            result = await session.execute(
                text("SELECT DISTINCT pair FROM historical_prices ORDER BY pair LIMIT 20")
            )
            pairs = [row[0] for row in result]
            print(f"\nFirst 20 pairs: {pairs}")
            
            # Try EURUSD
            if "EURUSD" in pairs or any("EUR" in p for p in pairs):
                pair_to_test = "EURUSD" if "EURUSD" in pairs else [p for p in pairs if "EUR" in p][0]
                print(f"\nTesting with pair: {pair_to_test}")
                
                # Check if data exists for this pair
                result = await session.execute(
                    text("SELECT COUNT(*) FROM historical_prices WHERE pair = :pair"),
                    {"pair": pair_to_test}
                )
                count = result.scalar()
                print(f"Rows for {pair_to_test}: {count}")
                
                # Get recent prices
                result = await session.execute(
                    text("""SELECT pair, price, observed_at FROM historical_prices 
                           WHERE pair = :pair ORDER BY observed_at DESC LIMIT 5"""),
                    {"pair": pair_to_test}
                )
                recent = result.fetchall()
                print(f"Recent prices: {recent}")
                
                # Test 1m bucket query
                result = await session.execute(text("""
                    WITH candles AS (
                        SELECT
                            TO_TIMESTAMP((EXTRACT(EPOCH FROM observed_at)::bigint / 60) * 60) AS bucket,
                            (ARRAY_AGG(price ORDER BY observed_at ASC))[1] AS open,
                            MAX(price) AS high,
                            MIN(price) AS low,
                            (ARRAY_AGG(price ORDER BY observed_at DESC))[1] AS close,
                            COUNT(*) AS volume
                        FROM historical_prices
                        WHERE pair = :pair
                        GROUP BY bucket
                        ORDER BY bucket DESC
                        LIMIT 10
                    )
                    SELECT * FROM candles ORDER BY bucket ASC
                """), {"pair": pair_to_test})
                
                candles = result.fetchall()
                print(f"\n1m OHLC Candles (last 10): {len(candles)} results")
                for c in candles[:3]:
                    print(f"  {c}")
            else:
                # Test with first available pair
                if pairs:
                    pair_to_test = pairs[0]
                    print(f"\nNo EURUSD found. Testing with: {pair_to_test}")
                    
                    result = await session.execute(
                        text("SELECT COUNT(*) FROM historical_prices WHERE pair = :pair"),
                        {"pair": pair_to_test}
                    )
                    count = result.scalar()
                    print(f"Rows for {pair_to_test}: {count}")
                    
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
