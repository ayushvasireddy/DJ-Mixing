#!/bin/bash
# Double-click this file in Finder to set up (first run only) and launch the AI DJ.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "First-time setup: creating a Python environment and installing packages."
  echo "This can take a few minutes -- don't close this window."
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
else
  source .venv/bin/activate
fi

echo "Starting the AI DJ -- your browser will open automatically."
python -m dj_mixing.webapp
