#!/usr/bin/env python3
"""
Mullvad WireGuard Web GUI

A browser-based tool to:
  1. Select a country and list its WireGuard relays
  2. Ping each relay to measure latency
  3. Generate OpenWrt WireGuard configs

Usage:
    ./wg-web-gui.py [--host 0.0.0.0] [--port 5000]
"""

import http.server
import json
import os
import re
import socketserver
import subprocess
import threading
import urllib.parse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

API_URL = "https://api.mullvad.net/www/relays/all/"
WG_PORT = 51820
PING_COUNT = 3
PING_TIMEOUT = 2
MAX_WORKERS = 30
API_TIMEOUT = 15

# ── Data cache ──────────────────────────────────────────────────────────────
_all_relays = None
_countries = None
_lock = threading.Lock()


def fetch_all_relays():
    global _all_relays, _countries
    with _lock:
        if _all_relays is not None:
            return _all_relays
    req = urllib.request.Request(API_URL)
    req.add_header("User-Agent", "MullvadWGWebGUI/1.0")
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise ConnectionError(f"Failed to fetch Mullvad API: {e}")
    with _lock:
        _all_relays = data
        countries = sorted(set(
            r.get("country_name", "Unknown")
            for r in _all_relays
            if r.get("type") == "wireguard" and r.get("country_name")
        ))
        _countries = countries
    return _all_relays


def get_countries():
    fetch_all_relays()
    with _lock:
        return list(_countries)


def get_relays_by_country(country_name):
    relays = fetch_all_relays()
    return [
        {
            "hostname": r.get("hostname", ""),
            "public_key": r.get("pubkey", ""),
            "ipv4": r.get("ipv4_addr_in", ""),
            "country": r.get("country_name", ""),
            "city": r.get("city_name", ""),
            "provider": r.get("provider", ""),
            "owned": r.get("owned", False),
        }
        for r in relays
        if r.get("type") == "wireguard"
        and r.get("country_name") == country_name
        and r.get("ipv4_addr_in")
    ]


def ping_ip(ip):
    try:
        result = subprocess.run(
            ["ping", "-c", str(PING_COUNT), "-W", str(PING_TIMEOUT), ip],
            capture_output=True, text=True,
            timeout=(PING_TIMEOUT * PING_COUNT) + 5,
        )
        output = result.stdout
        loss_match = re.search(r"(\d+)% packet loss", output)
        loss = int(loss_match.group(1)) if loss_match else 100
        rtt_match = re.search(
            r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)",
            output,
        )
        avg = float(rtt_match.group(2)) if rtt_match else float("inf")
        return avg, loss
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        return float("inf"), 100


def format_latency(ms):
    if ms == float("inf"):
        return "timeout"
    if ms < 1.0:
        return f"{ms*1000:.0f} µs"
    return f"{ms:.1f} ms"


