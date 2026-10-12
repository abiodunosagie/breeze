"""Electricity used by the air conditioner: today, this month, and the last 24 hours by hour.

The AC keeps a running total in kWh and reports its power draw. On the owner's unit the BCD
encoding is the right one: its total rose 0.2 kWh in 50 minutes at about 225 W, which matches,
while the binary encoding claimed about 720 W. Day totals are worked out from the running
total, so a reading missed while the Mac sleeps costs nothing. Kept privately, like the key.
"""

from __future__ import annotations

import json
import math
import re
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
        # date: [running total at the day's first reading, at its latest, kWh carried over a reset]
        self._days: dict[str, list[float]] = data["days"]
        # hour start (unix seconds), the same three numbers
        self._hours: dict[str, list[float]] = data["hours"]
        self._low_once: float | None = None  # a lower total, waiting for a second one to confirm a reset

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}

        def spans(value: Any, key_shape: re.Pattern[str]) -> dict[str, list[float]]:
            if not isinstance(value, dict):
                return {}
            good = {}
            for k, v in value.items():
                if (isinstance(k, str) and key_shape.fullmatch(k) and isinstance(v, list) and len(v) in (2, 3)
                        and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v)):
                    good[k] = [float(v[0]), float(v[1]), float(v[2]) if len(v) == 3 else 0.0]
            return good

        data = data if isinstance(data, dict) else {}
        return {"days": spans(data.get("days"), re.compile(r"\d{4}-\d{2}-\d{2}")),
                "hours": spans(data.get("hours"), re.compile(r"\d{9,11}"))}

    def record(self, total_kwh: float | None, power_w: float | None) -> None:
        """One reading from the AC. A total that went down (the unit was reset) starts afresh."""
        self.power_w = power_w if power_w is not None and math.isfinite(power_w) and power_w >= 0 else None
        if total_kwh is None or not math.isfinite(total_kwh) or total_kwh < 0:
            return
        now = self._clock()
        day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        hour = str(int(now // 3600 * 3600))
        latest = self._latest_total()
        if latest is not None and total_kwh < latest:
            # One low reading may be a glitch; a second in a row means the unit's counter restarted.
            if self._low_once is None:
                self._low_once = total_kwh
                return
            self._restart_counter(total_kwh)
        self._low_once = None
        for table, key in ((self._days, day), (self._hours, hour)):
            span = table.get(key)
            if span is None:
                # A new day or hour starts where the last one ended, so nothing used between readings is lost.
                start = self._previous_end(table, key)
                table[key] = [start if start is not None and start <= total_kwh else total_kwh, total_kwh, 0.0]
            else:
                span[1] = total_kwh
        self._trim(now)
        if now - self._saved_at >= SAVE_EVERY_SECONDS:
            self.save()

    def _latest_total(self) -> float | None:
        return self._days[max(self._days)][1] if self._days else None

    def _restart_counter(self, total_kwh: float) -> None:
        """Keep what each day and hour already used, and count on from the new total."""
        for table in (self._days, self._hours):
            for span in table.values():
                if span[1] > total_kwh:
                    span[2] += span[1] - span[0]
                    span[0] = span[1] = total_kwh

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
        first_hour = int((now // 3600 - HOURS + 1) * 3600)
        by_hour = []
        for h in range(HOURS):
            span = self._hours.get(str(first_hour + h * 3600))
            by_hour.append(round(_used(span), 3) if span else 0.0)
        return {
            "power_w": round(self.power_w) if self.power_w is not None else None,
            "today_kwh": round(_used(self._days[today]), 2) if today in self._days else 0.0,
            "month_kwh": round(sum(_used(span) for day, span in self._days.items() if day.startswith(month)), 2),
            "hourly_kwh": by_hour,
        }


def _used(span: list[float]) -> float:
    """kWh used in a day or hour: since its first reading, plus anything carried over a counter reset."""
    return max(span[1] - span[0], 0.0) + span[2]
