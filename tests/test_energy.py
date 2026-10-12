"""Energy from the AC's running total: days, hours, resets, gaps and bad files."""

from datetime import datetime

from energy import EnergyLog


class Clock:
    def __init__(self, when):
        self.now = datetime.fromisoformat(when).timestamp()

    def __call__(self):
        return self.now

    def advance(self, minutes):
        self.now += minutes * 60


def log_at(when, tmp_path, write=lambda path, data: None):
    clock = Clock(when)
    return EnergyLog(tmp_path / "energy.json", write, clock), clock


def test_today_and_this_month(tmp_path):
    log, clock = log_at("2026-10-12T18:00:00", tmp_path)
    log.record(256.0, 225)
    clock.advance(50)
    log.record(256.2, 224)
    s = log.summary()
    assert (s["today_kwh"], s["month_kwh"], s["power_w"]) == (0.2, 0.2, 224)


def test_a_new_day_starts_where_the_last_ended(tmp_path):
    log, clock = log_at("2026-10-12T23:50:00", tmp_path)
    log.record(256.0, 300)
    clock.advance(30)  # past midnight, one reading missed meanwhile
    log.record(256.5, 300)
    s = log.summary()
    assert s["today_kwh"] == 0.5 and s["month_kwh"] == 0.5


def test_a_reset_counter_starts_afresh(tmp_path):
    log, clock = log_at("2026-10-12T10:00:00", tmp_path)
    log.record(256.0, 200)
    clock.advance(10)
    log.record(0.1, 200)  # the unit's counter went back to zero
    assert log.summary()["today_kwh"] >= 0


def test_hourly_bars_cover_the_last_day(tmp_path):
    log, clock = log_at("2026-10-12T10:05:00", tmp_path)
    log.record(100.0, 200)
    clock.advance(30)
    log.record(100.3, 200)
    bars = log.summary()["hourly_kwh"]
    assert len(bars) == 24 and bars[-1] == 0.3 and sum(bars) == 0.3


def test_bad_file_and_bad_readings_are_ignored(tmp_path):
    (tmp_path / "energy.json").write_text('{"days": {"x": ["a", 1]}, "hours": 5}')
    log, _ = log_at("2026-10-12T10:00:00", tmp_path)
    log.record(None, None)
    log.record(-1, -5)
    assert log.summary() == {"power_w": None, "today_kwh": 0.0, "month_kwh": 0.0, "hourly_kwh": [0.0] * 24}


def test_saved_and_read_back(tmp_path):
    import json
    written = {}
    log, clock = log_at("2026-10-12T10:00:00", tmp_path, write=lambda path, data: written.update(data))
    log.record(10.0, 100)
    clock.advance(10)
    log.record(10.4, 100)
    log.save()
    (tmp_path / "energy.json").write_text(json.dumps(written))
    again, _ = log_at("2026-10-12T10:20:00", tmp_path)
    assert again.summary()["today_kwh"] == 0.4
