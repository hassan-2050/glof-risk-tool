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
