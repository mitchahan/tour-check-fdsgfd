"""Unit tests for the day-availability parsing in check_slots.py.

These use the real aria-label formats observed on the live page and need no
browser or network. Run with: python test_check_slots.py  (or pytest -q)
"""

from datetime import date

from check_slots import find_open_days, parse_label_date

TODAY = date(2026, 6, 16)  # a Tuesday, matching the live-page snapshot


def labels(*pairs):
    """Build day-cell labels. Each pair is (text, open?)."""
    out = []
    for text, is_open in pairs:
        suffix = "3 available times" if is_open else "no available times"
        out.append(f"{text}, {suffix}")
    return out


def test_all_closed_returns_nothing():
    # Mirrors the live page today: every day says "no available times".
    lbls = labels(
        ("16, Tuesday, today", False),
        ("17, Wednesday", False),
        ("18, Thursday", False),
    )
    assert find_open_days(lbls, TODAY, 7) == []


def test_open_day_inside_window_is_found():
    lbls = labels(
        ("16, Tuesday, today", False),
        ("17, Wednesday", False),
        ("18, Thursday", True),
    )
    out = find_open_days(lbls, TODAY, 7)
    assert [s["date"] for s in out] == [date(2026, 6, 18)]


def test_open_day_outside_window_ignored():
    # 'today' at index 0; an open day 10 positions out is beyond a 7-day window.
    lbls = labels(("16, Tuesday, today", False)) + labels(
        *[(f"{17 + i}, X", i == 9) for i in range(10)]
    )
    assert find_open_days(lbls, TODAY, 7) == []


def test_anchors_by_today_position_not_label_number():
    # Even with bare day numbers, position relative to 'today' drives the date.
    lbls = labels(
        ("16, Tuesday, today", False),
        ("17, Wednesday", True),
    )
    out = find_open_days(lbls, TODAY, 7)
    assert out[0]["date"] == date(2026, 6, 17)


def test_non_day_cells_ignored():
    lbls = ["Next month", "Previous day"] + labels(("18, Thursday", True))
    # No 'today' cell here -> falls back to parse_label_date for the real cell.
    out = find_open_days(lbls, TODAY, 7)
    assert [s["date"] for s in out] == [date(2026, 6, 18)]


def test_parse_label_date_named_month():
    assert parse_label_date("July 1, Wednesday, no available times", TODAY) == date(2026, 7, 1)


def test_parse_label_date_bare_day_uses_current_month():
    assert parse_label_date("18, Thursday, 3 available times", TODAY) == date(2026, 6, 18)


def test_parse_label_date_dec_to_jan_rollover():
    dec = date(2026, 12, 30)
    assert parse_label_date("January 2, Friday, no available times", dec) == date(2027, 1, 2)


if __name__ == "__main__":
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
