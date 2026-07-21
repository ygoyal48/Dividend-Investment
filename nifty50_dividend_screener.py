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

import requests

LOGIN_URL = "https://www.screener.in/login/"
NIFTY50_CSV_URL = "https://niftyindices.com/IndexConstituent/ind_nifty50list.csv"
SUGGESTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Suggestions.md")


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


def fetch_nifty50_constituents(session):
    resp = session.get(NIFTY50_CSV_URL, timeout=20)
    resp.raise_for_status()
    rows = list(csv.DictReader(resp.text.splitlines()))
    return [(row["Company Name"].strip(), row["Symbol"].strip()) for row in rows]


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


def parse_previous_suggestions(path):
    """Return {symbol: company_name} from the Suggestions.md written by a prior run."""
    if not os.path.exists(path):
        return {}
    previous = {}
    row_re = re.compile(r'^\|\s*([A-Z0-9&.\-]+)\s*\|\s*([^|]+?)\s*\|\s*[\d.]+%\s*\|\s*$')
    with open(path) as f:
        for line in f:
            m = row_re.match(line.strip())
            if m:
                previous[m.group(1)] = m.group(2).strip()
    return previous


def write_suggestions(path, matches, min_yield, generated_at):
    """Overwrite the suggestions file with only the latest matches (old list is discarded)."""
    lines = [
        f"# Nifty 50 Dividend Yield Suggestions (> {min_yield}%)",
        "",
        f"_Generated: {generated_at}_",
        "",
        "| Symbol | Company | Dividend Yield |",
        "|---|---|---|",
    ]
    for name, symbol, yield_pct in matches:
        lines.append(f"| {symbol} | {name} | {yield_pct:.2f}% |")
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

    previous = parse_previous_suggestions(SUGGESTIONS_PATH)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    login(session, username, password)

    constituents = fetch_nifty50_constituents(session)

    results = []
    for name, symbol in constituents:
        yield_pct = fetch_dividend_yield(session, symbol)
        results.append((name, symbol, yield_pct))
        time.sleep(0.4)

    matches = [r for r in results if r[2] is not None and r[2] > args.min_yield]
    matches.sort(key=lambda r: r[2], reverse=True)

    new_symbols = {symbol for _, symbol, _ in matches}
    removed = {sym: comp_name for sym, comp_name in previous.items() if sym not in new_symbols}

    print(f"\nNifty 50 stocks with Dividend Yield > {args.min_yield}% "
          f"({len(matches)} of {len(results)}):\n")
    print(f"{'Symbol':<12}{'Name':<40}{'Div Yield %':>12}")
    print("-" * 64)
    for name, symbol, yield_pct in matches:
        print(f"{symbol:<12}{name[:38]:<40}{yield_pct:>11.2f}%")

    missing = [r for r in results if r[2] is None]
    if missing:
        print(f"\nCould not fetch dividend yield for: {', '.join(s for _, s, _ in missing)}")

    if removed:
        print("\n**Removed since last suggestion list (no longer above threshold):**")
        for sym, comp_name in removed.items():
            print(f"- **{sym} ({comp_name})**")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    write_suggestions(SUGGESTIONS_PATH, matches, args.min_yield, generated_at)
    print(f"\nSuggestions.md updated ({generated_at}).")


if __name__ == "__main__":
    main()
