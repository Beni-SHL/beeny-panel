#!/usr/bin/env bash
# Public repository installer; this file must be published with the release first.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
if [[ -x /opt/beeny-panel/venv/bin/python && -f /opt/beeny-panel/scripts/beenyctl.py ]]; then
  exec /opt/beeny-panel/venv/bin/python /opt/beeny-panel/scripts/beenyctl.py
fi
command -v git >/dev/null || { apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y git ca-certificates; }
checkout="$(mktemp -d /root/beeny-install.XXXXXXXX)"
trap 'rm -rf -- "$checkout"' EXIT
GIT_TERMINAL_PROMPT=0 git -c credential.helper= clone --depth 1 --branch main https://github.com/Beni-SHL/beeny-panel.git "$checkout"
python3 - "$checkout/VERSION" <<'PYVERSION'
import pathlib,re,sys
value=pathlib.Path(sys.argv[1]).read_text().strip()
if not re.fullmatch(r'\d+\.\d+\.\d+',value) or tuple(map(int,value.split('.')))<(3,7,1):raise SystemExit('Publish release 3.7.1 or newer to GitHub before using this bootstrap.')
PYVERSION
python3 "$checkout/scripts/beenyctl.py"
