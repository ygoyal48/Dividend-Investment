# Dividend Investment

## Nifty 50 dividend yield screener

`nifty50_dividend_screener.py` logs into [Screener.in](https://www.screener.in)
with your credentials, pulls the current Nifty 50 constituent list live, and
reports every constituent whose dividend yield exceeds a threshold (2% by
default).

The constituent list is fetched live from several independent sources, tried
in order until one succeeds (no offline/hardcoded fallback):

1. niftyindices.com CSV (official)
2. NSE archives CSV (official)
3. Wikipedia (`/wiki/NIFTY_50`)
4. Wikipedia REST API

If every source fails, the run prints an error and exits non-zero rather than
using a stale list.

### Signals

Results are persisted in `Suggestions.md` as `Symbol | Signal`. Each run reads
the previous file, rebuilds the list, and emits one signal per stock (ordered
STRONG SELL, then Dividend Dropped, then BUY):

- **STRONG SELL** - was in the previous list but has been dropped from Nifty 50.
- **Dividend Dropped (DONT BUY, DONT SELL)** - still in Nifty 50, but yield fell
  below the threshold.
- **BUY** - currently in Nifty 50 with yield above the threshold.

Only BUY rows are carried forward as state; the file is overwritten each run.

### Setup

```bash
pip install -r requirements.txt
export SCREENER_LOGIN="you@example.com"
export SCREENER_PASS="your-screener-password"
```

### Usage

```bash
python nifty50_dividend_screener.py
python nifty50_dividend_screener.py --min-yield 3
```
