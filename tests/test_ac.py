"""The air conditioner session: what the Mac app sees, what it may change, and the change queue."""

import asyncio
from pathlib import Path

import pytest

import ac
from ac import FANS, MODES, SWINGS, ACError, ACSession


class FakeAC:
    """The parts of msmart's AirConditioner Breeze uses, with a unit like the owner's (no heat)."""

    def __init__(self, ip=None, port=None, device_id=None):
        self.power_state = True
        self.operational_mode = MODES["cool"]
        self.target_temperature = 16.0
        self.indoor_temperature = 25.0
        self.outdoor_temperature = 30.4
        self.fan_speed = FANS["max"]
        self.swing_mode = SWINGS["both"]
        self.eco = self.ieco = self.turbo = self.sleep = self.flash = False
        self.display_on = True
        self.self_clean_active = False
        self.compressor_frequency = 52
        self.indoor_coil_temperature = 16.5
        self.error_code = 0
        self.filter_alert = False
        self.purifier = self.breeze_away = False
        self.vertical_swing_angle = self.horizontal_swing_angle = ac.Angle.OFF
        self.supports_purifier = self.supports_breeze_away = True
        self.supports_vertical_swing_angle = self.supports_horizontal_swing_angle = True
        self.supports_custom_fan_speed = True
        self.total_kwh, self.power = 256.03, 225.0
        self.online = True
        self.min_target_temperature, self.max_target_temperature = 16.0, 30.0
        self.supported_operation_modes = [MODES["fan"], MODES["dry"], MODES["cool"], MODES["auto"]]
        self.supported_fan_speeds = list(FANS.values())
        self.supported_swing_modes = list(SWINGS.values())
        self.supports_eco, self.supports_ieco = False, True
        self.supports_turbo = self.supports_display_control = self.supports_flash = True
        self.applied = []

    def get_total_energy_usage(self, _format):
        return self.total_kwh

    def get_real_time_power_usage(self, _format):
        return self.power

    async def authenticate(self, token, key):
        pass

    async def get_capabilities(self):
        pass

    async def apply(self):
        await asyncio.sleep(0)
        self.applied.append((self.target_temperature, self.operational_mode))


def online_session(device=None):
    session = ACSession(on_change=lambda: None)
    session.settings = dict(ac.DEFAULT_SETTINGS)  # never the owner's real choices
    session.energy = ac.EnergyLog(Path("/nonexistent/energy.json"), lambda path, data: None)
    session._device = device or FakeAC()
    session.status = "online"
    return session


def test_message_lists_only_what_the_unit_has():
    message = online_session().message()
    assert message["modes"] == ["auto", "cool", "dry", "fan"]  # no heat on this unit
    assert message["mode"] == "cool" and message["fan"] == "max" and message["swing"] == "both"
    assert message["target"] == 16.0 and message["indoor"] == 25.0
    assert message["has_eco"] and message["has_turbo"] and message["has_display"]
    assert "token" not in message and "key" not in message


def test_unlinked_and_offline_send_status_only(monkeypatch, tmp_path):
    assert ac.load_link() is None
    assert ACSession(on_change=lambda: None).message() == {"type": "ac", "status": "unlinked", "notice": "", "notice_id": 0,
                                                            "event": None, "event_id": 0}


def test_changes_are_checked():
    async def check():
        session = online_session()
        for bad in ({"target": 31}, {"target": 15}, {"target": True}, {"mode": "heat"}, {"mode": "boil"},
                    {"fan": "hurricane"}, {"swing": "spin"}, {"power": "yes"}, {"colour": "red"}, {}):
            with pytest.raises(ACError):
                session.change(bad)
        session._device.supports_turbo = False
        with pytest.raises(ACError):
            session.change({"turbo": True})
    asyncio.run(check())


def test_offline_refuses_changes():
    session = online_session()
    session.status = "offline"
    with pytest.raises(ACError):
        session.change({"power": False})


def test_latest_value_wins_and_shows_at_once():
    async def check():
        session = online_session()
        for degrees in range(17, 25):  # a slider drag
            session.change({"target": degrees})
        assert session.message()["target"] == 24.0  # shown before the AC answers
        await session._flusher
        return session._device
    device = asyncio.run(check())
    # The whole drag collapsed into one command with the last value.
    assert [target for target, _mode in device.applied] == [24.0]
    assert device.target_temperature == 24.0


