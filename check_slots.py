#!/usr/bin/env python3
"""Watch a Google appointment-schedule page for the next bookable date.

The target schedule is typically booked solid, so scanning only the current
week finds nothing. Instead we click Google's own **"Jump to the next bookable
date"** control, which searches forward and either lands the calendar on the
soonest opening or shows "No available times in the next year". We then read
the calendar grid's accessibility labels to find which day(s) are open, date
them against the displayed month/year header, and push a phone notification via
ntfy.sh when the soonest opening falls within the window.

Design notes:
- Detection uses **aria-labels** ("…no available times" / "…N available
  times") plus the month/year header — the same info a human sees — rather than
  Google's rotating CSS classes or a background RPC (which returns nothing when
  fully booked). Verified against the live page in its fully-booked state.
- **Fail-open**: if availability is detected but we cannot confidently parse a
  date (a layout we haven't seen), we notify anyway with the raw label, because
  missing a rare opening is worse than an extra notification.

Config via env vars:
    NTFY_TOPIC   (required)  ntfy.sh topic to POST notifications to
    BOOKING_URL  (optional)  override the appointment page
    DAYS_AHEAD   (optional)  window size in days (default 30)
    NTFY_SERVER  (optional)  ntfy server base URL (default https://ntfy.sh)

Exit codes: 0 on a successful run; non-zero only if the page failed to load or
no calendar day cells were found (so a broken run shows red in Actions).
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta

# `requests` and `playwright` are imported lazily inside the functions that use
# them so the pure parsing helpers stay importable/testable without a browser.

DEFAULT_URL = (
    "https://calendar.google.com/calendar/u/0/appointments/schedules/"
    "AcZssZ2G7NhnN1uaunypuOaF8ScIntvaClqZIMRjkSp8m5n3J_BgA4a3_w5Cvv-_O0-NRU_DrQLGgx9d"
)

# A day cell's aria-label ends with "<N> available times" or "no available
# times" (verified on the live page). These markers identify a day cell and
# tell open from closed.
DAY_MARKER = "available times"
CLOSED_MARKER = "no available times"
# Google renders this exact phrase (only after the jump) when the entire
# schedule is empty — a reliable "genuinely fully booked" signal.
EMPTY_PHRASE = "no available times in the next year"
JUMP_TEXT = "Jump to the next bookable date"

MONTHS = {
    m: i
    for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"],
        start=1,
    )
}
_MONTH_RX = re.compile(
    r"^(january|february|march|april|may|june|july|august|september|october"
    r"|november|december)\s+(20\d\d)$",
    re.I,
)


def log(msg: str) -> None:
    print(msg, flush=True)


def cell_date(label: str, disp_month: int, disp_year: int) -> date | None:
    """Date a day-cell aria-label using the displayed month/year as anchor.

    Spillover days carry an explicit month name ("July 1, ..."); days of the
    displayed month are bare ("16, Tuesday, ..."). Years roll over at Dec/Jan.
    """
    low = label.lower()
    m = re.match(r"\s*([a-z]+)\s+(\d{1,2})\b", low)
    if m and m.group(1) in MONTHS:
        month, day = MONTHS[m.group(1)], int(m.group(2))
    else:
        m2 = re.match(r"\s*(\d{1,2})\b", low)
        if not m2:
            return None
        month, day = disp_month, int(m2.group(1))
    year = disp_year
    if month <= disp_month - 6:      # e.g. Jan spillover while showing Dec
        year += 1
    elif month >= disp_month + 6:    # e.g. Dec spillover while showing Jan
        year -= 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_open_days(day_labels: list[str], disp_month: int, disp_year: int) -> list[dict]:
    """From ordered day-cell labels, return the open ones as {'date','label'}.

    Open = label has DAY_MARKER but not CLOSED_MARKER. Undatable cells get
    date=None and sort last (handled fail-open by the caller).
    """
    out: list[dict] = []
    for label in day_labels:
        low = label.lower()
        if DAY_MARKER not in low or CLOSED_MARKER in low:
            continue
        out.append({"date": cell_date(label, disp_month, disp_year), "label": label})
    out.sort(key=lambda s: (s["date"] is None, s["date"] or date.max))
    return out


def in_window(opens: list[dict], today: date, days_ahead: int) -> list[dict]:
    return [s for s in opens if s["date"] and 0 <= (s["date"] - today).days <= days_ahead]


def scrape(url: str) -> dict:
    """Load the page, click 'next bookable date', and read the result.

    Returns a dict: day_labels, disp_month, disp_year, globally_empty, debug.
    """
    from playwright.sync_api import sync_playwright

    debug: list[str] = []
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

        # Ask Google to jump to the soonest opening anywhere.
        jump = page.get_by_text(JUMP_TEXT, exact=False)
        if jump.count():
            try:
                jump.first.click(timeout=5000)
                debug.append("Clicked 'Jump to the next bookable date'.")
                page.wait_for_timeout(6000)
            except Exception as e:
                debug.append(f"Jump click failed ({e}); reading current view.")
        else:
            debug.append("Jump control not found; reading current view.")

        body_text = ""
        try:
            body_text = page.locator("body").inner_text().lower()
        except Exception:
            pass
        globally_empty = EMPTY_PHRASE in body_text

        # Displayed month/year header (anchors bare-number day cells).
        disp_month, disp_year = None, None
        loc = page.get_by_text(_MONTH_RX)
        if loc.count():
            mm = _MONTH_RX.match(loc.first.inner_text().strip())
            if mm:
                disp_month, disp_year = MONTHS[mm.group(1).lower()], int(mm.group(2))

        day_labels = []
        for h in page.locator("button, div[role='button'], [role='gridcell']").element_handles():
            al = (h.get_attribute("aria-label") or "").strip()
            if DAY_MARKER in al.lower():
                day_labels.append(al)

        browser.close()

    return {
        "day_labels": day_labels,
        "disp_month": disp_month,
        "disp_year": disp_year,
        "globally_empty": globally_empty,
        "debug": "\n".join(debug),
    }


def notify(topic: str, server: str, title: str, body: str, url: str) -> None:
    import requests

    endpoint = f"{server.rstrip('/')}/{topic}"
    resp = requests.post(
        endpoint,
        data=(body + f"\n\nBook: {url}").encode("utf-8"),
        headers={
            "Title": title,
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
    days_ahead = int(os.environ.get("DAYS_AHEAD", "30"))
    today = date.today()

    try:
        r = scrape(url)
    except Exception as e:
        log(f"ERROR: failed to load/scrape page: {e}")
        return 1

    if r["debug"]:
        log(r["debug"])

    labels = r["day_labels"]
    if not labels:
        log("ERROR: found 0 calendar day cells — page layout may have changed.")
        return 1

    dm, dy = r["disp_month"], r["disp_year"]
    log(f"Displayed month: {dm}/{dy}  |  {len(labels)} day cell(s) scanned.")

    opens = parse_open_days(labels, dm or today.month, dy or today.year) if dm else \
        [{"date": None, "label": l} for l in labels if CLOSED_MARKER not in l.lower()]

    log(f"===== CALENDAR SCAN ({len(labels)} day cells) =====")
    for l in labels:
        flag = "OPEN " if CLOSED_MARKER not in l.lower() else "     "
        log(f"  {flag}{l}")
    log("===== END CALENDAR SCAN =====")

    if r["globally_empty"] and not opens:
        log("Page shows 'No available times in the next year' - fully booked. No notification.")
        return 0

    within = in_window(opens, today, days_ahead)
    datable = [s for s in opens if s["date"]]

    if within:
        lines = "\n".join("• " + s["date"].strftime("%a %b %d") for s in within)
        notify(topic, server, f"{len(within)} open appointment day(s)",
               "Open appointment day(s) within the window:\n" + lines, url)
    elif datable:
        # Availability exists, but the soonest is beyond the window (respect it).
        soonest = datable[0]["date"]
        log(f"Next available is {soonest:%a %b %d} - beyond {days_ahead}-day window. "
            "No notification.")
    elif opens:
        # Openings detected but undatable (unfamiliar layout): fail open.
        raw = "\n".join("• " + s["label"] for s in opens[:10])
        notify(topic, server, "Possible appointment opening (verify)",
               "Availability detected but the date couldn't be parsed — check the "
               "page:\n" + raw, url)
    else:
        log("No open days detected in the current view. No notification.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
