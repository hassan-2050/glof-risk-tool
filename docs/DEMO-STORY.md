# Demo story — "was it a glacial lake?"

A five-minute narrative. Every repository figure here is reproducible and gated
by Stage 17; every external figure names its source. Screen cues in *italics*.

> **Currency warning.** Beat 1 describes an event four days old at the time of
> writing (30 Aug 2026). The toll is rising and the attribution is provisional.
> **Re-check the numbers on the morning of the demo** and say the date out loud
> when you give them. If the attribution has changed, say that too — it would
> make the point better, not worse.

---

## Beat 1 — Open on the question everyone is asking (45 seconds)

On **26 August 2026**, a block of bedrock and glacier ice about **600 metres
wide** broke off the north slope of Langtang-Lirung and fell **1,200 metres**.
It registered on seismographs worldwide as a **magnitude 5.2**. It dammed the
Lhende Khola, the lake behind the debris burst, and a wall of water perhaps
**100 metres high** went down the valley. As of 29–30 August: **579 dead, around
400 missing.** Warning lead time was described as *"minutes rather than hours."*

The first question everybody asked — press, agencies, the public — was:
**was it a glacial lake outburst?**

The answer, days later, is **no**. It was a rock-ice avalanche. There was a
lake, but the landslide *created* it.

*Pause here. That question is what this project is about.*

---

## Beat 2 — This is the second time (45 seconds)

**Chamoli, February 2021.** Over 200 dead. Reported worldwide as a glacial lake
outburst. It was a rock-and-ice avalanche. No lake was involved.

Five years later the same misattribution ran again, at greater cost, in the
first hours of coverage.

*This is why the project's negative control is not a footnote.* We put Chamoli
in the evaluation set as a case the system must **refuse**. It finds 300 m² of
scattered meltwater, below its own 5,000 m² minimum, fires zero proxies, and
declines to call it a lake burst — in English and in Nepali, and in the
machine-readable CAP export too.

A hazard system that cannot say what something **is not** will eventually send
people to watch the wrong thing.

---

## Beat 3 — And the distinction is not academic (40 seconds)

*Same river. Fourteen months apart.*

- **July 2025, Lhende Khola:** a supraglacial lake on the Pyurepu Glacier in
  Tibet — formed from ponds first seen in December 2023 — drained in a single
  day. 9 dead, 19 missing, the Rasuwagadhi Friendship Bridge gone. **That was a
  GLOF**, and it is in our evaluation set as a hindcast case.
- **August 2026, same river:** **not a GLOF.**

Two catastrophic floods, one valley, two entirely different causes. Call them
both "glacial flood" and you have destroyed the only distinction that changes
what you do next: one says *watch the lakes*, the other says *watch the slopes*.

---

## Beat 4 — What we built, and the lake that was too small to look at (75 seconds)

The standard first filter for glacial-lake hazard is **area growth**, and it
ignores anything under **0.1 km²**.

*Open `outputs/tools/map.html`. Drag the timeline 2017 → 2024.*

Thame, August 2024. The outline barely moves. **0.0384 km²** on our last usable
pre-event scene — a third of the threshold. And that is the *only* pre-event
scene clearing the cloud gate, so the two-date growth test has nothing to
compare it against. That lake
emptied in 22 minutes, displaced 135 people, and carried debris 80 km.

Growth-and-size screening did not rank it low. It **never assessed it**. The
researchers who reconstructed the event say exactly that: the lakes "were missed
in the previous GLOF hazard and risk assessments", and name minimum lake-size
thresholds as the reason.

So we ask a different question: **how much rock and ice can fall in, compared
with how much water is already there?** On pre-event data only, Thame ranks
**1 of 13** — ahead of Tsho Rolpa, ahead of Imja, ahead of every officially
listed dangerous lake.

*Drag the alarm-threshold slider.* The flag count moves. The **rank does not**.
The threshold was chosen after seeing every score, so the threshold is not
evidence. The ordering is.

---

## Beat 5 — Where we check ourselves (75 seconds)

**Do not cut this beat.** It is the one they will remember.

