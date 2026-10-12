"""Breeze's sleep curve: the setting rises a degree after the first hour and another after the
second, as the body cools in sleep, then holds until morning. At the end it goes back to where it
started, or switches off, as the user chose.

It runs by the wall clock, so it survives a sleeping Mac or a restart of Breeze. It never runs
beside the unit's own Sleep mode, which does its own rising.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

LENGTHS = (360, 420, 480, 540)  # minutes
ENDS = ("restore", "off")
# (minutes after the start, degrees above the starting setting)
STEPS = ((60, 1.0), (120, 2.0))
# Seen ending later than this (the Mac slept through the morning), the end is skipped: switching
# the AC off hours late, with someone sitting under it, would be worse than doing nothing.
LATE_END_SECONDS = 15 * 60


class SleepCurve:
    def __init__(self, path: Path, write: Callable[[Path, Any], None], clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._write = write
        self._clock = clock
        self.state: dict[str, Any] | None = self._load()

    def _load(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self._path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        started, start, minutes, end = (data.get(k) for k in ("started_at", "start_target", "minutes", "end"))
        numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (started, start))
        if not numbers or minutes not in LENGTHS or end not in ENDS:
            return None
        state = {"started_at": float(started), "start_target": float(start), "minutes": minutes, "end": end}
        # Ended while Breeze was not running: nothing to finish now.
        return None if self._clock() >= state["started_at"] + minutes * 60 else state

    def _save(self) -> None:
        try:
            self._write(self._path, self.state or {})
        except OSError:
            pass

    @property
    def active(self) -> bool:
        return self.state is not None

    def start(self, start_target: float, minutes: int, end: str) -> None:
        assert minutes in LENGTHS and end in ENDS
        self.state = {"started_at": self._clock(), "start_target": float(start_target), "minutes": minutes, "end": end}
        self._save()

    def stop(self) -> None:
        self.state = None
        self._save()

    def _elapsed_minutes(self) -> float:
        assert self.state is not None
        return (self._clock() - self.state["started_at"]) / 60

    def finished(self) -> bool:
        return self.state is not None and self._elapsed_minutes() >= self.state["minutes"]

    def ended_unseen(self) -> bool:
        """Finished long enough ago that its end should not be acted on now."""
        assert self.state is not None
        return (self._elapsed_minutes() - self.state["minutes"]) * 60 > LATE_END_SECONDS

    def offset(self) -> float:
        elapsed = self._elapsed_minutes()
        return max((degrees for after, degrees in STEPS if elapsed >= after), default=0.0)

    def wanted(self, highest: float) -> float:
        assert self.state is not None
        return min(self.state["start_target"] + self.offset(), highest)

    def summary(self) -> dict[str, Any] | None:
        if self.state is None:
            return None
        ends = datetime.fromtimestamp(self.state["started_at"] + self.state["minutes"] * 60)
        left = max(0, round(self.state["minutes"] - self._elapsed_minutes()))
        return {"offset": self.offset(), "ends_at": ends.strftime("%H:%M"), "minutes_left": left,
                "end": self.state["end"]}
