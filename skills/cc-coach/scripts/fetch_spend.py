#!/usr/bin/env python3
"""
Fetch authoritative Claude Code spend for the current developer from the
Athena cc-coach API (athenaupdater-api, which proxies the Anthropic cost
report). Exit 1 on failure — the caller falls back to the transcript estimate.

Usage:
  python3 fetch_spend.py                        # current month
  python3 fetch_spend.py --month 5 --year 2026
  python3 fetch_spend.py --email user@co.com    # override email

Returns JSON to stdout, e.g.:
  {"email": "...", "spend_usd": 15.95, "period": {...}, "cap_warning": false,
   "user_message": "", "data_refreshed_at": "...", "source": "api"}
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Authoritative spend API endpoint.
SPEND_API_BASE = "https://athena.webmdhelios.com/api/claude-code/coach/spend"
TIMEOUT = 8


def _find_email() -> str | None:
    for candidate in [
        os.path.expanduser("~/.claude.json"),
        os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                     "claude/.claude.json"),
    ]:
        if os.path.exists(candidate):
            try:
                with open(candidate) as f:
                    data = json.load(f)
                email = (data.get("oauthAccount") or {}).get("emailAddress", "")
                if email:
                    return email
            except (json.JSONDecodeError, OSError):
                pass

    athena_cfg = os.path.expanduser("~/.athena-config/athena-config.json")
    if os.path.exists(athena_cfg):
        try:
            with open(athena_cfg) as f:
                data = json.load(f)
            email = data.get("user-email", "")
            if email:
                return email
        except (json.JSONDecodeError, OSError):
            pass
    return None


def fetch_via_api(email: str, month: int, year: int) -> dict | None:
    url = f"{SPEND_API_BASE}?email={email}&month={month}&year={year}"
    # The API gateway rejects Python's default User-Agent with 403;
    # send a browser UA instead.
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
    })
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        float(body["spend_usd"])  # must be numeric to be usable
        body["source"] = "api"
        return body
    except (HTTPError, URLError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default=None)
    ap.add_argument("--month", type=int, default=None)
    ap.add_argument("--year",  type=int, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    month = args.month or now.month
    year  = args.year  or now.year
    email = args.email or _find_email()

    if not email:
        if not args.quiet:
            print("fetch_spend: could not determine developer email", file=sys.stderr)
        sys.exit(1)

    result = fetch_via_api(email, month, year)
    if result is None:
        if not args.quiet:
            print("fetch_spend: could not obtain authoritative spend", file=sys.stderr)
        sys.exit(1)

    result.setdefault("email", email)
    result.setdefault("period", {"month": month, "year": year})
    print(json.dumps(result))


if __name__ == "__main__":
    main()
