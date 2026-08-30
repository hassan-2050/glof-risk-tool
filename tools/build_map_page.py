"""Inline outputs/map_data.json into the template -> outputs/map.html.

    python tools/build_map_data.py     # geometry, hillshades, scores
    python tools/build_map_page.py     # one self-contained page

The data is INLINED rather than fetched. A page opened as file:// cannot
fetch() a sibling JSON - Chrome blocks it as a cross-origin request - so a
two-file design would break for the one audience that matters here, someone
who clones the repo and double-clicks the page with the network off.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tools" / "map_template.html"
SITE = ROOT / "outputs" / "tools"
DATA = SITE / "map_data.json"
DEST = SITE / "map.html"

PLACEHOLDER = "__MAP_DATA__"


def main() -> int:
    if not DATA.exists():
        raise SystemExit(f"{DATA.relative_to(ROOT).as_posix()} missing - "
                         "run tools/build_map_data.py first")
    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise SystemExit(f"template has no {PLACEHOLDER} placeholder")

    raw = DATA.read_text(encoding="utf-8")
    json.loads(raw)  # fail here rather than in someone's browser

    # The payload sits inside <script type="application/json">, so the only
    # sequence that can break out is a literal "</script". Escaping the slash
    # is invisible to JSON.parse and cannot terminate the element.
    safe = raw.replace("</", r"<\/")

    DEST.write_text(html.replace(PLACEHOLDER, safe), encoding="utf-8",
                    newline="\n")
    print(f"wrote {DEST.relative_to(ROOT).as_posix()}  "
          f"({DEST.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
