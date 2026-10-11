# wg-updater-openwrt

A suite of tools for working with Mullvad WireGuard relays on OpenWrt:

1. **Latency checker** — find the lowest-latency Mullvad WireGuard relay
2. **OpenWrt configurator** — generate WireGuard config blocks from relay hostnames
3. **Web GUI** — browser-based interface combining both tools

## Tools

### 1. mullvad-wg-latency.py

Fetches all WireGuard relay IPv4 addresses from the Mullvad API, pings each one, and sorts by latency.

**Requirements:** Python 3, `ping`

**Usage:**
```bash
python3 mullvad-wg-latency.py                    # all relays
python3 mullvad-wg-latency.py --europe           # European countries only
python3 mullvad-wg-latency.py --asia             # Asian countries only
python3 mullvad-wg-latency.py --less-than 50     # below 50ms
```

### 2. wg-openwrt-configurator

Generates OpenWrt `config wireguard_*` blocks from Mullvad relay hostnames by looking up public keys and endpoint IPs from the Mullvad API.

**Requirements:** Bash 4+, `curl`, `jq`

**Usage:**
```bash
./wg-openwrt-configurator -s wg0 nl-ams-wg-005
./wg-openwrt-configurator -s wg1 nl-ams-wg-005,de-ber-wg-001,us-atl-wg-001
```

## 3. wg-web-gui.py

A zero-dependency web GUI combining both tools. Select a country, load servers, measure latency, and generate OpenWrt configs — all in your browser.

**Requirements:** Python 3 (built-in `http.server` only, no external packages)

**Usage:**
```bash
python3 wg-web-gui.py                         # defaults to 127.0.0.1:5000
python3 wg-web-gui.py --host 0.0.0.0 --port 8081
```

**Workflow:**
1. Select a country from the dropdown
2. Click **Load Servers** to fetch available relays
3. Click **Ping Servers** to measure latency (up to 30 concurrent ICMP pings)
4. Select one or more servers via checkboxes
5. Click **Generate Config** to produce OpenWrt WireGuard blocks inline
6. Click **Copy** to copy the config to clipboard

**Features:**
- Sortable columns — click any header (Hostname, City, Country, Provider, IPv4, Latency, Loss)
- Dark theme (Sashiko/GitHub-inspired)
- Server-owned badges (Mullvad-owned vs. partner)
- Latency coloring: green (<50ms), yellow (50-150ms), red (>150ms)

## Typical Workflow

1. Run `mullvad-wg-latency.py` to find low-latency relays
2. Copy the desired relay hostname(s)
3. Run `wg-openwrt-configurator` to get the OpenWrt WireGuard config

Or use the web GUI (`wg-web-gui.py`) to do all steps in a single browser window.
