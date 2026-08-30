# The shell ate a backslash and the patch silently did nothing

**Why this one.** A patch script asserts, writes nothing, and reports success on a different line. The agent diagnoses the heredoc mangling backslashes, proves it with a byte-level comparison, and works around it. Small, unglamorous, and the most honest picture of what agentic coding actually looks like.

Tool output is truncated here for reading; the complete record is in `raw/session.jsonl`.

---

### AGENT &nbsp;<sub>2026-08-30 20:45:47</sub>

Bash is eating one level of backslash in the heredoc, so the tail pattern never matched (nothing was written). Redoing the patch without any backslash escapes:

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ./.venv/Scripts/python.exe - <<'PY'\nfrom pathlib import Path\np = Path(\"tools/corridor_exposure.py\"); t = p.read_text(encoding=\"utf-8\")\nBS = chr(92)\n\nold = '''        cache = pinned / lid / \"corridor_osm.json\"\n        if cache.exists() and not args.refresh:\n            osm = read_json(cache)\n        else:\n            print(f\"  {lid}: querying Overpass over {len(line)} vertices ...\",\n                  flush=True)\n            osm = query_corridor(_bbox_of(line))\n            if not osm.get(\"elements\"):\n                raise RuntimeError(f\"{lid}: Overpass returned no elements; \"\n                                   \"refusing to cache an empty extract\")\n            write_json(cache, osm)\n            time.sleep(5)          # be a good citizen on a free endpoint\n'''\nnew = '''        cache = pinned / lid / \"corridor_osm.json\"\n        osm_error = None\n        if cache.exists() and not args.refresh:\n            osm = read_json(cache)\n        else:\n            print(f\"  {lid}: querying Overpass over {len(line)} vertices ...\",\n                  flush=True)\n            try:\n                osm = query_corridor(_bbox_of(line))\n            except RuntimeError as exc:\n                # A throttled lake must not abort the other thirteen, and must\n                # not be allowed to LOOK like a lake with nothing downstream.\n                # The record carries osm_available false so every consumer has\n                # to say \"not queried\" instead of printing an empty asset list.\n                osm, osm_error = {\"elements\": []}, str(exc)\n                print(f\"  {lid}: {exc}\")\n                print(\"      -> recorded as NOT QUERIED, not as empty\")\n            else:\n                write_json(cache, osm)\n                time.sleep(5)      # be a good citizen on a free endpoint\n'''\nassert t.count(old) == 1, \"cache block\"\nt = t.replace(old, new)\n\nold2 = '''        res
... [truncated]
```

**&#8627; Bash responded**

```
main() hardened
parse ok
```

### AGENT &nbsp;<sub>2026-08-30 20:46:12</sub>

Now the consumer, so a not-queried corridor can't render as an empty one:

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ./.venv/Scripts/python.exe - <<'PY'\nfrom pathlib import Path\np = Path(\"tools/build_scenarios.py\"); t = p.read_text(encoding=\"utf-8\")\n\nold = '''        exr = exposure.get(lid) or {}\n        counts = exr.get(\"counts\") or {}'''\nnew = '''        exr = exposure.get(lid) or {}\n        # A lake Overpass never answered for has no counts, and an empty count\n        # dict renders identically to \"nothing is downstream\". Carry the\n        # distinction through instead of letting it collapse here. A record\n        # written before the flag existed was, by definition, queried.\n        osm_ok = bool(exr) and exr.get(\"osm_available\", True)\n        counts = exr.get(\"counts\") or {}'''\nassert t.count(old) == 1, \"exr\"\nt = t.replace(old, new)\n\nold2 = '''            \"assets_along_corridor\": {\n                \"counts\": counts,'''\nnew2 = '''            \"assets_along_corridor\": {\n                \"osm_available\": osm_ok,\n                \"counts\": counts,'''\nassert t.count(old2) == 1, \"block\"\nt = t.replace(old2, new2)\n\nold3 = '''        if a[\"counts\"]:\n            got = \", \".join('''\nnew3 = '''        if not a[\"osm_available\"]:\n            lines.append(\"- **In the corridor:** not queried - OpenStreetMap \"\n                         \"did not answer for this corridor. That is a missing \"\n                         \"answer, not an empty one.\")\n        elif a[\"counts\"]:\n            got = \", \".join('''\nassert t.count(old3) == 1, \"md\"\nt = t.replace(old3, new3)\n\nold4 = '''        print(f\"  {s['lake_id']:<24} reach {s['reach_km']['bracket']} km, \"\n              f\"{sum((a['counts'] or {}).values())} assets, \"\n              f\"{a['n_named']} named\")'''\nnew4 = '''        assets = (f\"{sum((a['counts'] or {}).values())} assets, \"\n                  f\"{a['n_named']} named\" if a[\"osm_available\"]\n                  else \"assets NOT QUERIED\")\n        print(f\"  {s['l
... [truncated]
```

**&#8627; Bash responded**

```
build_scenarios patched
parse ok
```

### AGENT &nbsp;<sub>2026-08-30 20:46:29</sub>

Verifying the metric itself first — no network needed for the population path:

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ./.venv/Scripts/python.exe - <<'PY'\nimport sys, json\nsys.path.insert(0, \".\")\nfrom pathlib import Path\nfrom tools.corridor_exposure import population_along, CORRIDOR_BUFFER_M\nfrom src.common.config import load_config\ncfg = load_config()\nwp = cfg.path(\"pinned\") / \"exposure\" / \"worldpop_npl_2020_constrained.tif\"\ndoc = json.load(open(\"outputs/tools/long_routing.json\"))\nprev = {r[\"lake_id\"]: r for r in\n        json.load(open(\"outputs/tools/corridor_exposure.json\"))[\"lakes\"]}\nprint(f\"{'lake':<24}{'pop':>10}  {'cov_new':>8} {'cov_old':>8}   note\")\nfor rec in doc[\"lakes\"]:\n    lid = rec[\"lake_id\"]\n    line = (rec[\"regimes\"].get(\"clearwater_flood\") or {}).get(\"polyline_lonlat\")\n    if not line or len(line) < 2:\n        continue\n    r = population_along(line, wp, CORRIDOR_BUFFER_M)\n    o = (prev.get(lid) or {}).get(\"population_in_corridor\") or {}\n    if not r.get(\"available\"):\n        print(f\"{lid:<24}{'-':>10}  {r['reason']}\"); continue\n    flag = \"\"\n    if o.get(\"available\"):\n        if abs(r[\"population\"] - o[\"population\"]) > 0.5:\n            flag = f\"pop changed from {o['population']:,.0f}\"\n        if o.get(\"coverage_fraction\", 1) < 0.02 and r[\"coverage_fraction\"] > 0.5:\n            flag = (flag + \"; \" if flag else \"\") + \"was self-contradictory\"\n    print(f\"{lid:<24}{r['population']:>10,.0f}  {r['coverage_fraction']:>8.3f} \"\n          f\"{o.get('coverage_fraction', float('nan')):>8.3f}   {flag}\")\nPY",
 "description": "Compare new vs old coverage metric"
}
```

**&#8627; Bash responded**

```
Exit code 1
Traceback (most recent call last):
  File "<stdin>", line 10, in <module>
  File "C:\ProgramData\anaconda3\Lib\json\__init__.py", line 293, in load
    return loads(fp.read(),
                 ~~~~~~~^^
  File "C:\ProgramData\anaconda3\Lib\encodings\cp1252.py", line 23, in decode
    return codecs.charmap_decode(input,self.errors,decoding_table)[0]
           ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
UnicodeDecodeError: 'charmap' codec can't decode byte 0x81 in position 1974: character maps to <undefined>
```

**&#8594; calls `Bash`**

```json
{
 "command": "cd C:/Users/<user>/Downloads/micro1 && ./.venv/Scripts/python.exe - <<'PY'\nimport sys, json\nsys.path.insert(0, \".\")\nfrom pathlib import Path\nfrom tools.corridor_exposure import population_along, CORRIDOR_BUFFER_M\nfrom src.common.config import load_config\nrd = lambda f: json.loads(Path(f).read_text(encoding=\"utf-8\"))\ncfg = load_config()\nwp = cfg.path(\"pinned\") / \"exposure\" / \"worldpop_npl_2020_constrained.tif\"\ndoc = rd(\"outputs/tools/long_routing.json\")\nprev = {r[\"lake_id\"]: r for r in rd(\"outputs/tools/corridor_exposure.json\")[\"lakes\"]}\nprint(f\"{'lake':<24}{'pop':>10}  {'cov_new':>8} {'cov_old':>8}   note\")\nfor rec in doc[\"lakes\"]:\n    lid = rec[\"lake_id\"]\n    line = (rec[\"regimes\"].get(\"clearwater_flood\") or {}).get(\"polyline_lonlat\")\n    if not line or len(line) < 2:\n        continue\n    r = population_along(line, wp, CORRIDOR_BUFFER_M)\n    o = (prev.get(lid) or {}).get(\"population_in_corridor\") or {}\n    if not r.get(\"available\"):\n        print(f\"{lid:<24}{'-':>10}  {r['reason']}\"); continue\n    note = []\n    if o.get(\"available\"):\n        if abs(r[\"population\"] - o[\"population\"]) > 0.5:\n            note.append(f\"pop was {o['population']:,.0f}\")\n        if o.get(\"coverage_fraction\", 1) < 0.05 and r[\"coverage_fraction\"] > 0.5:\n            note.append(\"old metric self-contradictory\")\n    print(f\"{lid:<24}{r['population']:>10,.0f}  {r['coverage_fraction']:>8.3f} \"\n          f\"{o.get('coverage_fraction', float('nan')):>8.3f}   {'; '.join(note)}\")\nPY",
 "description": "Compare new vs old coverage metric"
}
```
