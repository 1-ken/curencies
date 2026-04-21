#!/usr/bin/env python
"""
Production-ready uvicorn server launcher for Linux.
Note: Auto-reload disabled due to Playwright subprocess limitations.
"""
import os

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))

    # Production configuration
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # Allow external connections
        port=port,
        reload=False,
        log_level="info",
        access_log=True,
    )
