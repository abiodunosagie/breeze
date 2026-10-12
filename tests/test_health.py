"""The room-to-coil gap over weeks: learning, a drop told once, recovery."""

import json

from health import SAMPLES_FOR_A_DAY, SETTLE_SECONDS, Health
from test_care import Clock


def health_at(when, tmp_path):
    clock = Clock(when)
    return Health(tmp_path / "health.json", lambda path, data: None, clock), clock


def cool_day(h, clock, gap, samples=SAMPLES_FOR_A_DAY):
    """Switch on, settle, then a run of hard cooling readings with this gap; then the next morning."""
    news = [h.record(power=True, hard_cooling=True, room=26.0, coil=26.0 - gap)]
    clock.advance(SETTLE_SECONDS / 60)
    for _ in range(samples):
        clock.advance(1 / 3)
        news.append(h.record(power=True, hard_cooling=True, room=26.0, coil=26.0 - gap))
    h.record(power=False, hard_cooling=False, room=None, coil=None)
    clock.advance(24 * 60 - SETTLE_SECONDS / 60 - samples / 3)
    return [n for n in news if n]


def test_nothing_counts_while_settling_resting_or_unknown(tmp_path):
    h, clock = health_at("2026-10-12T10:00:00", tmp_path)
    for _ in range(10):  # the first minutes after switching on
        clock.advance(1 / 3)
        h.record(power=True, hard_cooling=True, room=26.0, coil=14.0)
    clock.advance(SETTLE_SECONDS / 60)
    h.record(power=True, hard_cooling=False, room=26.0, coil=20.0)  # resting
    h.record(power=True, hard_cooling=True, room=None, coil=14.0)
    assert h.summary()["health"]["gap"] is None
    h.record(power=True, hard_cooling=True, room=26.0, coil=14.0)
    assert h.summary()["health"]["gap"] == 12.0


def test_learning_then_good(tmp_path):
    h, clock = health_at("2026-10-01T10:00:00", tmp_path)
    for _ in range(6):
        cool_day(h, clock, 12)
    assert h.summary()["health"]["state"] == "learning"
    cool_day(h, clock, 12)
    cool_day(h, clock, 11.5)
    s = h.summary()["health"]
    assert s["state"] == "good" and s["usual"] == 12.0 and s["recent"] == 11.5


def test_a_short_day_does_not_count(tmp_path):
    h, clock = health_at("2026-10-01T10:00:00", tmp_path)
    for _ in range(7):
        cool_day(h, clock, 12, samples=SAMPLES_FOR_A_DAY - 5)
    assert h.summary()["health"]["state"] == "learning"


def test_a_drop_is_told_once_and_recovery_rearms(tmp_path):
    h, clock = health_at("2026-10-01T10:00:00", tmp_path)
    for _ in range(7):
        cool_day(h, clock, 12)
    news = []
    for _ in range(7):
        news += cool_day(h, clock, 7)
    assert news == ["low"] and h.summary()["health"]["state"] == "low"
    assert "Check the filter first" in h.message_for_low()
    for _ in range(7):
        news += cool_day(h, clock, 12)
    assert h.summary()["health"]["state"] == "good"
    for _ in range(7):
        news += cool_day(h, clock, 6)
    assert news == ["low", "low"]


def test_a_bad_file_is_ignored(tmp_path):
    (tmp_path / "health.json").write_text(json.dumps({"days": {"x": [1, 2], "2026-10-01": [0, 5], "2026-10-02": "a"},
                                                     "told": "yes"}))
    h, _ = health_at("2026-10-12T10:00:00", tmp_path)
    assert h._days == {} and h.told is False