def test_eco_uses_ieco_when_the_unit_has_it():
    async def check():
        session = online_session()
        session.change({"eco": True, "mode": "dry"})
        await session._flusher
        return session._device
    device = asyncio.run(check())
    assert device.ieco is True and device.eco is False and device.operational_mode == MODES["dry"]


def test_a_failed_send_marks_offline():
    async def check():
        device = FakeAC()

        async def broken():
            raise TimeoutError()

        device.apply = broken
        session = online_session(device)
        session.change({"power": False})
        await session._flusher
        return session.status
    assert asyncio.run(check()) == "offline"


def test_off_timer_turns_the_ac_off_on_a_fresh_reading():
    async def check():
        session = online_session()

        async def refresh():
            pass

        session._device.refresh = refresh
        with pytest.raises(ACError):
            session.set_off_timer(7)
        session.set_off_timer(60)
        assert session.message()["off_in"] == 60
        session._timer_fired()  # as if an hour passed
        assert session._device.power_state is True  # nothing sent before a fresh reading
        await session._poll_once()
        await session._flusher
        assert session.message()["off_in"] is None
        return session._device
    assert asyncio.run(check()).power_state is False


def test_timer_never_ends_a_clean():
    async def check():
        session = online_session()

        async def refresh():
            session._device.power_state, session._device.self_clean_active = False, True

        session._device.refresh = refresh
        session.set_off_timer(30)
        session._timer_fired()
        await session._poll_once()
        return session._device.applied, session._pending
    assert asyncio.run(check()) == ([], {})


def test_failed_change_is_kept_and_sent_later():
    async def check():
        device = FakeAC()
        real_apply = device.apply

        async def broken():
            raise TimeoutError()

        device.apply = broken
        session = online_session(device)
        session.change({"target": 22})
        await session._flusher
        assert session.status == "offline" and session._pending == {"target": 22.0}
        assert "try again" in session.message()["notice"]
        device.apply = real_apply

        async def refresh():
            pass

        device.refresh = refresh
        await session._poll_once()
        await session._flusher
        return device.target_temperature, session._pending
    assert asyncio.run(check()) == (22.0, {})


def test_a_clean_started_elsewhere_drops_queued_changes():
    async def check():
        device = FakeAC()
        session = online_session(device)
        session.change({"target": 20})
        device.self_clean_active = True  # started from the hand remote before the change went out
        await session._flusher
        return device.applied, session.message()["notice"]
    applied, notice = asyncio.run(check())
    assert applied == [] and "cleaning" in notice


def test_linking_while_running_is_picked_up(tmp_path, monkeypatch):
    async def check():
        session = ACSession(on_change=lambda: None, make_device=lambda **_: FakeAC())
        assert session.status == "unlinked"
        ac.save_link({"ip": "192.0.2.9", "port": 6444, "id": 1, "token": "aa", "key": "bb"})
        session.refresh_soon()
        status = session.status
        await session.close()
        return status
    assert asyncio.run(check()) == "connecting"


def test_cancel_timer():
    async def check():
        session = online_session()
        session.set_off_timer(30)
        session.set_off_timer(None)
        return session.message()["off_in"]
    assert asyncio.run(check()) is None


def test_cleaning_blocks_everything_but_power():
    async def check():
        device = FakeAC()
        device.power_state, device.self_clean_active = False, True
        session = online_session(device)
        assert session.message()["cleaning"] is True
        for change in ({"target": 20}, {"mode": "dry"}, {"power": True, "fan": "low"}):
            with pytest.raises(ACError, match="cleaning"):
                session.change(change)
        session.change({"power": True})  # a deliberate press of power still works
        await session._flusher
        return device.power_state
    assert asyncio.run(check()) is True


def test_save_link_is_private_and_whole(private_files):
    import os
    folder = private_files
    folder.mkdir(mode=0o755)
    link = {"ip": "192.0.2.9", "port": 6444, "id": 1, "token": "aa", "key": "bb"}
    ac.save_link(link)
    assert ac.load_link() == link
    assert oct(os.stat(folder).st_mode & 0o777) == "0o700"
    assert oct(os.stat(folder / "ac.json").st_mode & 0o777) == "0o600"
    assert [p.name for p in folder.iterdir()] == ["ac.json"]  # no temp file left behind


