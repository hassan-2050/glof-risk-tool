"""Export the watcher's geometry so it can be drawn, panned and scrubbed.

    python tools/build_map_data.py   ->  outputs/tools/map_data.json

WHY THIS IS A TOOL AND NOT A STAGE
----------------------------------
`reproduce` is byte-identical and offline, and every artefact it writes is
hashed. This writes a ~2 MB JSON containing JPEG bytes, which would bloat that
comparison for something no downstream stage reads. It re-derives geometry from
the same pinned scenes using the same functions the pipeline uses, so it cannot
disagree with the run - but it stays out of the hashed set.

WHAT IT EXPORTS, PER LAKE
  * one outline per scene, in WGS84, so a time slider can morph the lake
  * the debris-flow and clear-water corridors as polygons
  * a hillshade of the window as a JPEG, with its geographic bounds, so the
    page needs no tile server and works with the network off
  * the proxy values behind the alarm score, so a threshold slider can re-rank
    all fourteen lakes in the browser without another pipeline run

WHAT IT CANNOT EXPORT
  A live feed. Every scene here was acquired between 2017 and 2025 and is
  committed to the repository. There is no real-time satellite path in this
  project and no authenticated service behind the page; see the non-goals in
  README. What changes as you drag is the *view* over measured history.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys

# Must precede the numeric imports: the pipeline's own determinism contract.
os.environ.setdefault("PYTHONHASHSEED", "0")
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402
import rasterio.features  # noqa: E402
from PIL import Image  # noqa: E402
from pyproj import Transformer  # noqa: E402
from shapely.geometry import shape as shapely_shape  # noqa: E402

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from src.common.config import REPO_ROOT, load_config  # noqa: E402
from src.common.io import TOOL_OUTPUT_DIR, read_json  # noqa: E402
from src.watcher.delineate import select_lake_component, water_mask  # noqa: E402
from src.watcher.pipeline import find_anchor, load_dem_on_grid  # noqa: E402
from src.watcher.routing import msf_corridor  # noqa: E402
from src.watcher.scene import load_scene  # noqa: E402
from src.watcher.terrain import pixel_size_m  # noqa: E402

OUT = REPO_ROOT / "outputs"
# Reserved for tool-built artefacts; the run manifest does not hash it,
# so a page built here cannot pollute the determinism comparison.
SITE = OUT / TOOL_OUTPUT_DIR

# Simplification tolerance in metres. 15 m on a 10 m grid removes the pixel
# staircase without moving a shoreline by more than one and a half cells; the
# areas in the JSON are the UNSIMPLIFIED measured ones, so nothing downstream
# inherits the smoothing.
#
# It has to scale with the feature. A flat 15 m ate three quarters of Chamoli's
# 400 m² of scattered meltwater - drawn 99 m² against a measured 400 - which
# would have understated the one case whose whole point is that there is barely
# any water there. Tolerance is capped at an eighth of the polygon's own
# width, so a four-pixel blob is drawn as it was measured.
SIMPLIFY_M = 15.0
HILLSHADE_MAX_PX = 700


AREA_DRIFT_MAX = 0.05


def _simplify_within(g, tol_m: float, budget: float = AREA_DRIFT_MAX):
    """Smooth the pixel staircase, but never by more than `budget` of the area.

    Douglas-Peucker does not preserve area: on a jagged single-pixel boundary
    it cuts some corners and bridges others, and on small fragmented lakes it
    bridged more than it cut - Pyurepu's 14,800 m2 of supraglacial ponds drew
    as 16,748, a 13% overstatement of the very quantity the page exists to
    show. Backing the tolerance off until the drawn area is within budget
    bounds that error by construction instead of by a tuned constant, and
    falls back to the raw pixel outline when nothing fits.
    """
    a0 = g.area
    if a0 <= 0:
        return g
    while tol_m > 0.5:
        s = g.simplify(tol_m, preserve_topology=True)
        if not s.is_empty and abs(s.area - a0) / a0 <= budget:
            return s
        tol_m /= 2.0
    return g


def _mask_to_lonlat_polygons(mask: np.ndarray, transform, crs) -> list:
    """Vectorise a boolean raster into WGS84 rings.

    Returns a list of polygons, each [exterior, *holes], each ring a list of
    [lon, lat] pairs rounded to 6 dp (~0.1 m - past the point where a 10 m
    grid means anything, and it keeps the file half the size).
    """
    if not mask.any():
        return []
    tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    out = []
    for geom, value in rasterio.features.shapes(
            mask.astype(np.uint8), mask=mask, transform=transform):
        if not value:
            continue
        g = shapely_shape(geom)
        g = _simplify_within(g, SIMPLIFY_M)
        if g.is_empty:
            continue
        for poly in (g.geoms if g.geom_type == "MultiPolygon" else [g]):
            rings = []
            for ring in [poly.exterior, *poly.interiors]:
                xs, ys = zip(*ring.coords)
                lon, lat = tr.transform(xs, ys)
                rings.append([[round(a, 6), round(b, 6)]
                              for a, b in zip(lon, lat)])
            out.append(rings)
    # Largest first, so a renderer that draws only the first still draws the
    # lake rather than a stray pond.
    out.sort(key=lambda rings: -len(rings[0]))
    return out


def _bounds_lonlat(transform, shape, crs) -> list:
    tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    h, w = shape
    xs = [transform.c, transform.c + w * transform.a]
    ys = [transform.f + h * transform.e, transform.f]
    lon, lat = tr.transform([xs[0], xs[1], xs[0], xs[1]],
                            [ys[0], ys[0], ys[1], ys[1]])
    return [round(min(lon), 6), round(min(lat), 6),
            round(max(lon), 6), round(max(lat), 6)]


def _hillshade_jpeg(dem: np.ndarray, res_m: float) -> str | None:
    """Standard Horn hillshade, 315 deg azimuth, 45 deg altitude, as a data URI.

    JPEG rather than PNG: this is a continuous-tone shaded relief, and at
    quality 82 it is roughly a tenth the size of the equivalent PNG. The
    outlines are drawn as vectors on top, so nothing that needs crisp edges is
    going through the lossy codec.
    """
    if dem is None:
        return None
    z = np.asarray(dem, dtype=float)
    if not np.isfinite(z).any():
        return None
    z = np.nan_to_num(z, nan=float(np.nanmedian(z)))
    dy, dx = np.gradient(z, res_m, res_m)
    slope = np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    az, alt = np.radians(315.0), np.radians(45.0)
    shade = (np.sin(alt) * np.cos(slope)
             + np.cos(alt) * np.sin(slope) * np.cos(az - aspect))
    img = np.clip(shade, 0, 1)
    # Lift the midtones: a raw hillshade is dark enough that a dark-red
    # corridor drawn over it is hard to separate from shadow.
    img = 0.25 + 0.75 * img
    im = Image.fromarray((img * 255).astype(np.uint8), mode="L")
    if max(im.size) > HILLSHADE_MAX_PX:
        f = HILLSHADE_MAX_PX / max(im.size)
        im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))),
                       Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _downstream_hillshade(lid: str, pinned) -> tuple[str | None, list | None]:
    """Hillshade of the 100 km downstream DEM, plus its WGS84 bounds.

    The window hillshade covers 7 km; a 100 km corridor drawn past its edge
    floats on black. The downstream DEM is 90 m and already in WGS84, so the
    relief under the whole corridor costs one JPEG per lake.
    """
    import rasterio
    dem_path = pinned / lid / "dem_downstream.tif"
    if not dem_path.exists():
        return None, None
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(float)
        if src.nodata is not None:
            dem[dem == src.nodata] = np.nan
        b = src.bounds
        # Mean N-S pixel size in metres; the grid is geographic.
        res_m = abs(src.transform.e) * 110574.0
    uri = _hillshade_jpeg(dem, res_m)
    if uri is None:
        return None, None
    return uri, [round(b.left, 6), round(b.bottom, 6),
                 round(b.right, 6), round(b.top, 6)]


def build_downstream(lid: str, pinned, long_doc, exposure, scenarios,
                     validation) -> dict | None:
    """Everything the map needs to tell the downstream story for one lake.

    Best-effort by design: these artefacts come from `make scenarios`, which is
    a tool chain rather than a pipeline stage, and the map must still build for
    someone who has only run `reproduce`. Missing pieces are omitted, and the
    page says "run make scenarios" instead of drawing nothing silently.
    """
    lrec = (long_doc or {}).get(lid)
    if not lrec:
        return None
    regimes = {}
    for name, r in (lrec.get("regimes") or {}).items():
        line = r.get("polyline_lonlat") or []
        if len(line) < 2:
            continue
        regimes[name] = {
            "polyline": [[round(a, 5), round(b, 5)] for a, b in line],
            "runout_km": round(r["max_runout_m"] / 1000.0, 2),
            "truncated": bool(r.get("truncated_at_domain_edge")),
            "stop_reason": r.get("stop_reason"),
        }
    if not regimes:
        return None

    out = {"regimes": regimes}
    shade, bounds = _downstream_hillshade(lid, pinned)
    if shade:
        out["hillshade"] = shade
        out["bounds"] = bounds

    exr = (exposure or {}).get(lid) or {}
    if exr and "skipped" not in exr:
        out["osm_available"] = exr.get("osm_available", True)
        out["counts"] = exr.get("counts") or {}
        out["asset_km"] = exr.get("asset_km") or {}
        out["population"] = exr.get("population_in_corridor")
        out["named"] = exr.get("named_assets") or []
    srec = (scenarios or {}).get(lid) or {}
    if srec:
        out["volume_band_m3"] = srec.get("release_volume_band_m3")
        out["reach"] = srec.get("reach_km")
        out["capacity_trend"] = srec.get("capacity_trend")
    vrec = (validation or {}).get(lid)
    if vrec:
        out["validation"] = {
            "event": vrec.get("event"),
            "observed_km": vrec.get("observed_reach_km"),
            "observed_basis": vrec.get("observed_reach_basis"),
            "bracket_km": vrec.get("bracket_km"),
            "inside_bracket": vrec.get("observation_inside_bracket"),
            "places": vrec.get("impacted_places") or [],
        }
    return out


def build_lake(lake: dict, manifest_lake: dict, cfg, delin_rec: dict,
               routing_rec: dict, proxy_rec: dict) -> dict | None:
    lid = lake["id"]
    scenes, dem = {}, None
    for entry in manifest_lake["scenes"]:
        if not entry.get("assets"):
            continue
        sc = load_scene(lid, entry)
        if sc is None:
            continue
        if dem is None:
            dem = load_dem_on_grid(lid, sc)
        scenes[sc.label] = sc
    if not scenes:
        return None

    anchor_rc, _ = find_anchor(scenes, cfg)
    any_scene = next(iter(scenes.values()))
    res_m = pixel_size_m(any_scene.transform)

    # Per-scene records from the run, so the map shows the same area, QA verdict
    # and selection status the pipeline recorded - never a recomputed variant.
    by_label = {s["label"]: s for s in delin_rec["scenes"]}

    frames, masks = [], {}
    for label, sc in sorted(scenes.items()):
        rec = by_label.get(label)
        if rec is None:
            continue
        wm, _ = water_mask(sc, cfg)
        mask, _ = select_lake_component(wm, sc, cfg, anchor_rc=anchor_rc)
        masks[label] = mask
        # Scene QA and "did we actually see the lake" are different questions
        # and must both travel. Thame's 2025-12-12 scene is cloud-free - no QA
        # reason at all - yet the lake is frozen over, so delineation settled on
        # an 800 m2 pond 1.15 km away. The pipeline already discards that frame
        # when it picks one scene per year; a viewer needs the same evidence.
        comp = (rec.get("component_selection") or {}).get("selected") or {}
        frames.append({
            "label": label,
            "date": rec["acquired_date"],
            "role": rec["role"],
            "area_m2": rec["area_m2"],
            "area_km2": rec["area_km2"],
            "usable": not rec["qa"]["reasons"],
            "qa_reasons": rec["qa"]["reasons"],
            "in_series": bool(rec.get("selected_for_series")),
            "open_water_fraction": rec.get("footprint_open_water_fraction"),
            "dist_m": comp.get("distance_m"),
            "on_anchor": bool(comp.get("contains_anchor")),
            "tile_cloud_pct": rec.get("tile_cloud_pct"),
            "rings": _mask_to_lonlat_polygons(mask, sc.transform, sc.crs),
        })
    frames.sort(key=lambda f: (f["date"], f["label"]))

    # Corridors: route from the same scene the pipeline routed from, which it
    # records as scene_date, so the corridor on the map is the corridor in the
    # artefact rather than a fresh one from a different day's lake outline.
    corridors = {}
    route_date = (routing_rec or {}).get("scene_date")
    route_label = next((f["label"] for f in frames if f["date"] == route_date),
                       None)
    if route_label and dem is not None:
        base = masks[route_label]
        sc = scenes[route_label]
        for regime, clearwater in (("debris_flow", False),
                                   ("clearwater_flood", True)):
            r = msf_corridor(dem, base, res_m, cfg, clearwater=clearwater)
            corr = r.get("corridor")
            if corr is None or not corr.any():
                continue
            src = (routing_rec.get("regimes") or {}).get(regime, {})
            corridors[regime] = {
                "rings": _mask_to_lonlat_polygons(corr, sc.transform, sc.crs),
                "area_m2": src.get("area_m2", r["area_m2"]),
                "max_runout_m": src.get("max_runout_m", r["max_runout_m"]),
                "truncated": bool(src.get("truncated_at_window_edge")),
                "disclaimer": r["disclaimer"]["text"],
            }

    proxies = {p["proxy"]: p for p in (proxy_rec or {}).get("proxies", [])}
    ratio = proxies.get("source_to_lake_volume_ratio", {}).get("value")
    return {
        "lake_id": lid,
        "name": delin_rec.get("name", lid),
        "class": delin_rec.get("class"),
        "bounds": _bounds_lonlat(any_scene.transform, any_scene.shape,
                                 any_scene.crs),
        "hillshade": _hillshade_jpeg(dem, res_m),
        "frames": frames,
        "corridors": corridors,
        "validation": delin_rec.get("validation"),
        "score": ratio,
        "proxies": {k: {"fired": v.get("fired"), "value": v.get("value"),
                        "threshold": v.get("threshold"),
                        "source": v.get("source")}
                    for k, v in proxies.items()},
    }


def main() -> int:
    cfg = load_config()
    manifest = read_json(cfg.path("pinned") / "scenes_manifest.json")
    lakes_cfg = read_json(REPO_ROOT / "data" / "labels" / "lakes.json")
    delin = {r["lake_id"]: r for r in read_json(OUT / "stage02_delineation.json")["lakes"]}
    routing = {r["lake_id"]: r for r in read_json(OUT / "stage06_routing.json")["lakes"]}
    proxies = {r["lake_id"]: r for r in read_json(OUT / "stage04_proxies.json")["lakes"]}
    weval = read_json(OUT / "stage07_watcher_eval.json")

    # Tool-chain artefacts (make scenarios). Optional on purpose - see
    # build_downstream. read if present, keyed by lake.
    def _opt(name, key="lakes"):
        f = SITE / name
        if not f.exists():
            return None
        doc = read_json(f)
        rows = doc[key] if isinstance(doc, dict) else doc
        return {r["lake_id"]: r for r in rows if "lake_id" in r}
    long_doc = _opt("long_routing.json")
    exposure = _opt("corridor_exposure.json")
    scenarios = _opt("scenarios.json")
    validation = _opt("routing_validation.json", key="per_event")
    pinned = cfg.path("pinned")

    by_id = {l["id"]: l for l in lakes_cfg["lakes"]}
    out = []
    for ml in manifest["lakes"]:
        lid = ml["lake_id"]
        if lid not in by_id or lid not in delin:
            continue
        print(f"  {lid} ...", flush=True)
        rec = build_lake(by_id[lid], ml, cfg, delin[lid],
                         routing.get(lid), proxies.get(lid))
        if rec:
            ev = weval["per_lake"].get(lid, {})
            rec["label_burst"] = ev.get("label_burst")
            rec["rounce_class"] = ev.get("rounce_2017_class")
            # The advanced model is a strict superset of the baseline, so a
            # threshold slider that only moved the proxy side would show a
            # recall the pipeline never produces. Carry the growth flag too.
            rec["growth_flagged"] = ev.get("growth_only", {}).get("flagged")
            rec["growth_pct"] = ev.get("growth_only", {}).get("growth_pct")
            rec["growth_area_km2"] = ev.get("growth_only", {}).get("area_km2")
            rec["reasons_proxy"] = ev.get("proxy_augmented", {}).get("reasons")
            rec["downstream"] = build_downstream(lid, pinned, long_doc,
                                                 exposure, scenarios,
                                                 validation)
            out.append(rec)

    doc = {
        "lakes": out,
        "alarm_threshold": cfg.require(
            "proxies.impulse_wave.source_to_lake_volume_alarm"),
        "area_screen_km2": cfg.require("evaluation.baseline.area_threshold_km2"),
        "growth_screen_pct": cfg.require("evaluation.baseline.growth_flag_pct"),
        "downstream_available": long_doc is not None,
        "provenance": {
            "source": "re-derived from data/pinned/ with the pipeline's own "
                      "delineation and routing functions, after a reproduce",
            "not_live": "Every scene is a committed 2017-2025 acquisition. "
                        "There is no real-time satellite path in this project.",
        },
    }
    SITE.mkdir(parents=True, exist_ok=True)
    dest = SITE / "map_data.json"
    dest.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False), encoding="utf-8",
                    newline="\n")
    print(f"wrote {dest.relative_to(REPO_ROOT).as_posix()}  "
          f"({dest.stat().st_size:,} bytes, {len(out)} lakes, "
          f"{sum(len(l['frames']) for l in out)} outlines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
