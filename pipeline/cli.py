"""Command line for MORE CONTEXT pipeline steps.

    python -I run.py measure-reprints --hours 6
    python -I run.py measure-reprints --from-jsonl data/raw/matched-<stamp>.jsonl
    python -I run.py rss-poll [--include-candidates] [--probe-report data/reports/probe.json]
    python -I run.py feed-health
    python -I run.py eval-relevance [--set catalog/eval/relevance_v1.jsonl]
    python -I run.py vertex-estimate [--set ...] [--per-request 25]      # no calls, no cost
    python -I run.py code-stories --cap 0.25 [--set ...] [--out ...]      # BILLABLE: needs Tom's yes
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import feeds, gdelt, health
from .match import Matcher
from .stories import build_stories

DATA = Path(__file__).resolve().parent.parent / "data"


def cmd_rss_poll(args) -> int:
    state = health.load_state()
    now = health.utcnow()
    new_rows, probe = feeds.poll(state, now, args.include_candidates)
    health.save_state(state)

    if new_rows:
        raw = DATA / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        with (raw / f"rss-{now:%Y%m%d}.jsonl").open("a", encoding="utf-8") as f:
            for r in new_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    probe.sort(key=lambda p: (p["status"] != "fresh", p["group"], p["id"]))
    print(f"{'source':<22}{'group':<16}{'status':<9}{'http':>5}{'items':>6}{'new':>5}{'newest':>8}{'gap':>7}  error")
    for p in probe:
        age = f"{p['newest_age_h']}h" if p["newest_age_h"] is not None else "-"
        gap = f"{p['median_gap_min']:g}m" if p["median_gap_min"] is not None else "-"
        print(f"{p['id']:<22}{p['group']:<16}{p['status']:<9}{p['http']:>5}{p['items'] or 0:>6}{p['new']:>5}"
              f"{age:>8}{gap:>7}  {p['error'][:60]}")
    counts = defaultdict(int)
    for p in probe:
        counts[p["status"]] += 1
    print(f"\n{len(probe)} sources: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
          + f"; {len(new_rows)} new items")
    if args.probe_report:
        Path(args.probe_report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.probe_report).write_text(json.dumps(probe, indent=1), encoding="utf-8")
    return 0


def cmd_cycle(args) -> int:
    from .cycle import run_cycle
    from .sinks import LocalSink

    started = time.time()
    summary = run_cycle(LocalSink(Path(args.root)), poll_rss=not args.no_rss)
    summary["elapsed_s"] = round(time.time() - started, 1)
    print(json.dumps(summary, indent=1))
    return 0


def cmd_build_stories(args) -> int:
    from datetime import date

    from .daily import build_day
    from .sinks import LocalSink

    print(json.dumps(build_day(LocalSink(Path(args.root)), date.fromisoformat(args.day)), indent=1))
    return 0


def cmd_eval_relevance(args) -> int:
    from . import relevance

    rep = relevance.evaluate(args.set, iters=args.iters, codings_path=args.codings)
    names = list(rep["methods"])
    lab = rep["labels"]
    print(f"{rep['set']}: {sum(lab.values())} stories (on {lab['on']}, off {lab['off']}, unclear {lab['unclear']}); "
          f"weighted to the full window in {rep['population']}\n")

    def pct(v):
        return "  -  " if v is None else f"{v:5.0%}"

    def span(ci):
        return f"{ci[0]:.0%}-{ci[1]:.0%}" if ci else "-"

    print(f"{'method':<22}{'unit':<10}{'precision':>10}{'(90%)':>10}{'retention':>11}{'off removed':>13}{'F1':>7}")
    for name in names:
        m = rep["methods"][name]
        for unit in ("stories", "articles"):
            o, ci = m["overall"][unit], m["interval_90"].get(unit, {})
            print(f"{name if unit == 'stories' else '':<22}{unit:<10}{pct(o['precision']):>10}{span(ci.get('precision')):>10}"
                  f"{pct(o['retention']):>11}{pct(o['off_removed']):>13}{pct(o['f1']):>7}")
    print(f"\nPer entity, article-weighted precision / retention:")
    print(f"{'entity':<28}{'n':>4}{'unclear':>9}" + "".join(f"{n[:18]:>20}" for n in names))
    for eid in rep["methods"][names[0]]["entities"]:
        cells = []
        for n in names:
            e = rep["methods"][n]["entities"][eid]["articles"]
            cells.append(f"{pct(e['precision']).strip():>9} / {pct(e['retention']).strip():<7}")
        first = rep["methods"][names[0]]["entities"][eid]
        print(f"{eid:<28}{first['n']:>4}{pct(first['unclear_share']):>9}" + "".join(f"{c:>20}" for c in cells))
    if rep.get("agreement"):
        print("\nlabel > model (unweighted): " + ", ".join(f"{k} {v}" for k, v in rep["agreement"].items()))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
        print(f"\nreport: {args.out}")
    return 0


def _set_stories(path: str) -> tuple[list[dict], dict | None]:
    """Stories to code: a relevance set (with its population file) or a daily stories.jsonl."""
    rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    pop_path = Path(path).with_name(Path(path).stem + ".population.json")
    pop = json.loads(pop_path.read_text(encoding="utf-8")) if pop_path.exists() else None
    out = []
    for r in rows:
        if r.get("kind") == "rss" or not r.get("entity"):
            continue
        sid = r.get("story_id") or r["id"].split(":", 1)[1]
        out.append({**r, "story_id": sid})
    return out, pop


def cmd_vertex_estimate(args) -> int:
    from . import relevance, vertex
    from .match import load_catalog

    stories, pop = _set_stories(args.set)
    plan = vertex.plan_coding(stories, load_catalog(), per_request=args.per_request)
    tin, tout = plan.tokens(args.thinking_tokens)
    per_in, per_out = tin / plan.stories, tout / plan.stories
    prices = vertex.load_prices()
    m = args.model

    def line(label, n):
        a, b = n * per_in, n * per_out
        std, bat = vertex.cost(a, b, m, prices=prices), vertex.cost(a, b, m, batch=True, prices=prices)
        print(f"{label:<44}{n:>9,.0f}{a / 1e6:>9.2f}M{b / 1e6:>8.2f}M  ${std:>8.2f}  ${bat:>7.2f}  ${std * 30:>8.0f}  ${bat * 30:>7.0f}")

    print(f"model {m}; {args.per_request} stories per request; no calls made (token counts are estimates, +-30%)")
    print(f"per story: {per_in:.0f} input + {per_out:.0f} output tokens"
          f" (output assumes {vertex.OUTPUT_TOKENS_PER_STORY}/story + {args.thinking_tokens} thinking/request)\n")
    print(f"{'scenario':<44}{'stories':>9}{'input':>10}{'output':>9}  {'standard':>9}  {'batch':>8}  {'std/30d':>9}  {'bat/30d':>8}")
    line(f"this set ({Path(args.set).name})", plan.stories)
    if pop:
        per_day = sum(e["stories"] for e in pop["entities"].values()) * 24 / 6
        line("per day: every story v4.3 matches", per_day)
        try:
            rows, _ = relevance.load_set(args.set)
            w = relevance.weights(rows, pop)
            hit = relevance.methods()["title_terms"]
            share = sum(wt for r, wt in zip(rows, w) if hit(r)) / sum(w)
            line(f"per day: headline-term filter ({share:.0%} kept)", per_day * share)
        except (KeyError, ValueError):
            pass
        n_ent = len(pop["entities"])
        line(f"per day: top 100 stories x {n_ent} entities", min(per_day, 100 * n_ent))
    print("\nStandard = online calls; batch = Vertex batch prediction (half price, results within 24 h).")
    print(f"Prices: catalog/vertex_prices.json (checked {json.loads(vertex.PRICES.read_text(encoding='utf-8'))['checked']}).")
    return 0


def cmd_code_stories(args) -> int:
    from . import vertex
    from .match import load_catalog

    stories, _ = _set_stories(args.set)
    if args.limit:
        stories = stories[:args.limit]
    plan = vertex.plan_coding(stories, load_catalog(), per_request=args.per_request)
    tin, tout = plan.tokens()
    est = vertex.cost(tin, tout, args.model)
    print(f"{plan.stories} stories in {len(plan.requests)} requests; estimated ${est:.2f}; cap ${args.cap:.2f}")
    if est > args.cap:
        print("estimate exceeds the cap; nothing sent")
        return 1
    coder = vertex.Coder(model=args.model, spend_cap_usd=args.cap, thinking_level=args.thinking_level)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    coded = 0
    with out.open("w", encoding="utf-8") as f:
        for req, codings, problems in coder.run(plan):
            for c in codings:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
            coded += len(codings)
            print(f"  {req['entity']:<28}{len(codings):>3}/{len(req['story_ids'])}  ${coder.spent:.4f}"
                  + (f"  {'; '.join(problems)[:120]}" if problems else ""), flush=True)
    u = coder.usage
    print(f"\n{coded}/{plan.stories} coded; {u['requests']} requests; tokens in {u['in']:,}, out {u['out']:,}, "
          f"thinking {u['thinking']:,}; cost ${coder.spent:.4f} (from Vertex usage counts)\n-> {out}")
    return 0

def cmd_feed_health(args) -> int:
    now = health.utcnow()
    print("GDELT streams (expected every 15 min):")
    for stream in ("english", "translation"):
        try:
            stamp = gdelt.latest_stamp(stream)
            lag = (now - health.from_iso(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[8:10]}:{stamp[10:12]}:00Z"))
            mins = lag.total_seconds() / 60
            st = "fresh" if mins <= 30 else "late" if mins <= 90 else "stale"
            print(f"  {stream:<12} latest {stamp}  {mins:.0f} min ago  {st}")
        except Exception as e:
            print(f"  {stream:<12} failing: {e}")
    rss_state = health.load_state().get("rss", {})
    srcs = {s["id"]: s for s in feeds.load_sources(include_candidates=True)}
    counts = defaultdict(list)
    for sid, src in srcs.items():
        counts[health.status(rss_state.get(sid), src["expected_minutes"], now)].append(sid)
    print("\nRSS sources:")
    for st in ("fresh", "late", "stale", "failing", "never"):
        if counts[st]:
            print(f"  {st:<8} {len(counts[st]):>3}  {', '.join(sorted(counts[st]))}")
    return 0


def collect(hours: float, streams: list[str], workers: int = 4) -> tuple[list[dict], dict]:
    """Download the window, keep articles that match a zone or topic. Returns (rows, stats)."""
    matcher = Matcher()
    jobs, ends = [], {}
    for stream in streams:
        ends[stream] = gdelt.latest_stamp(stream)
        jobs += [(s, stream) for s in gdelt.window_stamps(ends[stream], hours)]

    def work(job):
        stamp, stream = job
        data = None
        for attempt in range(2):
            try:
                data = gdelt.download(stamp, stream)
                break
            except Exception as e:  # network hiccup: one retry, then record the failure
                if attempt == 1:
                    return job, "failed", 0, 0, [], str(e)
                time.sleep(3)
        if data is None:
            return job, "missing", 0, 0, [], ""
        rows, scanned = [], 0
        for art in gdelt.parse_zip(data, stream):
            scanned += 1
            labels = matcher.labels(art)
            if labels:
                d = art.to_dict()
                d["labels"] = labels
                rows.append(d)
        return job, "ok", len(data), scanned, rows, ""

    stats = {"window_hours": hours, "streams": streams, "end_stamps": ends, "files_ok": 0,
             "files_missing": [], "files_failed": [], "bytes_downloaded": 0, "articles_scanned": 0}
    rows: list[dict] = []
    started = time.time()
    with ThreadPoolExecutor(workers) as ex:
        futures = [ex.submit(work, j) for j in jobs]
        for n, fut in enumerate(as_completed(futures), 1):
            job, status, size, scanned, got, err = fut.result()
            if status == "ok":
                stats["files_ok"] += 1
                stats["bytes_downloaded"] += size
                stats["articles_scanned"] += scanned
                rows += got
            elif status == "missing":
                stats["files_missing"].append(f"{job[1]}:{job[0]}")
            else:
                stats["files_failed"].append(f"{job[1]}:{job[0]} {err}")
            if n % 8 == 0 or n == len(jobs):
                print(f"  {n}/{len(jobs)} files, {stats['articles_scanned']:,} scanned, "
                      f"{len(rows):,} matched, {time.time() - started:.0f}s", flush=True)
    stats["elapsed_s"] = round(time.time() - started, 1)
    return rows, stats


def reprint_report(rows: list[dict], names: dict) -> list[dict]:
    by_entity: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        for label in r["labels"]:
            by_entity[label].append(r)
    report = []
    for eid in sorted(by_entity):
        arts = by_entity[eid]
        urls = {a["url"] for a in arts}
        stories = build_stories(arts)
        multi = sum(s["articles"] for s in stories if s["articles"] > 1)
        report.append({
            "entity": eid,
            "name": names.get(eid, eid),
            "articles": len(urls),
            "stories": len(stories),
            "inflation": round(len(urls) / len(stories), 2) if stories else None,
            "share_in_multi_article_stories": round(multi / len(urls), 3) if urls else None,
            "top_stories": [{k: s[k] for k in ("title", "articles", "outlets", "languages", "sample_urls")}
                            for s in stories[:5]],
        })
    report.sort(key=lambda e: -e["articles"])
    return report


def cmd_measure_reprints(args) -> int:
    matcher = Matcher()
    if args.from_jsonl:
        path = Path(args.from_jsonl)
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        stats = {"source": str(path)}
        tag = path.stem.replace("matched-", "")
    else:
        streams = [s.strip() for s in args.streams.split(",") if s.strip()]
        print(f"Downloading {args.hours} h of GKG files ({', '.join(streams)})...", flush=True)
        rows, stats = collect(args.hours, streams, args.workers)
        tag = f"{stats['end_stamps'][streams[0]]}-{args.hours:g}h"
        raw = DATA / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        with (raw / f"matched-{tag}.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    report = reprint_report(rows, matcher.names)
    total_articles = sum(e["articles"] for e in report)
    total_stories = sum(e["stories"] for e in report)
    out = {"stats": stats, "totals": {"articles": total_articles, "stories": total_stories,
           "inflation": round(total_articles / total_stories, 2) if total_stories else None},
           "entities": report}
    reports = DATA / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    dest = reports / f"reprints-{tag}.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'entity':<28}{'articles':>9}{'stories':>9}{'ratio':>7}{'in multi':>10}")
    for e in report:
        print(f"{e['entity']:<28}{e['articles']:>9,}{e['stories']:>9,}{e['inflation']:>7.2f}"
              f"{e['share_in_multi_article_stories']:>10.0%}")
    print(f"{'ALL (zone+topic labels)':<28}{total_articles:>9,}{total_stories:>9,}"
          f"{out['totals']['inflation'] or 0:>7.2f}")
    if "files_ok" in stats:
        print(f"\nfiles ok {stats['files_ok']}, missing {len(stats['files_missing'])}, failed "
              f"{len(stats['files_failed'])}; {stats['bytes_downloaded'] / 1e6:,.0f} MB; "
              f"{stats['articles_scanned']:,} articles scanned in {stats['elapsed_s']}s")
    print(f"report: {dest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pipeline.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure-reprints", help="how much reprints inflate article counts")
    m.add_argument("--hours", type=float, default=6)
    m.add_argument("--streams", default="english,translation")
    m.add_argument("--workers", type=int, default=4)
    m.add_argument("--from-jsonl", help="re-run grouping on a saved matched-*.jsonl file")
    m.set_defaults(func=cmd_measure_reprints)
    r = sub.add_parser("rss-poll", help="fetch RSS sources once, store new items, update feed health")
    r.add_argument("--include-candidates", action="store_true", help="also poll sources not yet approved")
    r.add_argument("--probe-report", help="write per-source results to this JSON file")
    r.set_defaults(func=cmd_rss_poll)
    h = sub.add_parser("feed-health", help="status of GDELT and every RSS source")
    h.set_defaults(func=cmd_feed_health)
    c = sub.add_parser("cycle", help="run one 15-minute ingest cycle into a local folder (cloud dry run)")
    c.add_argument("--root", default=str(DATA / "cloudsim"))
    c.add_argument("--no-rss", action="store_true")
    c.set_defaults(func=cmd_cycle)
    b = sub.add_parser("build-stories", help="build one day's stories from a local folder of cycle files")
    b.add_argument("--day", required=True, help="YYYY-MM-DD (UTC)")
    b.add_argument("--root", default=str(DATA / "cloudsim"))
    b.set_defaults(func=cmd_build_stories)
    e = sub.add_parser("eval-relevance", help="score relevance methods against a labelled story set")
    e.add_argument("--set", default=str(DATA.parent / "catalog" / "eval" / "relevance_v1.jsonl"))
    e.add_argument("--iters", type=int, default=2000, help="bootstrap resamples (0 to skip intervals)")
    e.add_argument("--out", help="also write the full report as JSON")
    e.add_argument("--codings", help="model codings from code-stories, scored as extra methods")
    e.set_defaults(func=cmd_eval_relevance)
    default_set = str(DATA.parent / "catalog" / "eval" / "relevance_v1.jsonl")
    v = sub.add_parser("vertex-estimate", help="dry-run token and cost estimate for coding stories (no calls)")
    v.add_argument("--set", default=default_set, help="relevance set or a daily stories.jsonl")
    v.add_argument("--per-request", type=int, default=25)
    v.add_argument("--model", default="gemini-3.1-flash-lite")
    v.add_argument("--thinking-tokens", type=int, default=0, help="assumed thinking tokens per request")
    v.set_defaults(func=cmd_vertex_estimate)
    k = sub.add_parser("code-stories", help="BILLABLE: code stories with Gemini on Vertex under a spend cap")
    k.add_argument("--cap", type=float, required=True, help="hard spend cap in USD (approved by Tom)")
    k.add_argument("--set", default=default_set)
    k.add_argument("--limit", type=int, default=0)
    k.add_argument("--per-request", type=int, default=25)
    k.add_argument("--model", default="gemini-3.1-flash-lite")
    k.add_argument("--thinking-level", default=None, help="e.g. minimal or low; omitted = model default")
    k.add_argument("--out", default=str(DATA / "coding" / "relevance_v1.codings.jsonl"))
    k.set_defaults(func=cmd_code_stories)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
