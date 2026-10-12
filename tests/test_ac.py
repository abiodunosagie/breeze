"""The air conditioner session: what the Mac app sees, what it may change, and the change queue."""

import asyncio

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
        self.online = True
        self.min_target_temperature, self.max_target_temperature = 16.0, 30.0
        self.supported_operation_modes = [MODES["fan"], MODES["dry"], MODES["cool"], MODES["auto"]]
        self.supported_fan_speeds = list(FANS.values())
        self.supported_swing_modes = list(SWINGS.values())
        self.supports_eco, self.supports_ieco = False, True
        self.supports_turbo = self.supports_display_control = self.supports_flash = True
        self.applied = []

    async def authenticate(self, token, key):
        pass

    async def get_capabilities(self):
        pass

    async def apply(self):
        await asyncio.sleep(0)
        self.applied.append((self.target_temperature, self.operational_mode))


def online_session(device=None):
    session = ACSession(on_change=lambda: None)
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
    monkeypatch.setattr(ac, "AC_FILE", tmp_path / "missing.json")
    assert ac.load_link() is None
    assert ACSession(on_change=lambda: None).message() == {"type": "ac", "status": "unlinked", "notice": "", "notice_id": 0}


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
        monkeypatch.setattr(ac, "AC_FILE", tmp_path / "ac.json")
        monkeypatch.setattr(ac, "CONFIG_DIR", tmp_path)
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


def test_save_link_is_private_and_whole(tmp_path, monkeypatch):
    import os
    folder = tmp_path / "breeze"
    folder.mkdir(mode=0o755)
    monkeypatch.setattr(ac, "CONFIG_DIR", folder)
    monkeypatch.setattr(ac, "AC_FILE", folder / "ac.json")
    link = {"ip": "192.0.2.9", "port": 6444, "id": 1, "token": "aa", "key": "bb"}
    ac.save_link(link)
    assert ac.load_link() == link
    assert oct(os.stat(folder).st_mode & 0o777) == "0o700"
    assert oct(os.stat(folder / "ac.json").st_mode & 0o777) == "0o600"
    assert [p.name for p in folder.iterdir()] == ["ac.json"]  # no temp file left behind
