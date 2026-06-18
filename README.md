# tour-check

Free, fully-automated watcher for a Google appointment-schedule page. Once a
day, GitHub Actions clicks Google's "next bookable date" control, and if the
soonest opening falls within a configurable window (default 30 days) it pushes
a phone notification via [ntfy.sh](https://ntfy.sh). Nothing runs on your own
machine.

## How it works

- **GitHub Actions** runs `check_slots.py` on a daily cron (and on demand).
- **Playwright (headless Chromium)** loads the booking page and clicks
  **"Jump to the next bookable date"**. The target schedule is usually booked
  solid, so scanning just the current week finds nothing; the jump makes Google
  search forward and either land the calendar on the soonest opening or render
  "No available times in the next year".
- It then reads the **calendar grid's accessibility labels** ("…no available
  times" / "…N available times") and dates each open day against the displayed
  **month/year header**. This signal mirrors what a human sees and was chosen
  over Google's rotating CSS classes **and** over the background availability
  RPC (which returns nothing when fully booked).
- If the soonest opening is within `DAYS_AHEAD`, it **POSTs to a free ntfy.sh
  topic** your phone subscribes to. Detection is **day-level** — the
  notification links you straight to the page to pick a time.
- **Fail-open:** if an opening is detected but its date can't be parsed (a
  layout not yet seen), it notifies anyway with the raw label — missing a rare
  opening is worse than an extra ping.
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
| `DAYS_AHEAD`  | no       | `30`               | notify only if soonest opening is within N days |
| `NTFY_SERVER` | no       | `https://ntfy.sh`  | self-hosted ntfy server base URL     |

The cron time lives in `.github/workflows/check.yml` (`0 13 * * *`, UTC).

## ⚠️ Known issues to be aware of

### 1. Detection is verified in BOTH states, but stays day-level
Detection has now been confirmed against the live page both fully booked and
with real openings:
- **Fully booked:** the jump control renders "No available times in the next
  year" and every day cell reads "…no available times" → no notification.
- **Open:** open day cells carry *no* availability suffix at all — just
  "8, Wednesday" or "August 4, Tuesday" — while closed cells end with ", no
  available times". The script identifies a day cell by its "<day>, <weekday>"
  shape and treats the absence of "no available times" as open. (Confirmed: it
  correctly flagged July 8 + Aug 4–7 and notified for the one inside the
  window.)

Remaining safety net: if an opening is detected but its date can't be parsed
(an unfamiliar layout), the script **fails open** with a "Possible appointment
opening (verify)" notification carrying the raw label. The `===== CALENDAR
SCAN =====` block in every run log shows exactly what was seen, flagging open
days with `OPEN`.

Note this is **day-level** detection by design (see "How it works") — it tells
you which day has openings, not the exact times; tap through to book.

### 2. GitHub disables scheduled workflows after 60 days of inactivity
If the repo sees **no commits/activity for 60 days**, GitHub automatically
**disables the scheduled trigger** (you'll get an email). The workflow won't
run until you re-enable it (Actions tab) or push a commit. This is expected
GitHub behavior, not a bug here — just push an occasional commit, or re-enable
when notified, to keep the daily check alive.
