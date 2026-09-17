"""
Hyperlocal urban water-accumulation hotspots.

This is the part of the system aimed squarely at PS2's point that city-level weather
does not describe what happens at individual locations. A monitored city is divided
into a 16 x 16 grid of ~800 m cells (~13 x 13 km) and each cell gets:

  terrain (static, real data)
    elevation          Copernicus DEM GLO-90 via Open-Meteo, one sample per cell
    relative low-ness  where the cell sits in the city's own elevation range
    sink depth         how far the cell lies below the mean of its 8 neighbours
    flow accumulation  D8 routing on the grid: how many upslope cells drain into it
  urban form (static, OpenStreetMap)
    drains, streams, canals, major roads, rail, built-up land use -> urban intensity
    hospitals, schools, fire stations, road tunnels/underpasses -> exposure
  rain (dynamic, real data)
    hourly precipitation, 24 h back + 24 h ahead, sampled at a 3 x 3 grid over the
    city and bilinearly interpolated, so storms crossing the city are not smeared

and a simple, explainable ponding model runs hour by hour:

    runoff    = rain_rate x runoff_coefficient(urban) x (1 + upslope contribution)
    storage   = 0.85 x storage_prev + runoff - drainage_capacity(drains, urban)
    ponding   = storage x (1 + sink amplification)

It is deliberately a transparent bucket model, not a hydraulic simulation: there is
no sewer network data for Indian cities in the open. What it offers is ranking -
which streets fill first, and when - with every input shown. Uncertainty is carried
by re-running with rainfall at 60 % and 140 %, and by stating plainly that the DEM
(90 m) cannot see a 2 m underpass dip.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from datetime import datetime
from pathlib import Path

import httpx

from .config import OPEN_METEO_ELEVATION, OPEN_METEO_FORECAST, TIMEZONE
from .engine import LOCATIONS_BY_ID
from .features import _now_index

log = logging.getLogger("jaldrishti.hotspots")

N = 16
STEP = 0.0072  # degrees, ~800 m
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "hotspots"
OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
UA = {"User-Agent": "JalDrishti-prototype/1.0 (flood research)"}
RAIN_TTL_S = 1800
_rain_cache: dict[str, tuple[float, dict]] = {}

PONDING_KNOTS = [(0.0, 0.0), (2.0, 15.0), (10.0, 40.0), (30.0, 65.0), (60.0, 85.0), (120.0, 100.0)]


def _pw(x: float, knots) -> float:
    if x <= knots[0][0]:
        return knots[0][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return knots[-1][1]


def _grid(lat: float, lon: float) -> list[tuple[float, float]]:
    return [
        (round(lat + (i - N / 2 + 0.5) * STEP, 5), round(lon + (j - N / 2 + 0.5) * STEP, 5))
        for i in range(N)
        for j in range(N)
    ]


# ------------------------------------------------------------------ static


async def _elevations(client: httpx.AsyncClient, pts: list[tuple[float, float]]) -> list[float]:
    out: list[float] = []
    for k in range(0, len(pts), 100):
        b = pts[k : k + 100]
        r = await client.get(
            OPEN_METEO_ELEVATION,
            params={"latitude": ",".join(str(p[0]) for p in b), "longitude": ",".join(str(p[1]) for p in b)},
        )
        r.raise_for_status()
        out.extend(r.json()["elevation"])
    return out


async def _osm(client: httpx.AsyncClient, s: float, w: float, n: float, e: float) -> list[dict] | None:
    q = f"""[out:json][timeout:50];
