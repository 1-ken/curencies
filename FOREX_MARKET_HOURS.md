# Forex Market Hours Feature

## Overview
The Finance Observer now automatically respects forex market operating hours. Data streaming and alert monitoring only occur when the forex market is actually open.

## Forex Market Hours
- **Operating Schedule**: 24 hours a day, 5 days a week
- **Opens**: Sunday 22:00 UTC (5 PM EST)
- **Closes**: Friday 22:00 UTC (5 PM EST)
- **Closed**: Saturday and most of Sunday

## How It Works

### Data Streaming
The `data_streaming_task` checks market hours before fetching and broadcasting data:
- ✅ **Market Open**: Fetches data every ~0.2 seconds (configurable via `streamIntervalSeconds`)
- 🔒 **Market Closed**: Pauses streaming, checks every 5 minutes for market reopening
- 📊 Logs market status changes for visibility

### Alert Monitoring
The `alert_monitoring_task` only processes and triggers alerts when the market is open:
- ✅ **Market Open**: Monitors prices and sends notifications when conditions are met
- 🔒 **Market Closed**: Skips alert processing (won't trigger false alerts during weekends)
- 📧 SMS/Email notifications only sent during market hours

### Creating Alerts
- ✅ Users can create alerts at any time (24/7)
- ✅ Alerts are stored and persist across restarts
- ⏰ Alerts will be checked and triggered only during market hours

## Benefits

1. **Accurate Alerts**: No false triggers from stale weekend data
2. **Resource Efficiency**: Browser automation and data fetching only when needed
3. **Cost Savings**: Reduces API calls during non-trading hours
4. **Better User Experience**: Users know data is real-time when market is active

## Technical Implementation

### Files Modified
- `app/api/v1/endpoints/data.py`: Added market hour checks to streaming and alert tasks
- `app/utils/forex_market_hours.py`: Core utility functions for market hour detection

### Utility Functions
```python
from app.utils.forex_market_hours import (
    is_forex_market_open,      # Check if market is currently open
    get_time_until_market_opens, # Get time until next market opening
    get_time_until_market_closes # Get time until market closes
)
```

## Testing
Run the test suite to verify market hours logic:
```bash
python3 test_forex_market_hours.py
```

Expected output shows:
- All test cases pass (13/13)
- Current market status
- Time until next market event (open/close)

## Logs
Monitor application logs for market status:
```
🔒 Forex market is CLOSED. Data streaming paused. Market opens in: 1 day, 8:56:32
✅ Forex market is OPEN. Resuming data streaming.
```

## Configuration
Market hours are hardcoded based on forex trading standards:
- Sunday 22:00 UTC - Friday 22:00 UTC
- No configuration needed
- Automatically handles timezone conversions

## Future Enhancements
Potential improvements for future versions:
- Holiday calendar integration (Christmas, New Year's, etc.)
- Major news event awareness (NFP, FOMC, etc.)
- Configurable market hours per currency pair region
- Manual override option for testing

---

**Note**: This feature ensures the application behaves exactly like real forex markets - active during trading hours, quiet on weekends.
