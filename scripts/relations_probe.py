"""Relations-and-tone probe (15 Nov 2026): what GDELT Events says about pairs of countries, read-only and free.

A prototype for Watchfloor's proposed relations layer, measured first on the Korean Peninsula. It downloads the
public GDELT Events 2.0 files (English and translation streams, one per 15 minutes; no GCP, no BigQuery) and keeps,
per day, three compact tables and the raw rows that touch the focus country:

- `dyads`: per directed country pair (Actor1 country > Actor2 country, CAMEO codes such as PRK, KOR, USA), the
  events, article-weighted counts (NumArticles) in each QuadClass (1 verbal cooperation, 2 material cooperation,
  3 verbal conflict, 4 material conflict), article-weighted sums of GoldsteinScale and AvgTone, distinct source
  articles, and article-weighted counts of lead-paragraph (root) events.
- `within`: the same vector for events whose two actors share a country, split by actor type: S (state: GOV,
  MIL, COP, JUD, SPY, LEG), P (people and society: CVL, OPP, REB, LAB, REF, HRI, MED and the like), O (other typed
  actors, e.g. IGO, NGO) and N (no type code). `PRK|S>P` is the North Korean state acting on its people.
- `press`: per outlet country (GDELT's 2018 domain-to-country table, FIPS codes) and subject actor country, the
  distinct articles, the sum of their tone, and how many carried a conflict event (QuadClass 3 or 4) about it.
  Event AvgTone is the mean tone of the documents that mentioned the event in its first 15 minutes; for most
  events that is the one source article.

Events dated more than two days before their file are references to the past and are skipped, as in
`pipeline/events.py`. Days are assigned by file time (DATEADDED), not by the event's own date.

    python -I scripts/relations_probe.py fetch --start 2026-08-16 --end 2026-11-14 --root data/relations
    python -I scripts/relations_probe.py series --root data/relations --focus PRK --partners KOR,USA,JPN,CHN,RUS

`fetch` writes `days/YYYY-MM-DD.json.gz` and `rows/YYYY-MM-DD.tsv.gz` (rows whose actor is the focus country or
whose action is placed there) and skips days already written, so it can be rerun after an interruption.
`series` writes `series/*.csv` and `series/series.json`: daily and 7-day values for the focus country with each
partner, both directions, with z-scores against each series' own previous 28 days (`pipeline.measures`).
`spikes` lists the articles behind each unusual day, `score` matches flags against a dated event list
(docs/relations/korea_events.json), `chart` draws the SVG in docs/relations/, and `gkg-sample` measures press tone
by outlet country from a sample of GKG files. Findings: docs/relations/2026-11-15-relations-tone.md.
Downloaded data stays under --root (keep it in the git-ignored `data/`).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import events, measures  # noqa: E402

STREAMS = ("english", "translation")
A1CC, A1T1, A2CC, A2T1, GOLD, TONE = 7, 12, 17, 22, 30, 34
STATE = frozenset({"GOV", "MIL", "COP", "JUD", "SPY", "LEG"})
PEOPLE = frozenset({"CVL", "OPP", "REB", "INS", "LAB", "EDU", "HLH", "MED", "REF", "HRI", "AGR", "BUS", "CRM",
                    "ELI", "SEP", "UAF", "RAD", "MOD", "DEV", "ENV", "SET"})
# Vector layout for dyads and within. GDELT-weighted: events, NumArticles, NumArticles by quad 1-4, Goldstein x
# NumArticles, tone x NumArticles, NumArticles of root (lead-paragraph) events. Per article (one vote per source
# URL, since one article yields several coded events): distinct URLs, URLs with an event in quad 1-4, URLs with
# any conflict event (quad 3 or 4), the sum over URLs of each URL's mean Goldstein and mean tone, URLs with a
# root event.
VEC = ("ev", "art", "q1", "q2", "q3", "q4", "gs", "tn", "urls", "rart",
       "u1", "u2", "u3", "u4", "uconf", "ugs", "utn", "uroot")
PRESS = ("urls", "tn", "conf")
FOCUS_FIPS = {"PRK": "KN", "KOR": "KS", "USA": "US", "JPN": "JA", "CHN": "CH", "RUS": "RS"}
# GDELT's table places outlets by the country they cover, not who runs them. Corrections for this probe:
DOMAIN_OVERRIDES = {
    "nknews.org": "XX",  # NK News: specialist outlet about North Korea, run from Seoul and the US, not North Korean
    "kcna.co.jp": "KN",  # KCNA relay run by the Korea News Service in Tokyo: North Korean state text
    "kcnawatch.org": "XX",  # NK News' archive of North Korean state media
}


# ---------------------------------------------------------------- outlet country

class Outlets:
    """Domain -> FIPS country from GDELT's MASTER-GDELTDOMAINSBYCOUNTRY-MAY2018.TXT (domain, FIPS, name)."""

    def __init__(self, path: Path):
        self.table: dict[str, str] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                f = line.split("\t")
                if len(f) >= 2 and f[0] and f[1]:
                    self.table[f[0].strip().lower()] = f[1].strip()
        self.table.update(DOMAIN_OVERRIDES)

    def country(self, url: str) -> str:
        host = (urlsplit(url).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        parts = host.split(".")
        for i in range(len(parts) - 1):
            cc = self.table.get(".".join(parts[i:]))
            if cc:
                return cc
        return "?"


DOMAINS_URL = ("https://data.gdeltproject.org/blog/2018-news-outlets-by-country-may2018-update/"
               "MASTER-GDELTDOMAINSBYCOUNTRY-MAY2018.TXT")


def load_outlets(a) -> Outlets:
    """GDELT's domain table (download it once from DOMAINS_URL to --domains); outlets are '?' without it."""
    o = Outlets(Path(a.domains))
    if len(o.table) < 1000:
        print(f"warning: no domain table at {a.domains} ({DOMAINS_URL}); outlet countries will be '?'", flush=True)
    return o


# ---------------------------------------------------------------- fetch

def _group(t: str) -> str:
    if not t:
        return "N"
    if t in STATE:
        return "S"
    if t in PEOPLE:
        return "P"
    return "O"


def _f(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


class Day:
    def __init__(self, day: date, focus: str, focus_fips: str, outlets: Outlets):
        self.day, self.focus, self.focus_fips, self.outlets = day, focus, focus_fips, outlets
        self.oldest = (day - timedelta(days=events.MAX_AGE_DAYS)).strftime("%Y%m%d")
        self.vec: dict[str, dict[str, list[float]]] = {"dyads": {}, "within": {}}
        self.vec_urls: dict[tuple[str, str], dict[str, list]] = {}
        self.url_info: dict[str, dict] = {}
        self.rows_kept: list[str] = []
        self.files = {s: 0 for s in STREAMS}
        self.n_rows = self.n_old = 0

    def add_file(self, rows: list[list[str]], stream: str, stamp: str) -> None:
        self.files[stream] += 1
        for r in rows:
            self.n_rows += 1
            if r[events.DAY] < self.oldest:
                self.n_old += 1
                continue
            a1, a2 = r[A1CC], r[A2CC]
            if a1 == self.focus or a2 == self.focus or r[events.GCC] == self.focus_fips:
                self.rows_kept.append(stream + "\t" + stamp + "\t" + "\t".join(r))
            if not a1 and not a2:
                continue
            try:
                quad = int(r[events.QUAD])
            except ValueError:
                continue
            art = max(1, int(r[events.NUM_ARTICLES] or 1))
            gold, tone = _f(r[GOLD]), _f(r[TONE])
            url = r[events.URL]
            root = r[events.ROOT] == "1"
            if a1 and a2:
                if a1 != a2:
                    self._add("dyads", f"{a1}|{a2}", quad, art, gold, tone, url, root)
                else:
                    g = f"{_group(r[A1T1])}>{_group(r[A2T1])}"
                    self._add("within", f"{a1}|{g}", quad, art, gold, tone, url, root)
            info = self.url_info.get(url)
            if info is None:
                info = self.url_info[url] = {"tones": [], "subj": set(), "conf": set()}
            if tone is not None:
                info["tones"].append(tone)
            for cc in {a1, a2} - {""}:
                info["subj"].add(cc)
                if quad >= 3:
                    info["conf"].add(cc)

    def _add(self, table: str, key: str, quad: int, art: int, gold, tone, url: str, root: bool) -> None:
        v = self.vec[table].get(key)
        if v is None:
            v = self.vec[table][key] = [0] * len(VEC)
            self.vec_urls[(table, key)] = {}
        v[0] += 1
        v[1] += art
        if 1 <= quad <= 4:
            v[1 + quad] += art
        if gold is not None:
            v[6] += gold * art
        if tone is not None:
            v[7] += tone * art
        if root:
            v[9] += art
        # per URL: [quad bitmask, Goldstein sum, Goldstein n, tone sum, tone n, root]
        u = self.vec_urls[(table, key)].get(url)
        if u is None:
            u = self.vec_urls[(table, key)][url] = [0, 0.0, 0, 0.0, 0, 0]
        if 1 <= quad <= 4:
            u[0] |= 1 << quad
        if gold is not None:
            u[1] += gold
            u[2] += 1
        if tone is not None:
            u[3] += tone
            u[4] += 1
        if root:
            u[5] = 1

    def result(self) -> dict:
        for (table, key), urls in self.vec_urls.items():
            v = self.vec[table][key]
            v[8] = len(urls)
            for mask, gsum, gn, tsum, tn, root in urls.values():
                for q in (1, 2, 3, 4):
                    if mask & (1 << q):
                        v[9 + q] += 1
                if mask & 0b11000:
                    v[14] += 1
                if gn:
                    v[15] += gsum / gn
                if tn:
                    v[16] += tsum / tn
                v[17] += root
        press: dict[str, list[float]] = {}
        for url, info in self.url_info.items():
            if not info["tones"]:
                continue
            t = mean(info["tones"])
            oc = self.outlets.country(url)
            for cc in info["subj"]:
                p = press.setdefault(f"{oc}>{cc}", [0, 0.0, 0])
                p[0] += 1
                p[1] += t
                if cc in info["conf"]:
                    p[2] += 1
        rnd = lambda v: [round(x, 1) if isinstance(x, float) else x for x in v]  # noqa: E731
        return {
            "day": self.day.isoformat(), "files": self.files, "rows": self.n_rows, "skipped_old": self.n_old,
            "vec": list(VEC), "press_vec": list(PRESS),
            "dyads": {k: rnd(v) for k, v in self.vec["dyads"].items()},
            "within": {k: rnd(v) for k, v in self.vec["within"].items()},
            "press": {k: rnd(v) for k, v in press.items()},
        }


def _download(stamp: str, stream: str) -> tuple[str, str, list[list[str]] | None]:
    for attempt in range(4):
        try:
            data = events.download(stamp, stream)
            return stamp, stream, (events.parse_zip(data) if data is not None else None)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 + attempt * 4)
    return stamp, stream, None


def fetch(a) -> int:
    root = Path(a.root)
    (root / "days").mkdir(parents=True, exist_ok=True)
    (root / "rows").mkdir(parents=True, exist_ok=True)
    outlets = load_outlets(a)
    focus_fips = FOCUS_FIPS.get(a.focus, "")
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    until = datetime.now(timezone.utc) - timedelta(minutes=20)
    d = start
    with ThreadPoolExecutor(a.workers) as ex:
        while d <= end:
            out = root / "days" / f"{d}.json.gz"
            if out.exists():
                d += timedelta(days=1)
                continue
            t0 = time.time()
            stamps = []
            t = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            while t.date() == d and t <= until:
                stamps.append(t.strftime("%Y%m%d%H%M%S"))
                t += timedelta(minutes=15)
            acc = Day(d, a.focus, focus_fips, outlets)
            failed = 0
            futs = [ex.submit(_download, s, st) for s in stamps for st in STREAMS]
            for fut in futs:
                try:
                    stamp, stream, rows = fut.result()
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"  failed: {str(e)[:100]}", flush=True)
                    continue
                if rows is not None:
                    acc.add_file(rows, stream, stamp)
            res = acc.result()
            res["failed"] = failed
            res["slots"] = len(stamps)
            with gzip.open(root / "rows" / f"{d}.tsv.gz", "wt", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(acc.rows_kept) + ("\n" if acc.rows_kept else ""))
            tmp = out.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                json.dump(res, fh, separators=(",", ":"))
            tmp.replace(out)
            print(f"{d}: files {res['files']}, failed {failed}, rows {res['rows']}, dyads {len(res['dyads'])}, "
                  f"within {len(res['within'])}, press {len(res['press'])}, focus rows {len(acc.rows_kept)}, "
                  f"{time.time() - t0:.0f} s", flush=True)
            d += timedelta(days=1)
    return 0