(
 way["waterway"~"^(drain|canal|river|stream|ditch)$"]({s},{w},{n},{e});
 nwr["amenity"~"^(hospital|school|fire_station)$"]({s},{w},{n},{e});
 way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]({s},{w},{n},{e});
 way["highway"]["tunnel"="yes"]({s},{w},{n},{e});
 way["railway"="rail"]({s},{w},{n},{e});
 way["landuse"~"^(residential|commercial|industrial|retail)$"]({s},{w},{n},{e});
);
out center tags;"""
    for mirror in OVERPASS:
        try:
            r = await client.post(mirror, data={"data": q}, timeout=75, headers=UA)
            if r.status_code == 200:
                return r.json().get("elements", [])
        except Exception as exc:
            log.info("overpass %s failed: %s", mirror, str(exc)[:80])
    return None


def _d8_accumulation(elev: list[float]) -> list[int]:
    """Classic D8: visit cells high to low, pass each cell's flow to its lowest neighbour."""
    acc = [1] * (N * N)
    order = sorted(range(N * N), key=lambda k: -elev[k])
    for k in order:
        i, j = divmod(k, N)
        best, drop = None, 0.0
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == dj == 0:
                    continue
                ii, jj = i + di, j + dj
                if 0 <= ii < N and 0 <= jj < N:
                    d = (elev[k] - elev[ii * N + jj]) / (1.414 if di and dj else 1.0)
                    if d > drop:
                        best, drop = ii * N + jj, d
        if best is not None:
            acc[best] += acc[k]
    return acc


