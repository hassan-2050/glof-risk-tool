"""Stage implementations, registered in plan order.

Stages 1-18 land here as they are built. Stage 0 registers the environment
self-check, which is a real gate: it fails the run if determinism guarantees
are not actually in force.
"""
from __future__ import annotations

from pathlib import Path

from src.common.config import REPO_ROOT, Config
from src.common.determinism import environment_fingerprint, offline_engaged
from src.common.io import sha256_file, write_json
from src.common.stages import stage

# Directories every later stage assumes exist. Checked, not created blindly -
# a missing data dir should be visible, not silently papered over.
REQUIRED_DIRS = (
    "src/watcher", "src/reporter", "src/eval",
    "data/pinned", "data/labels", "docs", "outputs", "config",
)


@stage(0, "scaffold", "Repository, environment, and determinism scaffolding",
       outputs=("outputs/stage00_environment.json",))
def stage00_scaffold(cfg: Config) -> dict:
    """Verify the determinism contract holds, then record it.

    This is deliberately a *gate*, not a no-op: if the offline guard is not
    engaged or a required directory is missing, reproduce fails here rather
    than producing an output that quietly means nothing.
    """
    missing = [d for d in REQUIRED_DIRS if not (REPO_ROOT / d).is_dir()]
    if missing:
        raise RuntimeError(f"required directories missing: {missing}")

    if cfg.require("determinism.enforce_offline") and not offline_engaged():
        raise RuntimeError(
            "offline guard is not engaged but config demands it; "
            "reproduce would not actually prove the no-network claim"
        )

    # Hash the inputs that define the run. If a reviewer's numbers differ from
    # ours, the first question is whether these three files match.
    inputs = {}
    for rel in ("config/config.yaml", "requirements.txt", "requirements-lock.txt"):
        p = REPO_ROOT / rel
        inputs[rel] = sha256_file(p) if p.is_file() else None

    record = {
        "stage": 0,
        "environment": environment_fingerprint(),
        "seeds": {
            "seed": cfg.require("determinism.seed"),
            "python_hash_seed": cfg.require("determinism.python_hash_seed"),
            "llm_temperature": cfg.require("llm.temperature"),
            "llm_seed": cfg.require("llm.seed"),
        },
        "frozen_clock_utc": cfg.require("determinism.frozen_utc"),
        "offline_guard_engaged": offline_engaged(),
        "input_hashes": inputs,
        "directories_present": list(REQUIRED_DIRS),
    }
    write_json(REPO_ROOT / "outputs" / "stage00_environment.json", record)
    return {"checks_passed": len(REQUIRED_DIRS) + 1, "artefacts": 1}


@stage(1, "pinned_data", "Pinned dataset and ground-truth labels",
       outputs=("outputs/stage01_dataset_validation.json",))
def stage01_pinned_data(cfg: Config) -> dict:
    """Validate the pinned dataset instead of trusting it.

    Runs on the reproduce path with the network blocked, so it also proves the
    zero-runtime-download claim: if a file is missing, this fails here rather
    than somewhere in Stage 2 with a confusing rasterio error.

    The leakage check is the one that matters. Every scene tagged event_pre is
    re-verified against the lake's cutoff date. That invariant is what makes
    the headline Thame result meaningful, so it is checked on every run rather
    than assumed from the fetch.
    """
    from src.common.io import read_json

    labels = cfg.path("labels")
    pinned = cfg.path("pinned")
    lakes_doc = read_json(labels / "lakes.json")
    cutoffs = read_json(labels / "cutoffs.json")
    manifest = read_json(pinned / "scenes_manifest.json")

    problems: list[str] = []
    leakage: list[str] = []
    missing_files = 0
    n_scenes = 0

    by_id = {l["lake_id"]: l for l in manifest["lakes"]}
    for lake in lakes_doc["lakes"]:
        lid = lake["id"]
        ml = by_id.get(lid)
        if ml is None:
            problems.append(f"{lid}: absent from scenes_manifest.json")
            continue
        if not (pinned / lid / "dem_glo30.tif").exists():
            problems.append(f"{lid}: DEM missing")
        cut = (cutoffs.get("per_lake", {}).get(lid) or {}).get("cutoff")
        for sc in ml["scenes"]:
            if not sc.get("assets"):
                continue
            n_scenes += 1
            for meta in sc["assets"].values():
                if not (REPO_ROOT / meta["path"]).exists():
                    missing_files += 1
            # Hindcast discipline, re-checked every run.
            if sc["role"] == "event_pre" and cut and sc["acquired_date"] > cut:
                leakage.append(f"{lid}/{sc['label']} acquired {sc['acquired_date']} "
                               f"is AFTER the {cut} cutoff")

    if missing_files:
        problems.append(f"{missing_files} referenced raster files are missing")
    if leakage:
        raise RuntimeError("PRE-EVENT CUTOFF VIOLATED - this invalidates the "
                           "headline result: " + "; ".join(leakage))

    # Document bundles: Stage 8 needs >= 3 distinct publishers per event.
    doc_manifest = read_json(pinned / "documents" / "MANIFEST.json")
    thin = [eid for eid, ev in doc_manifest["events"].items()
            if ev["n_distinct_publishers"] < 3]
    if thin:
        problems.append(f"events with fewer than 3 distinct publishers: {thin}")

    record = {
        "stage": 1,
        "lakes": len(lakes_doc["lakes"]),
        "scenes_with_assets": n_scenes,
        "events": doc_manifest["totals"]["events"],
        "documents": doc_manifest["totals"]["documents"],
        "cutoff_violations": leakage,
        "problems": problems,
        "pdgl_verification": read_json(labels / "pdgl_verification.json")["conclusion"],
    }
    write_json(REPO_ROOT / "outputs" / "stage01_dataset_validation.json", record)
    if problems:
        raise RuntimeError("pinned dataset validation failed: " + "; ".join(problems))
    return {"lakes": len(lakes_doc["lakes"]), "scenes": n_scenes,
            "documents": doc_manifest["totals"]["documents"], "leakage": 0}


