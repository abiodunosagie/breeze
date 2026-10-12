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
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from msmart.device import AirConditioner
from msmart.discover import Discover

CONFIG_DIR = Path.home() / ".config" / "breeze"
AC_FILE = CONFIG_DIR / "ac.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
# The user's choices, all off until turned on.
DEFAULT_SETTINGS: dict[str, Any] = {
    # On switching off after cooling, run the fan alone until the coil is dry: no damp coil for mould.
    "dry_coil": False,
}
# Drying ends when the coil is this close to the room temperature, or after DRY_MAX_MINUTES.
DRY_DONE_WITHIN = 1.0
DRY_MAX_MINUTES = 20
# Modes that leave the coil cold and wet.
WET_MODES = ("cool", "dry", "auto")
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


def write_private(path: Path, data: Any) -> None:
    """Write JSON readable only by this user, all at once: a crash never leaves half a file."""
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)  # also tighten a folder that already existed
    fd, temp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".tmp-", suffix=".json")  # created 0600
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out)
        os.replace(temp, path)
    except BaseException:
        os.unlink(temp)
        raise


def save_link(link: dict[str, Any]) -> None:
    write_private(AC_FILE, link)


def load_settings() -> dict[str, Any]:
    """The user's choices, each falling back to its default when missing or of the wrong type."""
    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {name: data[name] if isinstance(data.get(name), type(default)) else default
            for name, default in DEFAULT_SETTINGS.items()}


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
        # While drying the coil: when it started and the mode to go back to, for next time.
        self._drying: dict[str, Any] | None = None
        if self._link:
            self.status = "connecting"

    # ------------------------------------------------------------ state

    def message(self) -> dict[str, Any]:
        """For the Mac app. Lists what this unit supports, so the app shows only those controls."""
        dev = self._device
        base = {"type": "ac", "status": self.status, "notice": self.notice, "notice_id": self.notice_id}
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
        }
        # Changes on their way show already, so the app never snaps back meanwhile.
        state.update(self._inflight)
        state.update(self._pending)
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
        if self._off_timer:
            self._off_timer.cancel()
        tasks = [task for task in (self._poller, self._flusher) if task]
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
        if online:
            self._after_fresh_reading()
        self._set_status("online" if online else "offline")
        if self._silent_polls >= REDISCOVER_AFTER:
            self._silent_polls = 0
            await self._rediscover()

    def _after_fresh_reading(self) -> None:
        """Things that wait for a reading we can trust: a due timer, changes held back by a failure."""
        dev = self._device
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
        if self._pending and (self._flusher is None or self._flusher.done()):
            self._flusher = asyncio.get_running_loop().create_task(self._flush())

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

    # ------------------------------------------------------------ changes

    # ------------------------------------------------------------ drying the coil

    def _turn_off(self) -> None:
        """Switch off, the way Breeze does it: dry the coil first if the user asked for that.
        Only Breeze's own power offs come here (button, timer); an off from the hand remote never does."""
        dev = self._device
        mode = _name(MODES, dev.operational_mode)
        if self.settings["dry_coil"] and dev.power_state and mode in WET_MODES and not dev.self_clean_active:
            self._drying = {"since": asyncio.get_running_loop().time(), "mode": mode}
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
        """Off, with the mode put back so the next switch on cools again."""
        assert self._drying is not None
        self._pending.update(power=False, mode=self._drying["mode"])
        self._drying = None
        self._tell("The coil is dry. The air conditioner is off.")

    def _drying_minutes_left(self) -> int | None:
        if self._drying is None:
            return None
        elapsed = (asyncio.get_running_loop().time() - self._drying["since"]) / 60
        return max(1, round(DRY_MAX_MINUTES - elapsed))

    def set_setting(self, name: object, value: object) -> None:
        if name not in DEFAULT_SETTINGS or not isinstance(value, type(DEFAULT_SETTINGS[name])):
            raise ACError("Unknown setting.")
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
        if self._drying is not None:
            # Any press while drying takes over: power means off now, anything else ends the drying.
            if changes.get("power") is False:
                self._finish_drying()
                self._kick()
                return
            self._drying = None
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
        if checked.pop("power", None) is False:
            self._turn_off()
        elif "power" in changes:
            checked["power"] = True
        self._pending.update(checked)
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
