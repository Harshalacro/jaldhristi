"""
River network status: CWC gauges placed along India's rivers.

For each river line (Natural Earth, clipped to India) this module:

  1. attaches every catalogued CWC gauge within GAUGE_SNAP_KM of the line and
     measures its chainage (km along the line),
  2. orients the line upstream -> downstream using the gauges' own danger levels,
     which are reduced levels in metres above mean sea level and therefore fall
     downstream (Ballia 57.6 m -> Patna 48.6 m -> Farakka 22.3 m on the Ganga).
     With fewer than two datum points the direction is reported as unknown and
     the UI does not animate flow rather than guess,
  3. splits the line at the gauges into reaches, each coloured by the worse
     status of the gauges bounding it. Beyond the first and last gauge a reach
     is "unmonitored" - it is never painted safe just because nothing measures it.

A per-river longitudinal profile (level minus danger mark, upstream to downstream)
is returned too: it shows where along a river the flood wave currently sits.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import substring

from .config import DATA_DIR
from .official import official

log = logging.getLogger("jaldrishti.rivers")

RIVERS_PATH = DATA_DIR / "india_rivers.geojson"
GAUGE_SNAP_KM = 8.0
KM_PER_DEG = 111.0
EXTEND_KM = 25.0  # how far a gauge's status is carried past the first/last gauge

STATUS_RANK = {"DANGER": 3, "WARNING": 2, "NORMAL": 1, "UNMONITORED": 0}


@lru_cache(maxsize=1)
def _rivers() -> list[dict]:
    if not RIVERS_PATH.exists():
        return []
    gj = json.loads(RIVERS_PATH.read_text(encoding="utf-8"))
    out = []
    for f in gj["features"]:
        geom = shape(f["geometry"])
        parts = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
        out.append({**f["properties"], "parts": parts})
    return out


def _worse(a: str, b: str) -> str:
    return a if STATUS_RANK[a] >= STATUS_RANK[b] else b


def network_status() -> dict:
    rivers = _rivers()
    gauges = [official.station_status(code) for code in official.catalog]

    # Assign each gauge to the single nearest river part within the snap radius.
    assigned: dict[tuple[int, int], list[dict]] = {}
    for g in gauges:
        pt = Point(g["lon"], g["lat"])
        best, best_d = None, GAUGE_SNAP_KM / KM_PER_DEG
        for ri, r in enumerate(rivers):
            for pi, part in enumerate(r["parts"]):
                d = part.distance(pt)
                if d < best_d:
                    best, best_d = (ri, pi), d
        if best:
            part = rivers[best[0]]["parts"][best[1]]
            assigned.setdefault(best, []).append(
                {**g, "chainage_deg": part.project(pt), "offset_km": round(best_d * KM_PER_DEG, 1)}
            )

    features, summaries = [], []
    for ri, r in enumerate(rivers):
        river_counts = {"DANGER": 0, "WARNING": 0, "NORMAL": 0}
        profile = []
        oriented_any = False
        for pi, part in enumerate(r["parts"]):
            gs = sorted(assigned.get((ri, pi), []), key=lambda x: x["chainage_deg"])

            # Orientation: danger levels are metres above MSL and fall downstream.
            datum = [(x["chainage_deg"], x["danger_level"]) for x in gs if x.get("danger_level")]
            direction = "unknown"
            if len(datum) >= 2:
                n = len(datum)
                mx = sum(c for c, _ in datum) / n
                my = sum(v for _, v in datum) / n
                cov = sum((c - mx) * (v - my) for c, v in datum)
                if cov > 0:  # datum rises along the line -> line is drawn downstream->upstream
                    part = LineString(list(part.coords)[::-1])
                    L = part.length
                    for x in gs:
                        x["chainage_deg"] = L - x["chainage_deg"]
                    gs.reverse()
                direction = "downstream"
                oriented_any = True

            L = part.length
            ext = EXTEND_KM / KM_PER_DEG
            cuts: list[tuple[float, float, str]] = []
            if not gs:
                cuts.append((0.0, L, "UNMONITORED"))
            else:
                first, last = gs[0], gs[-1]
                if first["chainage_deg"] > 0:
                    a = max(0.0, first["chainage_deg"] - ext)
                    if a > 0:
                        cuts.append((0.0, a, "UNMONITORED"))
                    cuts.append((a, first["chainage_deg"], first["status"]))
                for x, y in zip(gs, gs[1:]):
                    cuts.append((x["chainage_deg"], y["chainage_deg"], _worse(x["status"], y["status"])))
                if last["chainage_deg"] < L:
                    b = min(L, last["chainage_deg"] + ext)
                    cuts.append((last["chainage_deg"], b, last["status"]))
                    if b < L:
                        cuts.append((b, L, "UNMONITORED"))

            for a, b, status in cuts:
                if b - a < 1e-4:
                    continue
                seg = substring(part, a, b)
                if seg.is_empty or seg.geom_type != "LineString":
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "river": r["name"],
                            "river_hi": r["name_hi"],
                            "status": status,
                            "direction": direction,
                        },
                        "geometry": mapping(seg),
                    }
                )

            for x in gs:
                river_counts[x["status"]] = river_counts.get(x["status"], 0) + 1
                vs = x.get("above_danger_m")
                # A reading tens of metres off its own danger mark is a datum
                # mismatch in the source (gauge zero vs mean sea level), not a flood.
                datum_suspect = vs is not None and abs(vs) > 25
                if x.get("danger_level") is not None and not datum_suspect:
                    profile.append(
                        {
                            "code": x["code"],
                            "name": x["name"],
                            "state": x.get("state"),
                            "part": pi,
                            "chainage_km": round(x["chainage_deg"] * KM_PER_DEG),
                            "status": x["status"],
                            "level_m": x.get("level_m"),
                            "danger_level": x["danger_level"],
                            "warning_level": x.get("warning_level"),
                            "vs_danger_m": x.get("above_danger_m"),
                            "trend": x.get("trend"),
                        }
                    )

        worst = "DANGER" if river_counts["DANGER"] else "WARNING" if river_counts["WARNING"] else "NORMAL" if river_counts["NORMAL"] else "UNMONITORED"
        profile.sort(key=lambda p: (p["part"], p["chainage_km"]))
        summaries.append(
            {
                "name": r["name"],
                "name_hi": r["name_hi"],
                "status": worst,
                "gauges": sum(river_counts.values()),
                "counts": river_counts,
                "direction_known": oriented_any,
                "profile": profile,
            }
        )

    summaries.sort(key=lambda s: (-STATUS_RANK[s["status"]], -s["counts"]["DANGER"], -s["counts"]["WARNING"], -s["gauges"]))
    return {
        "fetched_at": official.fetched_at,
        "gauges_on_rivers": sum(s["gauges"] for s in summaries),
        "rivers": summaries,
        "reaches": {"type": "FeatureCollection", "features": features},
        "method": (
            "CWC gauges within 8 km of a Natural Earth river line are placed by chainage; "
            "reaches between gauges take the worse status of the two; flow direction is "
            "inferred from gauge danger levels (m above MSL), which fall downstream."
        ),
    }
