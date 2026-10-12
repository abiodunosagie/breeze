"""Run hours, filter reminders and automatic self cleans."""

import asyncio
import json

import care
from care import Care
from helpers import Clock


def care_at(when, tmp_path, write=lambda path, data: None):
    clock = Clock(when)
    return Care(tmp_path / "care.json", write, clock), clock


def run_for(c, clock, minutes, **reading):
    """Readings every minute, as Breeze would take them while awake."""
    news = []
    for _ in range(minutes):
        clock.advance(1)
        news.append(c.record(**reading))
    return [n for n in news if n]


def test_only_wet_running_hours_count(tmp_path):
    c, clock = care_at("2026-10-12T10:00:00", tmp_path)
    c.record(power=True, wet=True, cleaning=False)  # the first reading only starts the count
    run_for(c, clock, 60, power=True, wet=True, cleaning=False)
    run_for(c, clock, 60, power=True, wet=False, cleaning=False)  # fan only
    run_for(c, clock, 60, power=False, wet=True, cleaning=False)  # off
    assert round(c.clean_hours, 2) == round(c.filter_hours, 2) == 1.0


def test_a_long_gap_counts_only_a_little(tmp_path):
    c, clock = care_at("2026-10-12T10:00:00", tmp_path)
    c.record(power=True, wet=True, cleaning=False)
    clock.advance(8 * 60)  # the Mac slept all night
    c.record(power=True, wet=True, cleaning=False)
    assert c.clean_hours == care.MAX_GAP_SECONDS / 3600


def test_filter_reminder_once_until_washed(tmp_path):
    c, clock = care_at("2026-10-12T10:00:00", tmp_path)
    c.filter_hours = care.FILTER_AFTER_HOURS - 0.01
    assert run_for(c, clock, 5, power=True, wet=True, cleaning=False) == ["filter_due"]
    assert run_for(c, clock, 5, power=True, wet=True, cleaning=False) == []
    c.filter_cleaned()
    assert c.filter_hours == 0 and not c.filter_wash_due


def test_clean_due_only_by_day_after_a_while_off(tmp_path):
    c, clock = care_at("2026-10-12T10:00:00", tmp_path)
    c.clean_hours = care.CLEAN_AFTER_HOURS
    c.record(power=False, wet=True, cleaning=False)
    assert not c.clean_due(True)  # just switched off
    run_for(c, clock, 11, power=False, wet=True, cleaning=False)
    assert c.clean_due(True)
    assert not c.clean_due(False)  # the user has not turned it on
    night, clock2 = care_at("2026-10-12T23:00:00", tmp_path)
    night.clean_hours = care.CLEAN_AFTER_HOURS
    run_for(night, clock2, 11, power=False, wet=True, cleaning=False)
    assert not night.clean_due(True)


def test_one_try_a_day(tmp_path):
    c, clock = care_at("2026-10-12T10:00:00", tmp_path)
    c.clean_hours = care.CLEAN_AFTER_HOURS
    run_for(c, clock, 11, power=False, wet=True, cleaning=False)
    c.trying_clean()
    run_for(c, clock, 120, power=False, wet=True, cleaning=False)
    assert not c.clean_due(True)  # it never began, but not again today
    clock.advance(22 * 60)  # tomorrow morning
    run_for(c, clock, 11, power=False, wet=True, cleaning=False)
    assert c.clean_due(True)


def test_off_time_counts_afresh_after_an_unseen_gap(tmp_path):
    c, clock = care_at("2026-10-12T08:00:00", tmp_path)
    c.clean_hours = care.CLEAN_AFTER_HOURS
    run_for(c, clock, 11, power=False, wet=True, cleaning=False)
    clock.advance(10 * 60)  # the Mac slept; the user may have used the AC meanwhile
    c.record(power=False, wet=True, cleaning=False)
    assert not c.clean_due(True)
    run_for(c, clock, 11, power=False, wet=True, cleaning=False)
    assert c.clean_due(True)


