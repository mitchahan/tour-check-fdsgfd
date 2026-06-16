#!/usr/bin/env python3
"""Check a Google appointment-schedule page for open slots in the next 7 days.

Loads the JS-rendered booking page with headless Chromium (Playwright),
scrapes the available time-slot buttons, keeps only those within the next
7 days, and pushes a phone notification via ntfy.sh when any are found.

Designed to run unattended on GitHub Actions. Configuration comes from
environment variables:

    NTFY_TOPIC   (required)  the ntfy.sh topic to POST notifications to
    BOOKING_URL  (optional)  override the default appointment page
    DAYS_AHEAD   (optional)  how many days out to look (default 7)
    NTFY_SERVER  (optional)  ntfy server base URL (default https://ntfy.sh)

Exit codes: always 0 on a successful run (slots found or not). Non-zero
only if the page failed to load / scrape so the Actions run shows red.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests
from playwright.sync_api import sync_playwright

DEFAULT_URL = (
    "https://calendar.google.com/calendar/u/0/appointments/schedules/"
    "AcZssZ2G7NhnN1uaunypuOaF8ScIntvaClqZIMRjkSp8m5n3J_BgA4a3_w5Cvv-_O0-NRU_DrQLGgx9d"
)

# ---------------------------------------------------------------------------
# !! KNOWN ISSUE !!  The selectors below are *guesses* against Google's
# obfuscated markup. After the first real run, open the GitHub Actions log,
# read the "DOM DUMP" section this script prints, and correct these to match
# the actual rendered DOM. See README.md "Fixing the selectors".
# ---------------------------------------------------------------------------

# Candidate selectors for clickable available-slot buttons, tried in order.
SLOT_SELECTORS = [
    "button[data-slot-time]",
    "button[jsname][aria-label*=':']",
    "div[role='button'][data-datetime]",
    "[data-time-slot]",
    "button[aria-label*='AM'], button[aria-label*='PM']",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_slot_datetime(raw: str) -> datetime | None:
    """Best-effort parse of a slot label/attribute into an aware datetime.

    Google exposes slot times in a few shapes depending on the widget; we try
    the common ones. Returns None if nothing parses (caller decides what to do).
    """
    raw = raw.strip()
    if not raw:
        return None

    # 1) ISO-8601 (e.g. data-datetime="2026-06-18T14:30:00-07:00")
    iso = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    # 2) Unix epoch milliseconds (common in data-* attributes)
    if re.fullmatch(r"\d{10,13}", raw):
        ts = int(raw)
        if len(raw) >= 13:
            ts //= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    # 3) Human label like "Thu, Jun 18, 2:30 PM" or "June 18, 2026 2:30 PM"
    for fmt in (
        "%a, %b %d, %I:%M %p",
        "%A, %B %d, %Y %I:%M %p",
        "%B %d, %Y %I:%M %p",
        "%b %d, %Y, %I:%M %p",
        "%Y-%m-%d %H:%M",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.year == 1900:  # format had no year -> assume current/next
                now = datetime.now()
                dt = dt.replace(year=now.year)
                if dt < now - timedelta(days=1):
                    dt = dt.replace(year=now.year + 1)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def scrape_slots(url: str) -> tuple[list[dict], str]:
    """Return (slots, dom_dump). Each slot is {'label', 'raw', 'dt'}.

    dom_dump is a trimmed snapshot of candidate elements, printed to the log
    so selectors can be corrected after the first run.
    """
    slots: list[dict] = []
    dom_dump_parts: list[str] = []

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
        # Give the booking widget time to hydrate.
        page.wait_for_timeout(5000)

        # Try to surface any "next available" / load buttons that reveal slots.
        for sel in SLOT_SELECTORS:
            try:
                count = page.locator(sel).count()
            except Exception:
                count = 0
            if count:
                log(f"Selector matched {count} element(s): {sel}")
                handles = page.locator(sel).element_handles()
                for h in handles:
                    label = (h.get_attribute("aria-label") or h.inner_text() or "").strip()
                    raw = (
                        h.get_attribute("data-datetime")
                        or h.get_attribute("data-slot-time")
                        or h.get_attribute("data-time-slot")
                        or label
                    )
                    slots.append({"label": label, "raw": raw, "dt": parse_slot_datetime(raw)})
                if slots:
                    break  # first selector that produced slots wins

        # Always capture a DOM snapshot of likely-relevant nodes for debugging.
        dom_dump_parts.append("===== DOM DUMP (for fixing selectors) =====")
        try:
            buttons = page.locator("button, div[role='button']").element_handles()[:60]
            for b in buttons:
                al = (b.get_attribute("aria-label") or "").strip()
                txt = (b.inner_text() or "").strip().replace("\n", " ")[:60]
                jn = b.get_attribute("jsname") or ""
                if al or txt:
                    dom_dump_parts.append(f"  jsname={jn!r} aria={al!r} text={txt!r}")
        except Exception as e:  # pragma: no cover - debugging aid only
            dom_dump_parts.append(f"  (dom dump failed: {e})")
        dom_dump_parts.append("===== END DOM DUMP =====")

        browser.close()

    return slots, "\n".join(dom_dump_parts)


def filter_upcoming(slots: list[dict], days_ahead: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days_ahead)
    upcoming = []
    for s in slots:
        dt = s["dt"]
        if dt is None:
            # Unparseable time but a real slot button -> include it so we don't
            # silently miss openings; the notification shows the raw label.
            upcoming.append(s)
            continue
        if now - timedelta(hours=1) <= dt <= horizon:
            upcoming.append(s)
    return upcoming


def notify(topic: str, server: str, slots: list[dict], url: str) -> None:
    lines = []
    for s in slots[:20]:
        if s["dt"] is not None:
            lines.append("• " + s["dt"].strftime("%a %b %d, %I:%M %p"))
        elif s["label"]:
            lines.append("• " + s["label"])
        else:
            lines.append("• (open slot)")
    body = "Open appointment slots found:\n" + "\n".join(lines) + f"\n\nBook: {url}"

    endpoint = f"{server.rstrip('/')}/{topic}"
    resp = requests.post(
        endpoint,
        data=body.encode("utf-8"),
        headers={
            "Title": f"{len(slots)} appointment slot(s) open",
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

    try:
        slots, dom_dump = scrape_slots(url)
    except Exception as e:
        log(f"ERROR: failed to load/scrape page: {e}")
        return 1

    log(dom_dump)
    log(f"Scraped {len(slots)} raw slot candidate(s).")

    upcoming = filter_upcoming(slots, days_ahead)
    log(f"{len(upcoming)} slot(s) within the next {days_ahead} days.")

    if upcoming:
        notify(topic, server, upcoming, url)
    else:
        log("No open slots in window; no notification sent.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
