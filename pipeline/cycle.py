"""One ingest cycle, run every 15 minutes: new GDELT files since the last run, plus one RSS poll.

Writes one data object per run (`cycles/YYYY/MM/DD/HHMMSS.jsonl`, rows tagged kind=gdelt|rss) and the
state object (`state/state.json`: last GDELT stamp per stream, feed health, the last run's summary).
GDELT rows carry their zone/topic labels and, when the outlet is catalogued, its source group.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from . import daily, feeds, gdelt, health, ondemand
from .budget import BudgetExceeded
from .match import Matcher
from .sources import lookup_domain

STREAMS = ("english", "translation")
MAX_FILES_PER_STREAM = 8  # catch up at most two hours in one run
# GDELT's index can list a file 30-45 minutes before it is downloadable (seen on the translation stream,
# 26 Oct 2026). A not-found file younger than this is "not published yet": stop and retry next run.
NOT_YET_PUBLISHED = timedelta(hours=3)
STATE_KEY = "state/state.json"
MAX_ALARMS_PER_RUN = 2  # each is one Vertex request (~10 s); the rest wait for the next run
MAX_PENDING_ALARMS = 50
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


def gdelt_rows(stamp: str, stream: str, data: bytes, matcher: Matcher) -> list[dict]:
    rows = []
    for art in gdelt.parse_zip(data, stream):
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
              build_stories: bool = True, ai_on: bool | None = None, code_alarm=ondemand.code_entity_day) -> dict:
    now = now or datetime.now(timezone.utc)
    state = sink.read_json(STATE_KEY) or {}
    gstate = state.setdefault("gdelt", {})
    matcher = Matcher()
    rows: list[dict] = []
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
            got = gdelt_rows(stamp, stream, data, matcher)
            rows += got
            scanned_rows += len(got)
            ok += 1
        if todo:
            s["last_stamp"] = max(todo[-1], s.get("last_stamp") or "")
        s["pending"] = pending
        if ok:
            s["last_ok"] = health.iso(now)
            s["consecutive_failures"] = 0
        s["missing_total"] = s.get("missing_total", 0) + len(missing)
        summary["gdelt"][stream] = {"files": len(todo), "ok": ok, "missing": missing, "failed": failed,
                                    "waiting": waiting, "matched": scanned_rows, "through": s.get("last_stamp")}

    if poll_rss:
        new_rows, probe = poll(state, now)
        for r in new_rows:
            r["kind"] = "rss"
        rows += new_rows
        summary["rss"] = {"new": len(new_rows), "status": dict(Counter(p["status"] for p in probe)),
                          "searches_refused": feeds.searches_refused(probe)}
        state["feed_health"] = {"at": health.iso(now), "sources": probe}

    if rows:
        key = f"cycles/{now:%Y/%m/%d}/{now:%H%M%S}.jsonl"
        sink.write_lines(key, rows)
        summary["written"] = {"key": key, "rows": len(rows)}
        state.setdefault("first_data_day", f"{now:%Y-%m-%d}")

    # Save ingest progress first: a build that dies (28 Oct 2026: out of memory) must not make the next run
    # repeat this ingest.
    state["last_run"] = summary
    sink.write_json(STATE_KEY, state)

    if build_stories:
        sstate = state.setdefault("stories", {})
        first = state.get("first_data_day")
        for day in daily.days_to_build(sstate.get("last_day"), now, date.fromisoformat(first) if first else None):
            try:
                summary.setdefault("stories_built", []).append(daily.build_day(sink, day))
                sstate["last_day"] = day.isoformat()
            except Exception as e:  # leave last_day; the next run retries this day
                sstate["last_error"] = f"{day}: {e}"[:200]
                summary["stories_error"] = sstate["last_error"]
                break

    run_alarms(sink, state, summary, ondemand.ai_enabled() if ai_on is None else ai_on, code_alarm)
    state["last_run"] = summary
    sink.write_json(STATE_KEY, state)
    return summary


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
