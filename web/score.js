// How scores and sample headlines read on the page: plain functions with no DOM, so tests/test_web_score.py can run
// them in Node. app.js builds the elements and inserts every string as text.
//
// A score (pipeline/measures.scored, pipeline/countries.score) carries a z against `expected`, the count the last
// 28 days predict, and `ratio_shown` = count / max(expected, median90 when stored, 3) (pipeline/zstats.floored_ratio),
// with `floored` when the 3 binds. The ratio and the z can therefore rest on different baselines: these functions
// say which, and show no z where the count is too small to judge.

export const FLOOR = 3; // pipeline/zstats.RATIO_FLOOR
export const MIN_JUDGED = 5; // pipeline/measures.ALARM_MIN_STORIES: no alarm, and here no z, on fewer

const known = (x) => x !== null && x !== undefined;
const num = (x) => (typeof x === "number" ? x.toLocaleString("en-US") : String(x));

// What ratio_shown divides by: "floor" (3 a day), "median" (the 90-day median) or "expected" (the z's own baseline).
export function ratioBase(s) {
  if (s.floored) return "floor";
  return known(s.median90) && known(s.expected) && s.median90 > s.expected ? "median" : "expected";
}

// A count too small to judge: usually 3 or fewer a day, and under MIN_JUDGED on the day. No ratio or z is shown.
export function tooFew(s, count) {
  return Boolean(s && s.floored) && (!known(count) || count < MIN_JUDGED);
}

// The ratio as shown in a badge: "1.26×", "1.49× 90-day median", "8 (usually ≤3)" or, without a count, "usually ≤3".
export function ratioText(s, count) {
  const base = ratioBase(s);
  if (base === "floor") return known(count) ? `${num(count)} (usually ≤${FLOOR})` : `usually ≤${FLOOR}`;
  const r = s.ratio_shown ?? s.ratio;
  if (!known(r)) return "?";
  return base === "median" ? `${r}× 90-day median` : `${r}×`;
}

// The tooltip sentence that names the baseline of the ratio and of the z. `unit` names the count ("stories").
export function baselineNote(s, count, units = "stories") {
  const unit = count === 1 ? units.replace(/ies$/, "y").replace(/s$/, "") : units;
  const days = `the last ${s.baseline_days || 28} days`;
  if (tooFew(s, count)) {
    return `${known(count) ? `${num(count)} ${unit}; ` : ""}usually ${FLOOR} or fewer a day: too few to judge against its own normal, so no ratio or z is shown`;
  }
  const z = `z ${s.z} against ${days} (expected ${s.expected})`;
  const base = ratioBase(s);
  if (base === "floor") return `${known(count) ? `${num(count)} ${unit}` : "The count"} against usually ${FLOOR} or fewer a day, so no ratio is shown; ${z}`;
  const r = s.ratio_shown ?? s.ratio;
  if (!known(r)) return `No ratio: nothing was expected; ${z}`;
  if (base === "median") return `${r}× the median of the last 90 days (${s.median90}), which is above the expected ${s.expected}; ${z}`;
  return `${r}× the expected ${s.expected}; ${z}: the ratio and the z use the same baseline`;
}

// Sample headlines that can be shown: a link with a title read from it. A link with no readable title is left out,
// never shown as its site's name.
export function readableHeads(samples, n = 2) {
  return (samples || []).filter((x) => x && typeof x.title === "string" && x.title.trim() && /^https?:\/\//.test(x.url || "")).slice(0, n);
}
