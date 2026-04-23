# Log Analysis & Error Workarounds

## 🔴 CRITICAL ERRORS IDENTIFIED

---

## ERROR #1: SMS Service Failure - `'status' KeyError`

**Location**: Line 69 (17:02:49)
```
ERROR - Failed to send SMS to +254737778111: 'status'
```

**Root Cause**: 
The SMS service is trying to access a 'status' key from the Africa's Talking API response that doesn't exist. The response structure may have changed or the API returned an error response with a different structure.

**Impact**:
- SMS alerts will fail silently
- Users won't be notified when SMS alert is triggered
- Alert is marked as triggered but notification never reaches the user

### ✅ WORKAROUND #1: Add Response Validation to SMS Service

**File to modify**: `app/services/sms_service.py`

**Solution**: Add defensive null-checking and proper error handling:
```python
def send_sms(self, to_phone: str, message: str) -> bool:
    """Send SMS with robust error handling."""
    try:
        response = self.client.send(to_phone, message)
        
        # Defensive check: Handle both response objects and dicts
        if not response:
            logger.error(f"Empty response from SMS API for {to_phone}")
            return False
            
        # Try to get status safely
        status = None
        if isinstance(response, dict):
            status = response.get('status', response.get('StatusCode'))
        elif hasattr(response, 'status'):
            status = response.status
        elif hasattr(response, 'StatusCode'):
            status = response.StatusCode
        
        # Check for success status codes
        if status in [200, '200', 'Success', 'submitted']:
            logger.info(f"SMS sent to {to_phone}")
            return True
        else:
            logger.warning(f"SMS failed with status {status}")
            return False
            
    except KeyError as e:
        logger.error(f"Missing key in SMS response: {e}")
        logger.debug(f"Response: {response}")
        return False
    except Exception as e:
        logger.error(f"SMS service error: {e}")
        return False
```

**Alternative Workaround**: Disable SMS alerts temporarily
```python
# In alert_monitoring_task, wrap SMS sending in try-catch:
elif channel == "sms" and sms_service and alert.get("phone"):
    try:
        await _run_alert_action(sms_service.send_price_alert, ...)
    except Exception as e:
        logger.error(f"SMS alert failed (non-blocking): {e}")
        # Continue with other alerts instead of crashing
```

---

## ERROR #2: Commodity Pair Name Validation Missing

**Location**: Line 45 (17:01:21)
```
Created price alert 92bbc2a0-5e05-48d8-868f-19554a78e7e5 for XAUUSDCUR at 4747.0
```

**Root Cause**:
Alert was created with pair name `XAUUSDCUR` instead of `XAUUSD:CUR`. The colon was stripped during normalization, making it impossible to match against streaming data which includes the colon.

**Impact**:
- Commodity alerts never trigger because pair names don't match
- Alert is "active" but will never find matching price data
- Silent failure - alert looks fine but never works

### ✅ WORKAROUND #2: Validate Commodity Pair Format on Creation

**File to modify**: `app/api/v1/endpoints/alerts.py`

Add validation in the `create_alert` endpoint:
```python
@router.post("", response_model=dict)
async def create_alert(request: Union[CreateAlertRequest, CreateCandleAlertRequest]):
    """Create a new alert with pair validation."""
    
    # Validate commodity pair format
    pair = request.pair.strip()
    
    # Check if pair contains colon (commodity format)
    if ':' in pair:
        # Validate commodity pair has required colon and suffix
        parts = pair.split(':')
        if len(parts) != 2 or not parts[1]:
            raise HTTPException(
                status_code=400, 
                detail="Commodity pair must be in format 'SYMBOL:TYPE' (e.g., 'XAUUSD:CUR', 'HG1:COM')"
            )
    
    # Rest of validation...
```

**Quick Fix in Database**:
```bash
# Fix the incorrect alert in alerts.json
source .venv/bin/activate
python3 << 'EOF'
import json

with open('alerts.json', 'r') as f:
    data = json.load(f)

# Find and fix XAUUSDCUR → XAUUSD:CUR
for alert_id, alert in data.items():
    if alert.get('pair') == 'XAUUSDCUR':
        alert['pair'] = 'XAUUSD:CUR'
        print(f"Fixed alert {alert_id}: XAUUSDCUR → XAUUSD:CUR")

with open('alerts.json', 'w') as f:
    json.dump(data, f, indent=2)

print("✓ Alerts.json repaired")
EOF
```

---

## ERROR #3: Browser Timeout & Page Redirect to about:blank

**Location**: Lines 119-149 (17:10:39 - 17:11:05)
```
WARNING - [currencies] Page appears redirected/blocked (title=, url=about:blank); attempting recovery
ERROR - Snapshot failed for observer 'currencies': TimeoutError (TimeoutError())
```

**Root Cause**:
After 1200 snapshots (~13 minutes of streaming), browser context gets recycled. During recycling, the page is redirected to `about:blank` and subsequent navigation attempts timeout. The recovery mechanism tries to navigate but fails consistently.

**Impact**:
- ✅ Commodities observer recovers successfully (one warning, then continues)
- ❌ Currencies observer enters recovery loop and fails 3+ times
- Data streaming stops for currencies until observer is manually restarted
- Market data gaps during this period

### ✅ WORKAROUND #3: Improve Browser Recovery & Increase Context Lifespan

**Solution A: Increase context recycling interval** (QUICK FIX)

File: `app/services/observer_service.py`