async def build_static(location_id: str) -> dict:
    loc = LOCATIONS_BY_ID[location_id]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{location_id}.json"
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        # A cache built while Overpass was down is retried at most once a day.
        if cached.get("osm_ok") or time.time() - cached.get("built_ts", 0) < 86400:
            return cached

    pts = _grid(loc["lat"], loc["lon"])
    s, w = pts[0][0] - STEP / 2, pts[0][1] - STEP / 2
    n, e = pts[-1][0] + STEP / 2, pts[-1][1] + STEP / 2

    async with httpx.AsyncClient(timeout=60, headers=UA) as client:
        elev, osm = await asyncio.gather(_elevations(client, pts), _osm(client, s, w, n, e))
    elev = [float(x if x is not None else 0.0) for x in elev]
    # The DEM reports open sea as 0 m. Sea cells are masked out: they would
    # otherwise rank as "the lowest ground in the city" in every coastal city.
    sea = [x <= 0.5 for x in elev]
    land = [x for x, is_sea in zip(elev, sea) if not is_sea] or elev

    # neighbourhood terrain metrics
    lo, hi = min(land), max(land)
    span = max(hi - lo, 1.0)
    acc = _d8_accumulation(elev)
    max_acc = max(acc)

    cells = []
    for k, (lat, lon) in enumerate(pts):
        i, j = divmod(k, N)
        neigh = [elev[ii * N + jj] for ii in range(i - 1, i + 2) for jj in range(j - 1, j + 2)
                 if (ii, jj) != (i, j) and 0 <= ii < N and 0 <= jj < N]
        mean_n = sum(neigh) / len(neigh)
        slope = max(abs(elev[k] - x) for x in neigh) / 800.0 * 100.0  # % grade to steepest neighbour
        cells.append(
            {
                "k": k, "i": i, "j": j, "lat": lat, "lon": lon, "sea": sea[k],
                "elev": round(elev[k], 1),
                # percentile rank among land cells, so a few hills cannot make
                # the whole city look "low"
                "rel_low": 0.0 if sea[k] else round(sum(1 for x in land if x > elev[k]) / len(land), 3),
                "sink_m": round(max(0.0, mean_n - elev[k]), 2),
                "slope_pct": round(slope, 2),
                "acc": acc[k],
                "acc_norm": round(math.log1p(acc[k]) / math.log1p(max_acc), 3),
                "drains": 0, "roads": 0, "rail": 0, "landuse": 0,
                "hospitals": [], "schools": [], "fire": [], "tunnels": [],
                "water_body": False,
            }
        )

    def cell_of(lat: float, lon: float) -> dict | None:
        i = int((lat - s) / STEP)
        j = int((lon - w) / STEP)
        if 0 <= i < N and 0 <= j < N:
            return cells[i * N + j]
        return None

    for el in osm or []:
        c = el.get("center") or ({"lat": el["lat"], "lon": el["lon"]} if "lat" in el else None)
        if not c:
            continue
        cell = cell_of(c["lat"], c["lon"])
        if not cell:
            continue
        tg = el.get("tags", {})
        name = tg.get("name") or tg.get("name:en")
        if "waterway" in tg:
            cell["drains"] += 1
            if tg["waterway"] in ("river", "canal"):
                cell["water_body"] = True
        elif tg.get("amenity") == "hospital":
            cell["hospitals"].append(name or "Hospital")
        elif tg.get("amenity") == "school":
            cell["schools"].append(name or "School")
        elif tg.get("amenity") == "fire_station":
            cell["fire"].append(name or "Fire station")
        elif tg.get("railway") == "rail":
            cell["rail"] += 1
        elif "landuse" in tg:
            cell["landuse"] += 1
        elif tg.get("tunnel") == "yes":
            cell["tunnels"].append(name or tg.get("ref") or "Road underpass")
        elif "highway" in tg:
            cell["roads"] += 1
            if name:
                cell.setdefault("road_names", [])
                if name not in cell["road_names"] and len(cell["road_names"]) < 3:
                    cell["road_names"].append(name)

    max_roads = max((c["roads"] for c in cells), default=1) or 1
    max_land = max((c["landuse"] for c in cells), default=1) or 1
    for c in cells:
        for key in ("hospitals", "schools", "fire", "tunnels"):
            c[key] = list(dict.fromkeys(c[key]))[:4]
        if osm is None:
            c["urban"] = 0.5  # unknown: assume mid-density rather than rural
        else:
            c["urban"] = round(min(1.0, 0.6 * c["roads"] / max_roads + 0.4 * c["landuse"] / max_land + 0.1 * min(c["rail"], 2)), 3)
        if c["sea"]:
            c.update(urban=0.0, susceptibility=0.0, capacity_mm_h=1e6, runoff_coeff=0.0)
            continue
        flat = math.exp(-c["slope_pct"] / 1.5)
        sink = min(c["sink_m"] / 4.0, 1.0)
        c["susceptibility"] = round(
            100 * (0.28 * c["rel_low"] + 0.20 * sink + 0.25 * c["acc_norm"] + 0.12 * flat + 0.15 * c["urban"]), 1
        )
        # drainage capacity (mm/h of runoff removed): formal drains help; dense
        # built-up land without mapped drains removes the least.
        base = 22.0 if c["drains"] else 12.0
        c["capacity_mm_h"] = round(base * (1.15 - 0.35 * c["urban"]) + (15.0 if c["water_body"] else 0.0), 1)
        c["runoff_coeff"] = round(0.30 + 0.55 * c["urban"], 2)

    static = {
        "location_id": location_id,
        "center": [loc["lat"], loc["lon"]],
        "n": N,
        "step_deg": STEP,
        "cell_m": 800,
        "bbox": [s, w, n, e],
        "elevation_range_m": [round(lo, 1), round(hi, 1)],
        "osm_ok": osm is not None,
        "osm_features": len(osm or []),
        "built_ts": time.time(),
        "cells": cells,
    }
    path.write_text(json.dumps(static, ensure_ascii=False), encoding="utf-8")
    return static


# ------------------------------------------------------------------ rainfall


async def _rain_field(static: dict) -> dict:
    """Hourly rain at a 3x3 lattice over the city (24 h back, 24 h ahead)."""
    lid = static["location_id"]
    cached = _rain_cache.get(lid)
    if cached and time.time() - cached[0] < RAIN_TTL_S:
        return cached[1]
    s, w, n, e = static["bbox"]
    lats = [s, (s + n) / 2, n]
    lons = [w, (w + e) / 2, e]
    pts = [(la, lo) for la in lats for lo in lons]
    async with httpx.AsyncClient(timeout=60, headers=UA) as client:
        r = await client.get(
            OPEN_METEO_FORECAST,
            params={
                "latitude": ",".join(f"{p[0]:.4f}" for p in pts),
                "longitude": ",".join(f"{p[1]:.4f}" for p in pts),
                "hourly": "precipitation",
                "past_days": 1,
                "forecast_days": 2,
                "timezone": TIMEZONE,
            },
        )
    r.raise_for_status()
    payload = r.json()
    payload = payload if isinstance(payload, list) else [payload]
    times = payload[0]["hourly"]["time"]
    series = [[v or 0.0 for v in item["hourly"]["precipitation"]] for item in payload]
    field = {"times": times, "lats": lats, "lons": lons, "series": series}
    _rain_cache[lid] = (time.time(), field)
    return field


