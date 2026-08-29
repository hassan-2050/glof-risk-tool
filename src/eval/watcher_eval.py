"""Stage 7: growth-only baseline vs. proxy-augmented screening, same cases.

The claim under test is narrow and falsifiable: a screen that looks only at
lake area and its growth misses Thyanbo Tsho, and a screen that also reasons
about dam geometry and trigger terrain does not.

Three disciplines make the comparison fair rather than flattering:

* The baseline is the REAL published screen, not a strawman. Rounce et al.
  (2017) assessed Nepal's lakes larger than 0.1 km2; that threshold is the
  baseline, unchanged, and it is applied to our own measured areas so both
  models see identical inputs.

* Both models see ONLY pre-event data. The cutoff is enforced upstream in
  Stage 1 and re-checked here before anything is scored.

* Both are reported on the SAME cases with the same labels, and where the
  advanced model does no better, that is reported too.

A note on what "negative" means here, because it decides how the numbers read.
Eight of the eleven non-burst lakes are ICIMOD PDGL Rank-I lakes: experts
already consider them dangerous, and they simply have not burst inside our
window. Counting a flag on them as a false positive would punish a model for
agreeing with the expert assessment. So two views are reported - burst recall,
where those lakes are negatives, and rank-correlation against the Rounce expert
classes, where they are the ground truth. Neither view alone is honest.
"""
from __future__ import annotations

import numpy as np

ROUNCE_RANK = {"very_high": 4, "high": 3, "moderate": 2, "low": 1}


def growth_only_screen(lake: dict, traj: dict | None, cfg) -> dict:
    """The published baseline: area threshold plus two-date growth.

    Deliberately faithful to what a growth-only pipeline actually does. It is
    not weakened to manufacture a gap - the whole argument collapses if the
    baseline is a strawman.
    """
    area_t_km2 = cfg.require("evaluation.baseline.area_threshold_km2")
    growth_t = cfg.require("evaluation.baseline.growth_flag_pct")

    t = (traj or {}).get("trend", {})
    area_m2 = t.get("last_area_m2")
    area_km2 = (area_m2 / 1e6) if area_m2 else 0.0
    growth_pct = t.get("naive_two_date_change_pct")

    over_area = area_km2 >= area_t_km2
    growing = growth_pct is not None and growth_pct >= growth_t
    flagged = bool(over_area and growing)

    reasons = []
    if not over_area:
        reasons.append(f"area {area_km2:.4f} km2 is below the {area_t_km2} km2 "
                       f"screening threshold, so the lake is never assessed")
    elif not growing:
        reasons.append(f"area {area_km2:.4f} km2 passes the size screen but "
                       f"two-date growth {growth_pct}% is below {growth_t}%")
    else:
        reasons.append(f"area {area_km2:.4f} km2 and growth {growth_pct}% both "
                       f"exceed the screen")

    return {"model": "growth_only", "flagged": flagged,
            "area_km2": round(area_km2, 5), "growth_pct": growth_pct,
            "passes_area_screen": bool(over_area), "reasons": reasons,
            "thresholds": {"area_km2": area_t_km2, "growth_pct": growth_t},
            "source": "Rounce et al. 2017, Remote Sensing 9(7):654"}


