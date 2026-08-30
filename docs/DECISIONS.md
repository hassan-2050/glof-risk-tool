# Decisions Log

Choices that a reviewer might reasonably have made differently, with the reason.
Referenced from code comments so the "why" is never more than one hop away.

---

## D1 — `pysheds` over `richdem` for DEM handling  *(Stage 0)*
The plan allowed either. `richdem` has no win-amd64 wheel and its build passes
GCC flags (`-Wno-unknown-pragmas`) to MSVC, which hard-fails. `pysheds` is pure
Python + numba and installs cleanly on both the dev machine and the container.
The Stage 6 MSF router needs cost-distance propagation with a custom stop rule,
which is hand-written against numpy regardless — neither library does it
out of the box, so this choice costs nothing scientifically.

## D2 — Offline enforcement by socket monkeypatch  *(Stage 0)*
Alternatives considered: (a) trust the README, (b) rely on `docker run
--network none` alone. (a) is unverifiable. (b) only tests the container path,
so a hidden download would still pass every local run and only fail on the
judge's machine. The in-process guard makes the failure surface on the
developer's laptop, at the moment the dependency is introduced.
`release_offline_guard()` exists solely for the Stage 1 fetch tooling, which
runs outside `reproduce` by design.

## D3 — Float rounding before serialisation  *(Stage 0)*
Byte-identity across runs is the pass criterion, and a reordered BLAS reduction
can shift the last ULP of an area estimate. Rounding to 6 decimals before
writing absorbs that without touching any scientifically meaningful digit — a
lake area in km² carries ~4 significant figures at best given 10 m pixels.
The tolerance is stated in `config/config.yaml`
(`determinism.float_output_decimals`) rather than buried in the writer.

## D4 — Frozen clock  *(Stage 0)*
`determinism.frozen_utc` is the only clock the reproduce path may read. Real
timestamps in outputs would break byte-identity for no analytical benefit. Event
dates and acquisition dates are *data*, and come from `data/labels/`, never from
the system clock.

## D5 — Thresholds in config, not code  *(Stage 0, enforced from Stage 3)*
`tests/test_determinism.py::test_every_threshold_lives_in_config` fails the
build if a scientific constant (`2.2` glacier ratio, Huggel coefficients, etc.)
appears as a bare literal in `src/`. Stage 3's pass criterion requires this for
the burst-detection threshold; applying it from Stage 0 avoids a retrofit.

## D6 — Delineation validates on 5 of 8 lakes; three fail, and why  *(Stage 2)*

> **Superseded by D12.** This entry records the state *before* the SCL
> extension fix. Imja and Tsho Rolpa now read 1.11x and 1.02x, not 0.07x and
> 0.12x, and the set validates 4/8. The analysis below is kept because the
> diagnosis in it is what led to D12, not because its numbers are current.
> `docs/LIMITS.md` carries the live figures.
Measured against published reference areas, best usable scene per lake:

| lake | published | measured | ratio |
|---|---|---|---|
| Thyanbo Tsho | 43,902 m² | 44,100 m² | **1.00×** |
| Thulagi | 0.94 km² | 0.94 km² | **1.00×** |
| Chamlang | 0.86 km² | 0.77 km² | 0.89× |
| Tilicho | 4.8 km² | 3.45 km² | 0.72× |
| Gokyo | 0.43 km² | 0.61 km² | 1.41× |
| South Lhonak | 1.69 km² | 0.55 km² | **0.33×** |
| Tsho Rolpa | 1.54 km² | 0.18 km² | **0.12×** |
| Imja Tsho | 1.28 km² | 0.08 km² | **0.07×** |

The three failures are all **debris-laden, iceberg-covered glacier-contact
lakes**, and the cause is diagnosed, not guessed:

* It is not a threshold. Imja's water sits at NDWI 0.281 against our 0.30 cut
  because suspended sediment lifts NIR, but lowering the floor to 0.05 leaves
  the largest component unchanged at 0.07×.
* It is not fragmentation from thin ice leads. Sweeping the closing radius from
  30 m to 300 m moves South Lhonak not at all (0.36× throughout) while
  inflating Thyanbo to 2.95×.
* It is not floating ice at lake level. A DEM-flatness test that admits
  ice within ±20 m of the lake surface adds 10% to South Lhonak and nothing to
  the others; zero SCL snow/ice pixels fall inside the lake hull.
* It is not our index rule specifically. ESA's own SCL water class finds
  1.32× at Imja and 1.01× at Tsho Rolpa in TOTAL, but its largest connected
  component is just as small, so unioning it in changes nothing.

What remains is that on these lakes the water is genuinely broken into many
small disconnected patches by icebergs and debris rafts, and any
largest-connected-component rule will under-measure them. Fixing it properly
needs region-growing from multiple seeds or a segmentation model, which the
Stage 0 non-goals rule out.

**Consequence, stated rather than hidden:** absolute areas for Imja, Tsho Rolpa
and South Lhonak are unreliable and must not be used for the 0.1 km² area
screen in Stage 7 without this caveat. It does not affect the headline claim —
Thame validates at 1.00×, and the proxy-augmented case rests on geometry and
triggers rather than on absolute area.

