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

* **Absolute areas are unreliable for calving lakes.** Imja reads 0.07x its
  published area, Tsho Rolpa 0.12x, South Lhonak 0.33x. The water is genuinely
  broken into disconnected patches by icebergs and debris, and any
  largest-connected-component rule under-measures it. Ruled out by measurement:
  thresholds, closing radius, floating-ice inclusion, and ESA's own classifier
  (DECISIONS D6). Absolute areas for those three must not feed an area screen.

* **Empirical volume estimates carry 50 to >400% error.** Cook & Quincey (2015)
  report r²=0.38 for area-depth. Volume is emitted as a band with that caveat
  inside the record, never as a point estimate.

* **Free 30 m DEMs are the binding constraint on flow routing.** In a valley
  50 m wide the channel is one to two pixels across and its cross-section is
  unresolved. Corridors are indicative, and the disclaimer travels as
  structured metadata rather than prose someone can crop out.

* **Optical monitoring is blindest exactly when GLOFs happen.** Every
  event-bracket scene for South Lhonak and Pyurepu is cloud-obscured; the Thame
  pre-event window contains no scene under 80% tile cloud. Three of our four
  events occur in or near monsoon season. This is a strong argument for
  Sentinel-1 SAR fusion and a real limit on any optical-only system.

* **Exposure counts are lower bounds, and weak ones.** Corridors are truncated
  by a 6 km analysis window while the Thame flood carried debris 80 km and
  South Lhonak's inundation ran 169 km. Twelve lakes yield two buildings and no
  population. Meaningful exposure needs a river-network domain, not a
  lake-centred window (DECISIONS D11).

* **Published binary proxies do not discriminate on this set.** Six of nine
  fire on 13/13 lakes. Eight of the eleven non-burst lakes are ICIMOD PDGL
  Rank-I lakes that experts already consider dangerous, so firing on them is
  correct - which is exactly why burst-recall alone is the wrong scoreboard
  (DECISIONS D7).

* **One threshold is not a blind holdout.** The source-to-lake volume alarm
  level was chosen after inspecting all fourteen values. The threshold-free
  rank statement is the defensible one and is what the headline uses.

* **The Nepali output is template-assembled, not machine-translated.**
  Terminology consistency is exact by construction. That is a property of the
  method, not a measured translation quality, and is reported as such.

## What this is

A research prototype and a hindcast. It is not an operational warning system,
it has no real-time path, and it must not be used to alert the public.
