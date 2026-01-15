#!/usr/bin/env python
"""
Production-ready uvicorn server launcher.
Note: Auto-reload disabled due to Playwright/Windows subprocess limitations.
"""
import sys
import asyncio
import logging

# Configure event loop for Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    # Production configuration
    uvicorn.run(
        "main:app",
        host="0.0.0.0",  # Allow external connections
        port=8000,
        reload=False,
        log_level="info",
        access_log=True,
    )
