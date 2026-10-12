"""How well the air conditioner cools, week by week: the gap between the room and the coil.

While the compressor works hard in cool mode, a healthy unit keeps its indoor coil well below the
room. A gap that shrinks over weeks means less cooling for the same work, most often a dirty filter
or coil. Breeze learns the usual gap over the first days and says so once if it falls well short.
Readings only; nothing here changes the AC.
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

DAYS_KEPT = 90
# A day counts once it has this many readings (20 s apart, about ten minutes of hard cooling).
SAMPLES_FOR_A_DAY = 30
BASELINE_DAYS = 7
RECENT_DAYS = 7
# Below this share of the usual gap, tell the user; above RECOVERED_SHARE, the worry is over.
DROP_SHARE = 0.7
RECOVERED_SHARE = 0.85
# Right after switching on, the coil is still cooling down: those readings say nothing yet.
SETTLE_SECONDS = 5 * 60
SAVE_EVERY_SECONDS = 300.0
DAY_SHAPE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class Health:
    def __init__(self, path: Path, write: Callable[[Path, Any], None], clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._write = write
        self._clock = clock
        self._saved_at = 0.0
        self._on_since: float | None = None
        data = self._load()
        self._days: dict[str, list[float]] = data["days"]  # date: [count, mean gap]
        self.told: bool = data["told"]

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
        data = data if isinstance(data, dict) else {}
        raw = data.get("days") if isinstance(data.get("days"), dict) else {}
        days = {k: [float(v[0]), float(v[1])] for k, v in raw.items()
                if isinstance(k, str) and DAY_SHAPE.fullmatch(k) and isinstance(v, list) and len(v) == 2
                and all(_number(x) for x in v) and v[0] >= 1}
        return {"days": days, "told": data.get("told") is True}

    def save(self) -> None:
        self._saved_at = self._clock()
        try:
            self._write(self._path, {"days": self._days, "told": self.told})
        except OSError:
            pass

    def record(self, power: bool, hard_cooling: bool, room: float | None, coil: float | None) -> str | None:
        """One reading. Returns "low" the first time the gap falls well short of the usual one."""
        now = self._clock()
        if not power:
            self._on_since = None
            return None
        if self._on_since is None:
            self._on_since = now
        settled = now - self._on_since >= SETTLE_SECONDS
        if hard_cooling and settled and _number(room) and _number(coil):
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

    def _full_days(self) -> list[float]:
        return [mean for _, (count, mean) in sorted(self._days.items()) if count >= SAMPLES_FOR_A_DAY]

    def _baseline_and_recent(self) -> tuple[float | None, float | None]:
        full = self._full_days()
        if len(full) < BASELINE_DAYS + 1:
            return (sum(full[:BASELINE_DAYS]) / BASELINE_DAYS if len(full) >= BASELINE_DAYS else None), None
        recent = full[BASELINE_DAYS:][-RECENT_DAYS:]
        return sum(full[:BASELINE_DAYS]) / BASELINE_DAYS, sum(recent) / len(recent)

    def _judge(self) -> str | None:
        baseline, recent = self._baseline_and_recent()
        if baseline is None or recent is None:
            return None
        if not self.told and recent < baseline * DROP_SHARE:
            self.told = True
            return "low"
        if self.told and recent > baseline * RECOVERED_SHARE:
            self.told = False
        return None

    def summary(self) -> dict[str, Any]:
        today = self._days.get(datetime.fromtimestamp(self._clock()).strftime("%Y-%m-%d"))
        baseline, recent = self._baseline_and_recent()
        state = "learning" if baseline is None else "low" if self.told else "good"
        return {"health": {"gap": round(today[1], 1) if today else None,
                           "recent": round(recent, 1) if recent is not None else None,
                           "usual": round(baseline, 1) if baseline is not None else None, "state": state}}

    def message_for_low(self) -> str:
        baseline, recent = self._baseline_and_recent()
        return (f"The coil is not getting as cold as it did: about {recent:.0f}° below the room, it was "
                f"{baseline:.0f}°. Check the filter first.")
