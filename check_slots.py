#!/usr/bin/env python3
"""Check a Google appointment-schedule page for open days in the next 7 days.

Loads the JS-rendered booking page with headless Chromium (Playwright) and
reads the calendar grid. Each day cell carries an accessibility label that
says either "...no available times" or "...available times"; we use that
signal (it mirrors exactly what a human sees) to decide which days within the
window are bookable, and push a phone notification via ntfy.sh when any are.

Why day-level, not exact time slots: Google only emits a real per-slot
availability payload once a day with openings is selected, so there is nothing
reliable to scrape when everything is full. The day-cell aria-labels are
present and meaningful in every state, which makes them the dependable signal.
When a day is open, the notification links you straight to the page to pick a
time.

Designed to run unattended on GitHub Actions. Configuration via env vars:

    NTFY_TOPIC   (required)  the ntfy.sh topic to POST notifications to
    BOOKING_URL  (optional)  override the default appointment page
    DAYS_AHEAD   (optional)  how many days out to look (default 7)
    NTFY_SERVER  (optional)  ntfy server base URL (default https://ntfy.sh)

Exit codes: 0 on a successful run (open days found or not). Non-zero only if
the page failed to load / no day cells were found, so the Actions run shows red.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta

# Note: `requests` and `playwright` are imported lazily inside the functions
# that use them (notify / scrape_open_days) so the pure parsing helpers can be
# imported and unit-tested without a browser or those deps installed.

DEFAULT_URL = (
    "https://calendar.google.com/calendar/u/0/appointments/schedules/"
    "AcZssZ2G7NhnN1uaunypuOaF8ScIntvaClqZIMRjkSp8m5n3J_BgA4a3_w5Cvv-_O0-NRU_DrQLGgx9d"
)

# A day cell's aria-label always ends with "<N> available times" or
# "no available times" (verified against the live page). These two markers are
# how we tell a calendar day apart from nav buttons and whether it's open.
DAY_MARKER = "available times"
CLOSED_MARKER = "no available times"

MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ],
        start=1,
    )
}


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_label_date(label: str, today: date) -> date | None:
    """Parse a calendar day-cell aria-label into a date (fallback path).

    Handles both "July 1, Wednesday, no available times" (month named) and
    "16, Tuesday, today, no available times" (current month, bare day number).
    Used only when the 'today' cell can't be located to anchor by position.
    """
    low = label.lower()
    # "Month D, ..."  -> month is named explicitly
    m = re.match(r"\s*([a-z]+)\s+(\d{1,2})\b", low)
    if m and m.group(1) in MONTHS:
        month, day = MONTHS[m.group(1)], int(m.group(2))
        year = today.year
        # Calendar shows a few months around 'now'; pick the year that puts
        # this month nearest today (handles a Dec->Jan rollover).
        candidate = date(year, month, day)
        if (candidate - today).days < -180:
            candidate = date(year + 1, month, day)
        return candidate
    # "D, ..." -> bare day number, assume the current month being viewed
    m = re.match(r"\s*(\d{1,2})\b", low)
    if m:
        day = int(m.group(1))
        try:
            return date(today.year, today.month, day)
        except ValueError:
            return None
    return None


def find_open_days(day_labels: list[str], today: date, days_ahead: int) -> list[dict]:
    """Given the ordered calendar day-cell aria-labels, return open days in window.

    Anchors dates off the cell flagged "today" and counts by position (robust to
    locale and missing month names); falls back to parsing labels if no 'today'
    cell is present. A day is "open" when its label lacks the CLOSED_MARKER.
    Returns [{'date': date, 'label': str}, ...] sorted by date.
    """
    today_idx = next((i for i, l in enumerate(day_labels) if "today" in l.lower()), None)

    out: list[dict] = []
    for i, label in enumerate(day_labels):
        low = label.lower()
        if DAY_MARKER not in low:
            continue  # not a day cell
        if today_idx is not None:
            d = today + timedelta(days=i - today_idx)
        else:
            d = parse_label_date(label, today)
            if d is None:
                continue
        delta = (d - today).days
        if 0 <= delta <= days_ahead and CLOSED_MARKER not in low:
            out.append({"date": d, "label": label})
    out.sort(key=lambda s: s["date"])
    return out


def scrape_open_days(url: str, today: date, days_ahead: int) -> tuple[list[dict], int, str]:
    """Load the page and return (open_days, total_day_cells, debug_text)."""
    from playwright.sync_api import sync_playwright

    debug: list[str] = []
    day_labels: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        )
        log(f"Loading {url}")
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(6000)

        handles = page.locator("button, div[role='button'], [role='gridcell']").element_handles()
        for h in handles:
            al = (h.get_attribute("aria-label") or "").strip()
            if DAY_MARKER in al.lower():
                day_labels.append(al)

        browser.close()

    open_days = find_open_days(day_labels, today, days_ahead)

    debug.append(f"===== CALENDAR SCAN ({len(day_labels)} day cells) =====")
    for label in day_labels:
        flag = "OPEN " if CLOSED_MARKER not in label.lower() else "     "
        debug.append(f"  {flag}{label}")
    debug.append("===== END CALENDAR SCAN =====")

    return open_days, len(day_labels), "\n".join(debug)


def notify(topic: str, server: str, open_days: list[dict], url: str) -> None:
    import requests

    lines = ["• " + s["date"].strftime("%a %b %d") for s in open_days]
    body = "Open appointment day(s) found:\n" + "\n".join(lines) + f"\n\nBook: {url}"

    endpoint = f"{server.rstrip('/')}/{topic}"
    resp = requests.post(
        endpoint,
        data=body.encode("utf-8"),
        headers={
            "Title": f"{len(open_days)} day(s) with open appointments",
            "Priority": "high",
            "Tags": "calendar,bell",
            "Click": url,
        },
        timeout=30,
    )
    resp.raise_for_status()
    log(f"Pushed notification to {endpoint} (HTTP {resp.status_code})")


def main() -> int:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        log("ERROR: NTFY_TOPIC environment variable is not set.")
        return 2

    url = os.environ.get("BOOKING_URL", DEFAULT_URL)
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
    days_ahead = int(os.environ.get("DAYS_AHEAD", "7"))
    today = date.today()

    try:
        open_days, total_cells, debug = scrape_open_days(url, today, days_ahead)
    except Exception as e:
        log(f"ERROR: failed to load/scrape page: {e}")
        return 1

    log(debug)

    if total_cells == 0:
        # No day cells at all means the calendar didn't render / markup changed.
        log("ERROR: found 0 calendar day cells — page layout may have changed.")
        return 1

    log(f"{len(open_days)} open day(s) within the next {days_ahead} days.")
    if open_days:
        notify(topic, server, open_days, url)
    else:
        log("No open days in window; no notification sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
