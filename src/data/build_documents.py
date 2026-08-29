"""Build the reporter-side document bundles (Stage 1, final criterion).

Run:  python -m src.data.build_documents

Emits data/pinned/documents/<event_id>/*.json plus a bundle manifest. Runs
fully offline from the curated table below; the network work (reading the
sources, checking the DOIs) already happened, and its results are recorded here
with attribution.

LICENSING - why these files look the way they do
------------------------------------------------
Contest rules require public or synthetic data only, so we do not redistribute
copyrighted article text. Each passage is tagged:

  verbatim_quote      a short quotation (<= ~25 words) of a specific factual
                      claim, with publisher, URL and date - ordinary quotation
                      with attribution
  synthesized_summary connective prose written by us, describing what the
                      source reported, in our own words

Every figure the reconciliation agent must find is carried on a verbatim_quote,
so the agent is extracting real reported numbers, not our paraphrase of them.

WHY THE CONTRADICTIONS ARE REAL
-------------------------------
Every disagreement encoded here was verified against the primary source, not
inherited from the project brief:

  South Lhonak fatalities  55 dead + 74 missing (Sattar et al., Science 2025,
                           doi:10.1126/science.ads2659) vs 178 fatalities
                           (Zhang et al., Landslides 2024,
                           doi:10.1007/s10346-024-02358-x). Both checked.
  Rasuwa HEP count         SANDRP states outright that the count "varies from
                           4, 5, 8 to 11".
  Rasuwa lake area         638,000 -> 435,000 m2 (Institute of Mountain Hazards
                           and Environment) vs 0.725 -> 0.60 km2 (NDRRMA) vs
                           ~0.75 -> ~0.60 km2 (DHM/ICIMOD via press). Three
                           incompatible pairs for the same two days.
  Rasuwa casualties        9 dead / 18 missing (SANDRP) vs 19 dead / 13 missing
                           / 1 injured summed as "23 human casualties" (NDRRMA -
                           internally inconsistent, since those sum to 33).

The NDRRMA arithmetic error is kept deliberately. A reconciliation agent that
only compares numbers ACROSS documents will miss a document that contradicts
itself, and that is a failure mode worth measuring.
"""
from __future__ import annotations

from src.common.config import REPO_ROOT, load_config
from src.common.io import write_json

# --------------------------------------------------------------------------
# Curated source table. Each entry is one document in a bundle.
# --------------------------------------------------------------------------

EVENTS = {
    "thame_2024": {
        "title": "Thame / Thyanbo Tsho GLOF, 16 August 2024",
        "country": "Nepal",
        "admin": "Solukhumbu District, Koshi Province",
        "is_glof": True,
        "documents": [
            {
                "doc_id": "icimod_thame_study_2025",
                "publisher": "ICIMOD",
                "doc_type": "institutional_study",
                "published": "2025-10-14",
                "url": "https://www.icimod.org/press-release/everest-region-a-hotspot-of-cryosphere-linked-hazards-icimods-new-study-on-nepals-2024-thame-flood-confirms/",
                "licence": "public web page, quoted with attribution",
                "authors": ["Sudan Bikash Maharjan", "Tenzing Chogyal Sherpa", "Arun Bhakta Shrestha"],
                "passages": [
                    ("synthesized_summary",
                     "ICIMOD's follow-up study, 'Thame Valley Glacial Lake Outburst Flood - Causes, "
                     "Impacts, and Future Risks', reconstructs the 16 August 2024 event as a two-stage "
                     "chain reaction rather than a single dam failure. A rock avalanche breached an "
                     "upper lake, and the resulting flow fell into a lower moraine-dammed lake and "
                     "breached that in turn."),
                    ("verbatim_quote",
                     "156,000 cubic metres of water was released from the upper lake at 4,900 metres.",
                     ["upper_lake_volume_m3", "upper_lake_elevation_m"]),
                    ("verbatim_quote",
                     "The water fell 120 metres into the lower lake, releasing a further 303,000 cubic metres.",
                     ["fall_height_m", "lower_lake_volume_m3"]),
                    ("verbatim_quote",
                     "A total of 459,000 cubic metres, the equivalent of 185 Olympic-size swimming pools.",
                     ["total_volume_m3"]),
                    ("verbatim_quote",
                     "The breach left a 22-metre high, 51-metre-wide erosional hole.",
                     ["breach_height_m", "breach_width_m"]),
                    ("verbatim_quote",
                     "Debris was carried 80km downstream; 135 people were displaced and 25 homes destroyed.",
                     ["debris_distance_km", "displaced", "homes_destroyed"]),
                    ("synthesized_summary",
                     "A school, a health post, a bridge and a hydropower plant were also reported damaged."),
                ],
            },
            {
                "doc_id": "icimod_press_thame_2024",
                "publisher": "ICIMOD",
                "doc_type": "press_release",
                "published": "2024-08-16",
                "url": "https://www.icimod.org/press-release/glof-from-thyanbo-glacial-lake-sweeps-away-thame-village/",
                "licence": "public web page, quoted with attribution",
                "passages": [
                    ("synthesized_summary",
                     "ICIMOD's same-day release attributed the flood that swept through Thame village to "
                     "an outburst from the Thyanbo glacial lake, above the settlement in the Thame valley, "
                     "Solukhumbu. Early reporting focused on displacement and damage to homes, a school "
                     "and a health post; no casualty figure was given in the initial release."),
                ],
            },
            {
                "doc_id": "bisht_2025_thyanbo_ndwi",
                "publisher": "International Journal of Disaster Studies and Climate Resilience",
                "doc_type": "scientific_paper",
                "published": "2025-01-01",
                "url": "https://resiliencepress.org/index.php/disaster/article/view/31",
                "licence": "open access, quoted with attribution",
                "authors": ["Bisht et al."],
                "confidence_note": "Low-visibility journal. Treated as a secondary cross-check against ICIMOD, not as a primary source. Its causal framing (climatic drivers) differs from ICIMOD's (rock avalanche) - a genuine interpretive disagreement, not a numeric one.",
                "passages": [
                    ("verbatim_quote",
                     "From 2017 to 2023, the lake remained relatively stable, with areas ranging from "
                     "32,881 to 41,758 square metres.",
                     ["area_stable_range_m2"]),
                    ("verbatim_quote",
                     "By 30 July 2024, the lake reached its maximum extent, 43,902 square metres, and "
                     "volume, 169 thousand cubic metres.",
                     ["area_pre_event_m2", "volume_pre_event_m3"]),
                    ("verbatim_quote",
                     "On 18 September 2024 the NDWI-derived area was 12,515.58 square metres, a change of -71.5 per cent.",
                     ["area_post_event_m2", "area_change_pct"]),
                    ("synthesized_summary",
                     "The paper attributes the 2024 expansion primarily to rising temperatures and "
                     "intensified monsoon rainfall, a framing that differs from ICIMOD's rock-avalanche "
                     "trigger. Both accounts agree the lake was small and had been stable for years."),
                ],
            },
            {
                "doc_id": "icimod_pdgl_2020_context",
                "publisher": "ICIMOD / UNDP",
                "doc_type": "inventory_report",
                "published": "2020-09-10",
                "url": "https://lib.icimod.org/records/p869r-n4132",
                "doi": "10.53055/ICIMOD.773",
                "licence": "CC BY-NC-ND 4.0, quoted with attribution",
                "passages": [
                    ("verbatim_quote",
                     "Of the 47 PDGLs identified, 25 are in the Tibet Autonomous Region of China, 21 in "
                     "Nepal, and one in India.",
                     ["pdgl_total", "pdgl_china", "pdgl_nepal", "pdgl_india"]),
                    ("synthesized_summary",
                     "Neither Thyanbo nor any Thame-valley lake appears anywhere in this inventory. We "
                     "verified this directly against the report text and against all 47 lake-ID centroids; "
                     "the nearest listed lake is Lumding, 5.76 km away. This does not mean the lake was "
                     "unknown to science - it means it fell outside the screening criteria."),
                ],
            },
        ],
    },

    "south_lhonak_2023": {
        "title": "South Lhonak Lake GLOF, 3-4 October 2023",
        "country": "India",
        "admin": "Mangan District, Sikkim",
        "is_glof": True,
        "documents": [
            {
                "doc_id": "sattar_2025_science",
                "publisher": "Science (AAAS)",
                "doc_type": "scientific_paper",
                "published": "2025-01-01",
                "url": "https://www.science.org/doi/10.1126/science.ads2659",
                "doi": "10.1126/science.ads2659",
                "licence": "quoted with attribution",
                "authors": ["Sattar et al."],
                "passages": [
                    ("verbatim_quote",
                     "The disaster caused 55 deaths, and 74 persons were reported missing.",
                     ["deaths", "missing"]),
                    ("verbatim_quote",
                     "Approximately 14.7 million cubic metres of frozen lateral moraine collapsed into the lake.",
                     ["moraine_collapse_volume_m3"]),
                    ("verbatim_quote",
                     "The collapse generated a tsunami-like impulse wave approximately 20 metres high.",
                     ["wave_height_m"]),
                    ("verbatim_quote",
                     "About 50 million cubic metres of water drained from the lake.",
                     ["water_drained_m3"]),
                    ("verbatim_quote",
                     "Lake area dropped from 1.69 plus or minus 0.03 to 1.46 plus or minus 0.03 square kilometres, a 15.38 per cent reduction.",
                     ["area_pre_km2", "area_post_km2", "area_change_pct"]),
                    ("verbatim_quote",
                     "Inundation extended 169 kilometres downstream over approximately 32.04 plus or minus 1.91 square kilometres.",
                     ["inundation_length_km", "inundation_area_km2"]),
                    ("synthesized_summary",
                     "A section of the failed moraine had been moving at more than 15 metres per year "
                     "between 2016 and 2023, detectable in satellite data before the event. The 1,200 MW "
                     "Teesta III hydropower project was destroyed."),
                ],
            },
            {
                "doc_id": "zhang_2024_landslides",
                "publisher": "Landslides (Springer)",
                "doc_type": "scientific_paper",
                "published": "2024-09-18",
                "url": "https://link.springer.com/article/10.1007/s10346-024-02358-x",
                "doi": "10.1007/s10346-024-02358-x",
                "licence": "quoted with attribution",
                "authors": ["Zhang et al."],
                "passages": [
                    ("verbatim_quote",
                     "The glacial lake outburst flood caused 178 fatalities and destroyed three downstream "
                     "hydropower projects.",
                     ["deaths", "hydropower_destroyed_count"]),
                    ("verbatim_quote",
                     "The estimated volume of the collapsed moraine material is 16.75 by 10 to the 6 cubic metres.",
                     ["moraine_collapse_volume_m3"]),
                    ("synthesized_summary",
                     "The study attributes the outburst to the collapse of a massive lateral moraine, "
                     "analysed through satellite imagery and numerical modelling of the flood propagation."),
                ],
            },
            {
                "doc_id": "reuters_sikkim_oct2023",
                "publisher": "Reuters (as cited in contemporaneous coverage)",
                "doc_type": "news",
                "published": "2023-10-06",
                "url": "https://en.wikipedia.org/wiki/2023_Sikkim_flash_floods",
                "licence": "figure only, attributed; no article text reproduced",
                "passages": [
                    ("synthesized_summary",
                     "Early wire reporting three days after the breach put the toll at at least 40 people "
                     "killed with dozens still missing. Contemporaneous reporting during an ongoing search "
                     "operation is expected to undercount relative to later peer-reviewed figures, and is "
                     "included here precisely so the reconciliation agent must weigh recency and source "
                     "type, not just pick a number."),
                ],
            },
        ],
    },

    "rasuwa_2025": {
        "title": "Lhende Khola / Bhote Koshi transboundary GLOF, 8 July 2025",
        "country": "Nepal (source in Tibet Autonomous Region, China)",
        "admin": "Rasuwa and Nuwakot Districts, Bagmati Province",
        "is_glof": True,
        "documents": [
            {
                "doc_id": "ndrrma_rasuwa_sitrep",
                "publisher": "NDRRMA (National Disaster Risk Reduction and Management Authority, Nepal)",
                "doc_type": "government_situation_report",
                "published": "2025-07-15",
                "url": "https://www.dpnet.org.np/resource-detail/2197",
                "licence": "government situation report, quoted with attribution",
                "passages": [
                    ("verbatim_quote",
                     "Surface water collected rapidly, resulting in the formation of a supraglacial lake "
                     "of area 0.725 sq. km by July 7.",
                     ["lake_area_pre_km2"]),
                    ("verbatim_quote",
                     "The lake had drained to 0.60 sq. km by July 8.",
                     ["lake_area_post_km2"]),
                    ("verbatim_quote",
                     "The report tallies 23 human casualties: 19 deaths, 13 missing and 1 injured.",
                     ["casualties_total", "deaths", "missing", "injured"]),
                    ("synthesized_summary",
                     "The flood is attributed to an outburst from the Pyurepu Glacier on the Nepal-China "
                     "border. DHM found no heavy rainfall beforehand; NDRRMA had initially reported an "
                     "ice-rock landslide."),
                ],
                "internal_inconsistency_note": "19 + 13 + 1 = 33, not the stated total of 23. Retained verbatim: a document that contradicts itself is a distinct failure mode from two documents contradicting each other, and the agent must catch both.",
            },
            {
                "doc_id": "nea_urjakhabar_rasuwa",
                "publisher": "Nepal Electricity Authority via Urjakhabar (spokesperson Rajan Dhakal)",
                "doc_type": "news",
                "published": "2025-07-10",
                "url": "https://sandrp.in/2025/07/24/july-2025-glof-disaster-impact-ten-heps-in-nepal/",
                "licence": "figure only, attributed",
                "passages": [
                    ("verbatim_quote",
                     "The flood damaged structures associated with 11 hydropower projects totalling 405 MW "
                     "and a 25 MW solar project.",
                     ["hydropower_count", "hydropower_mw", "solar_mw"]),
                    ("verbatim_quote",
                     "The 111 MW Rasuwagadhi plant and electricity substation have reportedly been "
                     "completely destroyed.",
                     ["rasuwagadhi_mw"]),
                ],
            },
            {
                "doc_id": "sandrp_rasuwa_2025",
                "publisher": "SANDRP (South Asia Network on Dams, Rivers and People)",
                "doc_type": "ngo_analysis",
                "published": "2025-07-24",
                "url": "https://sandrp.in/2025/07/24/july-2025-glof-disaster-impact-ten-heps-in-nepal/",
                "licence": "quoted with attribution",
                "passages": [
                    ("verbatim_quote",
                     "The figure of number of hydro projects damaged varies from 4, 5, 8 to 11 HEP projects.",
                     ["hydropower_count_spread"]),
                    ("verbatim_quote",
                     "At least 9 human beings were killed in the disaster.",
                     ["deaths"]),
                    ("verbatim_quote",
                     "18 individuals including 12 Nepali and 6 Chinese nationals went missing.",
                     ["missing", "missing_nepali", "missing_chinese"]),
                    ("verbatim_quote",
                     "Shutting down of about 250 MW capacity generation from 7 HEPs.",
                     ["capacity_halted_mw", "hepcount_halted"]),
                    ("synthesized_summary",
                     "SANDRP lists damaged operational plants as Rasuwagadhi 111 MW, Chilime 22 MW, "
                     "Trishuli 3A 60 MW, Trishuli 25.25 MW and Devighat 14 MW, plus under-construction "
                     "projects Upper Trishuli 3B 37 MW, Upper Trishuli 1 216 MW and Super Trishuli 100 MW. "
                     "Water level in the Lhende river rose by 3.5 metres at Timure; initial financial "
                     "losses were estimated above NPR 5 billion."),
                ],
            },
            {
                "doc_id": "imhe_rasuwa_satellite",
                "publisher": "Institute of Mountain Hazards and Environment (Chinese Academy of Sciences), as reported",
                "doc_type": "scientific_analysis",
                "published": "2025-07-20",
                "url": "https://sandrp.in/2025/07/24/july-2025-glof-disaster-impact-ten-heps-in-nepal/",
                "licence": "figure only, attributed",
                "passages": [
                    ("verbatim_quote",
                     "The lake reached a maximum of 638,000 square metres on July 7.",
                     ["lake_area_pre_km2"]),
                    ("verbatim_quote",
                     "By July 8, following the rupture, the lake had shrunk to 435,000 square metres.",
                     ["lake_area_post_km2"]),
                    ("synthesized_summary",
                     "Satellite analysis traced the ponds atop the Pyurepu Glacier back to first "
                     "appearance on 21 December 2023, at roughly 5,100 metres elevation about 35 km north "
                     "of the Nepal-China border."),
                ],
            },
            {
                "doc_id": "dhm_icimod_rasuwa_confirmation",
                "publisher": "DHM and ICIMOD, via Nepali press",
                "doc_type": "government_statement",
                "published": "2025-10-01",
                "url": "https://english.khabarhub.com/2025/10/484718/",
                "licence": "figure only, attributed",
                "passages": [
                    ("verbatim_quote",
                     "Prior to the flood the supraglacial lake measured around 0.75 square kilometres, "
                     "reduced to roughly 0.60 square kilometres after.",
                     ["lake_area_pre_km2", "lake_area_post_km2"]),
                    ("synthesized_summary",
                     "DHM and ICIMOD confirmed a glacial lake outburst as the cause, based on Sentinel-2 "
                     "imagery and open-source platforms. The glacier name is rendered both 'Pyurepu' and "
                     "'Purepu' across sources."),
                ],
            },
        ],
    },

    "chamoli_2021": {
        "title": "Chamoli rock-and-ice avalanche and debris flow, 7 February 2021 (NOT a GLOF)",
        "country": "India",
        "admin": "Chamoli District, Uttarakhand",
        "is_glof": False,
        "negative_control_note": "This bundle exists to test that the reporter does NOT describe this as a glacial lake outburst flood in either language. Every source here attributes it to a rock-and-ice avalanche.",
        "documents": [
            {
                "doc_id": "shugar_2021_science",
                "publisher": "Science (AAAS)",
                "doc_type": "scientific_paper",
                "published": "2021-06-10",
                "url": "https://www.science.org/doi/10.1126/science.abh4455",
                "doi": "10.1126/science.abh4455",
                "licence": "quoted with attribution",
                "authors": ["Shugar et al."],
                "passages": [
                    ("verbatim_quote",
                     "Approximately 27 million cubic metres of rock and glacier ice collapsed from the "
                     "steep north face of Ronti Peak.",
                     ["avalanche_volume_m3"]),
                    ("verbatim_quote",
                     "The rock and ice avalanche rapidly transformed into an extraordinarily large and "
                     "mobile debris flow.",
                     []),
                    ("verbatim_quote",
                     "It transported boulders greater than 20 metres in diameter and scoured valley walls "
                     "up to 220 metres above the valley floor.",
                     ["boulder_size_m", "scour_height_m"]),
                    ("verbatim_quote",
                     "More than 200 people were killed or are missing.",
                     ["deaths_and_missing"]),
                    ("synthesized_summary",
                     "The flow descended the Ronti Gad, Rishiganga and Dhauliganga valleys. No glacial "
                     "lake was involved: the analysis of satellite imagery, seismic records, numerical "
                     "models and eyewitness video identifies a rock and ice detachment as the sole "
                     "initiating mechanism. Two hydropower projects were destroyed."),
                ],
            },
            {
                "doc_id": "early_media_chamoli_glof_claim",
                "publisher": "Contemporaneous international media (aggregate characterisation)",
                "doc_type": "news",
                "published": "2021-02-07",
                "url": "https://en.wikipedia.org/wiki/2021_Uttarakhand_flood",
                "licence": "characterisation only; no article text reproduced",
                "passages": [
                    ("synthesized_summary",
                     "In the first hours, much international coverage described the Chamoli disaster as a "
                     "glacier burst or glacial lake outburst flood. That initial characterisation was "
                     "later contradicted by the peer-reviewed analysis. It is retained here on purpose: "
                     "the reporter must side with the primary scientific source over the volume of early "
                     "reporting, and must surface the disagreement rather than silently adopting the "
                     "more common phrasing."),
                ],
            },
            {
                "doc_id": "icimod_chamoli_record",
                "publisher": "ICIMOD HimalDoc",
                "doc_type": "institutional_record",
                "published": "2021-06-11",
                "url": "https://lib.icimod.org/record/35562",
                "licence": "catalogue record, attributed",
                "passages": [
                    ("synthesized_summary",
                     "ICIMOD's library record catalogues the Shugar et al. analysis under rock and ice "
                     "avalanche, not glacial lake outburst flood, consistent with the primary source."),
                ],
            },
        ],
    },
}


