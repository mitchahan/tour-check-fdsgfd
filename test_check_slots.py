"""Unit tests for the slot-parsing logic in check_slots.py.

These cover extract_epoch_slots (the network-data path) without needing a
browser or network access. Run with: python -m pytest -q
"""

from datetime import datetime, timedelta, timezone

from check_slots import extract_epoch_slots


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


NOW = datetime.now(timezone.utc)


def test_keeps_timestamps_inside_window():
    soon = ms(NOW + timedelta(days=2))
    later = ms(NOW + timedelta(days=5))
    body = f'[[null,{soon}],[null,{later}]]'
    assert extract_epoch_slots(body, max_days=7) == {soon, later}


def test_drops_timestamps_beyond_horizon():
    far = ms(NOW + timedelta(days=120))
    body = f"[{far}]"
    assert extract_epoch_slots(body, max_days=90) == set()


def test_drops_well_past_timestamps():
    old = ms(NOW - timedelta(days=3))
    body = f"[{old}]"
    assert extract_epoch_slots(body, max_days=7) == set()


def test_tolerates_slight_tz_skew():
    # A slot a couple hours "in the past" by UTC clock should still survive the
    # 6-hour tolerance, covering timezone skew between us and Google's server.
    skewed = ms(NOW - timedelta(hours=2))
    assert extract_epoch_slots(f"[{skewed}]", max_days=7) == {skewed}


def test_ignores_non_13_digit_numbers():
    # 10-digit epoch-seconds and short ids must not be treated as slots.
    epoch_seconds = str(int((NOW + timedelta(days=1)).timestamp()))  # 10 digits
    body = f'[42, 1000, {epoch_seconds}, "AcZssZ2G7"]'
    assert extract_epoch_slots(body, max_days=7) == set()


def test_dedupes_repeated_timestamps():
    t = ms(NOW + timedelta(days=1))
    body = f"[{t},{t},{t}]"
    assert extract_epoch_slots(body, max_days=7) == {t}


def test_empty_body():
    assert extract_epoch_slots("", max_days=7) == set()


if __name__ == "__main__":
    # Allows running without pytest: `python test_check_slots.py`
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(1 if failures else 0)
