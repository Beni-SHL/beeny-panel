#!/usr/bin/env bash
# Public repository installer; this file must be published with the release first.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
[[ ! -e /opt/beeny-panel/app.py ]] || { echo 'Panel already installed. Use beeny → Update or scripts/update_panel.sh.' >&2; exit 1; }
command -v git >/dev/null || { apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y git ca-certificates; }
checkout="$(mktemp -d /root/beeny-install.XXXXXXXX)"
trap 'rm -rf -- "$checkout"' EXIT
GIT_TERMINAL_PROMPT=0 git -c credential.helper= clone --depth 1 --branch main https://github.com/Beni-SHL/beeny-panel.git "$checkout"
python3 - "$checkout/VERSION" <<'PYVERSION'
import pathlib,re,sys
value=pathlib.Path(sys.argv[1]).read_text().strip()
if not re.fullmatch(r'\d+\.\d+\.\d+',value) or tuple(map(int,value.split('.')))<(3,6,9):raise SystemExit('Publish release 3.6.9 or newer to GitHub before using this bootstrap.')
PYVERSION
bash "$checkout/install.sh"
