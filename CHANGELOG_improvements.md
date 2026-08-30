# Improvement changelog

Every stage, with its hypothesis, what changed, and the measured before/after -
or an explicit rationale where no metric applies.

**Generated from the run**, not hand-maintained. Metrics are read out of
`outputs/` at generation time so a figure here cannot disagree with the
pipeline that produced it. Judgement calls and the reasoning behind rejected
approaches live in `docs/DECISIONS.md`, which this references rather than
duplicates.

Run fingerprint: python 3.13.9,
PYTHONHASHSEED=0,
frozen clock 2026-01-01T00:00:00Z.

## Stage 0 - Determinism scaffolding

**Hypothesis.** Reproducibility retrofitted at the end is reproducibility that does not exist.

**Change.** Offline guard, frozen clock, seeded RNG, single-threaded BLAS, canonical JSON, and a run manifest hashing every artefact.

**Result.** Two cold runs produce byte-identical output. Offline guard engaged: True. No metric delta applies - this is a gate, and it fails the run when the guarantees are not in force.

**Evidence.** outputs/stage00_environment.json, outputs/run_manifest.json


## Stage 1 - Pinned dataset and labels

**Hypothesis.** Locking the evaluation universe before modelling prevents hindsight leakage.

**Change.** 14 lakes, 241 scenes, 15 documents pinned; cutoffs re-verified on every run.

**Result.** Cutoff violations: 0. The check is executed each run rather than assumed from the fetch, and it later caught a real leak in Stage 4's fallback.

**Evidence.** outputs/stage01_dataset_validation.json; DECISIONS D3


## Stage 2 - Delineation

**Hypothesis.** NDWI alone counts snow and ice as water; requiring NDWI AND MNDWI plus a glacier-ratio veto fixes it.

**Change.** Conditional BOA offset, dual-index rule, Huggel NIR/SWIR1 veto, SCL/DEM QA, anchored component selection.

| | before | after |
|---|---|---|
| lakes within 25% of published | - | 4/8 |
| Thyanbo vs. published 43,902 m2 | - | 1.00x |

**Evidence.** outputs/stage02_area_series.csv; DECISIONS D6 records the three calving lakes that still fail and why each hypothesis was ruled out by measurement.


## Stage 3 - Trajectory and burst detection

**Hypothesis.** A sudden area drop signals an outburst - but freeze-up produces the same signature.

**Change.** Theil-Sen trend; magnitude + suddenness + persistence tests, and a fourth state for 'no usable follow-up'.

**Result.** Bursts detected: ['thyanbo_tsho']. Magnitude alone fired on three non-burst lakes; suddenness removed Thulagi and Imja; persistence separated Tsho Rolpa's freeze-up from Thame's real outburst despite near identical open-water fractions (65% vs 62%).

**Evidence.** outputs/stage03_trajectory.csv


## Stage 4 - Proxy engine

**Hypothesis.** Area-growth screening misses Thame because the danger was terrain and dam geometry, not size.

**Change.** Nine published proxies, each separately queryable with source and confidence tier; a no-lake guard for the negative control.

| | before | after |
|---|---|---|
| Thame area vs 0.1 km2 screen | 0.0441 km2 | below - growth screen never assesses it |
| proxies fired on Thame (pre-event data only) | 0 | 8 |

**Evidence.** outputs/stage04_proxies.csv; DECISIONS D7 on why the published binary criteria do not discriminate here and what replaced them.


## Stage 5 - Exposure overlay

**Hypothesis.** Hazard without consequence is a geometry exercise.

**Change.** OSM assets and WorldPop over the routed corridor, with hydropower reported as its own field.

