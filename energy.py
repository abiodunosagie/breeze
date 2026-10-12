"""Electricity used by the air conditioner: today, this month, and the last 24 hours by hour.

The AC keeps a running total in kWh and reports its power draw. On the owner's unit the BCD
encoding is the right one: its total rose 0.2 kWh in 50 minutes at about 225 W, which matches,
while the binary encoding claimed about 720 W. Day totals are worked out from the running
total, so a reading missed while the Mac sleeps costs nothing. Kept privately, like the key.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

HOURS = 24
DAYS_KEPT = 62
SAVE_EVERY_SECONDS = 300


class EnergyLog:
    def __init__(self, path: Path, write: Callable[[Path, Any], None], clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._write = write
        self._clock = clock
        self._saved_at = 0.0
        self.power_w: float | None = None
        data = self._load()
        # date: [running total at the day's first reading, at its latest reading]
        self._days: dict[str, list[float]] = data["days"]
        # hour start (unix seconds): [running total at the hour's first reading, at its latest]
        self._hours: dict[str, list[float]] = data["hours"]

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}

        def pairs(value: Any) -> dict[str, list[float]]:
            if not isinstance(value, dict):
                return {}
            return {k: [float(v[0]), float(v[1])] for k, v in value.items()
                    if isinstance(k, str) and isinstance(v, list) and len(v) == 2
                    and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)}

        return {"days": pairs(data.get("days") if isinstance(data, dict) else None),
                "hours": pairs(data.get("hours") if isinstance(data, dict) else None)}

    def record(self, total_kwh: float | None, power_w: float | None) -> None:
        """One reading from the AC. A total that went down (the unit was reset) starts afresh."""
        self.power_w = power_w if power_w is not None and power_w >= 0 else None
        if total_kwh is None or total_kwh < 0:
            return
        now = self._clock()
        day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        hour = str(int(now // 3600 * 3600))
        for table, key in ((self._days, day), (self._hours, hour)):
            span = table.get(key)
            if span is None or total_kwh < span[1]:
                # A new day or hour starts where the last one ended, so nothing used between readings is lost.
                start = self._previous_end(table, key)
                table[key] = [start if start is not None and start <= total_kwh else total_kwh, total_kwh]
            else:
                span[1] = total_kwh
        self._trim(now)
        if now - self._saved_at >= SAVE_EVERY_SECONDS:
            self.save()

    @staticmethod
    def _previous_end(table: dict[str, list[float]], key: str) -> float | None:
        earlier = [k for k in table if k < key]
        return table[max(earlier)][1] if earlier else None

    def _trim(self, now: float) -> None:
        first_hour = (now // 3600 - HOURS + 1) * 3600
        for key in [k for k in self._hours if float(k) < first_hour]:
            del self._hours[key]
        for key in sorted(self._days)[:-DAYS_KEPT]:
            del self._days[key]

    def save(self) -> None:
        self._saved_at = self._clock()
        try:
            self._write(self._path, {"days": self._days, "hours": self._hours})
        except OSError:
            pass  # the next save tries again; the AC keeps its own running total meanwhile

    def summary(self) -> dict[str, Any]:
        now = self._clock()
        today = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        month = today[:7]
        used = lambda span: max(span[1] - span[0], 0.0)  # noqa: E731
        first_hour = int((now // 3600 - HOURS + 1) * 3600)
        by_hour = [round(used(self._hours[str(first_hour + h * 3600)]), 3) if str(first_hour + h * 3600) in self._hours
                   else 0.0 for h in range(HOURS)]
        return {
            "power_w": round(self.power_w) if self.power_w is not None else None,
            "today_kwh": round(used(self._days[today]), 2) if today in self._days else 0.0,
            "month_kwh": round(sum(used(span) for day, span in self._days.items() if day.startswith(month)), 2),
            "hourly_kwh": by_hour,
        }
