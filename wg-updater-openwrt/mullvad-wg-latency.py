#!/usr/bin/env python3
"""
Mullvad WireGuard Relay Latency Checker

Fetches all IPv4 addresses from the Mullvad relay API,
pings each one (5 packets), and sorts by latency.
"""

import argparse
import subprocess
import json
import re
import sys
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

API_URL = "https://api.mullvad.net/www/relays/all/"
PING_COUNT = 5
TIMEOUT = 10  # seconds per ping
MAX_WORKERS = 25  # concurrent ping workers

EU_COUNTRIES = [
    "Spain", "Netherlands", "Switzerland", "Germany", "UK",
    "Belgium", "Italy", "Sweden", "France", "Denmark",
    "Ireland", "Norway",
]

ASIA_COUNTRIES = [
    "Singapore", "Malaysia", "Thailand", "Hong Kong",
]


def fetch_relays():
    """Fetch all relay data from Mullvad API."""
    req = urllib.request.Request(API_URL)
    req.add_header("User-Agent", "MullvadLatencyChecker/1.0")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"Error fetching relay data: {e}", file=sys.stderr)
        sys.exit(1)
    return data


def extract_wg_ipv4(relays):
    """Extract WireGuard IPv4 addresses along with relay metadata."""
    entries = []
    for relay in relays:
        if relay.get("type") != "wireguard":
            continue
        ipv4 = relay.get("ipv4_addr_in")
        if ipv4:
            entries.append({
                "ip": ipv4,
                "name": relay.get("hostname", "unknown"),
                "country": relay.get("country_name", "unknown"),
                "city": relay.get("city_name", "unknown"),
                "owner": relay.get("provider", "unknown"),
            })
    return entries


def ping_ip(ip, count=PING_COUNT, timeout=TIMEOUT):
    """Ping an IP address and return the average latency in ms.

    Returns (avg_latency_ms, loss_percent, ip, metadata).
    """
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", "2", ip],
            capture_output=True,
            text=True,
            timeout=timeout * count + 5,
        )
        output = result.stdout

        # Parse loss
        loss_match = re.search(r"(\d+)% packet loss", output)
        loss = int(loss_match.group(1)) if loss_match else 100

        # Parse rtt average
        rtt_match = re.search(
            r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)",
            output,
        )
        if rtt_match:
            avg = float(rtt_match.group(2))
        else:
            avg = float("inf")

        return avg, loss

    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        return float("inf"), 100


def format_latency(ms):
    """Format latency nicely."""
    if ms == float("inf"):
        return "timeout"
    return f"{ms:.1f} ms"


def filter_by_countries(entries, countries):
    """Filter entries to only those in the given country list."""
    return [e for e in entries if e["country"] in countries]


def main():
    parser = argparse.ArgumentParser(description="Mullvad WireGuard Relay Latency Checker")
    parser.add_argument("-e", "--europe", action="store_true",
                        help="Only ping relays in selected European countries")
    parser.add_argument("-a", "--asia", action="store_true",
                        help="Only ping relays in selected Asian countries")
    parser.add_argument("-lt", "--less-than", type=float, metavar="MS",
                        help="Only show results with latency below MS ms")
    args = parser.parse_args()

    if args.europe:
        countries = EU_COUNTRIES
        print(f"Filtering to {len(countries)} European countries: {', '.join(countries)}")
    elif args.asia:
        countries = ASIA_COUNTRIES
        print(f"Filtering to {len(countries)} Asian countries: {', '.join(countries)}")
    else:
        countries = None

    print("Fetching Mullvad WireGuard relay data...")
    data = fetch_relays()
    relays = data if isinstance(data, list) else data.get("relays", [])
    print(f"Found {len(relays)} relays, extracting WireGuard IPv4 addresses...")

    entries = extract_wg_ipv4(relays)
    if countries:
        entries = filter_by_countries(entries, countries)
        print(f"Filtered to {len(entries)} WireGuard relays in selected countries")
    print(f"Found {len(entries)} WireGuard IPv4 addresses. Pinging each ({PING_COUNT} packets)...\n")

    results = []
    lock = threading.Lock()
    completed = 0

    def ping_entry(entry):
        nonlocal completed
        ip = entry["ip"]
        avg, loss = ping_ip(ip)
        with lock:
            completed += 1
            results.append({
                **entry,
                "avg_latency": avg,
                "loss": loss,
            })
        print(f"[{completed}/{len(entries)}] {ip} ({entry['name']}, {entry['country']}) — avg={format_latency(avg)} loss={loss}%", flush=True)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        list(executor.map(ping_entry, entries))

    # Sort: low-loss first (<=15%), then by latency; high-loss (>15%) pushed to bottom
    results.sort(key=lambda x: (x["loss"] > 15, x["avg_latency"]))

    # Filter by max latency
    if args.less_than is not None:
        results = [r for r in results if r["avg_latency"] < args.less_than]
        print(f"Filtered to {len(results)} relays with latency < {args.less_than} ms")

    if not results:
        print("No relays matched the criteria.")
        return

    # Print sorted results
    print("\n" + "=" * 100)
    print(f"{'#':<4} {'IPv4 Address':<20} {'Name':<25} {'Country':<15} {'Avg Latency':<14} {'Loss':<8}")
    print("=" * 100)

    for i, r in enumerate(results, 1):
        print(
            f"{i:<4} {r['ip']:<20} {r['name']:<25} {r['country']:<15} "
            f"{format_latency(r['avg_latency']):<14} {r['loss']}%"
        )

    print("=" * 100)

    # Print top 20
    print("\nTop 20 lowest latency:")
    for i, r in enumerate(results[:20], 1):
        print(f"  {i}. {r['ip']} ({r['name']}, {r['country']}) — {format_latency(r['avg_latency'])}")


if __name__ == "__main__":
    main()