**Result.** [{'class': 'hindcast_event', 'corridor': {'area_km2': 0.0937, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 0.426, 'truncated_at_window_edge': False}, 'country': 'NP', 'counts': {}, 'critical_infrastructure': {}, 'criticality_weighted_score': 0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'thyanbo_tsho', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 0.0, 'osm_method': '0 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': {'all_nodata': True, 'cells': 0, 'note': 'WorldPop constrained has no populated cells anywhere in this corridor. The product only assigns population where buildings are detected, so this is a measured absence of settlement, not a coverage gap or an overlay failure.', 'population': 0.0}, 'worldpop_available': True, 'worldpop_unavailable_reason': None}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}, {'class': 'hindcast_event', 'corridor': {'area_km2': 1.7069, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 3.479, 'truncated_at_window_edge': True}, 'country': 'IN', 'counts': {}, 'critical_infrastructure': {}, 'criticality_weighted_score': 0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'south_lhonak', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 0.0, 'osm_method': '0 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': None, 'worldpop_available': False, 'worldpop_unavailable_reason': 'WorldPop pinned for Nepal only; India and China rasters are 506 MB and 657 MB and the server ignores HTTP Range requests. This is a coverage gap, NOT an absence of population.'}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}, {'class': 'hindcast_event', 'corridor': {'area_km2': 1.2521, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 2.732, 'truncated_at_window_edge': False}, 'country': 'CN', 'counts': {}, 'critical_infrastructure': {}, 'criticality_weighted_score': 0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'pyurepu_supraglacial', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 0.0, 'osm_method': '0 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': None, 'worldpop_available': False, 'worldpop_unavailable_reason': 'WorldPop pinned for Nepal only; India and China rasters are 506 MB and 657 MB and the server ignores HTTP Range requests. This is a coverage gap, NOT an absence of population.'}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}, {'class': 'negative_control', 'corridor': {'area_km2': 4.8188, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 4.211, 'truncated_at_window_edge': True}, 'country': 'IN', 'counts': {}, 'critical_infrastructure': {}, 'criticality_weighted_score': 0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'chamoli_ronti', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 0.0, 'osm_method': '0 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': None, 'worldpop_available': False, 'worldpop_unavailable_reason': 'WorldPop pinned for Nepal only; India and China rasters are 506 MB and 657 MB and the server ignores HTTP Range requests. This is a coverage gap, NOT an absence of population.'}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}, {'class': 'pdgl_known_high', 'corridor': {'area_km2': 0.7129, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 2.14, 'truncated_at_window_edge': False}, 'country': 'NP', 'counts': {}, 'critical_infrastructure': {}, 'criticality_weighted_score': 0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'imja_tsho', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 0.0, 'osm_method': '0 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': {'all_nodata': True, 'cells': 0, 'note': 'WorldPop constrained has no populated cells anywhere in this corridor. The product only assigns population where buildings are detected, so this is a measured absence of settlement, not a coverage gap or an overlay failure.', 'population': 0.0}, 'worldpop_available': True, 'worldpop_unavailable_reason': None}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}, {'class': 'pdgl_known_high', 'corridor': {'area_km2': 0.3468, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 1.332, 'truncated_at_window_edge': False}, 'country': 'NP', 'counts': {'building': 2}, 'critical_infrastructure': {}, 'criticality_weighted_score': 2.0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'tsho_rolpa', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 19.2, 'osm_method': '2 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': {'all_nodata': True, 'cells': 0, 'note': 'WorldPop constrained has no populated cells anywhere in this corridor. The product only assigns population where buildings are detected, so this is a measured absence of settlement, not a coverage gap or an overlay failure.', 'population': 0.0}, 'worldpop_available': True, 'worldpop_unavailable_reason': None}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}, {'class': 'pdgl_known_high', 'corridor': {'area_km2': 0.4745, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 0.4, 'truncated_at_window_edge': False}, 'country': 'NP', 'counts': {}, 'critical_infrastructure': {}, 'criticality_weighted_score': 0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'thulagi', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 0.0, 'osm_method': '0 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': {'all_nodata': True, 'cells': 0, 'note': 'WorldPop constrained has no populated cells anywhere in this corridor. The product only assigns population where buildings are detected, so this is a measured absence of settlement, not a coverage gap or an overlay failure.', 'population': 0.0}, 'worldpop_available': True, 'worldpop_unavailable_reason': None}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}, {'class': 'pdgl_known_high', 'corridor': {'area_km2': 2.4374, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 1.987, 'truncated_at_window_edge': True}, 'country': 'NP', 'counts': {}, 'critical_infrastructure': {}, 'criticality_weighted_score': 0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'lower_barun', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 0.0, 'osm_method': '0 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': {'all_nodata': True, 'cells': 0, 'note': 'WorldPop constrained has no populated cells anywhere in this corridor. The product only assigns population where buildings are detected, so this is a measured absence of settlement, not a coverage gap or an overlay failure.', 'population': 0.0}, 'worldpop_available': True, 'worldpop_unavailable_reason': None}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}, {'class': 'pdgl_known_high', 'corridor': {'area_km2': 0.1189, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 0.552, 'truncated_at_window_edge': False}, 'country': 'NP', 'counts': {}, 'critical_infrastructure': {}, 'criticality_weighted_score': 0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'chamlang_tsho', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 0.0, 'osm_method': '0 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': {'all_nodata': True, 'cells': 0, 'note': 'WorldPop constrained has no populated cells anywhere in this corridor. The product only assigns population where buildings are detected, so this is a measured absence of settlement, not a coverage gap or an overlay failure.', 'population': 0.0}, 'worldpop_available': True, 'worldpop_unavailable_reason': None}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}, {'class': 'pdgl_known_high', 'corridor': {'area_km2': 0.1292, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 0.29, 'truncated_at_window_edge': False}, 'country': 'NP', 'counts': {}, 'critical_infrastructure': {}, 'criticality_weighted_score': 0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'lumding_tsho', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 0.0, 'osm_method': '0 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': {'all_nodata': True, 'cells': 0, 'note': 'WorldPop constrained has no populated cells anywhere in this corridor. The product only assigns population where buildings are detected, so this is a measured absence of settlement, not a coverage gap or an overlay failure.', 'population': 0.0}, 'worldpop_available': True, 'worldpop_unavailable_reason': None}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}, {'class': 'pdgl_known_high', 'corridor': {'area_km2': 0.7602, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 1.629, 'truncated_at_window_edge': False}, 'country': 'NP', 'counts': {}, 'critical_infrastructure': {}, 'criticality_weighted_score': 0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'hongu_1', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 0.0, 'osm_method': '0 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': {'all_nodata': True, 'cells': 0, 'note': 'WorldPop constrained has no populated cells anywhere in this corridor. The product only assigns population where buildings are detected, so this is a measured absence of settlement, not a coverage gap or an overlay failure.', 'population': 0.0}, 'worldpop_available': True, 'worldpop_unavailable_reason': None}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}, {'class': 'pdgl_known_high', 'corridor': {'area_km2': 2.895, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 3.525, 'truncated_at_window_edge': True}, 'country': 'NP', 'counts': {}, 'critical_infrastructure': {}, 'criticality_weighted_score': 0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'hongu_2', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 0.0, 'osm_method': '0 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': {'all_nodata': True, 'cells': 0, 'note': 'WorldPop constrained has no populated cells anywhere in this corridor. The product only assigns population where buildings are detected, so this is a measured absence of settlement, not a coverage gap or an overlay failure.', 'population': 0.0}, 'worldpop_available': True, 'worldpop_unavailable_reason': None}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}, {'class': 'benign_negative', 'corridor': {'area_km2': 3.8564, 'disclaimer_id': 'indicative_corridor_30m_dem', 'runout_km': 0.862, 'truncated_at_window_edge': False}, 'country': 'NP', 'counts': {}, 'critical_infrastructure': {}, 'criticality_weighted_score': 0, 'criticality_weights': {'bridge': 4.0, 'building': 1.0, 'health_post': 8.0, 'hydropower': 10.0, 'power_substation': 6.0, 'road': 1.0, 'school': 6.0, 'settlement': 5.0}, 'hydropower_in_corridor': 0, 'lake_id': 'tilicho', 'named_assets': [], 'population': {'divergence': None, 'osm_derived': 0.0, 'osm_method': '0 buildings x 9.6 persons/building (documented Nepal method; crude)', 'worldpop': {'all_nodata': True, 'cells': 0, 'note': 'WorldPop constrained has no populated cells anywhere in this corridor. The product only assigns population where buildings are detected, so this is a measured absence of settlement, not a coverage gap or an overlay failure.', 'population': 0.0}, 'worldpop_available': True, 'worldpop_unavailable_reason': None}, 'weights_note': 'our judgement, not a published scheme; raw counts are reported alongside so a reviewer can reweight'}] lakes assessed; 2 buildings and no population in total. NOT a null result to hide: WorldPop constrained assigns population only where buildings exist, and the corridors are truncated by a 6 km window while the Thame flood ran 80 km. Every count is a lower bound.

