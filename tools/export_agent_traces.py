"""Export the coding-agent trajectories that accompany this submission.

    python tools/export_agent_traces.py          -> submission/agent_traces/

TWO KINDS OF AGENT TRACE, AND THEY ARE NOT THE SAME THING
---------------------------------------------------------
1. THE PRODUCT'S OWN AGENTS - the multi-agent reporter (retriever, reconciler,
   drafter, critic, verifier). Their trajectories are a pipeline artefact,
   written by Stage 17 to outputs/agent_trajectories.json on every run. This
   script copies that file in; it does not generate it.

2. THE CODING AGENT THAT BUILT THE REPOSITORY - Claude Code. Its trajectory is
   the session transcript Claude Code keeps under ~/.claude/projects/. This
   script reads that transcript and renders it into something a judge can
   actually follow.

The submission asks for trajectories that are "easy to follow from the agent
instructions through to the final result", showing "what the agent did and how
its tools responded" plus "the feedback that shaped its next step". A raw
19 MB JSONL satisfies none of that on its own, so this emits three layers:

    raw/          the complete record, redacted - the evidence
    TRANSCRIPT.md every turn, readable, long tool output truncated
    episodes/     four hand-chosen runs of the loop, in full

REDACTION IS NOT OPTIONAL
-------------------------
A development transcript is a plaintext log of everything typed during the
build, including anything pasted into the chat. This script refuses to write
an export it can still find a secret in: it redacts, then re-scans its own
output, and exits non-zero if anything survives. Redacting the export does NOT
un-leak a credential that was already logged - rotate it as well.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEST = REPO_ROOT / "submission" / "agent_traces"

# Claude Code stores a session under a directory named after the working
# directory, with the separators and the drive colon flattened to hyphens:
#   C:\Users\me\Downloads\micro1  ->  C--Users-me-Downloads-micro1
# Derived rather than hard-coded, so this runs on a machine that is not the
# author's - and so no personal path is committed in this file.
PROJECTS = Path.home() / ".claude" / "projects"
SESSIONS = PROJECTS / re.sub(r"[:\\/]", "-", str(REPO_ROOT))

# The account name to scrub, taken from the machine rather than typed in - so
# this file carries no personal string of its own, and works for whoever runs
# it. re.escape because an account name may contain regex metacharacters.
USER = re.escape(Path.home().name)

# Applied to every byte that leaves this script, raw JSONL included. Ordered:
# the most specific patterns first, so a broad rule cannot mask a narrow one.
REDACTIONS: list[tuple[str, str]] = [
    # Credentials pasted into the chat during the build. The Gemini key was
    # used once to record the LLM cache; `reproduce` needs no key at all.
    # 4+, not 20+. Searching for the key during the build logged truncated
    # PREFIXES of it into the transcript, and a length-gated pattern walked
    # straight past them - the self-check found a 15-character fragment still
    # sitting in the export. A fragment of a credential is still a credential.
    (r"AQ\.[A-Za-z0-9_\-]{4,}", "<REDACTED_GEMINI_API_KEY>"),
    (r"AIza[0-9A-Za-z_\-]{30,}", "<REDACTED_GOOGLE_API_KEY>"),
    (r"sk-ant-[0-9A-Za-z_\-]{20,}", "<REDACTED_ANTHROPIC_KEY>"),
    (r"\bsk-[0-9A-Za-z]{32,}", "<REDACTED_OPENAI_KEY>"),
    (r"gh[pousr]_[0-9A-Za-z]{30,}", "<REDACTED_GITHUB_TOKEN>"),
    (r"AKIA[0-9A-Z]{16}", "<REDACTED_AWS_KEY>"),
    # Personal information: the author's email and home directory.
    (r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "<redacted-email>"),
    # Separator-agnostic on purpose. The same path appears raw
    # (C:\Users\me), JSON-escaped (C:\\Users\\me) and doubly-escaped where a
    # transcript records a tool call that itself carried JSON - a fixed-width
    # pattern matches the first two and silently leaves the third, which is
    # exactly what the self-check caught on the first run.
    (rf"(?i)(Users)([\\/]+){USER}",
     lambda m: f"{m.group(1)}{m.group(2)}<user>"),
    # The harness derives project directory names from the path, hyphenated
    # (C--Users-me-Downloads-micro1). Match the token, not a fixed wrapper.
    (rf"(?i)Users-{USER}", "Users-<user>"),
]

# Patterns that must NOT appear in the finished export. Checked after writing.
FORBIDDEN = [
    (r"AQ\.[A-Za-z0-9_\-]{4,}", "Gemini API key (or a fragment of one)"),
    (r"AIza[0-9A-Za-z_\-]{30,}", "Google API key"),
    (r"sk-ant-[0-9A-Za-z_\-]{20,}", "Anthropic key"),
    (r"gh[pousr]_[0-9A-Za-z]{30,}", "GitHub token"),
    (rf"(?i)users[\\/]+{USER}", "author home directory"),
    (rf"(?i)Users-{USER}", "author home directory (hyphenated)"),
]

# Representative runs of the build loop. Each is (slug, title, why it is worth
# reading, regex that marks its first record, how many turns to carry).
#
# Chosen for what they SHOW, not for flattering the result: three of the four
# are the agent being wrong and finding out from a tool, which is the loop the
# submission is asking to see.
EPISODES = [
    ("01-coverage-metric-conflation",
     "A metric that reported 0% coverage beside 5,222 people",
     "The agent is told a metric is wrong, fixes it, and then discovers the "
     "same conflation twice more in places nobody asked it to look - two "
     "corridors outside the raster reporting 0 people, and Gokyo reporting 0 "
     "people beside 21 settlements. It verifies the 696 m claim independently "
     "before writing it into an output. Feedback shaping the next step, three "
     "times over.",
     r"Two problems\. The population coverage metric is wrong", 46),

    ("02-polyline-order-bug",
     "The map UI exposed a village 202 km down a 104 km channel",
     "A visual check catches an arithmetic bug no test had. The agent traces "
     "it from the label, through the exporter, to the router that lost the "
     "walk order - fixes the cause rather than the symptom, re-runs the chain, "
     "and the headline validation result IMPROVES (Reni 43.8 km -> 22.3 km). "
     "The retry loop and the root-cause discipline are both visible.",
     r"Labels show 202.241 km on a 104 km corridor", 34),

    ("03-tooling-fights-back",
     "The shell ate a backslash and the patch silently did nothing",
     "A patch script asserts, writes nothing, and reports success on a "
     "different line. The agent diagnoses the heredoc mangling backslashes, "
     "proves it with a byte-level comparison, and works around it. Small, "
     "unglamorous, and the most honest picture of what agentic coding "
     "actually looks like.",
     r"Bash is eating one level of backslash in the heredoc", 12),

    ("04-human-checkpoints",
     "The human redirects scope against a deadline",
     "The operator supplies the competition rules, the agent audits the repo "
     "against them and proposes an order, and the human overrides that order "
     "('lets do c first'). Later the human declines a suggested edit "
     "('no i wont make any edits'). Human checkpoints steering the work.",
     r"i will present it here so find loop holes", 18),
]

MAX_TOOL_OUTPUT = 1500          # characters, in the readable transcript only
MAX_TOOL_INPUT = 2000


def redact(text: str) -> str:
    for pat, repl in REDACTIONS:
        text = re.sub(pat, repl, text)      # repl may be a string or callable
    return text


def newest_session(explicit: Path | None) -> Path:
    if explicit:
        return explicit
    if not SESSIONS.exists():
        raise SystemExit(
            f"no Claude Code sessions found at {SESSIONS}\n"
            "Pass --session <path-to-transcript.jsonl> if your transcripts "
            "live elsewhere.")
    files = [f for f in SESSIONS.glob("*.jsonl")
             if not f.name.endswith(".pre-import")]
    if not files:
        raise SystemExit(f"no .jsonl transcripts in {SESSIONS}")
    # Largest, not newest: a resumed session leaves small stubs behind, and the
    # build transcript is the one with the work in it.
    return max(files, key=lambda f: f.stat().st_size)


def blocks(msg: dict) -> list:
    c = msg.get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return [b for b in (c or []) if isinstance(b, dict)]


def is_noise(text: str) -> bool:
    """Harness chatter the reader does not need: reminders, hook output."""
    t = text.strip()
    return (not t
            or t.startswith("<system-reminder>")
            or t.startswith("<local-command")
            or t.startswith("<command-name>")
            or "[SYSTEM NOTIFICATION - NOT USER INPUT]" in t)


def render(records: list, title: str, preamble: str) -> str:
    """One readable markdown document from a list of transcript records."""
    out = [f"# {title}", "", preamble, "",
           "Tool output is truncated here for reading; the complete record is "
           "in `raw/session.jsonl`.", "", "---", ""]
    tool_names: dict[str, str] = {}
    for d in records:
        kind = d.get("type")
        msg = d.get("message") or {}
        stamp = (d.get("timestamp") or "")[:19].replace("T", " ")

        if kind == "user":
            for b in blocks(msg):
                if b.get("type") == "text" and not is_noise(b.get("text", "")):
                    out += [f"### HUMAN &nbsp;<sub>{stamp}</sub>", "",
                            "> " + b["text"].strip().replace("\n", "\n> "), ""]
                elif b.get("type") == "tool_result":
                    name = tool_names.get(b.get("tool_use_id", ""), "tool")
                    body = b.get("content")
                    if isinstance(body, list):
                        body = "\n".join(x.get("text", "[non-text output]")
                                         for x in body if isinstance(x, dict))
                    body = str(body or "").strip()
                    clipped = body[:MAX_TOOL_OUTPUT]
                    if len(body) > MAX_TOOL_OUTPUT:
                        clipped += (f"\n... [{len(body) - MAX_TOOL_OUTPUT:,} "
                                    "more characters truncated]")
                    out += [f"**&#8627; {name} responded**", "",
                            "```", clipped or "[no output]", "```", ""]

        elif kind == "assistant":
            for b in blocks(msg):
                if b.get("type") == "text" and b.get("text", "").strip():
                    out += [f"### AGENT &nbsp;<sub>{stamp}</sub>", "",
                            b["text"].strip(), ""]
                elif b.get("type") == "thinking":
                    continue          # reasoning is not part of the deliverable
                elif b.get("type") == "tool_use":
                    name = b.get("name", "tool")
                    tool_names[b.get("id", "")] = name
                    inp = json.dumps(b.get("input", {}), indent=1,
                                     ensure_ascii=False)
                    if len(inp) > MAX_TOOL_INPUT:
                        inp = inp[:MAX_TOOL_INPUT] + "\n... [truncated]"
                    out += [f"**&#8594; calls `{name}`**", "",
                            "```json", inp, "```", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", type=Path, help="explicit transcript .jsonl")
    ap.add_argument("--dest", type=Path, default=DEST)
    args = ap.parse_args(argv)

    src = newest_session(args.session)
    dest = args.dest
    print(f"source : {src.name}  ({src.stat().st_size / 1e6:.1f} MB)")

    records = []
    for line in src.open(encoding="utf-8", errors="replace"):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    turns = [d for d in records if d.get("type") in ("user", "assistant")]
    print(f"records: {len(records):,} ({len(turns):,} conversational turns)")

    if dest.exists():
        shutil.rmtree(dest)
    (dest / "raw").mkdir(parents=True)
    (dest / "episodes").mkdir()

    # ---- layer 1: the complete record, redacted ---------------------------
    raw_out = dest / "raw" / "session.jsonl"
    with raw_out.open("w", encoding="utf-8", newline="\n") as fh:
        for line in src.open(encoding="utf-8", errors="replace"):
            fh.write(redact(line.rstrip("\n")) + "\n")

    # The product's own agent trajectories, if a run has produced them.
    prod = REPO_ROOT / "outputs" / "agent_trajectories.json"
    if prod.exists():
        (dest / "raw" / "pipeline_agent_trajectories.json").write_text(
            redact(prod.read_text(encoding="utf-8")), encoding="utf-8",
            newline="\n")

    # ---- layer 2: the readable transcript ---------------------------------
    (dest / "TRANSCRIPT.md").write_text(redact(render(
        records,
        "Coding-agent transcript - GLOF Risk Tool",
        "Every turn of the build, in order. The agent is Claude Code; the "
        "human turns are the operator steering it.")),
        encoding="utf-8", newline="\n")

    # ---- layer 3: the chosen episodes -------------------------------------
    written = []
    for slug, title, why, anchor, span in EPISODES:
        start = next((i for i, d in enumerate(turns)
                      if re.search(anchor, json.dumps(d.get("message", {}),
                                                      ensure_ascii=False))),
                     None)
        if start is None:
            print(f"  ! episode anchor not found, skipped: {slug}")
            continue
        chunk = turns[start:start + span]
        (dest / "episodes" / f"{slug}.md").write_text(
            redact(render(chunk, title, f"**Why this one.** {why}")),
            encoding="utf-8", newline="\n")
        written.append((slug, title, why, len(chunk)))
        print(f"  episode: {slug}  ({len(chunk)} turns)")

    # ---- the index --------------------------------------------------------
    tools: dict[str, int] = {}
    for d in records:
        if d.get("type") == "assistant":
            for b in blocks(d.get("message") or {}):
                if b.get("type") == "tool_use":
                    tools[b["name"]] = tools.get(b["name"], 0) + 1
    stamps = sorted(d["timestamp"] for d in records if d.get("timestamp"))
    tool_rows = "\n".join(f"| `{k}` | {v} |" for k, v in
                          sorted(tools.items(), key=lambda x: -x[1]))
    ep_rows = "\n".join(
        f"### [{t}](episodes/{s}.md)\n\n{w}\n" for s, t, w, _ in written)

    (dest / "README.md").write_text(f"""# Agent trajectories

