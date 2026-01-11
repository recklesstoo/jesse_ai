#!/usr/bin/env python
import argparse
import json
import time
import urllib.parse
import urllib.request


def fetch_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.load(resp)


def fmt(v):
    return "-" if v is None else str(v)


def summarize_monitor(data):
    return {
        "ok": data.get("ok"),
        "wsConnected": data.get("wsConnected"),
        "mode": (data.get("botStatus") or {}).get("mode"),
        "instrument": (data.get("botStatus") or {}).get("instrument"),
        "lastBarTs": data.get("lastBarTs"),
        "lastBarAgeSec": data.get("lastBarAgeSec"),
        "barsInMemory": data.get("barsInMemory"),
        "lastDbBarTs": (data.get("lastDbBar") or {}).get("ts"),
        "lastDbBarAgeSec": data.get("lastDbBarAgeSec"),
    }


def print_section(title, rows):
    print("\n== {} ==".format(title))
    for k, v in rows:
        print("{:<18} {}".format(k + ":", v))


def main():
    parser = argparse.ArgumentParser(description="Diagnose BridgePuppet data feed.")
    parser.add_argument("--base", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--bot", default="bot-1", help="Bot ID")
    parser.add_argument("--interval", type=float, default=2.0, help="Poll interval seconds")
    parser.add_argument("--count", type=int, default=5, help="Number of polls")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    bot = args.bot

    monitor_url = base + "/api/monitor/status?" + urllib.parse.urlencode({"botId": bot})
    signals_url = base + "/api/ai-signals?" + urllib.parse.urlencode({"botId": bot})
    bars_status_url = base + "/api/bars/status?" + urllib.parse.urlencode({"bot_id": bot})

    try:
        monitor = fetch_json(monitor_url)
        signals = fetch_json(signals_url)
        bars_status = fetch_json(bars_status_url)
    except Exception as exc:
        print("ERROR: failed to fetch endpoints:", exc)
        return 2

    mon = summarize_monitor(monitor)
    print_section("Monitor", [(k, fmt(v)) for k, v in mon.items()])

    print_section(
        "AI Signals",
        [
            ("signal", fmt(signals.get("signal"))),
            ("bias", fmt(signals.get("bias"))),
            ("confidence", fmt(signals.get("confidence"))),
            ("barTs", fmt(signals.get("barTs"))),
        ],
    )

    print_section(
        "Bars DB",
        [
            ("total", fmt(bars_status.get("total"))),
            ("latest", fmt(bars_status.get("latest"))),
            ("by_mode", fmt(bars_status.get("by_mode"))),
        ],
    )

    print("\nPolling {} times every {}s...".format(args.count, args.interval))
    last_ts = mon.get("lastBarTs")
    changes = 0
    for i in range(args.count):
        time.sleep(args.interval)
        try:
            data = fetch_json(monitor_url)
        except Exception as exc:
            print("poll {}: error: {}".format(i + 1, exc))
            continue
        ts = data.get("lastBarTs")
        age = data.get("lastBarAgeSec")
        changed = ts != last_ts and ts is not None
        if changed:
            changes += 1
        print(
            "poll {}: lastBarTs={} ageSec={} changed={}".format(
                i + 1, fmt(ts), fmt(age), "yes" if changed else "no"
            )
        )
        last_ts = ts

    if changes == 0:
        print("\nRESULT: STALE - no new bars observed during polling.")
        return 1

    print("\nRESULT: OK - bars updated {} time(s).".format(changes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
