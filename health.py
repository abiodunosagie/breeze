"""How well the air conditioner cools, week by week: the gap between the room and the coil.

While the compressor works hard in cool mode, a healthy unit keeps its indoor coil well below the
room. A gap that shrinks over weeks means less cooling for the same work, most often a dirty filter
or coil. Breeze learns the usual gap over the first full days, keeps it, and says so once if the
last week falls well short. Readings only; nothing here changes the AC.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from store import SAVE_EVERY_SECONDS, is_number, read_json_dict

DAYS_KEPT = 90
# A day counts once it has this many hard cooling readings (one each poll, see POLL_SECONDS in ac.py).
SAMPLES_FOR_A_DAY = 30
BASELINE_DAYS = 7
RECENT_DAYS = 7
# Below this share of the usual gap, tell the user; above RECOVERED_SHARE, the worry is over.
DROP_SHARE = 0.7
RECOVERED_SHARE = 0.85
# Right after switching on, the coil is still cooling down: those readings say nothing yet.
SETTLE_SECONDS = 5 * 60
# Readings further apart than this missed what happened between (an off and on, unseen).
MAX_GAP_SECONDS = 120.0
DAY_SHAPE = re.compile(r"\d{4}-\d{2}-\d{2}")


class Health:
    def __init__(self, path: Path, write: Callable[[Path, Any], None], clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._write = write
        self._clock = clock
        self._saved_at = 0.0
        self._on_since: float | None = None
        self._last_tick: float | None = None
        data = read_json_dict(path)
        raw = data.get("days") if isinstance(data.get("days"), dict) else {}
        self._days: dict[str, list[float]] = {  # date: [count, mean gap]
            k: [float(v[0]), float(v[1])] for k, v in raw.items()
            if isinstance(k, str) and DAY_SHAPE.fullmatch(k) and isinstance(v, list) and len(v) == 2
            and all(is_number(x) for x in v) and v[0] >= 1}
        # The usual gap, fixed once learnt, and the last day it was learnt from.
        baseline, until = data.get("baseline"), data.get("baseline_until")
        good = is_number(baseline) and baseline > 0 and isinstance(until, str) and DAY_SHAPE.fullmatch(until)
        self.baseline: float | None = float(baseline) if good else None
        self._baseline_until: str | None = until if good else None
        self.told: bool = data.get("told") is True

    def save(self) -> None:
        self._saved_at = self._clock()
        try:
            self._write(self._path, {"days": self._days, "baseline": self.baseline,
                                     "baseline_until": self._baseline_until, "told": self.told})
        except OSError:
            pass

    def record(self, power: bool, hard_cooling: bool, room: float | None, coil: float | None) -> str | None:
        """One reading. Returns "low" the first time the gap falls well short of the usual one."""
        now = self._clock()
        unseen = self._last_tick is None or now - self._last_tick > MAX_GAP_SECONDS
        self._last_tick = now
        if not power:
            self._on_since = None
            return None
        if self._on_since is None or unseen:
            self._on_since = now  # it may have been off meanwhile: settle again
        settled = now - self._on_since >= SETTLE_SECONDS
        if hard_cooling and settled and is_number(room) and is_number(coil):
            day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
            count, mean = self._days.get(day, [0.0, 0.0])
            count += 1
            self._days[day] = [count, mean + (room - coil - mean) / count]
            for old in sorted(self._days)[:-DAYS_KEPT]:
                del self._days[old]
        news = self._judge()
        if news or now - self._saved_at >= SAVE_EVERY_SECONDS:
            self.save()
        return news

    def _full_days(self, after: str | None = None) -> list[float]:
        return [mean for day, (count, mean) in sorted(self._days.items())
                if count >= SAMPLES_FOR_A_DAY and (after is None or day > after)]

    def _learn(self) -> None:
        full = [(day, mean) for day, (count, mean) in sorted(self._days.items()) if count >= SAMPLES_FOR_A_DAY]
        if self.baseline is None and len(full) >= BASELINE_DAYS:
            first = full[:BASELINE_DAYS]
            self.baseline = sum(mean for _, mean in first) / BASELINE_DAYS
            self._baseline_until = first[-1][0]

    def _recent(self) -> float | None:
        """The last week's gap, from full days after the ones the usual gap was learnt from."""
        if self._baseline_until is None:
            return None
        recent = self._full_days(after=self._baseline_until)[-RECENT_DAYS:]
        return sum(recent) / len(recent) if recent else None

    def _judge(self) -> str | None:
        self._learn()
        recent = self._recent()
        if self.baseline is None or recent is None:
            return None
        if not self.told and recent < self.baseline * DROP_SHARE:
            self.told = True
            return "low"
        if self.told and recent > self.baseline * RECOVERED_SHARE:
            self.told = False
        return None

    def summary(self) -> dict[str, Any]:
        today = self._days.get(datetime.fromtimestamp(self._clock()).strftime("%Y-%m-%d"))
        recent = self._recent()
        state = "learning" if self.baseline is None else "low" if self.told else "good"
        return {"gap": round(today[1], 1) if today else None,
                "recent": round(recent, 1) if recent is not None else None,
                "usual": round(self.baseline, 1) if self.baseline is not None else None, "state": state,
                "message": self.message_for_low() if state == "low" else None}

    def message_for_low(self) -> str:
        recent = self._recent()
        return (f"The coil is not getting as cold as it did: about {recent or 0:.0f}° below the room, it was "
                f"{self.baseline or 0:.0f}°. Check the filter first.")