Two different kinds of agent ran in this project. Both are here, and they
should not be confused.

## 1. The coding agent that built the repository

**Claude Code** (Anthropic), driven by one operator across
{stamps[0][:10]} to {stamps[-1][:10]}. It wrote and revised the pipeline, ran
it, read the artefacts, and chose the next change from what those artefacts
said. The iteration loop recorded in `CHANGELOG_improvements.md` -
hypothesis, change, measured result - is this agent's actual working loop.

| | |
|---|---|
| conversational turns | {len(turns):,} |
| tool calls | {sum(tools.values()):,} |
| session span | {stamps[0][:19].replace("T", " ")} to {stamps[-1][:19].replace("T", " ")} UTC |

| tool | calls |
|---|---|
{tool_rows}

**[TRANSCRIPT.md](TRANSCRIPT.md)** is every turn in order.
**[raw/session.jsonl](raw/session.jsonl)** is the complete unabridged record,
one JSON object per line, exactly as the harness wrote it.

### Representative episodes

Four runs of the loop, chosen for what they show rather than for flattering
the outcome - three of the four are the agent being wrong and finding out from
a tool.

{ep_rows}

## 2. The product's own agents

The deliverable itself is multi-agent: a retriever, a numeric reconciler, a
drafter, an adversarial critic and a verifier produce every situation report.
Their trajectories are a **pipeline artefact**, regenerated by Stage 17 on
every run rather than exported by hand:

