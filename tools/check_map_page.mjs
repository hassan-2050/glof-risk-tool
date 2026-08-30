// Verify outputs/map.html without a browser: parse it, syntax-check the
// script, then run the page's own pure logic against the real data.
//
// The extension was not connected, so "it renders" could not be observed
// directly. What CAN be observed is everything below - and every one of these
// caught something the first time it ran.
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync("outputs/tools/map.html", "utf8");
let fails = 0, checks = 0;
const ok = (name, cond, detail = "") => {
  checks++;
  if (!cond) { fails++; console.log(`  FAIL  ${name}${detail ? " — " + detail : ""}`); }
  else console.log(`  ok    ${name}${detail ? " — " + detail : ""}`);
};

/* ---------- 1. structure ------------------------------------------------ */
const dataM = html.match(
  /<script id="mapdata" type="application\/json">([\s\S]*?)<\/script>/);
ok("json payload element present", !!dataM);
const raw = dataM[1].replaceAll("<\\/", "</");
let DATA;
try { DATA = JSON.parse(raw); ok("payload parses", true, `${DATA.lakes.length} lakes`); }
catch (e) { ok("payload parses", false, e.message); process.exit(1); }

ok("no </script> escape leak", !dataM[1].includes("</script"));
ok("no external resource", !/src\s*=\s*"https?:|href\s*=\s*"https?:/.test(html));

const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
ok("page script present", scripts.length === 1);
try { new vm.Script(scripts[0]); ok("script parses as JS", true); }
catch (e) { ok("script parses as JS", false, e.message); }

/* ---------- 2. every id the script touches exists in the markup --------- */
const ids = new Set([...html.matchAll(/id="([\w-]+)"/g)].map(m => m[1]));
const used = new Set([...scripts[0].matchAll(/\$\("([\w-]+)"\)/g)].map(m => m[1]));
const missing = [...used].filter(i => !ids.has(i));
ok("every $(id) exists in markup", missing.length === 0, missing.join(", "));

/* ---------- 3. data integrity ------------------------------------------ */
let noHill = [], noFrames = [], badRing = [], outOfBounds = [];
for (const L of DATA.lakes) {
  if (!L.hillshade) noHill.push(L.lake_id);
  if (!L.frames?.length) noFrames.push(L.lake_id);
  const [w, s, e, n] = L.bounds;
  for (const f of L.frames) {
    for (const poly of f.rings) for (const ring of poly) {
      if (ring.length < 4) badRing.push(`${L.lake_id}/${f.label}`);
      for (const [lon, lat] of ring)
        if (lon < w - 1e-4 || lon > e + 1e-4 || lat < s - 1e-4 || lat > n + 1e-4)
          outOfBounds.push(`${L.lake_id}/${f.label}`);
    }
  }
}
ok("every lake has a hillshade", noHill.length === 0, noHill.join(","));
ok("every lake has frames", noFrames.length === 0, noFrames.join(","));
ok("no degenerate rings", badRing.length === 0, [...new Set(badRing)].join(","));
ok("all vertices inside declared bounds", outOfBounds.length === 0,
   [...new Set(outOfBounds)].slice(0, 3).join(","));

/* ---------- 4. geometry agrees with the measured areas ----------------- */
// Shoelace on the projected ring, in m². Simplification and the lat/lon round
// move this a little; 12% is the band that separates "the same lake" from
// "we drew the wrong component".
function ringAreaM2(rings, lat0) {
  const k = Math.cos(lat0 * Math.PI / 180) * 111320, m = 110540;
  let total = 0;
  for (const poly of rings) poly.forEach((ring, i) => {
    let a = 0;
    for (let j = 0; j < ring.length - 1; j++)
      a += (ring[j][0] * k) * (ring[j + 1][1] * m) - (ring[j + 1][0] * k) * (ring[j][1] * m);
    total += (i === 0 ? 1 : -1) * Math.abs(a / 2);
  });
  return total;
}
let worst = { d: 0 };
for (const L of DATA.lakes) for (const f of L.frames) {
  if (!f.rings.length || !f.area_m2) continue;
  const drawn = ringAreaM2(f.rings, (L.bounds[1] + L.bounds[3]) / 2);
  const d = Math.abs(drawn - f.area_m2) / f.area_m2;
  if (d > worst.d) worst = { d, id: `${L.lake_id}/${f.label}`, drawn, meas: f.area_m2 };
}
ok("drawn outline area matches measured area", worst.d < 0.12,
   `worst ${worst.id} ${(worst.d * 100).toFixed(1)}% ` +
   `(drawn ${Math.round(worst.drawn)} vs ${worst.meas} m²)`);

