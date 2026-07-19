#!/usr/bin/env python3
"""claude-glow: drive a Tuya/Halonix smart bulb from Claude Code hook events.

Usage: python3 glow.py <state>
States: idle, thinking, tool-done, waiting, error, off, test

Deterministic hook -> bulb pipeline. No LLM anywhere in the loop.
Designed to never break a calling hook: all failures log to stderr and exit 0.
"""

import json
import os
import signal
import subprocess
import sys
import time

STATES = ("idle", "thinking", "tool-done", "waiting", "error", "off", "test", "demo", "_pulse")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
PIDFILE = os.path.join(BASE_DIR, ".pulser.pid")
PULSE_MAX_SECONDS = 300

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
        # BulbDevice must know its DPS layout before set_hsv; nowait packets
        # skip auto-detection, so probe once (cheap on LAN) and fall back to
        # the configured bulb type (Halonix uses DPS 20-26 = type "B").
        try:
            bulb.status()
        except Exception:
            pass
        if not getattr(bulb, "bulb_configured", True):
            try:
                bulb.set_bulb_type(cfg.get("bulb_type", "B"))
            except Exception:
                pass
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
    """Turn bulb on and apply HSV. Blocking sends: closing the socket right
    after a fire-and-forget packet RSTs the connection and the bulb drops the
    command, so we pay ~100ms on the LAN for a confirmed delivery instead."""
    h = max(0.0, min(360.0, float(color["h"]))) / 360.0
    s = max(0.0, min(100.0, float(color["s"]))) / 100.0
    v = max(0.0, min(100.0, float(color["v"]))) / 100.0
    bulb.turn_on(nowait=True)
    bulb.set_hsv(h, s, v)


def kill_pulser():
    """Stop a background pulser from a previous 'waiting' state, if any.

    Tuya bulbs accept a single local TCP connection, so we must wait for the
    pulser to actually die (freeing the bulb's slot) before the caller
    connects, or the next color command is silently lost."""
    pid = None
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pid = None
    try:
        os.remove(PIDFILE)
    except OSError:
        pass
    if pid is None:
        return
    for _ in range(20):  # up to 2s for the process to exit
        try:
            os.kill(pid, 0)
        except OSError:
            break
        time.sleep(0.1)
    time.sleep(0.3)  # let the bulb notice the closed socket


def start_pulser():
    """Spawn a detached child running the _pulse loop and record its pid.
    The parent returns immediately so the calling hook never blocks."""
    with open(os.devnull, "wb") as devnull:
        proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "_pulse"],
            stdout=devnull, stderr=devnull,
            start_new_session=True,
        )
    with open(PIDFILE, "w") as f:
        f.write(str(proc.pid))


def pulse_settings(cfg):
    """Pulse tuning from config.json's optional "pulse" block."""
    p = cfg.get("pulse") or {}
    interval = max(0.2, float(p.get("interval", 0.4)))
    max_seconds = max(1, int(p.get("max_seconds", PULSE_MAX_SECONDS)))
    dim_percent = max(1, min(100, int(p.get("dim_percent", 20))))
    return interval, max_seconds, dim_percent


def do_pulse_loop(bulb, cfg, color):
    """Continuous dim/bright pulse until killed by the next state change,
    capped at pulse.max_seconds so an abandoned session can't strobe all
    night. Ends bright so a timed-out pulse still leaves the 'come look'
    color."""
    interval, max_seconds, dim_percent = pulse_settings(cfg)
    dim = dict(color, v=max(10, int(color["v"]) * dim_percent // 100))
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        set_color(bulb, dim)
        time.sleep(interval)
        set_color(bulb, color)
        time.sleep(interval)


def do_waiting(bulb, color):
    """Show bright red immediately, then hand off to a background pulser."""
    set_color(bulb, color)
    start_pulser()


def do_test(bulb, cfg):
    sequence = ("idle", "thinking", "tool-done", "waiting", "error")
    for state in sequence:
        print("claude-glow test: %s" % state)
        if state == "waiting":
            # inline short pulse; the background pulser is for real hooks only
            color = get_color(cfg, state)
            dim = dict(color, v=max(10, int(color["v"]) // 5))
            for _ in range(3):
                set_color(bulb, dim)
                time.sleep(0.4)
                set_color(bulb, color)
                time.sleep(0.4)
        else:
            set_color(bulb, get_color(cfg, state))
        time.sleep(1.0)
    print("claude-glow test: idle (resting state)")
    set_color(bulb, get_color(cfg, "idle"))


DEMO_SCRIPT = [
    ("idle",      2.5, "session idle, Claude is asleep"),
    ("thinking",  2.5, "you asked for something, tool spinning up"),
    ("tool-done", 2.5, "tool finished, results in"),
    ("thinking",  1.2, "another tool"),
    ("tool-done", 1.2, "done"),
    ("thinking",  0.8, "another"),
    ("tool-done", 0.8, "done"),
    ("waiting",   None, "Claude needs YOU (pulsing)"),
    ("error",     2.5, "something broke"),
    ("idle",      2.5, "back to sleep"),
]


def do_demo(bulb, cfg, loops=2):
    """Slow, narrated state cycle paced for screen-recording a GIF."""
    for n in range(loops):
        print("--- demo loop %d/%d ---" % (n + 1, loops))
        for state, hold, caption in DEMO_SCRIPT:
            print("%-9s  %s" % (state, caption))
            color = get_color(cfg, state)
            if state == "waiting":
                dim = dict(color, v=max(10, int(color["v"]) // 5))
                for _ in range(4):
                    set_color(bulb, dim)
                    time.sleep(0.4)
                    set_color(bulb, color)
                    time.sleep(0.4)
            else:
                set_color(bulb, color)
                time.sleep(hold)
    print("demo over, resting at idle")
    set_color(bulb, get_color(cfg, "idle"))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in STATES:
        log("usage: python3 glow.py <%s>" % "|".join(s for s in STATES if not s.startswith("_")))
        return 0  # never fail the calling hook, even on bad args

    state = sys.argv[1]
    if state != "_pulse":
        # any state change silences a leftover pulser first
        kill_pulser()
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
        elif state == "demo":
            do_demo(bulb, cfg)
        elif state == "waiting":
            do_waiting(bulb, get_color(cfg, state))
        elif state == "_pulse":
            do_pulse_loop(bulb, cfg, get_color(cfg, "waiting"))
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
