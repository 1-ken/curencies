import asyncio
import json
from observer import SiteObserver

async def test():
    obs = SiteObserver(
        'https://finance.yahoo.com/markets/currencies/',
        'table',
        'tbody tr td:nth-child(2)',
        'table tbody tr'
    )
    await obs.startup()
    
    # Test the extraction
    data = await obs._extract_pairs_with_prices()
    print(f"Found {len(data)} pairs")
    print(json.dumps(data[:10], indent=2))
    
    await obs.shutdown()

asyncio.run(test())
