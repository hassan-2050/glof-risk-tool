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