def _bilinear(field: dict, lat: float, lon: float, h: int) -> float:
    lats, lons, ser = field["lats"], field["lons"], field["series"]
    fy = min(max((lat - lats[0]) / (lats[2] - lats[0]) * 2, 0.0), 2.0)
    fx = min(max((lon - lons[0]) / (lons[2] - lons[0]) * 2, 0.0), 2.0)
    y0, x0 = min(int(fy), 1), min(int(fx), 1)
    ty, tx = fy - y0, fx - x0
    v = lambda yy, xx: ser[yy * 3 + xx][h]
    top = v(y0, x0) * (1 - tx) + v(y0, x0 + 1) * tx
    bot = v(y0 + 1, x0) * (1 - tx) + v(y0 + 1, x0 + 1) * tx
    return top * (1 - ty) + bot * ty


# ------------------------------------------------------------------ dynamics


def _simulate(cells: list[dict], rain_at, hours: list[int], rain_scale: float, capacity_scale: float) -> list[list[float]]:
    """Bucket model per cell. Returns ponding (mm) for each hour index in `hours`."""
    storage = [0.0] * len(cells)
    out = []
    for h in hours:
        row = []
        for c in cells:
            rate = rain_at(c, h) * rain_scale
            runoff = rate * c["runoff_coeff"] * (1.0 + 1.5 * c["acc_norm"])
            st = max(0.0, 0.85 * storage[c["k"]] + runoff - c["capacity_mm_h"] * capacity_scale)
            storage[c["k"]] = st
            row.append(round(st * (1.0 + min(c["sink_m"] / 3.0, 1.0)), 1))
        out.append(row)
    return out


ACTIONS = {
    "tunnel": ("Close or barricade the underpass and divert traffic", "अंडरपास बंद कर यातायात मोड़ें"),
    "hospital": ("Keep an access route to the hospital clear; alert its emergency desk", "अस्पताल तक पहुँच मार्ग खुला रखें; आपात विभाग को सूचित करें"),
    "school": ("Advise the school on closure / early dismissal", "स्कूल को बंद या जल्दी छुट्टी की सलाह दें"),
    "no_drain": ("Pre-position portable dewatering pumps", "पोर्टेबल जल-निकासी पंप तैनात करें"),
    "drain": ("Clear drain inlets and culverts before the rain peak", "वर्षा चरम से पहले नालियों व पुलियों की सफाई करें"),
    "sink": ("Warn residents of the low-lying pocket; ready sandbags", "निचले इलाके के निवासियों को चेताएँ; रेत की बोरियाँ तैयार रखें"),
}


