# Limits

Stated plainly, because a screening tool whose failure modes are undocumented
is more dangerous than no tool.

## What this measures, and what it does not

It measures **lake area from optical satellite imagery** and **geometric
proxies from a 30 m DEM**. It does **not** measure moraine-dam internal
structure, ice-core presence, bathymetry, or pore pressure - the properties
that actually determine whether a dam fails. Every hazard statement here is an
inference from surface geometry, not a stability analysis.

## Quantified failure modes

* **Absolute areas are still unreliable on 2 of 8 validated lakes**, against
  published references. Under-measured: Pyurepu supraglacial lake 0.03x, South
  Lhonak 0.35x. Under-measurement is floating ice and debris breaking the
  water into disconnected patches, which any largest-connected-component rule
  loses; over-measurement is the opposite failure, adjacent wet ground and
  shadow joining the lake. Ruled out by measurement: thresholds, closing
  radius, floating-ice inclusion, and ESA's own classifier (DECISIONS D6).
  Absolute areas for these lakes must not feed an area screen.

* **Empirical volume estimates carry 50 to >400% error.** Cook & Quincey (2015)
  report r²=0.38 for area-depth. Volume is emitted as a band with that caveat
  inside the record, never as a point estimate.

* **Free 30 m DEMs are the binding constraint on flow routing.** In a valley
  50 m wide the channel is one to two pixels across and its cross-section is
  unresolved. Corridors are indicative, and the disclaimer travels as
  structured metadata rather than prose someone can crop out.

* **Optical monitoring is blindest exactly when GLOFs happen.** Only 1 of the
  16 pre-event scenes across our 4 events clears the cloud and snow QA gate. 3
  of 4 events - Chamoli / Ronti Gad, South Lhonak, Thyanbo Tsho - have no
  usable pre-event scene at all, so the last measurement before the burst
  comes from the annual series weeks or months earlier. Three of the four
  events fall in or near monsoon season. This is a strong argument for
  Sentinel-1 SAR fusion and a real limit on any optical-only system.

* **Exposure counts are lower bounds, and weak ones.** Corridors are truncated
  by a 6 km analysis window while the Thame flood carried debris 80 km and
  South Lhonak's inundation ran 169 km. 13 lakes yield 2 buildings and no
  population at all. Meaningful exposure needs a river-network domain, not a
  lake-centred window (DECISIONS D11).

* **Published binary proxies do not discriminate on this set.** Six of nine
  fire on 13/13 lakes. Eight of the eleven non-burst lakes are ICIMOD PDGL
  Rank-I lakes that experts already consider dangerous, so firing on them is
  correct - which is exactly why burst-recall alone is the wrong scoreboard
  (DECISIONS D7).

* **One threshold is not a blind holdout.** The source-to-lake volume alarm
  level was chosen after inspecting all 13 values - all 13, not all 14,
  because Chamoli impounds no water and carries no ratio. The threshold-free
  rank statement is the defensible one and is what the headline uses.

* **The Nepali output is template-assembled, not machine-translated.**
  Terminology consistency is exact by construction. That is a property of the
  method, not a measured translation quality, and is reported as such.

## What this is

A research prototype and a hindcast. It is not an operational warning system,
it has no real-time path, and it must not be used to alert the public.
