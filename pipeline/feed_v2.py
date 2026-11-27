"""One built day of Watchfloor in The Intelligence Company's feed contract v2 (tic-feed/2), as GeoJSON.

Served by the API at GET /feed?day=YYYY-MM-DD from the same data as /summary and /countries, so it costs no extra
storage writes. Every item is a measurement (kind observation): a daily summary, one item per zone (a point at the
zone) and per topic (no place; a link to its page), and one per country on the violence Rising or Elevated list or the
attention Rising list. Warnings, which are judged, wait for the zone charters (doctrine/indicators.json).

Since the z calibration (picked 16 Nov 2026; docs/method/2026-11-16-z-calibration.md):
- every z is calibrated (scores carry `z_method`; stored days 29 Jul-15 Nov were re-scored on 17 Nov 2026 by
  scripts/rescore_z.py), so titles say plain "z" (they said "calibrated z" from 16 to 17 Nov 2026, feed 1.1);
- titles give count / max(expected, 90-day median, 3), and when the floor of 3 binds they give the count instead
  ("15 articles, usually 3 or fewer"), so a near-zero baseline no longer reads "79.3x normal";
- a zone country on a country list is a neutral observation under the zone's warning problem, not support for its
  H1: the country count has no headline filter (44% of its articles name the zone, 12 Aug-15 Nov). Counting only
  zone-named articles waits for the charters;
- a day whose countries.json is missing (a country build waiting for its retry, or given up) is marked partial and
  its summary says "no country data", never "0 countries rising".

Since contract revision 2.1 (feed 1.4, ideas#183): every item names its `subject_id` (the dated `id` stays), its
`event_start` (the UTC day, `event_time_precision: day`; no `event_end`, because a source never says a day's count
"ended"), and its `last_change`, read from the tiers of the last LOOKBACK_DAYS built days. `none` means no change in
that window. Partial days and days without country data are skipped, since their tiers cannot be compared. An anomaly
carries `signal`, the count its tier rests on. Nothing here writes to storage.

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
from tic_doctrine import CONTRACT, CONTRACT_REV, contract, registers, vocab  # noqa: E402
from pipeline.zone_scope import scope_id  # noqa: E402

SITE = "https://watchfloor.theintelligence.company"
METHOD = "watchfloor-feed-1.4"  # 1.4 (23 Nov 2026): contract 2.1 fields; 1.3: origins on country items
LOOKBACK_DAYS = 35                     # built days read for last_change (two small reads a day, cached)
ONE_STORY_SHARE = 0.15  # Australia violence 21 Oct 2026: one column was 30 of 167
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
    """'2.9x normal (z 3.4)' from a score; 'at 15, usually 3 or fewer (z 2.7)' when the ratio's floor binds; 'no score
    yet' before 14 days of history."""
    if not x or x.get("z") is None:
        return "no score yet"
    if x.get("floored") and count is not None:
        return f"at {count}, usually 3 or fewer (z {x['z']:.1f})"
    r = x.get("ratio_shown", x.get("ratio"))
    ratio = f"{r:.1f}x normal" if r is not None else "normal not known"
    return f"{ratio} (z {x['z']:.1f})"


def _one_story(og: dict, articles: int | None) -> str:
    """'; one story is 30 of its 85 articles' when the largest origin is at least ONE_STORY_SHARE of the count
    (independent origins, 18 Nov 2026: shown, never scored)."""
    big = og.get("largest") or 0
    if not articles or big < 5 or big < ONE_STORY_SHARE * articles:
        return ""
    return f"; one story is {big} of its {articles} articles"


def _ncf_rules() -> dict:
    return {r["match"]["entity"]: r["ncf"] for r in json.loads((DOCTRINE / "ncf_map.json").read_text(encoding="utf-8"))["rules"]}


def _sources(*which, accessed: str) -> list[dict]:
    return [{**s, "accessed_at": accessed} for s in which]


