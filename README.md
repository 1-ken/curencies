# Finance Observer (Playwright + FastAPI)

Streams live snapshots from a JS-heavy site using Playwright, extracts main FX currencies from a currency-pairs table via CSS selectors, and serves them over WebSockets.

**🌎 Forex Market Hours Feature**: This application automatically respects forex market operating hours (24/5). Data streaming and alert monitoring only occur when the forex market is open (Sunday 22:00 UTC - Friday 22:00 UTC). See [FOREX_MARKET_HOURS.md](FOREX_MARKET_HOURS.md) for details.

## Configure
Edit `config.json`:
- `sources`: Optional array of source configs. If provided, each source is scraped concurrently and merged into one live stream.
	- `name`: Source label (e.g., `currencies`, `commodities`).
	- `url`: Target page URL.
	- `waitSelector`, `tableSelector`, `pairCellSelector`: CSS selectors for extraction.
	- For TradingEconomics commodities, `pair` is extracted from the row `data-symbol` attribute and `common_name` from the first cell label.
	- `injectMutationObserver`: Enable DOM mutation tracking for that source.
	- `filterByMajors`: If true, keep only rows matching configured `majors`.
	- `enabled`: Enable/disable source without removing config.
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

## Frontend bootstrap and onboarding
The backend now exposes a first-run bootstrap contract for authenticated clients:

- `GET /me`: Returns the current user’s onboarding state and runtime bootstrap data.
- `POST /onboarding/complete`: Marks onboarding as complete for that user.

### `GET /me` response fields
The frontend should consume these fields:

- `userId`: Stable authenticated user id.
- `isFirstTimeUser`: `true` when the user has never completed onboarding.
- `onboardingCompletedAt`: Timestamp if onboarding is already done, otherwise `null`.
- `authRequired`: Whether the frontend should attach a bearer token.
- `wsUrl`: WebSocket URL for the observer stream.
- `apiBaseUrl`: Optional backend base URL if the frontend needs to build absolute links.

### Database requirement
Onboarding state is stored in PostgreSQL (`user_states` table). The table is created automatically on startup via `init_models()` when Postgres connects.

- Set `DATABASE_URL` (or `postgresDsn` in `config.json`) before starting the API.
- On successful startup, logs should include `PostgreSQL schema ensured` and must not show `PostgreSQL unavailable`.
- If Postgres is down, `GET /me` still returns a degraded first-time-user payload, but `POST /onboarding/complete` returns **503** with `{"detail":"Database unavailable"}`.

Restart the API after changing database configuration.

### Frontend behavior
1. After login, call `GET /me` first.
2. If `isFirstTimeUser` is `true`, show onboarding instead of the dashboard.
3. When onboarding is finished, call `POST /onboarding/complete`.
4. After completion, re-fetch `GET /me` and continue to the dashboard.
5. For protected observer routes, send:
   - `Authorization: Bearer <token>` for HTTP requests
   - `access_token=<token>` for `/ws/observe`

### Example request headers
```http
Authorization: Bearer eyJhbGciOi...
```

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
- `pairs`: Merged rows from all active sources.
- `pairsSample`: First 10 cell texts for quick inspection.
- `changes`: Recent DOM mutation types (if enabled).
- `ts`: ISO timestamp (UTC).

## /snapshot response contract
`GET /snapshot` returns grouped market rows by source:

```json
{
	"market_status": "open",
	"pairs": {
		"currencies": [
			{
				"pair": "EUR/USD",
				"price": "1.1514",
				"change": "-0.19",
				"source": "currencies"
			}
		],
		"commodities": [
			{
				"pair": "Gold",
				"common_name": "Gold",
				"price": "4890.70",
				"change": "+0.25",
				"source": "commodities"
			}
		]
	},
	"ts": "2026-03-19T05:25:37.000000+00:00"
}
```

Notes:
- `pairs.currencies` and `pairs.commodities` are always present as arrays (possibly empty).
- Commodity `pair` comes from TradingEconomics row `data-symbol` (e.g., `XAUUSD:CUR`, `HG1:COM`) and `common_name` contains readable labels (e.g., `Gold`, `Copper`).

## Data retention policy
- Historical and telemetry rows are retained for 14 calendar days.
- Cleanup runs automatically once per week at market open (`Sunday 22:00 UTC`).
- Rows older than 14 days are deleted from `historical_prices` and `stream_metrics`.
- Read APIs `/historical` and `/historical/stream-metrics` are also clamped to the last 14 days.
- This keeps backtesting focused on recent data while reducing storage usage.
