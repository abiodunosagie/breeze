"""The Midea air conditioner, over the home network.

Midea's V3 units encrypt their local protocol with a token and key that only Midea's cloud
hands out, and only to the account that owns the unit. `tools/ac_link.py` fetches them once
(the user types their own MSmartHome password there) and saves them to AC_FILE, readable only
by the user. From then on Breeze talks to the AC directly with msmart-ng, no cloud involved.

Every change goes through one queue: the latest value of each setting wins, so dragging the
temperature slider sends one command, not thirty. The token and key never leave this module.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Callable
from typing import Any

from msmart.device import AirConditioner
from msmart.discover import Discover

from care import Care
from energy import EnergyLog
from sleepcurve import LENGTHS as CURVE_LENGTHS
from sleepcurve import SleepCurve
from store import (AC_FILE, CARE_FILE, CONFIG_DIR, DEFAULT_SETTINGS, DRY_DONE_WITHIN, DRY_MAX_MINUTES, ENERGY_FILE,  # noqa: F401
                   OUTAGE_SECONDS, SCHEDULE_FILE, SETTINGS_FILE, SLEEP_FILE, WET_MODES, check_setting, load_settings,
                   save_link, write_private)
from timetable import ScheduleError, Timetable, changes_for

POLL_SECONDS = 20.0
# After this many silent polls in a row, look for the AC again (the router may have moved it).
REDISCOVER_AFTER = 3
# Right after a failed connection (a restart often finds the old one still open), retry soon.
QUICK_RETRY_SECONDS = 3.0
QUICK_RETRIES = 3
DISCOVER_SECONDS = 4

log = logging.getLogger("breeze.ac")
# msmart logs packets and cloud replies at debug level, keys among them.
logging.getLogger("msmart").setLevel(logging.WARNING)

Mode = AirConditioner.OperationalMode
Fan = AirConditioner.FanSpeed
Swing = AirConditioner.SwingMode

# The names the Mac app uses, in the order its pickers show them.
MODES = {"auto": Mode.AUTO, "cool": Mode.COOL, "dry": Mode.DRY, "heat": Mode.HEAT, "fan": Mode.FAN_ONLY}
FANS = {"auto": Fan.AUTO, "silent": Fan.SILENT, "low": Fan.LOW, "medium": Fan.MEDIUM, "high": Fan.HIGH,
        "max": Fan.MAX}
SWINGS = {"off": Swing.OFF, "vertical": Swing.VERTICAL, "horizontal": Swing.HORIZONTAL, "both": Swing.BOTH}
TOGGLES = ("power", "eco", "turbo", "sleep", "flash", "purifier", "breeze_away")
Angle = AirConditioner.SwingAngle
# Louver positions, 1 is the top (or the left).
ANGLES = {"1": Angle.POS_1, "2": Angle.POS_2, "3": Angle.POS_3, "4": Angle.POS_4, "5": Angle.POS_5}
# Below this share of the fastest compressor speed seen, the AC is holding the room, not cooling it.
HOLDING_SHARE = 0.25
# Starting guess for the compressor's top speed; raised as faster speeds are seen.
COMPRESSOR_HZ_GUESS = 60
# The Timer button: turn the AC off after this many minutes.
TIMER_MINUTES = (30, 60, 120, 180, 240, 480)

CLEANING = "The air conditioner is cleaning itself. Press power to stop the clean first."
# Toggles some units lack, and how to tell.
FEATURES: dict[str, Callable[[Any], bool]] = {
    "eco": lambda dev: bool(dev.supports_ieco or dev.supports_eco),
    "turbo": lambda dev: bool(dev.supports_turbo),
    "flash": lambda dev: bool(dev.supports_flash),
    "purifier": lambda dev: bool(dev.supports_purifier),
    "breeze_away": lambda dev: bool(dev.supports_breeze_away),
}
# Settings picked from a list: the names, what this unit supports, and the message if not.
CHOICES: dict[str, tuple[dict[str, Any], Callable[[Any], list], str]] = {
    "mode": (MODES, lambda dev: dev.supported_operation_modes, "This air conditioner does not have that mode."),
    "fan": (FANS, lambda dev: dev.supported_fan_speeds, "This air conditioner does not have that fan speed."),
    "swing": (SWINGS, lambda dev: dev.supported_swing_modes, "This air conditioner does not have that airflow."),
    "louver_v": (ANGLES, lambda dev: list(ANGLES.values()) if dev.supports_vertical_swing_angle else [],
                 "This air conditioner cannot hold its louvers there."),
    "louver_h": (ANGLES, lambda dev: list(ANGLES.values()) if dev.supports_horizontal_swing_angle else [],
                 "This air conditioner cannot hold its louvers there."),
}


class ACError(Exception):
    """A problem worded for the user."""


def _name(table: dict[str, Any], value: Any) -> str | None:
    return next((name for name, member in table.items() if member == value), None)


def load_link() -> dict[str, Any] | None:
    """The saved address and keys, or None when the AC has not been linked."""
    try:
        data = json.loads(AC_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    keys = ("ip", "port", "id", "token", "key")
    if not isinstance(data, dict) or not all(data.get(k) for k in keys):
        return None
    return data


class ACSession:
    """status: unlinked | connecting | online | offline"""

    def __init__(self, on_change: Callable[[], None], make_device: Callable[..., Any] = AirConditioner) -> None:
        self.status = "unlinked"
        self._on_change = on_change
        self._make_device = make_device
        self._link = load_link()
        self._device: Any = None
        self._lock = asyncio.Lock()  # one exchange with the AC at a time
        self._pending: dict[str, Any] = {}  # queued, not sent yet
        self._inflight: dict[str, Any] = {}  # being sent right now
        self._flusher: asyncio.Task[None] | None = None
        self._poller: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._silent_polls = 0
        self._off_timer: asyncio.TimerHandle | None = None
        self._off_at: float | None = None  # loop time the timer fires
        self._off_due = False  # the timer fired; turn off on the next fresh reading
        self.notice = ""  # a short message for the user, shown once per notice_id
        self.notice_id = 0
        self._top_hz = COMPRESSOR_HZ_GUESS  # fastest compressor speed seen, to judge how hard it works
        self._cleaning_since: float | None = None  # loop time the current self clean was first seen
        self.settings = load_settings()
        self.energy = EnergyLog(ENERGY_FILE, write_private)
        self.care = Care(CARE_FILE, write_private)
        self._cleaner: asyncio.Task[None] | None = None
        self.timetable = Timetable(SCHEDULE_FILE, write_private)
        self.curve = SleepCurve(SLEEP_FILE, write_private)
        # While drying the coil: when it started and the mode to go back to, for next time.
        self._drying: dict[str, Any] | None = None
        # Power cuts. Loop time stops while the Mac sleeps, so a sleeping Mac never looks like one.
        self._unreachable_since: float | None = None
        self._last_running: dict[str, Any] | None = None  # settings the last time it was seen on
        self.event: dict[str, Any] | None = None  # sent to the app once, for a notification
        self.event_id = 0
        if self._link:
            self.status = "connecting"

    # ------------------------------------------------------------ state

    def message(self) -> dict[str, Any]:
        """For the Mac app. Lists what this unit supports, so the app shows only those controls."""
        dev = self._device
        base = {"type": "ac", "status": self.status, "notice": self.notice, "notice_id": self.notice_id,
                "event": self.event, "event_id": self.event_id}
        if dev is None or self.status in ("unlinked", "connecting"):
            return base
        state = {
            "power": bool(dev.power_state),
            "mode": _name(MODES, dev.operational_mode),
            "target": dev.target_temperature,
            "indoor": dev.indoor_temperature,
            "outdoor": dev.outdoor_temperature,
            "fan": _name(FANS, dev.fan_speed),
            "swing": _name(SWINGS, dev.swing_mode),
            "eco": bool(dev.ieco if dev.supports_ieco else dev.eco),
            "turbo": bool(dev.turbo),
            "sleep": bool(dev.sleep),
            "flash": bool(dev.flash),
            "display": bool(dev.display_on),
            "purifier": bool(dev.purifier),
            "breeze_away": bool(dev.breeze_away),
            "louver_v": _name(ANGLES, dev.vertical_swing_angle),
            "louver_h": _name(ANGLES, dev.horizontal_swing_angle),
            # The exact fan speed, when one of 1 to 100 is set rather than a named speed.
            # (named speeds are numbers too, so only a plain int counts).
            "fan_percent": dev.fan_speed if type(dev.fan_speed) is int and 0 < dev.fan_speed <= 100 else None,
            # Self clean runs with the unit off; any change but power would end it.
            "cleaning": bool(dev.self_clean_active),
            "cleaning_minutes": self._cleaning_minutes(),
            # What the unit is really doing, beyond its settings.
            "effort": self._effort(dev),
            "phase": self._phase(dev),
            "compressor_hz": dev.compressor_frequency,
            "coil": dev.indoor_coil_temperature,
            "fault": dev.error_code or None,
            "filter_due": bool(dev.filter_alert),
            "drying_minutes_left": self._drying_minutes_left(),
            **self.energy.summary(),
            **self.care.summary(),
        }
        # Changes on their way show already, so the app never snaps back meanwhile.
        for waiting in (self._inflight, self._pending):
            state.update(waiting)
            # A named speed and an exact one replace each other.
            if "fan" in waiting:
                state["fan_percent"] = None
            if "fan_percent" in waiting:
                state["fan"] = None
        return {
            **base, **state, "settings": dict(self.settings),
            "min": dev.min_target_temperature, "max": dev.max_target_temperature,
            "modes": [n for n, m in MODES.items() if m in dev.supported_operation_modes],
            "fans": [n for n, f in FANS.items() if f in dev.supported_fan_speeds],
            "swings": [n for n, s in SWINGS.items() if s in dev.supported_swing_modes],
            "has_eco": bool(dev.supports_ieco or dev.supports_eco),
            "has_turbo": bool(dev.supports_turbo),
            "has_display": bool(dev.supports_display_control),
            "has_flash": bool(dev.supports_flash),
            "has_purifier": bool(dev.supports_purifier),
            "has_breeze_away": bool(dev.supports_breeze_away),
            "has_louver_v": bool(dev.supports_vertical_swing_angle),
            "has_louver_h": bool(dev.supports_horizontal_swing_angle),
            "has_fan_percent": bool(dev.supports_custom_fan_speed),
            "has_self_clean": bool(dev.supports_self_clean),
            "schedules": self.timetable.entries,
            "sleep_curve": self.curve.summary(),
            "sleep_curve_choices": list(CURVE_LENGTHS),
            "timer_choices": list(TIMER_MINUTES),
            "off_in": self._minutes_left(),
        }

    def _effort(self, dev: Any) -> float:
        """How hard the AC works right now, 0 to 1, from the compressor (or the fan in fan mode).
        The panel's air follows this, so it calms down once the room has reached the setting."""
        if not dev.power_state:
            return 0.0
        if dev.operational_mode == Mode.FAN_ONLY or dev.compressor_frequency is None:
            level = {Fan.SILENT: 0.25, Fan.LOW: 0.45, Fan.MEDIUM: 0.65, Fan.HIGH: 0.85, Fan.MAX: 1.0}
            return level.get(dev.fan_speed, 0.7)
        share = (dev.compressor_frequency or 0) / max(self._top_hz, 1)
        # Still some air while holding: the indoor fan keeps running.
        return round(max(0.2, min(share, 1.0)), 2)

    def _phase(self, dev: Any) -> str:
        """off, fan (fan only), working (compressor pushing) or holding (room reached, resting)."""
        if not dev.power_state:
            return "off"
        if dev.operational_mode == Mode.FAN_ONLY or dev.compressor_frequency is None:
            return "fan"
        working = (dev.compressor_frequency or 0) >= HOLDING_SHARE * self._top_hz
        return "working" if working else "holding"

    def _cleaning_minutes(self) -> int | None:
        if self._cleaning_since is None:
            return None
        return int((asyncio.get_running_loop().time() - self._cleaning_since) // 60)

    def _set_status(self, status: str) -> None:
        """Every reading is sent on, changed or not: the room temperature moves on its own."""
        self.status = status
        self._on_change()

    def _tell(self, text: str) -> None:
        self.notice = text
        self.notice_id += 1

    # ------------------------------------------------------------ connection

    def start(self) -> None:
        if self._link and self._poller is None:
            self._poller = asyncio.get_running_loop().create_task(self._poll_loop())

    async def close(self) -> None:
        self.energy.save()
        self.care.save()
        if self._off_timer:
            self._off_timer.cancel()
        tasks = [task for task in (self._poller, self._flusher, self._cleaner) if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def refresh_soon(self) -> None:
        """Read the AC now, for a panel that just opened. Picks up a link made since Breeze started."""
        if self._link is None:
            self._link = load_link()
            if self._link is None:
                return
            self.status = "connecting"
            self._on_change()
            self.start()
        self._wake.set()

    async def _connect(self) -> None:
        link = self._link
        assert link is not None
        dev = self._make_device(ip=link["ip"], port=link["port"], device_id=link["id"])
        await dev.authenticate(link["token"], link["key"])
        await dev.get_capabilities()
        # Extra readings, one more exchange each per poll: compressor and coils, indoor fan, energy.
        dev.enable_group1_data_requests = True
        dev.enable_group2_data_requests = True
        dev.enable_energy_usage_requests = True
        self._device = dev

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never let one bad reading stop the polling for good.
                log.exception("AC poll failed")
            self._wake.clear()
            quick = self.status == "offline" and 0 < self._silent_polls <= QUICK_RETRIES
            try:
                await asyncio.wait_for(self._wake.wait(), QUICK_RETRY_SECONDS if quick else POLL_SECONDS)
            except TimeoutError:
                pass

    async def _poll_once(self) -> None:
        try:
            async with self._lock:
                if self._device is None:
                    await self._connect()
                await self._device.refresh()
            online = bool(self._device.online)
        except Exception as exc:  # network and protocol errors of every kind end here
            log.info("AC not reachable: %s", type(exc).__name__)
            online = False
        self._silent_polls = 0 if online else self._silent_polls + 1
        now = asyncio.get_running_loop().time()
        if not online and self._unreachable_since is None:
            self._unreachable_since = now
        if online:
            self.status = "online"  # before acting on the reading, so changes it makes are allowed
            if self._unreachable_since is not None:
                self._came_back(now - self._unreachable_since)
            self._unreachable_since = None
            self._after_fresh_reading()
        self._set_status("online" if online else "offline")
        if self._silent_polls >= REDISCOVER_AFTER:
            self._silent_polls = 0
            await self._rediscover()

    def _after_fresh_reading(self) -> None:
        """Things that wait for a reading we can trust: a due timer, changes held back by a failure."""
        dev = self._device
        BCD = AirConditioner.EnergyDataFormat.BCD  # the right encoding on this unit, see energy.py
        self.energy.record(dev.get_total_energy_usage(BCD), dev.get_real_time_power_usage(BCD))
        hz = dev.compressor_frequency or 0
        self._top_hz = max(self._top_hz, hz)
        if dev.self_clean_active:
            if self._cleaning_since is None:
                self._cleaning_since = asyncio.get_running_loop().time()
        else:
            self._cleaning_since = None
        if self._off_timer and not dev.power_state and not self._pending.get("power"):
            self._cancel_timer()  # switched off by hand: an old timer must not catch it later
        if self._off_due:
            self._off_due = False
            if dev.power_state and not dev.self_clean_active:
                self._turn_off()
        if self._drying:
            self._check_drying(dev)
        self._remember_running()
        self._look_after(dev)
        self._run_schedules()
        self._follow_curve(dev)
        if self._pending and (self._flusher is None or self._flusher.done()):
            self._flusher = asyncio.get_running_loop().create_task(self._flush())

    # ------------------------------------------------------------ power cuts

    def _remember_running(self) -> None:
        dev = self._device
        if dev.power_state and not self._drying:
            self._last_running = {"mode": _name(MODES, dev.operational_mode), "target": dev.target_temperature,
                                  "fan": _name(FANS, dev.fan_speed), "swing": _name(SWINGS, dev.swing_mode)}

    def _came_back(self, seconds: float) -> None:
        """The AC answers again. If it was running and came back off, the power most likely went:
        put it back on when the user chose that, otherwise ask."""
        dev = self._device
        if seconds < OUTAGE_SECONDS or self._last_running is None or dev.power_state or dev.self_clean_active:
            return
        minutes = max(1, round(seconds / 60))
        if self.settings["restore_after_outage"]:
            self.restore()
            text = f"The power came back after about {minutes} min. Breeze switched the air conditioner back on."
            self._send_event("restored", text)
        else:
            text = f"The power came back after about {minutes} min, and the air conditioner is off."
            self._send_event("power_back", text)

    def _send_event(self, kind: str, text: str) -> None:
        self.event = {"kind": kind, "text": text}
        self.event_id += 1

    def restore(self) -> None:
        """On again, with the settings it had when last seen running."""
        if self._last_running is None:
            raise ACError("Breeze has not seen the air conditioner running yet.")
        known = {k: v for k, v in self._last_running.items() if v is not None}
        self.change({"power": True, **known})

    async def _rediscover(self) -> None:
        """Find the AC by its id if its address changed, and keep the new address."""
        assert self._link is not None
        try:
            found = await Discover.discover(timeout=DISCOVER_SECONDS, auto_connect=False)
        except OSError:
            return
        match = next((d for d in found if d.id == self._link["id"]), None)
        if match and (match.ip, match.port) != (self._link["ip"], self._link["port"]):
            log.info("AC moved to a new address")
            self._link.update(ip=match.ip, port=match.port)
            try:
                save_link(self._link)
            except OSError as exc:
                log.info("could not save the new AC address: %s", type(exc).__name__)
            async with self._lock:
                self._device = None

    # ------------------------------------------------------------ self clean and filter

    def _look_after(self, dev: Any) -> None:
        """Count wet hours, tell the user about a finished clean or a filter due, start a clean when due."""
        wet = _name(MODES, dev.operational_mode) in WET_MODES
        news = self.care.record(bool(dev.power_state), wet, bool(dev.self_clean_active))
        if news == "clean_done":
            self._send_event("clean_done", "The self clean finished. The coil is clean and dry.")
        elif news == "filter_due":
            hours = round(self.care.filter_hours)
            self._send_event("filter", f"Time to wash the filter: about {hours} hours of cooling since the last wash.")
        if self._clean_allowed(dev) and self.care.clean_due(self.settings["auto_clean"]):
            self.care.asked_for_clean()
            self._cleaner = asyncio.get_running_loop().create_task(self._start_clean())

    def _clean_allowed(self, dev: Any) -> bool:
        """Only with the AC off and idle: nothing queued or being sent, no drying, no timer waiting."""
        return dev.supports_self_clean and self._off_and_idle(dev) and (self._cleaner is None or self._cleaner.done())

    async def _start_clean(self) -> None:
        try:
            async with self._lock:
                dev = self._device
                # Checked again under the lock: a change may have been queued meanwhile.
                if dev is None or not self._off_and_idle(dev):
                    return
                await dev.start_self_clean()
        except Exception as exc:
            log.info("AC self clean start failed: %s", type(exc).__name__)
            return
        log.info("asked the AC for a self clean")
        self._wake.set()

    def _off_and_idle(self, dev: Any) -> bool:
        return (not dev.power_state and not dev.self_clean_active and not self._pending and not self._inflight
                and self._drying is None and not self._off_due)

    def filter_cleaned(self) -> None:
        self.care.filter_cleaned()
        self._on_change()

    # ------------------------------------------------------------ schedules and the sleep curve

    def set_schedules(self, entries: object) -> None:
        try:
            self.timetable.replace(entries)
        except ScheduleError as exc:
            raise ACError(str(exc)) from None
        self._on_change()

    def _run_schedules(self) -> None:
        run, missed = self.timetable.due()
        for entry in run:
            try:
                self.change(changes_for(entry))
            except ACError as exc:
                self._tell(f"The {entry['time']} schedule did not run: {exc}")
        for entry in missed:
            self._tell(f"Breeze could not reach the air conditioner at {entry['time']}, so that schedule did not run.")

    def start_sleep_curve(self, minutes: object) -> None:
        """Start Breeze's curve for `minutes`, or stop it with None."""
        if minutes is None:
            if self.curve.active:
                self.curve.stop()
                self._on_change()
            return
        dev = self._device
        if minutes not in CURVE_LENGTHS:
            raise ACError("Choose one of the sleep curve lengths.")
        if dev is None or self.status != "online" or not dev.power_state:
            raise ACError("Turn the air conditioner on first.")
        mode = self._pending.get("mode") or _name(MODES, dev.operational_mode)
        if mode not in ("cool", "auto"):
            raise ACError("The sleep curve works while cooling.")
        if dev.sleep or self._pending.get("sleep"):
            raise ACError("Turn the unit's own Sleep off first.")
        start = self._pending.get("target", dev.target_temperature)
        self.curve.start(start, minutes, self.settings["sleep_curve_end"])
        self._on_change()

    def _stop_curve(self, why: str = "The sleep curve stopped.") -> None:
        self.curve.stop()
        self._tell(why)

    def _follow_curve(self, dev: Any) -> None:
        """Keep the setting where the curve wants it; stop if the AC was turned off or to its own Sleep."""
        if not self.curve.active:
            return
        if not dev.power_state or dev.sleep:
            self._stop_curve()
            return
        if self.curve.finished():
            state = self.curve.state
            self.curve.stop()
            ending = {"power": False} if state["end"] == "off" else {"target": state["start_target"]}
            try:
                self.change(ending)
            except ACError as exc:
                self._tell(f"The sleep curve ended, but: {exc}")
                return
            self._tell("Good morning. The sleep curve has ended.")
            return
        wanted = self.curve.wanted(dev.max_target_temperature)
        if dev.target_temperature != wanted and "target" not in self._pending and "target" not in self._inflight:
            self._pending["target"] = wanted
            self._kick()

    # ------------------------------------------------------------ drying the coil

    def _turn_off(self) -> None:
        """Switch off, the way Breeze does it: dry the coil first if the user asked for that.
        Only Breeze's own power offs come here (button, timer); an off from the hand remote never does."""
        dev = self._device
        if self._drying is not None:
            self._finish_drying()  # already drying (the timer fired meanwhile): off now, as it was
            return
        mode = self._pending.get("mode") or _name(MODES, dev.operational_mode)
        can_dry = Mode.FAN_ONLY in dev.supported_operation_modes and Fan.LOW in dev.supported_fan_speeds
        if self.settings["dry_coil"] and can_dry and dev.power_state and mode in WET_MODES and not dev.self_clean_active:
            # Keep the user's mode and fan speed (named or exact) to put back afterwards.
            fan = {"fan_percent": dev.fan_speed} if type(dev.fan_speed) is int else {"fan": _name(FANS, dev.fan_speed)}
            self._drying = {"since": asyncio.get_running_loop().time(), "restore": {"mode": mode, **fan}}
            self._pending.pop("fan_percent", None)
            self._pending.update(mode="fan", fan="low")
            self._tell("Drying the coil before switching off.")
        else:
            self._pending["power"] = False

    def _check_drying(self, dev: Any) -> None:
        """Finish once the coil is dry or time is up. If the AC was switched off another way, stop."""
        assert self._drying is not None
        if not dev.power_state:
            self._drying = None
            return
        elapsed = (asyncio.get_running_loop().time() - self._drying["since"]) / 60
        coil, room = dev.indoor_coil_temperature, dev.indoor_temperature
        dry = coil is not None and room is not None and coil >= room - DRY_DONE_WITHIN
        if dry or elapsed >= DRY_MAX_MINUTES:
            self._finish_drying()

    def _finish_drying(self) -> None:
        """Off, with the mode and fan put back so the next switch on is as before."""
        assert self._drying is not None
        self._pending.update(power=False, **self._restore_after_drying())
        self._drying = None
        self._tell("The coil is dry. The air conditioner is off.")

    def _restore_after_drying(self) -> dict[str, Any]:
        restore = {k: v for k, v in self._drying["restore"].items() if v is not None}
        if "fan_percent" in restore:
            self._pending.pop("fan", None)
        return restore

    def _cancel_drying(self, changes: dict[str, Any]) -> None:
        """The user took over: drying stops and their mode and fan come back, unless they set them now."""
        assert self._drying is not None
        restore = self._restore_after_drying()
        sets_fan = "fan" in changes or "fan_percent" in changes
        self._pending.update({k: v for k, v in restore.items()
                              if not (k == "mode" and "mode" in changes) and not (k in ("fan", "fan_percent") and sets_fan)})
        self._drying = None

    def _drying_minutes_left(self) -> int | None:
        if self._drying is None:
            return None
        elapsed = (asyncio.get_running_loop().time() - self._drying["since"]) / 60
        return max(1, round(DRY_MAX_MINUTES - elapsed))

    def set_setting(self, name: object, value: object) -> None:
        checked = check_setting(name, value)
        if checked is None:
            raise ACError("That setting or value is not allowed.")
        value = checked
        self.settings[name] = value
        write_private(SETTINGS_FILE, self.settings)
        self._on_change()

    # ------------------------------------------------------------ changes

    def change(self, changes: dict[str, Any]) -> None:
        """Check every value against what this unit supports, then queue it."""
        dev = self._device
        if dev is None or self.status != "online":
            raise ACError("The air conditioner is not reachable right now.")
        if not changes:
            raise ACError("Nothing to change.")
        if self._drying is not None and changes.get("power") is False:
            # Power while drying: off now.
            self._finish_drying()
            self._kick()
            return
        if dev.self_clean_active and set(changes) != {"power"}:
            raise ACError(CLEANING)
        checked: dict[str, Any] = {}
        for name, value in changes.items():
            if name in TOGGLES:
                if not isinstance(value, bool):
                    raise ACError("Bad value.")
                if name in FEATURES and not FEATURES[name](dev):
                    raise ACError("This air conditioner does not have that.")
            elif name == "target":
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not (
                        dev.min_target_temperature <= value <= dev.max_target_temperature):
                    raise ACError(f"Choose {dev.min_target_temperature:g} to {dev.max_target_temperature:g} °C.")
                value = float(math.floor(value + 0.5))  # whole degrees, halves round up
            elif name == "fan_percent":
                if not dev.supports_custom_fan_speed:
                    raise ACError("This air conditioner has no exact fan speeds.")
                if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 100:
                    raise ACError("Choose a fan speed from 1 to 100%.")
            elif name in CHOICES:
                table, supported, problem = CHOICES[name]
                if not isinstance(value, str) or table.get(value) not in supported(dev):
                    raise ACError(problem)
            else:
                raise ACError("Unknown setting.")
            checked[name] = value
        # Checked, so a refused request never ends the drying or the sleep curve.
        if self.curve.active and (checked.get("power") is False or checked.get("sleep") is True
                                  or "target" in checked or "mode" in checked):
            self._stop_curve()  # the user took over
        if self._drying is not None:
            self._cancel_drying(checked)
        power = checked.pop("power", None)
        if "fan" in checked:
            self._pending.pop("fan_percent", None)
        if "fan_percent" in checked:
            self._pending.pop("fan", None)
        self._pending.update(checked)
        if power is False:
            self._turn_off()  # after the other changes, so drying starts from them
        elif power is True:
            self._pending["power"] = True
        self._kick()

    def _kick(self) -> None:
        """Tell the app, and send whatever is queued."""
        self._on_change()
        if self._pending and (self._flusher is None or self._flusher.done()):
            self._flusher = asyncio.get_running_loop().create_task(self._flush())

    async def _flush(self) -> None:
        """Send queued changes. Values changed again meanwhile go out in the next round."""
        while self._pending:
            self._inflight, self._pending = self._pending, {}
            changes = self._inflight
            try:
                async with self._lock:
                    dev = self._device
                    if dev is None:
                        raise ConnectionError("no device")
                    if dev.self_clean_active and set(changes) != {"power"}:
                        # Started from the hand remote or the Midea app since the change was queued.
                        changes = {k: v for k, v in changes.items() if k == "power"}
                        self._tell(CLEANING)
                    if changes:
                        self._apply_to(dev, changes)
                        await dev.apply()
                    online = bool(dev.online)
            except Exception as exc:
                log.info("AC change failed: %s", type(exc).__name__)
                online = False
            self._inflight = {}
            if not online:
                # Keep the change for the next good reading; newer values win.
                self._pending = {**changes, **self._pending}
                self._tell("Couldn't reach the air conditioner. Breeze will try again.")
                self._set_status("offline")
                return
            self._set_status("online")

    @staticmethod
    def _apply_to(dev: Any, changes: dict[str, Any]) -> None:
        for name, value in changes.items():
            if name == "power":
                dev.power_state = value
            elif name == "target":
                dev.target_temperature = value
            elif name == "mode":
                dev.operational_mode = MODES[value]
            elif name == "fan":
                dev.fan_speed = FANS[value]
            elif name == "swing":
                dev.swing_mode = SWINGS[value]
            elif name == "eco":
                if dev.supports_ieco:
                    dev.ieco = value
                else:
                    dev.eco = value
            elif name == "turbo":
                dev.turbo = value
            elif name == "sleep":
                dev.sleep = value
            elif name == "flash":
                dev.flash = value
            elif name == "purifier":
                dev.purifier = value
            elif name == "breeze_away":
                dev.breeze_away = value
            elif name == "louver_v":
                dev.vertical_swing_angle = ANGLES[value]
            elif name == "louver_h":
                dev.horizontal_swing_angle = ANGLES[value]
            elif name == "fan_percent":
                dev.fan_speed = value

    # ------------------------------------------------------------ timer

    def _minutes_left(self) -> int | None:
        if self._off_at is None:
            return None
        return max(1, round((self._off_at - asyncio.get_running_loop().time()) / 60))

    def set_off_timer(self, minutes: object) -> None:
        """Turn the AC off after `minutes`, or cancel with None. Runs while Breeze runs."""
        if minutes is not None and minutes not in TIMER_MINUTES:
            raise ACError("Choose one of the timer lengths.")
        if minutes is not None and not (self._device and self._device.power_state):
            raise ACError("Turn the air conditioner on first.")
        self._cancel_timer()
        if minutes is not None:
            loop = asyncio.get_running_loop()
            self._off_at = loop.time() + minutes * 60
            self._off_timer = loop.call_later(minutes * 60, self._timer_fired)
        self._on_change()

    def _cancel_timer(self) -> None:
        if self._off_timer:
            self._off_timer.cancel()
        self._off_timer = self._off_at = None

    def _timer_fired(self) -> None:
        """Turn off on a fresh reading, so a clean started meanwhile is never cut short. If the AC
        cannot be reached, the next reading that can does it."""
        self._off_timer = self._off_at = None
        self._off_due = True
        self._on_change()
        self.refresh_soon()

    async def toggle_display(self) -> None:
        """The light on the indoor unit. Midea only offers a toggle for it."""
        dev = self._device
        if dev is None or self.status != "online" or not dev.supports_display_control:
            raise ACError("The air conditioner is not reachable right now.")
        async with self._lock:
            if dev.self_clean_active:
                raise ACError(CLEANING)
            try:
                await dev.toggle_display()
            except Exception as exc:
                log.info("AC light toggle failed: %s", type(exc).__name__)
                self._set_status("offline")
                raise ACError("Couldn't reach the air conditioner.") from None
        self._on_change()
