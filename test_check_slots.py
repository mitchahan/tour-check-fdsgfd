"""Unit tests for the date/availability parsing in check_slots.py.

Uses the real aria-label and month-header formats observed on the live page;
no browser or network needed. Run: python test_check_slots.py  (or pytest -q)
"""

from datetime import date

from check_slots import cell_date, parse_open_days, in_window

TODAY = date(2026, 6, 16)  # Tuesday, matching the live snapshot


def labels(*pairs):
    """Build day-cell labels from (text, open?) pairs."""
    return [
        f"{t}, {'3 available times' if o else 'no available times'}" for t, o in pairs
    ]


# ---- cell_date: dating a label against the displayed month/year ----

def test_cell_date_bare_day_uses_displayed_month():
    assert cell_date("16, Tuesday, no available times", 6, 2026) == date(2026, 6, 16)


def test_cell_date_named_spillover_month():
    assert cell_date("July 1, Wednesday, no available times", 6, 2026) == date(2026, 7, 1)


def test_cell_date_future_month_view():
    # After the jump navigates to August, bare days belong to August.
    assert cell_date("14, Thursday, 2 available times", 8, 2026) == date(2026, 8, 14)


def test_cell_date_dec_jan_rollover():
    # Showing December 2026, a "January 2" spillover cell is 2027.
    assert cell_date("January 2, Friday, no available times", 12, 2026) == date(2027, 1, 2)


def test_cell_date_unparseable():
    assert cell_date("Next month", 6, 2026) is None


# ---- parse_open_days: pick out the open cells ----

def test_parse_open_days_all_closed():
    lbls = labels(("16, Tuesday", False), ("17, Wednesday", False))
    assert parse_open_days(lbls, 6, 2026) == []


def test_parse_open_days_finds_open_sorted():
    lbls = labels(("20, Saturday", True), ("18, Thursday", True), ("17, Wed", False))
    out = parse_open_days(lbls, 6, 2026)
    assert [s["date"] for s in out] == [date(2026, 6, 18), date(2026, 6, 20)]


def test_parse_open_days_undatable_open_kept_last():
    # An open cell we can't date still surfaces (fail-open), sorted to the end.
    lbls = ["mystery layout, 1 available times"] + labels(("18, Thursday", True))
    out = parse_open_days(lbls, 6, 2026)
    assert out[0]["date"] == date(2026, 6, 18)
    assert out[1]["date"] is None


# ---- in_window: the configurable horizon ----

def test_in_window_includes_and_excludes():
    opens = [
        {"date": date(2026, 6, 20), "label": "x"},   # 4 days  -> in
        {"date": date(2026, 7, 20), "label": "y"},   # 34 days -> out (30)
        {"date": None, "label": "z"},                # undatable -> out here
    ]
    got = in_window(opens, TODAY, 30)
    assert [s["date"] for s in got] == [date(2026, 6, 20)]


def test_in_window_excludes_past():
    opens = [{"date": date(2026, 6, 10), "label": "x"}]  # before today
    assert in_window(opens, TODAY, 30) == []


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
