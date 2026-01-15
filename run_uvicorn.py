#!/usr/bin/env python
"""
Wrapper to run uvicorn without reload.
Reload is incompatible with Playwright on Windows due to subprocess limitations.

For development, restart this script manually when you make changes.
"""
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,  # Playwright + reload = subprocess issues on Windows
    )
