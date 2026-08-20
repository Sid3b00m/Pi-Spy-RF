#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt
if [[ ! -f config/config.yaml ]]; then
  cp config/config.example.yaml config/config.yaml
fi
exec python -m app.main
