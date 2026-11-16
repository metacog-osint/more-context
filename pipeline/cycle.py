"""One ingest cycle, run every 15 minutes: new GDELT files since the last run, plus one RSS poll.

Writes one data object per run (`cycles/YYYY/MM/DD/HHMMSS.jsonl`, rows tagged kind=gdelt|rss|events) and the
state (last GDELT stamp per stream, feed health, the last run's summary): `state/state.json` in the sink, or a
Firestore document with that object as fallback and daily backup (statestore.py, MC_STATE=firestore).
For each GKG slot read, the matching GDELT Events files are read too (events.py; ~100 KB each) and kept as one
compact record per file, a kind=events row in the same cycle file (in `events/YYYY/MM/DD/HHMMSS.json` before
30 Oct 2026: one write a run saved); the daily build turns them into country counts and, since 15 Nov 2026, the
relations between countries (relations.py). Each GKG file read also gives one kind=press row (press.py: articles and
tone by outlet country), which the same build sums into the relations files.
GDELT rows carry their zone/topic labels and, when the outlet is catalogued, its source group.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from . import blocklist, countries, daily, events, feeds, gdelt, health, ondemand, press, relations, statestore
from .budget import BudgetExceeded
from .match import Matcher
from .sources import lookup_domain

STREAMS = ("english", "translation")
MAX_FILES_PER_STREAM = 8  # catch up at most two hours in one run
# GDELT's index can list a file 30-45 minutes before it is downloadable (seen on the translation stream,
# 26 Oct 2026). A not-found file younger than this is "not published yet": stop and retry next run.
NOT_YET_PUBLISHED = timedelta(hours=3)
STATE_KEY = statestore.STATE_KEY
MAX_ALARMS_PER_RUN = 2  # each is one Vertex request (~10 s); the rest wait for the next run
MAX_PENDING_ALARMS = 50
# A day whose country build failed (countries.json, violent.jsonl, then relations) is kept in
# state["stories"]["countries_retry"] and rebuilt on a later run with no day to build, at most one day a run and
# one try an hour; after COUNTRY_RETRIES tries it moves to "countries_failed" (scripts/backfill_events.py by hand).
# The cap matters: a day's build reads all its cycle files (about 100 Class B reads).
COUNTRY_RETRY_EVERY = timedelta(hours=1)
COUNTRY_RETRIES = 6
_FMT = "%Y%m%d%H%M%S"


def stamp_time(stamp: str) -> datetime:
    return datetime.strptime(stamp, _FMT).replace(tzinfo=timezone.utc)


def stamps_after(last: str | None, latest: str, cap: int = MAX_FILES_PER_STREAM) -> list[str]:
    """15-minute stamps after `last` up to `latest`, oldest first; the most recent `cap` only.

    With no `last` (first run) it starts `cap` slots back, so files the index lists early are not the
    only candidates.
    """
    fmt = _FMT
    end = datetime.strptime(latest, fmt)
    if last is None:
        t = end - timedelta(minutes=15 * (cap - 1))
    else:
        t = datetime.strptime(last, fmt) + timedelta(minutes=15)
    out = []
    while t <= end:
        out.append(t.strftime(fmt))
        t += timedelta(minutes=15)
    return out[-cap:]


def gdelt_rows(stamp: str, stream: str, data: bytes, matcher: Matcher,
               press_table: press.FileTable | None = None) -> list[dict]:
    """The file's matched article rows. With `press_table`, every article not blocked (matched or not) is also
    counted into it (pipeline/press.py)."""
    rows = []
    for art in gdelt.parse_zip(data, stream):
        if blocklist.gdelt_reason(art.domain, art.url):  # catalog/blocklist.json: non-news, press releases, copies
            continue
        if press_table is not None:
            press_table.add(art.domain, art.tone, art.v2_locations)
        labels = matcher.labels(art)
        if not labels:
            continue
        d = art.to_dict()
        d["kind"] = "gdelt"
        d["labels"] = labels
        d["file"] = stamp
        src = lookup_domain(art.domain)
        if src:
            d.update(source=src["source"], group=src["group"], owner=src["owner"])
        rows.append(d)
    return rows


def run_cycle(sink, now: datetime | None = None, streams=STREAMS, poll_rss: bool = True,
              latest=gdelt.latest_stamp, download=gdelt.download, poll=feeds.poll,
              build_stories: bool = True, ai_on: bool | None = None, code_alarm=ondemand.code_entity_day,
              download_events=None, store=None) -> dict:
    now = now or datetime.now(timezone.utc)
    store = store or statestore.SinkState(sink)
    # Events follow the live GKG downloader; a test that fakes GKG files gets no Events unless it passes a fake.
    if download_events is None and download is gdelt.download:
        download_events = events.download
    done: dict[str, list[str]] = {}
    state = store.read() or {}
    gstate = state.setdefault("gdelt", {})
    matcher = Matcher()
    rows: list[dict] = []
    press_rows: list[dict] = []
    summary: dict = {"run_at": health.iso(now), "gdelt": {}, "rss": {}}

    for stream in streams:
        s = gstate.setdefault(stream, {})
        try:
            newest = latest(stream)
        except Exception as e:
            health.record_failure(s, now, f"index: {e}"[:200])
            summary["gdelt"][stream] = {"error": s["last_error"]}
            continue
        # Files not yet downloadable stay on a retry list ("pending") until they arrive or turn 3 h old,
        # so a late or skipped file never blocks the stream.
        todo = sorted(set(s.get("pending", [])) | set(stamps_after(s.get("last_stamp"), newest)))
        ok, missing, failed, waiting, scanned_rows = 0, [], [], [], 0
        pending = []
        for stamp in todo:
            young = now - stamp_time(stamp) < NOT_YET_PUBLISHED
            try:
                data = download(stamp, stream)
            except Exception as e:
                s["last_error"] = f"{stamp}: {e}"[:200]
                failed.append(stamp)
                if young:
                    pending.append(stamp)
                continue
            if data is None:
                if young:
                    waiting.append(stamp)
                    pending.append(stamp)
                else:
                    missing.append(stamp)
                continue
            ptab = press.FileTable()
            got = gdelt_rows(stamp, stream, data, matcher, ptab)
            press_rows.append(ptab.row(stamp, stream))
            rows += got
            scanned_rows += len(got)
            ok += 1
            done.setdefault(stream, []).append(stamp)
        if todo:
            s["last_stamp"] = max(todo[-1], s.get("last_stamp") or "")
        s["pending"] = pending
        if ok:
            s["last_ok"] = health.iso(now)
            s["consecutive_failures"] = 0
        s["missing_total"] = s.get("missing_total", 0) + len(missing)
        summary["gdelt"][stream] = {"files": len(todo), "ok": ok, "missing": missing, "failed": failed,
                                    "waiting": waiting, "matched": scanned_rows, "through": s.get("last_stamp")}

    event_recs = ingest_events(state, summary, now, done, download_events) if download_events else []

    if poll_rss:
        new_rows, probe = poll(state, now)
        for r in new_rows:
            r["kind"] = "rss"
        rows += new_rows
        summary["rss"] = {"new": len(new_rows), "status": dict(Counter(p["status"] for p in probe)),
                          "searches_refused": feeds.searches_refused(probe)}
        state["feed_health"] = {"at": health.iso(now), "sources": probe}

    if rows or event_recs or press_rows:
        key = f"cycles/{now:%Y/%m/%d}/{now:%H%M%S}.jsonl"
        sink.write_lines(key, rows + [events.as_row(r) for r in event_recs] + press_rows)
        summary["written"] = {"key": key, "rows": len(rows), "events_files": len(event_recs),
                              "press_files": len(press_rows)}
        state.setdefault("first_data_day", f"{now:%Y-%m-%d}")

    days = []
    if build_stories:
        first = state.get("first_data_day")
        days = daily.days_to_build((state.get("stories") or {}).get("last_day"), now,
                                   date.fromisoformat(first) if first else None)
    retry = [] if days or not build_stories else country_retry_due(state, now)
    ai_on = ondemand.ai_enabled() if ai_on is None else ai_on
    # Save ingest progress first when slow work follows: a build or a Vertex call that dies (28 Oct 2026: out of
    # memory) must not make the next run repeat this ingest. Most runs have neither and write state once, at the end:
    # in the bucket every write is a Class A operation and leaves a copy kept for a week (soft delete).
    if days or retry or (ai_on and (state.get("ai") or {}).get("pending")):
        state["last_run"] = summary
        store.write(state)

    if days:
        sstate = state.setdefault("stories", {})
        for day in days:
            try:
                summary.setdefault("stories_built", []).append(daily.build_day(sink, day))
                sstate["last_day"] = day.isoformat()
            except Exception as e:  # leave last_day; the next run retries this day
                sstate["last_error"] = f"{day}: {e}"[:200]
                summary["stories_error"] = sstate["last_error"]
                break
            # Country counts never hold up the story build; a failed one is retried on a later run.
            if not build_countries(sink, day, summary):
                note_country_failure(sstate, day, summary["countries_error"], now)
    for day in retry:
        sstate = state.setdefault("stories", {})
        if build_countries(sink, day, summary):
            sstate["countries_retry"].pop(day.isoformat(), None)
            summary["countries_retried"] = day.isoformat()
        else:
            note_country_failure(sstate, day, summary["countries_error"], now)

    run_alarms(sink, state, summary, ai_on, code_alarm)
    state["last_run"] = summary
    store.write(state, backup=bool(days))  # Firestore state: the run that builds a day refreshes the bucket copy
    return summary


def build_countries(sink, day: date, summary: dict) -> bool:
    """The day's country counts (countries.py), then relations (relations.py) from the same records. False when
    the country build failed: relations are skipped too, and the caller keeps the day for a retry."""
    try:
        recs, press_recs = countries.day_records_and_press(sink, day)
        summary.setdefault("countries_built", []).append(countries.build_day(sink, day, recs))
    except Exception as e:
        summary["countries_error"] = f"{day}: {e}"[:200]
        return False
    try:  # relations never hold up the country build
        summary.setdefault("relations_built", []).append(relations.build_day(sink, day, recs, press_recs))
    except Exception as e:
        summary["relations_error"] = f"{day}: {e}"[:200]
    return True


def note_country_failure(sstate: dict, day: date, error: str, now: datetime) -> None:
    pending = sstate.setdefault("countries_retry", {})
    entry = pending.setdefault(day.isoformat(), {"attempts": 0})
    entry.update(attempts=entry["attempts"] + 1, last=health.iso(now), error=error)
    if entry["attempts"] >= COUNTRY_RETRIES:
        failed = sstate.setdefault("countries_failed", [])
        failed.append({"day": day.isoformat(), **pending.pop(day.isoformat())})
        del failed[:-20]


def country_retry_due(state: dict, now: datetime) -> list[date]:
    """The oldest day waiting for a country rebuild whose last try was at least COUNTRY_RETRY_EVERY ago."""
    pending = (state.get("stories") or {}).get("countries_retry") or {}
    for day in sorted(pending):
        last = pending[day].get("last")
        if not last or now - health.from_iso(last) >= COUNTRY_RETRY_EVERY:
            return [date.fromisoformat(day)]
    return []


def ingest_events(state: dict, summary: dict, now: datetime, done: dict[str, list[str]], download) -> list[dict]:
    """Records of the Events files for the GKG slots read this run, plus earlier ones not published then (kept up
    to 3 h). The caller writes them into the run's cycle file."""
    estate = state.setdefault("events", {})
    recs, out = [], {}
    for stream in events.FILE_NAMES:
        s = estate.setdefault(stream, {})
        todo = sorted(set(s.get("pending", [])) | set(done.get(stream, [])))
        pending, ok, missing = [], 0, 0
        for stamp in todo:
            young = now - stamp_time(stamp) < NOT_YET_PUBLISHED
            try:
                data = download(stamp, stream)
            except Exception as e:
                s["last_error"] = f"{stamp}: {e}"[:200]
                data = None
            if data is None:
                if young:
                    pending.append(stamp)
                else:
                    missing += 1
                continue
            try:
                recs.append(events.record(events.parse_zip(data), stamp, stream))
                ok += 1
            except Exception as e:  # a damaged file: skip it
                s["last_error"] = f"{stamp}: {e}"[:200]
        s["pending"] = pending
        s["missing_total"] = s.get("missing_total", 0) + missing
        out[stream] = {"files": len(todo), "ok": ok, "waiting": len(pending)}
    summary["events"] = out
    return recs