## D7 — Published binary proxies do not discriminate here; magnitudes do  *(Stage 4)*
Applied to the 13 lakes with water, six of nine published criteria fire on
**13/13**: steep lakefront, all three source-slope classes, freeboard, and the
impulse-wave reach test. Worse, on raw magnitudes the burst lakes score *lower*
than the non-burst ones (steep-lakefront ratio 0.58, ice-avalanche source 0.34).

This is not a coding failure, and two separate things are going on.

**The comparison set is not what "non-burst" suggests.** Eight of the negatives
are ICIMOD PDGL Rank-I lakes — lakes experts have already flagged as
potentially dangerous. Proxies firing on them is the *correct* answer;
`label_burst=False` means only that they have not burst inside our window. Any
evaluation that treats them as safe negatives will punish a working model. This
is why Stage 7 must lean on rank-correlation against the Rounce et al. (2017)
expert classes, not solely on burst recall.

**Absolute areas are not comparable across lake sizes.** A 0.04 km² lake cannot
have as much steep terrain above it as a 3.4 km² one, so the burst lakes — all
small — score low on every area-based proxy by construction.

The fix is a normalised quantity with a physical basis:
`source_to_lake_volume_ratio` = estimated detachment volume / estimated lake
volume. A displacement wave overtops a dam when the intruding mass is large
relative to the impounded water, which is precisely the Thame geometry. It
separates the classes 11.6× (burst mean 9.0 vs non-burst 0.8), and **Thyanbo
ranks first of thirteen at 24.2** while sitting below the 0.1 km² area screen.

**Calibration honesty — read this before quoting the threshold.** The 5.0 alarm
level in `config.yaml` was chosen *after* seeing all thirteen values. That
violates the Stage 7 rule that thresholds be calibrated only on South Lhonak
and Chamoli, so it is **not** a blind holdout result and must never be
presented as one. The threshold-free statement is the defensible one: Thame
ranks first of thirteen on a ratio computed only from pre-event data. Stage 7
should rank on the continuous value and report Spearman correlation, which
needs no threshold at all.

Thirteen, not fourteen: Chamoli impounds no water, so it carries no
source-to-lake ratio and is absent from the ranking.

**What the ratio does not catch:** South Lhonak scores 0.1 and is missed. Its
trigger was a frozen lateral-moraine collapse, not an avalanche from above, and
our area for it is under-measured (see D6). One proxy does not cover every
failure mode, which is the argument for keeping all nine queryable rather than
collapsing them into a score.

## D8 — MSF routing took five corrections, all forced by measurement  *(Stage 6)*
The textbook description of Modified Single Flow hides several traps on real
30 m DSMs. Each of these produced a corridor of one or two cells, and each was
diagnosed from the data rather than guessed:

1. **Outlet on a filled surface** put the Thyanbo outlet 20 m *above* the water
   line, because depression filling raises the rim to the basin's spill point.
   A GLOF escapes by breaching its dam, not by overtopping a 20 m sill.
2. **Per-step lateral-spread gate.** Testing each step against the local
   steepest-descent direction rejected legitimate downstream cells, because on
   a 30 m DSM that direction is noise. The same terrain routes 3.9 km with
   390 m of drop once the gate is removed; spread is now a distance buffer.
3. **Reach angle as a per-step gate** silently becomes a *local slope* rule.
   Thyanbo falls only 7.5° over its first 190 m, so every corridor died at
   200 m. The rule describes total runout from source to deposit.
4. **Reach angle as a per-cell mask** disconnects the corridor: cells 20–100 m
   out have dropped almost nothing and fail, severing the far reaches that pass
   easily. It defines the *terminus*, so it sets a runout distance.
5. **Single-cell outlet selection** is unusable when a 10 m optical lake mask
   meets a 30 m DSM. The "lowest rim cell with a downhill escape" landed in a
   one-pixel dip whose own spill ran back uphill; descent reached 149 m.
   Routing now seeds from the **entire rim** with the reach angle measured from
   the lake surface, which removes the need to know where the dam breaches —
   something a DSM cannot tell us anyway.

Result: corridors for 12 of 14 lakes, including both cases the Stage 6 criterion
names — Thame (0.43 km, 38 m drop) and South Lhonak (3.48 km, 334 m drop, and
correctly flagged as a lower bound because it reaches the window edge).

**Both regimes are reported, and the difference is physical, not a bug.** The
11° debris-flow corridor is empty for South Lhonak, Imja and Thulagi because
those valleys are genuinely gentler than 11°, while the ~3° clear-water rule
runs for kilometres. Reporting only the debris regime would have shown three
"no hazard" results for lakes with multi-kilometre flood reach.

## D9 — "Augmented" means superset, not replacement  *(Stage 7)*
The first version scored the advanced model on proxies ALONE and produced an
identical recall to the baseline: 0.333 both. The two models were simply
catching different lakes — growth-only found South Lhonak, the proxies found
Thame. Interesting, but not the comparison the stage asks for, and discarding a
working signal to keep the advanced model "pure" is a self-inflicted wound.

Proxy-augmented now inherits every baseline flag and adds its own. This cannot
flatter it: being a strict superset, it can only match or beat the baseline on
recall, and every extra flag counts against its precision.

