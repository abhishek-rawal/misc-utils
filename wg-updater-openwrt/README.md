# wg-updater-openwrt

A pair of tools for working with Mullvad WireGuard relays on OpenWrt:

1. **Latency checker** — find the lowest-latency Mullvad WireGuard relay
2. **OpenWrt configurator** — generate WireGuard config blocks from relay hostnames

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

## Typical Workflow

1. Run `mullvad-wg-latency.py` to find low-latency relays
2. Copy the desired relay hostname(s)
3. Run `wg-openwrt-configurator` to get the OpenWrt WireGuard config
