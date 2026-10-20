#!/usr/bin/env bash
# Fixed installation paths; the web and bot workers have no root privileges.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.'; exit 1; }
DEST=/opt/beeny-panel
command -v tc >/dev/null || { apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y iproute2; }
getent passwd beeny >/dev/null || useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin beeny
chmod 755 "$DEST"
find "$DEST" -maxdepth 1 -type f -name '*.py' -exec chown root:root {} + -exec chmod 644 {} +
for code_dir in static templates scripts node_agent; do
  if [[ -d "$DEST/$code_dir" ]]; then
    chown -R root:root "$DEST/$code_dir"
    find "$DEST/$code_dir" -type d -exec chmod 755 {} +
    find "$DEST/$code_dir" -type f -exec chmod 644 {} +
  fi
done
if [[ -d "$DEST/.venv-releases" ]]; then chmod 755 "$DEST/.venv-releases"; fi
install -d -o beeny -g beeny -m 700 "$DEST/instance"
chown -R beeny:beeny "$DEST/instance"
find "$DEST/instance" -type d -exec chmod 700 {} +
find "$DEST/instance" -type f -exec chmod 600 {} +
chown beeny:beeny "$DEST/config.json"
chmod 600 "$DEST/config.json"
install -d -o root -g beeny -m 750 "$DEST/backups"
# Old upgrade snapshots remain private to root; signed snapshots are readable by the owner UI.
find "$DEST/backups" -maxdepth 1 -type f -name '*.tar.gz' -exec chown root:beeny {} + -exec chmod 640 {} +
find "$DEST/backups" -maxdepth 1 -type f -name '*.db' -exec chown root:beeny {} + -exec chmod 640 {} +
ENV_FILE=/etc/beeny-panel/panel.env
sed -i '/^BEENY_PRIVILEGE_SOCKET=/d' "$ENV_FILE"
printf '%s\n' 'BEENY_PRIVILEGE_SOCKET=/run/beeny-panel/privileged.sock' >> "$ENV_FILE"
chmod 600 "$ENV_FILE"
chmod 755 "$DEST/scripts/vpn_disconnect.py" "$DEST/scripts/vpn_admission.py"
install -m 644 "$DEST/beeny-privileged.service" /etc/systemd/system/beeny-privileged.service
install -m 644 "$DEST/beeny-vpn-recovery.service" /etc/systemd/system/beeny-vpn-recovery.service
systemctl daemon-reload
systemctl enable beeny-vpn-recovery.service
systemctl enable beeny-privileged
systemctl restart beeny-privileged
