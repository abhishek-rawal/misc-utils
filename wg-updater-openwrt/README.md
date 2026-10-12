# wg-updater-openwrt

A suite of tools for working with Mullvad WireGuard relays on OpenWrt:

1. **Latency checker** — find the lowest-latency Mullvad WireGuard relay
2. **OpenWrt configurator** — generate WireGuard config blocks from relay hostnames
3. **Web GUI** — browser-based interface combining both tools

## Tools

## 1. wg-web-gui.py

A zero-dependency web GUI combining both tools. Select a country, load servers, measure latency, and generate OpenWrt configs — all in your browser.

**Requirements:** `python3`

**Usage:**
```bash
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

**Example:**
  <img width="1910" height="1201" alt="Screenshot_20261011_222438" src="https://github.com/user-attachments/assets/071d1ea0-ff35-40e0-986e-64e40a5acfa8" />

### 2. mullvad-wg-latency.py

Fetches all WireGuard relay IPv4 addresses from the Mullvad API, pings each one, and sorts by latency.

**Requirements:** `python`, `ping`

**Usage:**
```bash
python3 mullvad-wg-latency.py                    # all relays
python3 mullvad-wg-latency.py --europe           # European countries only
python3 mullvad-wg-latency.py --asia             # Asian countries only
python3 mullvad-wg-latency.py --less-than 50     # below 50ms
```
**Example:**
```bash
$ python3 mullvad-wg-latency.py --asia -lt 90
[..]
Filtered to 8 relays with latency < 90.0 ms

====================================================================================================
#    IPv4 Address         Name                      Country         Avg Latency    Loss    
====================================================================================================
1    146.70.199.130       sg-sin-wg-102             Singapore       64.9 ms        0%
2    135.136.98.130       sg-sin-wg-103             Singapore       65.1 ms        0%
3    138.199.60.28        sg-sin-wg-003             Singapore       65.8 ms        0%
4    146.70.199.2         sg-sin-wg-101             Singapore       66.1 ms        0%
5    98.98.47.130         my-kul-wg-001             Malaysia        72.3 ms        0%
6    138.199.60.2         sg-sin-wg-001             Singapore       72.7 ms        0%
7    162.128.129.98       my-kul-wg-002             Malaysia        74.5 ms        0%
8    138.199.60.15        sg-sin-wg-002             Singapore       86.3 ms        0%
====================================================================================================
```

### 3. wg-openwrt-configurator

Generates OpenWrt `config wireguard_*` blocks from Mullvad relay hostnames by looking up public keys and endpoint IPs from the Mullvad API.

**Requirements:** `bash`, `curl`, `jq`

**Usage:**
```bash
./wg-openwrt-configurator -s wg0 nl-ams-wg-005
./wg-openwrt-configurator -s wg1 nl-ams-wg-005,de-ber-wg-001,us-atl-wg-001
```
**Example:**
```bash
$ ./wg-openwrt-configurator -s wg1 nl-ams-wg-005,de-ber-wg-001,us-atl-wg-001

config wireguard_wg1
    option description 'nl-ams-wg-005'
    option public_key '33BoONMGCm2vknq2eq72eozRsHmHQY6ZHEEZ4851TkY='
    list allowed_ips '0.0.0.0/0'
    option route_allowed_ips '1'
    option endpoint_host '193.32.249.70'
    option endpoint_port '51820'

config wireguard_wg1
    option description 'de-ber-wg-001'
    option public_key '0qSP0VxoIhEhRK+fAHVvmfRdjPs2DmmpOCNLFP/7cGw='
    list allowed_ips '0.0.0.0/0'
    option route_allowed_ips '1'
    option endpoint_host '193.32.248.66'
    option endpoint_port '51820'

config wireguard_wg1
    option description 'us-atl-wg-001'
    option public_key 'nvyBkaEXHwyPBAm8spGB0TFzf2W5wPAl8EEuJ0t+bzs='
    list allowed_ips '0.0.0.0/0'
    option route_allowed_ips '1'
    option endpoint_host '45.134.140.130'
    option endpoint_port '51820'
```


## Typical Workflow

1. Run `mullvad-wg-latency.py` to find low-latency relays
2. Copy the desired relay hostname(s)
3. Run `wg-openwrt-configurator` to get the OpenWrt WireGuard config

Or use the web GUI (`wg-web-gui.py`) to do all steps in a single browser window.
