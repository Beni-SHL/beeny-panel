#!/usr/bin/env bash
# Older entry point retained for users; additive upgrades now require the full package.
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT_DIR/scripts/update_panel.sh" "$@"
