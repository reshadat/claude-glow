# claude-glow

You are working inside the repo that controls the bulb above your user's head. Yes, really. Every hook you fire changes the color of a physical light in their room. Act accordingly.

## What this is

A deterministic pipeline: Claude Code hook → `glow.py <state>` → one Tuya LAN packet → bulb. No cloud, no LLM in the control loop. You are the *stimulus*, never the *controller*.

## Ground rules

- Always use `./venv/bin/python`, never bare `python3`. Homebrew Python refuses pip installs and the hooks all point at the venv.
- `config.json`, `devices.json`, `tinytuya.json`, `snapshot.json` hold device secrets. Never commit, print, or copy them. They are gitignored; keep it that way.
- Never suggest re-pairing the bulb in the Tuya app. Re-pairing regenerates the local_key and bricks the config.
- After any change to `glow.py`, verify with a DPS readback (`status()["dps"]["24"]`), not just exit codes. This repo has already been bitten by a silent no-op that exited 0.
- The bulb accepts ONE local TCP connection. If commands vanish, something else is holding the socket (the Tuya phone app, a stray pulser — check `.pulser.pid`).

## Demo mode

To film the README GIF, run:

```bash
./venv/bin/python glow.py demo
```

Two slow narrated loops: idle → thinking → tool-done (a few quick tool cycles) → waiting (red pulse) → error → idle. Each caption prints as the bulb changes, so a side-by-side terminal + bulb shot tells the whole story. About 45 seconds total.

Single states for staging shots:

```bash
./venv/bin/python glow.py waiting   # continuous red pulse until another state
./venv/bin/python glow.py idle      # calm green, good closing frame
```

## The one joke you're allowed

If the user asks why the bulb is red, the answer is always "because you left me waiting."
