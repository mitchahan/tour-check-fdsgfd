# tour-check

Free, fully-automated watcher for a Google appointment-schedule page. Once a
day, GitHub Actions runs a headless-Chromium scraper, looks for open slots in
the next 7 days, and pushes a phone notification via [ntfy.sh](https://ntfy.sh)
when it finds any. Nothing runs on your own machine.

## How it works

- **GitHub Actions** runs `check_slots.py` on a daily cron (and on demand).
- **Playwright (headless Chromium)** loads the JS-rendered booking page and
  **intercepts the availability RPC** the widget fetches in the background.
  Slot times come back as structured epoch-millisecond timestamps, which is
  far more stable than scraping the obfuscated DOM. (DOM scraping is kept only
  as a fallback if no usable network response is captured.)
- The script keeps slots within the next 7 days and **POSTs to a free
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
   reports zero slots cleanly).

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

### 1. Verify the captured timestamps once after the first run
The script prefers structured data: it intercepts the calendar availability
RPC and pulls out 13-digit epoch-ms timestamps that fall in a future window
(`extract_epoch_slots` in `check_slots.py`). This keys off a **stable data
contract** rather than rotating CSS class/`jsname` hashes, so it shouldn't
break on Google's routine UI redeploys.

There is still one sanity-check to do on the first run:
1. Run the workflow once (manually).
2. Open the run log and find **`===== CAPTURED CALENDAR RESPONSES =====`**.
   - If it lists endpoints with a sensible epoch count, you're done — the
     count should roughly match the open slots actually shown on the page.
   - If it says **(none)**, the script fell back to DOM scraping and printed a
     **`===== DOM DUMP =====`**; tighten the matching there, or narrow the URL
     filter / epoch heuristic in `scrape_slots` to the real RPC you see logged.
3. Commit and re-run.

Once the captured endpoint is confirmed, no per-deploy selector maintenance is
expected — unlike pure DOM scraping.

### 2. GitHub disables scheduled workflows after 60 days of inactivity
If the repo sees **no commits/activity for 60 days**, GitHub automatically
**disables the scheduled trigger** (you'll get an email). The workflow won't
run until you re-enable it (Actions tab) or push a commit. This is expected
GitHub behavior, not a bug here — just push an occasional commit, or re-enable
when notified, to keep the daily check alive.
