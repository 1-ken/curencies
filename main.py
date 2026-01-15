import asyncio
import json
import os
from typing import Any, Dict

from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse

from observer import SiteObserver

HERE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(HERE, "config.json")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG: Dict[str, Any] = json.load(f)

STREAM_INTERVAL = int(CONFIG.get("streamIntervalSeconds", 1))
MAJORS = CONFIG.get("majors", [])

app = FastAPI(title="Finance Observer")

observer: SiteObserver | None = None


@app.on_event("startup")
async def on_startup():
    global observer
    observer = SiteObserver(
        url=CONFIG.get("url", "https://example.com"),
        table_selector=CONFIG.get("tableSelector", "#pairs-table"),
        pair_cell_selector=CONFIG.get("pairCellSelector", "tbody tr td:first-child"),
        wait_selector=CONFIG.get("waitSelector", "body"),
        inject_mutation_observer=bool(CONFIG.get("injectMutationObserver", True)),
    )
    await observer.startup()


@app.on_event("shutdown")
async def on_shutdown():
    if observer:
        await observer.shutdown()


@app.get("/snapshot")
async def snapshot():
    if not observer:
        return JSONResponse({"error": "Observer not ready"}, status_code=503)
    data = await observer.snapshot(MAJORS)
    return JSONResponse(data)


@app.websocket("/ws/observe")
async def ws_observe(ws: WebSocket):
    await ws.accept()
    if not observer:
        await ws.send_json({"error": "Observer not ready"})
        await ws.close()
        return

    try:
        while True:
            data = await observer.snapshot(MAJORS)
            await ws.send_json(data)
            await asyncio.sleep(STREAM_INTERVAL)
    except Exception:
        # In a production app, log the exception
        try:
            await ws.close()
        except Exception:
            pass
