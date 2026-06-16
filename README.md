# tour-check

Free, fully-automated watcher for a Google appointment-schedule page. Once a
day, GitHub Actions runs a headless-Chromium scraper, looks for days with open
appointments in the next 7 days, and pushes a phone notification via
[ntfy.sh](https://ntfy.sh) when it finds any. Nothing runs on your own machine.

## How it works

- **GitHub Actions** runs `check_slots.py` on a daily cron (and on demand).
- **Playwright (headless Chromium)** loads the JS-rendered booking page and
  reads the **calendar grid's accessibility labels**. Each day cell says either
  "…no available times" or "…N available times" — the same signal a human sees.
  We anchor dates off the cell marked "today" and report any day within the
  window whose label lacks "no available times".
- This was chosen over scraping obfuscated CSS classes (which rotate on
  Google's deploys) **and** over parsing the background availability RPC: when
  nothing is open, Google sends no real slot payload, so there's nothing
  dependable to parse. The aria-labels are present and meaningful in every
  state. Detection is **day-level** — the notification links you to the page to
  pick an exact time.
- The script reports open days within the next 7 days and **POSTs to a free
  ntfy.sh topic** that your phone subscribes to.
- The repo is **public**, so Actions minutes are free.

## One-time setup

1. **Create a public repo** and push these files (already done if you're
   reading this in the repo).
2. **Pick a hard-to-guess ntfy topic** — treat it like a password, since
   anyone who knows it can read your notifications. Example:
   `tour-check-3f9a2c7e1b`.
3. **Add it as a repo secret** named `NTFY_TOPIC`:
   repo → Settings → Secrets and variables → Actions → New repository secret.
4. **Subscribe on your phone**: install the ntfy app (iOS/Android), tap
   "Subscribe to topic", and enter the exact same topic string.
5. **Test it**: repo → Actions → "Check appointment slots" → "Run workflow".
   Watch the run log, and confirm a notification arrives (or that the log
   reports zero open days cleanly).

## Configuration

Set via repo secrets or by editing the workflow `env:` block:

| Var           | Required | Default            | Purpose                              |
|---------------|----------|--------------------|--------------------------------------|
| `NTFY_TOPIC`  | yes      | —                  | ntfy topic your phone subscribes to  |
| `BOOKING_URL` | no       | the target page    | override the appointment page        |
| `DAYS_AHEAD`  | no       | `7`                | how many days out to look            |
| `NTFY_SERVER` | no       | `https://ntfy.sh`  | self-hosted ntfy server base URL     |

The cron time lives in `.github/workflows/check.yml` (`0 13 * * *`, UTC).

## ⚠️ Known issues to be aware of

### 1. The "open" wording is inferred — confirm it on the first real opening
Detection was verified against the live page **while everything was full**: all
42 day cells read "no available times" and the script correctly reported zero
(see the `===== CALENDAR SCAN =====` block in the run log, which lists every
day cell and flags open ones with `OPEN`).

What hasn't been seen on the real page yet is the exact label text when a day
*does* have openings. The code assumes an open day's label contains
"available times" **without** the "no" prefix (e.g. "Thu Jun 18, 3 available
times") — a safe reading of the observed pattern, but unconfirmed. The first
time a day actually opens, check the CALENDAR SCAN log: the open day should
show the `OPEN` flag and you should get a notification. If a known-open day is
*not* flagged, adjust `CLOSED_MARKER` / `DAY_MARKER` at the top of
`check_slots.py` to match the real wording.

Note this is **day-level** detection by design (see "How it works"); it tells
you which days have openings, not the exact times — tap through to book.

### 2. GitHub disables scheduled workflows after 60 days of inactivity
If the repo sees **no commits/activity for 60 days**, GitHub automatically
**disables the scheduled trigger** (you'll get an email). The workflow won't
run until you re-enable it (Actions tab) or push a commit. This is expected
GitHub behavior, not a bug here — just push an occasional commit, or re-enable
when notified, to keep the daily check alive.
