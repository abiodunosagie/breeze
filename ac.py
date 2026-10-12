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
import os
from collections.abc import Callable
from typing import Any

from pathlib import Path

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


def _save_link(link: dict[str, Any]) -> None:
    fd = os.open(AC_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(link, out)


class ACSession:
    """status: unlinked | connecting | online | offline"""

    def __init__(self, on_change: Callable[[], None], make_device: Callable[..., Any] = AirConditioner) -> None:
        self.status = "unlinked"
        self._on_change = on_change
        self._make_device = make_device
        self._link = load_link()
        self._device: Any = None
        self._lock = asyncio.Lock()  # one exchange with the AC at a time
        self._pending: dict[str, Any] = {}
        self._flusher: asyncio.Task[None] | None = None
        self._poller: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._silent_polls = 0
        self._off_timer: asyncio.TimerHandle | None = None
        self._off_at: float | None = None  # loop time the timer fires
        if self._link:
            self.status = "connecting"

    # ------------------------------------------------------------ state

    def message(self) -> dict[str, Any]:
        """For the Mac app. Lists what this unit supports, so the app shows only those controls."""
        dev = self._device
        if dev is None or self.status in ("unlinked", "connecting"):
            return {"type": "ac", "status": self.status}
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
        # A change waiting to go out shows already, so the app never snaps back meanwhile.
        state.update(self._pending)
        return {
            "type": "ac", "status": self.status, **state,
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
        if status != self.status:
            self.status = status
        self._on_change()

    # ------------------------------------------------------------ connection

    def start(self) -> None:
        if self._link and self._poller is None:
            self._poller = asyncio.get_running_loop().create_task(self._poll_loop())

    async def close(self) -> None:
        if self._off_timer:
            self._off_timer.cancel()
        for task in (self._poller, self._flusher):
            if task:
                task.cancel()

    def refresh_soon(self) -> None:
        """Read the AC now, for a panel that just opened."""
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
                async with self._lock:
                    if self._device is None:
                        await self._connect()
                    await self._device.refresh()
                online = bool(self._device.online)
            except Exception as exc:  # network and protocol errors of every kind end here
                log.info("AC not reachable: %s", type(exc).__name__)
                online = False
            self._silent_polls = 0 if online else self._silent_polls + 1
            self._set_status("online" if online else "offline")
            if self._silent_polls >= REDISCOVER_AFTER:
                self._silent_polls = 0
                await self._rediscover()
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), POLL_SECONDS)
            except TimeoutError:
                pass

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
            _save_link(self._link)
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
            raise ACError("The air conditioner is cleaning itself. Press power to stop the clean first.")
        checked: dict[str, Any] = {}
        for name, value in changes.items():
            if name in TOGGLES:
                if not isinstance(value, bool):
                    raise ACError("Bad value.")
                if (name == "eco" and not (dev.supports_ieco or dev.supports_eco)) or (
                        name == "turbo" and not dev.supports_turbo) or (name == "flash" and not dev.supports_flash):
                    raise ACError("This air conditioner does not have that.")
            elif name == "target":
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not (
                        dev.min_target_temperature <= value <= dev.max_target_temperature):
                    raise ACError(f"Choose {dev.min_target_temperature:g} to {dev.max_target_temperature:g} °C.")
                value = float(round(value))
            elif name == "mode":
                if MODES.get(value) not in dev.supported_operation_modes:
                    raise ACError("This air conditioner does not have that mode.")
            elif name == "fan":
                if FANS.get(value) not in dev.supported_fan_speeds:
                    raise ACError("This air conditioner does not have that fan speed.")
            elif name == "swing":
                if SWINGS.get(value) not in dev.supported_swing_modes:
                    raise ACError("This air conditioner does not have that airflow.")
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
            changes, self._pending = self._pending, {}
            try:
                async with self._lock:
                    self._apply_to(self._device, changes)
                    await self._device.apply()
                    online = bool(self._device.online)
            except Exception as exc:
                log.info("AC change failed: %s", type(exc).__name__)
                online = False
            self._set_status("online" if online else "offline")

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
        if self._off_timer:
            self._off_timer.cancel()
        self._off_timer = self._off_at = None
        if minutes is not None:
            loop = asyncio.get_running_loop()
            self._off_at = loop.time() + minutes * 60
            self._off_timer = loop.call_later(minutes * 60, self._timer_fired)
        self._on_change()

    def _timer_fired(self) -> None:
        self._off_timer = self._off_at = None
        dev = self._device
        if dev is not None and (dev.self_clean_active or not dev.power_state):
            self._on_change()  # already off (or cleaning, which an off command would end)
            return
        try:
            self.change({"power": False})
        except ACError:
            log.info("off timer fired while the AC was not reachable")
            self._on_change()

    async def toggle_display(self) -> None:
        """The light on the indoor unit. Midea only offers a toggle for it."""
        dev = self._device
        if dev is None or self.status != "online" or not dev.supports_display_control:
            raise ACError("The air conditioner is not reachable right now.")
        if dev.self_clean_active:
            raise ACError("The air conditioner is cleaning itself. Press power to stop the clean first.")
        async with self._lock:
            await dev.toggle_display()
        self._on_change()
