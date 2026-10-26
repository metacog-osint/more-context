"""Monthly AI spend ledger: every Vertex call is reserved against it first and settled afterwards.

Tom's limits (26 Oct 2026): a hard cap of $5 per calendar month (UTC), across everything MORE CONTEXT
asks of Gemini. Anyone may trigger on-view coding while the cap allows; alarm-triggered coding stays on.

- `view` work (a person opened a zone or story) may use the cap minus ALARM_RESERVE, and at most
  VIEW_DAILY_USD per UTC day, so one busy visitor cannot spend the month in an afternoon and alarms
  always have money left.
- `alarm` work (a free measure crossed its threshold) may use the whole cap.
- A call reserves its estimated cost (with a safety margin) before it is sent and settles to the cost
  computed from Vertex's own token counts afterwards. A reservation left unsettled for 15 minutes (a crash
  mid-call) is counted as spent at its estimate.

The ledger lives at `state/ai_spend.json` and is updated with compare-and-swap (Cloud Storage generation
match), so the ingest job and the public API cannot overwrite each other's entries.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

LEDGER_KEY = "state/ai_spend.json"
MONTHLY_CAP_USD = float(os.environ.get("MC_AI_MONTHLY_CAP_USD", "5"))
ALARM_RESERVE_USD = 1.00
VIEW_DAILY_USD = 0.50
STALE_AFTER = timedelta(minutes=15)
_RETRIES = 8


class BudgetExceeded(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class Ledger:
    def __init__(self, sink, cap_usd: float = MONTHLY_CAP_USD, alarm_reserve: float = ALARM_RESERVE_USD,
                 view_daily: float = VIEW_DAILY_USD, now=_now):
        self.sink, self.cap, self.alarm_reserve, self.view_daily, self.now = sink, cap_usd, alarm_reserve, view_daily, now

    # --- reading -------------------------------------------------------------------------------
    def _blank(self) -> dict:
        return {"cap_usd": self.cap, "months": {}, "days": {}, "reservations": {}}

    def _expire(self, led: dict, now: datetime) -> None:
        """Reservations older than STALE_AFTER count as spent at their estimate."""
        for rid, r in list(led["reservations"].items()):
            if now - datetime.fromisoformat(r["at"].replace("Z", "+00:00")) > STALE_AFTER:
                self._add_spend(led, r["month"], r["day"], r["source"], r["usd"], expired=True)
                del led["reservations"][rid]

    @staticmethod
    def _add_spend(led: dict, month: str, day: str, source: str, usd: float, expired: bool = False) -> None:
        m = led["months"].setdefault(month, {"spent": 0.0, "calls": 0, "by_source": {}, "expired": 0})
        m["spent"] = round(m["spent"] + usd, 6)
        m["calls"] += 1
        m["by_source"][source] = round(m["by_source"].get(source, 0.0) + usd, 6)
        if expired:
            m["expired"] += 1
        d = led["days"].setdefault(day, {"spent": 0.0, "view": 0.0})
        d["spent"] = round(d["spent"] + usd, 6)
        if source == "view":
            d["view"] = round(d["view"] + usd, 6)

    def status(self) -> dict:
        led, _ = self.sink.read_json_versioned(LEDGER_KEY)
        led = led or self._blank()
        now = self.now()
        month, day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
        held = sum(r["usd"] for r in led["reservations"].values() if r["month"] == month)
        m = led["months"].get(month, {"spent": 0.0})
        d = led["days"].get(day, {"spent": 0.0, "view": 0.0})
        return {"month": month, "cap_usd": self.cap, "spent_usd": round(m["spent"], 4), "held_usd": round(held, 4),
                "left_usd": round(max(self.cap - m["spent"] - held, 0.0), 4),
                "view_left_today_usd": round(max(min(self.view_daily - d["view"],
                                                     self.cap - self.alarm_reserve - m["spent"] - held), 0.0), 4)}

    # --- reserve / settle ----------------------------------------------------------------------
    def _limit_ok(self, led: dict, month: str, day: str, source: str, usd: float) -> bool:
        spent = led["months"].get(month, {}).get("spent", 0.0)
        held = sum(r["usd"] for r in led["reservations"].values() if r["month"] == month)
        if source == "alarm":
            return spent + held + usd <= self.cap
        day_view = led["days"].get(day, {}).get("view", 0.0)
        day_held = sum(r["usd"] for r in led["reservations"].values() if r["day"] == day and r["source"] == "view")
        return (spent + held + usd <= self.cap - self.alarm_reserve
                and day_view + day_held + usd <= self.view_daily)

    def _update(self, change) -> object:
        for _ in range(_RETRIES):
            led, version = self.sink.read_json_versioned(LEDGER_KEY)
            led = led or self._blank()
            led["cap_usd"] = self.cap
            now = self.now()
            self._expire(led, now)
            result = change(led, now)
            if self.sink.write_json_if(LEDGER_KEY, led, version):
                return result
        raise RuntimeError("AI spend ledger busy; try again")

    def reserve(self, usd: float, source: str) -> str:
        """Hold `usd` for one call. Raises BudgetExceeded when the cap (or the view limits) would be passed."""
        if source not in ("view", "alarm"):
            raise ValueError(source)
        rid = uuid.uuid4().hex[:12]

        def change(led, now):
            month, day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
            if not self._limit_ok(led, month, day, source, usd):
                return False
            led["reservations"][rid] = {"usd": round(usd, 6), "source": source, "month": month, "day": day, "at": _iso(now)}
            return True

        if not self._update(change):
            raise BudgetExceeded(f"AI budget: ${usd:.4f} for {source} would pass the limit")
        return rid

    def settle(self, rid: str, actual_usd: float) -> None:
        """Replace a reservation with the actual cost (0 when the call failed before Vertex charged)."""
        def change(led, now):
            r = led["reservations"].pop(rid, None)
            if r is not None:
                self._add_spend(led, r["month"], r["day"], r["source"], actual_usd)
            return True

        self._update(change)