# ── Request handler ─────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Suppress per-request logs
        pass

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path == "/api/config":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
                country = body.get("country", "")
                hostnames = body.get("hostnames", [])
                if not country:
                    self._send_json({"error": "No country specified"})
                    return
                relays = get_relays_by_country(country)
                selected = [r for r in relays if r["hostname"] in hostnames]
                if not selected:
                    self._send_json({"error": "No matching relays found"})
                    return
                configs = []
                for r in selected:
                    configs.append(
                        f"""config wireguard_wg0
    option description '{r['hostname']}'
    option public_key '{r['public_key']}'
    list allowed_ips '0.0.0.0/0'
    option route_allowed_ips '1'
    option endpoint_host '{r['ipv4']}'
    option endpoint_port '{WG_PORT}'
"""
                    )
                self._send_json({"config": "\n".join(configs), "relay_count": len(selected)})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
        else:
            self.send_error(404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/countries":
            try:
                self._send_json(get_countries())
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path.startswith("/api/relays/"):
            country = urllib.parse.unquote(path.split("/api/relays/", 1)[1])
            try:
                relays = get_relays_by_country(country)
                self._send_json(relays)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path.startswith("/api/ping/"):
            country = urllib.parse.unquote(path.split("/api/ping/", 1)[1])
            try:
                relays = get_relays_by_country(country)
                if not relays:
                    self._send_json({"error": f"No relays found for '{country}'"})
                    return

                results = []
                lock = threading.Lock()

                def worker(r):
                    avg, loss = ping_ip(r["ipv4"])
                    return {**r, "avg_latency": None if avg == float('inf') else round(avg, 2),
                            "loss": loss, "latency_display": format_latency(avg)}

                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    results = list(executor.map(worker, relays))

                results.sort(key=lambda x: (x["loss"] > 15, x["avg_latency"] if x["avg_latency"] is not None else 999999))
                self._send_json(results)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path.startswith("/api/config/"):
            country = urllib.parse.unquote(path.split("/api/config/", 1)[1])
            try:
                relays = get_relays_by_country(country)
                if not relays:
                    self._send_json({"error": f"No relays found for '{country}'"})
                    return
                configs = []
                for r in relays:
                    configs.append(
                        f"""config wireguard_wg0
    option description '{r['hostname']}'
    option public_key '{r['public_key']}'
    list allowed_ips '0.0.0.0/0'
    option route_allowed_ips '1'
    option endpoint_host '{r['ipv4']}'
    option endpoint_port '{WG_PORT}'
"""
                    )
                self._send_json({"config": "\n".join(configs), "relay_count": len(relays)})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/" or path == "":
            self._send_html()

        else:
            self.send_error(404)

    def _send_html(self):
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wg-web-gui.html")
        countries = get_countries()
        try:
            with open(html_path, "r") as f:
                html = f.read()
        except FileNotFoundError:
            html = HTML_TEMPLATE
        html = html.replace("__COUNTRIES_JSON__", json.dumps(countries))
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── HTML Template (written to separate file) ────────────────────────────────
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mullvad WireGuard — Server Finder</title>
<style>
:root {
    color-scheme: dark;
    --bg: #0d1117;
    --border: #30363d;
    --border-light: #21262d;
    --text: #c9d1d9;
    --text-muted: #8b949e;
    --text-dim: #6e7681;
    --link: #58a6ff;
    --hover: #21262d;
    --selected: #161b22;
    --code-bg: #161b22;
    --code-border: #30363d;
    --btn-bg: #21262d;
    --input-bg: #0d1117;
    --card-bg: #161b22;
    --th-bg: #161b22;
    --radius: 3px;
    --green: #3fb950;
    --yellow: #d29922;
    --red: #f85149;
    --mullvad: #58a6ff;
}

* { box-sizing: border-box; }

body {
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    font-size: 13px;
    line-height: 1.5;
    max-width: 1200px;
    margin: 0 auto;
    padding: 12px 16px;
    background-color: var(--bg);
    color: var(--text);
}

h1 {
    font-size: 1.5em;
    margin: 0 0 12px 0;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
}
h1 .subtitle { font-size: 0.7em; font-weight: 400; color: var(--text-dim); }

.controls {
    display: flex; gap: 8px; margin-bottom: 10px;
    flex-wrap: wrap; align-items: center;
}
.controls select {
    flex: 1; min-width: 200px; padding: 4px 8px;
    background: var(--input-bg); border: 1px solid var(--border);
    border-radius: var(--radius); color: var(--text);
    font-family: inherit; font-size: inherit;
    outline: none; cursor: pointer;
}
.controls select:disabled { opacity: 0.5; cursor: default; }

button, .btn {
    padding: 4px 10px;
    background: var(--btn-bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-family: inherit;
    font-size: inherit;
    cursor: pointer;
}
button:hover, .btn:hover { background: var(--hover); }
button:disabled, .btn:disabled { opacity: 0.5; cursor: default; }
.btn.primary { background: var(--link); color: #fff; border-color: var(--link); }
.btn.primary:hover { opacity: 0.9; }



.stats {
    margin-top: 16px;
    padding-top: 8px;
    border-top: 1px solid var(--border);
    font-size: 0.85em;
    color: var(--text-muted);
}
.stat-card {
    display: inline-block;
}
.stat-card .label {
    color: var(--text-dim);
    font-size: 0.9em;
}
.stat-card .value {
    font-weight: bold;
    font-size: 1.1em;
    color: var(--text);
}

.progress-bar {
    width: 100%; height: 6px;
    background: var(--border-light);
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 8px;
}
.progress-bar .fill {
    height: 100%;
    background: var(--link);
    transition: width 0.3s;
}
.progress-text {
    font-size: 0.9em;
    color: var(--text-dim);
    margin-bottom: 6px;
}

.table-wrap { overflow-x: auto; margin-bottom: 12px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td {
    text-align: left;
    padding: 6px 8px;
    border-bottom: 1px solid var(--border-light);
    vertical-align: top;
}
th {
    font-weight: 600;
    background: var(--th-bg);
}
th[onclick] { cursor: pointer; user-select: none; }
th[onclick]:hover { color: var(--link); }
th.sorted-asc::after { content: ' ▲'; font-size: 0.75em; color: var(--link); }
th.sorted-desc::after { content: ' ▼'; font-size: 0.75em; color: var(--link); }
th[onclick]:hover { color: var(--link); }
tr:hover { background-color: var(--hover); }

.badge {
    display: inline-block;
    background: var(--border-light);
    color: var(--text-muted);
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 0.85em;
}
.badge.mullvad { background: #0366d6; color: #fff; }

.latency-good { color: var(--green); }
.latency-ok { color: var(--yellow); }
.latency-bad { color: var(--red); }

.config-wrap { margin-top: 12px; }
.config-output {
    background: var(--code-bg);
    border: 1px solid var(--code-border);
    border-radius: var(--radius);
    padding: 10px;
    font-family: inherit;
    font-size: 12px;
    line-height: 1.4;
    color: var(--text);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 500px;
    overflow-y: auto;
}

.empty { text-align: center; padding: 40px 20px; color: var(--text-dim); }
.empty .icon { font-size: 36px; margin-bottom: 8px; }
.empty p { font-size: 0.95em; }

@media (max-width: 600px) {
    body { padding: 8px; }
    .controls { flex-direction: column; }
    .controls select { min-width: 100%; }
}
</style>
</head>
<body>
<h1>🛡️ Mullvad WireGuard Server Finder <span class="subtitle">Select a country, measure latency, generate OpenWrt configs</span></h1>

<div class="controls">
    <select id="country-select">
        <option value="">— Select a country —</option>
    </select>
    <button id="btn-fetch-relays" disabled>Load Servers</button>
    <button id="btn-ping" disabled>Ping Servers</button>
</div>

<div class="stats" id="stats" style="display:none;">
    <span class="stat-card"><span class="label">Total Servers</span> <span class="value" id="stat-total">0</span></span>
</div>

<div id="progress-area" style="display:none;">
    <div class="progress-text" id="progress-text">Pinging…</div>
    <div class="progress-bar"><div class="fill" id="progress-fill" style="width:0%"></div></div>
</div>

<div class="controls" style="margin-top:10px;">
    <label style="font-size:12px;color:var(--text-dim);"><input type="checkbox" id="select-all"> Select All</label>
    <button id="btn-generate" disabled>Generate Config</button>
</div>

<div class="table-wrap">
    <div class="empty" id="servers-empty">
        <div class="icon">🌍</div>
        <p>Select a country and click "Load Servers" to see available WireGuard relays.</p>
    </div>
    <table id="servers-table" style="display:none;">
        <thead><tr>
            <th style="width:32px;text-align:center">✓</th>
            <th onclick="sortLatencyTable(0)">Hostname</th>
            <th onclick="sortLatencyTable(1)">City</th>
            <th onclick="sortLatencyTable(2)">Country</th>
            <th onclick="sortLatencyTable(3)">Provider</th>
            <th onclick="sortLatencyTable(4)">IPv4</th>
            <th onclick="sortLatencyTable(5)">Latency</th>
            <th onclick="sortLatencyTable(6)">Loss</th>
        </tr></thead>
        <tbody id="servers-body"></tbody>
    </table>
</div>

<div class="config-wrap" id="config-wrap" style="display:none;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <span style="font-size:13px;font-weight:600;">OpenWrt WireGuard Config</span>
        <button onclick="copyConfig()">📋 Copy</button>
    </div>
    <div class="config-output" id="config-output"></div>
</div>

<script>
const $ = id => document.getElementById(id);

let currentCountry = '';
let currentRelays = [];
let currentLatency = [];

// ── Init ────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const countries = __COUNTRIES_JSON__;
    const sel = $('country-select');
    countries.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c; opt.textContent = c;
        sel.appendChild(opt);
    });

    sel.addEventListener('change', () => {
        resetAll();
        $('btn-fetch-relays').disabled = !sel.value;
    });

    });

// ── Reset ───────────────────────────────────────────────────────────────────
function resetAll() {
    currentCountry = '';
    currentRelays = [];
    currentLatency = [];
    $('stats').style.display = 'none';
    $('progress-area').style.display = 'none';
    $('servers-empty').style.display = '';
    $('servers-table').style.display = 'none';
    $('config-wrap').style.display = 'none';
    $('config-output').textContent = '';
    $('btn-fetch-relays').disabled = true;
    $('btn-ping').disabled = true;
    $('btn-generate').disabled = true;
    $('select-all').checked = false;
}

// ── Fetch relays ────────────────────────────────────────────────────────────
$('btn-fetch-relays').addEventListener('click', async () => {
    currentCountry = $('country-select').value;
    if (!currentCountry) return;

    $('btn-fetch-relays').disabled = true;
    $('btn-fetch-relays').textContent = 'Loading…';

    try {
        const resp = await fetch(`/api/relays/${encodeURIComponent(currentCountry)}`);
        const data = await resp.json();
        if (data.error) { alert(data.error); resetBtn(); return; }
        currentRelays = data;
        renderTable();
        resetBtn();
        $('btn-ping').disabled = false;
    } catch(e) {
        alert('Failed to load relays: ' + e.message);
        resetBtn();
    }
});

function resetBtn() {
    $('btn-fetch-relays').textContent = 'Load Servers';
    $('btn-fetch-relays').disabled = false;
}

// ── Ping ────────────────────────────────────────────────────────────────────
async function startPing() {
    currentCountry = $('country-select').value;
    if (!currentCountry || currentRelays.length === 0) return;

    $('btn-ping').disabled = true;
    $('btn-ping').textContent = 'Pinging…';
    $('progress-area').style.display = '';
    $('stats').style.display = 'block';

    const startTime = Date.now();
    const total = currentRelays.length;
    $('progress-text').textContent = `Pinging ${total} servers, please wait…`;

    try {
        const resp = await fetch(`/api/ping/${encodeURIComponent(currentCountry)}`);
        currentLatency = await resp.json();

        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        $('progress-fill').style.width = '100%';
        $('progress-text').textContent = `Done! ${currentLatency.length}/${total} pings completed in ${elapsed}s`;

        setTimeout(() => { $('progress-area').style.display = 'none'; }, 2000);

        renderTable();
        $('config-wrap').style.display = 'none';
        $('btn-generate').disabled = false;
        $('btn-ping').textContent = 'Ping Servers';
        $('btn-ping').disabled = false;
    } catch(e) {
        alert('Ping failed: ' + e.message);
        $('btn-ping').textContent = 'Ping Servers';
        $('btn-ping').disabled = false;
        $('progress-area').style.display = 'none';
    }
}

$('btn-ping').addEventListener('click', startPing);

function renderTable() {
    $('servers-empty').style.display = 'none';
    $('servers-table').style.display = '';

    if (currentLatency.length > 0) {
        $('stat-total').textContent = currentLatency.length;
    }

    const hasLatency = currentLatency.length > 0;
    const lookup = hasLatency ? Object.fromEntries(currentLatency.map(r => [r.hostname, r])) : {};

    $('servers-body').innerHTML = currentRelays.map((r, i) => {
        const l = lookup[r.hostname];
        const latCls = l ? (l.avg_latency < 50 ? 'latency-good' : l.avg_latency < 150 ? 'latency-ok' : 'latency-bad') : '';
        const lossCls = l && l.loss === 0 ? 'latency-good' : (l ? 'latency-bad' : '');
        return `<tr>
            <td style="text-align:center"><input type="checkbox" class="row-check" data-idx="${i}"></td>
            <td><code>${r.hostname}</code></td>
            <td>${r.city}</td>
            <td>${r.country}</td>
            <td><span class="badge ${r.owned ? 'mullvad' : 'other'}">${r.provider}</span></td>
            <td><code>${r.ipv4}</code></td>
            <td class="${latCls}">${l ? l.latency_display : '—'}</td>
            <td class="${lossCls}">${l ? l.loss + '%' : '—'}</td>
        </tr>`;
    }).join('');
}

$('select-all').addEventListener('change', () => {
    document.querySelectorAll('.row-check').forEach(cb => cb.checked = $('select-all').checked);
});

$('select-all').addEventListener('change', () => {
    document.querySelectorAll('.row-check').forEach(cb => cb.checked = $('select-all').checked);
});

let sortCol = -1;
let sortAsc = true;

function sortLatencyTable(col) {
    sortCol = col;
    sortAsc = !sortAsc;

    document.querySelectorAll('#servers-table th').forEach((th, i) => {
        th.classList.remove('sorted-asc', 'sorted-desc');
        if (i === col + 1) th.classList.add(sortAsc ? 'sorted-asc' : 'sorted-desc');
    });

    const colMap = { 0:'hostname', 1:'city', 2:'country', 3:'provider', 4:'ipv4', 5:'avg_latency', 6:'loss' };
    const key = colMap[col];
    if (!key) return;

    const hasLatency = currentLatency.length > 0;
    const lookup = hasLatency ? Object.fromEntries(currentLatency.map(r => [r.hostname, r])) : {};

    currentRelays.sort((a, b) => {
        let va, vb;
        if (key === 'country') {
            va = a[key]; vb = b[key];
        } else if (hasLatency) {
            va = lookup[a.hostname]; vb = lookup[b.hostname];
            va = va ? va[key] : null;
            vb = vb ? vb[key] : null;
        } else {
            va = a[key]; vb = b[key];
        }
        if (va == null || vb == null) {
            return sortAsc ? (va==null ? -1 : 1) : (vb==null ? -1 : 1);
        }
        if (typeof va === 'string') return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        return sortAsc ? va - vb : vb - va;
    });

    renderTable();
}

// ── Generate Config ─────────────────────────────────────────────────────────
$('btn-generate').addEventListener('click', async () => {
    const checks = document.querySelectorAll('.row-check:checked');
    if (checks.length === 0) { alert('Select at least one server.'); return; }
    const hostnames = Array.from(checks).map(cb => currentRelays[parseInt(cb.dataset.idx)].hostname);

    $('btn-generate').disabled = true;
    $('btn-generate').textContent = 'Generating…';

    try {
        const resp = await fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ country: currentCountry, hostnames })
        });
        const data = await resp.json();
        if (data.error) { alert(data.error); resetGenBtn(); return; }
        $('config-output').textContent = data.config;
        $('config-wrap').style.display = '';
        resetGenBtn();
    } catch(e) {
        alert('Failed to generate config: ' + e.message);
        resetGenBtn();
    }
});

