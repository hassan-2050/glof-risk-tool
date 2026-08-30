# The map UI exposed a village 202 km down a 104 km channel

**Why this one.** A visual check catches an arithmetic bug no test had. The agent traces it from the label, through the exporter, to the router that lost the walk order - fixes the cause rather than the symptom, re-runs the chain, and the headline validation result IMPROVES (Reni 43.8 km -> 22.3 km). The retry loop and the root-cause discipline are both visible.

Tool output is truncated here for reading; the complete record is in `raw/session.jsonl`.

---

### AGENT &nbsp;<sub>2026-08-30 21:30:04</sub>

Labels show 202–241 km on a 104 km corridor — an along-channel accounting problem in the data. Measuring the polyline directly:

**&#8594; calls `mcp__Claude_Browser__javascript_tool`**

```json
{
 "action": "javascript_exec",
 "text": "const pl=sel.downstream.regimes.clearwater_flood.polyline;\nconst lat0=pl[0][1];\nlet total=0, maxSeg=0, jumps=[];\nfor(let i=1;i<pl.length;i++){const d=mBetween(pl[i-1],pl[i],lat0);total+=d;if(d>maxSeg)maxSeg=d;if(d>2000)jumps.push([i,Math.round(d)]);}\n({verts:pl.length, path_km:+(total/1000).toFixed(1), declared_runout:sel.downstream.regimes.clearwater_flood.runout_km, maxSeg_m:Math.round(maxSeg), jumps_over_2km:jumps.length, first_jumps:jumps.slice(0,5)})",
 "tabId": "seed"
}
```

**&#8627; mcp__Claude_Browser__javascript_tool responded**

```
{
  "declared_runout": 104.32,
  "first_jumps": [
    [
      8,
      2617
    ],
    [
      13,
      4715
    ],
    [
      14,
      2161
    ],
    [
      16,
      3895
    ],
    [
      17,
      4148
    ]
  ],
  "jumps_over_2km": 33,
  "maxSeg_m": 9230,
  "path_km": 249,
  "verts": 197
}


Tab Context:
- Executed on tabId: seed
- Available tabs:
  • tabId seed: "GLOF Watcher — interactive map" (http://localhost:8123)
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && cat src/watcher/routing_long.py",
 "description": "Read long routing implementation"
}
```

**&#8627; Bash responded**

```
"""Long-range corridor routing on the wide, coarse downstream DEM.

Stage 6 routes on the 7 km optical window, which caps every corridor at ~3.5 km
from the lake. This routes the same physics on `dem_downstream.tif` - a 100 km
box at 90 m - so a corridor can actually leave the headwaters.

WHAT IS THE SAME
    The Modified Single Flow descent, the lateral spread, and the reach-angle
    stop rule (Huggel et al. 2003). Changing the domain must not quietly change
    the model, or the comparison against Stage 6 means nothing.

WHAT IS DIFFERENT, AND WHY
  * 90 m cells, not 10 m. At 90 m a Himalayan gorge is one cell wide, so the
    corridor here is a FLOW PATH with an indicative buffer, not a width
    estimate. Stage 6 keeps the near-field geometry; this answers "how far, and
    past what".
  * Seeded from the lake's mapped outline projected onto the coarse grid, not
    re-delineated. Delineation is Stage 2's job and is done at 10 m.
  * Runs until the reach angle stops it, the flow leaves the domain, or a step
    budget is exhausted - whichever comes first, and it records which.

WHAT IT STILL CANNOT DO
    No hydraulics, no discharge, no depth, no timing. A corridor that exits the
    100 km box is still a lower bound; the flag just moves 14x further out.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

# Descent to the 8 neighbours, as (dr, dc, distance in cell units).
_NEIGHBOURS = [(-1, -1, math.sqrt(2)), (-1, 0, 1.0),
... [9,800 more characters truncated]
```

### AGENT &nbsp;<sub>2026-08-30 21:30:31</sub>

