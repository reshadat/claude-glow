<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo.svg" width="420" alt="claude-glow">
  </picture>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-16161a?style=flat-square" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.9%2B-16161a?style=flat-square" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/bulb-Tuya%20%2F%20Halonix-f59e0b?style=flat-square" alt="Tuya / Halonix">
  <img src="https://img.shields.io/badge/control-100%25%20local%20LAN-16161a?style=flat-square" alt="Local LAN">
  <img src="https://img.shields.io/badge/LLM%20in%20control%20loop-never-16161a?style=flat-square" alt="No LLM in loop">
</p>

<p align="center"><b>Your room tells you what Claude Code is doing.</b></p>

An ambient status light for Claude Code sessions. A Tuya-based WiFi smart bulb (Halonix, Smart Life, most white-label brands) changes color and brightness to reflect what Claude is doing right now. Green and dim means idle. Amber means a tool is about to run. Red and pulsing means Claude is waiting on you.

The whole pipeline is deterministic. Claude Code hook fires, runs a small Python script, script sends one packet to the bulb over your LAN. No cloud round trip after setup, no LLM in the control loop, nothing to hallucinate.

## State to color mapping

| State | Trigger | Color | Brightness |
|---|---|---|---|
| idle | Stop hook (session/turn ends) | Green (h 120) | Dim (15%) |
| thinking | PreToolUse hook (tool about to run) | Amber (h 35) | Medium (60%) |
| tool-done | PostToolUse hook (tool finished) | Blue (h 210) | Medium (50%) |
| waiting | Notification hook (Claude needs you) | Red (h 0) | Bright (100%), pulses 3x |
| error | Manual, or wire it yourself | Red (h 0) | Solid (70%) |
| off | Manual | Bulb off | - |
| test | Manual | Cycles all states, ~1s each | - |

All colors are configurable in `config.json` under the `colors` block, as HSV with h 0-360, s 0-100, v 0-100.

## How Halonix and Tuya fit together

Halonix smart bulbs are white-label Tuya devices. The Halonix app (and the Smart Life app) is a skin over the Tuya cloud. That matters because Tuya devices also speak a local LAN protocol, and once you extract the device's `local_key` you can control the bulb directly over your WiFi with the `tinytuya` library. Fast, private, works even if the Tuya cloud is down.

You need three things per bulb: `device_id`, `local_key`, and its LAN `ip`.

## Getting device_id and local_key

The local_key lives in the Tuya cloud, so you extract it once through a free developer account.

1. Pair the bulb with the Tuya Smart app. If the bulb currently lives in the Halonix OEM app, remove it there first and re-pair in Tuya Smart. The account link QR flow below works reliably with Tuya's own apps and is hit or miss with OEM skins. To re-pair: remove device, flip the wall switch off and on three times about a second apart until the bulb blinks fast, then Add Device in the app and give it your 2.4GHz WiFi. Do not skip the WiFi step or the bulb pairs over Bluetooth only and never joins your LAN.
2. Create a free account at https://iot.tuya.com and create a Cloud project (Smart Home type). Pick the data center matching your app account region (India for Indian accounts) or the device list comes back empty.
3. In the project, enable the core APIs (IoT Core, Authorization) and link your app account: Devices tab, Link App Account, Add App Account. If it asks for a bundle identifier, Tuya Smart is `com.tuya.smart` and Smart Life is `com.tuya.smartlife`. Scan the QR with the app (Me tab, scan icon top right). The QR expires in about a minute, refresh as needed.
4. Note the project's Access ID and Access Secret from the Overview tab.
5. Run the wizard: `./venv/bin/python -m tinytuya wizard`. Give it the Access ID, Secret and your region (`in` for India). It pulls the device list, scans your LAN, and writes `devices.json` with device_id, local_key and ip for every bulb.
6. Copy those three values into `config.json`, plus the `version` it reports as `protocol_version`.

Give the bulb a static IP (DHCP reservation on your router) or the ip in config will drift and glow dies silently.

Two warnings from real use. Never re-pair the bulb once this works, because re-pairing regenerates the local_key and kills your config. And if `tinytuya scan` finds nothing, that is not fatal: mesh routers (TP-Link Deco among them) often swallow the UDP discovery broadcasts. Find the bulb by probing TCP port 6668 across your subnet instead; a Tuya device is the only thing that listens there.

## Install

```bash
cd ~/checkouts/claude-glow
./setup.sh
```

setup.sh creates a `venv/` and installs into it, because Homebrew's Python refuses system-wide pip installs (PEP 668). Everything below and every hook command runs through `./venv/bin/python`, never bare `python3`.

Or manually:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp config.example.json config.json
# fill in device_id, local_key, ip
```

## Test it

```bash
./venv/bin/python glow.py test        # cycles idle, thinking, tool-done, waiting, error
./venv/bin/python glow.py waiting     # single state
./venv/bin/python glow.py off
```

If config is missing or the bulb is unreachable, glow.py logs a clear message to stderr and exits 0. It never throws a traceback at a calling hook and never blocks for more than a couple of seconds (1.5s socket timeout, single retry, fire-and-forget packets).

## Wiring into Claude Code

Merge the contents of `hooks.example.json` into `~/.claude/settings.json` (or a project's `.claude/settings.json`). If you already have a `hooks` block, add these entries into it rather than replacing it.

The mapping is: PreToolUse runs `glow.py thinking`, PostToolUse runs `glow.py tool-done`, Notification runs `glow.py waiting`, Stop runs `glow.py idle`. The `matcher: "*"` on the tool hooks matches every tool. Restart Claude Code or run `/hooks` to confirm they loaded.

There is no built-in error hook event in Claude Code, so the `error` state is there for your own wiring (a wrapper script, a CI job, whatever signals trouble in your setup).

## Config reference

```json
{
  "device_id": "...",
  "local_key": "...",
  "ip": "192.168.1.x",
  "protocol_version": 3.3,
  "socket_timeout": 1.5,
  "colors": { "idle": { "h": 120, "s": 100, "v": 15 }, ... }
}
```

`protocol_version` is 3.3 for most Halonix bulbs. If commands silently do nothing, try 3.4 or 3.5 (the tinytuya wizard's devices.json shows the right version). `socket_timeout` caps how long a hook can block on an unreachable bulb.

The optional `pulse` block tunes the waiting-state pulse. `interval` is seconds per half-pulse (dim or bright, floor 0.2). `max_seconds` caps how long the background pulser runs before settling on solid bright, so an abandoned session cannot strobe all night. `dim_percent` sets the dim phase as a percentage of the state's brightness. Defaults: 0.4, 300, 20.

## Troubleshooting

Bulb does nothing, no error: wrong protocol_version, or another app holds the bulb's single local connection. Close the Tuya app.
"Bulb not configured, cannot get device capabilities": tinytuya could not detect the bulb's DPS layout. glow.py probes status() once on connect and falls back to type B (DPS 20 to 26, which Halonix uses). If your bulb is the older type A, set `"bulb_type": "A"` in config.json.
"no config found": copy config.example.json to config.json and fill it in.
Wrong colors: Tuya bulbs vary in color rendering at low brightness. Tune the `colors` block.
Glow stopped working weeks later: the bulb's IP moved. Reserve it in your router's DHCP, update config.json.