/* ---------- 5. the page's own screening logic, re-derived --------------- */
// Lifted verbatim from the template so a divergence here is a real bug.
const flagged = (L, t) => (L.score != null && L.score >= t) || !!L.growth_flagged;
function confusion(t) {
  let tp = 0, fp = 0, fn = 0, tn = 0;
  for (const L of DATA.lakes) {
    const p = flagged(L, t), a = !!L.label_burst;
    if (p && a) tp++; else if (p && !a) fp++; else if (!p && a) fn++; else tn++;
  }
  return { tp, fp, fn, tn, recall: tp + fn ? tp / (tp + fn) : 0 };
}
const pub = confusion(DATA.alarm_threshold);
const stage7 = JSON.parse(readFileSync("outputs/stage07_watcher_eval.json", "utf8"));
const cm = stage7.confusion_proxy_augmented;
ok("page reproduces Stage 7 at the published threshold",
   pub.tp === cm.n_tp && pub.fp === cm.n_fp && pub.fn === cm.n_fn && pub.tn === cm.n_tn,
   `page ${pub.tp}/${pub.fp}/${pub.fn}/${pub.tn} vs stage7 ` +
   `${cm.n_tp}/${cm.n_fp}/${cm.n_fn}/${cm.n_tn}`);

// The slider must actually move something, and monotonically.
const lo = confusion(0), hi = confusion(30);
ok("threshold 0 flags everything with a score", lo.tp + lo.fp === 13,
   `${lo.tp + lo.fp} flagged`);
// Not zero at the top of the range: the advanced model is a strict SUPERSET of
// the growth baseline, so lakes the growth screen flagged stay flagged however
// far the proxy threshold is pushed. That residual is the baseline showing
// through, and it must equal the baseline's own flag count exactly.
const growthFlags = DATA.lakes.filter(L => L.growth_flagged).length;
ok("above every score, only the growth baseline still flags",
   hi.tp + hi.fp === growthFlags,
   `${hi.tp + hi.fp} flagged, growth baseline flags ${growthFlags}`);
const b = stage7.confusion_growth_only;
ok("that residual matches Stage 7's growth-only matrix",
   growthFlags === b.n_tp + b.n_fp, `${growthFlags} vs ${b.n_tp + b.n_fp}`);
let mono = true, prev = 99;
for (let t = 0; t <= 30; t += 0.5) {
  const c = confusion(t), n = c.tp + c.fp;
  if (n > prev) mono = false;
  prev = n;
}
ok("flag count is monotone in the threshold", mono);

// The headline: Thame must top the ranking, with no threshold involved.
const rank = DATA.lakes.filter(L => L.score != null).sort((a, b) => b.score - a.score);
ok("Thame ranks first, threshold-free", rank[0].lake_id === "thyanbo_tsho",
   `${rank[0].lake_id} @ ${rank[0].score}`);
ok("ranking length matches Stage 7", rank.length === stage7.ranking.length,
   `${rank.length} vs ${stage7.ranking.length}`);
ok("ranking order matches Stage 7",
   rank.map(l => l.lake_id).join() === stage7.ranking.join());

/* ---------- 6. corridors agree with Stage 6 ---------------------------- */
const routing = JSON.parse(readFileSync("outputs/stage06_routing.json", "utf8"));
let corrMissing = [], corrExtra = [], corrArea = [];
for (const r of routing.lakes) {
  const L = DATA.lakes.find(x => x.lake_id === r.lake_id);
  if (!L) continue;
  for (const [regime, src] of Object.entries(r.regimes || {})) {
    const drawn = L.corridors[regime];
    const hasArea = (src.area_m2 || 0) > 0;
    if (hasArea && !drawn) corrMissing.push(`${r.lake_id}/${regime}`);
    if (!hasArea && drawn) corrExtra.push(`${r.lake_id}/${regime}`);
    if (hasArea && drawn && Math.abs(drawn.area_m2 - src.area_m2) > 1)
      corrArea.push(`${r.lake_id}/${regime}`);
  }
}
ok("every routed corridor is drawable", corrMissing.length === 0, corrMissing.join(","));
ok("no corridor drawn where routing found none", corrExtra.length === 0, corrExtra.join(","));
ok("corridor areas match Stage 6", corrArea.length === 0, corrArea.join(","));
// D8: the 11-degree debris rule genuinely yields nothing in gentle valleys.
const noDebris = DATA.lakes.filter(L => L.corridors.clearwater_flood &&
                                        !L.corridors.debris_flow).map(L => L.lake_id);
ok("lakes with no debris corridor are recorded, not silently empty",
   noDebris.length > 0, noDebris.join(",") || "none — check D8 still holds");