@stage(2, "delineation", "Watcher: deterministic lake delineation",
       outputs=("outputs/stage02_delineation.json", "outputs/stage02_area_series.csv"))
def stage02_delineation(cfg: Config) -> dict:
    """Per-lake, per-date area with a QA flag attached to every number.

    No bare areas leave this stage. An area without its QA verdict is a number
    that looks equally confident whether the lake was clear or 80% frozen, and
    Stage 3's trend and Stage 7's screening decision both depend on knowing
    which.
    """
    from src.common.io import read_json, write_csv
    from src.watcher.pipeline import run_lake

    lakes_doc = read_json(cfg.path("labels") / "lakes.json")
    manifest = read_json(cfg.path("pinned") / "scenes_manifest.json")
    by_id = {l["lake_id"]: l for l in manifest["lakes"]}

    results, rows = [], []
    for lake in lakes_doc["lakes"]:
        ml = by_id.get(lake["id"])
        if ml is None:
            continue
        r = run_lake(lake, ml, cfg)
        results.append(r)
        for s in r.get("annual_series", []):
            rows.append({"lake_id": lake["id"], "lake_name": lake["name"],
                         "class": lake["class"], **s,
                         "qa_reasons": "; ".join(s.get("qa_reasons") or [])})

    write_json(REPO_ROOT / "outputs" / "stage02_delineation.json",
               {"lakes": results})
    write_csv(REPO_ROOT / "outputs" / "stage02_area_series.csv", rows,
              fieldnames=["lake_id", "lake_name", "class", "year", "date", "label",
                          "area_m2", "area_km2", "area_uncertainty_m2",
                          "qa_verdict", "open_water_fraction", "n_candidates",
                          "qa_reasons"])
    usable = sum(1 for r in rows if r["qa_verdict"] != "unusable")
    return {"lakes": len(results), "area_points": len(rows), "usable": usable}


@stage(3, "trajectory", "Watcher: multi-date trajectory + burst detection",
       outputs=("outputs/stage03_trajectory.json", "outputs/stage03_trajectory.csv"))
def stage03_trajectory(cfg: Config) -> dict:
    """Robust growth trend per lake, plus post-hoc detection of sudden drops."""
    from src.common.io import read_json, write_csv
    from src.watcher.trajectory import analyse

    lakes_doc = read_json(cfg.path("labels") / "lakes.json")
    delin = read_json(REPO_ROOT / "outputs" / "stage02_delineation.json")
    by_id = {r["lake_id"]: r for r in delin["lakes"]}

    results, rows = [], []
    for lake in lakes_doc["lakes"]:
        lr = by_id.get(lake["id"])
        if lr is None or lr.get("status") != "ok":
            continue
        a = analyse(lake, lr, cfg)
        results.append(a)
        t = a["trend"]
        rows.append({
            "lake_id": lake["id"], "class": lake["class"],
            "label_burst": lake["label_burst"],
            "n_usable": t.get("n_usable"),
            "slope_m2_per_year": t.get("theil_sen_slope_m2_per_year"),
            "relative_growth_pct_per_year": t.get("relative_growth_pct_per_year"),
            "naive_two_date_change_pct": t.get("naive_two_date_change_pct"),
            "burst_detected": a["burst_detected"],
            "n_drops": len(a["drops_detected"]),
            "n_suppressed_freeze_up": len(a["drops_suppressed"]),
            "max_drop_pct": max((d["drop_pct"] for d in a["drops_detected"]), default=None),
        })

    write_json(REPO_ROOT / "outputs" / "stage03_trajectory.json", {"lakes": results})
    write_csv(REPO_ROOT / "outputs" / "stage03_trajectory.csv", rows,
              fieldnames=["lake_id", "class", "label_burst", "n_usable",
                          "slope_m2_per_year", "relative_growth_pct_per_year",
                          "naive_two_date_change_pct", "burst_detected", "n_drops",
                          "n_suppressed_freeze_up", "max_drop_pct"])
    detected = [r["lake_id"] for r in rows if r["burst_detected"]]
    return {"lakes": len(results), "burst_detected": detected,
            "suppressed_freeze_up": sum(r["n_suppressed_freeze_up"] for r in rows)}


