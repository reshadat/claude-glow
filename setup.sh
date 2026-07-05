#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f config.json ]; then
    cp config.example.json config.json
    echo "Created config.json from config.example.json."
else
    echo "config.json already exists, leaving it alone."
fi

echo "Installing requirements..."
python3 -m pip install -r requirements.txt

cat <<'EOF'

Next steps:
1. Get your bulb's device_id, local_key and ip:
       python3 -m tinytuya wizard
   (needs a free Tuya IoT platform account, see README.md)
2. Fill those three values into config.json.
3. Verify the bulb responds:
       python3 glow.py test
4. Wire the hooks: merge hooks.example.json into ~/.claude/settings.json.
EOF
