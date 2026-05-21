# Finance Observer — Codebase Overview and 401 Diagnosis

## Summary
This codebase is a FastAPI backend for live FX and market-observer data. It uses Playwright to scrape market pages, streams snapshots over HTTP/WebSocket, persists telemetry to Redis/PostgreSQL, and exposes health and dashboard endpoints. The frontend/login logs you shared are from a separate Next.js app, but the backend authorization contract lives here and is the reason your `/api/observer/*` calls are returning `401`.

## Architecture
This project is organized as a layered asynchronous service:

- **Entry point**: `run_uvicorn.py` runs `app.main:app` with Uvicorn.
- **API layer**: `app/api/v1/endpoints/data.py` exposes snapshot, health, stream metrics, and WebSocket routes.
- **Browser scraping layer**: `app/services/observer_service.py` launches Playwright and extracts rows from source pages.
- **Alerting/persistence layer**: `app/services/alert_service.py`, `redis_service.py`, and `postgres_service.py` handle alerts and storage.
- **Auth layer**: `app/core/auth.py` validates bearer tokens and WebSocket tokens using the NextAuth secret.
- **Runtime wiring**: `app/main.py` creates the app, loads config, initializes services, starts background tasks, and registers routes.

The runtime model is event-loop driven and heavily asynchronous. On startup the app:
1. loads config,
2. connects to Redis/Postgres if available,
3. creates one or more `SiteObserver` instances from `config.json`,
4. injects them into the endpoint module,
5. starts background streaming and alert-monitoring tasks.

## Directory Structure

```text
project-root/
├── app/
│   ├── main.py                 — FastAPI application bootstrap, startup/shutdown hooks
│   ├── core/
│   │   ├── auth.py             — Bearer/WebSocket token validation
│   │   └── config.py           — Config loader for config.json and env vars
│   ├── api/
│   │   └── v1/
│   │       ├── api.py          — Router composition
│   │       └── endpoints/
│   │           ├── alerts.py    — Alert CRUD/management endpoints
│   │           └── data.py      — Snapshot, WS, health, client config, stream endpoints
│   ├── services/
│   │   ├── observer_service.py  — Playwright observer and row normalization
│   │   ├── alert_service.py     — Alert state and trigger logic
│   │   ├── postgres_service.py  — Async DB access
│   │   ├── redis_service.py     — Redis publish/subscribe and queue support
│   │   ├── email_service.py     — SendGrid alerts
│   │   ├── sms_service.py       — Africa's Talking alerts
│   │   └── call_service.py      — Twilio voice alerts
│   ├── schemas/
│   │   └── responses.py         — Pydantic response models
│   └── utils/
│       ├── forex_market_hours.py — Market-hours gating logic
│       └── pair_normalizer.py    — Canonical symbol normalization
├── config.json                  — Source definitions and runtime tuning
├── run_uvicorn.py               — Server launcher
├── README.md                    — Setup and endpoint notes
└── scripts/migrations/          — DB migrations
```

## Key Abstractions

### `Config` / `get_config`
- **File**: `app/core/config.py`
- **Responsibility**: Loads `config.json` and environment overrides into a typed config object.
- **Interface**: `get_config()` returns a `Config` dataclass with URLs, selectors, Redis/Postgres settings, timing knobs, and source definitions.
- **Lifecycle**: Imported once during app startup in `app/main.py`.
- **Used by**: `app/main.py`, `app/services/observer_service.py` via source configuration, `app/api/v1/endpoints/data.py` via injected tuning values.

### `get_current_user_id`
- **File**: `app/core/auth.py`
- **Responsibility**: Enforces API authorization for HTTP routes.
- **Interface**: Depends on `Authorization: Bearer <token>` and decodes the token with `NEXTAUTH_SECRET`.
- **Lifecycle**: Called on every protected request via FastAPI dependency injection.
- **Used by**: `/snapshot`, `/stream-health`, `/client-config`, `/ws/observe` token validation path indirectly.