- `raw/pipeline_agent_trajectories.json` (copied from `outputs/`)
- reproduce it yourself with `make reproduce`

## Redaction

This export is machine-redacted and then re-scanned; the generator exits
non-zero if any forbidden pattern survives. Removed: API keys pasted into the
chat during development, the author's email address, and the author's home
directory path. Replacements are visible as `<REDACTED_...>` and
`C:\\Users\\<user>`.

No credential is needed to reproduce anything in this repository: the
pipeline's language-model calls replay from `data/pinned/llm_cache/`, and on
the reproduce path a cache miss is a hard error rather than a live call.

Regenerate this directory with:

```bash
python tools/export_agent_traces.py
```
""", encoding="utf-8", newline="\n")

    # ---- verify our own output --------------------------------------------
    print("\nscanning the export for anything that should not ship ...")
    leaks = 0
    for f in sorted(dest.rglob("*")):
        if not f.is_file():
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        for pat, label in FORBIDDEN:
            n = len(re.findall(pat, body))
            if n:
                leaks += n
                print(f"  LEAK  {f.relative_to(dest)}: {n}x {label}")
    total = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
    print(f"\n-> {dest.relative_to(REPO_ROOT).as_posix()}  "
          f"({total / 1e6:.1f} MB)")
    if leaks:
        print(f"REFUSING TO PASS: {leaks} leak(s) above. Fix REDACTIONS.")
        return 1
    print("clean: no forbidden pattern found in the export.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