def _point(lat_lon) -> dict | None:
    return {"type": "Point", "coordinates": [lat_lon[1], lat_lon[0]]} if lat_lon else None


def _feature(geom, props) -> dict:
    return {"type": "Feature", "geometry": geom, "properties": props}


def _zone_hits(e: dict, partial: bool) -> tuple[bool, bool, list]:
    """(attention alarm, violence alarm, member spikes) for one zone or topic. A partial day raises none."""
    vio = e.get("violence") or {}
    vscore = vio.get("named_score")
    att_hit = bool(e.get("alarms")) and not partial
    spikes = [] if partial else [k for k in vio.get("spikes") or [] if k in (vio.get("members") or {})]
    vio_hit = (bool(vscore and vscore.get("z") is not None and vscore["z"] >= ALARM_Z
                    and (vio.get("named") or 0) >= MIN_ARTICLES) or bool(spikes)) and not partial
    return att_hit, vio_hit, spikes


def _signal(name: str, count, score: dict | None, unit: str, expected=None) -> dict | None:
    """The contract's signal from a stored score. `expected` overrides the score's (the Elevated list's 90-day median)."""
    if count is None:
        return None
    score = score or {}
    central = score.get("expected") if expected is None else expected
    out = {"name": name, "value": count, "unit": unit, "tail": "high"}
    if central is not None:
        out["expected"] = central
    if isinstance(score.get("baseline_days"), int) and expected is None:
        out["baseline_n"] = score["baseline_days"]
    return out


def _zone_signal(e: dict, att_hit: bool, vio_hit: bool, spikes: list) -> dict | None:
    """The one count a zone's anomaly rests on: of the tests it tripped, the one with the highest z."""
    vio = e.get("violence") or {}
    options = []
    if att_hit:
        options.append(((e.get("attention") or {}).get("z"),
                        _signal("headline-matched stories", e.get("filtered_stories"), e.get("attention"), "stories")))
    vscore = vio.get("named_score") or {}
    if vio_hit and vscore.get("z") is not None and vscore["z"] >= ALARM_Z and (vio.get("named") or 0) >= MIN_ARTICLES:
        options.append((vscore["z"], _signal("violent-event articles naming the zone", vio.get("named"), vscore,
                                             "articles")))
    for k in spikes:
        mv = vio["members"][k]
        options.append(((mv.get("named_score") or {}).get("z"),
                        _signal(f"violent-event articles naming the zone, in {k}", mv.get("named"),
                                mv.get("named_score"), "articles")))
    options = [(z if z is not None else float("-inf"), sig) for z, sig in options if sig]
    return max(options, key=lambda o: o[0])[1] if options else None


def _country_subject(iso_code: str, measure: str) -> str:
    return f"watchfloor:country:{iso_code}:{measure}"


def day_states(summary: dict, countries: dict | None, catalog: dict, fips: dict) -> dict | None:
    """{subject_id: tier} for one built day, or None when its tiers cannot be compared (partial or no country data).
    A country series has a state only on the days it is listed."""
    if countries is None or summary.get("partial") or countries.get("partial"):
        return None
    ents = summary.get("entities") or {}
    out = {}
    for kind, rows in (("zone", catalog["zones"]), ("topic", catalog["topics"])):
        for z in rows:
            if z["id"] in ents:
                att, vio, _ = _zone_hits(ents[z["id"]], False)
                out[f"watchfloor:{kind}:{z['id']}"] = "anomaly" if att or vio else "routine"
    lists = countries.get("lists") or {}
    violent = lists.get("violent") or {}
    for measure, codes in (("violence", (violent.get("rising") or []) + (violent.get("elevated") or [])),
                           ("attention", (lists.get("urls") or {}).get("rising") or [])):
        for cc in codes:
            code = (fips.get(cc) or {}).get("iso")
            if code:
                out[_country_subject(code, measure)] = "anomaly"
    return out


