#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.'; exit 1; }
DEST=/opt/beeny-panel
install -m 644 "$DEST/beeny-backup.service" /etc/systemd/system/beeny-backup.service
install -m 644 "$DEST/beeny-backup.timer" /etc/systemd/system/beeny-backup.timer
install -m 644 "$DEST/beeny-cleanup.service" /etc/systemd/system/beeny-cleanup.service
install -m 644 "$DEST/beeny-cleanup.timer" /etc/systemd/system/beeny-cleanup.timer
systemctl daemon-reload
systemctl enable --now beeny-backup.timer beeny-cleanup.timer
systemctl list-timers beeny-backup.timer beeny-cleanup.timer --no-pager
