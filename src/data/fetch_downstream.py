"""Fetch a WIDE, COARSE DEM per lake so a corridor can leave the headwaters.

    python -m src.data.fetch_downstream            # all lakes
    python -m src.data.fetch_downstream --lakes thyanbo_tsho south_lhonak
    python -m src.data.fetch_downstream --dry-run  # sizes only, no download

NEEDS NETWORK. Like Stage 1, deliberately outside `reproduce`.

WHY
---
Every corridor in this project was capped at ~3.5 km because that is the
half-width of the analysis window, while the floods being modelled ran 10 to
169 km. `tools/validate_routing.py` measured the result: 0 of 4 predicted
corridors reached the nearest observed impact, short by 5.9x to 23.5x. That is
a domain problem, not a physics problem - the router was describing a valley it
could not see.

WHY COARSE
----------
Long-range runout does not need 30 m. The corridor is explicitly indicative and
the disclaimer already says a 30 m DSM cannot resolve a channel cross-section,
so carrying 30 m over 100 km buys nothing and costs ~9x the bytes. This fetches
GLO-30 and resamples to the configured long-range resolution, which keeps a
100 x 100 km domain around 1-2 MB compressed instead of 40 MB.

The near-lake 30 m window is untouched: dam geometry, lakefront slope and
avalanche source areas all still run on `dem_glo30.tif`. Two DEMs, two jobs.

WHAT IT DOES NOT SOLVE
----------------------
A wider box is still a box. A corridor that leaves this domain is still a lower
bound, and the truncation flag still travels with it. What changes is the size
of the box: 100 km rather than 7 km.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling

from src.common.config import REPO_ROOT, load_config
from src.common.io import read_json, sha256_file, write_json
from src.data.fetch import DEM_COLLECTION, GDAL_ENV, _open_catalog

# One degree of latitude is ~110.6 km; GLO-30 tiles are 1x1 degree, so a
# domain wider than ~55 km half-width starts pulling many tiles. Kept in config
# so it is a documented threshold rather than a number in code.
DEFAULT_HALF_KM = 50.0
DEFAULT_RES_M = 90.0


def bbox_around(lat: float, lon: float, half_km: float):
    dlat = half_km / 110.574
    dlon = half_km / (111.320 * np.cos(np.radians(lat)))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def _covers(path: Path, bbox) -> bool:
    """True if an existing file already spans the requested box.

    Same guard as the Stage 1 fetch, for the same reason: resuming on filename
    alone silently reuses a file cut to a narrower box, and the failure looks
    like a routing bug three stages later.
    """
    if not path.exists():
        return False
    try:
        with rasterio.open(path) as src:
            b = src.bounds
    except Exception:
        return False
    eps = 1e-6
    return (b.left <= bbox[0] + eps and b.bottom <= bbox[1] + eps
            and b.right >= bbox[2] - eps and b.top >= bbox[3] - eps)


def fetch_one(cat, lake: dict, half_km: float, res_m: float, pinned: Path,
              dry_run: bool) -> dict:
    lid = lake["id"]
    bbox = bbox_around(lake["lat"], lake["lon"], half_km)
    out_path = pinned / lid / "dem_downstream.tif"

    if _covers(out_path, bbox):
        return {"lake_id": lid, "skipped": True, "path": out_path.name,
                "bytes": out_path.stat().st_size,
                "sha256": sha256_file(out_path)}

    # Target grid: the requested box at res_m, in degrees.
    deg_per_m_lat = 1.0 / 110574.0
    deg_per_m_lon = 1.0 / (111320.0 * float(np.cos(np.radians(lake["lat"]))))
    width = int(round((bbox[2] - bbox[0]) / (res_m * deg_per_m_lon)))
    height = int(round((bbox[3] - bbox[1]) / (res_m * deg_per_m_lat)))

    # Sizing is answerable without the network, and the point of --dry-run is
    # to decide whether to spend the bandwidth at all. Ask before searching.
    if dry_run:
        return {"lake_id": lid, "dry_run": True, "bbox_wgs84": list(bbox),
                "grid": [height, width],
                "est_mb_uncompressed": round(height * width * 4 / 1e6, 1)}

    items = list(cat.search(collections=[DEM_COLLECTION], bbox=list(bbox)).items())
    if not items:
        return {"lake_id": lid, "error": "no DEM tiles returned"}

    with rasterio.Env(**GDAL_ENV):
        from rasterio.merge import merge
        srcs = [rasterio.open(i.assets["data"].href) for i in items]
        try:
            # Resample during the merge rather than after: merging 30 m tiles
            # across a 1-degree span first would materialise ~40x more memory
            # than the result needs.
            mosaic, transform = merge(
                srcs, bounds=(bbox[0], bbox[1], bbox[2], bbox[3]),
                res=(res_m * deg_per_m_lon, res_m * deg_per_m_lat),
                resampling=Resampling.bilinear)
            profile = srcs[0].profile.copy()
            profile.update(height=mosaic.shape[1], width=mosaic.shape[2],
                           transform=transform, count=1, driver="GTiff",
                           compress="deflate", predictor=3, tiled=True)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(mosaic[0], 1)
        finally:
            for s in srcs:
                s.close()

    return {"lake_id": lid, "tiles": [i.id for i in items],
            "shape": list(mosaic.shape[1:]), "res_m": res_m,
            "half_width_km": half_km, "bbox_wgs84": list(bbox),
            "bytes": out_path.stat().st_size,
            "sha256": sha256_file(out_path)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="fetch-downstream", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lakes", nargs="*", help="lake ids (default: all)")
    p.add_argument("--half-km", type=float, default=DEFAULT_HALF_KM)
    p.add_argument("--res-m", type=float, default=DEFAULT_RES_M)
    p.add_argument("--dry-run", action="store_true",
                   help="report grid sizes without downloading")
    args = p.parse_args(argv)

    cfg = load_config()
    pinned = cfg.path("pinned")
    lakes = read_json(REPO_ROOT / "data" / "labels" / "lakes.json")["lakes"]
    if args.lakes:
        want = set(args.lakes)
        lakes = [l for l in lakes if l["id"] in want]
        missing = want - {l["id"] for l in lakes}
        if missing:
            print(f"unknown lake ids: {sorted(missing)}", file=sys.stderr)
            return 2

    cat = None if args.dry_run else _open_catalog()

    records, total = [], 0
    for lake in lakes:
        print(f"  {lake['id']} ...", end=" ", flush=True)
        try:
            r = fetch_one(cat, lake, args.half_km, args.res_m, pinned,
                          args.dry_run)
        except Exception as exc:                       # noqa: BLE001
            r = {"lake_id": lake["id"], "error": f"{type(exc).__name__}: {exc}"}
        records.append(r)
        if "error" in r:
            print(f"FAILED {r['error']}")
        elif r.get("dry_run"):
            print(f"{r['grid'][0]}x{r['grid'][1]} ~{r['est_mb_uncompressed']} MB raw")
        else:
            total += r.get("bytes", 0)
            print(f"{'cached' if r.get('skipped') else 'fetched'} "
                  f"{r.get('bytes', 0)/1e6:.2f} MB")

    manifest = {
        "half_width_km": args.half_km,
        "resolution_m": args.res_m,
        "collection": DEM_COLLECTION,
        "note": ("Wide coarse DEM for long-range routing only. The 30 m "
                 "dem_glo30.tif remains the source for every near-lake "
                 "terrain proxy."),
        "lakes": records,
    }
    if not args.dry_run:
        write_json(pinned / "downstream_dem_manifest.json", manifest)
        print(f"\ntotal {total/1e6:.1f} MB -> "
              f"{(pinned / 'downstream_dem_manifest.json').relative_to(REPO_ROOT).as_posix()}")
    return 0 if all("error" not in r for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
