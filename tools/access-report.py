#!/usr/bin/env python3
"""Summarise Jellyfin's access log: what clients actually ask for, and what it costs.

Reads the access_*.log files that config/logging.json routes ASP.NET's
"Request finished" lines into (route, full query string, status, duration).
Jellyfin ships no request log of its own; before this existed the only way to
learn what a client sends was to grep the client's source (2026-09-20).

  tools/access-report.py                 # today's log in the live config dir
  tools/access-report.py --days 7        # last 7 files
  tools/access-report.py --route Items   # only routes containing "Items"
  tools/access-report.py --fields        # which Fields= sets each route receives

Routes are templated (GUIDs -> {id}) so /Shows/<guid>/Episodes groups as one.
"""
import argparse
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

LOG_DIR = Path("/mnt/data/docker-data/jellyfin/log")
LINE = re.compile(
    r"^(?P<ts>\S+ \S+) Request finished \S+ (?P<method>[A-Z]+) (?P<url>\S+) - (?P<status>\d+) "
    r"(?P<len>\S+) (?P<ctype>.*?) (?P<ms>[\d.]+)ms$")
GUID = re.compile(r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")


def template(path):
    return GUID.sub("{id}", path)


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--route", help="substring filter on the templated route")
    ap.add_argument("--fields", action="store_true", help="show Fields= sets per route")
    ap.add_argument("--slow", type=float, default=0, help="list individual requests slower than N ms")
    ap.add_argument("--log-dir", default=str(LOG_DIR))
    a = ap.parse_args()

    files = sorted(Path(a.log_dir).glob("access_*.log"))[-a.days:]
    if not files:
        raise SystemExit(f"no access_*.log under {a.log_dir} -- is config/logging.json installed?")

    by_route = defaultdict(list)
    fields = defaultdict(Counter)
    slow = []
    total = 0
    for f in files:
        for line in f.read_text(errors="replace").splitlines():
            m = LINE.match(line)
            if not m:
                continue
            total += 1
            u = urlsplit(m["url"])
            route = f"{m['method']} {template(u.path)}"
            ms = float(m["ms"])
            by_route[route].append(ms)
            q = parse_qs(u.query)
            # the Kotlin SDK repeats the param (fields=A&fields=B); the web client comma-joins
            fs = {f for v in (q.get("Fields", []) + q.get("fields", [])) for f in v.split(",") if f}
            if fs:
                fields[route][",".join(sorted(fs))] += 1
            if a.slow and ms >= a.slow:
                slow.append((ms, m["ts"], m["status"], m["url"]))

    print(f"{total} requests in {', '.join(f.name for f in files)}\n")
    print(f"{'route':60s} {'n':>6s} {'p50':>7s} {'p95':>7s} {'max':>8s} {'total s':>8s}")
    rows = sorted(by_route.items(), key=lambda kv: -sum(kv[1]))
    for route, xs in rows:
        if a.route and a.route not in route:
            continue
        print(f"{route[:60]:60s} {len(xs):6d} {pct(xs, 50):7.0f} {pct(xs, 95):7.0f} {max(xs):8.0f} {sum(xs) / 1000:8.1f}")

    if a.fields:
        print("\nFields= sets by route (what clients actually request):")
        for route, c in sorted(fields.items()):
            if a.route and a.route not in route:
                continue
            for fs, n in c.most_common():
                print(f"  {n:5d}  {route}\n         {fs}")

    if a.slow:
        print(f"\nrequests >= {a.slow:.0f} ms:")
        for ms, ts, st, url in sorted(slow, reverse=True)[:40]:
            print(f"  {ms:8.0f}ms {ts} {st} {url[:140]}")


if __name__ == "__main__":
    main()