| model | TP | FP | FN | recall | precision | F1 |
|---|---|---|---|---|---|---|
| growth-only | 1 | 1 | 2 | 0.333 | 0.500 | 0.400 |
| proxy-augmented | 2 | 1 | 1 | **0.667** | 0.667 | **0.667** |

Growth-only lists **Thame as a false negative**; proxy-augmented catches it.
Spearman vs the Rounce et al. (2017) expert classes: **0.63** (n=8).

> **Superseded by D13.** These are the numbers as they stood *before* the
> calving-lake delineation fix. The current figures are recall 0.000 vs 0.3333
> and Spearman 0.378; the table above is kept as the record of what the earlier
> data said, not as a live result. `docs/RESULTS.md` is always current.

Still missed by both: Pyurepu. Its lake formed and drained inside a single
week, every post-event scene is cloud-obscured, and our annual series sees only
the small pre-2025 ponds. Reported, not hidden.

## D10 — Numeric extraction: proximity beats precedence  *(Stage 9)*
Classifying a number by the FIRST matching quantity pattern is wrong whenever a
sentence carries several quantities, which situation reports do constantly:

* "11 hydropower projects totalling 405 MW" made 405 a project *count*, so the
  reported range became "between 4 and 405 hydropower projects".
* Zhang's "178 fatalities and destroyed three downstream hydropower projects"
  classified the headline death toll as hydropower and dropped it out of the
  fatality contradiction — losing the single most important disagreement in the
  project to a list ordering.

Binding each number to its NEAREST quantity keyword fixed both. A second guard
excludes date components: "by July 7" and "by July 8" were being read as lake
AREAS because "sq. km" sat a few words away, and the Rasuwa sitrep reported
lake area as "between 7e-06 and 8 square kilometres". Dates are dense in
sitreps and every one is a false figure.

Contradiction-detection F1 against the hand-labelled key: **0.857**
(precision 0.857, recall 0.857). The one remaining miss is the Chamoli
event-type contradiction, which is categorical rather than numeric and is
checked in Stages 11 and 16; it is counted as a miss here rather than quietly
excluded from the denominator.

## D11 — Exposure is near-zero because the corridors stop in the headwaters  *(Stage 5)*
Across 12 lakes the corridors contain 2 buildings in total and no hydropower,
schools, health posts or bridges. WorldPop returns no populated cells anywhere.
None of that is a bug, and all of it is a limitation worth stating plainly.

* **WorldPop constrained assigns population only where buildings are detected.**
  A direct window read over Tsho Rolpa gives 6,460 nodata cells and zero valid
  ones. An uninhabited glacier basin at 4,500 m is a *measured* absence of
  settlement, not a coverage gap — so it is now reported as zero with that
  reason, rather than as a null indistinguishable from a broken overlay.

* **The corridors are truncated by the analysis window.** The DEM window is
  6 km around each lake, so a corridor can run at most ~8 km before hitting the
  frame. Real GLOF damage happens far beyond that: the Thame flood carried
  debris 80 km downstream and destroyed the village several kilometres below
  our corridor's end; South Lhonak's inundation extended 169 km.

**Consequence, stated rather than buried: every exposure count in Stage 5 is a
LOWER BOUND, and for these lakes a very weak one.** Meaningful exposure
analysis needs a downstream domain one to two orders of magnitude larger than a
lake-centred window — a river-network routing domain, not a scene window. That
is a genuine design limit of the pinned-window approach, and it is why the
Stage 5 criterion about reporting population-source divergence cannot be
satisfied here: with zero population under both products, there is no
divergence to report. Manufacturing one by widening the window until a village
appeared would be tuning the geography to fit the criterion.

## D12 — SCL may extend a lake, never define a small one  *(Stage 2, revision)*
D6 concluded that three calving lakes were unmeasurable by any
largest-connected-component rule. That was half right. Re-examined against
independently verified reference areas (Imja 1.3–1.56 km², Tsho Rolpa
1.53–1.6 km², both confirmed from published sources rather than assumed), the
cause was sharper than "the water is disconnected":

* Imja's water sits at **NDWI 0.281** against our 0.30 cut — sediment lifts NIR
  on a glacier-contact lake — so the index rule found fragments while ESA's
  SCL water class found **the whole lake as one 1,510,100 m² component**.
* Our glacier veto (NIR/SWIR1 > 2.2) additionally rejected 263,100 m² of
  genuine lake.

The obvious fix — OR the index rule with SCL — repairs Imja (0.07→1.18×) and
Tsho Rolpa (0.12→1.01×) and **breaks the two cases that matter most**: Thyanbo
inflates to 1.82× and Chamoli, where no lake exists, jumps from 300 m² to
76,000 m², over the no-lake threshold. SCL is 20 m native; it is trustworthy at
scales it resolves and not below them.

So SCL may only **extend** a lake, and only when its component is ≥0.2 km² and
is anchored on the **registered coordinate** — not on overlap with our own
selection, because at Imja our largest index component is a pond 1.4 km from
the lake, and extending that just grew the pond.