async def hotspots(location_id: str, capacity_scale: float = 1.0, scenario_mm_h: float | None = None, scenario_hours: int = 3) -> dict:
    static = await build_static(location_id)
    cells = static["cells"]
    field = await _rain_field(static)
    times = field["times"]
    now_i = _now_index(times, None)
    h_from, h_to = max(0, now_i - 24), min(len(times) - 1, now_i + 24)
    hours = list(range(h_from, h_to + 1))

    if scenario_mm_h:
        # A design storm starting next hour, on top of nothing else - the planner's
        # "what happens at 50 mm/h for 3 hours" question.
        rain_at = lambda c, h: scenario_mm_h if now_i < h <= now_i + scenario_hours else 0.0
    else:
        rain_at = lambda c, h: _bilinear(field, c["lat"], c["lon"], h)

    mid = _simulate(cells, rain_at, hours, 1.0, capacity_scale)
    low = _simulate(cells, rain_at, hours, 0.6, capacity_scale)
    high = _simulate(cells, rain_at, hours, 1.4, capacity_scale)

    risk_by_hour = [[round(_pw(p, PONDING_KNOTS)) for p in row] for row in mid]
    now_pos = hours.index(now_i)
    future = range(now_pos, len(hours))

    # per-cell peak over the next 24 h, with its uncertainty band
    for c in cells:
        k = c["k"]
        peak_pos = max(future, key=lambda t: mid[t][k])
        c["peak_ponding_mm"] = mid[peak_pos][k]
        c["peak_low_mm"] = low[peak_pos][k]
        c["peak_high_mm"] = high[peak_pos][k]
        c["peak_hour"] = times[hours[peak_pos]]
        c["peak_risk"] = round(_pw(mid[peak_pos][k], PONDING_KNOTS))
        c["now_risk"] = risk_by_hour[now_pos][k]
        exposure = min(1.0, 0.5 * c["urban"] + 0.25 * bool(c["hospitals"]) + 0.15 * bool(c["schools"]) + 0.25 * bool(c["tunnels"]))
        c["exposure"] = round(exposure, 2)
        # Priority blends where water will collect with what it would hit. The
        # static susceptibility keeps dry-day rankings meaningful for pre-monsoon
        # preparation work.
        c["priority"] = round((0.7 * c["peak_risk"] + 0.3 * c["susceptibility"]) * (0.5 + 0.5 * exposure), 1)

    ranked = sorted((c for c in cells if not c["sea"]), key=lambda c: -c["priority"])[:12]
    priorities = []
    for rank, c in enumerate(ranked, start=1):
        acts = []
        if c["tunnels"]:
            acts.append("tunnel")
        if c["hospitals"]:
            acts.append("hospital")
        if c["schools"] and c["peak_risk"] >= 40:
            acts.append("school")
        acts.append("drain" if c["drains"] else "no_drain")
        if c["sink_m"] >= 1.0:
            acts.append("sink")
        label = (c.get("road_names") or c["tunnels"] or c["hospitals"] or [None])[0]
        priorities.append(
            {
                "rank": rank,
                "k": c["k"],
                "lat": c["lat"],
                "lon": c["lon"],
                "label": label or f"Cell {c['i']}-{c['j']}",
                "priority": c["priority"],
                "peak_risk": c["peak_risk"],
                "peak_ponding_mm": c["peak_ponding_mm"],
                "band_mm": [c["peak_low_mm"], c["peak_high_mm"]],
                "peak_hour": c["peak_hour"],
                "susceptibility": c["susceptibility"],
                "why": _why(c),
                "facilities": {"hospitals": c["hospitals"], "schools": c["schools"], "tunnels": c["tunnels"], "fire": c["fire"]},
                "actions_en": [ACTIONS[a][0] for a in acts],
                "actions_hi": [ACTIONS[a][1] for a in acts],
            }
        )

    timeline = []
    for t, h in enumerate(hours):
        city_rain = sum(_bilinear(field, c["lat"], c["lon"], h) for c in cells[:: N + 1]) / len(cells[:: N + 1]) if not scenario_mm_h else rain_at(None, h)
        timeline.append(
            {
                "time": times[h],
                "is_forecast": h > now_i,
                "rain_mm_h": round(city_rain, 2),
                "cells_elevated": sum(1 for v in risk_by_hour[t] if v >= 40),
                "land_cells": sum(1 for c in cells if not c["sea"]),
                "cells_high": sum(1 for v in risk_by_hour[t] if v >= 65),
                "max_ponding_mm": max(mid[t]),
            }
        )

    peak_rain = max((x["rain_mm_h"] for x in timeline if x["is_forecast"]), default=0.0)
    confidence = _confidence(static, peak_rain, scenario_mm_h is not None)

    return {
        "location": {k: LOCATIONS_BY_ID[location_id].get(k) for k in ("id", "name", "name_hi", "state", "lat", "lon", "population")},
        "grid": {k: static[k] for k in ("n", "step_deg", "cell_m", "bbox", "elevation_range_m", "osm_ok", "osm_features")},
        "hours": [times[h] for h in hours],
        "now_index": now_pos,
        "risk_by_hour": risk_by_hour,
        "cells": [
            {k: c[k] for k in ("k", "i", "j", "lat", "lon", "sea", "elev", "sink_m", "acc", "urban", "susceptibility",
                               "capacity_mm_h", "drains", "peak_risk", "now_risk", "peak_ponding_mm",
                               "peak_low_mm", "peak_high_mm", "peak_hour", "priority", "hospitals", "schools", "tunnels")}
            for c in cells
        ],
        "priorities": priorities,
        "timeline": timeline,
        "scenario": {"mm_h": scenario_mm_h, "hours": scenario_hours} if scenario_mm_h else None,
        "capacity_scale": capacity_scale,
        "confidence": confidence,
        "method": {
            "en": (
                "800 m grid. Terrain from Copernicus DEM (90 m) with D8 flow accumulation and sink depth; "
                "urban intensity, drains and critical facilities from OpenStreetMap; hourly rain from a 3x3 "
                "Open-Meteo lattice. A bucket model routes runoff minus drainage capacity each hour; the band "
                "re-runs rainfall at 60% and 140%."
            ),
            "hi": (
                "800 मीटर ग्रिड। कोपरनिकस DEM से ऊँचाई, जल-प्रवाह संचय व गड्ढे; ओपनस्ट्रीटमैप से शहरी घनत्व, नालियाँ व "
                "महत्वपूर्ण सुविधाएँ; 3x3 बिंदुओं से प्रति घंटा वर्षा। प्रति घंटा बहाव में से जल-निकासी क्षमता घटाई जाती है; "
                "अनिश्चितता हेतु वर्षा 60% व 140% पर पुनः चलाई जाती है।"
            ),
        },
    }