**Evidence.** outputs/stage05_exposure.csv; DECISIONS D11


## Stage 6 - Flow routing

**Hypothesis.** A reach-angle stop rule gives a defensible corridor from a free DEM.

**Change.** MSF routing seeded from the whole lake rim, reach angle applied as a terminus rather than a per-step gate.

**Result.** Corridors for 13/14 lakes, including both cases the criterion names. Five separate corrections were needed, each forced by a measured failure that produced a one-cell corridor.

**Evidence.** outputs/stage06_routing.csv; DECISIONS D8


## Stage 7 - Watcher evaluation - THE MONEY CHART

**Hypothesis.** Adding dam-failure and trigger proxies catches what growth-only screening misses, on identical cases with identical inputs.

**Change.** Real published baseline (Rounce 0.1 km2 screen), same pre-event data, advanced model a strict superset of the baseline.

| | before | after |
|---|---|---|
| recall | 0.0 | **0.3333** |
| F1 | 0.0 | **0.4** |

**Evidence.** Thame is a growth-only FALSE NEGATIVE and a proxy-augmented TRUE POSITIVE. Threshold-free: Thame ranks 1 of 13 on the continuous score. Spearman vs Rounce 2017: 0.378. outputs/stage07_confusion_matrix.csv; DECISIONS D9


## Stage 8 - Retriever

**Hypothesis.** Provenance must survive retrieval or nothing downstream can cite.

**Change.** Deterministic pull from pinned bundles with full per-source metadata.