```python
class SiteObserver:
    def __init__(self, ...):
        # ... existing code ...
        self.CONTEXT_RESET_INTERVAL = 3600  # 1 hour (instead of current)
        self.CONTEXT_RESET_SNAPSHOT_COUNT = 2400  # 2400 snapshots (double it)
```

**Rationale**: If 1200 snapshots = 1-2 hours and causes issues, doubling it gives more time before recycle.

**Solution B: Add retry logic with exponential backoff** (ROBUST FIX)

Modify `_navigate_with_retry()` to handle `about:blank`:
```python
async def _navigate_with_retry(self) -> bool:
    """Navigate with exponential backoff for about:blank recovery."""
    max_retries = 5
    base_delay = 1
    
    for attempt in range(max_retries):
        try:
            await self.page.goto(self.url, wait_until='domcontentloaded', timeout=15000)
            current_url = self.page.url
            if current_url != 'about:blank':
                return True
        except Exception as e:
            logger.warning(f"Navigation attempt {attempt+1} failed: {e}")
        
        # Exponential backoff
        delay = base_delay * (2 ** attempt)
        logger.info(f"Retrying navigation in {delay}s...")
        await asyncio.sleep(delay)
    
    return False
```

**Solution C: Disable context recycling for currencies observer** (AGGRESSIVE FIX)

In `config.json`:
```json
{
  "sources": [
    {
      "name": "currencies",
      "url": "https://finance.yahoo.com/markets/currencies/",
      // ... other config ...
      "contextRecyclingEnabled": false,
      "contextMaxSnapshots": 999999,  // Disable snapshot-based recycling
      "contextMaxAgeSeconds": 86400   // Recycle once per day instead
    }
  ]
}
```

---

## ERROR #4: Context Recycling Timing Issue

**Location**: Lines 118-121
```
INFO - Recycling browser context (snapshot #1200 or 767s old)
INFO - Recycling browser context (snapshot #1200 or 760s old)
```

**Root Cause**:
Both observers trigger context recycling simultaneously (at snapshot #1200). When commodities finishes first, it releases resources; currencies observer then fails immediately after.

**Impact**:
- Resource contention between observers
- Timing-dependent failure
- Hard to reproduce and debug

### ✅ WORKAROUND #4: Stagger Context Recycling

File: `app/services/observer_service.py`

```python
class SiteObserver:
    def __init__(self, source_name: str = "default", ...):
        # ... existing code ...
        self.source_name = source_name
        
        # Stagger recycling based on source name to avoid simultaneous recycling
        if source_name == "commodities":
            self.CONTEXT_RESET_SNAPSHOT_COUNT = 1200
        elif source_name == "currencies":
            self.CONTEXT_RESET_SNAPSHOT_COUNT = 1250  # Slightly offset
        else:
            self.CONTEXT_RESET_SNAPSHOT_COUNT = 1200
```

---

## RECOMMENDED IMPLEMENTATION ORDER

### 🔥 IMMEDIATE (Do First)
1. **Fix SMS service** → Add error handling (Workaround #1)
2. **Fix commodity pair** → Use quick fix script above
3. **Add pair validation** → Prevent future issues (Workaround #2)

### ⚡ SHORT TERM (Within 1 hour)
4. **Increase context lifespan** → (Workaround #3, Solution A)
5. **Stagger observer recycling** → (Workaround #4)

### 🔧 MEDIUM TERM (Next update)
6. **Improve browser recovery** → (Workaround #3, Solution B)
7. **Add comprehensive logging** → Capture response structures

---

## QUICK FIXES TO APPLY NOW

### 1. Fix SMS Error Handling
```bash
cd /home/here/Desktop/fx alert/currencies/curencies
source .venv/bin/activate

# Check current SMS service implementation
grep -n "status" app/services/sms_service.py
```

### 2. Fix Commodity Alert in Database
```bash
python3 << 'EOF'
import json

with open('alerts.json', 'r') as f:
    alerts = json.load(f)

fixed = 0
for aid, alert in alerts.items():
    if alert.get('pair') == 'XAUUSDCUR':
        alert['pair'] = 'XAUUSD:CUR'
        fixed += 1

with open('alerts.json', 'w') as f:
    json.dump(alerts, f, indent=2)

print(f"✓ Fixed {fixed} alerts")
EOF
```

### 3. Verify Pattern Match
```bash
python3 << 'EOF'
from app.services.alert_service import AlertManager

am = AlertManager()

# Test if commodities will match now
test_data = [
    {"pair": "XAUUSD:CUR", "price": "2451"},
    {"pair": "HG1:COM", "price": "5.45"}
]

triggered = am.check_alerts(test_data)
print(f"✓ Alerts triggered: {len(triggered)}")
EOF
```

---

## PREVENTION CHECKLIST

- [ ] Add input validation for pair format on alert creation
- [ ] Add defensive response parsing in SMS/Call services
- [ ] Add timeout monitoring dashboard
- [ ] Add logging for all API responses
- [ ] Add unit tests for observer recovery scenarios
- [ ] Document commodity pair naming requirements
- [ ] Add request/response logging for external services

---

## KEY TAKEAWAYS

| Error | Severity | Cause | Workaround | Time to Fix |
|-------|----------|-------|-----------|-------------|
| SMS 'status' KeyError | 🔴 High | Missing field in response | Defensive null-checking | 10 min |
| Pair format (XAUUSDCUR) | 🔴 High | No validation | Add pair validation + fix DB | 15 min |
| Browser timeout | 🟠 Medium | Context recycling | Increase interval + stagger | 20 min |
| about:blank redirect | 🟠 Medium | Recovery timeout | Add retry with backoff | 30 min |