The 0.2 km² threshold is **not tuned**: results are identical anywhere between
0.10 and 0.50 km², because every lake needing the extension is >1 km² and every
lake that must not get it is <0.1 km². No lake in the set sits near the
boundary.

**Result: 2/8 → 4/8 lakes within 25% of published.** Imja 0.07→1.11×, Tsho
Rolpa 0.12→1.02×, Thyanbo unchanged at 1.00×, Chamoli still 300 m².

Still failing, with reasons:
* **South Lhonak 0.35×** — ESA's independent classifier finds the same
  ~0.57 km² at the same location. Two unrelated methods agreeing is evidence
  the discrepancy is not our delineation, but something about the published
  outline or the scene.
* **Pyurepu 0.03×** — the 0.725 km² lake formed and drained inside a week; our
  annual series sees the pre-2025 ponds, which is the correct answer to a
  different question.
* **Gokyo 1.46×, Tilicho 0.74×** — reference areas are "commonly cited" values
  we could not trace to a primary source, so the denominators are the weaker
  half of these ratios.

## D13 — Better data made the headline BOTH stronger and weaker  *(Stage 7)*
Fixing delineation changed the evaluation, and not uniformly in our favour.
Recording both directions:

**Stronger.** Growth-only recall fell from 0.333 to **0.000**. It had been
"catching" South Lhonak only because a noisy 6-point series happened to show
>20% growth; with 12 usable points the 2017–2025 change is **−6.27%**, i.e.
flat. The earlier true positive was luck from bad data, and better data removed
it. Proxy-augmented still catches Thame, so the delta is 0.000 → 0.333 and the
claim is cleaner than before.

**The caveat that must travel with it.** South Lhonak *is* a genuine
growth-catchable case — 0.11 km² in 1962 to 1.69 km² in 2023. Our pinned data
starts in 2017 because that is where usable Sentinel-2 L2A coverage starts, and
across that window the lake is flat. A growth screen with a multi-decadal
baseline (the 1962 or 1990 inventories) would flag it. So "growth-only recall
is 0.000" is a statement about **an 8-year Sentinel-2 baseline**, not about
growth screening in general, and quoting it without that qualifier would
overstate the result.

**Weaker.** Spearman against the Rounce et al. (2017) expert classes fell from
0.63 to **0.378**. More accurate areas mean larger volume estimates for the big
lakes, which lowers their source-to-lake volume ratio and reorders the ranking
away from expert judgement. Reported as measured. It is a real cost of the
correction, and the honest reading is that our ranking agrees with expert
classes less well once the areas are right — which is uncomfortable and is
exactly why it is written down.

## D14 — Two "delineation failures" were bad reference data, not bad pixels  *(Stage 2)*
Checked the four failing reference areas against published sources rather than
trusting the label file. Two of the four were wrong in the label, and the
measurement had been right all along.

**Gokyo: we were measuring a different lake.** The label read
`Gokyo Cho / Dudh Pokhari`, reference 42.9 ha, and validated at 1.46×. But the
`coordinate_correction` in the same record says the anchor was moved to *"the
largest lake in the chain"* — and the largest lake in the Gokyo chain is
**Thonak Cho**, the fourth lake, not Dudh Pokhari, the third. The name and the
reference stayed with lake three while the measurement moved to lake four.

Settled **independently of area**, which matters because area is the quantity
under test: Stage 6 reads the lake surface at **4832 m** off the DEM. Thonak Cho
is 4834 m; Dudh Pokhari is 4700–4750 m and sits 2.8 km south. Against Thonak
Cho's 65.07 ha the same pixels validate at **0.96×**.

**Tilicho: the label asserted a consensus that does not exist.** It claimed
4.8 km², *"verified; consistent across sources"*. The sources are not
consistent:

| value | provenance |
|---|---|
| 4.8 km² | repeated in encyclopaedic and trekking sources; no method, no primary measurement |
| **3.54 km²** | Gandaki Province lake monitoring report (2024); same figure in the Landsat/NDWI Gandaki lake series 1988–2018 |

Two independent classifiers here agree with the smaller value — our NDWI rule
gives 3.46 km², ESA's own SCL water class 3.56 km² on the same scene — and the
DEM puts the surface at 4913 m against a published 4919 m, so this *is* Tilicho.
Adopting the measured figure: **1.01×**.

**Result: 4/8 → 6/8 within 25%.** Stated plainly, because it would be easy to
present this as the model getting better: **it did not.** Not one pixel changed.
Two labels were wrong and the measurement was right, which is the opposite of
the usual direction and is only visible because the reference areas were written
down with their provenance instead of as bare numbers.

**Still failing, and these are real:** Pyurepu 0.03× (the lake formed and
drained inside a week; our annual series sees the pre-2025 ponds) and South
Lhonak 0.35× (ESA's independent classifier finds the same ~0.57 km² at the same
location, so the disagreement is with the published outline, not within our
pipeline). Neither is a reference-provenance problem, so neither is fixed here.

**Process note.** The four references were originally recorded with confidence
labels ranging from "verified" to "commonly cited". Every one that turned out to
be wrong carried the word *verified*. The lesson taken is that a confidence
label written by the same person who copied the number is worth nothing; what
had value was the elevation cross-check, which came from a different sensor
entirely.

