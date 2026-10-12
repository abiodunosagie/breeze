"""Breeze's files in ~/.config/breeze, all readable only by the user, and the user's settings."""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

CONFIG_DIR = Path.home() / ".config" / "breeze"
AC_FILE = CONFIG_DIR / "ac.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
ENERGY_FILE = CONFIG_DIR / "energy.json"
CARE_FILE = CONFIG_DIR / "care.json"
SCHEDULE_FILE = CONFIG_DIR / "schedules.json"
SLEEP_FILE = CONFIG_DIR / "sleep.json"
MAX_PRICE = 100_000.0  # naira per kWh; anything above is a typo

# The user's choices, all off until turned on.
DEFAULT_SETTINGS: dict[str, Any] = {
    # On switching off after cooling, run the fan alone until the coil is dry: no damp coil for mould.
    "dry_coil": False,
    # After a power cut, switch the AC back on by itself, as it was. Off: Breeze asks first.
    "restore_after_outage": False,
    # Naira per kWh, set by the user. 0 means not set: kWh only, no money.
    "price_per_kwh": 0.0,
    # Start a self clean now and then, by day, while the AC is off. See care.py.
    "auto_clean": False,
    # How Breeze's sleep curve ends in the morning: back to the starting setting, or off.
    "sleep_curve_end": "restore",
}
# Drying ends when the coil is this close to the room temperature, or after DRY_MAX_MINUTES.
DRY_DONE_WITHIN = 1.0
DRY_MAX_MINUTES = 20
# Unreachable this long, with the Mac awake, counts as an outage worth telling the user about.
OUTAGE_SECONDS = 60
# Modes that leave the coil cold and wet.
WET_MODES = ("cool", "dry", "auto")
# How each setting's value is checked.
SETTING_RULES: dict[str, Callable[[Any], bool]] = {
    "dry_coil": lambda v: isinstance(v, bool),
    "restore_after_outage": lambda v: isinstance(v, bool),
    "auto_clean": lambda v: isinstance(v, bool),
    "sleep_curve_end": lambda v: v in ("restore", "off"),
    "price_per_kwh": lambda v: isinstance(v, float) and math.isfinite(v) and 0 <= v <= MAX_PRICE,
}


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
    return {name: data[name] if SETTING_RULES[name](data.get(name)) else default
            for name, default in DEFAULT_SETTINGS.items()}


def check_setting(name: object, value: object) -> Any:
    """The value as stored, or None if the name is unknown or the value not allowed."""
    if not isinstance(name, str) or name not in DEFAULT_SETTINGS:
        return None
    if isinstance(DEFAULT_SETTINGS[name], float) and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)  # JSON sends 120 for 120.0
    return value if SETTING_RULES[name](value) else None