**Result.** 4 events, 48 passages, all events at or above the 3-distinct-publisher minimum.

**Evidence.** outputs/stage08_retrieval.json


## Stage 9 - Numeric reconciliation - THE KILLER FEATURE

**Hypothesis.** For high-stakes reporting, surfacing that sources disagree beats fluently picking one.

**Change.** Rule-based extraction with nearest-keyword binding, cross-source and intra-document contradiction detection.

| | before | after |
|---|---|---|
| contradiction F1 vs hand-labelled key | - | **0.8571** |
| precision / recall | - | 0.8571 / 0.8571 |

**Evidence.** South Lhonak deaths surface as 40/55/74/178 across Reuters, Science and Landslides; Rasuwa hydropower as 4/5/8/11; NDRRMA's internal arithmetic error (states 23, itemises 33) caught by a separate check. outputs/stage09_disagreements.csv; DECISIONS D10


## Stage 10 - Drafting

**Hypothesis.** Every claim inline-cited and every contradiction visible, by construction rather than by prompt instruction.

**Change.** OCHA skeleton assembled from reconciliation output, English and Nepali.

**Result.** 8 drafts; 0 contradictions unreflected; 0 negative-control mislabels.

**Evidence.** outputs/sitreps/


## Stage 11 - Critic and verification loop

**Hypothesis.** Unsupported claims must not be able to ship.

**Change.** Deterministic numeric verifier plus adversarial critic, with an advisory LLM second opinion that cannot clear a draft.

**Result.** Fabricated figure caught: True. Uncited claim flagged: True - and that one only passes because the first version MISSED it: the claim carries no digits, so the numeric verifier was structurally blind to it.

**Evidence.** outputs/stage11_verification.json


## Stage 12 - Provenance ledger and approval

**Hypothesis.** The Tsho Rolpa EWS failed partly through over-automation; nothing here is final without a named human.

**Change.** Append-only hash-chained ledger; verification-blocked drafts are withheld from approval rather than presented.

**Result.** 27 entries, chain intact True, tamper detected on edit True. 7 finalised, 1 withheld.

**Evidence.** outputs/stage12_ledger.jsonl


## Stage 13 - CAP and HXL exports

**Hypothesis.** Machine-readable output must not drift from the human-readable one.

**Change.** Both generated from the same reconciliation record; CAP status is Exercise, never Actual.

**Result.** 4 CAP files valid, 28 HXL rows, 0 drift against the sitreps.

**Evidence.** outputs/exports/


## Stage 14 - Reporter evaluation

**Hypothesis.** The multi-agent pipeline beats a single-prompt summariser on the metrics that matter for high-stakes reporting.

**Change.** 10 scenarios (4 real + 6 perturbed), five metrics, both pipelines.

| | before | after |
|---|---|---|
| contradiction recall | 0.0 | **0.95** |
| hallucination rate | 0.3584 | **0.0958** |

**Evidence.** Also numeric accuracy 0.6417 -> 0.9042, citation F1 0.0 -> 0.5202. Reported honestly: the edit-distance win is trivial because the approved text IS the advanced draft. outputs/stage14_metrics.csv


## Stage 15 - Nepali QA

**Hypothesis.** Fluency is not correctness; terminology consistency matters more in a sitrep.

**Change.** Fixed glossary, chrF++ over a back-translation round trip, number preservation check. COMET deliberately not run, per the brief's own fallback.

**Result.** chrF++ 54.6-62.1 across 4 drafts; number preservation 1.00 on all of them; terminology consistent: True.

**Evidence.** outputs/stage15_nepali_eval.json


## Stage 16 - Negative control

**Hypothesis.** A system that cannot say what a hazard is NOT will eventually misattribute one.

**Change.** Chamoli 2021 run end to end through watcher, reporter in both languages, and the CAP export.

**Result.** Holds: True. Watcher finds 300 m2 of scattered meltwater and fires 0 proxies.

**Evidence.** outputs/stage16_confusion_matrix.csv


## Stage 17 - Reproducibility packaging

**Hypothesis.** A judge must reproduce every headline number with no credentials.

**Change.** Docker pinned to the lockfile; LLM responses cached and committed; headline numbers extracted from the run.

**Result.** 964 scene rasters, 8 cached LLM responses. Offline during run: True.

**Evidence.** outputs/stage17_reproducibility.json


## Stage 18 - Documentation

**Hypothesis.** Hand-written results drift from the pipeline the moment a threshold changes, and the drift is invisible.

**Change.** RESULTS, LIMITS, ETHICS and this changelog generated FROM the run.

**Result.** No metric applies. The property being asserted is that no documented figure can disagree with the run that produced it, because none of them is typed by hand.

**Evidence.** docs/RESULTS.md, docs/LIMITS.md, docs/ETHICS.md
