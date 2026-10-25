# shared fixtures. "now" is a Thursday afternoon so weekday tests are predictable.
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


@pytest.fixture
def tz():
    return ZoneInfo("America/Phoenix")


@pytest.fixture
def now(tz):
    return datetime(2026, 10, 22, 14, 0, tzinfo=tz)


@pytest.fixture
def tmp_store(tmp_path):
    from store import Store

    return Store(tmp_path / "state.json")
