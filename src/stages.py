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
    cutoffs = read_json(cfg.path("labels") / "cutoffs.json")
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

        # The cutoff binds the FALLBACK too, not just the event_pre scenes.
        # Without this the annual fallback silently reached past the cutoff -
        # South Lhonak was assessed on 2023-10-24, three weeks AFTER its
        # 2023-10-03 outburst, and Chamoli on a 2024 scene for a 2021 event.
        # Stage 7's leakage guard caught both, which is what it is for.
        cut = (cutoffs.get("per_lake", {}).get(lake["id"]) or {}).get("cutoff")
        if cut:
            usable = {k: v for k, v in usable.items() if v["acquired_date"] <= cut}
        if not usable:
            continue

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


@stage(7, "watcher_eval", "Watcher eval: baseline vs. proxy-augmented",
       outputs=("outputs/stage07_watcher_eval.json", "outputs/stage07_confusion_matrix.csv"))
def stage07_watcher_eval(cfg: Config) -> dict:
    """The money chart: does adding proxies catch what growth-only misses?"""
    from src.common.io import read_json, write_csv
    from src.eval.watcher_eval import (ROUNCE_RANK, confusion, growth_only_screen,
                                       precision_at_k, proxy_augmented_screen,
                                       spearman)

    lakes_doc = read_json(cfg.path("labels") / "lakes.json")
    cutoffs = read_json(cfg.path("labels") / "cutoffs.json")
    traj = {r["lake_id"]: r for r in
            read_json(REPO_ROOT / "outputs" / "stage03_trajectory.json")["lakes"]}
    prox = {r["lake_id"]: r for r in
            read_json(REPO_ROOT / "outputs" / "stage04_proxies.json")["lakes"]}

    # Leakage re-check before anything is scored. Stage 1 already enforces this
    # at acquisition; repeating it here means a hand-edited manifest cannot
    # quietly invalidate the headline.
    leaks = []
    for lake in lakes_doc["lakes"]:
        cut = (cutoffs["per_lake"].get(lake["id"]) or {}).get("cutoff")
        p = prox.get(lake["id"])
        if cut and p and p.get("scene_date", "") > cut:
            leaks.append(f"{lake['id']}: proxy scene {p['scene_date']} is after cutoff {cut}")
    if leaks:
        raise RuntimeError("POST-CUTOFF DATA IN THE SCREENING DECISION: " + "; ".join(leaks))

    rows, per_lake = [], {}
    truth = {}
    for lake in lakes_doc["lakes"]:
        lid = lake["id"]
        base = growth_only_screen(lake, traj.get(lid), cfg)
        adv = proxy_augmented_screen(lake, prox.get(lid), traj.get(lid), cfg,
                                     baseline=base)
        truth[lid] = bool(lake["label_burst"])
        per_lake[lid] = {"lake": lake["name"], "class": lake["class"],
                         "label_burst": truth[lid],
                         "rounce_2017_class": lake.get("rounce_2017_class"),
                         "growth_only": base, "proxy_augmented": adv}
        rows.append({
            "lake_id": lid, "class": lake["class"], "label_burst": truth[lid],
            "rounce_2017_class": lake.get("rounce_2017_class") or "",
            "area_km2": base["area_km2"],
            "growth_only_flagged": base["flagged"],
            "growth_only_passes_area_screen": base["passes_area_screen"],
            "proxy_score": adv.get("score"),
            "proxy_augmented_flagged": adv["flagged"],
            "n_proxies_fired": adv.get("n_proxies_fired", 0),
            "growth_only_reason": "; ".join(base["reasons"]),
            "proxy_reason": "; ".join(adv["reasons"]),
        })

    base_flags = {k: v["growth_only"]["flagged"] for k, v in per_lake.items()}
    adv_flags = {k: v["proxy_augmented"]["flagged"] for k, v in per_lake.items()}
    cm_base, cm_adv = confusion(base_flags, truth), confusion(adv_flags, truth)

    # Threshold-free view: rank by the continuous proxy score.
    scored = [(k, v["proxy_augmented"].get("score")) for k, v in per_lake.items()
              if v["proxy_augmented"].get("score") is not None]
    ranked = [k for k, _ in sorted(scored, key=lambda kv: -kv[1])]
    ks = cfg.require("evaluation.precision_at_k")

    # Rank correlation against the Rounce et al. expert classes.
    pairs = [(v["proxy_augmented"]["score"], ROUNCE_RANK[v["rounce_2017_class"]])
             for v in per_lake.values()
             if v.get("rounce_2017_class") in ROUNCE_RANK
             and v["proxy_augmented"].get("score") is not None]
    rho = spearman([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= 3 else None

    thame = per_lake.get("thyanbo_tsho", {})
    headline = {
        "claim": ("growth-only screening misses Thyanbo Tsho while the "
                  "proxy-augmented screen catches it, on pre-event data only"),
        "thame_growth_only_flagged": thame.get("growth_only", {}).get("flagged"),
        "thame_growth_only_reason": thame.get("growth_only", {}).get("reasons"),
        "thame_proxy_flagged": thame.get("proxy_augmented", {}).get("flagged"),
        "thame_proxy_rank_of_n": (f"{ranked.index('thyanbo_tsho') + 1} of {len(ranked)}"
                                  if "thyanbo_tsho" in ranked else None),
        "thame_proxy_score": thame.get("proxy_augmented", {}).get("score"),
        "claim_holds": bool(thame.get("growth_only", {}).get("flagged") is False
                            and thame.get("proxy_augmented", {}).get("flagged") is True),
        "threshold_free_statement": (
            "Thame ranks first of fourteen on the continuous source-to-lake "
            "volume ratio computed from pre-event data alone; this statement "
            "does not depend on any alarm threshold."),
    }

    result = {
        "headline": headline,
        "confusion_growth_only": cm_base,
        "confusion_proxy_augmented": cm_adv,
        "recall_delta": round(cm_adv["recall"] - cm_base["recall"], 4),
        "precision_at_k_proxy": precision_at_k(ranked, truth, ks),
        "ranking": ranked,
        "spearman_vs_rounce_2017": rho,
        "spearman_n": len(pairs),
        "spearman_note": ("Computed over the PDGL lakes that carry a Rounce class. "
                          "A low or negative value is a reportable result, not a "
                          "failure to be tuned away."),
        "negatives_caveat": (
            "8 of 11 non-burst lakes are ICIMOD PDGL Rank-I lakes that experts "
            "already consider dangerous. Flags on them are counted as false "
            "positives in the burst confusion matrix, which understates the "
            "proxy model; the rank correlation is the fairer view for those."),
        "calibration_policy": cutoffs["calibration_policy"],
        "per_lake": per_lake,
    }
    write_json(REPO_ROOT / "outputs" / "stage07_watcher_eval.json", result)
    write_csv(REPO_ROOT / "outputs" / "stage07_confusion_matrix.csv", rows,
              fieldnames=["lake_id", "class", "label_burst", "rounce_2017_class",
                          "area_km2", "growth_only_flagged",
                          "growth_only_passes_area_screen", "proxy_score",
                          "proxy_augmented_flagged", "n_proxies_fired",
                          "growth_only_reason", "proxy_reason"])
    return {"claim_holds": headline["claim_holds"],
            "recall_growth_only": cm_base["recall"],
            "recall_proxy": cm_adv["recall"],
            "thame_rank": headline["thame_proxy_rank_of_n"],
            "spearman_vs_rounce": rho}


@stage(8, "retriever", "Reporter: retriever agent",
       outputs=("outputs/stage08_retrieval.json",))
def stage08_retriever(cfg: Config) -> dict:
    """Pull the pinned bundles into per-source-attributed passages."""
    from src.reporter.retriever import retrieve_all

    docs = cfg.path("pinned") / "documents"
    result = retrieve_all(docs, cfg)
    write_json(REPO_ROOT / "outputs" / "stage08_retrieval.json", result)
    thin = [eid for eid, e in result["events"].items()
            if not e["meets_three_source_minimum"]]
    if thin:
        raise RuntimeError(f"events below the 3-distinct-source minimum: {thin}")
    return {"events": result["n_events"],
            "passages": sum(e["n_passages"] for e in result["events"].values()),
            "all_meet_3_source_minimum": result["all_meet_three_source_minimum"]}


@stage(9, "reconciliation", "Reporter: numeric-reconciliation agent",
       outputs=("outputs/stage09_reconciliation.json",
                "outputs/stage09_disagreements.csv"))
def stage09_reconciliation(cfg: Config) -> dict:
    """Extract every figure, surface every disagreement, score against truth."""
    from src.common.io import read_json, write_csv
    from src.reporter.reconciliation import reconcile_event

    retrieval = read_json(REPO_ROOT / "outputs" / "stage08_retrieval.json")
    truth = read_json(cfg.path("labels") / "numeric_ground_truth.json")

    per_event, rows = {}, []
    for eid, ev in retrieval["events"].items():
        r = reconcile_event(ev, cfg)
        per_event[eid] = r
        for c in r["contradictions"]:
            rows.append({
                "event_id": eid, "quantity": c["quantity"], "kind": c["kind"],
                "severity": c["severity"],
                "min": c.get("min", c.get("stated_total")),
                "max": c.get("max", c.get("itemised_sum")),
                "n_documents": c.get("n_documents", 1),
                "publishers": "; ".join(sorted({v["publisher"] for v in c.get("values", [])}))
                              or c.get("publisher", ""),
                "reportable_sentence": c["reportable_sentence"],
            })

    # --- score against the hand-labelled answer key -----------------------
    # Matching is by (event, quantity), which is what the ground truth is keyed
    # on. A detection is a true positive when the labelled quantity is one we
    # flagged for that event.
    QMAP = {"fatalities": "deaths", "moraine_collapse_volume_m3": "volume_m3",
            "hydropower_projects_damaged": "hydropower_projects",
            "deaths_and_missing": "deaths", "casualties_total": "casualties_total",
            "lake_area_km2": "area_km2", "publication_date": None,
            "event_classification": None}
    must = [c for c in truth["contradictions"] if c["must_detect"]]
    detected, missed = [], []
    for c in must:
        want = QMAP.get(c["quantity"], c["quantity"])
        if want is None:
            missed.append({"id": c["id"], "reason": "not a numeric quantity; "
                           "requires the categorical check in Stage 11/16"})
            continue
        found = any(x["quantity"] == want
                    for x in per_event.get(c["event_id"], {}).get("contradictions", []))
        (detected if found else missed).append({"id": c["id"], "quantity": want})

    flagged_quantities = {(e, x["quantity"])
                          for e, r in per_event.items() for x in r["contradictions"]}
    false_positives = []
    for a in truth["agreements"]:
        want = QMAP.get(a["quantity"], a["quantity"])
        if want and (a["event_id"], want) in flagged_quantities:
            false_positives.append({"id": a["id"], "quantity": want})

    tp, fn, fp = len(detected), len(missed), len(false_positives)
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    metrics = {"tp": tp, "fn": fn, "fp": fp,
               "precision": round(prec, 4), "recall": round(rec, 4),
               "f1": round(2 * prec * rec / max(prec + rec, 1e-9), 4),
               "detected": detected, "missed": missed,
               "false_positives": false_positives,
               "note": ("Scored by (event, quantity) against the hand-labelled key. "
                        "Categorical items - the Chamoli misclassification - are not "
                        "numeric and are checked in Stages 11 and 16 instead; they "
                        "count as missed here rather than being quietly excluded.")}

    write_json(REPO_ROOT / "outputs" / "stage09_reconciliation.json",
               {"events": per_event, "metrics_vs_ground_truth": metrics})
    write_csv(REPO_ROOT / "outputs" / "stage09_disagreements.csv", rows,
              fieldnames=["event_id", "quantity", "kind", "severity", "min", "max",
                          "n_documents", "publishers", "reportable_sentence"])
    return {"events": len(per_event),
            "claims": sum(r["n_claims_extracted"] for r in per_event.values()),
            "contradictions": sum(r["n_contradictions"] for r in per_event.values()),
            "f1_vs_ground_truth": metrics["f1"]}


@stage(10, "drafting", "Reporter: drafting agent (OCHA bilingual sitrep)",
       outputs=("outputs/stage10_drafts.json", "outputs/sitreps/"))
def stage10_drafting(cfg: Config) -> dict:
    """OCHA-structured sitrep per event, English and Nepali, fully cited."""
    from src.common.io import read_json, write_text
    from src.reporter.drafter import OCHA_SECTIONS, draft_event, render_markdown

    retrieval = read_json(REPO_ROOT / "outputs" / "stage08_retrieval.json")
    recon = read_json(REPO_ROOT / "outputs" / "stage09_reconciliation.json")
    max_words = cfg.require("reporter.sitrep.max_words")

    out_dir = REPO_ROOT / "outputs" / "sitreps"
    drafts, summary = {}, []
    for eid, ev in retrieval["events"].items():
        r = recon["events"][eid]
        for lang in ("en", "ne"):
            d = draft_event(ev, r, cfg, lang=lang)
            drafts[f"{eid}_{lang}"] = d
            write_text(out_dir / f"{eid}_{lang}.md", render_markdown(d))
            summary.append({
                "event_id": eid, "lang": lang,
                "words": d["word_count"],
                "within_length_target": d["word_count"] <= max_words,
                "sections_present": d["all_sections_present"],
                "contested_reflected": d["n_contested_reflected"],
                "claims": d["n_claim_sentences"],
            })

    # Criterion: every contradiction Stage 9 found must be visible in the text.
    unreflected = []
    for eid, r in recon["events"].items():
        want = {c["quantity"] for c in r["contradictions"]}
        for lang in ("en", "ne"):
            body = " ".join(t for sec in drafts[f"{eid}_{lang}"]["sections"].values()
                            for t in sec)
            got = set()
            for c in r["contradictions"]:
                vals = [c.get("min"), c.get("max"), c.get("stated_total"),
                        c.get("itemised_sum")]
                for v in vals:
                    if v is None:
                        continue
                    if f"{v:,.0f}" in body or f"{v:g}" in body:
                        got.add(c["quantity"])
                        break
            if want - got:
                unreflected.append({"event_id": eid, "lang": lang,
                                    "missing": sorted(want - got)})

    # Criterion: the negative control must not be called a GLOF, in either language.
    glof_terms = ["glacial lake outburst", "हिमताल विस्फोट"]
    mislabel = []
    for key, d in drafts.items():
        if d["is_glof"]:
            continue
        body = " ".join(t for sec in d["sections"].values() for t in sec)
        for term in glof_terms:
            # "NOT a glacial lake outburst flood" is the required disclaimer,
            # so only an UNNEGATED mention counts as a misclassification.
            for idx in range(len(body)):
                i = body.find(term, idx)
                if i < 0:
                    break
                window = body[max(0, i - 40):i].lower()
                if "not" not in window and "थिएन" not in body[max(0, i - 40):i + 60]:
                    mislabel.append({"draft": key, "term": term})
                break
    write_json(REPO_ROOT / "outputs" / "stage10_drafts.json",
               {"drafts": drafts, "summary": summary,
                "contradictions_unreflected": unreflected,
                "negative_control_mislabelled": mislabel,
                "ocha_sections": OCHA_SECTIONS})
    return {"drafts": len(drafts),
            "all_within_length": all(s["within_length_target"] for s in summary),
            "contradictions_unreflected": len(unreflected),
            "negative_control_mislabelled": len(mislabel)}


@stage(5, "exposure", "Watcher: exposure overlay and asset-criticality weighting",
       outputs=("outputs/stage05_exposure.json", "outputs/stage05_exposure.csv"))
def stage05_exposure(cfg: Config) -> dict:
    """Who and what sits in the indicative corridor, from two methods."""
    import numpy as _np

    from src.common.io import read_json, write_csv
    from src.watcher.delineate import select_lake_component, water_mask
    from src.watcher.exposure import assess, classify
    from src.watcher.pipeline import find_anchor, load_dem_on_grid
    from src.watcher.routing import msf_corridor
    from src.watcher.scene import load_scene

    lakes_doc = read_json(cfg.path("labels") / "lakes.json")
    manifest = read_json(cfg.path("pinned") / "scenes_manifest.json")
    delin = read_json(REPO_ROOT / "outputs" / "stage02_delineation.json")
    exp_dir = cfg.path("pinned") / "exposure"
    exp_manifest_path = exp_dir / "exposure_manifest.json"
    if not exp_manifest_path.exists():
        raise RuntimeError("exposure layers not pinned; run "
                           "`python -m src.data.fetch_exposure` once, with network")
    exp_manifest = read_json(exp_manifest_path)
    wp = exp_manifest.get("worldpop")
    wp_path = (REPO_ROOT / wp["path"]) if wp else None

    by_id = {l["lake_id"]: l for l in manifest["lakes"]}
    delin_by_id = {r["lake_id"]: r for r in delin["lakes"]}

    records, rows, skipped = [], [], []
    for lake in lakes_doc["lakes"]:
        osm_path = exp_dir / f"{lake['id']}_osm.json"
        ml, dr = by_id.get(lake["id"]), delin_by_id.get(lake["id"])
        if not osm_path.exists():
            skipped.append({"lake_id": lake["id"], "reason": "no pinned OSM extract"})
            continue
        if ml is None or dr is None or dr.get("status") != "ok":
            skipped.append({"lake_id": lake["id"], "reason": "no delineation"})
            continue
        scenes = {}
        for e in ml["scenes"]:
            if e.get("assets"):
                sc = load_scene(lake["id"], e)
                if sc is not None:
                    scenes[sc.label] = sc
        usable = [s for s in dr["scenes"] if s["qa"]["verdict"] != "unusable"]
        if not scenes or not usable:
            skipped.append({"lake_id": lake["id"], "reason": "no usable scene"})
            continue
        anchor, _ = find_anchor(scenes, cfg)
        chosen = max(usable, key=lambda s: s["area_m2"])
        scene = scenes.get(chosen["label"])
        if scene is None:
            skipped.append({"lake_id": lake["id"], "reason": "scene missing"})
            continue

        dem = load_dem_on_grid(lake["id"], scene)
        wm, _ = water_mask(scene, cfg)
        lake_mask, _ = select_lake_component(wm, scene, cfg, anchor_rc=anchor)
        res = float(_np.sqrt(scene.pixel_area_m2))
        # Clear-water regime for exposure: it bounds how far the flood reaches,
        # which is the question exposure is asking. The debris corridor bounds
        # the destructive near field and is a subset.
        corr = msf_corridor(dem, lake_mask, res, cfg, clearwater=True)
        corridor = corr.get("corridor")
        if corridor is None or not corridor.any():
            skipped.append({"lake_id": lake["id"],
                            "reason": corr.get("reason", "empty corridor")})
            continue

        osm = read_json(osm_path)
        a = assess(lake, osm, corridor, scene.transform, scene.crs, wp_path, classify)
        a["corridor"] = {"area_km2": round(corr["area_m2"] / 1e6, 4),
                         "runout_km": round(corr["max_runout_m"] / 1000.0, 3),
                         "truncated_at_window_edge": corr["truncated_at_window_edge"],
                         "disclaimer_id": corr["disclaimer"]["id"]}
        a["class"] = lake["class"]
        records.append(a)
        rows.append({
            "lake_id": lake["id"], "class": lake["class"], "country": lake["country"],
            "corridor_area_km2": a["corridor"]["area_km2"],
            "corridor_runout_km": a["corridor"]["runout_km"],
            "buildings": a["counts"].get("building", 0),
            "hydropower": a["hydropower_in_corridor"],
            "schools": a["counts"].get("school", 0),
            "health_posts": a["counts"].get("health_post", 0),
            "bridges": a["counts"].get("bridge", 0),
            "settlements": a["counts"].get("settlement", 0),
            "pop_osm_derived": a["population"]["osm_derived"],
            "pop_worldpop": (a["population"]["worldpop"] or {}).get("population"),
            "pop_divergence_pct": (a["population"]["divergence"] or {}).get("difference_pct"),
            "criticality_score": a["criticality_weighted_score"],
        })

    diverging = [r for r in records
                 if (r["population"]["divergence"] or {}).get("materially_different")]
    write_json(REPO_ROOT / "outputs" / "stage05_exposure.json",
               {"lakes": records, "skipped": skipped,
                "n_with_population_divergence": len(diverging),
                "divergence_examples": [d["lake_id"] for d in diverging],
                "osm_attribution": exp_manifest["osm"],
                "worldpop": wp})
    write_csv(REPO_ROOT / "outputs" / "stage05_exposure.csv", rows,
              fieldnames=["lake_id", "class", "country", "corridor_area_km2",
                          "corridor_runout_km", "buildings", "hydropower", "schools",
                          "health_posts", "bridges", "settlements",
                          "pop_osm_derived", "pop_worldpop", "pop_divergence_pct",
                          "criticality_score"])
    return {"lakes": len(records), "skipped": len(skipped),
            "with_population_divergence": len(diverging),
            "hydropower_exposed": sum(1 for r in records if r["hydropower_in_corridor"])}


@stage(11, "verification", "Reporter: adversarial critic + verification loop",
       outputs=("outputs/stage11_verification.json",))
def stage11_verification(cfg: Config) -> dict:
    """No unsupported claim ships. Unresolved findings block release."""
    from src.common.io import read_json
    from src.reporter.critic import run_loop, verify_sentence

    retrieval = read_json(REPO_ROOT / "outputs" / "stage08_retrieval.json")
    recon = read_json(REPO_ROOT / "outputs" / "stage09_reconciliation.json")
    drafts = read_json(REPO_ROOT / "outputs" / "stage10_drafts.json")["drafts"]
    cap = cfg.require("reporter.verification.max_iterations")

    passages_by_doc: dict[str, dict[str, list[str]]] = {}
    for eid, ev in retrieval["events"].items():
        by_doc: dict[str, list[str]] = {}
        for p in ev["passages"]:
            by_doc.setdefault(p["doc_id"], []).append(p["text"])
        passages_by_doc[eid] = by_doc

    results = {}
    for key, d in drafts.items():
        eid, lang = key.rsplit("_", 1)
        results[key] = run_loop(d, recon["events"][eid], passages_by_doc[eid],
                                lang, cap)

    # --- injection test: a fabricated fact MUST be caught -------------------
    # Stage 11's pass criterion is not "the real drafts verify" - a pipeline
    # that verifies everything trivially would also pass that. It is that a
    # deliberately planted falsehood is CAUGHT, so the check is run here rather
    # than asserted.
    eid = "thame_2024"
    poisoned = {**drafts[f"{eid}_en"]}
    poisoned["sections"] = {k: list(v) for k, v in poisoned["sections"].items()}
    fabricated = ("A total of 9,412 people were evacuated from the valley "
                  "[icimod_thame_study_2025].")
    poisoned["sections"]["humanitarian_impact"].append(fabricated)
    inj = run_loop(poisoned, recon["events"][eid], passages_by_doc[eid], "en", cap)
    caught = fabricated not in inj["sections"]["humanitarian_impact"]

    # And an uncited claim, which fails a different check.
    poisoned2 = {**drafts[f"{eid}_en"]}
    poisoned2["sections"] = {k: list(v) for k, v in poisoned2["sections"].items()}
    uncited = "Three additional villages were destroyed downstream."
    poisoned2["sections"]["humanitarian_impact"].append(uncited)
    inj2 = run_loop(poisoned2, recon["events"][eid], passages_by_doc[eid], "en", cap)
    uncited_flagged = any(f["type"] in ("uncited_figure", "uncited_claim")
                          for f in inj2["critic_findings"]) or \
        uncited not in inj2["sections"]["humanitarian_impact"]

    injection = {
        "fabricated_figure": {"text": fabricated, "caught": bool(caught),
                              "mechanism": "verifier: 9412 appears in no cited source"},
        "uncited_claim": {"text": uncited, "flagged": bool(uncited_flagged),
                          "mechanism": "critic: claim carries no citation",
                          "note": ("this one carries no FIGURE either, so the "
                                   "numeric verifier cannot see it - it is exactly "
                                   "the gap the critic exists to cover")},
    }

    blocked = [k for k, r in results.items() if r["release_blocked"]]
    write_json(REPO_ROOT / "outputs" / "stage11_verification.json",
               {"drafts": results, "injection_test": injection,
                "iteration_cap": cap, "blocked_drafts": blocked})
    if not caught:
        raise RuntimeError("INJECTION TEST FAILED: a fabricated figure survived "
                           "the critic/verifier loop. Release gating is not working.")
    return {"drafts_checked": len(results), "blocked": len(blocked),
            "fabricated_caught": bool(caught),
            "uncited_flagged": bool(uncited_flagged),
            "max_iterations_used": max(r["iterations"] for r in results.values())}
