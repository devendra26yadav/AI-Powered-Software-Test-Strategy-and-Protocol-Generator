#!/bin/bash
set -euo pipefail

# Include common uv locations when the shell has a short PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:${HOME}/.local/bin:${PATH}"

cd "$(dirname "$0")/test_strategy_protocol_generator"

echo "Starting Test Strategy Protocol Generator UI..."
echo "Open the URL printed below in your browser."
echo

uv run python -m test_strategy_protocol_generator.main

echo
echo "The UI stopped. Press Enter to close this window."
read -r