def _why(c: dict) -> list[str]:
    out = []
    if c["rel_low"] >= 0.8:
        out.append(f"lower than {c['rel_low'] * 100:.0f}% of the city")
    if c["sink_m"] >= 1.0:
        out.append(f"sits {c['sink_m']} m below surrounding cells")
    if c["acc"] >= 12:
        out.append(f"{c['acc']} upslope cells drain into it")
    if not c["drains"] and c["urban"] >= 0.4:
        out.append("built-up with no mapped drain")
    if c["tunnels"]:
        out.append("contains a road underpass")
    if c["peak_ponding_mm"] >= 10:
        out.append(f"~{c['peak_ponding_mm']:.0f} mm of ponding expected at peak")
    return out or ["moderate terrain and drainage exposure"]


def _confidence(static: dict, peak_rain: float, scenario: bool) -> dict:
    value, reasons = 0.7, []
    reasons.append("Terrain from a 90 m DEM: street-scale dips such as underpasses are below its resolution")
    value -= 0.1
    if static["osm_ok"]:
        reasons.append(f"{static['osm_features']} OpenStreetMap features describe drains, roads and facilities")
    else:
        value -= 0.2
        reasons.append("OpenStreetMap unavailable: urban intensity and drains assumed, not mapped")
    if scenario:
        reasons.append("Design-storm scenario: rainfall is an input, not a forecast")
    elif peak_rain < 2:
        value += 0.1
        reasons.append("Little rain forecast in the next 24 h, so a low-risk reading is robust")
    else:
        reasons.append("Rain forecast at ~11 km resolution interpolated across the city")
    value = max(0.1, min(1.0, value))
    level = "high" if value >= 0.7 else "medium" if value >= 0.45 else "low"
    return {"value": round(value, 2), "level": level, "reasons": reasons}
