#!/usr/bin/env bash
# Manual package uses the same transactional upgrade as the GitHub release.
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT_DIR/scripts/update_panel.sh" "$@"