@stage(4, "proxies", "Watcher: dam-failure and mass-movement proxy engine",
       outputs=("outputs/stage04_proxies.json", "outputs/stage04_proxies.csv"))
def stage04_proxies(cfg: Config) -> dict:
    """Per-lake hazard record: every proxy separately queryable and cited.

    Evaluated on the last PRE-EVENT scene for hindcast lakes and the best
    annual scene otherwise, so the record answers the question that matters:
    what could have been known before the event, from free data.
    """
    from src.common.io import read_json, write_csv
    from src.watcher.pipeline import find_anchor, load_dem_on_grid
    from src.watcher.delineate import select_lake_component, water_mask
    from src.watcher.proxies import compute_all
    from src.watcher.scene import load_scene

    lakes_doc = read_json(cfg.path("labels") / "lakes.json")
    manifest = read_json(cfg.path("pinned") / "scenes_manifest.json")
    delin = read_json(REPO_ROOT / "outputs" / "stage02_delineation.json")
    by_id = {l["lake_id"]: l for l in manifest["lakes"]}
    delin_by_id = {r["lake_id"]: r for r in delin["lakes"]}

    records, rows = [], []
    for lake in lakes_doc["lakes"]:
        ml = by_id.get(lake["id"])
        if ml is None:
            continue
        scenes = {}
        for e in ml["scenes"]:
            if e.get("assets"):
                sc = load_scene(lake["id"], e)
                if sc is not None:
                    scenes[sc.label] = sc
        if not scenes:
            continue
        anchor, _ = find_anchor(scenes, cfg)

        # Which scene do we judge on? For a hindcast lake, the most recent
        # usable PRE-EVENT view - that is the evidence a screening decision
        # would have had. Never a post-event scene: the drained lake is not
        # what we were asked to assess.
        dr = delin_by_id.get(lake["id"], {})
        usable = {s["label"]: s for s in dr.get("scenes", [])
                  if s["qa"]["verdict"] != "unusable"}
        pre = [s for s in usable.values() if s["role"] == "event_pre"]
        if pre:
            chosen = max(pre, key=lambda s: (s["acquired_date"], s["area_m2"]))
        else:
            annual = [s for s in usable.values() if s["role"] == "annual"]
            if not annual:
                continue
            chosen = max(annual, key=lambda s: s["area_m2"])
        scene = scenes.get(chosen["label"])
        if scene is None:
            continue

        dem = load_dem_on_grid(lake["id"], scene)
        wm, _ = water_mask(scene, cfg)
        lake_mask, _ = select_lake_component(wm, scene, cfg, anchor_rc=anchor)
        rec = compute_all(lake, scene, dem, lake_mask, cfg)
        rec["class"] = lake["class"]
        rec["label_burst"] = lake["label_burst"]
        rec["scene_role"] = chosen["role"]
        records.append(rec)

        row = {"lake_id": lake["id"], "class": lake["class"],
               "label_burst": lake["label_burst"], "scene_date": rec["scene_date"],
               "scene_role": chosen["role"], "lake_area_m2": rec["lake_area_m2"],
               "n_fired": rec["n_fired"], "fired": "; ".join(rec["proxies_fired"])}
        for p in rec["proxies"]:
            row[p["proxy"]] = p["fired"]
        rows.append(row)

    write_json(REPO_ROOT / "outputs" / "stage04_proxies.json", {"lakes": records})
    names = sorted({p["proxy"] for r in records for p in r["proxies"]})
    write_csv(REPO_ROOT / "outputs" / "stage04_proxies.csv", rows,
              fieldnames=["lake_id", "class", "label_burst", "scene_date", "scene_role",
                          "lake_area_m2", "n_fired", *names, "fired"])
    return {"lakes": len(records),
            "mean_proxies_fired": round(sum(r["n_fired"] for r in records) / max(len(records), 1), 2)}