## D15 — Thame was a CASCADE of two lakes, and we track one of them  *(Stage 2/7)*
Checked the headline against the peer-reviewed account of the event
(Sapkota et al., *NHESS* 26:4131, 2026; ICIMOD Thame Valley GLOF 2024 report).
It is a materially more complicated event than our registry represents.

**What actually happened.** Two lakes, roughly 10 km upstream of Thame village:

| lake | elevation | area before the event | role |
|---|---|---|---|
| Upper Ngole Cho | 4,890 m | **0.11 ± 0.004 km²** | rock avalanche fell in; displacement wave eroded its moraine dam; **failed first** |
| Lower Ngole Cho / Ngole Pokhari | 4,718 m | 0.048 ± 0.01 km² | overtopped by the upper lake's release; **failed second** |

**Which one are we measuring?** The lower one. Our best pre-event measurement is
0.044 km² against Bisht et al.'s 43,902 m² (1.005×), and the lower lake is
0.048 ± 0.01 km². The upper lake is inside the same 7 km window — the 30 Jul
2024 scene carries persistent water bodies 633 m, 701 m and 815 m from our
anchor — but `find_anchor` deliberately resolves **one lake per registered
coordinate** (that rule exists to fix the flip-flop bug in D-anchor), and the
registry has a single Thame entry. So the pipeline sees the upper lake every run
and never assesses it.

**This qualifies the headline, and the qualification must travel with it.** Our
claim is that the lake sat below the 0.1 km² screen. That is true of the lake we
measure. It is *not* true of the lake that initiated the cascade: at
0.11 km², Upper Ngole was marginally **above** the Rounce screen, and it had
grown roughly sixfold since 2010 (0.018 → 0.11 km²). A growth screen with a
long enough baseline, pointed at the right lake, could have flagged it.

**What survives the qualification, and why the claim is not withdrawn:**

* The NHESS authors state the lakes "were missed in the previous GLOF hazard and
  risk assessments at regional and local scales", and name "minimum lake-size
  thresholds for screening glacial lakes" as the reason. The screening failure
  is not our inference; it is the finding of the people who studied the event.
* Our proxies fired on the mechanism that was actually reported. On the lake we
  do measure, the engine fired `rock_landslide_source`, `ice_avalanche_source`,
  `impulse_wave` and `steep_lakefront_area`, with a source-to-lake volume ratio
  of 24.23 — an avalanche-into-lake displacement wave overtopping the dam. That
  is the published mechanism, and both lakes sit beneath the same source slopes.
* The two lakes are 172 m apart vertically and share a catchment. Terrain proxies
  computed on one are not independent of the other.

**What would settle it.** Registering Upper Ngole as its own entry and screening
it directly. Not done here: neither the NHESS paper nor the ICIMOD report
publishes coordinates for the two lakes, and picking a component off our own
imagery and *calling* it Upper Ngole would be assuming the answer to the
question being asked. Recorded as an open gap rather than guessed.

**Naming.** ICIMOD's press release calls the source "Thyanbo glacial lake"; the
NHESS paper calls the pair "Upper/Lower Ngole Cho". Both names are in circulation
for the same event; the registry keeps `thyanbo_tsho` because it keys the pinned
scene directory.

## D16 — The one source volume we can check, we underestimate 48×  *(Stage 4)*
The `source_to_lake_volume_ratio` carries the headline. Until now nothing
external constrained it. The published reconstruction of the 4 Oct 2023 Sikkim
flood supplies one number that does.

| | volume |
|---|---|
| observed debris into South Lhonak | **38,310,000 m³** (plus ~7,000,000 m³ calved ice) |
| our Stage 4 estimate | **805,200 m³** |
| our upper bound if the *whole* source zone failed | 16,104,000 m³ |

We are **47.6× low**, and 2.4× below even our own whole-zone bound. The estimate
is `source area 1,610,400 m² × 0.05 release fraction × 10 m assumed depth`. The
source *area* is not the problem; the **5% release fraction and the 10 m
assumed failure depth** are, and neither is constrainable from a single DSM —
which the proxy record already says, in its own `volume_caveat`.

It also explains the miss. South Lhonak scores 0.05 and never approaches the
5.0 alarm. With the observed volume it would score ≈2.3 — still below 5.0, so
**the geometry was never the whole story here**: the failure was a deep-seated
lateral-moraine collapse plus glacier calving, which is a different mechanism
from the avalanche-into-lake case the ratio is built for.

**Not retuned, deliberately.** Fitting the release fraction to one observation
is calibrating on n=1, and it would move the alarm status of every lake. Two
things make leaving it alone defensible:

* South Lhonak is a designated calibration lake, so we *could* have tuned on it
  without touching the holdouts. We did not, and this entry records that the
  option existed and was declined rather than overlooked.
* The ratio scales **linearly** with the release fraction, so the *ranking* is
  invariant to it. Thame ranks first whatever constant is chosen. That is a
  further argument for reporting the rank rather than the threshold — the
  headline does not depend on the number we are least sure of.

**The honest summary:** the absolute values of this proxy are, on the single
occasion they can be checked, wrong by a factor of fifty. Its ordering may still
be useful. Those are different claims and only the second one is made.