### `SiteObserver`
- **File**: `app/services/observer_service.py`
- **Responsibility**: Opens a browser, navigates to a market source, waits for the page to stabilize, extracts rows, and normalizes them into payloads.
- **Interface**: `startup()`, `snapshot(majors)`, `shutdown()`.
- **Lifecycle**: Created per source in `app/main.py`, kept alive for the lifetime of the app.
- **Used by**: `data_streaming_task`, snapshot endpoint, health checks.

### `data_endpoints` module state
- **File**: `app/api/v1/endpoints/data.py`
- **Responsibility**: Holds the active observers, latest snapshot, subscriber queues, stream tuning, and background tasks.
- **Interface**: `set_observers`, `set_observer`, `set_alert_manager`, `set_config`, `set_runtime_tuning`, `data_streaming_task()`, `alert_monitoring_task()`, `snapshot()`, `ws_observe()`.
- **Lifecycle**: Initialized by `app.main.on_startup()`, cleared on shutdown.
- **Used by**: HTTP endpoints and long-running tasks.

### `AlertManager`
- **File**: `app/services/alert_service.py`
- **Responsibility**: Tracks user alerts, evaluates them against live data, and queues persistence actions.
- **Used by**: Alert monitoring task and the dashboard/data broadcast flow.

## Data Flow

### 1) Startup
1. `run_uvicorn.py` launches `app.main:app`.
2. `app.main` loads env vars and `config.json` through `get_config()`.
3. Redis and PostgreSQL are connected if available.
4. Each enabled source in `config.sources` becomes a `SiteObserver`.
5. The first observer is stored as the primary observer; all are injected into `data_endpoints`.
6. Background tasks start:
   - `alert_monitoring_task()`
   - `data_streaming_task()`
   - optionally archive/retention tasks

### 2) Snapshot streaming
1. `data_streaming_task()` checks forex market hours.
2. If open, it calls `_collect_snapshot_from_observers()`.
3. Each observer calls `snapshot(MAJORS)`.
4. `SiteObserver.snapshot()` extracts source-specific rows and normalizes them.
5. The merged payload is cached in `latest_data`, pushed to Redis, and fanned out to subscriber queues.
6. Health and WebSocket clients read this cached or streamed data.

### 3) Protected API access
1. HTTP endpoints like `/snapshot`, `/stream-health`, and `/client-config` call `get_current_user_id`.
2. That dependency requires a valid bearer token unless `AUTH_DISABLED` is enabled.
3. The token must be signed with `NEXTAUTH_SECRET` and contain `sub` and `exp`.
4. If the header is missing or invalid, FastAPI returns `401`.

### 4) WebSocket access
1. `/ws/observe` reads `access_token` from the query string.
2. `verify_ws_access_token()` validates it using the same NextAuth secret.
3. If valid, the socket opens and receives stream data.
4. If invalid/missing, the server closes with code `4401`.

## Non-Obvious Behaviors & Design Decisions

### Why you are getting `401` after login
Your login succeeded in the Next.js app, but that does not automatically authorize calls to this backend. In this codebase, backend routes do **not** use the browser session cookie directly. They require:

- an **Authorization header** for HTTP requests, or
- an **`access_token` query param** for WebSocket connections.

So requests like:

- `GET /api/observer/health`
- `GET /api/observer/snapshot`
- `GET /api/observer/stream-health`

will return `401` unless the frontend forwards a valid bearer token.

### What token format the backend expects
`app/core/auth.py` uses `jwt.decode(..., NEXTAUTH_SECRET, algorithms=["HS256"], options={"require": ["sub", "exp"]})`.

That means the token must be:
- signed with the same `NEXTAUTH_SECRET` as the NextAuth server,
- HS256,
- contain `sub`,
- contain `exp`.

If the frontend is using only a session cookie or an ID token from Google, that is not enough unless your backend knows how to validate it. This backend is specifically expecting the NextAuth-issued JWT, not just any authenticated browser session.

