# Finance Observer (Playwright + FastAPI)

Streams live snapshots from a JS-heavy site using Playwright, extracts main FX currencies from a currency-pairs table via CSS selectors, and serves them over WebSockets.

**🌎 Forex Market Hours Feature**: This application automatically respects forex market operating hours (24/5). Data streaming and alert monitoring only occur when the forex market is open (Sunday 22:00 UTC - Friday 22:00 UTC). See [FOREX_MARKET_HOURS.md](FOREX_MARKET_HOURS.md) for details.

## Configure
Edit `config.json`:
- `url`: Target website.
- `waitSelector`: Element to wait for (e.g., `body`).
- `tableSelector`: CSS for the pairs table (e.g., `#pairs-table`, `.currency-pairs`).
- `pairCellSelector`: Cells containing the pair text (usually first column: `tbody tr td:first-child`).
- `streamIntervalSeconds`: Push interval for WebSocket.
- `snapshotTimeoutSeconds`: Max seconds to wait for one market snapshot before counting a failure.
- `maxSnapshotFailures`: Consecutive snapshot failures before observer auto-restart.
- `wsSendTimeoutSeconds`: Max seconds allowed for one WebSocket send operation.
- `alertActionTimeoutSeconds`: Max seconds for one alert delivery action (email/SMS/call).
- `majors`: Currencies to extract: USD, EUR, JPY, GBP, AUD, CAD, CHF, NZD.
- `injectMutationObserver`: If true, records DOM mutation types in the payload.

Health endpoint:
- `GET /stream-health`: Returns stream freshness (`last_snapshot_age_seconds`), subscriber count, and failure counters.

Alert provider environment variables (SendGrid, Africa's Talking, Twilio) are listed in `DEPLOYMENT.md`.

Notes on selectors:
- Table rows: `<tableSelector> tbody tr`
- Pair cell (first column): `<tableSelector> tbody tr td:first-child`
- Pair link inside cell: `<tableSelector> tbody tr td:first-child a`
- With an id: `#pairs-table tbody tr td:first-child`
- With a class: `.currency-pairs tbody tr td:first-child`

## Install
```powershell
python -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Install browser engines
python -m playwright install
# or
playwright install
```

## Run
Start the server:
```powershell
uvicorn main:app --reload --port 8000
```
Use your frontend app (for example, Next.js) to consume the API and WebSocket endpoints.

One-off snapshot test (optional):
```powershell
python observer.py
```

## What it returns
Each snapshot payload:
- `title`: Page title.
- `majors`: Unique set of major currencies present.
- `pairsSample`: First 10 cell texts for quick inspection.
- `changes`: Recent DOM mutation types (if enabled).
- `ts`: ISO timestamp (UTC).
