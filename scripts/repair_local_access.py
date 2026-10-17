#!/usr/bin/env python3
"""Remove stale local CCD disable directives; never change database or quotas."""
import argparse
from datetime import date, datetime
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile


def repair(database, ccd_dir, backup_dir, apply=False):
    changed = []
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        columns={row[1] for row in db.execute('PRAGMA table_info(user)')}
        policy="u.quota_mode" if 'quota_mode' in columns else "'metered'"
        pending="u.speed_sync_pending" if 'speed_sync_pending' in columns else "0"
        rows = db.execute(f'''SELECT DISTINCT u.id, u.username, u.expire_date,
                u.traffic_limit, u.traffic_usage, {policy}, {pending} FROM user u
            JOIN user_nodes un ON un.user_id=u.id JOIN nodes n ON n.id=un.node_id
            WHERE u.status='active' AND u.customer_paused=0
                AND n.api_key='__beeny_local_primary__' ''').fetchall()
        has_devices = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_devices'").fetchone()
        for uid, username, expiry, limit, usage, mode, pending in rows:
            if pending or (limit and (usage or 0) >= limit and mode!='fair_use'):
                continue
            if expiry and expiry != '-' and not expiry.isdigit():
                try:
                    if date.fromisoformat(expiry) < date.today():
                        continue
                except ValueError:
                    continue
            names = [username]
            if has_devices:
                names += [r[0] for r in db.execute('SELECT common_name FROM account_devices WHERE user_id=? AND blocked=0', (uid,))]
            for name in names:
                if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}', name):
                    continue
                path = ccd_dir / name
                if path.is_symlink() or not path.is_file():
                    continue
                original = path.read_bytes()
                lines = original.splitlines(keepends=True)
                # Explicit comparison avoids interpreting comments or other directives.
                clean = b''.join(line for line in lines if line.strip() != b'disable')
                if clean == original:
                    continue
                if apply:
                    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                    shutil.copy2(path, backup_dir / name)
                    stat = path.stat()
                    fd, temporary = tempfile.mkstemp(prefix='.access-repair-', dir=ccd_dir)
                    try:
                        with os.fdopen(fd, 'wb') as stream:
                            stream.write(clean)
                        os.chmod(temporary, stat.st_mode & 0o777)
                        os.chown(temporary, stat.st_uid, stat.st_gid)
                        if path.is_symlink() or path.read_bytes() != original:
                            raise RuntimeError('CCD changed during repair; retry: '+name)
                        os.replace(temporary, path)
                    finally:
                        Path(temporary).unlink(missing_ok=True)
                changed.append(name)
    return changed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Back up and remove stale disable lines; otherwise preview only')
    args = parser.parse_args()
    if args.apply and os.geteuid() != 0:
        raise SystemExit('Run with sudo or as root.')
    backup = Path('/root') / ('beeny-access-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    changed = repair(Path('/opt/beeny-panel/instance/beeny.db'), Path('/etc/openvpn/ccd'), backup, args.apply)
    for name in changed:
        print(('Repaired: ' if args.apply else 'Would repair: ')+name)
    print('Accounts/device identities:', len(changed))
    print('Database, traffic and VPN service were not changed.')
    if args.apply and changed:
        print('CCD backup:', backup)
