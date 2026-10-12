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
POLL_SECONDS = 20.0
# After this many silent polls in a row, look for the AC again (the router may have moved it).
REDISCOVER_AFTER = 3
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
TOGGLES = ("power", "eco", "turbo", "sleep", "flash")
# The Timer button: turn the AC off after this many minutes.
TIMER_MINUTES = (30, 60, 120, 180, 240, 480)

CLEANING = "The air conditioner is cleaning itself. Press power to stop the clean first."
# Toggles some units lack, and how to tell.
FEATURES: dict[str, Callable[[Any], bool]] = {
    "eco": lambda dev: bool(dev.supports_ieco or dev.supports_eco),
    "turbo": lambda dev: bool(dev.supports_turbo),
    "flash": lambda dev: bool(dev.supports_flash),
}
# Settings picked from a list: the names, what this unit supports, and the message if not.
CHOICES: dict[str, tuple[dict[str, Any], Callable[[Any], list], str]] = {
    "mode": (MODES, lambda dev: dev.supported_operation_modes, "This air conditioner does not have that mode."),
    "fan": (FANS, lambda dev: dev.supported_fan_speeds, "This air conditioner does not have that fan speed."),
    "swing": (SWINGS, lambda dev: dev.supported_swing_modes, "This air conditioner does not have that airflow."),
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


def save_link(link: dict[str, Any]) -> None:
    """Write the keys readable only by this user, all at once: a crash never leaves half a file."""
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)  # also tighten a folder that already existed
    fd, temp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".ac-", suffix=".json")  # created 0600
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(link, out)
        os.replace(temp, AC_FILE)
    except BaseException:
        os.unlink(temp)
        raise


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
            # Self clean runs with the unit off; any change but power would end it.
            "cleaning": bool(dev.self_clean_active),
        }
        # Changes on their way show already, so the app never snaps back meanwhile.
        state.update(self._inflight)
        state.update(self._pending)
        return {
            **base, **state,
            "min": dev.min_target_temperature, "max": dev.max_target_temperature,
            "modes": [n for n, m in MODES.items() if m in dev.supported_operation_modes],
            "fans": [n for n, f in FANS.items() if f in dev.supported_fan_speeds],
            "swings": [n for n, s in SWINGS.items() if s in dev.supported_swing_modes],
            "has_eco": bool(dev.supports_ieco or dev.supports_eco),
            "has_turbo": bool(dev.supports_turbo),
            "has_display": bool(dev.supports_display_control),
            "has_flash": bool(dev.supports_flash),
            "timer_choices": list(TIMER_MINUTES),
            "off_in": self._minutes_left(),
        }

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
            try:
                await asyncio.wait_for(self._wake.wait(), POLL_SECONDS)
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
        if self._off_timer and not dev.power_state and not self._pending.get("power"):
            self._cancel_timer()  # switched off by hand: an old timer must not catch it later
        if self._off_due:
            self._off_due = False
            if dev.power_state and not dev.self_clean_active:
                # Power is always supported, so this skips change()'s checks safely.
                self._pending["power"] = False
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

    def change(self, changes: dict[str, Any]) -> None:
        """Check every value against what this unit supports, then queue it."""
        dev = self._device
        if dev is None or self.status != "online":
            raise ACError("The air conditioner is not reachable right now.")
        if not changes:
            raise ACError("Nothing to change.")
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
            elif name in CHOICES:
                table, supported, problem = CHOICES[name]
                if not isinstance(value, str) or table.get(value) not in supported(dev):
                    raise ACError(problem)
            else:
                raise ACError("Unknown setting.")
            checked[name] = value
        self._pending.update(checked)
        self._on_change()
        if self._flusher is None or self._flusher.done():
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