## D17 — The Langtang-Lirung disaster, 26 Aug 2026  *(context; not a data case)*
Four days before this was written, the deadliest event in the project's subject
area happened, and it is instructive precisely because **our tool would have
been silent on it.**

**Facts as understood on 30 Aug 2026. Attribution is four days old and
provisional; every figure here will move.**

| | |
|---|---|
| date | 26 August 2026 |
| place | Langtang-Lirung north slope, Rasuwa / Gyirong border (28.2853, 85.5252) |
| mechanism | bedrock failure at ~5,200 m; glacier-and-rock block ~600 m wide fell ~1,200 m |
| detached volume | **100–200 million m³** |
| what it did | blocked the Lhende Khola, impounded a lake behind the debris, the dam burst |
| seismic signal | equivalent to M5.2 |
| toll | 579 dead, ~400 missing (29–30 Aug) |
| warning | SMS as the flood emerged; lead time "minutes rather than hours" |
| **classification** | **NOT a GLOF.** A rock-ice avalanche. Initially suspected as a GLOF |

### Why this matters to a project about glacial lakes

**1. It is the negative control, live.** The whole reason `chamoli_ronti` is in
this repository is that Chamoli 2021 was a rock-ice avalanche reported worldwide
as a lake burst. Five years later the same misattribution ran again, at greater
cost, in the first hours of reporting. The discrimination this project tests is
not a methodological nicety; it is the question that was actually open last week.

**2. Same river, two mechanisms, fourteen months apart.** Our
`pyurepu_supraglacial` case *is* the July 2025 Lhende Khola flood — a genuine
supraglacial GLOF from Tibet. The August 2026 event hit the same river and was
not a GLOF at all. A pipeline that labels both "glacial flood" has destroyed the
distinction that determines the response: one implies watching lakes, the other
implies watching slopes.

**3. It falls outside our screening scope, and that is a limitation, not a
defence.** This pipeline screens *lakes*. It requires 5,000 m² of impounded
water before it will assess anything — the rule that makes the Chamoli control
work. Langtang-Lirung's initiating slope held no lake, so our watcher would have
had nothing to say about it. The hazard class that killed 579 people is one this
tool does not cover.

**4. It is 16 km outside the window we would have been looking at.** Measured
from our Pyurepu window centre, the 2026 source is 16.2 km away — well beyond
the 3.5 km half-width. LIMITS already says a lake-centred window is the wrong
analysis domain and that corridors are truncated by it. This is that limitation,
demonstrated at scale.

**5. Our volume model is not built for this magnitude.** D16 records that we
underestimated South Lhonak's 38.31 million m³ detachment by 47.6×, with a
whole-zone upper bound of 16.1 million m³. A 100–200 million m³ collapse is an
order of magnitude beyond even that bound. The `source_to_lake_volume_ratio` asks
the right question — how much mass can arrive versus how much water is there —
and its absolute answers are not calibrated for events of this size.

**6. It confirms the framing we chose.** "Lead time measured in minutes rather
than hours" is what the researchers reported. This project has consistently
declined to describe itself as a warning system, and the reason is exactly this:
susceptibility screening tells you where to put instruments, and instruments are
what buy minutes.

### Deliberately NOT added as a data case
Tempting, and wrong for now. The attribution is four days old, the toll is still
rising, and no pre-event scene analysis has been published. Adding a live event
to a hindcast evaluation set — with a cutoff we would have to define ourselves,
against ground truth that does not exist yet — would be the exact hindsight leak
the cutoff machinery in Stage 4 exists to prevent. Recorded as context, and as
the obvious next case once the reconstruction is published.

### One small, real vindication
Coverage renders the collapse as "the equivalent of 40,000–80,000 Olympic-sized
swimming pools". The analogy guard added to the reconciliation agent this week —
written for ICIMOD's "185 Olympic-size swimming pools" in the Thame study —
fires on the current reporting of this disaster. The failure mode it was built
for is house style, not a one-off.

## D18 — We validated the input and never the output  *(Stage 6)*
The project validated lake **area** on eight lakes and called that validation.
It never checked a routed **corridor** against what any flood actually did —
and the corridor is the part a district officer would act on.

Checked now, against published post-event observations
(`data/labels/observed_impacts.json`, `tools/validate_routing.py`):

| event | predicted runout | observed reach | short by |
|---|---|---|---|
| Thame 2024 | 0.43 km | 10 km (village hit) | **23.5×** |
| South Lhonak 2023 | 3.48 km | 60 km (Chungthang dam) | **17.2×** |
| Rasuwa 2025 | 2.73 km | 36 km (Rasuwagadhi) | **13.2×** |
| Chamoli 2021 | 4.21 km | 25 km (Tapovan) | **5.9×** |

**0 of 4 corridors reach the nearest observed impact.**

**The cause is the analysis domain, not the routing rule.** Every lake is
analysed inside a 7 km window, so no corridor can exceed ~3.5 km from the lake
whatever the physics does; two of the four terminate at the window edge with the
truncation flag already set. Debris transport for these events ran 25–169 km.
The routing is being asked to describe a valley it cannot see.

