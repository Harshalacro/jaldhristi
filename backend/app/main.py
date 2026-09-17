"""
FastAPI application entry point.

The background scheduler is a plain asyncio task rather than APScheduler: one
periodic job does not justify a dependency, and this way the refresh loop shares
the event loop (and therefore the HTTP client pool) with the request handlers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import store
from .api import router
from .config import (
    APP_NAME,
    APP_TAGLINE_EN,
    CORS_ORIGINS,
    REFRESH_MINUTES,
    REFRESH_ON_STARTUP,
    VERSION,
)
from .engine import engine

log = logging.getLogger("jaldrishti")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s")


async def _refresh_loop() -> None:
    """Re-score every REFRESH_MINUTES so the dashboard tracks changing conditions."""
    while True:
        await asyncio.sleep(REFRESH_MINUTES * 60)
        try:
            snap = await engine.refresh("schedule")
            log.info("scheduled refresh ok: run %s, %d locations", snap.run_id, len(snap.assessments))
        except Exception as exc:
            log.warning("scheduled refresh failed, keeping previous snapshot: %s", exc)


GAUGE_SWEEP_MINUTES = 15


async def _gauge_loop() -> None:
    """
    Read every CWC gauge on its own, faster cadence than the weather refresh:
    river levels move hourly and the portal publishes hourly. When a gauge that
    sits beside a monitored town changes tier, re-score the towns so the
    official-data floor follows the river without waiting 90 minutes.
    """
    from .official import official
    from .engine import LOCATIONS

    await asyncio.sleep(20)  # let the bootstrap load the catalogue first
    while True:
        try:
            if official.catalog:
                near = set(official.nearest_codes([(l["lat"], l["lon"]) for l in LOCATIONS]))
                before = {c: official.station_status(c)["status"] for c in near}
                n = await official.refresh_readings(list(official.catalog.keys()))
                changed = [c for c in near if official.station_status(c)["status"] != before[c]]
                log.info("gauge sweep: %d gauges reporting, %d town gauges changed tier", n, len(changed))
                if changed and engine.snapshot is not None and not engine.refreshing:
                    await engine.refresh("gauges")
        except Exception as exc:
            log.warning("gauge sweep failed: %s", exc)
        await asyncio.sleep(GAUGE_SWEEP_MINUTES * 60)


async def _bootstrap() -> None:
    """
    Boot in the order that gets a usable screen soonest:
      1. score immediately against a short baseline
      2. build the 30-year climatology in the background
      3. re-score, now with real seasonal context
    """
    try:
        from .official import official

        if official.catalog_stale():
            n = await official.build_catalog()
            log.info("CWC gauge catalogue built: %d stations", n)
    except Exception as exc:
        log.warning("CWC catalogue unavailable, continuing model-only: %s", exc)

    try:
        await engine.load_climatology()
        if REFRESH_ON_STARTUP:
            snap = await engine.refresh("startup")
            log.info("startup refresh ok: run %s, %d locations", snap.run_id, len(snap.assessments))
    except Exception as exc:
        log.error("startup refresh failed: %s", exc)

    try:
        built = await engine.ensure_climatology()
        if built:
            log.info("climatology built for %d locations; re-scoring", built)
            await engine.refresh("climatology")
    except Exception as exc:
        log.warning("climatology build failed, staying on the recent-window baseline: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    log.info("%s %s starting; refresh every %d min", APP_NAME, VERSION, REFRESH_MINUTES)
    boot = asyncio.create_task(_bootstrap())
    loop = asyncio.create_task(_refresh_loop())
    gauges = asyncio.create_task(_gauge_loop())
    try:
        yield
    finally:
        for task in (boot, loop, gauges):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title=f"{APP_NAME} API",
    description=(
        f"{APP_TAGLINE_EN}. A prototype hyperlocal flood risk engine for India built on "
        "Open-Meteo weather, GloFAS river discharge, Copernicus DEM and OpenStreetMap. "
        "Not an official Government of India service."
    ),
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", include_in_schema=False)
def root() -> JSONResponse:
    return JSONResponse(
        {
            "name": APP_NAME,
            "version": VERSION,
            "docs": "/docs",
            "api": "/api/system",
            "note": "Prototype. Not an official Government of India service.",
        }
    )
