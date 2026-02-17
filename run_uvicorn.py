#!/usr/bin/env python
"""
Production-ready uvicorn server launcher for Linux.
Note: Auto-reload disabled due to Playwright subprocess limitations.
"""
import uvicorn

if __name__ == "__main__":
    # Production configuration
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # Allow external connections
        port=8000,
        reload=False,
        log_level="info",
        access_log=True,
    )