**What this changes in how the corridors may be described.** Runout is a
**lower bound**, not an inundation extent, and D11's "exposure counts are weak
lower bounds" was understated: 14 lakes yield 2 buildings because the corridors
stop in the headwaters, above everything worth counting. No statement of the
form "this river can affect this area" is supportable from the current outputs.

**What would fix it,** in order of what each unlocks:

1. **A river-network domain instead of a box.** Fetch DEM along the downstream
   flow path until the corridor terminates on its own or leaves the basin. This
   is the single blocking change; everything below depends on it. Needs network,
   so it belongs in Stage 1, outside `reproduce`.
2. **Exposure along the whole path** — OSM assets and WorldPop over the real
   corridor, which is what turns a corridor into "these settlements, this many
   people, these bridges".
3. **Volume-driven scenarios.** The volume bands already exist per lake; route a
   given release and report reach plus assets, with the band carried through as
   a range rather than collapsed to a point.
4. **Re-run this validator.** The harness is built and the ground truth is
   committed, so the next attempt is measured the day it lands rather than
   assumed.

**Why the finding is kept rather than fixed quietly.** A corridor that stops
0.43 km from a lake whose flood destroyed a village 10 km away is not a small
calibration error; it is the wrong answer to the question. Publishing the factor
is the only thing that makes the next version's number mean anything.

## D19 — Long-range routing: 0/4 to 1/4, and five bugs on the way  *(new)*
D18 measured the corridors against reality and found every one short by 5.9x to
23.5x, diagnosing the 7 km analysis window as the cause. This is the fix and its
result.

**What was built.** `src/data/fetch_downstream.py` pulls a 100 x 100 km
Copernicus GLO-30 mosaic per lake, resampled to 90 m (3 MB each, against ~40 MB
at native resolution — long-range reach does not need 30 m, and the corridor is
explicitly indicative). `src/watcher/routing_long.py` routes on it.
`tools/run_long_routing.py` runs it; `tools/validate_routing.py` scores it.

| event | Stage 6 (7 km) | long (100 km) | observed | short by |
|---|---|---|---|---|
| Thame 2024 | 0.43 km | **11.76 km** | 10 km | **0.9x — reaches it** |
| Chamoli 2021 | 4.21 km | **16.09 km** | 25 km | 1.6x |
| Rasuwa 2025 | 2.73 km | **10.02 km** | 36 km | 3.6x |
| South Lhonak 2023 | 3.48 km | 0.87 km | 60 km | **69x — still fails** |

**Five bugs, all found by the measurement rather than by reading the code.**
Recorded because each is a trap that looks like working code:

1. **The pit fill was a no-op.** `minimum_filter(z, size=3)` includes the centre
   cell, so its output is always <= z and the test `z < mn` never fires. The
   footprint must exclude the centre. Every corridor died in the first hollow.
2. **A FIFO steepest-descent walk is a single thread of cells.** It stalls at
   flats and confluences, and produced corridors *shorter* than the window it
   was built to escape.
3. **A priority-flood spanning tree is a catchment, not a river.** Every lake
   returned the same 70.6 km — the corner of the box — and following its parent
   chain gave 150–352 km, because a traversal tree meanders around a basin.
4. **The reach angle cannot gate each step.** At the outlet the drop is ~0 over
   one cell, so the test rejects the first move and the flow never develops:
   D8's lesson, rediscovered on a coarser grid. The Fahrboeschung describes
   where a deposit *ends*, so it must be applied after the walk, not during it.
5. **A lake sits in a depression, so its outlet is not adjacent to it.** Pit
   filling raises the whole basin, and descent from inside is stuck on step
   zero. The spill point has to be found first, by priority flood over the
   original surface.

Plus two data traps: the mosaics declare **no nodata and pad with a row of exact
zeros**, which is a bottomless sink in a domain whose lowest real ground is
496 m; and an **equal-area disc is the wrong seed for an elongated lake** —
South Lhonak is ~2 km long against a 450 m disc, so most of the lake sat outside
the seed as flat ground at exactly lake level, and the walk stalled on it.

**South Lhonak still fails, and the likely reason is physical, not numerical.**
Its flood breached a moraine dam. A purely topographic descent starts at the
spill point of the *intact* surface, and GLO-30 shows the moraine unbreached, so
there is no downhill path out of the basin at 90 m. Routing a dam-break needs
the dam to be breached in the DEM first — an assumption the current code does
not make and should not make silently. Left failing and labelled.

**Status of the original question.** "Given a volume, which areas are affected"
is now answerable to within a factor of ~1–4 on three of four hindcast events,
against a lake-area-only validation before. It is not yet exposure-linked: the
downstream asset counting still runs on the Stage 6 corridors, so "this river
affects this settlement and this many people" remains built but not connected.

## D20 — Corridors now name the places, and the places check out  *(new)*
D19 got corridors out of the headwaters. This connects them to what is
downstream and scores the result against the settlements the floods actually
destroyed.

**Built:** `tools/corridor_exposure.py` (OpenStreetMap along the routed
channel, 500 m buffer, cached to `data/pinned/<lake>/corridor_osm.json`),
`tools/build_scenarios.py` (the triage statement), and named-place scoring in
`tools/validate_routing.py`.

