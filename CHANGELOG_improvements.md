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
| lakes within 25% of published | - | 6/8 |
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

**Result.** 13 lakes assessed; 2 buildings and no population in total. NOT a null result to hide: WorldPop constrained assigns population only where buildings exist, and the corridors are truncated by a 6 km window while the Thame flood ran 80 km. Every count is a lower bound.

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
| hallucination rate | 0.344 | **0.0911** |

**Evidence.** Also numeric accuracy 0.656 -> 0.9089, citation F1 0.0 -> 0.5354. Reported honestly: the edit-distance win is trivial because the approved text IS the advanced draft. outputs/stage14_metrics.csv


## Stage 15 - Nepali QA

**Hypothesis.** Fluency is not correctness; terminology consistency matters more in a sitrep.

**Change.** Fixed glossary, chrF++ over a back-translation round trip, number preservation check. COMET deliberately not run, per the brief's own fallback.

**Result.** chrF++ pending an LLM cache pass.

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


---

## Post-pipeline tools - the downstream chain (`make scenarios`, `make map`)

Built after Stage 18 against the pinned 100 km DEMs and cached OSM extracts; offline once `make fetch-downstream` has run once. Figures below are read from the tool artefacts at generation time, like everything above.


## Stage T1 - Long-range routing (DECISIONS D18-D19)

**Hypothesis.** Exposure needs a river-network domain, not a 7 km box around the lake; every Stage 6 corridor stops in the headwaters.

**Change.** Same MSF physics on a 100 km, 90 m domain per lake. Priority-flood pit fill (a 200-iteration local fill left South Lhonak stalled in an unfilled hollow), spill-point seeding (pit filling strands a steepest-descent walk inside the lake basin), and the walk kept in walk order.

**Result.** Corridors reach 31-127 km against a 3.5 km cap before; median gain factor 73.5x across 12 lakes.

**Evidence.** outputs/tools/long_routing.json; DECISIONS D18-D19


## Stage T2 - Corridor exposure, scored against destroyed villages (DECISIONS D20)

**Hypothesis.** A corridor down the wrong valley can still travel the right distance; the sharper test is whether it passes the villages the floods actually destroyed, at the observed distance.

**Change.** OSM assets and WorldPop within 500 m of the routed channel, validated against five documented impact sites. Three data-integrity bugs found and fixed on the way, each one a wrong answer that LOOKED like an empty one: HTTP 200 responses with zero elements cached as 'nothing downstream'; nodata inside the raster scored as uncovered (0% coverage printed beside 5,222 people); the polyline ordered by distance-from-lake, which interleaved river bends and put Reni 3.4x too far down the channel.

**Result.** 3 of 5 destroyed settlements found, 3 within 2x of the observed distance (Thame 7.6 km vs 10, Rasuwagadhi 35.1 vs 36, Reni 22.3 vs 13 - the last was 43.8 km before the polyline-order fix). 2 of 4 observed reaches fall inside the debris/clear-water bracket.

**Evidence.** outputs/tools/corridor_exposure.json, outputs/tools/routing_validation.json; DECISIONS D20


## Stage T3 - Scenario dial and capacity trend (map)

**Hypothesis.** A duty officer's question is conditional - 'if the flow runs R km, who is in the way?' - and an answer fixed at full reach hides how exposure accumulates down the valley.

**Change.** A reach slider on the map conditions the corridor, the asset counts and the WorldPop sum on one draggable distance, with the observed reach of each real event marked on the slider. A capacity line projects the release band 12 months forward on the Theil-Sen slope Stage 3 already fits - framed as a capacity forecast, never a hazard forecast, because Thame was stable in area and burst anyway.

**Result.** Fastest-growing lake: Lumding at +212,206 m2/yr, central band 44M -> 56M m3 in 12 months. The map page is verified against these artefacts by tools/check_map_page.mjs (32 checks), including that the dial's counters equal the artefact counts.

**Evidence.** outputs/tools/scenarios.json, outputs/tools/map.html, tools/check_map_page.mjs