# ---------------------------------------------------------------- series

def load_days(root: Path) -> dict[date, dict]:
    out = {}
    for p in sorted((root / "days").glob("*.json.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            rec = json.load(fh)
        out[date.fromisoformat(rec["day"])] = rec
    return out


def complete(rec: dict) -> bool:
    return all(rec["files"].get(s, 0) >= 96 * 0.9 for s in STREAMS)


def _sum(vs: list[list[float]]) -> list[float]:
    out = [0.0] * len(VEC)
    for v in vs:
        for i, x in enumerate(v):
            out[i] += x
    return out


def derived(v: list[float]) -> dict:
    """Measures per article (distinct source URL) first; the NumArticles-weighted ones keep an `art_` prefix."""
    i = {k: n for n, k in enumerate(VEC)}
    n, art = v[i["urls"]], v[i["art"]]
    return {
        "urls": n, "u1": v[i["u1"]], "u2": v[i["u2"]], "u3": v[i["u3"]], "u4": v[i["u4"]],
        "uconf": v[i["uconf"]], "uroot": v[i["uroot"]],
        "gold": round(v[i["ugs"]] / n, 3) if n else None,
        "tone": round(v[i["utn"]] / n, 3) if n else None,
        "conflict": round(v[i["uconf"]] / n, 4) if n else None,
        "matconf": round(v[i["u4"]] / n, 4) if n else None,
        "ev": v[i["ev"]], "art": art,
        "art_gold": round(v[i["gs"]] / art, 3) if art else None,
        "art_conflict": round((v[i["q3"]] + v[i["q4"]]) / art, 4) if art else None,
    }


# z floors for 7-day means and shares, in their own units. Well under the spread seen on the Korea pairs
# (sd of the 7-day Goldstein 0.8 to 2.1, of the conflict share 0.08 to 0.17; docs/relations/), so rarely used.
FLOORS = {"gold7": 0.3, "tone7": 0.3, "conflict7": 0.03}


def window_z(values: dict[date, float | None], day: date, floor: float) -> dict | None:
    """z of the 7-day value ending `day` against the 7-day values ending 7-34 days earlier (windows that do not
    overlap the current one), so a week is compared with the four weeks before it."""
    x = values.get(day)
    if x is None:
        return None
    base = [values.get(day - timedelta(days=k)) for k in range(7, 35)]
    base = [b for b in base if b is not None]
    if len(base) < 14:
        return None
    mu, sd = mean(base), max(pstdev(base), floor)
    return {"z": round((x - mu) / sd, 2), "baseline": round(mu, 3)}


def series_for(days: dict[date, dict], keys_fn) -> list[dict]:
    """Daily rows for one series; keys_fn(rec) -> list of vectors to add for that day."""
    dlist = sorted(days)
    daily = {d: _sum(keys_fn(days[d])) for d in dlist}
    ok = {d: complete(days[d]) for d in dlist}
    rows = []
    col = {k: n for n, k in enumerate(VEC)}
    hists = {name: {d: daily[d][col[name]] for d in dlist if ok[d]} for name in ("urls", "u3", "u4")}
    w7: dict[date, dict] = {}
    for d in dlist:
        win = [d - timedelta(days=k) for k in range(7)]
        if all(w in daily and ok[w] for w in win):
            w7[d] = derived(_sum([daily[w] for w in win]))
    vals = {m: {d: w7[d][m.replace("7", "")] for d in w7} for m in ("gold7", "tone7", "conflict7")}
    for d in dlist:
        row = {"day": d.isoformat(), "complete": ok[d], **derived(daily[d])}
        if ok[d]:
            for name, hist in hists.items():
                z = measures.attention_anomaly(hist, d, daily[d][col[name]])
                row[f"z_{name}"] = z["z"] if z else None
                if name == "urls":
                    row["expected_urls"] = z["expected"] if z else None
        if d in w7:
            row.update({"urls7": w7[d]["urls"], "u3_7": w7[d]["u3"], "u4_7": w7[d]["u4"], "gold7": w7[d]["gold"],
                        "tone7": w7[d]["tone"], "conflict7": w7[d]["conflict"]})
            for m in ("gold7", "tone7", "conflict7"):
                z = window_z(vals[m], d, FLOORS[m])
                row[f"z_{m}"] = z["z"] if z else None
        rows.append(row)
    return rows


COLS = ("day", "complete", "urls", "u1", "u2", "u3", "u4", "uconf", "uroot", "gold", "tone", "conflict",
        "matconf", "ev", "art", "art_gold", "art_conflict", "z_urls", "expected_urls", "z_u3", "z_u4", "urls7",
        "u3_7", "u4_7", "gold7", "tone7", "conflict7", "z_gold7", "z_tone7", "z_conflict7")


def series(a) -> int:
    root = Path(a.root)
    days = load_days(root)
    if not days:
        print("no days under", root / "days")
        return 1
    out_dir = root / "series"
    out_dir.mkdir(parents=True, exist_ok=True)
    f = a.focus
    defs = {}
    for p in a.partners.split(","):
        defs[f"{f}>{p}"] = (lambda rec, k=f"{f}|{p}": [rec["dyads"].get(k, [0] * len(VEC))])
        defs[f"{p}>{f}"] = (lambda rec, k=f"{p}|{f}": [rec["dyads"].get(k, [0] * len(VEC))])
        defs[f"{f}-{p}"] = (lambda rec, k1=f"{f}|{p}", k2=f"{p}|{f}":
                            [rec["dyads"].get(k1, [0] * len(VEC)), rec["dyads"].get(k2, [0] * len(VEC))])
    defs[f"{f}>any"] = lambda rec: [v for k, v in rec["dyads"].items() if k.startswith(f + "|")]
    defs[f"any>{f}"] = lambda rec: [v for k, v in rec["dyads"].items() if k.endswith("|" + f)]
    for g in ("S>P", "P>S", "S>S", "P>P"):
        defs[f"{f}:{g}"] = (lambda rec, k=f"{f}|{g}": [rec["within"].get(k, [0] * len(VEC))])
    result = {}
    for name, fn in defs.items():
        rows = series_for(days, fn)
        result[name] = rows
        with open(out_dir / f"{name.replace('>', '_to_').replace(':', '_')}.csv", "w", newline="",
                  encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    # Press: outlet country (FIPS) -> subject (CAMEO), daily distinct articles and mean tone.
    press = {}
    subj = f
    for d in sorted(days):
        rec = days[d]
        for k, v in rec["press"].items():
            oc, cc = k.split(">", 1)
            if cc != subj:
                continue
            press.setdefault(oc, {})[d.isoformat()] = v
    result["press"] = press
    meta = {"focus": f, "partners": a.partners.split(","), "days": [d.isoformat() for d in sorted(days)],
            "complete": [d.isoformat() for d in sorted(days) if complete(days[d])],
            "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    with open(out_dir / "series.json", "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "series": result}, fh, separators=(",", ":"))
    print(f"{len(days)} days ({len(meta['complete'])} complete), {len(defs)} series -> {out_dir}")
    return 0


# ---------------------------------------------------------------- spikes (what drove an unusual day)

SPIKE_Z = 2.5


def focus_rows(root: Path, d: date) -> list[list[str]]:
    p = root / "rows" / f"{d}.tsv.gz"
    if not p.exists():
        return []
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return [line.rstrip("\n").split("\t") for line in fh if line.strip()]


def spikes(a) -> int:
    """Days where a focus series is unusual (z >= SPIKE_Z on articles, verbal or material conflict, or |z| >=
    SPIKE_Z on the 7-day Goldstein, tone or conflict share), each with the articles behind it."""
    root = Path(a.root)
    data = json.loads((root / "series" / "series.json").read_text(encoding="utf-8"))
    f = data["meta"]["focus"]
    out_lines = []
    for name, rows in data["series"].items():
        if name == "press" or not any(s in name for s in (">", "-")):
            continue
        for r in rows:
            why = []
            for m in ("z_urls", "z_u3", "z_u4"):
                if (r.get(m) or 0) >= SPIKE_Z:
                    why.append(f"{m} {r[m]}")
            for m in ("z_gold7", "z_tone7", "z_conflict7"):
                if abs(r.get(m) or 0) >= SPIKE_Z:
                    why.append(f"{m} {r[m]}")
            if not why:
                continue
            d = date.fromisoformat(r["day"])
            directed = ">" in name
            a1, _, a2 = name.replace("-", ">").partition(">")
            arts: dict[str, list] = {}
            for x in focus_rows(root, d):
                e = x[2:]
                c1, c2 = e[A1CC], e[A2CC]
                if not c1 or not c2 or c1 == c2:
                    continue
                if directed and not ((a1 in (c1, "any")) and (a2 in (c2, "any"))):
                    continue
                if not directed and {c1, c2} != {a1, a2}:
                    continue
                arts.setdefault(e[events.URL], []).append(f"{e[5]}>{e[15]} {e[events.CODE]} q{e[events.QUAD]}")
            top = sorted(arts.items(), key=lambda kv: -len(kv[1]))[:a.top]
            out_lines.append(f"{r['day']} {name}: {', '.join(why)} | urls {r['urls']} (expected "
                             f"{r.get('expected_urls')}), u3 {r['u3']}, u4 {r['u4']}, gold7 {r.get('gold7')}")
            for url, evs in top:
                out_lines.append(f"    {url[:140]}  [{'; '.join(sorted(set(evs))[:4])}]")
    text = "\n".join(out_lines)
    (root / "series" / "spikes.txt").write_text(text + "\n", encoding="utf-8")
    print(text[:a.print_chars])
    return 0


# ---------------------------------------------------------------- score against a reference event list

def score(a) -> int:
    """For each reference event: did the series for its partners flag (z >= --z) within +/- --slack days?
    And for each flagged day: is a reference event within the slack? Prints both tables."""
    root = Path(a.root)
    data = json.loads((root / "series" / "series.json").read_text(encoding="utf-8"))
    ser, f = data["series"], data["meta"]["focus"]
    evs = json.loads(Path(a.events).read_text(encoding="utf-8"))["events"]
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    checks = {"volume": [("{f}-{p}", "z_urls")],
              "conflict": [("{f}>{p}", "z_u3"), ("{f}>{p}", "z_u4"), ("{p}>{f}", "z_u3"), ("{p}>{f}", "z_u4")]}
    idx = {name: {r["day"]: r for r in rows} for name, rows in ser.items() if name != "press"}

    def flags(p: str, d: date) -> list[str]:
        out = []
        for kind, specs in checks.items():
            for tmpl, m in specs:
                name = tmpl.format(f=f, p=p)
                r = idx.get(name, {}).get(d.isoformat())
                if r and (r.get(m) or 0) >= a.z and (r.get(m[2:]) or 0) >= a.min_count:
                    out.append(f"{name} {m} {r[m]} (n {r[m[2:]]:.0f})")
        return out

    print(f"Reference events, caught if a series flags z >= {a.z} (count >= {a.min_count}) within {a.slack} "
          f"day(s):")
    caught = caught_other = 0
    for e in evs:
        d0 = date.fromisoformat(e["day"])
        if not (start <= d0 <= end):
            continue
        def hits_for(ps):
            out = []
            for p in ps:
                if f"{f}-{p}" not in idx:
                    continue
                for k in range(-a.slack, a.slack + 1):
                    out += [f"{d0 + timedelta(days=k):%m-%d} {h}" for h in flags(p, d0 + timedelta(days=k))]
            return out
        hits = hits_for(e["partners"])
        other = [] if hits else hits_for([p for p in a.partners.split(",") if p not in e["partners"]])
        caught += bool(hits)
        caught_other += bool(other)
        mark = "HIT " if hits else ("HIT*" if other else "miss")
        print(f"  {mark} {e['day']} {e['kind']:<9} {','.join(e['partners']):<12} {e['what'][:70]}")
        hits = hits or other
        for h in hits[:4]:
            print(f"         {h}")
    n = sum(1 for e in evs if start <= date.fromisoformat(e["day"]) <= end)
    print(f"caught {caught} of {n} by a named partner's series; {caught_other} more only by another partner's "
          f"(HIT*)")
    near = lambda p, d: [e for e in evs if p in e["partners"]  # noqa: E731
                         and abs((date.fromisoformat(e["day"]) - d).days) <= a.slack]
    print(f"\nFlagged days (z >= {a.z}) and whether a reference event naming that partner is within {a.slack}:")
    tot = expl = 0
    for p in a.partners.split(","):
        d = start
        while d <= end:
            fl = flags(p, d)
            if fl:
                tot += 1
                ne = near(p, d)
                expl += bool(ne)
                print(f"  {d} {p}: {'event' if ne else 'none '} | {'; '.join(fl)}"
                      + (f" | {ne[0]['day']} {ne[0]['what'][:50]}" if ne else ""))
            d += timedelta(days=1)
    print(f"{expl} of {tot} flagged partner-days have a listed event within {a.slack} day(s)")
    return 0


# ---------------------------------------------------------------- chart (static SVG small multiples)

def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def chart(a) -> int:
    """Small multiples, one row per partner: articles a day naming both countries (bars; spikes in blue), the
    7-day conflict share and the 7-day mean Goldstein in each direction, with the reference events as ticks."""
    root = Path(a.root)
    data = json.loads((root / "series" / "series.json").read_text(encoding="utf-8"))
    ser, f = data["series"], data["meta"]["focus"]
    evs = json.loads(Path(a.events).read_text(encoding="utf-8"))["events"] if a.events else []
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    ndays = (end - start).days + 1
    partners = a.partners.split(",")
    names = {"KOR": "South Korea", "USA": "United States", "JPN": "Japan", "CHN": "China", "RUS": "Russia"}
    W, left, top, colw, rowh, gap = 1000, 110, 104, 282, 104, 22
    H = top + len(partners) * (rowh + gap) + 40
    xs = lambda i: i * (colw - 8) / (ndays - 1)  # noqa: E731
    css = """<style>
.bg{fill:#fcfcfb}.t1{fill:#0b0b0b}.t2{fill:#52514e}.grid{stroke:#e4e3de}.axis{stroke:#b9b8b2}
.bar{fill:#c8c7c1}.spike{fill:#2a78d6}.out{stroke:#2a78d6}.in{stroke:#eb6834}.tick{stroke:#9b9a94}
.tickall{stroke:#e4e3de}.launch{fill:#52514e}
@media (prefers-color-scheme: dark){.bg{fill:#1a1a19}.t1{fill:#f0efec}.t2{fill:#c3c2b7}.grid{stroke:#33332f}
.axis{stroke:#5b5a55}.bar{fill:#4a4945}.spike{fill:#3987e5}.out{stroke:#3987e5}.in{stroke:#d95926}
.tick{stroke:#7d7c76}.tickall{stroke:#33332f}.launch{fill:#c3c2b7}}
text{font-family:system-ui,-apple-system,'Segoe UI',sans-serif}
</style>"""
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'role="img" aria-label="North Korea with five partners, GDELT Events, {start} to {end}">', css,
         f'<rect class="bg" width="{W}" height="{H}"/>',
         f'<text class="t1" x="16" y="24" font-size="15" font-weight="600">North Korea with five partners: '
         f'GDELT Events, {start:%d %b} to {end:%d %b %Y} (UTC days)</text>',
         f'<text class="t2" x="16" y="44" font-size="12">Counted per article (distinct source URL). Blue line: '
         f'North Korea as actor ({f}&#8594;partner). Orange line: partner as actor (partner&#8594;{f}).</text>',
         f'<text class="t2" x="16" y="60" font-size="12">Dashed ticks: dated events naming that partner '
         f'(docs/relations/korea_events.json); triangles: missile launches. Lines start after 7 complete days.'
         f'</text>']
    heads = ("Articles a day, both directions (blue: z &#8805; 2.5)", "Conflict share, 7 days (quad 3+4)",
             "Mean Goldstein, 7 days (&#8722;10 to +10)")
    for c, h in enumerate(heads):
        o.append(f'<text class="t2" x="{left + c * (colw + 18)}" y="{top - 14}" font-size="12">{h}</text>')
    by_day = lambda rows: {r["day"]: r for r in rows}  # noqa: E731
    for ri, p in enumerate(partners):
        y0 = top + ri * (rowh + gap)
        o.append(f'<text class="t1" x="16" y="{y0 + rowh / 2}" font-size="13" font-weight="600">'
                 f'{names.get(p, p)}</text>')
        both, out_, in_ = (by_day(ser[f"{f}-{p}"]), by_day(ser[f"{f}>{p}"]), by_day(ser[f"{p}>{f}"]))
        days = [(start + timedelta(days=i)).isoformat() for i in range(ndays)]
        mine = [e for e in evs if p in e["partners"]]
        for c in range(3):
            x0 = left + c * (colw + 18)
            o.append(f'<line class="axis" x1="{x0}" x2="{x0 + colw - 8}" y1="{y0 + rowh}" y2="{y0 + rowh}"/>')
            for e in mine:
                i = (date.fromisoformat(e["day"]) - start).days
                if 0 <= i < ndays:
                    o.append(f'<line class="tick" x1="{x0 + xs(i):.1f}" x2="{x0 + xs(i):.1f}" y1="{y0}" '
                             f'y2="{y0 + rowh}" stroke-width="1" stroke-dasharray="2 2"/>')
                    if c == 0 and e["kind"] == "launch":
                        cx = x0 + xs(i)
                        o.append(f'<path class="launch" d="M{cx - 4:.1f} {y0 - 7} L{cx + 4:.1f} {y0 - 7} '
                                 f'L{cx:.1f} {y0 - 1} Z"><title>{_esc(e["day"] + ": " + e["what"])}</title></path>')
        # col 0: bars
        x0 = left
        vals = [both.get(d, {}).get("urls", 0) for d in days]
        vmax = max(vals + [1])
        bw = max(1.0, (colw - 8) / ndays - 1)
        for i, d in enumerate(days):
            v = vals[i]
            if not v:
                continue
            h = v / vmax * (rowh - 6)
            z = both.get(d, {}).get("z_urls")
            cls = "spike" if (z or 0) >= SPIKE_Z else "bar"
            o.append(f'<rect class="{cls}" x="{x0 + xs(i) - bw / 2:.1f}" y="{y0 + rowh - h:.1f}" width="{bw:.1f}" '
                     f'height="{h:.1f}"><title>{d}: {v} articles, z {z}</title></rect>')
        o.append(f'<text class="t2" x="{x0 - 6}" y="{y0 + 10}" font-size="10" text-anchor="end">{vmax:.0f}</text>')
        o.append(f'<text class="t2" x="{x0 - 6}" y="{y0 + rowh}" font-size="10" text-anchor="end">0</text>')
        # col 1 and 2: lines
        for c, (m, lo, hi, fmt) in enumerate((("conflict7", 0.0, 0.8, "{:.0%}"), ("gold7", -4.0, 4.0, "{:+.0f}")),
                                             start=1):
            x0 = left + c * (colw + 18)
            yv = lambda v: y0 + rowh - (min(max(v, lo), hi) - lo) / (hi - lo) * rowh  # noqa: E731
            for g in ((0.0, 0.4, 0.8) if m == "conflict7" else (-4.0, 0.0, 4.0)):
                o.append(f'<line class="grid" x1="{x0}" x2="{x0 + colw - 8}" y1="{yv(g):.1f}" y2="{yv(g):.1f}"/>')
                o.append(f'<text class="t2" x="{x0 - 4}" y="{yv(g) + 3:.1f}" font-size="10" '
                         f'text-anchor="end">{fmt.format(g)}</text>')
            for cls, rows in (("out", out_), ("in", in_)):
                pts, seg = [], []
                for i, d in enumerate(days):
                    v = rows.get(d, {}).get(m)
                    if v is None:
                        if len(seg) > 1:
                            pts.append(seg)
                        seg = []
                        continue
                    seg.append(f"{x0 + xs(i):.1f},{yv(v):.1f}")
                if len(seg) > 1:
                    pts.append(seg)
                for s in pts:
                    o.append(f'<polyline class="{cls}" fill="none" stroke-width="2" stroke-linejoin="round" '
                             f'points="{" ".join(s)}"/>')
    # month labels under the last row
    yb = top + len(partners) * (rowh + gap) - gap + 16
    for c in range(3):
        x0 = left + c * (colw + 18)
        d = start
        while d <= end:
            if d.day == 1 or d == start:
                o.append(f'<text class="t2" x="{x0 + xs((d - start).days):.1f}" y="{yb}" font-size="10">'
                         f'{d:%d %b}</text>')
            d += timedelta(days=1)
    o.append(f'<text class="t2" x="16" y="{H - 10}" font-size="10">Source: GDELT Project Events 2.0 '
             f'(gdeltproject.org), English and translation streams; scripts/relations_probe.py.</text>')
    o.append("</svg>")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(o), encoding="utf-8")
    print("wrote", out)
    return 0


