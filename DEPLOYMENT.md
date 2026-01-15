# Finance Observer - Production Deployment Guide

## Prerequisites
- Python 3.13 installed
- Port 8000 available
- SendGrid account with a verified sender email

## Installation

1. **Create virtual environment:**
```bash
python3.13 -m venv .venv313
```

2. **Activate environment:**
```bash
# Windows
.venv313\Scripts\Activate.ps1

# Linux/Mac
source .venv313/bin/activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
playwright install chromium
```

4. **Environment variables (.env):**
```
SENDGRID_API_KEY=your-sendgrid-api-key
FROM_EMAIL=verified-sender@example.com
```

## Configuration

Edit `config.json` to customize:
- `url`: Target website to scrape
- `streamIntervalSeconds`: Data refresh rate (default: 1)
- `majors`: Currency codes to monitor

Other runtime settings:
- Alerts persist in `alerts.json` (JSON store in project root)
- Email alerts use SendGrid with `FROM_EMAIL` as the sender
- "Equal" alerts use a tolerance of ±0.0001 (1 pip) for price matching

## Running

**Development:**
```bash
python run_uvicorn.py
```

**Production (example systemd):**
```
[Unit]
Description=Finance Observer
After=network.target

[Service]
WorkingDirectory=/path/to/app
Environment="PATH=/path/to/app/.venv313/bin"
ExecStart=/path/to/app/.venv313/bin/python run_uvicorn.py
Restart=always

[Install]
WantedBy=multi-user.target
```
Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable finance-observer
sudo systemctl start finance-observer
```

## API Endpoints

- `GET /` - Web interface
- `GET /snapshot` - Single data snapshot (JSON)
- `WS /ws/observe` - Live data stream (WebSocket)

## Monitoring

Logs are output to stdout. Redirect to file:
```bash
python run_uvicorn.py > app.log 2>&1
```

Alert data: `alerts.json` (safe to back up). Delete to start fresh (alerts will be lost).

## Security Notes

- Change `host` in `run_uvicorn.py` to `127.0.0.1` for localhost-only access
- Use reverse proxy (nginx/caddy) for production
- Enable HTTPS
- Rate limit API endpoints

## Troubleshooting

**Port in use:**
```bash
lsof -ti:8000 | xargs kill -9  # Linux/Mac
taskkill /F /IM python.exe     # Windows
```

**Browser issues:**
```bash
playwright install --force chromium
```
