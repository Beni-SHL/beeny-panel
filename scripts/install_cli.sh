#!/usr/bin/env bash
set -Eeuo pipefail
# Copy the previous launcher in the updater before calling this script.
temporary="$(mktemp /usr/local/bin/.beeny.XXXXXXXX)"
printf '%s\n' '#!/usr/bin/env bash' 'exec /opt/beeny-panel/venv/bin/python /opt/beeny-panel/scripts/beenyctl.py "$@"' > "$temporary"
chmod 755 "$temporary"
mv -f -- "$temporary" /usr/local/bin/beeny