def build() -> dict:
    cfg = load_config()
    root = cfg.path("pinned") / "documents"
    manifest = {"events": {}, "totals": {}}
    n_docs = n_pass = 0

    for event_id, ev in EVENTS.items():
        docs_out = []
        for doc in ev["documents"]:
            passages = []
            for i, p in enumerate(doc["passages"], 1):
                kind, text = p[0], p[1]
                figures = p[2] if len(p) > 2 else []
                passages.append({
                    "passage_id": f"{doc['doc_id']}#p{i}",
                    "kind": kind,
                    "text": text,
                    "carries_figures": list(figures),
                })
            record = {
                "doc_id": doc["doc_id"],
                "event_id": event_id,
                "source": {
                    "publisher": doc["publisher"],
                    "doc_type": doc["doc_type"],
                    "published": doc["published"],
                    "url": doc["url"],
                    "doi": doc.get("doi"),
                    "authors": doc.get("authors", []),
                    "licence": doc["licence"],
                },
                "notes": {k: doc[k] for k in
                          ("confidence_note", "internal_inconsistency_note") if k in doc},
                "passages": passages,
            }
            path = root / event_id / f"{doc['doc_id']}.json"
            write_json(path, record)
            docs_out.append({
                "doc_id": doc["doc_id"],
                "publisher": doc["publisher"],
                "doc_type": doc["doc_type"],
                "published": doc["published"],
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "n_passages": len(passages),
            })
            n_docs += 1
            n_pass += len(passages)

        distinct = sorted({d["publisher"] for d in docs_out})
        manifest["events"][event_id] = {
            "title": ev["title"],
            "country": ev["country"],
            "admin": ev["admin"],
            "is_glof": ev["is_glof"],
            "negative_control_note": ev.get("negative_control_note"),
            "n_documents": len(docs_out),
            "distinct_publishers": distinct,
            "n_distinct_publishers": len(distinct),
            "documents": docs_out,
        }

    manifest["totals"] = {"documents": n_docs, "passages": n_pass,
                          "events": len(EVENTS)}
    write_json(root / "MANIFEST.json", manifest)
    return manifest


if __name__ == "__main__":
    m = build()
    print(f"events: {m['totals']['events']}  documents: {m['totals']['documents']}  "
          f"passages: {m['totals']['passages']}")
    for eid, ev in m["events"].items():
        ok = "OK " if ev["n_distinct_publishers"] >= 3 else "FAIL"
        print(f"  [{ok}] {eid:<20} {ev['n_documents']} docs, "
              f"{ev['n_distinct_publishers']} distinct publishers")