def run_alarms(sink, state: dict, summary: dict, ai_on: bool, code_alarm) -> None:
    """Queue alarms from days built this run; when AI is on, code up to MAX_ALARMS_PER_RUN of them."""
    ai = state.setdefault("ai", {"pending": [], "done": []})
    for built in summary.get("stories_built", []):
        for eid, reasons in (built.get("alarms") or {}).items():
            ai["pending"].append({"entity": eid, "day": built["day"], "reasons": reasons, "tries": 0})
    ai["pending"] = ai["pending"][-MAX_PENDING_ALARMS:]
    if not ai_on or not ai["pending"]:
        return
    results = []
    for _ in range(min(MAX_ALARMS_PER_RUN, len(ai["pending"]))):
        job = ai["pending"].pop(0)
        try:
            r = code_alarm(sink, job["entity"], date.fromisoformat(job["day"]), "alarm")
            results.append({k: r[k] for k in ("entity", "day", "coded", "already_coded", "cost_usd")})
            ai["done"].append({**job, "coded": r["coded"], "cost_usd": r["cost_usd"]})
        except BudgetExceeded as e:
            ai["done"].append({**job, "skipped": str(e)[:120]})
            results.append({"entity": job["entity"], "day": job["day"], "skipped": "budget"})
        except Exception as e:  # network or Vertex trouble: retry later, up to three times
            job["tries"] += 1
            if job["tries"] < 3:
                ai["pending"].append(job)
            results.append({"entity": job["entity"], "day": job["day"], "error": str(e)[:120]})
    ai["done"] = ai["done"][-50:]
    summary["ai_alarms"] = results