@stage(6, "routing", "Watcher: flow routing / indicative inundation path",
       outputs=("outputs/stage06_routing.json", "outputs/stage06_routing.csv"))
def stage06_routing(cfg: Config) -> dict:
    """MSF corridor per lake, in both flow regimes, with the disclaimer attached.

    Both regimes are run because they answer different questions: the 11 deg
    debris-flow rule bounds the near-field destructive reach, and the ~3 deg
    clear-water rule bounds how far the flood itself travels. Several Himalayan
    valleys here are gentler than 11 deg, so the debris corridor is legitimately
    empty while the clear-water one runs kilometres - reporting only one would
    hide half the answer.
    """
    from src.common.io import read_json, write_csv
    from src.watcher.delineate import select_lake_component, water_mask
    from src.watcher.pipeline import find_anchor, load_dem_on_grid
    from src.watcher.routing import laharz_cross_check, msf_corridor
    from src.watcher.scene import load_scene

    lakes_doc = read_json(cfg.path("labels") / "lakes.json")
    manifest = read_json(cfg.path("pinned") / "scenes_manifest.json")
    delin = read_json(REPO_ROOT / "outputs" / "stage02_delineation.json")
    proxies = read_json(REPO_ROOT / "outputs" / "stage04_proxies.json")
    by_id = {l["lake_id"]: l for l in manifest["lakes"]}
    delin_by_id = {r["lake_id"]: r for r in delin["lakes"]}
    prox_by_id = {r["lake_id"]: r for r in proxies["lakes"]}

    records, rows = [], []
    for lake in lakes_doc["lakes"]:
        ml = by_id.get(lake["id"])
        dr = delin_by_id.get(lake["id"])
        if ml is None or dr is None or dr.get("status") != "ok":
            continue
        scenes = {}
        for e in ml["scenes"]:
            if e.get("assets"):
                sc = load_scene(lake["id"], e)
                if sc is not None:
                    scenes[sc.label] = sc
        if not scenes:
            continue
        anchor, _ = find_anchor(scenes, cfg)
        usable = [s for s in dr["scenes"] if s["qa"]["verdict"] != "unusable"]
        if not usable:
            continue
        chosen = max(usable, key=lambda s: s["area_m2"])
        scene = scenes.get(chosen["label"])
        if scene is None:
            continue
        dem = load_dem_on_grid(lake["id"], scene)
        wm, _ = water_mask(scene, cfg)
        lake_mask, _ = select_lake_component(wm, scene, cfg, anchor_rc=anchor)
        import numpy as _np
        res = float(_np.sqrt(scene.pixel_area_m2))

        regimes = {}
        for cw, name in ((False, "debris_flow"), (True, "clearwater_flood")):
            r = msf_corridor(dem, lake_mask, res, cfg, clearwater=cw)
            r.pop("corridor", None)
            regimes[name] = r

        pr = prox_by_id.get(lake["id"], {})
        vb = next((p for p in pr.get("proxies", []) if p["proxy"] == "volume_band"), None)
        vol = (vb["value"] or {}).get("central_m3") if vb and isinstance(vb["value"], dict) else None
        rec = {"lake_id": lake["id"], "class": lake["class"],
               "label_burst": lake["label_burst"], "scene_date": chosen["acquired_date"],
               "regimes": regimes, "laharz_cross_check": laharz_cross_check(vol, cfg)}
        records.append(rec)
        for name, r in regimes.items():
            rows.append({"lake_id": lake["id"], "class": lake["class"],
                         "regime": name, "cells": r.get("cells", 0),
                         "corridor_area_km2": round(r.get("area_m2", 0) / 1e6, 4),
                         "runout_km": round(r.get("max_runout_m", 0) / 1000.0, 3),
                         "drop_m": r.get("total_drop_m"),
                         "truncated_at_window_edge": r.get("truncated_at_window_edge"),
                         "reason_if_empty": r.get("reason")})

    write_json(REPO_ROOT / "outputs" / "stage06_routing.json", {"lakes": records})
    write_csv(REPO_ROOT / "outputs" / "stage06_routing.csv", rows,
              fieldnames=["lake_id", "class", "regime", "cells", "corridor_area_km2",
                          "runout_km", "drop_m", "truncated_at_window_edge",
                          "reason_if_empty"])
    with_path = {r["lake_id"] for r in records
                 if any(g.get("cells", 0) > 0 for g in r["regimes"].values())}
    return {"lakes": len(records), "with_corridor": len(with_path),
            "thame_and_lhonak": sorted(with_path & {"thyanbo_tsho", "south_lhonak"})}