def test_effort_follows_the_compressor():
    async def check():
        session = online_session()
        dev = session._device
        session._top_hz = 80
        dev.compressor_frequency = 80
        working = session.message()["effort"]
        assert session.message()["phase"] == "working"
        dev.compressor_frequency = 0  # room reached, compressor resting
        holding = session.message()["effort"]
        assert session.message()["phase"] == "holding"
        dev.operational_mode, dev.fan_speed = MODES["fan"], FANS["low"]
        fan = session.message()["effort"]
        dev.power_state = False
        off = session.message()["effort"]
        return working, holding, fan, off
    assert asyncio.run(check()) == (1.0, 0.2, 0.45, 0.0)


def test_fault_and_filter_are_reported():
    async def check():
        session = online_session()
        session._device.error_code, session._device.filter_alert = 5, True
        m = session.message()
        return m["fault"], m["filter_due"]
    assert asyncio.run(check()) == (5, True)


def drying_session(tmp_path, monkeypatch):
    session = online_session()

    async def refresh():
        pass

    session._device.refresh = refresh
    session.set_setting("dry_coil", True)
    return session


def test_switching_off_after_cooling_dries_the_coil_first(tmp_path, monkeypatch):
    async def check():
        session = drying_session(tmp_path, monkeypatch)
        dev = session._device
        session.change({"power": False})
        await session._flusher
        assert dev.power_state is True and dev.operational_mode == MODES["fan"] and dev.fan_speed == FANS["low"]
        assert session.message()["drying_minutes_left"] == ac.DRY_MAX_MINUTES
        dev.indoor_coil_temperature = 24.5  # room 25: dry
        await session._poll_once()
        await session._flusher
        return dev, session.message()
    dev, message = asyncio.run(check())
    assert dev.power_state is False and dev.operational_mode == MODES["cool"]  # mode back for next time
    assert message["drying_minutes_left"] is None
    assert ac.load_settings()["dry_coil"] is True  # remembered


def test_power_while_drying_stops_at_once(tmp_path, monkeypatch):
    async def check():
        session = drying_session(tmp_path, monkeypatch)
        session.change({"power": False})
        await session._flusher
        session.change({"power": False})  # "Stop now"
        await session._flusher
        return session._device.power_state, session._drying
    assert asyncio.run(check()) == (False, None)


def test_off_from_the_hand_remote_is_left_alone(tmp_path, monkeypatch):
    async def check():
        session = drying_session(tmp_path, monkeypatch)
        session.change({"power": False})
        await session._flusher
        session._device.power_state = False  # switched off by hand meanwhile
        await session._poll_once()
        return session._drying, session._device.power_state, session._pending
    assert asyncio.run(check()) == (None, False, {})


def test_no_drying_when_off_or_not_asked(tmp_path, monkeypatch):
    async def check():
        session = online_session()  # drying not turned on
        session.change({"power": False})
        await session._flusher
        return session._device.power_state, session._drying
    assert asyncio.run(check()) == (False, None)


def test_bad_settings_are_refused(tmp_path, monkeypatch):
    session = drying_session(tmp_path, monkeypatch)
    for name, value in (("dry_coil", "yes"), ("rm", True)):
        with pytest.raises(ACError):
            session.set_setting(name, value)


def test_comfort_controls():
    async def check():
        session = online_session()
        session.change({"purifier": True, "breeze_away": True, "louver_v": "2", "fan_percent": 35})
        await session._flusher
        m = session.message()
        for bad in ({"fan_percent": 0}, {"fan_percent": 101}, {"fan_percent": "35"}, {"louver_v": "9"}, {"louver_h": 3}):
            with pytest.raises(ACError):
                session.change(bad)
        session._device.supports_purifier = False
        with pytest.raises(ACError):
            session.change({"purifier": False})
        return m
    m = asyncio.run(check())
    assert (m["purifier"], m["breeze_away"], m["louver_v"], m["fan_percent"]) == (True, True, "2", 35)
    assert online_session().message()["fan_percent"] is None  # "max" is not an exact speed


