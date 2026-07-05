# claude-glow

An ambient status light for Claude Code sessions. A Halonix WiFi smart bulb changes color and brightness to reflect what Claude is doing right now. Green and dim means idle. Amber means a tool is about to run. Red and pulsing means Claude is waiting on you.

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

1. Pair the bulb with the Smart Life app (or the Halonix app, both register the device on Tuya's backend).
2. Create a free account at https://iot.tuya.com and create a Cloud project (Smart Home type). Pick the India data center if your app account is Indian.
3. In the project, enable the core APIs (IoT Core, Authorization) and link your app account: Devices tab, Link Tuya App Account, scan the QR code from the Smart Life app (Me, top-right scan icon).
4. Note the project's Access ID and Access Secret.
5. Run the wizard: `python3 -m tinytuya wizard`. Give it the Access ID, Secret, one device_id (visible in the linked devices list) and your region. It scans your LAN, matches devices, and writes `devices.json` with device_id, local_key and ip for every bulb.
6. Copy those three values into `config.json`.

Give the bulb a static IP (DHCP reservation on your router) or the ip in config will drift.

## Install

```bash
cd ~/checkouts/claude-glow
./setup.sh
```

Or manually:

```bash
pip3 install -r requirements.txt
cp config.example.json config.json
# fill in device_id, local_key, ip
```

## Test it

```bash
python3 glow.py test        # cycles idle, thinking, tool-done, waiting, error
python3 glow.py waiting     # single state
python3 glow.py off
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

## Troubleshooting

Bulb does nothing, no error: wrong protocol_version, or another app holds the bulb's single local connection. Close the Smart Life app.
"no config found": copy config.example.json to config.json and fill it in.
Wrong colors: Tuya bulbs vary in color rendering at low brightness. Tune the `colors` block.