**The sharpest test in the project.** Not "did the corridor run far enough" — a
corridor down the wrong valley can satisfy that — but "does it pass the village
that was destroyed, at the right distance":

| place destroyed | observed | corridor | |
|---|---|---|---|
| Thame | 10 km | **7.6 km** | found |
| Rasuwagadhi | 36 km | **35.1 km** | found |
| Reni | 13 km | **22.3 km** | found, 1.7x |
| Tapovan | 25 km | — | missed |
| Chungthang | 60 km | — | missed (South Lhonak corridor stops at 31 km) |

**3 of 5 found, all 3 at the right distance.** Rasuwagadhi at 35.1 km against
a published 36 km is the strongest single result the routing has produced.
An earlier version of this table put Reni at 43.8 km — "3.4x too far down" —
and blamed the routing. The routing was innocent: the corridor polyline was
being ordered by straight-line distance from the lake, so every river bend
interleaved vertices from different reaches, and along-channel distances were
measured along a zigzag (Chamoli's 104 km channel summed to 249 km). The map
UI made the bug visible — a label reading "Birahi · 202.3 km" on a 104 km
corridor — and preserving the router's own walk order fixed all three
distances at once. Bug 6 below.

**Exposure, before and after.** Stage 5 found **2 buildings and no population
across all fourteen lakes**, because its corridors stop above anything worth
counting. Along the routed channels: Thame 88 assets (29 settlements, 15
schools, 2 hydropower), Rasuwa 64, Chamoli 100. The assets were always there;
the analysis domain could not see them.

**Six bugs worth recording:**

1. **An empty Overpass response was cached as an answer.** Under load these
   endpoints return HTTP 200 with zero elements. Two lakes reported *no assets*
   along 126 km and 31 km of Himalayan valley — "the query failed" rendered as
   "there is nothing downstream", which is the most dangerous wrong answer this
   tool could give. An empty element list is now a failure, retried across
   mirrors and never cached.
2. **The Stage 5 query does not scale.** Asking for every building along 100 km
   of valley times Overpass out (HTTP 504). Buildings are also the least useful
   class at corridor scale; the query now asks for settlements, hydropower,
   bridges, schools and health facilities.
3. **Latin-only ground truth misses places OSM tags in local script.**
   Rasuwagadhi is tagged रसुवागढी and scored as a MISS until aliases existed —
   the best result in the table was being reported as a failure.
4. **The population coverage metric conflated "no data" with "no people".**
   It scored coverage as *finite cells / cells in buffer*. WorldPop constrained
   is nodata wherever no building was detected, which over a Himalayan gorge is
   most of the corridor — so the tool reported *0% of the corridor covered*
   next to a population of 5,222, which cannot both be true. Coverage now means
   "inside the raster's own extent", the only thing that is genuinely a gap,
   and nodata inside Nepal is summed as the measured zero it is. Corridors that
   leave Nepal entirely (Chamoli, South Lhonak) now report *not measured*
   rather than a population of zero.
5. **A zero inside the buffer read as an empty valley.** Gokyo routes past 21
   OSM settlements and still summed to zero people, because WorldPop places
   people on building footprints and the nearest one is **696 m** from the
   channel while the buffer is 500 m. The zero was true of the band and false
   of the valley. A zero now carries the distance to the nearest populated cell
   and the population within 2 km — 1,161 people, in Gokyo's case.

6. **The corridor polyline was ordered by distance-from-lake, not walk
   order.** `route_long` walks the channel cell by cell but returned only a
   boolean mask; the exporter rebuilt a line by sorting masked cells on
   straight-line distance from the seed, which interleaves the bends of a
   meandering river. Every along-channel distance downstream of the first
   bend was wrong, and always too long. Preserving the walk order (filtered
   by the same deposition limit as the mask, so raster and polyline stay the
   same cell set) moved Reni from 43.8 km to 22.3 km against 13 observed —
   turning the routing's apparent worst distance miss into a pass.

**Overpass rate-limiting, handled rather than fought.** The mirror list only
helps when a host is *down*; throttling is per-IP and applies across all of
them, so rotating hosts buys nothing and only waiting does. Retries now back
off 30/90/240/600 s and honour `Retry-After`. More importantly a throttled lake
no longer aborts the run for the other thirteen, and — the part that matters —
its record carries `osm_available: false` so that a lake nobody asked about
cannot render as a lake with nothing downstream. The same flag covers Hongu 2,
which has no corridor to query along at all.

**What the scenarios deliberately refuse to say.** Every figure is a range:
volumes carry 50 to >400% error, and reach is a *bracket* between the 11 deg
debris and 3 deg clear-water regimes that is often two orders of magnitude
wide. The observed reach fell inside that bracket 2 times out of 4. Assets are
listed by position within 500 m of a routed channel — no depth, no discharge,
no hydraulics anywhere in the chain. And nothing says *when*: the trigger is an
avalanche nobody observes in advance.

**Still open.** South Lhonak (its dam is unbreached in the DEM, D19), Tapovan
and Chungthang, and the bracket width, which is wide enough that containing the
answer is not the same as predicting it.