def test_finished_clean_resets_and_tells_only_when_breeze_started_it(tmp_path):
    c, clock = care_at("2026-10-12T10:00:00", tmp_path)
    c.clean_hours = 50
    c.asked_for_clean()
    assert run_for(c, clock, 25, power=False, wet=True, cleaning=True) == []
    assert run_for(c, clock, 1, power=False, wet=True, cleaning=False) == ["clean_done"]
    assert c.clean_hours == 0
    c.clean_hours = 50
    run_for(c, clock, 60, power=False, wet=True, cleaning=False)  # the old request is long gone
    run_for(c, clock, 25, power=False, wet=True, cleaning=True)  # from the hand remote
    assert run_for(c, clock, 1, power=False, wet=True, cleaning=False) == []
    assert c.clean_hours == 0


def test_a_clean_stopped_early_does_not_count(tmp_path):
    c, clock = care_at("2026-10-12T10:00:00", tmp_path)
    c.clean_hours = 50
    run_for(c, clock, 3, power=False, wet=True, cleaning=True)
    run_for(c, clock, 1, power=True, wet=True, cleaning=False)
    assert c.clean_hours > 49


def test_a_clean_that_ended_unseen_does_not_count(tmp_path):
    c, clock = care_at("2026-10-12T10:00:00", tmp_path)
    c.clean_hours = 50
    c.asked_for_clean()
    run_for(c, clock, 15, power=False, wet=True, cleaning=True)
    clock.advance(30)  # a power cut: no readings, then the AC answers again, off
    assert c.record(power=False, wet=True, cleaning=False) is None
    assert c.clean_hours == 50


def test_saved_and_loaded_and_bad_file(tmp_path):
    saved = {}
    c, clock = care_at("2026-10-12T10:00:00", tmp_path, write=lambda path, data: saved.update(data))
    c.filter_hours = 12.5
    c.save()
    (tmp_path / "care.json").write_text(json.dumps(saved))
    again, _ = care_at("2026-10-12T10:00:00", tmp_path)
    assert again.filter_hours == 12.5
    (tmp_path / "care.json").write_text('{"clean_hours": "lots", "filter_hours": -3, "filter_told": 1}')
    bad, _ = care_at("2026-10-12T10:00:00", tmp_path)
    assert bad.clean_hours == bad.filter_hours == 0 and bad.filter_told is False


def test_session_starts_a_clean_only_when_off_and_idle(tmp_path):
    from test_ac import online_session

    async def check():
        session = online_session()
        session.settings["auto_clean"] = True
        c, clock = care_at("2026-10-12T10:00:00", tmp_path)
        c.clean_hours = care.CLEAN_AFTER_HOURS
        session.care = c
        dev = session._device
        dev.power_state = False
        for _ in range(11):
            clock.advance(1)
            session._pending = {"target": 20.0}  # a change waiting: never start a clean
            session._after_fresh_reading()
            session._pending = {}
        session._flusher = None
        await asyncio.sleep(0.01)
        assert dev.cleans_started == 0
        clock.advance(1)
        session._after_fresh_reading()
        await asyncio.sleep(0.01)
        started = dev.cleans_started
        clock.advance(1)
        session._after_fresh_reading()  # asked already: no second request
        await asyncio.sleep(0.01)
        return started, dev.cleans_started
    assert asyncio.run(check()) == (1, 1)


def test_no_clean_if_the_ac_was_switched_on_since_the_last_reading(tmp_path):
    from test_ac import online_session

    async def check():
        session = online_session()
        dev = session._device
        dev.power_state = False

        async def switched_on_by_hand():
            dev.power_state = True
        dev.refresh = switched_on_by_hand
        await session._start_clean()
        return dev.cleans_started, session.care._asked_at
    assert asyncio.run(check()) == (0, None)


def test_a_busy_moment_does_not_use_up_the_days_try(tmp_path):
    from test_ac import online_session

    async def check():
        session = online_session()
        session._device.power_state = False
        session._pending = {"target": 20.0}  # queued just now
        await session._start_clean()
        return session.care._tried_on
    assert asyncio.run(check()) is None
