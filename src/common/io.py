"""Deterministic serialisation.

Nothing on the reproduce path may call json.dump / DataFrame.to_csv directly.
Those default to insertion-ordered keys, platform newlines, and full float
repr - all three break byte-identity across runs or across OSes.

Everything funnels through write_json / write_csv / write_text here, which:
  * sort keys, so dict construction order stops mattering
  * force LF newlines, so a Windows author and a Linux judge get the same bytes
  * round floats to a stated precision *before* serialising, so the last ULP
    of a numpy reduction cannot change a hash
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_DECIMALS = 6


def _canonical(obj: Any, decimals: int) -> Any:
    """Recursively round floats and normalise container types."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            # JSON has no NaN; emit null rather than non-standard tokens so the
            # file stays loadable by any strict parser (e.g. a judge's jq).
            return None
        rounded = round(obj, decimals)
        # -0.0 and 0.0 hash differently as text; collapse them.
        return 0.0 if rounded == 0 else rounded
    if isinstance(obj, Mapping):
        return {str(k): _canonical(v, decimals) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v, decimals) for v in obj]
    if isinstance(obj, set):
        # Sets have no stable order; sort by repr so output is reproducible.
        return sorted((_canonical(v, decimals) for v in obj), key=repr)
    if hasattr(obj, "item") and hasattr(obj, "dtype"):  # numpy scalar
        return _canonical(obj.item(), decimals)
    if isinstance(obj, Path):
        return obj.as_posix()
    return obj


def dumps_json(data: Any, decimals: int = DEFAULT_DECIMALS) -> str:
    return json.dumps(
        _canonical(data, decimals),
        sort_keys=True,
        indent=2,
        ensure_ascii=False,   # Nepali Devanagari stays readable in the file
        separators=(",", ": "),
    ) + "\n"


def write_json(path: str | Path, data: Any, decimals: int = DEFAULT_DECIMALS) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_json(data, decimals), encoding="utf-8", newline="\n")
    return path


def write_text(path: str | Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    return path


def write_csv(
    path: str | Path,
    rows: Iterable[Mapping[str, Any]],
    fieldnames: Sequence[str] | None = None,
    decimals: int = DEFAULT_DECIMALS,
) -> Path:
    """Write a CSV with stable column order and LF newlines.

    Column order is taken from `fieldnames` if given, otherwise the union of
    keys sorted alphabetically - never dict insertion order.
    """
    rows = [_canonical(r, decimals) for r in rows]
    if fieldnames is None:
        keys: set[str] = set()
        for r in rows:
            keys.update(r.keys())
        fieldnames = sorted(keys)
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=list(fieldnames), lineterminator="\n",
                            extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fieldnames})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(buf.getvalue(), encoding="utf-8", newline="\n")
    return path


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# outputs/tools/ is where anything under tools/ writes, and the run manifest
# skips it. Named for the source directory that fills it, not for one of its
# contents: it was called "interactive" when it held only the map page, and
# the next two tool artefacts were written beside outputs/ instead, leaking
# into the manifest exactly as map.html had.
#
# The sweep in manifest_for is deliberately indiscriminate - it hashes whatever
# is under outputs/, so a stage cannot quietly emit an undeclared file. That
# property is worth keeping, but it also means an artefact built OUTSIDE
# `reproduce` lands in a manifest documented as "a pure function of the run's
# artefacts". outputs/map.html did exactly that: the count went 44 -> 46, and a
# container that never ran `make map` would have reported a spurious difference
# against a host that did. One reserved subdirectory keeps both properties, and
# Stage 17 asserts that no reproduce stage declares an output inside it.
TOOL_OUTPUT_DIR = "tools"


def manifest_for(root: str | Path, patterns: Sequence[str] = ("**/*",),
                 exclude_top: Sequence[str] = ()) -> dict:
    """sha256 of every file under `root`, keyed by POSIX-relative path.

    This is the artefact the determinism check diffs. Sorting is explicit
    because filesystem walk order is not guaranteed to match across machines.

    `exclude_top` names top-level subdirectories of `root` to skip. It is a
    parameter rather than a module constant because this function also hashes
    data/pinned/, where a directory that happened to share the name would be
    dropped silently. The caller that needs the exclusion asks for it.
    """
    # Placeholders are not artefacts. .gitkeep exists on a git checkout and not
    # in a container (where outputs/ is created by mkdir), so including it made
    # a host-vs-container comparison report a difference that says nothing
    # about the pipeline.
    IGNORED = {".gitkeep", ".gitignore"}
    root = Path(root)
    seen: dict[str, str] = {}
    for pattern in patterns:
        for p in sorted(root.glob(pattern)):
            if not p.is_file() or p.name in IGNORED:
                continue
            rel = p.relative_to(root).as_posix()
            if rel.split("/")[0] in exclude_top:
                continue
            seen[rel] = sha256_file(p)
    return {k: seen[k] for k in sorted(seen)}
