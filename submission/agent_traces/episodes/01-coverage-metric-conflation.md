# A metric that reported 0% coverage beside 5,222 people

**Why this one.** The agent is told a metric is wrong, fixes it, and then discovers the same conflation twice more in places nobody asked it to look - two corridors outside the raster reporting 0 people, and Gokyo reporting 0 people beside 21 settlements. It verifies the 696 m claim independently before writing it into an output. Feedback shaping the next step, three times over.

Tool output is truncated here for reading; the complete record is in `raw/session.jsonl`.

---

### AGENT &nbsp;<sub>2026-08-30 20:04:38</sub>

Two problems. The population coverage metric is wrong — it conflates "outside the raster" with "no buildings here", which for a *constrained* product is a measured zero. And Overpass is rate-limiting. Fixing the metric:

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ./.venv/Scripts/python.exe - <<'PY'\nfrom pathlib import Path\np = Path(\"tools/corridor_exposure.py\"); t = p.read_text(encoding=\"utf-8\")\na = '''    vals = arr[mask]\n    covered = np.isfinite(vals)\n    if not mask.any():\n        return {\"available\": False, \"reason\": \"no corridor cells on the grid\"}\n    return {\n        \"available\": True,\n        \"population\": round(float(np.nansum(vals)), 1),\n        \"cells_in_buffer\": int(mask.sum()),\n        \"cells_with_data\": int(covered.sum()),\n        \"coverage_fraction\": round(float(covered.sum()) / float(mask.sum()), 3),'''\nb = '''    if not mask.any():\n        return {\"available\": False, \"reason\": \"no corridor cells on the grid\"}\n\n    # Coverage means \"inside the raster\", NOT \"has a population value\".\n    #\n    # WorldPop constrained is nodata wherever no building was detected, which\n    # over a Himalayan gorge is most cells - and a measured zero, not a gap.\n    # Scoring coverage as finite/total conflated the two and reported \"0% of\n    # the corridor covered\" beside a population of 5,222, which is a\n    # self-contradiction. Only cells outside the raster's own bounds are\n    # genuinely uncovered.\n    inside = np.zeros_like(mask)\n    rr_i, cc_i = np.where(mask)\n    inside[rr_i, cc_i] = ((rr_i >= 0) & (rr_i < h) & (cc_i >= 0) & (cc_i < w))\n    outside_raster = mask & ~np.isfinite(arr) & ~in_bounds\n    covered_cells = int(mask.sum() - outside_raster.sum())\n    vals = np.where(np.isfinite(arr), arr, 0.0)[mask & in_bounds]\n    return {\n        \"available\": True,\n        \"population\": round(float(vals.sum()), 1),\n        \"cells_in_buffer\": int(mask.sum()),\n        \"cells_inside_raster\": covered_cells,\n        \"coverage_fraction\": round(covered_cells / float(mask.sum()), 3),'''\nassert t.count(a) == 1\nt = t.replace(a, b)\na2 = '''    if nodata is not None:\n        arr[arr == nodata] = np.nan\n    h, w 
... [truncated]
```

**&#8627; Bash responded**

```
/etc/profile.d/git-prompt.sh: line 28: C:/Program Files/Git/mingw64/share/git/completion/git-completion.bash: No such file or directory
coverage metric corrected
parse ok
```

### AGENT &nbsp;<sub>2026-08-30 20:05:02</sub>

You've hit your session limit · resets 4:10am (Asia/Karachi)

### HUMAN &nbsp;<sub>2026-08-30 20:42:00</sub>

> Continue from where you left off.

### AGENT &nbsp;<sub>2026-08-30 20:42:00</sub>

No response requested.

### HUMAN &nbsp;<sub>2026-08-30 20:42:15</sub>

> ok continue

**&#8594; calls `Bash`**

```json
{
 "command": "ls tools/ && echo \"--- wc ---\" && wc -l tools/*.py",
 "description": "List tools directory"
}
```

**&#8594; calls `Bash`**

```json
{
 "command": "cat tools/corridor_exposure.py",
 "description": "Read corridor_exposure.py"
}
```

**&#8627; Bash responded**

```
"""What lies along the routed corridor: settlements, bridges, hydropower.

    python -m src.data.fetch_downstream      # DEM, once
    python tools/run_long_routing.py         # corridors
    python tools/corridor_exposure.py        # -> outputs/tools/corridor_exposure.json

NEEDS NETWORK on first run (OpenStreetMap via Overpass). Results are cached to
data/pinned/<lake>/corridor_osm.json so later runs are offline.

WHY THIS IS NOT STAGE 5
-----------------------
Stage 5 counts assets inside a 7 km box around the lake. Across fourteen lakes
that found two buildings and no population, because the corridors stop in the
headwaters above anything worth counting (D11, D18). This counts along the
routed channel instead, over 100 km, which is where the assets actually are.

WHAT IT ANSWERS
    "If this lake releases, what is in the way, and how far down?" - a list of
    named places ordered by distance along the channel.

WHAT IT DOES NOT ANSWER
    Whether any of them floods. There is no depth, no discharge and no
    hydraulics here: an asset is listed if it lies within the corridor buffer,
    which is a screening statement about position, not an inundation call.
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import REPO_ROOT, load_config          # noqa: E402
from src.common.io import TOOL_OUT
... [14,428 more characters truncated]
```

**&#8627; Bash responded**

```
__pycache__
build_map_data.py
build_map_page.py
build_scenarios.py
check_map_page.mjs
corridor_exposure.py
make_overview_pdf.py
map_template.html
run_long_routing.py
validate_routing.py
--- wc ---
  334 tools/build_map_data.py
   49 tools/build_map_page.py
  201 tools/build_scenarios.py
  359 tools/corridor_exposure.py
  343 tools/make_overview_pdf.py
  178 tools/run_long_routing.py
  242 tools/validate_routing.py
 1706 total
```

### AGENT &nbsp;<sub>2026-08-30 20:42:39</sub>

Let me tidy the double-open (bounds are available in the first read) and check the cache state:

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ls data/pinned/*/corridor_osm.json 2>/dev/null | sed 's|data/pinned/||;s|/corridor_osm.json||' | tr '\\n' ' '; echo; echo \"--- lakes in long_routing ---\"; ./.venv/Scripts/python.exe -c \"\nimport json;d=json.load(open('outputs/tools/long_routing.json'))\nprint(len(d['lakes']),'lakes')\nprint(' '.join(l['lake_id'] for l in d['lakes']))\n\"; echo \"--- worldpop ---\"; ls -la data/pinned/exposure/*.tif 2>/dev/null",
 "description": "Check cache coverage and inputs"
}
```

**&#8627; Bash responded**

```
chamlang_tsho chamoli_ronti gokyo_dudh_pokhari hongu_1 imja_tsho lower_barun lumding_tsho pyurepu_supraglacial south_lhonak thulagi thyanbo_tsho 
--- lakes in long_routing ---
14 lakes
chamlang_tsho chamoli_ronti gokyo_dudh_pokhari hongu_1 hongu_2 imja_tsho lower_barun lumding_tsho pyurepu_supraglacial south_lhonak thulagi thyanbo_tsho tilicho tsho_rolpa
--- worldpop ---
-rw-r--r-- 1 ncai 197121 5051464 Aug 29 13:05 data/pinned/exposure/worldpop_npl_2020_constrained.tif
```

### AGENT &nbsp;<sub>2026-08-30 20:43:04</sub>

The metric is right but it opens the raster twice; bounds come free from the first read. Tightening that, then making one rate-limited lake stop killing the whole run:

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ./.venv/Scripts/python.exe - <<'PY'\nfrom pathlib import Path\np = Path(\"tools/corridor_exposure.py\"); t = p.read_text(encoding=\"utf-8\")\n\nold = '''            tr = src.window_transform(win)\n            nodata = src.nodata\n    except Exception as exc:                              # noqa: BLE001\n        return {\"available\": False, \"reason\": f\"{type(exc).__name__}: {exc}\"}\n\n    if nodata is not None:\n        arr[arr == nodata] = np.nan\n    h, w = arr.shape\n    # Which window cells actually lie within the source raster's own extent.\n    # boundless reads pad with NaN outside it, and those pads are the only\n    # cells that count as \"not covered\".\n    try:\n        with rasterio.open(worldpop_path) as src:\n            b_ = src.bounds\n        cols_ax = np.arange(w)\n        rows_ax = np.arange(h)\n        xs = tr.c + (cols_ax + 0.5) * tr.a\n        ys = tr.f + (rows_ax + 0.5) * tr.e\n        in_bounds = (((xs >= b_.left) & (xs <= b_.right))[None, :]\n                     & ((ys >= b_.bottom) & (ys <= b_.top))[:, None])\n    except Exception:                                     # noqa: BLE001\n        in_bounds = np.isfinite(arr)\n    if h == 0 or w == 0:\n        return {\"available\": False, \"reason\": \"corridor outside the raster\"}\n'''\nnew = '''            tr = src.window_transform(win)\n            nodata = src.nodata\n            bounds = src.bounds\n    except Exception as exc:                              # noqa: BLE001\n        return {\"available\": False, \"reason\": f\"{type(exc).__name__}: {exc}\"}\n\n    if nodata is not None:\n        arr[arr == nodata] = np.nan\n    h, w = arr.shape\n    if h == 0 or w == 0:\n        return {\"available\": False, \"reason\": \"corridor outside the raster\"}\n\n    # Which window cells lie inside the source raster's own extent. A boundless\n    # read pads with NaN beyond that extent, and those pads are the only cells\n    # that count as \"no
... [truncated]
```

**&#8627; Bash responded**

```
single-open bounds ok
parse ok
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && grep -rn \"corridor_exposure\" --include=*.py --include=*.md --include=*.mjs --include=*.html --include=Makefile --include=*.ps1 . | grep -v \"^./tools/corridor_exposure.py\" | grep -v __pycache__",
 "description": "Find consumers of corridor_exposure.json"
}
```

**&#8627; Bash responded**

```
./docs/DECISIONS.md:654:**Built:** `tools/corridor_exposure.py` (OpenStreetMap along the routed
./make.ps1:32:    "scenarios"          { & $py tools/run_long_routing.py; if ($?) { & $py tools/corridor_exposure.py }; if ($?) { & $py tools/build_scenarios.py }; if ($?) { & $py tools/validate_routing.py } }
./Makefile:71:	$(PY) tools/corridor_exposure.py
./tools/build_scenarios.py:76:    exp_path = SITE / "corridor_exposure.json"
./tools/validate_routing.py:64:    exp_path = SITE / "corridor_exposure.json"
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && sed -n '55,120p' tools/build_scenarios.py; echo \"=== validate_routing ===\"; sed -n '55,110p' tools/validate_routing.py",
 "description": "Read consumers of the exposure JSON"
}
```

**&#8627; Bash responded**

```
"bridge": ("bridge", "bridges"),
    "road": ("major road", "major roads"),
    "building": ("building", "buildings"),
}


def _fmt_m3(v: float | None) -> str:
    if not v:
        return "unknown"
    if v >= 1e6:
        return f"{v / 1e6:.1f} million m3"
    return f"{v:,.0f} m3"


def main() -> int:
    lakes = {l["id"]: l for l in
             read_json(REPO_ROOT / "data" / "labels" / "lakes.json")["lakes"]}
    proxies = {r["lake_id"]: r for r in
               read_json(OUT / "stage04_proxies.json")["lakes"]}
    weval = read_json(OUT / "stage07_watcher_eval.json")["per_lake"]
    long = {r["lake_id"]: r for r in read_json(SITE / "long_routing.json")["lakes"]}
    exp_path = SITE / "corridor_exposure.json"
    exposure = ({r["lake_id"]: r for r in read_json(exp_path)["lakes"]}
                if exp_path.exists() else {})

    scenarios = []
    for lid, rec in sorted(long.items()):
        lake = lakes.get(lid, {})
        px = {p["proxy"]: p for p in (proxies.get(lid) or {}).get("proxies", [])}
        band = (px.get("volume_band") or {}).get("value") or {}
        ev = weval.get(lid, {})

        runs = {k: v["max_runout_m"] / 1000.0 for k, v in rec["regimes"].items()}
        lo, hi = min(runs.values()), max(runs.values())
        truncated = any(v.get("truncated_at_domain_edge")
                        for v in rec["regimes"].values())

        exr = exposure.get(lid) or {}
        counts = exr.get("counts") or {}
        named = exr.get("named_assets") or []
   
... [4,102 more characters truncated]
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && sed -n '120,201p' tools/build_scenarios.py",
 "description": "Rest of build_scenarios"
}
```

**&#8627; Bash responded**

```
"physical bounds and the truth lies between them",
            },
            "assets_along_corridor": {
                "counts": counts,
                "population": exr.get("population_in_corridor"),
                "n_named": len(named),
                "nearest_named": nearest,
                "first_five": named[:5],
                "caveat": "position within 500 m of the routed channel; not an "
                          "inundation call",
            },
        })

    write_json(SITE / "scenarios.json", {"lakes": scenarios})

    lines = ["# Outburst scenarios", "",
             "One block per lake with a routed corridor. Every figure is a "
             "range. Nothing here predicts *when*.", ""]
    for s in scenarios:
        r, a = s["reach_km"], s["assets_along_corridor"]
        v = s["release_volume_band_m3"]
        lines += [f"## {s['name']}", ""]
        lines.append(
            f"- **If it releases** {_fmt_m3(v['central'])} "
            f"(range {_fmt_m3(v['low'])} to {_fmt_m3(v['high'])})")
        lines.append(
            f"- **Flow reaches** between **{r['bracket'][0]} km** (debris flow, "
            f"11 deg) and **{r['bracket'][1]} km** (clear water, 3 deg) down the "
            f"{s['basin'] or 'valley'}"
            + ("  \n  *corridor leaves the 100 km analysis domain, so the upper "
               "figure is a lower bound*" if r["truncated_at_domain_edge"] else ""))
        if a["counts"]:
            got = ", ".join(
                f"{n} {
... [2,563 more characters truncated]
```

### AGENT &nbsp;<sub>2026-08-30 20:44:15</sub>

Now the Overpass side. Three lakes (`hongu_2`, `tilicho`, `tsho_rolpa`) have no cached extract, and a failure there currently aborts the whole run — worse, a missing record reads downstream as "no assets", the same conflation one level up:

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ./.venv/Scripts/python.exe - <<'PY'\nfrom pathlib import Path\np = Path(\"tools/corridor_exposure.py\"); t = p.read_text(encoding=\"utf-8\")\n\nold = '''def query_corridor(bbox, retries: int = 2) -> dict:\n    \"\"\"bbox is (minlon, minlat, maxlon, maxlat); Overpass wants S,W,N,E.\"\"\"\n    q = CORRIDOR_QUERY.format(bbox=f\"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}\")\n    last = None\n    for attempt in range(retries):\n        for url in ENDPOINTS:\n            try:\n                r = requests.post(\n                    url, data=q.encode(\"utf-8\"), timeout=300,\n                    headers={\"Content-Type\": \"application/x-www-form-urlencoded\",\n                             \"User-Agent\": \"glof-risk-tool/0.1 (research \"\n                                           \"prototype; contact via repository)\",\n                             \"Accept\": \"application/json\"})\n                if r.status_code == 200:\n                    doc = r.json()\n                    # An empty element list is treated as a FAILURE, not an\n                    # answer. Under load these endpoints return HTTP 200 with\n                    # zero elements, and caching that silently turns \"the query\n                    # failed\" into \"there is nothing downstream\" - which is the\n                    # most dangerous wrong answer this tool could give. Two of\n                    # four lakes reported no assets along 126 km and 31 km of\n                    # Himalayan valley before this check existed.\n                    if doc.get(\"elements\"):\n                        return doc\n                    last = f\"{url.split('/')[2]} returned 0 elements\"\n                else:\n                    last = f\"{url.split('/')[2]} HTTP {r.status_code}\"\n            except Exception as exc:                     # noqa: BLE001\n                last = f\"{url.split('/')[2]} {type(exc).__name__}\"\n        time.sleep(15 * (attempt + 1
... [truncated]
```

**&#8627; Bash responded**

```
backoff ok
parse ok
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ./.venv/Scripts/python.exe - <<'PY'\nfrom pathlib import Path\np = Path(\"tools/corridor_exposure.py\"); t = p.read_text(encoding=\"utf-8\")\n\nold = '''        cache = pinned / lid / \"corridor_osm.json\"\n        if cache.exists() and not args.refresh:\n            osm = read_json(cache)\n        else:\n            print(f\"  {lid}: querying Overpass over {len(line)} vertices ...\",\n                  flush=True)\n            osm = query_corridor(_bbox_of(line))\n            if not osm.get(\"elements\"):\n                raise RuntimeError(f\"{lid}: Overpass returned no elements; \"\n                                   \"refusing to cache an empty extract\")\n            write_json(cache, osm)\n            time.sleep(5)          # be a good citizen on a free endpoint\n'''\nnew = '''        cache = pinned / lid / \"corridor_osm.json\"\n        osm_error = None\n        if cache.exists() and not args.refresh:\n            osm = read_json(cache)\n        else:\n            print(f\"  {lid}: querying Overpass over {len(line)} vertices ...\",\n                  flush=True)\n            try:\n                osm = query_corridor(_bbox_of(line))\n            except RuntimeError as exc:\n                # A throttled lake must not abort the other thirteen, and must\n                # not be allowed to LOOK like a lake with nothing downstream.\n                # The record carries osm_available false so every consumer has\n                # to say \"not queried\" instead of printing an empty asset list.\n                osm, osm_error = {\"elements\": []}, str(exc)\n                print(f\"  {lid}: {exc}\\\\n      -> recorded as NOT QUERIED, \"\n                      \"not as empty\")\n            else:\n                write_json(cache, osm)\n                time.sleep(5)      # be a good citizen on a free endpoint\n'''\nassert t.count(old) == 1\nt = t.replace(old, new)\n\nold2 = '''        results.append({\n            
... [truncated]
```

**&#8627; Bash responded**

```
Traceback (most recent call last):
  File "<stdin>", line 95, in <module>
AssertionError
parse ok
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && tail -25 tools/corridor_exposure.py | cat -A | sed 's/\\$$//' | head -30",
 "description": "Inspect file tail exactly"
}
```

**&#8627; Bash responded**

```
tot = sum(counts.values())
        ptxt = (f", ~{pop['population']:,.0f} people "
                f"({pop['coverage_fraction']:.0%} of the corridor covered)"
                if pop.get("available") else ", population unavailable")
        print(f"  {lid}: {tot} assets within {CORRIDOR_BUFFER_M:.0f} m of "
              f"{results[-1]['corridor_length_km']} km of channel "
              f"({len(named)} named){ptxt}")

    doc = {
        "regime": args.regime,
        "buffer_m": CORRIDOR_BUFFER_M,
        "source": "OpenStreetMap contributors, ODbL",
        "caveat": ("Position, not inundation. An asset is listed because it "
                   "lies within the buffer of a routed channel; nothing here "
                   "models depth, discharge or whether water reaches it."),
        "lakes": results,
    }
    SITE.mkdir(parents=True, exist_ok=True)
    write_json(SITE / "corridor_exposure.json", doc)
    print("\n-> outputs/tools/corridor_exposure.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ./.venv/Scripts/python.exe - <<'PY'\nfrom pathlib import Path\nt = Path(\"tools/corridor_exposure.py\").read_text(encoding=\"utf-8\")\nprobes = {\n \"old  (cache block)\": '        cache = pinned / lid / \"corridor_osm.json\"\\n        if cache.exists()',\n \"old2 (results)\":     '        results.append({\\n            \"lake_id\": lid, \"name\": rec[\"name\"], \"regime\": args.regime,',\n \"old3 (print)\":       \"        tot = sum(counts.values())\",\n \"old4 (doc)\":         '        \"source\": \"OpenStreetMap contributors, ODbL\",',\n \"old5 (tail)\":        '    print(\"\\\\n-> outputs/tools/corridor_exposure.json\")\\n    return 0',\n}\nfor k, v in probes.items():\n    print(f\"{k}: {t.count(v)}\")\nprint(\"---- repr of tail ----\")\nprint(repr(t[-260:]))\nPY",
 "description": "Probe which pattern failed to match"
}
```

**&#8627; Bash responded**

```
old  (cache block): 1
old2 (results): 1
old3 (print): 1
old4 (doc): 1
old5 (tail): 0
---- repr of tail ----
'."),\n        "lakes": results,\n    }\n    SITE.mkdir(parents=True, exist_ok=True)\n    write_json(SITE / "corridor_exposure.json", doc)\n    print("\\n-> outputs/tools/corridor_exposure.json")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ./.venv/Scripts/python.exe - <<'PY'\nfrom pathlib import Path\nt = Path(\"tools/corridor_exposure.py\").read_text(encoding=\"utf-8\")\ni = t.index('-> outputs/tools/corridor_exposure.json')\nprint(repr(t[i-30:i+60]))\nprobe = '    print(\"\\\\n-> outputs/tools/corridor_exposure.json\")\\n    return 0'\nprint(\"probe:\", repr(probe), \"count:\", t.count(probe))\nPY",
 "description": "Byte-level compare of the tail probe"
}
```

**&#8627; Bash responded**

```
'corridor_exposure.py        # -> outputs/tools/corridor_exposure.json\n\nNEEDS NETWORK on fi'
probe: '    print("\n-> outputs/tools/corridor_exposure.json")\n    return 0' count: 0
```

### AGENT &nbsp;<sub>2026-08-30 20:45:47</sub>

Bash is eating one level of backslash in the heredoc, so the tail pattern never matched (nothing was written). Redoing the patch without any backslash escapes:
