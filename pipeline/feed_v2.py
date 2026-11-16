"""One built day of Watchfloor in The Intelligence Company's feed contract v2 (tic-feed/2), as GeoJSON.

Served by the API at GET /feed?day=YYYY-MM-DD from the same data as /summary and /countries, so it costs no extra
storage writes. Every item is a measurement (kind observation): a daily summary, one item per zone (a point at the
zone) and per topic (no place; a link to its page), and one per country on the violence Rising or Elevated list or the
attention Rising list. Warnings, which are judged, wait for the zone charters (doctrine/indicators.json).

Since the z calibration (Tom's picks, 16 Nov 2026; docs/method/2026-11-16-z-calibration.md):
- a score carrying `z_method` is a calibrated z, and titles say "calibrated z" for the first month;
- titles give count / max(expected, 90-day median, 3), and when the floor of 3 binds they give the count instead
  ("15 articles, usually 3 or fewer"), so a near-zero baseline no longer reads "79.3x normal";
- a zone country on a country list is a neutral observation under the zone's warning problem, not support for its
  H1: the country count has no headline filter (44% of its articles name the zone, 12 Aug-15 Nov). Counting only
  zone-named articles waits for the charters;
- a day whose countries.json is missing (a country build waiting for its retry, or given up) is marked partial and
  its summary says "no country data", never "0 countries rising".

Each item is checked by the doctrine kit's contract linter (doctrine/kit); one that fails is left out and listed in
the header's `dropped`, so a bad item never breaks the feed.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))
from tic_doctrine import CONTRACT, contract, registers, vocab  # noqa: E402

SITE = "https://watchfloor.theintelligence.company"
METHOD = "watchfloor-feed-1.1"
FILES_PER_DAY = 192                     # GDELT Events: 96 fifteen-minute files a day in each of two streams
ALARM_Z, MIN_ARTICLES = 2.0, 5         # zone violence anomaly, matching the attention alarm (z >= 2, >= 5 stories)
LANGUAGE_KEY = "https://github.com/metacog-osint/noise-floor/blob/main/doctrine/kit/docs/language-key.md"
GDELT = {"publisher": "The GDELT Project", "url": "https://www.gdeltproject.org/",
         "licence": "GDELT terms: free for any use with a citation and a link to gdeltproject.org",
         "grade": "C3", "independence_group": "gdelt", "source_type": "dataset"}
GKG = {"id": "gdelt-gkg", **GDELT, "title": "Global Knowledge Graph 2.1 (15-minute files)",
       "descriptor": "Machine-read world news, English and translated streams; Watchfloor groups reprints into stories "
                     "and keeps those whose headline names the zone or topic."}
EVENTS = {"id": "gdelt-events", **GDELT, "title": "Events 2.0 export (15-minute files)",
          "descriptor": "Machine-coded CAMEO events with a geocoded place; Watchfloor counts articles per country and "
                        "zone. Single events can be misplaced, so only counts are used."}
BASE_28 = {"id": "wf-28d", "window": "previous 28 complete days, weekday-adjusted (log-scale z)", "type": "rolling",
           "version": "1"}
BASE_90 = {"id": "wf-90d-median", "window": "90-day median", "type": "rolling", "version": "1"}
COMMON = {"contract": CONTRACT, "program": "watchfloor", "kind": "observation", "status": "actual", "msg_type": "new",
          "human_review": "none", "us_person_data": "none", "status_class": "reported", "method_version": METHOD,
          "product_category": "current"}
DOCTRINE = ROOT / "doctrine"


def _load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def _plain(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d.day} {d:%b %Y}"


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _wp(eid: str) -> str:
    head = eid.split("_")[0]
    return f"WF-WP-{'Z' + head if head.isdigit() else head}"


def _times(x: dict | None, count: int | None = None) -> str:
    """'2.9x normal (calibrated z 3.4)' from a score; 'at 15, usually 3 or fewer (calibrated z 2.7)' when the ratio's
    floor binds; 'no score yet' before 14 days of history. Scores built before the calibration keep the old wording."""
    if not x or x.get("z") is None:
        return "no score yet"
    zlab = "calibrated z" if x.get("z_method") else "z"
    if x.get("floored") and count is not None:
        return f"at {count}, usually 3 or fewer ({zlab} {x['z']:.1f})"
    r = x.get("ratio_shown", x.get("ratio"))
    ratio = f"{r:.1f}x normal" if r is not None else "normal not known"
    return f"{ratio} ({zlab} {x['z']:.1f})"


def _ncf_rules() -> dict:
    return {r["match"]["entity"]: r["ncf"] for r in json.loads((DOCTRINE / "ncf_map.json").read_text(encoding="utf-8"))["rules"]}


def _sources(*which, accessed: str) -> list[dict]:
    return [{**s, "accessed_at": accessed} for s in which]


def _point(lat_lon) -> dict | None:
    return {"type": "Point", "coordinates": [lat_lon[1], lat_lon[0]]} if lat_lon else None


def _feature(geom, props) -> dict:
    return {"type": "Feature", "geometry": geom, "properties": props}


def build(summary: dict, countries: dict | None, *, catalog: dict | None = None, fips: dict | None = None,
          now: datetime | None = None) -> dict:
    """The day's FeatureCollection. `summary` and `countries` are the API's /summary and /countries bodies."""
    catalog = catalog or _load("catalog/entities.json")
    fips = fips or _load("catalog/fips_iso.json")["codes"]
    now = now or datetime.now(timezone.utc)
    day = summary["day"]
    # Whole-UTC-day items: the source gives no time, so say "day" and put data_as_of at midnight UTC (kit 0.5.6
    # contract); consumers then show a date, never a clock time such as "5:59 PM".
    as_of = f"{day}T00:00:00Z"
    published = summary.get("built_at") or _utc(now)
    files = (countries or {}).get("files")
    coverage = round(min(1.0, files / FILES_PER_DAY), 3) if files else None
    no_countries = countries is None
    partial = bool(summary.get("partial") or (countries or {}).get("partial"))
    ents = summary.get("entities") or {}
    ncf_rules = _ncf_rules()
    base = {**COMMON, "data_as_of": as_of, "data_as_of_precision": "day", "published_at": published}
    if coverage is not None:
        base["coverage_fraction"] = coverage
    if partial or no_countries:
        base["partial_day"] = True
    iso = lambda cc: (fips.get(cc) or {}).get("iso")  # noqa: E731
    zone_of = {cc: z["id"] for z in catalog["zones"] for cc in z.get("countries", [])}
    feats = []

    def zone_item(z: dict, kind: str):
        e = ents.get(z["id"]) or {}
        att, vio = e.get("attention"), (e.get("violence") or {})
        vscore = vio.get("named_score")
        att_hit = bool(e.get("alarms")) and not partial
        vio_hit = bool(vscore and vscore.get("z") is not None and vscore["z"] >= ALARM_Z
                       and (vio.get("named") or 0) >= MIN_ARTICLES) and not partial
        wp = _wp(z["id"])
        page = f"{SITE}/#/zone/{z['id']}?day={day}"
        title = f"{z['name']}: news attention {_times(att, e.get('filtered_stories'))}"
        if kind == "zone":
            title += f"; violent-event articles {_times(vscore, vio.get('named'))}"
        props = {**base, "id": f"watchfloor:{day}:{kind}:{z['id']}", "title": title,
                 "tier": "anomaly" if (att_hit or vio_hit) else "routine",
                 "warning_problem_id": wp, "requirement_ids": ["WF-PIR-1"] + (["WF-PIR-2"] if kind == "zone" else []),
                 "ie_aspect": ["informational"] + (["physical"] if kind == "zone" else []),
                 "pmesii_pt": ["military", "political"] if kind == "zone" else ["economic", "infrastructure"],
                 "ascope": ["events"],
                 "countries": sorted({iso(cc) for cc in z.get("countries", []) if iso(cc)}),
                 "sources": _sources(GKG, *([EVENTS] if kind == "zone" else []), accessed=published),
                 "measures": {"attention": att, "stories": e.get("filtered_stories"),
                              **({"violence": vscore, "violent_articles": vio.get("named")} if kind == "zone" else {})},
                 "indicators_present": [i for i, hit in (("WF-IND-1", att_hit), ("WF-IND-2", vio_hit)) if hit],
                 "link": page}
        if att_hit or vio_hit:
            props.update({"baseline_ref": BASE_28, "indicator_id": "WF-IND-2" if vio_hit else "WF-IND-1",
                          "hypothesis_id": f"{wp}-H1", "direction": "supports" if vio_hit else "neutral",
                          "indicator_state": "present"})
        if kind == "zone":
            props["precision_class"] = "area"
            return _feature(_point(z.get("map")), props)
        ncf = ncf_rules.get(z["id"], [])
        if ncf:
            props.update({"ncf": ncf, "sector": vocab.derive_sectors(ncf)})
        props.update({"precision_class": "none", "visual": {"type": "page", "url": page}})
        return _feature(None, props)

    for z in catalog["zones"]:
        feats.append(zone_item(z, "zone"))
    for t in catalog["topics"]:
        feats.append(zone_item(t, "topic"))

    def country_item(cc: str, measure: str, listed: str):
        info = fips.get(cc) or {}
        if not info.get("iso"):
            return None
        row = ((countries or {}).get("countries") or {}).get(cc) or {}
        score = row.get(f"{'violent' if measure == 'violence' else 'urls'}_score") or {}
        zone = zone_of.get(cc)
        name = info.get("name") or row.get("name") or cc
        articles = row.get("violent" if measure == "violence" else "urls")
        if measure == "violence":
            what = (f"violent-event articles {_times(score, articles)}, on the Rising list" if listed == "rising" else
                    f"violent-event articles {score.get('ratio90') or 0:.1f}x its 90-day median, on the Elevated list")
        else:
            what = f"news attention {_times(score, articles)}, on the Rising list"
        props = {**base, "id": f"watchfloor:{day}:country:{cc}:{measure}", "title": f"{name}: {what}",
                 "tier": "anomaly", "baseline_ref": BASE_28 if listed == "rising" else BASE_90,
                 "precision_class": "country", "countries": [info["iso"]],
                 "ie_aspect": ["physical"] if measure == "violence" else ["informational"],
                 "pmesii_pt": ["military"] if measure == "violence" else ["information"], "ascope": ["events"],
                 "sources": _sources(EVENTS, accessed=published),
                 "measures": {"articles": articles, "score": score, "list": listed},
                 "link": f"{SITE}/#/map?day={day}"}
        if zone:
            # No hypothesis (Tom, 16 Nov 2026): the country count is not filtered to the zone. The kit allows no
            # indicator_id without a hypothesis_id, so the indicator link goes too; the warning problem stays.
            props.update({"warning_problem_id": _wp(zone), "requirement_ids": ["WF-PIR-2"]})
        else:
            props.update({"requirement_ids": ["WF-PIR-3"], "review_queue": True})
        geom = _point(info.get("point"))
        if geom is None:
            props["visual"] = {"type": "map", "url": f"{SITE}/#/map?day={day}"}
        return _feature(geom, props)

    lists = (countries or {}).get("lists") or {}
    vio_rising = list((lists.get("violent") or {}).get("rising") or [])
    vio_elev = [cc for cc in (lists.get("violent") or {}).get("elevated") or [] if cc not in vio_rising]
    att_rising = list((lists.get("urls") or {}).get("rising") or [])
    for cc in vio_rising:
        feats.append(country_item(cc, "violence", "rising"))
    for cc in vio_elev:
        feats.append(country_item(cc, "violence", "elevated"))
    for cc in att_rising:
        feats.append(country_item(cc, "attention", "rising"))
    feats = [f for f in feats if f]

    n_att = sum(1 for f in feats if "WF-IND-1" in f["properties"].get("indicators_present", []))
    n_vio = sum(1 for f in feats if "WF-IND-2" in f["properties"].get("indicators_present", []))
    n_entities = len(catalog["zones"]) + len(catalog["topics"])
    head = {**base, "id": f"watchfloor:{day}:summary", "tier": "routine", "precision_class": "none",
            "title": (f"Watchfloor, {_plain(day)}: {n_att} of {n_entities} zones and topics above normal attention; "
                      f"{n_vio} of {len(catalog['zones'])} zones with violence above normal; "
                      + ("no country data" if no_countries else f"{len(vio_rising)} countries rising on violence")
                      + (" (partial day: no alarms)" if partial else "")),
            "requirement_ids": ["WF-PIR-1", "WF-PIR-2", "WF-PIR-3"], "ie_aspect": ["informational", "physical"],
            "pmesii_pt": ["military", "political", "information"], "ascope": ["events"], "countries": [],
            "sources": _sources(GKG, EVENTS, accessed=published),
            "visual": {"type": "map", "url": f"{SITE}/#/map?day={day}"}, "link": f"{SITE}/#/?day={day}"}
    feats.insert(0, _feature(None, head))

    regs = registers.ids(DOCTRINE)
    kept, dropped = [], []
    for f in feats:
        errs = [m for std, sev, m in contract.check(f, regs) if sev == "error"]
        if errs:
            dropped.append({"id": f["properties"].get("id"), "errors": errs})
        else:
            kept.append(f)
    return {"type": "FeatureCollection", "contract": CONTRACT, "program": "watchfloor", "day": day,
            "generated_at": _utc(now),
            "licence": f"Watchfloor terms of use ({SITE}/#/terms); news data from The GDELT Project under its terms",
            "attribution": "Watchfloor, The Intelligence Company. News data: The GDELT Project (gdeltproject.org).",
            "language_key": LANGUAGE_KEY, "dropped": dropped, "features": kept}