def outage_session(monkeypatch, restore=False):
    session = online_session()

    async def refresh():
        pass

    session._device.refresh = refresh
    session.settings["restore_after_outage"] = restore
    return session


async def go_through_outage(session, minutes, comes_back_on=False):
    await session._poll_once()  # seen running, settings remembered
    session._device.online = False
    await session._poll_once()
    session._unreachable_since -= minutes * 60  # as if that long passed with the Mac awake
    session._device.online, session._device.power_state = True, comes_back_on
    await session._poll_once()
    if session._flusher:
        await session._flusher


def test_power_cut_asks_before_switching_back_on(monkeypatch):
    async def check():
        session = outage_session(monkeypatch)
        await go_through_outage(session, 12)
        return session.message()["event"], session._device.power_state
    event, power = asyncio.run(check())
    assert event["kind"] == "power_back" and "12 min" in event["text"] and power is False


def test_power_cut_restores_when_chosen(monkeypatch):
    async def check():
        session = outage_session(monkeypatch, restore=True)
        session._device.target_temperature = 22.0
        await go_through_outage(session, 5)
        return session.message()["event"]["kind"], session._device.power_state, session._device.target_temperature
    assert asyncio.run(check()) == ("restored", True, 22.0)


def test_short_drop_or_still_on_is_not_a_power_cut(monkeypatch):
    async def check():
        short = outage_session(monkeypatch)
        await go_through_outage(short, 0.5)
        still_on = outage_session(monkeypatch)
        await go_through_outage(still_on, 30, comes_back_on=True)  # router restart: AC kept running
        return short.message()["event"], still_on.message()["event"]
    assert asyncio.run(check()) == (None, None)


def test_restore_needs_a_seen_running_state():
    session = online_session()
    with pytest.raises(ACError):
        session.restore()


def test_any_press_while_drying_puts_mode_and_fan_back(tmp_path, monkeypatch):
    async def check():
        session = drying_session(tmp_path, monkeypatch)
        dev = session._device
        dev.fan_speed = FANS["high"]
        session.change({"power": False})
        await session._flusher
        assert dev.operational_mode == MODES["fan"]
        session.change({"target": 18})  # the user takes over
        await session._flusher
        return dev, session._drying
    dev, drying = asyncio.run(check())
    assert drying is None and dev.operational_mode == MODES["cool"] and dev.fan_speed == FANS["high"]
    assert dev.target_temperature == 18.0 and dev.power_state is True


def test_a_refused_press_keeps_drying(tmp_path, monkeypatch):
    async def check():
        session = drying_session(tmp_path, monkeypatch)
        session.change({"power": False})
        await session._flusher
        with pytest.raises(ACError):
            session.change({"target": 99})
        return session._drying is not None
    assert asyncio.run(check())


def test_drying_puts_an_exact_fan_speed_back(tmp_path, monkeypatch):
    async def check():
        session = drying_session(tmp_path, monkeypatch)
        dev = session._device
        dev.fan_speed = 35  # an exact speed
        session.change({"power": False})
        await session._flusher
        dev.indoor_coil_temperature = 25.0
        await session._poll_once()
        await session._flusher
        return dev.fan_speed, dev.power_state
    assert asyncio.run(check()) == (35, False)


def test_timer_firing_while_drying_finishes_it(tmp_path, monkeypatch):
    async def check():
        session = drying_session(tmp_path, monkeypatch)
        dev = session._device
        session.change({"power": False})
        await session._flusher
        session._off_due = True
        await session._poll_once()
        await session._flusher
        return dev.power_state, dev.operational_mode, session._drying
    assert asyncio.run(check()) == (False, MODES["cool"], None)


def test_drying_times_out(tmp_path, monkeypatch):
    async def check():
        session = drying_session(tmp_path, monkeypatch)
        dev = session._device
        session.change({"power": False})
        await session._flusher
        dev.indoor_coil_temperature = None  # no coil reading: only the time limit can end it
        session._drying["since"] -= ac.DRY_MAX_MINUTES * 60
        await session._poll_once()
        await session._flusher
        return dev.power_state
    assert asyncio.run(check()) is False