def last_change(subject: str, tier: str, day: str, states: list[tuple[str, dict]]) -> tuple[str, str | None]:
    """(last_change, last_change_at) from comparable days, newest first and all before `day`. The item's own tier is
    the newest reading. A country series that was off its list and came back has crossed its threshold (`raised`); a
    zone or topic missing from an earlier day is `new`."""
    newer_day, newer = day, tier
    for older_day, state in states:
        older = state.get(subject)
        if older != newer:
            if older is None:
                return ("raised" if subject.startswith("watchfloor:country:") else "new"), f"{newer_day}T00:00:00Z"
            return ("raised" if newer == "anomaly" else "lowered"), f"{newer_day}T00:00:00Z"
        newer_day = older_day
    return "none", None


def build(summary: dict, countries: dict | None, *, catalog: dict | None = None, fips: dict | None = None,
          now: datetime | None = None, history: list[tuple[str, dict]] | None = None) -> dict:
    """The day's FeatureCollection. `summary` and `countries` are the API's /summary and /countries bodies. `history`
    is day_states() for earlier built days, newest first; without it items state no last_change rather than a guess."""
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
    base = {**COMMON, "data_as_of": as_of, "data_as_of_precision": "day", "published_at": published,
            "event_start": as_of, "event_time_precision": "day"}
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
        att_hit, vio_hit, spikes = _zone_hits(e, partial)
        wp = _wp(z["id"])
        page = f"{SITE}/#/zone/{z['id']}?day={day}"
        title = f"{z['name']}: news attention {_times(att, e.get('filtered_stories'))}"
        if kind == "zone":
            title += f"; violent-event articles {_times(vscore, vio.get('named'))}"
            for k in spikes:
                mv = vio["members"][k]
                name = mv.get("name") or (fips.get(k) or {}).get("name") or k
                title += f"; spike in {name}: {mv['named']} articles, {_times(mv.get('named_score'), mv['named'])}"
        props = {**base, "id": f"watchfloor:{day}:{kind}:{z['id']}", "subject_id": f"watchfloor:{kind}:{z['id']}",
                 "title": title,
                 "tier": "anomaly" if (att_hit or vio_hit) else "routine",
                 "warning_problem_id": wp, "requirement_ids": ["WF-PIR-1"] + (["WF-PIR-2"] if kind == "zone" else []),
                 "ie_aspect": ["informational"] + (["physical"] if kind == "zone" else []),
                 "pmesii_pt": ["military", "political"] if kind == "zone" else ["economic", "infrastructure"],
                 "ascope": ["events"],
                 "countries": sorted({iso(cc) for cc in z.get("countries", []) if iso(cc)}),
                 "sources": _sources(GKG, *([EVENTS] if kind == "zone" else []), accessed=published),
                 "measures": {"attention": att, "stories": e.get("filtered_stories"),
                              "catalog_version": catalog.get("catalog_version"), "zone_scope": scope_id(z),
                              **({"violence": vscore, "violent_articles": vio.get("named")} if kind == "zone" else {})},
                 "indicators_present": [i for i, hit in (("WF-IND-1", att_hit), ("WF-IND-2", vio_hit)) if hit],
                 "link": page}
        if att_hit or vio_hit:
            props.update({"baseline_ref": BASE_28, "indicator_id": "WF-IND-2" if vio_hit else "WF-IND-1",
                          "hypothesis_id": f"{wp}-H1", "direction": "supports" if vio_hit else "neutral",
                          "indicator_state": "present"})
            sig = _zone_signal(e, att_hit, vio_hit, spikes)
            if sig:
                props["signal"] = sig
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
        og = (row.get("origins") or {}).get("violent" if measure == "violence" else "urls") or {}
        if measure == "violence":
            what = (f"violent-event articles {_times(score, articles)}, on the Rising list" if listed == "rising" else
                    f"violent-event articles {score.get('ratio90') or 0:.1f}x its 90-day median, on the Elevated list")
        else:
            what = f"news attention {_times(score, articles)}, on the Rising list"
        what += _one_story(og, articles)
        unit = "articles"
        label = "violent-event articles" if measure == "violence" else "articles"
        sig = _signal(label, articles, score, unit, expected=score.get("median90") if listed == "elevated" else None)
        props = {**base, "id": f"watchfloor:{day}:country:{cc}:{measure}",
                 "subject_id": _country_subject(info["iso"], measure), "title": f"{name}: {what}",
                 **({"signal": sig} if sig else {}),
                 "tier": "anomaly", "baseline_ref": BASE_28 if listed == "rising" else BASE_90,
                 "precision_class": "country", "countries": [info["iso"]],
                 "ie_aspect": ["physical"] if measure == "violence" else ["informational"],
                 "pmesii_pt": ["military"] if measure == "violence" else ["information"], "ascope": ["events"],
                 "sources": _sources(EVENTS, accessed=published),
                 "measures": {"articles": articles, "score": score, "list": listed,
                              **({"origins": og["origins"], "largest_origin": og["largest"]} if og else {})},
                 "link": f"{SITE}/#/map?day={day}"}
        if zone:
            # No hypothesis (16 Nov 2026): the country count is not filtered to the zone. The kit allows no
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
    head = {**base, "id": f"watchfloor:{day}:summary", "subject_id": "watchfloor:summary:daily", "tier": "routine",
            "precision_class": "none",
            "title": (f"Watchfloor, {_plain(day)}: {n_att} of {n_entities} zones and topics above normal attention; "
                      f"{n_vio} of {len(catalog['zones'])} zones with violence above normal; "
                      + ("no country data" if no_countries else f"{len(vio_rising)} countries rising on violence")
                      + (" (partial day: no alarms)" if partial else "")),
            "requirement_ids": ["WF-PIR-1", "WF-PIR-2", "WF-PIR-3"], "ie_aspect": ["informational", "physical"],
            "pmesii_pt": ["military", "political", "information"], "ascope": ["events"], "countries": [],
            "sources": _sources(GKG, EVENTS, accessed=published),
            "visual": {"type": "map", "url": f"{SITE}/#/map?day={day}"}, "link": f"{SITE}/#/?day={day}"}
    feats.insert(0, _feature(None, head))

    if history is not None:
        for f in feats:
            p = f["properties"]
            if p["subject_id"] == "watchfloor:summary:daily":
                p["last_change"] = "none"  # one routine item a day: it has no level to move
                continue
            if (partial or no_countries) and history:
                # Today's tiers are held down by the missing data, so the last whole day is the newest reading.
                newest_day, newest = history[0]
                held = newest.get(p["subject_id"])
                change, at = (last_change(p["subject_id"], held, newest_day, history[1:]) if held is not None else
                              last_change(p["subject_id"], p["tier"], day, history))
            else:
                change, at = last_change(p["subject_id"], p["tier"], day, history)
            p["last_change"] = change
            if at:
                p["last_change_at"] = at

    regs = registers.ids(DOCTRINE)
    kept, dropped = [], []
    for f in feats:
        errs = [m for std, sev, m in contract.check(f, regs, CONTRACT_REV) if sev == "error"]
        if errs:
            dropped.append({"id": f["properties"].get("id"), "errors": errs})
        else:
            kept.append(f)
    return {"type": "FeatureCollection", "contract": CONTRACT, "contract_rev": CONTRACT_REV, "program": "watchfloor",
            "day": day,
            "generated_at": _utc(now),
            "licence": f"Watchfloor terms of use ({SITE}/#/terms); news data from The GDELT Project under its terms",
            "attribution": "Watchfloor, The Intelligence Company. News data: The GDELT Project (gdeltproject.org).",
            "language_key": LANGUAGE_KEY, "dropped": dropped, "features": kept}
