# Ethics and framing

## Decision-support, not public alarm

Publishing a hazard ranking of lakes above named villages is a sensitive act.
The audience for this tool is **DHM, NDRRMA and ICIMOD** - the institutions
holding the legal mandate, the ground truth and the relationships. Outputs are
inputs to Nepal's own systems, not a parallel authority, and every sitrep says
so in its own text.

## Why there is a human in the loop

Nepal's own record makes the argument. Tsho Rolpa received a ~US$3.2M
engineered outlet and a siren network across 19 villages in 2000-2002; the
early-warning system is now defunct, and the documented causes include
over-automation and technological dependence. The 1997 false-alarm evacuation
is part of the same record.

So no document here is final without a **named human approval** recorded in an
append-only ledger, and a draft that fails verification is **withheld from
approval** rather than presented for a rubber stamp. The CAP exports carry
`status=Exercise`, never `Actual`: that single attribute is what keeps a
research artefact out of an operations centre's automated ingest.

## Credit and data sovereignty

The scientific substance belongs to others: ICIMOD's PDGL inventory and Thame
study, DHM's hydrology, NDRRMA's situation reports, and the published work of
Rounce, Fujita, Huggel, Sattar, Shugar, Zhang and Cook & Quincey. Every
threshold in `config/config.yaml` carries its source paper and a confidence
tier. This tool contributes an open, reproducible pipeline - not new authority.

## Uncertainty is foregrounded, not buried

Where sources disagree, the disagreement is the output. The system is designed
to refuse to pick a number: four sources say 4, 5, 8 or 11 hydropower projects
were damaged, and reporting "11" fluently would be worse than reporting the
spread. For high-stakes reporting, contradiction-surfacing beats fluent
summarisation.

## On the negative control

Chamoli 2021 is in the evaluation set precisely because it is **not** a GLOF.
A system that cannot say what a hazard is not will eventually attribute a
rock-and-ice avalanche to a glacial lake, and misattribution in a hazard system
costs credibility that is very hard to rebuild.
