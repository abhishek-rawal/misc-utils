# wg-updater-openwrt

A pair of tools for working with Mullvad WireGuard relays on OpenWrt:

1. **Latency checker** — find the lowest-latency Mullvad WireGuard relay
2. **OpenWrt configurator** — generate WireGuard config blocks from relay hostnames

## Tools

### 1. mullvad-wg-latency.py

Fetches all WireGuard relay IPv4 addresses from the Mullvad API, pings each one, and sorts by latency.

**Requirements:** `python3`, `ping`

**Usage:**
```bash
python3 mullvad-wg-latency.py                    # all relays
python3 mullvad-wg-latency.py --europe           # European countries only
python3 mullvad-wg-latency.py --asia             # Asian countries only
python3 mullvad-wg-latency.py --less-than 50     # below 50ms
```

**Sample:**
```bash
$ python3 mullvad-wg-latency.py --europe -lt  130
[..]
Filtered to 12 relays with latency < 130.0 ms

====================================================================================================
#    IPv4 Address         Name                      Country         Avg Latency    Loss    
====================================================================================================
1    135.136.16.130       es-mad-wg-204             Spain           119.2 ms       0%
2    146.70.74.98         es-mad-wg-203             Spain           119.6 ms       0%
3    185.253.99.98        es-bcn-wg-102             Spain           123.2 ms       0%
4    169.150.201.2        de-fra-wg-401             Germany         123.5 ms       0%
5    135.136.4.130        es-mad-wg-205             Spain           123.6 ms       0%
6    185.65.134.76        nl-ams-wg-007             Netherlands     126.5 ms       0%
7    185.184.222.166      nl-ams-wg-302             Netherlands     127.1 ms       0%
8    146.70.119.130       gb-lon-wg-306             UK              127.5 ms       0%
9    169.150.211.175      de-fra-wg-404             Germany         128.1 ms       0%
10   138.199.6.233        ch-zrh-wg-404             Switzerland     129.0 ms       0%
11   185.253.99.30        es-bcn-wg-101             Spain           129.6 ms       0%
12   138.199.6.207        ch-zrh-wg-402             Switzerland     130.0 ms       0%
====================================================================================================
```

### 2. wg-openwrt-configurator

Generates OpenWrt `config wireguard_*` blocks from Mullvad relay hostnames by looking up public keys and endpoint IPs from the Mullvad API.

**Requirements:** `bash`, `curl`, `jq`

**Usage:**
```bash
./wg-openwrt-configurator -s wg0 nl-ams-wg-005
./wg-openwrt-configurator -s wg1 nl-ams-wg-005,de-ber-wg-001,us-atl-wg-001
```

**Sample:**
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
