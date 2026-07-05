#!/usr/bin/env python3
"""claude-glow: drive a Tuya/Halonix smart bulb from Claude Code hook events.

Usage: python3 glow.py <state>
States: idle, thinking, tool-done, waiting, error, off, test

Deterministic hook -> bulb pipeline. No LLM anywhere in the loop.
Designed to never break a calling hook: all failures log to stderr and exit 0.
"""

import json
import os
import sys
import time

STATES = ("idle", "thinking", "tool-done", "waiting", "error", "off", "test")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# HSV: h 0-360, s 0-100, v 0-100. Overridable per state via config.json "colors".
DEFAULT_COLORS = {
    "idle":      {"h": 120, "s": 100, "v": 15},   # green, dim
    "thinking":  {"h": 35,  "s": 100, "v": 60},   # amber
    "tool-done": {"h": 210, "s": 100, "v": 50},   # blue
    "waiting":   {"h": 0,   "s": 100, "v": 100},  # red, bright (pulsed)
    "error":     {"h": 0,   "s": 100, "v": 70},   # red, solid
}

PLACEHOLDER_MARKERS = ("REPLACE", "YOUR_", "CHANGEME", "XXXX")


def log(msg):
    print("claude-glow: %s" % msg, file=sys.stderr)


def load_config():
    """Return config dict, or None (with a clear stderr message) if unusable."""
    if not os.path.exists(CONFIG_PATH):
        log("no config found at %s. Copy config.example.json to config.json "
            "and fill in device_id, local_key and ip. Doing nothing." % CONFIG_PATH)
        return None
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        log("could not read config.json: %s. Doing nothing." % e)
        return None

    for key in ("device_id", "local_key", "ip"):
        val = str(cfg.get(key, "")).strip()
        if not val or any(m in val.upper() for m in PLACEHOLDER_MARKERS):
            log("config.json field '%s' is missing or still a placeholder. "
                "Run the tinytuya wizard to get real values (see README). "
                "Doing nothing." % key)
            return None
    return cfg


def connect(cfg):
    """Return a ready BulbDevice, or None (logged) on failure."""
    try:
        import tinytuya
    except ImportError:
        log("tinytuya is not installed. Run: pip3 install tinytuya. Doing nothing.")
        return None
    try:
        bulb = tinytuya.BulbDevice(cfg["device_id"], cfg["ip"], cfg["local_key"])
        bulb.set_version(float(cfg.get("protocol_version", 3.3)))
        # Keep hooks fast: short socket timeout, single retry, persistent socket
        # so multi-packet states (waiting pulse, test) reuse one connection.
        bulb.set_socketTimeout(float(cfg.get("socket_timeout", 1.5)))
        bulb.set_socketRetryLimit(1)
        bulb.set_socketPersistent(True)
        return bulb
    except Exception as e:
        log("could not set up bulb connection: %s. Doing nothing." % e)
        return None


def get_color(cfg, state):
    color = dict(DEFAULT_COLORS[state])
    override = (cfg.get("colors") or {}).get(state) or {}
    for k in ("h", "s", "v"):
        if k in override:
            color[k] = override[k]
    return color


def set_color(bulb, color):
    """Turn bulb on and apply HSV. nowait keeps hook latency low."""
    h = max(0.0, min(360.0, float(color["h"]))) / 360.0
    s = max(0.0, min(100.0, float(color["s"]))) / 100.0
    v = max(0.0, min(100.0, float(color["v"]))) / 100.0
    bulb.turn_on(nowait=True)
    bulb.set_hsv(h, s, v, nowait=True)


def do_waiting(bulb, color):
    """Pulse red a few times, end bright. Total ~1.5s; fine because the
    Notification hook fires when Claude is already idle waiting on the user."""
    dim = dict(color, v=max(10, int(color["v"]) // 5))
    for _ in range(3):
        set_color(bulb, dim)
        time.sleep(0.25)
        set_color(bulb, color)
        time.sleep(0.25)


def do_test(bulb, cfg):
    sequence = ("idle", "thinking", "tool-done", "waiting", "error")
    for state in sequence:
        print("claude-glow test: %s" % state)
        if state == "waiting":
            do_waiting(bulb, get_color(cfg, state))
        else:
            set_color(bulb, get_color(cfg, state))
        time.sleep(1.0)
    print("claude-glow test: idle (resting state)")
    set_color(bulb, get_color(cfg, "idle"))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in STATES:
        log("usage: python3 glow.py <%s>" % "|".join(STATES))
        return 0  # never fail the calling hook, even on bad args

    state = sys.argv[1]
    cfg = load_config()
    if cfg is None:
        return 0
    bulb = connect(cfg)
    if bulb is None:
        return 0

    try:
        if state == "off":
            bulb.turn_off(nowait=True)
        elif state == "test":
            do_test(bulb, cfg)
        elif state == "waiting":
            do_waiting(bulb, get_color(cfg, state))
        else:
            set_color(bulb, get_color(cfg, state))
    except Exception as e:
        log("bulb command failed (%s): %s. Doing nothing." % (state, e))
    finally:
        try:
            bulb.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