### Why the login log looks successful but API calls fail
Your logs show:
- NextAuth session endpoints succeeding,
- Google OAuth completing,
- dashboard loading,
- then the observer endpoints returning 401.

That pattern usually means:
- the frontend is authenticated,
- but the backend proxy is not attaching the bearer token to `/api/observer/*` requests,
- or the proxy route is forwarding unauthenticated requests to the FastAPI backend.

### `AUTH_DISABLED` exists as a development escape hatch
If `AUTH_DISABLED=true`, the auth layer returns `"dev-user"` and bypasses token checks. This is useful for local debugging, but it is not the normal production path.

### The earlier `get_config` crash was a separate startup issue
`app/main.py` originally imported `get_config` from `app.core.config`, but the module did not define it. That caused Uvicorn to fail before the app could start. The config loader has now been added, so the current runtime issue is auth, not config import.

### `config.json` is source-driven, not just global settings
The app reads an array of `sources`, each with its own:
- URL
- table selector
- wait selector
- pair selector
- optional commodity allowlist
- filter flags

That means the backend can scrape currencies, commodities, bonds, and DXY from different pages concurrently.

### Why the app uses a global module state pattern
`app/api/v1/endpoints/data.py` keeps global references to observers, tasks, Redis, and Postgres. This is deliberate: the endpoint handlers and background workers need to share live state without building a larger dependency injection container.

## Module Reference

| File | Purpose |
|------|---------|
| `run_uvicorn.py` | Launches the FastAPI server with Uvicorn |
| `app/main.py` | App bootstrap, service init, startup/shutdown orchestration |
| `app/core/config.py` | Loads `config.json` and env-driven runtime configuration |
| `app/core/auth.py` | Validates bearer tokens and WS access tokens |
| `app/api/v1/api.py` | Composes the API router |
| `app/api/v1/endpoints/data.py` | Snapshot, health, WS, and streaming logic |
| `app/api/v1/endpoints/alerts.py` | Alert management endpoints |
| `app/services/observer_service.py` | Playwright browser observer and extraction logic |
| `app/services/alert_service.py` | Alert state, trigger evaluation, persistence hooks |
| `app/services/redis_service.py` | Redis queue/pubsub abstraction |
| `app/services/postgres_service.py` | Async DB access and historical persistence |
| `app/utils/forex_market_hours.py` | Market-open/closed gating |
| `app/utils/pair_normalizer.py` | Symbol canonicalization |
| `app/schemas/responses.py` | Response models for health, snapshot, and stream info |
| `config.json` | Source list and timing/selector configuration |
| `README.md` | Setup and behavior notes |

## How to stop the 401s
The backend itself is doing exactly what it is coded to do: reject unauthenticated requests. To avoid `401`, the frontend must send a valid token.

### For HTTP endpoints
Attach:

```http
Authorization: Bearer <nextauth-jwt>
```

to requests for:
- `/api/observer/health`
- `/api/observer/snapshot`
- `/api/observer/stream-health`
- `/api/observer/client-config`
- any other protected observer API route

### For WebSocket
Connect with:

```text
/ws/observe?access_token=<nextauth-jwt>
```

### Practical debugging checks
1. Confirm the frontend can access the actual NextAuth JWT, not just the session object.
2. Confirm the token is the same secret/signing scheme used by `app/core/auth.py`.
3. Confirm your Next.js proxy layer forwards the token to the FastAPI backend.
4. If you only want local testing, set `AUTH_DISABLED=true` in the backend environment.

## Suggested Reading Order
1. `app/core/auth.py` — explains exactly why requests are being rejected.
2. `app/main.py` — shows how services and tasks are wired together.
3. `app/api/v1/endpoints/data.py` — shows which routes are protected and how data flows.
4. `app/core/config.py` — shows what the app expects from `config.json`.
5. `app/services/observer_service.py` — shows how the data is scraped and normalized.
