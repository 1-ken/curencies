"""Project structure documentation.

# Finance Observer - Project Structure

This project follows FastAPI best practices with a modular, scalable structure:

```
app/
├── __init__.py              # App package marker
├── main.py                  # FastAPI application entry point
├── api/                     # API routes
│   ├── __init__.py
│   └── v1/                  # API version 1
│       ├── __init__.py
│       ├── api.py           # Router combiner for v1
│       └── endpoints/       # Individual route modules
│           ├── __init__.py
│           ├── alerts.py    # Alert management endpoints
│           └── data.py      # Data streaming and observation endpoints
├── core/                    # Core configuration and constants
│   ├── __init__.py
│   └── config.py            # Configuration loader
├── schemas/                 # Pydantic request/response models
│   ├── __init__.py
│   └── alert.py             # Alert schemas
├── services/                # Business logic layer
│   ├── __init__.py
│   ├── alert_service.py     # Alert management logic (AlertManager)
│   ├── observer_service.py  # Browser-based market data observer (SiteObserver)
│   ├── email_service.py     # SendGrid email notifications
│   └── sms_service.py       # Africa's Talking SMS notifications
├── models/                  # SQLAlchemy ORM models (future DB support)
│   └── __init__.py
├── crud/                    # Database CRUD operations (future use)
│   └── __init__.py
├── db/                      # Database connection and session management (future use)
│   └── __init__.py
└── tests/                   # Unit and integration tests
    └── __init__.py
```

## Architecture Overview

- **main.py**: Initializes FastAPI app, manages startup/shutdown, coordinates all services
- **api/**: Handles HTTP routing and WebSocket connections
- **services/**: Contains business logic (alerts, browser automation, notifications)
- **schemas/**: Validates API requests/responses with Pydantic
- **core/**: Centralized configuration management

## Key Features

- Real-time forex price monitoring via Playwright browser automation
- Price alerts with email (SendGrid) and SMS (Africa's Talking) notifications
- WebSocket data streaming to connected clients
- Continuous alert monitoring independent of client connections
- Modular architecture easy to extend with database support

## Running the Application

```bash
python run_uvicorn.py
```

Visit http://localhost:8000 for the dashboard.
"""