We went to the peer-reviewed literature to test our own claims and found four
things wrong — with us.

**Thame was two lakes, not one.** A cascade: Upper Ngole Cho failed first and
overtopped the lower lake. We track the lower one. The upper was **0.11 km²** —
marginally *above* the screen. Our headline understates the event, and that
qualification now sits on the claim itself, not in a footnote.

**Two "measurement failures" were our own bad labels.** We were measuring
Thonak Cho and grading it against Dudh Pokhari's area — settled by elevation,
not area: our DEM reads 4,832 m, Thonak Cho is 4,834 m. And our Tilicho
reference asserted a consensus that does not exist. Validation went **4/8 → 6/8**
and *not one pixel changed*. Every reference that turned out to be wrong carried
the word **"verified."**

**The tool was inventing disagreements.** It reported sources disputing lake
elevation "between 51 m and 4,900 m" — that was a breach *width* and a *fall*
in the same bucket as a real altitude. And a flood volume "between 185 and
459,000 m³" — the 185 was **Olympic-size swimming pools**. Both fixed.

*Here is the part you cannot script.* The guard we wrote for that swimming-pool
bug fires on this week's coverage of Langtang: the collapse is being reported as
**"40,000 to 80,000 Olympic-sized swimming pools."** It was never a one-off. It
is house style.

**And the one number we could check against reality, we got wrong by 48×.** The
Sikkim reconstruction gives 38.31 million m³ of debris into South Lhonak; we
estimate 805,200. We could have retuned — South Lhonak is a designated
calibration lake, so it would have been legal. We didn't, and wrote down why.

---

## Beat 6 — What it cannot do, said plainly (45 seconds)

**It would have been silent on Langtang-Lirung.** This pipeline screens *lakes*;
it needs 5,000 m² of impounded water before it assesses anything — the same rule
that makes the Chamoli refusal work. The initiating slope held no lake. The
hazard class that killed 579 people is one this tool does not cover.

It would also have been **looking 16 km away.** Measured from our Rasuwa window
centre, the 2026 source is 16.2 km outside it. Our own limits document already
says a lake-centred window is the wrong analysis domain. Last week demonstrated
it.

And **it cannot predict floods.** It caught 1 of 3 bursts. Its agreement with
expert rankings is 0.378 — a number that *fell* when our measurements improved.
Only **1 of 16** pre-event satellite passes across four disasters was clear
enough to use, because optical satellites are blindest in monsoon, which is when
these floods happen.

It is triage. **It tells you where to send someone with instruments.** The
Langtang researchers said the same thing: soil-moisture sensors, drone imagery,
satellite data — and that *"technology alone cannot ensure preparedness."*

---

## Beat 7 — Close (30 seconds)

Nepal built an early-warning system at Tsho Rolpa in 2000–02, sirens across 19
villages. It is defunct. Over-automation without ownership does not last.

So nothing here is final until a named person types their approval — a blank
keypress is refused — and the whole thing runs offline from committed data and
reproduces **byte-for-byte** on Windows and Linux.

**Close on this:** *last week the first question was "was it a glacial lake?"
It took days to answer, and the first answer was wrong. Everything in this
project is built around getting that question right — and around admitting it
when we don't.*

---

## Cue sheet

| beat | screen | key figure |
|---|---|---|
| 1 | news map of Langtang / Rasuwa | 579 dead, ~400 missing, **not a GLOF** |
| 2 | `outputs/sitreps/chamoli_2021_en.md` | 300 m² water, 0 proxies, refused |
| 3 | map, select Pyurepu | July 2025 GLOF vs Aug 2026 not-GLOF, same river |
| 4 | `map.html`, drag 2017→2024, then threshold | 0.0384 km²; rank **1 of 13** |
| 5 | `docs/DECISIONS.md` D14–D17 | 4/8 → 6/8; 48× |
| 6 | `docs/LIMITS.md` | 1 of 16 usable pre-event scenes; 16 km |
| 7 | approval CLI; `verify-determinism` | 44 artefacts byte-identical |

## If you have 90 seconds

Beats 1, 2 and the last paragraph of 5. The live question, the fact that we
built for it before it was asked, and that we audit ourselves in public.

