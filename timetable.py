"""Schedules: switch the air conditioner on or off at set times on chosen days.

Times are the Mac's local wall clock, so a Mac that slept still knows what time it is. A
schedule runs while Breeze is running and the AC can be reached, up to GRACE_SECONDS late; a
time missed by more than that is skipped and the user told once. What each schedule may do is
checked here for shape only. Whether this unit has that mode or speed is checked when it
runs, by ACSession.change, because the AC may be away when the user saves.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from store import read_json_dict

GRACE_SECONDS = 15 * 60
# Missed by more than this, the time is skipped quietly: old news is no use to anyone.
TELL_MISSED_WITHIN_SECONDS = 12 * 3600
MAX_SCHEDULES = 16
# Shape only; the unit's own range is checked when the schedule runs.
MIN_TARGET, MAX_TARGET = 10, 35
ID_SHAPE = re.compile(r"[a-z0-9-]{1,32}")
TIME_SHAPE = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
NAME_SHAPE = re.compile(r"[a-z]{1,10}")


class ScheduleError(ValueError):
    """A schedule that cannot be saved, worded for the user."""


def check_entry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ScheduleError("A schedule is not in the right shape.")
    entry_id, days, at = raw.get("id"), raw.get("days"), raw.get("time")
    if not isinstance(entry_id, str) or not ID_SHAPE.fullmatch(entry_id):
        raise ScheduleError("A schedule is not in the right shape.")
    if (not isinstance(days, list) or not days or len(set(days)) != len(days)
            or not all(type(d) is int and 0 <= d <= 6 for d in days)):
        raise ScheduleError("Choose at least one day.")
    if not isinstance(at, str) or not TIME_SHAPE.fullmatch(at):
        raise ScheduleError("Choose a time like 06:30.")
    power, enabled = raw.get("power"), raw.get("enabled", True)
    if not isinstance(power, bool) or not isinstance(enabled, bool):
        raise ScheduleError("A schedule is not in the right shape.")
    entry: dict[str, Any] = {"id": entry_id, "enabled": enabled, "days": sorted(days), "time": at, "power": power,
                             "target": None, "mode": None, "fan": None}
    if power:
        target = raw.get("target")
        if target is not None:
            if not isinstance(target, (int, float)) or isinstance(target, bool) or not MIN_TARGET <= target <= MAX_TARGET:
                raise ScheduleError("Choose a temperature the AC can be set to.")
            entry["target"] = float(target)
        for name in ("mode", "fan"):
            value = raw.get(name)
            if value is not None:
                if not isinstance(value, str) or not NAME_SHAPE.fullmatch(value):
                    raise ScheduleError("A schedule is not in the right shape.")
                entry[name] = value
    return entry


def check_entries(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > MAX_SCHEDULES:
        raise ScheduleError(f"Up to {MAX_SCHEDULES} schedules.")
    entries = [check_entry(item) for item in raw]
    if len({e["id"] for e in entries}) != len(entries):
        raise ScheduleError("A schedule is not in the right shape.")
    return entries


def changes_for(entry: dict[str, Any]) -> dict[str, Any]:
    """What the schedule asks of the AC, in ACSession.change's terms."""
    if not entry["power"]:
        return {"power": False}
    return {"power": True, **{k: entry[k] for k in ("target", "mode", "fan") if entry[k] is not None}}


def last_time(entry: dict[str, Any], now: datetime) -> datetime:
    """The schedule's most recent time at or before now, on one of its days."""
    hour, minute = (int(part) for part in entry["time"].split(":"))
    for back in range(8):
        day = (now - timedelta(days=back)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day <= now and day.weekday() in entry["days"]:
            return day
    raise AssertionError("every schedule has a day in each week")


class Timetable:
    def __init__(self, path: Path, write: Callable[[Path, Any], None], clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._write = write
        self._clock = clock
        self.entries: list[dict[str, Any]] = []
        self._done: dict[str, str] = {}  # id: the last time run or skipped, as an ISO minute
        self._load()

    def _load(self) -> None:
        data = read_json_dict(self._path)
        try:
            self.entries = check_entries(data.get("entries", []))
        except ScheduleError:
            return
        done = data.get("done")
        ids = {e["id"] for e in self.entries}
        if isinstance(done, dict):
            self._done = {k: v for k, v in done.items() if k in ids and isinstance(v, str)}

    def _save(self) -> None:
        try:
            self._write(self._path, {"entries": self.entries, "done": self._done})
        except OSError:
            pass  # kept in memory; the next save tries again

    def replace(self, raw: Any) -> None:
        """A new list from the app. Times already past count as done, so saving never fires one."""
        entries = check_entries(raw)
        now = datetime.fromtimestamp(self._clock())
        old = {e["id"]: e for e in self.entries}
        done = {}
        for entry in entries:
            same = old.get(entry["id"]) == entry and entry["id"] in self._done
            done[entry["id"]] = self._done[entry["id"]] if same else last_time(entry, now).isoformat(timespec="minutes")
        self.entries, self._done = entries, done
        self._save()

    def due(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Schedules to run now, and ones missed (more than GRACE_SECONDS late) worth telling about."""
        now = datetime.fromtimestamp(self._clock())
        run, missed = [], []
        for entry in self.entries:
            if not entry["enabled"]:
                continue
            at = last_time(entry, now)
            key = at.isoformat(timespec="minutes")
            if self._done.get(entry["id"]) == key:
                continue
            self._done[entry["id"]] = key
            late = (now - at).total_seconds()
            if late <= GRACE_SECONDS:
                run.append(entry)
            elif late <= TELL_MISSED_WITHIN_SECONDS:
                missed.append(entry)
        if run or missed:
            self._save()
        return run, missed
