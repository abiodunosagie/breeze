"""Schedules: run once, a little late is fine, too late is skipped, and nothing fires on save."""

import json

import pytest

from test_care import Clock
from timetable import ScheduleError, Timetable, changes_for, check_entries

# 2026-10-12 is a Monday (weekday 0).
MORNING = {"id": "morning", "days": [0, 1, 2, 3, 4], "time": "06:30", "power": True, "target": 24, "mode": "cool"}
NIGHT_OFF = {"id": "night", "days": [0, 1, 2, 3, 4, 5, 6], "time": "23:00", "power": False}


def table_at(when, tmp_path, entries=(MORNING,)):
    clock = Clock(when)
    table = Timetable(tmp_path / "schedules.json", lambda path, data: (tmp_path / "schedules.json").write_text(
        json.dumps(data)), clock)
    table.replace(list(entries))
    return table, clock


def test_saving_never_fires_a_time_already_past(tmp_path):
    table, _ = table_at("2026-10-12T06:35:00", tmp_path)
    assert table.due() == ([], [])


def test_runs_once_and_a_little_late(tmp_path):
    table, clock = table_at("2026-10-12T05:00:00", tmp_path)
    assert table.due() == ([], [])
    clock.advance(60 + 30 + 10)  # 06:40, ten minutes late (the Mac woke up)
    run, missed = table.due()
    assert [e["id"] for e in run] == ["morning"] and missed == []
    assert table.due() == ([], [])


def test_too_late_is_skipped_and_told_once(tmp_path):
    table, clock = table_at("2026-10-12T05:00:00", tmp_path)
    clock.advance(90 + 20)  # 06:50
    run, missed = table.due()
    assert run == [] and [e["id"] for e in missed] == ["morning"]
    assert table.due() == ([], [])


def test_only_on_its_days(tmp_path):
    table, clock = table_at("2026-10-17T05:00:00", tmp_path)  # Saturday
    clock.advance(95)
    assert table.due() == ([], [])


def test_a_restart_does_not_run_it_again(tmp_path):
    table, clock = table_at("2026-10-12T06:00:00", tmp_path)
    clock.advance(35)
    assert len(table.due()[0]) == 1
    again = Timetable(tmp_path / "schedules.json", lambda path, data: None, clock)
    assert again.due() == ([], [])


def test_a_disabled_schedule_waits(tmp_path):
    table, clock = table_at("2026-10-12T06:00:00", tmp_path, [{**MORNING, "enabled": False}])
    clock.advance(35)
    assert table.due() == ([], [])


def test_what_each_schedule_asks():
    entries = check_entries([MORNING, NIGHT_OFF])
    assert changes_for(entries[0]) == {"power": True, "target": 24.0, "mode": "cool"}
    assert changes_for(entries[1]) == {"power": False}


@pytest.mark.parametrize("bad", [
    {**MORNING, "time": "6:30"}, {**MORNING, "time": "24:00"}, {**MORNING, "days": []},
    {**MORNING, "days": [0, 0]}, {**MORNING, "days": [7]}, {**MORNING, "id": "Bad Id"},
    {**MORNING, "power": "yes"}, {**MORNING, "target": 99}, {**MORNING, "mode": "<script>"},
    {**MORNING, "days": [True]}, "not a schedule",
])
def test_bad_schedules_are_refused(bad):
    with pytest.raises(ScheduleError):
        check_entries([bad])


def test_too_many_or_same_id_refused():
    with pytest.raises(ScheduleError):
        check_entries([{**MORNING, "id": f"s{i}"} for i in range(17)])
    with pytest.raises(ScheduleError):
        check_entries([MORNING, MORNING])


def test_a_bad_file_means_no_schedules(tmp_path):
    (tmp_path / "schedules.json").write_text('{"entries": [{"id": "x"}]}')
    table = Timetable(tmp_path / "schedules.json", lambda path, data: None, Clock("2026-10-12T06:00:00"))
    assert table.entries == []


def test_the_session_runs_a_schedule_and_reports_a_refusal(tmp_path):
    from test_ac import online_session
    session = online_session()
    clock = Clock("2026-10-12T06:00:00")
    session.timetable = Timetable(tmp_path / "s.json", lambda path, data: None, clock)
    session.timetable.replace([{**MORNING, "mode": "heat"}, {**MORNING, "id": "warm", "mode": None, "target": 26}])
    session._device.self_clean_active = False
    session._kick = lambda: None
    clock.advance(31)
    session._run_schedules()
    assert session._pending.get("target") == 26.0  # the good one went through
    assert "did not run" in session.notice  # the unit has no heat
