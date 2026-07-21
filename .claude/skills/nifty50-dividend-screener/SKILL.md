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
- **For Slack delivery (optional but preferred)** the script posts the report
  through a bot so it actually notifies the user (see "Delivering the report
  over Slack" below). Set these environment variables:
  - `SLACK_BOT_TOKEN` — a bot user OAuth token (`xoxb-...`) from a Slack app the
    user created with the `chat:write` scope.
  - `SLACK_CHANNEL_ID` — `C0BJB2WBB7Z` (the private `#dividend-reports`).
  - `SLACK_MENTION_USER_ID` — `U0BJL1X5KS7` (the user, @-mentioned at the top).

  The bot must be **invited to the channel** (`/invite @<botname>`), otherwise a
  private channel is invisible to it and `chat.postMessage` returns
  `channel_not_found`. Newly-added environment variables only take effect in a
  **fresh session** — a container already running when they were added won't see
  them.

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

## Delivering the report over Slack

The report is posted to the user's private `#dividend-reports` channel so it
lands somewhere durable and actually pings them.

**Who posts matters.** Slack never notifies you about a message you posted
yourself — including a self-@mention. The Slack MCP tools here are authenticated
as the *user*, so anything sent with `slack_send_message` goes out under the
user's own name and will **not** notify them, no matter the mention. Getting a
real ping requires a *different* identity (a bot) to post and mention the user.

**Preferred path — the script posts as a bot.** The screener itself posts the
report when these environment variables are set (see the `post_to_slack`
function in `nifty50_dividend_screener.py`):

- `SLACK_BOT_TOKEN` — a bot user OAuth token (`xoxb-...`) for a Slack app the
  user created; the bot must be invited to the channel.
- `SLACK_CHANNEL_ID` — `C0BJB2WBB7Z` (the private `#dividend-reports`).
- `SLACK_MENTION_USER_ID` — `U0BJL1X5KS7` (the user, @-mentioned at the top).

When the run prints `Report posted to Slack.`, the bot already delivered it —
**do not** also post via `slack_send_message`, or the user gets a duplicate (and
the duplicate from their own account is the one that doesn't notify anyway). Just
show the table in chat.

If the run instead prints `WARNING: Slack post failed: channel_not_found`, the
token is valid but the **bot isn't a member of the private channel** — tell the
user to invite it (`/invite @<botname>` in `#dividend-reports`), then re-run.
`invalid_auth`/`token_revoked` means the `SLACK_BOT_TOKEN` is wrong or rotated;
`not_in_channel` also means invite the bot.

**Fallback when the bot isn't configured.** If the run doesn't print
`Report posted to Slack.` (bot env vars unset), you may still post with
`slack_send_message` to `C0BJB2WBB7Z` with the `<@U0BJL1X5KS7>` mention so the
report at least lands in the channel — but tell the user plainly it won't notify
them until the bot token is set up, and point them at the `SLACK_BOT_TOKEN`
setup above. Use the same Symbol | Signal table with a short header and the
"X of 50 qualify / what changed" summary; lead with any STRONG SELL or Dividend
Dropped rows.

If the channel can't be found (different workspace, deleted channel), don't
silently fall back to a self-DM — it won't notify. Recreate it with
`slack_create_conversation(channel_name="dividend-reports", is_private=True)` or
ask the user where to post.

## Persisting the update

The script has already overwritten `Suggestions.md` by the time it finishes —
that's the persisted list. If you're working in the repo and the user expects
the change tracked, stage and commit it (`git add Suggestions.md`), matching
however the surrounding session handles commits and pushes. Don't commit
credentials or environment values.
