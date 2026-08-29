"""Stage 5 data acquisition: exposure layers. Network-only, outside reproduce.

Run:  python -m src.data.fetch_exposure

Two products, deliberately from different methods so their disagreement is
informative rather than noise:

  OSM (Overpass)  buildings and named critical assets - hydropower, schools,
                  health posts, bridges. Global, ODbL, and strong in Nepal
                  thanks to post-2015-earthquake HOT mapping. This is the only
                  source that identifies WHAT an asset is, which is what makes
                  exposure decision-relevant rather than a headcount.
  WorldPop        100 m modelled population grid, CC BY 4.0.

Why not the products the brief also names:
  * Planetary Computer carries no population collection at all.
  * WorldPop's server advertises `Accept-Ranges: bytes` and then ignores Range
    headers - a request for bytes 0-1023 returns HTTP 200 with 9.5 MB - so GDAL
    cannot window-read it. Nepal is 5 MB and is downloaded whole; India (506 MB)
    and China (657 MB) are not, so the gridded cross-check exists only for the
    Nepal lakes and the output says so per lake rather than silently returning
    zero.
  * Microsoft Building Footprints on Planetary Computer are partitioned
    GeoParquet over abfs://, needing dask + adlfs to read one window. OSM gives
    buildings AND asset types in a single request, so it earns its place twice.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

from src.common.config import REPO_ROOT, load_config
from src.common.io import read_json, sha256_file, write_json
# Shared with Stage 5, which must not import this module (it pulls in
# requests/ssl and the offline guard rejects that on the reproduce path).
from src.watcher.exposure import classify

OVERPASS = "https://overpass-api.de/api/interpreter"
WORLDPOP_NPL = ("https://data.worldpop.org/GIS/Population/"
                "Global_2000_2020_Constrained/2020/BSGM/NPL/npl_ppp_2020_constrained.tif")

# Asset classes that change a decision. Hydropower first: it is Nepal's
# headline GLOF exposure story (405 MW plus 25 MW solar at Rasuwa, Teesta III
# 1,200 MW at Sikkim), and it must be separately reportable rather than folded
# into a generic "assets" count, per the Stage 5 criteria.
OVERPASS_QUERY = """[out:json][timeout:180];
(
  way["building"]({bbox});
  relation["building"]({bbox});
  node["amenity"~"^(school|college|kindergarten|hospital|clinic|doctors|pharmacy)$"]({bbox});
  way["amenity"~"^(school|college|kindergarten|hospital|clinic|doctors|pharmacy)$"]({bbox});
  node["power"~"^(plant|generator|substation)$"]({bbox});
  way["power"~"^(plant|generator|substation)$"]({bbox});
  node["man_made"="water_works"]({bbox});
  way["waterway"~"^(dam|weir)$"]({bbox});
  way["bridge"]({bbox});
  way["highway"~"^(trunk|primary|secondary|tertiary)$"]({bbox});
  node["place"~"^(village|hamlet|town|city)$"]({bbox});
);
out tags center;
"""


def query_overpass(bbox, retries: int = 3) -> dict:
    """bbox is (minlon, minlat, maxlon, maxlat); Overpass wants S,W,N,E."""
    q = OVERPASS_QUERY.format(bbox=f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}")
    last = None
    for attempt in range(retries):
        try:
            # Overpass answers HTTP 406 to the default python-requests
            # User-Agent and to text/plain bodies. curl works because it sends
            # a form content type and its own UA, so both are matched here.
            r = requests.post(
                OVERPASS, data=q.encode("utf-8"), timeout=240,
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "User-Agent": "glof-risk-tool/0.1 (research prototype; "
                                       "contact via repository)",
                         "Accept": "application/json"})
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
        # Overpass rate-limits aggressively; back off rather than hammer a
        # free public endpoint.
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"Overpass failed after {retries} attempts: {last}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lake", action="append")
    p.add_argument("--skip-worldpop", action="store_true")
    args = p.parse_args(argv)

    cfg = load_config()
    pinned = cfg.path("pinned")
    out_dir = pinned / "exposure"
    out_dir.mkdir(parents=True, exist_ok=True)
    lakes_doc = read_json(cfg.path("labels") / "lakes.json")
    manifest = read_json(pinned / "scenes_manifest.json")
    dem_bbox = {l["lake_id"]: l.get("dem_bbox_wgs84") for l in manifest["lakes"]}

    # --- WorldPop Nepal ---------------------------------------------------
    wp_path = out_dir / "worldpop_npl_2020_constrained.tif"
    wp_meta = None
    if not args.skip_worldpop and not wp_path.exists():
        print("downloading WorldPop Nepal (~5 MB)...")
        r = requests.get(WORLDPOP_NPL, timeout=600)
        r.raise_for_status()
        wp_path.write_bytes(r.content)
    if wp_path.exists():
        wp_meta = {"path": wp_path.relative_to(REPO_ROOT).as_posix(),
                   "sha256": sha256_file(wp_path),
                   "source": WORLDPOP_NPL,
                   "licence": "CC BY 4.0",
                   "coverage": "Nepal only",
                   "coverage_note": ("India and China are 506 MB and 657 MB and the "
                                     "server ignores HTTP Range requests, so no "
                                     "gridded population is pinned for South Lhonak, "
                                     "Chamoli or Pyurepu. Those lakes report the OSM "
                                     "estimate alone, flagged.")}

    lakes = lakes_doc["lakes"]
    if args.lake:
        lakes = [l for l in lakes if l["id"] in set(args.lake)]

    records = []
    for i, lake in enumerate(lakes, 1):
        bbox = dem_bbox.get(lake["id"])
        if not bbox:
            continue
        path = out_dir / f"{lake['id']}_osm.json"
        if path.exists():
            data = read_json(path)
            print(f"[{i}/{len(lakes)}] {lake['id']}: cached ({len(data.get('elements', []))} elements)")
        else:
            print(f"[{i}/{len(lakes)}] {lake['id']}: querying Overpass...", flush=True)
            data = query_overpass(bbox)
            write_json(path, data)
            time.sleep(5)   # be a good citizen on a free endpoint
        counts: dict[str, int] = {}
        for el in data.get("elements", []):
            c = classify(el)
            if c:
                counts[c] = counts.get(c, 0) + 1
        records.append({"lake_id": lake["id"], "bbox_wgs84": bbox,
                        "path": path.relative_to(REPO_ROOT).as_posix(),
                        "n_elements": len(data.get("elements", [])),
                        "class_counts": counts})
        print(f"    {counts}")

    write_json(out_dir / "exposure_manifest.json", {
        "generated_by": "src.data.fetch_exposure",
        "osm": {"endpoint": OVERPASS, "licence": "ODbL",
                "attribution": "(c) OpenStreetMap contributors"},
        "worldpop": wp_meta,
        "lakes": records,
    })
    print(f"\nexposure manifest -> data/pinned/exposure/exposure_manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