function resetGenBtn() {
    $('btn-generate').textContent = 'Generate Config for Selected';
    $('btn-generate').disabled = false;
}

function copyConfig() {
    const text = $('config-output').textContent;
    const btn = document.querySelector('#config-wrap button');
    const orig = btn.textContent;

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => {
            btn.textContent = '✅ Copied!';
            setTimeout(() => btn.textContent = orig, 1500);
        });
    } else {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        try {
            document.execCommand('copy');
            btn.textContent = '✅ Copied!';
            setTimeout(() => btn.textContent = orig, 1500);
        } catch(e) {
            btn.textContent = '❌ Failed';
            setTimeout(() => btn.textContent = orig, 1500);
        }
        document.body.removeChild(ta);
    }
}
</script>
</body>
</html>'''


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Mullvad WireGuard Web GUI")
    parser.add_argument("--host", default="127.0.0.1", help="Listen address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    args = parser.parse_args()

    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wg-web-gui.html")
    with open(html_path, "w") as f:
        f.write(HTML_TEMPLATE)
    print(f"HTML template written to {html_path}")

    class ReuseServer(socketserver.TCPServer):
        allow_reuse_address = True

    handler = Handler
    with ReuseServer((args.host, args.port), handler) as httpd:
        print(f"Starting Mullvad WireGuard Web GUI on http://{args.host}:{args.port}")
        print("Press Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