## Questions you will be asked

**"Would your tool have caught last week's disaster?"** No, and say so first.
It screens lakes; that slope had none. Then say what it *does* do: it refuses to
call the event a GLOF, which took human experts several days and which the
initial reporting got wrong.

**"So what use is it?"** It ranks which lakes deserve instruments. Nobody can
instrument every lake in Nepal. On the one event we can test against, it put the
right lake first.

**"Can it predict the next one?"** No. It does not model the trigger — the
avalanche that sets the date is unobserved. Give the numbers from Beat 6, not a
hedge.

**"Why is recall only 0.333?"** Eight-year baseline. South Lhonak is only
growth-catchable over decades. Honest about a short record, not flattering.

**"You changed reference data to make your numbers better."** Correct, and in
both cases the evidence is independent of area — elevation for Gokyo, a stated
measurement method plus two independent classifiers for Tilicho. D14 says in its
own text that this is a label fix and not a model improvement.

**"Isn't it distasteful to demo on a disaster four days old?"** Fair. Give the
figures with their date, mark the attribution provisional, and make the point
about attribution discipline rather than about the tool. The reason to open here
is that 579 people died partly because the lead time was minutes — and the
argument for screening slopes and lakes *before* the season is exactly that.

---

*External sources: Kathmandu Post, 28 Aug 2026; AntarcticGlaciers.org, Aug 2026;
CNN, 26–29 Aug 2026 — all provisional. Sapkota et al., NHESS 26:4131 (2026);
ICIMOD Thame Valley GLOF 2024 report; Scientific Reports (2026) South Lhonak
sequence; Gandaki Province lake monitoring report (2024). Repository figures:
`docs/RESULTS.md`, `docs/LIMITS.md`, `docs/DECISIONS.md` D13–D17.*


---

## Submission-video mapping (required beats)

The judged video must show six specific things. Where each lands in this
script, plus the two inserts that are not in the beats above:

| required element | where |
|---|---|
| the problem and the simple baseline | Beat 4 — area-growth screening, the 0.1 km² floor, and Thame never assessed |
| one realistic execution, start to finish | **Insert A** below |
| the final comparison | Beat 4's rank + the F1 table from `outputs/results.html` (0.0 → 0.4, contradiction recall 0.0 → 0.95) |
| changelog walkthrough | **Insert B** below |
| the change that contributed most | the D19 domain change: routing moved from a 7 km box to a 100 km river domain — corridors went from a 3.5 km cap to 31–127 km, which is what made scoring against real destroyed villages possible at all |
| one experiment we removed | the priority-flood spanning-tree router: every lake reported the same ~70.6 km straight line (the corner of the box) because a traversal tree meanders around a catchment instead of running down a river. Removed for plain steepest descent; recorded in `src/watcher/routing_long.py` |

**Insert A — one execution, start to finish (~60 s).** Terminal:
`./make.ps1 reproduce` (or the Docker one-liner). Narrate while it runs: no
network — blocked in-process, not merely unused; no API key — LLM responses
replay from the committed cache; every artefact hashed into
`run_manifest.json`. Cut to `outputs/results.html` opening from disk. Then
`make scenarios` → open `map.html`, toggle **Downstream 100 km** on Thame,
drag the scenario dial to 10 km — the observed tick — and read the counters
out loud.

**Insert B — changelog walkthrough (~30 s).** Scroll
`CHANGELOG_improvements.md`: every stage is hypothesis → change → measured
before/after, generated *from* the run. Stop on Stage T2 and read the three
data-integrity bugs — each a wrong answer that looked like an empty one —
ending on Reni: 43.8 km → 22.3 km when the polyline-order bug fell, a fix the
map UI itself surfaced.

**The dial beat (fits inside Beat 4, +30 s).** After the threshold slider:
select Thyanbo, downstream layer on, drag the reach dial. *"If the flow runs
10 km — the observed reach — it has passed Thyangbo and Thame: 3 settlements,
7 bridges, a school. The red tick is where the 2024 flood actually stopped.
Nothing here says when. Everything here says what's in the way."*