# ---------------------------------------------------------------- GKG sample (press tone, layer 3)

GKG_DOMAIN, GKG_THEMES, GKG_LOC2, GKG_TONE, GKG_TRANS = 3, 7, 10, 15, 25


def _gkg_file(stamp: str, stream: str, outlets: Outlets, subjects: set[str]) -> dict:
    """One GKG file -> per (outlet FIPS > location FIPS): [articles naming the place, their tone sum,
    articles where it is the most-mentioned country, their tone sum], plus theme counts for `subjects`
    when they are the most-mentioned country. Streams the file; nothing is stored."""
    import io
    import zipfile
    from pipeline import gdelt
    data = None
    for attempt in range(4):
        try:
            data = gdelt.download(stamp, stream)
            break
        except Exception:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(2 + attempt * 4)
    out = {"pairs": {}, "themes": {}, "articles": 0, "unknown_outlet": 0, "bytes": len(data or b"")}
    if data is None:
        return out
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            with zf.open(name) as raw:
                for line in raw:
                    f = line.rstrip(b"\r\n").split(b"\t")
                    if len(f) < gdelt.GKG_FIELDS:
                        continue
                    try:
                        tone = float(f[GKG_TONE].split(b",", 1)[0])
                    except ValueError:
                        continue
                    counts: dict[str, int] = {}
                    for loc in f[GKG_LOC2].split(b";"):
                        p = loc.split(b"#")
                        if len(p) > 2 and p[2]:
                            cc = p[2].decode("ascii", "replace")
                            counts[cc] = counts.get(cc, 0) + 1
                    if not counts:
                        continue
                    out["articles"] += 1
                    oc = outlets.country("http://" + f[GKG_DOMAIN].decode("utf-8", "replace") + "/")
                    if oc == "?":
                        out["unknown_outlet"] += 1
                    top = max(counts.values())
                    mains = [cc for cc, n in counts.items() if n == top]
                    main = mains[0] if len(mains) == 1 else None
                    for cc in counts:
                        v = out["pairs"].setdefault(f"{oc}>{cc}", [0, 0.0, 0, 0.0])
                        v[0] += 1
                        v[1] += tone
                        if cc == main:
                            v[2] += 1
                            v[3] += tone
                    if main in subjects:
                        th = out["themes"].setdefault(main, {})
                        for t in set(f[GKG_THEMES].decode("utf-8", "replace").split(";")):
                            if t:
                                th[t] = th.get(t, 0) + 1
    return out


