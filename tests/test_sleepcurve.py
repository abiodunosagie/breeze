"""Breeze's sleep curve: steps, the ceiling, stopping, and surviving a restart."""

import asyncio
import json

import pytest

import ac
from ac import ACError
from sleepcurve import SleepCurve
from test_ac import online_session
from helpers import Clock


def curve_at(when, tmp_path):
    clock = Clock(when)
    path = tmp_path / "sleep.json"
    return SleepCurve(path, lambda p, data: path.write_text(json.dumps(data)), clock), clock


def test_steps_up_then_holds_then_ends(tmp_path):
    curve, clock = curve_at("2026-10-12T23:00:00", tmp_path)
    curve.start(24.0, 420, "restore")
    assert curve.wanted(30) == 24.0
    clock.advance(61)
    assert curve.wanted(30) == 25.0
    clock.advance(60)
    assert curve.wanted(30) == 26.0
    clock.advance(200)
    assert curve.wanted(30) == 26.0 and not curve.finished()
    assert curve.summary()["ends_at"] == "06:00"
    clock.advance(100)
    assert curve.finished()


def test_never_above_the_unit_ceiling(tmp_path):
    curve, clock = curve_at("2026-10-12T23:00:00", tmp_path)
    curve.start(29.5, 360, "restore")
    clock.advance(130)
    assert curve.wanted(30) == 30


def test_survives_a_restart_and_drops_an_old_one(tmp_path):
    curve, clock = curve_at("2026-10-12T23:00:00", tmp_path)
    curve.start(24.0, 360, "off")
    clock.advance(90)
    again = SleepCurve(tmp_path / "sleep.json", lambda p, d: None, clock)
    assert again.active and again.wanted(30) == 25.0
    clock.advance(400)
    assert not SleepCurve(tmp_path / "sleep.json", lambda p, d: None, clock).active


def session_with_curve(tmp_path):
    session = online_session()
    session._kick = lambda: None
    curve, clock = curve_at("2026-10-12T23:00:00", tmp_path)
    session.curve = curve
    return session, clock


def test_session_refuses_beside_the_units_own_sleep(tmp_path):
    session, _ = session_with_curve(tmp_path)
    session._device.sleep = True
    with pytest.raises(ACError):
        session.start_sleep_curve(420)
    session._device.sleep = False
    with pytest.raises(ACError):
        session.start_sleep_curve(45)  # not one of the lengths


def test_session_raises_the_setting_and_restores_in_the_morning(tmp_path):
    async def check():
        session, clock = session_with_curve(tmp_path)
        session.start_sleep_curve(360)
        clock.advance(61)
        session._follow_curve(session._device)
        raised = session._pending.pop("target")
        session._device.target_temperature = raised  # sent
        clock.advance(300)
        session._follow_curve(session._device)
        return raised, session._pending.get("target"), session.curve.active
    assert asyncio.run(check()) == (17.0, 16.0, False)


def test_session_switches_off_in_the_morning_when_asked(tmp_path):
    async def check():
        session, clock = session_with_curve(tmp_path)
        session.settings["sleep_curve_end"] = "off"
        session.start_sleep_curve(360)
        clock.advance(361)
        session._follow_curve(session._device)
        return session._pending.get("power")
    assert asyncio.run(check()) is False


@pytest.mark.parametrize("takeover", [{"target": 20.0}, {"mode": "dry"}, {"sleep": True}, {"power": False}])
def test_the_user_taking_over_stops_it(tmp_path, takeover):
    async def check():
        session, _ = session_with_curve(tmp_path)
        session.start_sleep_curve(420)
        session.change(takeover)
        return session.curve.active
    assert asyncio.run(check()) is False


def test_a_refused_change_leaves_it_running(tmp_path):
    async def check():
        session, _ = session_with_curve(tmp_path)
        session.start_sleep_curve(420)
        with pytest.raises(ACError):
            session.change({"target": 99})
        return session.curve.active
    assert asyncio.run(check()) is True


def test_turned_off_by_the_remote_stops_it(tmp_path):
    session, _ = session_with_curve(tmp_path)
    session.start_sleep_curve(420)
    session._device.power_state = False
    session._follow_curve(session._device)
    assert not session.curve.active


def test_an_end_seen_hours_late_is_skipped(tmp_path):
    async def check():
        session, clock = session_with_curve(tmp_path)
        session.settings["sleep_curve_end"] = "off"
        session.start_sleep_curve(360)
        clock.advance(61)
        session._follow_curve(session._device)
        session._device.target_temperature = session._pending.pop("target")  # sent
        clock.advance(300 + 60)  # the Mac slept through the end
        session._follow_curve(session._device)
        return session._pending, session.curve.active, session.notice
    pending, active, notice = asyncio.run(check())
    assert pending == {} and not active and "left as it was" in notice


def test_the_off_timer_ends_the_curve_too(tmp_path):
    async def check():
        session, _ = session_with_curve(tmp_path)
        session.start_sleep_curve(420)
        session._turn_off()
        return session.curve.active, "target" in session._pending
    assert asyncio.run(check()) == (False, False)


def test_a_new_length_keeps_the_starting_point(tmp_path):
    session, clock = session_with_curve(tmp_path)
    session.start_sleep_curve(420)
    clock.advance(121)
    session._device.target_temperature = 18.0  # raised by the curve
    session.start_sleep_curve(540)
    assert session.curve.state["start_target"] == 16.0


def test_a_change_on_the_hand_remote_stops_it(tmp_path):
    session, _ = session_with_curve(tmp_path)
    session.start_sleep_curve(420)
    session._device.target_temperature = 22.0  # from the hand remote
    session._follow_curve(session._device)
    assert not session.curve.active and "target" not in session._pending


def test_leaving_cooling_on_the_remote_stops_it(tmp_path):
    session, _ = session_with_curve(tmp_path)
    session.start_sleep_curve(420)
    session._device.operational_mode = ac.MODES["fan"]
    session._follow_curve(session._device)
    assert not session.curve.active


def test_power_back_after_a_cut_keeps_the_curve(tmp_path):
    async def check():
        session, clock = session_with_curve(tmp_path)
        session.start_sleep_curve(420)
        session._remember_running()
        session.restore()
        return session.curve.active, "target" in session._pending, session._pending.get("power")
    assert asyncio.run(check()) == (True, False, True)
