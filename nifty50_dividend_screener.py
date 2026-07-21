"""Screen Nifty 50 constituents for dividend yield using Screener.in.

Requires SCREENER_LOGIN and SCREENER_PASS environment variables set to
valid screener.in credentials.
"""
import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape

import requests

LOGIN_URL = "https://www.screener.in/login/"
_HERE = os.path.dirname(os.path.abspath(__file__))
SUGGESTIONS_PATH = os.path.join(_HERE, "Suggestions.md")

# A full nifty 50 has 50 constituents; reject a source that returns far fewer,
# which usually means a garbled download or a partial parse.
MIN_CONSTITUENTS = 45

# Some sources sit behind a WAF that blocks bare user-agents; use browser headers.
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-50",
    "Accept": "text/csv,text/html,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def login(session, username, password):
    r = session.get(LOGIN_URL, timeout=15)
    r.raise_for_status()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text).group(1)
    resp = session.post(
        LOGIN_URL,
        data={"csrfmiddlewaretoken": token, "username": username, "password": password},
        headers={"Referer": LOGIN_URL},
        timeout=15,
    )
    if "Logout" not in resp.text:
        raise RuntimeError("Screener.in login failed - check SCREENER_LOGIN/SCREENER_PASS")


def _parse_constituents_csv(text):
    """Parse the official NSE-format CSV (Company Name, Industry, Symbol, ...)."""
    rows = list(csv.DictReader(text.splitlines()))
    return [(row["Company Name"].strip(), row["Symbol"].strip()) for row in rows]


def _parse_wikipedia_table(html):
    """Parse the '#constituents' wikitable (columns: Company name, Symbol, ...)."""
    i = html.find('id="constituents"')
    if i == -1:
        raise ValueError("constituents table not found in page")
    segment = html[i:]
    end = segment.find("</table>")
    if end != -1:
        segment = segment[:end]
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", segment, re.DOTALL):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
        if len(cells) < 2:
            continue
        company = unescape(re.sub(r"<[^>]+>", "", cells[0])).strip()
        symbol = unescape(re.sub(r"<[^>]+>", "", cells[1])).strip()
        if re.fullmatch(r"[A-Z0-9&.\-]{1,20}", symbol):
            out.append((company, symbol))
    return out


def _source_csv(url):
    def fetch(session):
        resp = session.get(url, headers=BROWSER_HEADERS, timeout=20)
        resp.raise_for_status()
        return _parse_constituents_csv(resp.text)
    return fetch


def _source_wikipedia(url):
    def fetch(session):
        resp = session.get(url, headers=BROWSER_HEADERS, timeout=20)
        resp.raise_for_status()
        return _parse_wikipedia_table(resp.text)
    return fetch


# Ordered list of independent live sources. Each is tried in turn; the first
# that returns a plausible constituent list wins. There is no offline fallback.
NIFTY50_SOURCES = [
    ("niftyindices.com CSV",
     _source_csv("https://niftyindices.com/IndexConstituent/ind_nifty50list.csv")),
    ("NSE archives CSV",
     _source_csv("https://archives.nseindia.com/content/indices/ind_nifty50list.csv")),
    ("Wikipedia",
     _source_wikipedia("https://en.wikipedia.org/wiki/NIFTY_50")),
    ("Wikipedia REST API",
     _source_wikipedia("https://en.wikipedia.org/api/rest_v1/page/html/NIFTY_50")),
]


def fetch_nifty50_constituents(session):
    """Fetch the live Nifty 50 constituent list, trying each source in order.

    Raises RuntimeError (which the CLI reports as an error) if every source
    fails - there is no offline/hardcoded fallback.
    """
    errors = []
    for name, fetch in NIFTY50_SOURCES:
        try:
            constituents = fetch(session)
            if len(constituents) < MIN_CONSTITUENTS:
                raise ValueError(f"only {len(constituents)} constituents parsed")
            print(f"Fetched Nifty 50 constituents from {name} ({len(constituents)} stocks).")
            return constituents
        except Exception as exc:  # noqa: BLE001 - any failure should fall through
            errors.append(f"{name}: {exc}")

    detail = "; ".join(errors)
    raise RuntimeError(f"All Nifty 50 constituent sources failed -> {detail}")