def gkg_sample(a) -> int:
    root = Path(a.root)
    (root / "gkg").mkdir(parents=True, exist_ok=True)
    outlets = load_outlets(a)
    subjects = set(a.subjects.split(","))
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    d = start
    with ThreadPoolExecutor(a.workers) as ex:
        while d <= end:
            out = root / "gkg" / f"{d}.json.gz"
            if out.exists():
                d += timedelta(days=1)
                continue
            t0 = time.time()
            stamps = [f"{d:%Y%m%d}{h:02d}{a.minute:02d}00" for h in range(0, 24, a.every_hours)]
            day = {"day": d.isoformat(), "slots": stamps, "pairs": {}, "themes": {}, "articles": 0,
                   "unknown_outlet": 0, "bytes": 0, "files": 0, "failed": 0,
                   "pair_vec": ["n_any", "tone_any", "n_main", "tone_main"]}
            futs = [ex.submit(_gkg_file, s, st, outlets, subjects) for s in stamps for st in STREAMS]
            for fut in futs:
                try:
                    r = fut.result()
                except Exception as e:  # noqa: BLE001
                    day["failed"] += 1
                    print(f"  failed: {str(e)[:100]}", flush=True)
                    continue
                day["files"] += 1 if r["bytes"] else 0
                for k in ("articles", "unknown_outlet", "bytes"):
                    day[k] += r[k]
                for k, v in r["pairs"].items():
                    t = day["pairs"].setdefault(k, [0, 0.0, 0, 0.0])
                    for i in range(4):
                        t[i] += v[i]
                for cc, th in r["themes"].items():
                    t = day["themes"].setdefault(cc, {})
                    for k, n in th.items():
                        t[k] = t.get(k, 0) + n
            day["pairs"] = {k: [v[0], round(v[1], 1), v[2], round(v[3], 1)] for k, v in day["pairs"].items()}
            day["themes"] = {cc: dict(sorted(th.items(), key=lambda kv: -kv[1])[:300])
                             for cc, th in day["themes"].items()}
            tmp = out.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                json.dump(day, fh, separators=(",", ":"))
            tmp.replace(out)
            print(f"{d}: {day['files']} files, {day['bytes'] / 1e6:.0f} MB, {day['articles']} articles, "
                  f"{day['unknown_outlet']} unknown outlet, {len(day['pairs'])} pairs, {time.time() - t0:.0f} s",
                  flush=True)
            d += timedelta(days=1)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--root", required=True)
    p.add_argument("--focus", default="PRK")
    p.add_argument("--workers", type=int, default=8)
    p = sub.add_parser("series")
    p.add_argument("--root", required=True)
    p.add_argument("--focus", default="PRK")
    p.add_argument("--partners", default="KOR,USA,JPN,CHN,RUS")
    p = sub.add_parser("gkg-sample", help="press tone by outlet country from a sample of GKG files (~10 MB each)")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--root", required=True)
    p.add_argument("--every-hours", type=int, default=1, help="read one 15-minute file every N hours")
    p.add_argument("--minute", type=int, default=0, choices=(0, 15, 30, 45))
    p.add_argument("--subjects", default="KN,KS", help="FIPS codes whose GKG themes are counted")
    p.add_argument("--workers", type=int, default=6)
    p = sub.add_parser("spikes", help="unusual days in the series, with the articles behind each")
    p.add_argument("--root", required=True)
    p.add_argument("--top", type=int, default=4)
    p.add_argument("--print-chars", type=int, default=6000)
    p = sub.add_parser("score", help="hits and misses against a reference event list")
    p.add_argument("--root", required=True)
    p.add_argument("--events", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--partners", default="KOR,USA,JPN,CHN,RUS")
    p.add_argument("--z", type=float, default=2.0)
    p.add_argument("--slack", type=int, default=1)
    p.add_argument("--min-count", type=int, default=0, help="the flagged count must be at least this")
    p = sub.add_parser("chart", help="static SVG small multiples of the focus series")
    p.add_argument("--root", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--partners", default="KOR,USA,JPN,CHN,RUS")
    p.add_argument("--events", default="", help="JSON with an events list (day, kind, partners, what)")
    p.add_argument("--out", required=True)
    for name in ("fetch", "gkg-sample"):
        sub.choices[name].add_argument("--domains", default="data/relations/ref/domains_by_country_2018.txt")
    a = ap.parse_args()
    return {"fetch": fetch, "series": series, "spikes": spikes, "score": score, "chart": chart,
            "gkg-sample": gkg_sample}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
