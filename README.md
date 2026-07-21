# Dividend Investment

## Nifty 50 dividend yield screener

`nifty50_dividend_screener.py` logs into [Screener.in](https://www.screener.in)
with your credentials, pulls the current Nifty 50 constituent list from the
official NSE Indices CSV, and reports every constituent whose dividend yield
exceeds a threshold (2% by default).

Results are persisted in `Suggestions.md`. Each run reads the existing file
before overwriting it, calls out (in bold) any stock that was in the previous
list but no longer clears the threshold, then replaces the file with the new
suggestions.

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