def proxy_augmented_screen(lake: dict, prox: dict | None, traj: dict | None,
                           cfg, baseline: dict | None = None) -> dict:
    """Growth signal PLUS dam geometry and trigger terrain, no minimum size.

    AUGMENTED means the advanced model keeps everything the baseline uses and
    adds to it. An earlier version used the proxies ALONE and scored an
    identical recall of 0.333 - the two models simply caught different lakes,
    growth-only finding South Lhonak and the proxies finding Thame. That is a
    real and interesting result, but it is not the comparison the stage is
    asking for, and discarding a working signal to make the advanced model
    "purer" is a self-inflicted wound rather than a fair test.

    Note this cannot flatter the advanced model: it is a strict superset of the
    baseline, so it can only ever match or beat it on recall, and every extra
    flag it raises is counted against its precision.

    The ranking score is the source-to-lake volume ratio: the estimated
    detachment volume that can reach the lake, over the estimated lake volume.
    It is continuous, so the headline result needs no threshold at all - which
    matters, because the alarm level in config was set after seeing all
    fourteen values and is therefore NOT a blind holdout (see DECISIONS D7).
    """
    from_growth = bool(baseline and baseline.get("flagged"))
    if prox is None or prox.get("no_lake"):
        return {"model": "proxy_augmented", "flagged": from_growth, "score": None,
                "flagged_by": ["growth"] if from_growth else [],
                "reasons": [(prox or {}).get("no_lake_reason",
                            "no proxy record for this lake")]
                + (["growth screen flagged this lake"] if from_growth else []),
                "n_proxies_fired": 0}

    by = {p["proxy"]: p for p in prox.get("proxies", [])}
    ratio = by.get("source_to_lake_volume_ratio", {}).get("value")
    alarm = cfg.require("proxies.impulse_wave.source_to_lake_volume_alarm")

    trigger_proxies = ["ice_avalanche_source", "rock_landslide_source",
                       "impulse_wave", "steep_lakefront_area"]
    dam_proxies = ["freeboard", "distal_moraine_slope", "mother_glacier_proximity"]
    fired_trigger = [n for n in trigger_proxies if by.get(n, {}).get("fired")]
    fired_dam = [n for n in dam_proxies if by.get(n, {}).get("fired")]

    from_proxy = bool(ratio is not None and ratio >= alarm)
    flagged = bool(from_proxy or from_growth)
    reasons = []
    if from_growth:
        reasons.append("growth screen flagged this lake (inherited from baseline)")
    if ratio is not None:
        reasons.append(
            f"source-to-lake volume ratio {ratio} "
            f"({'at or above' if flagged else 'below'} the {alarm} alarm level)")
    if fired_trigger:
        reasons.append("trigger terrain: " + ", ".join(fired_trigger))
    if fired_dam:
        reasons.append("dam geometry: " + ", ".join(fired_dam))

    return {"model": "proxy_augmented", "flagged": flagged,
            "flagged_by": ([x for x in ("growth" if from_growth else None,
                                        "proxy" if from_proxy else None) if x]),
            "score": ratio, "n_proxies_fired": prox.get("n_fired", 0),
            "fired_trigger": fired_trigger, "fired_dam": fired_dam,
            "reasons": reasons,
            "no_minimum_lake_size": True,
            "alarm_threshold": alarm,
            "alarm_threshold_caveat": (
                "set after inspecting all 14 values; NOT a blind holdout result. "
                "The threshold-free claim is the rank, reported separately.")}


def confusion(flags: dict[str, bool], truth: dict[str, bool]) -> dict:
    tp = sorted(k for k in flags if flags[k] and truth[k])
    fp = sorted(k for k in flags if flags[k] and not truth[k])
    fn = sorted(k for k in flags if not flags[k] and truth[k])
    tn = sorted(k for k in flags if not flags[k] and not truth[k])
    rec = len(tp) / max(len(tp) + len(fn), 1)
    prec = len(tp) / max(len(tp) + len(fp), 1)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "n_tp": len(tp), "n_fp": len(fp), "n_fn": len(fn), "n_tn": len(tn),
            "recall": round(rec, 4), "precision": round(prec, 4),
            "f1": round(2 * prec * rec / max(prec + rec, 1e-9), 4)}


def spearman(x: list[float], y: list[float]) -> float | None:
    """Rank correlation without scipy.stats, so ties are handled explicitly."""
    if len(x) < 3:
        return None

    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(x), rank(y)
    mx, my = np.mean(rx), np.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = np.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(float(num / den), 4) if den else None


def precision_at_k(ranked: list[str], truth: dict[str, bool], ks: list[int]) -> dict:
    out = {}
    for k in ks:
        top = ranked[:k]
        hits = sum(1 for lid in top if truth.get(lid))
        out[f"p@{k}"] = round(hits / max(len(top), 1), 4)
    return out
