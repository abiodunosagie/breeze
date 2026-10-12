"""Shared by the tests: a clock the test moves by hand."""

from datetime import datetime


class Clock:
    def __init__(self, when):
        self.now = datetime.fromisoformat(when).timestamp()

    def __call__(self):
        return self.now

    def advance(self, minutes):
        self.now += minutes * 60