def fetch_dividend_yield(session, symbol, retries=2):
    for attempt in range(retries):
        for suffix in ("consolidated/", ""):
            url = f"https://www.screener.in/company/{symbol}/{suffix}"
            try:
                resp = session.get(url, timeout=15)
            except requests.RequestException:
                continue
            if resp.status_code != 200:
                continue
            idx = resp.text.find("Dividend Yield")
            if idx == -1:
                continue
            m = re.search(r'class="number">([\d.]+)<', resp.text[idx:idx + 300])
            if m:
                return float(m.group(1))
    return None


BUY = "BUY"
STRONG_SELL = "STRONG SELL"
DIVIDEND_DROPPED = "Dividend Dropped (DONT BUY, DONT SELL)"

# STRONG SELL first, then Dividend Dropped, then BUY.
SIGNAL_ORDER = {STRONG_SELL: 0, DIVIDEND_DROPPED: 1, BUY: 2}


def parse_previous_buys(path):
    """Return the set of symbols that were marked BUY by a prior run.

    Only BUY rows are carried forward as state; STRONG SELL / Dividend Dropped
    rows are one-time signals relative to the previous run and are not re-diffed.
    """
    if not os.path.exists(path):
        return set()
    previous = set()
    row_re = re.compile(r'^\|\s*([A-Z0-9&.\-]+)\s*\|\s*([^|]+?)\s*\|\s*$')
    with open(path) as f:
        for line in f:
            m = row_re.match(line.strip())
            if m and m.group(2).strip() == BUY:
                previous.add(m.group(1))
    return previous


def write_suggestions(path, rows, min_yield, generated_at):
    """Overwrite the suggestions file with the latest report (old list is discarded).

    `rows` is a list of (symbol, signal) tuples already ordered for the report.
    """
    lines = [
        f"# Nifty 50 Dividend Yield Suggestions (> {min_yield}%)",
        "",
        f"_Generated: {generated_at}_",
        "",
        "| Symbol | Signal |",
        "|---|---|",
    ]
    for symbol, signal in rows:
        lines.append(f"| {symbol} | {signal} |")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-yield", type=float, default=2.0,
                         help="Minimum dividend yield percent to include (default: 2.0)")
    args = parser.parse_args()

    username = os.environ.get("SCREENER_LOGIN")
    password = os.environ.get("SCREENER_PASS")
    if not username or not password:
        sys.exit("SCREENER_LOGIN / SCREENER_PASS environment variables are not set")

    previous_buys = parse_previous_buys(SUGGESTIONS_PATH)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    login(session, username, password)

    constituents = fetch_nifty50_constituents(session)
    current_nifty50 = {symbol for _, symbol in constituents}

    results = []
    for name, symbol in constituents:
        yield_pct = fetch_dividend_yield(session, symbol)
        results.append((name, symbol, yield_pct))
        time.sleep(0.4)

    matches = [r for r in results if r[2] is not None and r[2] > args.min_yield]
    matches.sort(key=lambda r: r[2], reverse=True)
    new_buys = {symbol for _, symbol, _ in matches}

    # Build the report rows: (symbol, signal).
    rows = []
    # Removals: stock was BUY last time but no longer qualifies.
    for symbol in sorted(previous_buys - new_buys):
        if symbol in current_nifty50:
            # Still in the index, so the dividend yield simply dropped.
            rows.append((symbol, DIVIDEND_DROPPED))
        else:
            # Gone from Nifty 50 entirely.
            rows.append((symbol, STRONG_SELL))
    # Current buys (kept in descending-yield order).
    for _, symbol, _ in matches:
        rows.append((symbol, BUY))

    rows.sort(key=lambda r: SIGNAL_ORDER[r[1]])

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print(f"\nNifty 50 Dividend Yield report (threshold > {args.min_yield}%):\n")
    print(f"{'Symbol':<12}{'Signal'}")
    print("-" * 50)
    for symbol, signal in rows:
        print(f"{symbol:<12}{signal}")

    missing = [r for r in results if r[2] is None]
    if missing:
        print(f"\nCould not fetch dividend yield for: {', '.join(s for _, s, _ in missing)}")

    write_suggestions(SUGGESTIONS_PATH, rows, args.min_yield, generated_at)
    print(f"\nSuggestions.md updated ({generated_at}).")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, requests.RequestException) as exc:
        sys.exit(f"ERROR: {exc}")
