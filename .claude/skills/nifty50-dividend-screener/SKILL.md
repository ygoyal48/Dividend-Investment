---
name: nifty50-dividend-screener
description: >-
  Screen the Nifty 50 for high-dividend-yield stocks and produce BUY / STRONG
  SELL / Dividend Dropped signals, persisted in the repo's Suggestions.md. Use
  this whenever the user asks for Nifty 50 dividend stocks, a dividend-yield
  screen, which index stocks pay dividends above some threshold, or wants the
  dividend suggestions list refreshed or re-run — even if they don't name the
  script or the file. Also trigger when they ask what changed since the last
  screen, or which suggested stocks got dropped or downgraded.
---

# Nifty 50 Dividend Yield Screener

This skill refreshes the dividend-yield screen for the Nifty 50 and turns the
result into an actionable, diff-aware report. All the real work lives in
`nifty50_dividend_screener.py` at the repository root — this skill's job is to
run it correctly and communicate the outcome well.

## What the script does (so you can explain it)

On each run it:

1. Reads the previous `Suggestions.md` (the last set of BUY stocks) from the
   repo root.
2. Fetches the **live** Nifty 50 constituent list, trying several independent
   sources in order (niftyindices CSV → NSE archives CSV → Wikipedia →
   Wikipedia REST API). There is no offline fallback; if every source fails it
   errors out rather than using a stale list.
3. Logs into Screener.in and reads each constituent's dividend yield.
4. Compares the new above-threshold set against the previous one and assigns a
   signal to every stock in the report.
5. Overwrites `Suggestions.md` with the new report (only BUY rows are carried
   forward as state for the next run's diff).

## Signals

The report is `Symbol | Signal`, ordered **STRONG SELL → Dividend Dropped →
BUY**:

- **STRONG SELL** — was a BUY last time but has been *dropped from the Nifty 50
  index entirely*. It's no longer an index constituent, so exit it.
- **Dividend Dropped (DONT BUY, DONT SELL)** — still in the Nifty 50, but its
  yield fell below the threshold. Hold what you have; don't add, don't sell.
- **BUY** — currently in the Nifty 50 with yield above the threshold.

The STRONG SELL vs Dividend Dropped distinction is the whole point of the diff:
a missing stock is only a sell if it left the index; if it's still in the index
and merely yields less, that's a hold, not a sell.

## Prerequisites

- `SCREENER_LOGIN` and `SCREENER_PASS` environment variables must be set to the
  user's Screener.in credentials. If they're missing, the script exits with a
  clear message — tell the user to set them rather than trying to work around it.
- Dependencies: `pip install -r requirements.txt` (just `requests`).
- **For phone push via ntfy** the script sends the report as a push
  notification through [ntfy](https://ntfy.sh) when `NTFY_TOPIC` is set (see the
  `post_to_ntfy` function and "Delivering the report over ntfy" below). The user
  installs the ntfy app and subscribes to the same topic; no account or token is
  needed on ntfy.sh.
  - `NTFY_TOPIC` — the topic to publish to. **Anyone who knows the topic can read
    it**, so use a long, unguessable value (treat like a secret).
  - `NTFY_SERVER` — optional, defaults to `https://ntfy.sh`.
  - `NTFY_TOKEN` — optional bearer token for a protected/self-hosted server.

  Newly-added environment variables only take effect in a **fresh session** — a
  container already running when they were added won't see them.

## Running it

From the repository root:

```bash
python nifty50_dividend_screener.py
```

The threshold defaults to 2%. To screen at a different yield, pass `--min-yield`:

```bash
python nifty50_dividend_screener.py --min-yield 3
```

The run takes roughly half a minute (it visits every constituent on
Screener.in). Run it once and use its output — don't loop it to "verify."

## Reporting back to the user

Present the results as a clean table of Symbol + Signal in the same order the
script prints (STRONG SELL first, then Dividend Dropped, then BUY). When there
are any STRONG SELL or Dividend Dropped rows, call them out prominently in
**bold** and say plainly what changed since the last run — that delta is
usually what the user cares about most.

If the script printed an `ERROR:` line (e.g. all constituent sources were
blocked, or login failed), report that honestly instead of inventing results.

## Delivering the report over ntfy

The report is delivered to the user's phone as an [ntfy](https://ntfy.sh) push
notification, so it actually pings them. A push from ntfy comes from the ntfy
service (not the user's own account), so there's no self-notification problem to
work around.

**The script sends it.** When `NTFY_TOPIC` is set, the screener publishes the
report itself (see `post_to_ntfy` in `nifty50_dividend_screener.py`) and prints
`Push notification sent via ntfy.` on success. You don't post anything yourself —
just show the full Symbol | Signal table in chat as described above.

The push is a concise summary, not the full table: the qualifying count and the
BUY list, with any STRONG SELL / Dividend Dropped symbols led first and the
notification bumped to high priority so actionable changes stand out.

If the run prints `WARNING: could not send ntfy notification: ...`, the publish
failed (network/proxy blocked, or a bad `NTFY_SERVER`/`NTFY_TOKEN`) — report it
honestly; the report was still written to `Suggestions.md`. If the run prints
nothing about ntfy, `NTFY_TOPIC` isn't set (e.g. an already-running session that
predates the variable) — tell the user to set it and re-run from a fresh session,
or pass it inline for a one-off:

```bash
NTFY_TOPIC='<the-topic>' python nifty50_dividend_screener.py
```

Reminder on the topic: it acts as a password (there's no auth on ntfy.sh), so
keep it long and unguessable, and never commit it or other environment values.

## Persisting the update

The script has already overwritten `Suggestions.md` by the time it finishes —
that's the persisted list. If you're working in the repo and the user expects
the change tracked, stage and commit it (`git add Suggestions.md`), matching
however the surrounding session handles commits and pushes. Don't commit
credentials or environment values.