/* ---------- 7. downstream layer matches the tool artefacts -------------- */
// The 100 km layer is built from make-scenarios artefacts. Where those exist,
// the page must agree with them; where they do not, the page must say "not
// built" rather than draw nothing. Checked with the same rigour as Stage 6.
try {
  const rdTool = f => JSON.parse(readFileSync(`outputs/tools/${f}`, "utf8"));
  const longDoc = rdTool("long_routing.json");
  const expDoc = rdTool("corridor_exposure.json");
  const valDoc = rdTool("routing_validation.json");
  ok("page knows the downstream layer exists", DATA.downstream_available === true);

  const dsMissing = [], dsRunout = [], dsNamed = [], dsVal = [];
  for (const r of longDoc.lakes) {
    const L = DATA.lakes.find(x => x.lake_id === r.lake_id);
    if (!L) continue;
    const routed = Object.entries(r.regimes || {})
      .filter(([, v]) => (v.polyline_lonlat || []).length >= 2);
    if (!routed.length) {
      if (L.downstream) dsMissing.push(`${r.lake_id} drawn without geometry`);
      continue;
    }
    if (!L.downstream) { dsMissing.push(r.lake_id); continue; }
    for (const [regime, src] of routed) {
      const drawn = L.downstream.regimes[regime];
      if (!drawn) { dsMissing.push(`${r.lake_id}/${regime}`); continue; }
      if (Math.abs(drawn.runout_km - src.max_runout_m / 1000) > 0.011)
        dsRunout.push(`${r.lake_id}/${regime}`);
    }
  }
  for (const r of expDoc.lakes) {
    if (r.skipped) continue;
    const L = DATA.lakes.find(x => x.lake_id === r.lake_id);
    if (!L?.downstream) continue;
    if ((L.downstream.named || []).length !== r.n_named)
      dsNamed.push(`${r.lake_id}: ${(L.downstream.named || []).length} vs ${r.n_named}`);
    // The two refusal semantics must survive the trip onto the page.
    const pop = r.population_in_corridor || {};
    const drawnPop = L.downstream.population || {};
    if (!!pop.zero_note !== !!drawnPop.zero_note)
      dsNamed.push(`${r.lake_id}: zero-note lost`);
    if (pop.available === false && drawnPop.available !== false)
      dsNamed.push(`${r.lake_id}: not-measured lost`);
    if (r.osm_available === false && L.downstream.osm_available !== false)
      dsNamed.push(`${r.lake_id}: not-queried lost`);
  }
  for (const v of valDoc.per_event) {
    const L = DATA.lakes.find(x => x.lake_id === v.lake_id);
    if (!L?.downstream) continue;
    const places = (L.downstream.validation || {}).places || [];
    if (places.length !== (v.impacted_places || []).length)
      dsVal.push(v.lake_id);
  }
  ok("every long corridor is on the page, none invented", dsMissing.length === 0,
     dsMissing.join(","));
  ok("downstream runouts match long_routing", dsRunout.length === 0, dsRunout.join(","));
  ok("named assets and population semantics match corridor_exposure",
     dsNamed.length === 0, dsNamed.join(","));
  // Scenario-dial data: the counters must be the counts, and the cumulative
  // population curve must end at the corridor total.
  const dsDial = [];
  for (const r of expDoc.lakes) {
    if (r.skipped) continue;
    const L = DATA.lakes.find(x => x.lake_id === r.lake_id);
    if (!L?.downstream) continue;
    for (const [cls, n] of Object.entries(r.counts || {})) {
      const got = ((L.downstream.asset_km || {})[cls] || []).length;
      if (cls !== "road" && cls !== "building" && got !== n)
        dsDial.push(`${r.lake_id}/${cls}: ${got} vs ${n}`);
    }
    const pop = r.population_in_corridor || {};
    if (pop.available && !pop.zero_note) {
      const cum = ((L.downstream.population || {}).cum_km) || [];
      const last = cum.length ? cum[cum.length - 1][1] : 0;
      if (Math.abs(last - pop.population) > 0.5)
        dsDial.push(`${r.lake_id}: cum ends ${last} vs total ${pop.population}`);
    }
  }
  ok("dial counters equal the counts; cum curve ends at the total",
     dsDial.length === 0, dsDial.join(","));
  ok("documented-impact scoring matches routing_validation", dsVal.length === 0,
     dsVal.join(","));
} catch (e) {
  if (e.code === "ENOENT")
    ok("downstream artefacts absent and page says so",
       DATA.downstream_available === false, "make scenarios not run");
  else { ok("downstream layer check", false, e.message); }
}

/* ---------- 8. Thame is below the area screen, as claimed -------------- */
const thame = DATA.lakes.find(L => L.lake_id === "thyanbo_tsho");
ok("Thame sits below the area screen",
   thame.growth_area_km2 < DATA.area_screen_km2,
   `${thame.growth_area_km2} < ${DATA.area_screen_km2} km²`);
ok("Chamoli carries no score",
   DATA.lakes.find(L => L.lake_id === "chamoli_ronti").score == null);

console.log(`\n${fails ? "FAIL" : "PASS"}: ${checks - fails}/${checks} checks`);
process.exit(fails ? 1 : 0);
