"""Stage 1 fetcher: build data/pinned/ once, so `reproduce` never downloads.

Run:  python -m src.data.fetch            (all lakes)
      python -m src.data.fetch --lake thyanbo_tsho --dry-run

Outputs, per lake, under data/pinned/<lake_id>/:
    dem_glo30.tif                 Copernicus GLO-30, window-clipped
    <label>_<date>_B03.tif        green   10 m
    <label>_<date>_B08.tif        NIR     10 m
    <label>_<date>_B11.tif        SWIR1   20 m
    <label>_<date>_SCL.tif        scene classification 20 m (cloud/shadow/snow)

plus data/pinned/scenes_manifest.json recording, for every scene, the STAC id,
acquisition datetime, cloud cover, role, whether it is pre- or post-event, and
a sha256 of each written file.

Design notes worth knowing before editing:

* Windowed reads, not whole scenes. A Sentinel-2 tile is ~1 GB; we need ~5 km
  around a lake. rasterio reads only the relevant COG blocks over HTTP, which
  turns a 100 GB download into ~90 MB.

* The manifest is the contract with Stage 2. It carries acquisition dates
  (a Stage 1 pass criterion) and the pre/post-event tag that Stage 7 relies on
  to avoid leakage. Nothing downstream re-derives dates from filenames.

* Resumable. Existing files are skipped, so a dropped connection costs one
  scene, not the whole run.

* The cutoff is enforced HERE, at acquisition time, not just at scoring time.
  A scene later than a lake's cutoff physically cannot be written with an
  event_pre role - the request carries the cutoff as its end date, and the
  assertion below re-checks it. Defence in depth for the one bug that would
  invalidate the headline result.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import planetary_computer as pc
import pystac_client
import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds

from src.common.config import REPO_ROOT, load_config
from src.common.io import read_json, sha256_file, write_json
from src.data.selection import (MIN_CLOUD_QA_HARD, SceneRequest, qa_hard_request,
                                requests_for_lake)

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
S2_COLLECTION = "sentinel-2-l2a"
DEM_COLLECTION = "cop-dem-glo-30"

# B03 green + B08 NIR give NDWI; B11 SWIR1 gives MNDWI and the NIR/SWIR1
# glacier-ice discriminator; SCL carries ESA's own cloud/shadow/snow classes,
# which Stage 2 uses as one input to its QA flag (not as the whole answer -
# SCL is known to under-flag terrain shadow, the dominant false positive here).
S2_ASSETS = ("B03", "B08", "B11", "SCL")

# GDAL tuning for remote COG reads. Without these every open() costs an extra
# directory listing and HEAD request per file.
GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_USE_HEAD="NO",
    GDAL_HTTP_MAX_RETRY="4",
    GDAL_HTTP_RETRY_DELAY="2",
    VSI_CACHE="TRUE",
)


def bbox_for(lake: dict, half_km: float) -> tuple[float, float, float, float]:
    """Geographic bbox around a lake centroid.

    Longitude degrees shrink with latitude, so the half-width is corrected by
    cos(lat); without it a 5 km box at 28 N would be ~4.4 km wide.
    """
    lat, lon = lake["lat"], lake["lon"]
    dlat = half_km / 110.574
    dlon = half_km / (111.320 * np.cos(np.radians(lat)))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def _open_catalog() -> pystac_client.Client:
    return pystac_client.Client.open(STAC_URL, modifier=pc.sign_inplace)


def search_scenes(cat, bbox, req: SceneRequest) -> list:
    """Candidate scenes for one request, cheapest-cloud first."""
    search = cat.search(
        collections=[S2_COLLECTION],
        bbox=list(bbox),
        datetime=f"{req.start.isoformat()}/{req.end.isoformat()}",
    )
    items = list(search.items())
    for it in items:
        it.properties.setdefault("eo:cloud_cover", 100.0)
    if req.role == "qa_hard":
        # Want the WORST scene here, and only if it is genuinely bad enough to
        # be a real test.
        items = [i for i in items if i.properties["eo:cloud_cover"] >= MIN_CLOUD_QA_HARD]
        items.sort(key=lambda i: -i.properties["eo:cloud_cover"])
        return items
    if req.role == "event_pre":
        # Deliberately NOT filtered on tile cloud - see N_CANDIDATES_EVENT in
        # selection.py. Ordered by recency, because the closest view to the
        # decision date is the one an officer would actually have used.
        items.sort(key=lambda i: -i.datetime.timestamp())
        return items
    if req.role == "event_post":
        items.sort(key=lambda i: i.datetime.timestamp())
        return items
    items = [i for i in items if i.properties["eo:cloud_cover"] <= req.max_cloud]
    items.sort(key=lambda i: (i.properties["eo:cloud_cover"], i.datetime.timestamp()))
    return items


def clip_asset(item, asset_key: str, bbox, out_path: Path) -> dict | None:
    """Read the bbox window from one COG asset and write a small GeoTIFF."""
    asset = item.assets.get(asset_key)
    if asset is None:
        return None
    with rasterio.Env(**GDAL_ENV):
        with rasterio.open(asset.href) as src:
            tf = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
            xs, ys = tf.transform([bbox[0], bbox[2]], [bbox[1], bbox[3]])
            win = from_bounds(min(xs), min(ys), max(xs), max(ys), src.transform)
            win = win.round_offsets().round_lengths()
            if win.width < 1 or win.height < 1:
                return None
            data = src.read(1, window=win, boundless=True,
                            fill_value=src.nodata if src.nodata is not None else 0)
            profile = src.profile.copy()
            profile.update(
                height=data.shape[0], width=data.shape[1],
                transform=src.window_transform(win),
                # deflate + horizontal predictor roughly halves these on
                # smoothly-varying mountain imagery.
                compress="deflate", predictor=2, tiled=True,
                blockxsize=256, blockysize=256, driver="GTiff",
            )
            profile.pop("blockysize", None) if data.shape[0] < 256 else None
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(data, 1)
    return {"shape": list(data.shape), "dtype": str(data.dtype),
            "crs": str(profile["crs"]), "sha256": sha256_file(out_path)}


def fetch_dem(cat, bbox, out_path: Path) -> dict | None:
    """Copernicus GLO-30 window. Mosaics tiles when the box straddles two."""
    if out_path.exists():
        return {"skipped": True, "sha256": sha256_file(out_path)}
    items = list(cat.search(collections=[DEM_COLLECTION], bbox=list(bbox)).items())
    if not items:
        return None
    # GLO-30 tiles are 1x1 degree; a 5 km window touches at most 4.
    with rasterio.Env(**GDAL_ENV):
        from rasterio.merge import merge
        srcs = [rasterio.open(i.assets["data"].href) for i in items]
        try:
            mosaic, transform = merge(srcs, bounds=(bbox[0], bbox[1], bbox[2], bbox[3]))
            profile = srcs[0].profile.copy()
            profile.update(height=mosaic.shape[1], width=mosaic.shape[2],
                           transform=transform, count=1, compress="deflate",
                           predictor=3, tiled=True, driver="GTiff")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(mosaic[0], 1)
        finally:
            for s in srcs:
                s.close()
    return {"tiles": [i.id for i in items], "shape": list(mosaic.shape[1:]),
            "sha256": sha256_file(out_path)}


def fetch_lake(cat, lake: dict, cutoffs: dict, half_km: float, pinned: Path,
               dry_run: bool, extra_qa: bool) -> dict:
    lid = lake["id"]
    bbox = bbox_for(lake, half_km)
    out_dir = pinned / lid
    record: dict = {"lake_id": lid, "bbox_wgs84": list(bbox), "scenes": [], "dem": None}

    reqs = requests_for_lake(lake, cutoffs)
    if extra_qa:
        reqs.append(qa_hard_request(lid))

    for req in reqs:
        cands = search_scenes(cat, bbox, req)
        if not cands:
            record["scenes"].append({
                "role": req.role, "label": req.label, "status": "no_scene_found",
                "window": [req.start.isoformat(), req.end.isoformat()],
                "max_cloud": req.max_cloud, "reason": req.reason,
            })
            print(f"    {req.label:<16} MISSING (no scene "
                  f"{req.start}..{req.end} under {req.max_cloud}% cloud)")
            continue
        for rank, item in enumerate(cands[:req.n_candidates]):
            acq = item.datetime.date()

            # Leakage guard, re-checked at write time rather than trusted from
            # the search window. This assertion protects the headline claim.
            if req.cutoff is not None and acq > req.cutoff:
                raise AssertionError(
                    f"{lid}: refusing to write {item.id} ({acq}) as {req.role}; "
                    f"it is AFTER the {req.cutoff} cutoff. This would leak "
                    f"post-event information into the screening decision."
                )

            # Candidate 0 keeps the bare label so downstream code has an
            # unambiguous default; the rest are suffixed.
            label = req.label if rank == 0 else f"{req.label}_c{rank}"
            entry = {
                "role": req.role, "label": label, "stac_id": item.id,
                "acquired": item.datetime.isoformat(),
                "acquired_date": acq.isoformat(),
                "tile_cloud_cover_pct": round(float(item.properties["eo:cloud_cover"]), 2),
                "platform": item.properties.get("platform"),
                "mgrs_tile": item.properties.get("s2:mgrs_tile"),
                "is_post_event": req.role == "event_post",
                "candidate_rank": rank,
                "selection_reason": req.reason,
                "candidates_available": len(cands),
                "assets": {},
            }
            if dry_run:
                record["scenes"].append(entry)
                print(f"    {label:<18} {acq} tile-cc={entry['tile_cloud_cover_pct']:5.1f}%  {item.id[:28]}")
                continue

            for key in S2_ASSETS:
                path = out_dir / f"{label}_{acq.isoformat()}_{key}.tif"
                if path.exists():
                    entry["assets"][key] = {"path": path.relative_to(REPO_ROOT).as_posix(),
                                            "sha256": sha256_file(path), "skipped": True}
                    continue
                try:
                    meta = clip_asset(item, key, bbox, path)
                except Exception as exc:  # noqa: BLE001 - one bad asset must not kill the run
                    print(f"      ! {key} failed: {type(exc).__name__}: {exc}")
                    meta = None
                if meta:
                    meta["path"] = path.relative_to(REPO_ROOT).as_posix()
                    entry["assets"][key] = meta
            record["scenes"].append(entry)
            n = len(entry["assets"])
            print(f"    {label:<18} {acq} tile-cc={entry['tile_cloud_cover_pct']:5.1f}%  {n}/{len(S2_ASSETS)} bands")

    if not dry_run:
        try:
            record["dem"] = fetch_dem(cat, bbox, out_dir / "dem_glo30.tif")
            print(f"    {'dem_glo30':<16} {record['dem']['shape'] if record['dem'] else 'MISSING'}")
        except Exception as exc:  # noqa: BLE001
            print(f"    dem_glo30 failed: {type(exc).__name__}: {exc}")
    return record


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lake", action="append", help="limit to these lake ids")
    p.add_argument("--dry-run", action="store_true",
                   help="resolve scenes and print the plan without downloading")
    p.add_argument("--qa-lake", default="thyanbo_tsho",
                   help="lake that also gets a deliberately cloud-affected scene")
    args = p.parse_args(argv)

    cfg = load_config()
    pinned = cfg.path("pinned")
    labels = cfg.path("labels")
    lakes_doc = read_json(labels / "lakes.json")
    cutoffs = read_json(labels / "cutoffs.json")
    half_km = lakes_doc["window_half_width_km"]

    lakes = lakes_doc["lakes"]
    if args.lake:
        wanted = set(args.lake)
        lakes = [l for l in lakes if l["id"] in wanted]
        missing = wanted - {l["id"] for l in lakes}
        if missing:
            print(f"unknown lake ids: {sorted(missing)}", file=sys.stderr)
            return 2

    cat = _open_catalog()
    records = []
    for i, lake in enumerate(lakes, 1):
        print(f"[{i}/{len(lakes)}] {lake['id']}  ({lake['name']})")
        records.append(fetch_lake(cat, lake, cutoffs, half_km, pinned,
                                  args.dry_run, extra_qa=lake["id"] == args.qa_lake))

    manifest = {
        "generated_by": "src.data.fetch",
        "stac_endpoint": STAC_URL,
        "collections": {"imagery": S2_COLLECTION, "dem": DEM_COLLECTION},
        "assets_per_scene": list(S2_ASSETS),
        "window_half_width_km": half_km,
        "dry_run": args.dry_run,
        "lakes": records,
    }
    out = pinned / ("scenes_manifest_dryrun.json" if args.dry_run else "scenes_manifest.json")
    write_json(out, manifest)
    print(f"\nmanifest -> {out.relative_to(REPO_ROOT).as_posix()}")

    got = sum(1 for r in records for s in r["scenes"] if s.get("stac_id"))
    miss = sum(1 for r in records for s in r["scenes"] if not s.get("stac_id"))
    print(f"scenes resolved: {got}   missing: {miss}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
