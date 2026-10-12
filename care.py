"""Looking after the air conditioner: run hours since its last self clean and filter clean.

Hours count only while the unit cools or dries (the coil is wet then), from the gaps between
readings. A gap longer than MAX_GAP_SECONDS counts as MAX_GAP_SECONDS, so a Mac that slept
for the night never credits the AC with hours nobody saw. Kept privately, like the key.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# A self clean after this many wet hours, when the user turned automatic cleaning on.
CLEAN_AFTER_HOURS = 40.0
# Breeze's own reminder to wash the filter, in the same wet hours.
FILTER_AFTER_HOURS = 150.0
MAX_GAP_SECONDS = 120.0
SAVE_EVERY_SECONDS = 300.0
# A clean shorter than this was stopped early and does not count as done.
CLEAN_COUNTS_AFTER_MINUTES = 10
# Automatic cleans start only in the day, so the fan never wakes anyone, and only once the AC
# has been off a while (the user is not about to switch it back on).
CLEAN_FROM_HOUR = 8
CLEAN_UNTIL_HOUR = 22
OFF_FOR_SECONDS = 10 * 60
# After asking for a clean that never began, wait this long before asking again.
RETRY_AFTER_SECONDS = 30 * 60


class Care:
    def __init__(self, path: Path, write: Callable[[Path, Any], None], clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._write = write
        self._clock = clock
        self._saved_at = 0.0
        self._last_tick: float | None = None
        data = self._load()
        self.clean_hours: float = data["clean_hours"]
        self.filter_hours: float = data["filter_hours"]
        self.filter_told: bool = data["filter_told"]
        self._off_since: float | None = None
        self._asked_at: float | None = None  # when Breeze last asked for a clean
        self._clean_started: float | None = None  # wall clock a clean was first seen running
        self._breeze_cleaning = False  # the running clean is one Breeze started

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
        data = data if isinstance(data, dict) else {}

        def hours(value: Any) -> float:
            ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
            return float(value) if ok else 0.0

        return {"clean_hours": hours(data.get("clean_hours")), "filter_hours": hours(data.get("filter_hours")),
                "filter_told": data.get("filter_told") is True}

    def save(self) -> None:
        self._saved_at = self._clock()
        try:
            self._write(self._path, {"clean_hours": round(self.clean_hours, 3),
                                     "filter_hours": round(self.filter_hours, 3), "filter_told": self.filter_told})
        except OSError:
            pass  # the next save tries again

    # ------------------------------------------------------------ readings

    def record(self, power: bool, wet: bool, cleaning: bool) -> str | None:
        """One fresh reading. Returns "clean_done" or "filter_due" when there is news for the user."""
        now = self._clock()
        # A clean that ended while nobody watched (a power cut, a sleeping Mac) may not have finished.
        watched = self._last_tick is not None and now - self._last_tick <= MAX_GAP_SECONDS
        if self._last_tick is not None and power and wet:
            gap = min(max(now - self._last_tick, 0.0), MAX_GAP_SECONDS) / 3600
            self.clean_hours += gap
            self.filter_hours += gap
        self._last_tick = now
        self._off_since = None if power else (self._off_since if self._off_since is not None else now)
        news = self._follow_clean(cleaning, now, watched)
        if news is None and self.filter_hours >= FILTER_AFTER_HOURS and not self.filter_told:
            self.filter_told = True
            news = "filter_due"
        if news or now - self._saved_at >= SAVE_EVERY_SECONDS:
            self.save()
        return news

    def _follow_clean(self, cleaning: bool, now: float, watched: bool) -> str | None:
        if cleaning:
            if self._clean_started is None:
                self._clean_started = now
                self._breeze_cleaning = self._asked_at is not None and now - self._asked_at < RETRY_AFTER_SECONDS
            return None
        if self._clean_started is None:
            return None
        ran = (now - self._clean_started) / 60
        self._clean_started = None
        by_breeze, self._breeze_cleaning = self._breeze_cleaning, False
        if ran < CLEAN_COUNTS_AFTER_MINUTES or not watched:
            return None
        self.clean_hours = 0.0  # a full clean from the hand remote counts too
        return "clean_done" if by_breeze else None

    # ------------------------------------------------------------ deciding

    def clean_due(self, auto_clean: bool) -> bool:
        """Time for Breeze to start a self clean, if everything else allows it (see ACSession)."""
        now = self._clock()
        hour = datetime.fromtimestamp(now).hour
        return (auto_clean and self.clean_hours >= CLEAN_AFTER_HOURS
                and CLEAN_FROM_HOUR <= hour < CLEAN_UNTIL_HOUR
                and self._off_since is not None and now - self._off_since >= OFF_FOR_SECONDS
                and self._clean_started is None
                and (self._asked_at is None or now - self._asked_at >= RETRY_AFTER_SECONDS))

    def asked_for_clean(self) -> None:
        self._asked_at = self._clock()

    def filter_cleaned(self) -> None:
        self.filter_hours = 0.0
        self.filter_told = False
        self.save()

    def summary(self) -> dict[str, Any]:
        return {"clean_hours": round(self.clean_hours, 1), "filter_hours": round(self.filter_hours, 1),
                "clean_after_hours": CLEAN_AFTER_HOURS, "filter_after_hours": FILTER_AFTER_HOURS,
                "filter_wash_due": self.filter_hours >= FILTER_AFTER_HOURS}