`route_long` walks an ordered path but returns only a boolean mask — the order is lost. Checking how `run_long_routing.py` builds the polyline:

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && grep -n \"polyline\\|flow_path\" tools/run_long_routing.py | head && sed -n '/polyline/,+25p' tools/run_long_routing.py | head -45",
 "description": "Find polyline construction"
}
```

**&#8627; Bash responded**

```
133:            # corridor goes, not just how far. Stored as a lon/lat polyline
136:            fp = r.pop("flow_path", None)
143:                r["polyline_lonlat"] = [[round(float(x), 5), round(float(y), 5)]
            # corridor goes, not just how far. Stored as a lon/lat polyline
            # down the channel, decimated to ~1 point per 5 cells - enough to
            # query assets against, far smaller than the raster.
            fp = r.pop("flow_path", None)
            r.pop("corridor", None)
            if fp is not None and fp.any():
                rows, cols = np.where(fp)
                order = np.argsort(dist_from_seed[rows, cols])
                rows, cols = rows[order][::5], cols[order][::5]
                xs, ys = rasterio.transform.xy(transform, rows, cols)
                r["polyline_lonlat"] = [[round(float(x), 5), round(float(y), 5)]
                                        for x, y in zip(xs, ys)]
            rec["regimes"][regime] = r

        near = (stage6.get(lid) or {}).get("regimes") or {}
        rec["stage6_max_runout_m"] = max(
            [(v.get("max_runout_m") or 0) for v in near.values()] or [0])
        rec["long_max_runout_m"] = max(
            v["max_runout_m"] for v in rec["regimes"].values())
        rec["gain_factor"] = (
            round(rec["long_max_runout_m"] / rec["stage6_max_runout_m"], 1)
            if rec["stage6_max_runout_m"] else None)
        results.append(rec)

    doc = {
        "n_lakes": len(results),
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ./.venv/Scripts/python.exe - <<'PY'\nfrom pathlib import Path\n\np = Path(\"src/watcher/routing_long.py\"); t = p.read_text(encoding=\"utf-8\")\nold = '''    r, c = _spill_point(dem, seed, z)\n\n    run_along, reached_edge, steps = 0.0, False, 0'''\nnew = '''    r, c = _spill_point(dem, seed, z)\n\n    walk = [(r, c)]                    # the descent, in the order it happened\n    run_along, reached_edge, steps = 0.0, False, 0'''\nassert t.count(old) == 1\nt = t.replace(old, new)\n\nold = '''        r, c = best\n        run_along += best_step * res_m\n        path[r, c] = True'''\nnew = '''        r, c = best\n        run_along += best_step * res_m\n        path[r, c] = True\n        walk.append((r, c))'''\nassert t.count(old) == 1\nt = t.replace(old, new)\n\nold = '''    if max_run > 0:\n        path &= (dist <= straight_run)\n    else:\n        path[:] = False\n'''\nnew = '''    if max_run > 0:\n        path &= (dist <= straight_run)\n        # The ordered walk, filtered by the SAME deposition limit as the mask,\n        # so the polyline and the raster describe the same set of cells. The\n        # order must come from here: sorting walked cells by distance from the\n        # seed - the first implementation - interleaves vertices from\n        # different bends of a meandering river, and Chamoli's 104 km channel\n        # summed to 249 km of zigzag, putting Birahi at \"202 km down-channel\".\n        walk = [(rr, cc) for rr, cc in walk if dist[rr, cc] <= straight_run]\n    else:\n        path[:] = False\n        walk = []\n'''\nassert t.count(old) == 1\nt = t.replace(old, new)\n\nold = '''    return {\n        \"corridor\": corridor,\n        \"flow_path\": path,'''\nnew = '''    return {\n        \"corridor\": corridor,\n        \"flow_path\": path,\n        \"flow_walk\": walk,'''\nassert t.count(old) == 1\nt = t.replace(old, new)\np.write_text(t, encoding=\"utf-8\", newline=\"\\n\")\n\np2 = Path(\"tools/run
... [truncated]
```

**&#8627; Bash responded**

```
both patched
parse ok
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tools/run_long_routing.py 2>&1 | tail -20",
 "description": "Re-run long routing with ordered polylines",
 "timeout": 600000,
 "run_in_background": true
}
```

**&#8627; Bash responded**

```
Command running in background with ID: bl8bfzjqd. Output is being written to: C:\Users\<user>\AppData\Local\Temp\claude\C--Users-<user>-Downloads-micro1\ab6f3eba-339a-4ccf-b131-16630e8fa3db\tasks\bl8bfzjqd.output. You will be notified when it completes. To check interim output, use Read on that file path.
Session cwd remains C:\Users\<user>\Downloads\micro1; directory changes made by the backgrounded command do not apply to subsequent commands.
```

### AGENT &nbsp;<sub>2026-08-30 21:31:27</sub>

While that runs — checking if the seed-distance array is now dead code in the exporter:

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && grep -n \"dist_from_seed\" tools/run_long_routing.py",
 "description": "Check for dead variable"
}
```

**&#8627; Bash responded**

```
122:        dist_from_seed = ndimage.distance_transform_edt(~seed, sampling=res_m)
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && sed -n '115,130p' tools/run_long_routing.py",
 "description": "View context around dead variable"
}
```

**&#8627; Bash responded**

```
# falls into and cannot leave.
            dem[dem <= 0] = np.nan
            res_m = abs(src.transform.a) * 111320.0 * float(
                np.cos(np.radians(lake["lat"])))
            seed = _seed_from_lake(src, lake["lat"], lake["lon"], area_m2)
            bounds_wgs = list(src.bounds)
            transform = src.transform
        dist_from_seed = ndimage.distance_transform_edt(~seed, sampling=res_m)

        rec = {"lake_id": lid, "name": lake["name"],
               "dem_resolution_m": round(res_m, 1),
               "domain_bounds_wgs84": [round(b, 6) for b in bounds_wgs],
               "seed_cells": int(seed.sum()), "regimes": {}}
        for regime, angle in (("debris_flow", debris_deg),
                              ("clearwater_flood", clear_deg)):
            r = route_long(dem, seed, res_m, angle, buffer_m,
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ./.venv/Scripts/python.exe - <<'PY'\nfrom pathlib import Path\np = Path(\"tools/run_long_routing.py\"); t = p.read_text(encoding=\"utf-8\")\nold = '''            transform = src.transform\n        dist_from_seed = ndimage.distance_transform_edt(~seed, sampling=res_m)\n'''\nnew = '''            transform = src.transform\n'''\nassert t.count(old) == 1\nt = t.replace(old, new)\n# drop the ndimage import too if nothing else uses it\nif \"ndimage\" not in t.replace(\"from scipy import ndimage\", \"\"):\n    t = t.replace(\"from scipy import ndimage\\n\", \"\")\np.write_text(t, encoding=\"utf-8\", newline=\"\\n\")\nprint(\"dead code removed; ndimage still imported:\", \"ndimage\" in t)\nPY\n./.venv/Scripts/python.exe -c \"import ast;ast.parse(open('tools/run_long_routing.py',encoding='utf-8').read());print('parse ok')\"",
 "description": "Remove dead seed-distance computation"
}
```

**&#8627; Bash responded**

```
dead code removed; ndimage still imported: True
parse ok
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && grep -n \"ndimage\" tools/run_long_routing.py",
 "description": "Verify ndimage usage"
}
```

**&#8627; Bash responded**

```
19:from scipy import ndimage
73:    lab, _ = ndimage.label(flat)
```

### AGENT &nbsp;<sub>2026-08-30 21:31:49</sub>

Import stays (used by `label`). The background routing job loaded the already-patched polyline code, so its output is unaffected by this cleanup. Waiting for it to finish before re-running the chain.

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && cat \"C:/Users/<user>/AppData/Local/Temp/claude/C--Users-<user>-Downloads-micro1/ab6f3eba-339a-4ccf-b131-16630e8fa3db/tasks/bl8bfzjqd.output\" 2>/dev/null | tail -6",
 "description": "Peek at routing progress"
}
```

**&#8627; Bash responded**

```
(Bash completed with no output)
```

### AGENT &nbsp;<sub>2026-08-30 21:31:54</sub>

Still in the first lake (pure-Python priority flood is slow). It notifies on completion; nothing downstream can run until then, so pausing here.

### HUMAN &nbsp;<sub>2026-08-30 21:33:31</sub>

> <task-notification>
> <task-id>bl8bfzjqd</task-id>
> <tool-use-id>toolu_01KRVjg9s3bmMswst7bsMjwX</tool-use-id>
> <output-file>C:\Users\<user>\AppData\Local\Temp\claude\C--Users-<user>-Downloads-micro1\ab6f3eba-339a-4ccf-b131-16630e8fa3db\tasks\bl8bfzjqd.output</output-file>
> <status>completed</status>
> <summary>Background command "Re-run long routing with ordered polylines" completed (exit code 0)</summary>
> </task-notification>
