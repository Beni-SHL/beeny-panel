#!/usr/bin/env python3
"""Migrate a verified pre-env installation, then use the normal backed-up updater."""
import ast
import datetime
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
from urllib.parse import urlsplit

PRIMARY_KEY = '__beeny_local_primary__'


def inspect_install(root, vpn):
    for rel in ('app.py', 'config.json', 'instance/beeny.db', 'venv/bin/python'):
        if not (root/rel).exists():
            raise ValueError('Missing legacy installation file: '+rel)
    cfg = json.loads((root/'config.json').read_text())
    path = cfg.get('panel_path', '')
    if not isinstance(path, str) or not path.startswith('/') or any(c in path for c in '\r\n?#'):
        raise ValueError('Unsupported panel path.')
    tree = ast.parse((root/'app.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Node')
    table = next(ast.literal_eval(n.value) for n in node.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == '__tablename__' for t in n.targets))
    if table != 'nodes':
        raise ValueError('This legacy adapter expects Node.__tablename__ = nodes.')
    ports = [ast.literal_eval(k.value) for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
             and n.func.value.id == 'app' and n.func.attr == 'run'
             for k in n.keywords if k.arg == 'port' and isinstance(k.value, ast.Constant)]
    if len(set(ports)) != 1 or not isinstance(ports[0], int) or not 1 <= ports[0] <= 65535:
        raise ValueError('Cannot determine the legacy panel port safely.')
    conf = vpn/'server/server.conf'
    if not conf.exists():
        conf = vpn/'server.conf'
    directives = {}
    for line in conf.read_text().splitlines():
        row = line.strip().split()
        if row and not row[0].startswith(('#', ';')):
            directives.setdefault(row[0], []).append(row[1:])
    if directives.get('proto', [[]])[-1] not in (['tcp'], ['tcp-server']):
        raise ValueError('This release generates TCP profiles; legacy VPN protocol is incompatible.')
    if directives.get('management', [[]])[-1][:2] != ['127.0.0.1', '7505']:
        raise ValueError('Expected a localhost management interface on port 7505.')
    tls = directives.get('tls-auth', [[]])[-1]
    if len(tls) != 2 or tls[1] != '0' or 'tls-crypt' in directives:
        raise ValueError('Expected the existing tls-auth server key and direction 0.')
    ta = Path(tls[0])
    if not ta.is_absolute():
        raise ValueError('Relative tls-auth paths require manual review.')
    if not ta.is_file() or not ta.read_bytes():
        raise ValueError('Existing tls-auth key is missing.')
    canonical = vpn/'ta.key'
    if canonical.exists() and canonical.read_bytes() != ta.read_bytes():
        raise ValueError('Different keys exist at old and canonical TLS paths. No keys were changed.')
    expected_ca = vpn/'easy-rsa/pki/ca.crt'
    if directives.get('ca', [[]])[-1] != [str(expected_ca)] or not expected_ca.is_file():
        raise ValueError('Unexpected CA layout. No certificates were changed.')
    for directive in ('cert', 'key'):
        values = directives.get(directive, [[]])[-1]
        if not values or not Path(values[0]).is_file():
            raise ValueError('Server '+directive+' file is missing.')
    vpn_port = int(directives['port'][-1][0])
    if not 1 <= vpn_port <= 65535:
        raise ValueError('Invalid VPN port.')
    with sqlite3.connect(f'file:{root/"instance/beeny.db"}?mode=ro', uri=True) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Database integrity check failed.')
        cols = {r[1] for r in db.execute('PRAGMA table_info(nodes)')}
        if not {'id','name','ip','host','country','api_key'}.issubset(cols):
            raise ValueError('Unsupported node schema.')
        nodes = [dict(zip(('id','name','ip','host','api_key'), row)) for row in db.execute('SELECT id,name,ip,host,api_key FROM nodes')]
        # Password material is checked privately, never printed or exported.
        hashes = [r[0] for r in db.execute('SELECT password FROM admin')]
        if not hashes or any(not isinstance(h, str) or not h.startswith(('scrypt:', 'pbkdf2:')) for h in hashes):
            raise ValueError('Legacy admin password format needs a separate migration.')
        counts = {t: db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('user','nodes','user_nodes')}
    return dict(config=cfg, panel_port=ports[0], vpn_port=vpn_port, tls=ta, nodes=nodes, counts=counts)


def promote_primary(database, primary):
    with sqlite3.connect(database) as db:
        current = db.execute('SELECT api_key FROM nodes WHERE id=?', (primary['id'],)).fetchone()
        if current is None or current[0] != primary['api_key']:
            raise ValueError('Selected node changed during preparation. Retry.')
        db.execute('UPDATE nodes SET api_key=? WHERE id=?', (PRIMARY_KEY, primary['id']))
        # First polling establishes baselines, rather than re-counting bytes already in old accounts.
        db.execute('CREATE TABLE IF NOT EXISTS traffic_baseline (node_id INTEGER PRIMARY KEY, pending BOOLEAN NOT NULL DEFAULT 1)')
        db.execute('INSERT OR REPLACE INTO traffic_baseline(node_id,pending) SELECT id,1 FROM nodes')


def host_input(default):
    value = input('VPN hostname or public IP of THIS VPS ['+default+']: ').strip() or default
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', value):
        raise ValueError('Invalid VPN hostname/IP.')
    try:
        if not ipaddress.ip_address(value).is_global:
            raise ValueError('VPN address must be public, not localhost/private.')
    except ValueError as exc:
        if value.replace('.', '').isdigit() or value.lower() == 'localhost':
            raise ValueError('Invalid public VPN address.') from exc
        if '.' not in value:
            raise ValueError('Use a public IP or a fully qualified hostname.') from exc
    return value


def main():
    if os.geteuid() != 0:
        raise ValueError('Run this migration as root.')
    root = Path('/opt/beeny-panel'); vpn = Path('/etc/openvpn')
    env = Path('/etc/beeny-panel/panel.env')
    if env.exists():
        raise ValueError('panel.env already exists. Use the normal updater; legacy mode is only for pre-env installations.')
    if not sys.stdin.isatty():
        raise ValueError('Run interactively to identify the original local node.')
    facts = inspect_install(root, vpn)
    print('Legacy layout verified. Existing panel path:', facts['config']['panel_path'])
    print('Accounts / nodes / assignments:', facts['counts'])
    print('Choose the existing node for THIS VPS. Do not select the England/remote node:')
    for n in facts['nodes']:
        host = urlsplit(n['host'] if '://' in (n['host'] or '') else '//'+(n['host'] or '')).hostname
        print(n['id'], repr(n['name']), 'IP:', n['ip'], 'Host:', host or '-')
    primary_id = int(input('Existing local node ID: ').strip())
    primary = next((n for n in facts['nodes'] if n['id'] == primary_id), None)
    if primary is None:
        raise ValueError('Select an existing local node; no new node will be created.')
    default = urlsplit(primary['host'] if '://' in (primary['host'] or '') else '//'+(primary['host'] or '')).hostname or primary['ip']
    public_host = host_input(default)
    https = input('Do you already access the panel through HTTPS? [y/N]: ').strip().lower()
    if https not in ('','n','no','y','yes'):
        raise ValueError('Answer y or n.')
    # No ports, paths, certificates, usernames or remote node keys are rewritten.
    values = dict(BEENY_SECRET_KEY=secrets.token_urlsafe(48), BEENY_PUBLIC_HOST=public_host,
                  BEENY_VPN_PORT=str(facts['vpn_port']), BEENY_BIND='0.0.0.0',
                  BEENY_PORT=str(facts['panel_port']), BEENY_PUBLIC_HTTPS='1' if https in ('y','yes') else '')
    lock = os.open('/run/beeny-panel-update.lock', os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.dup2(lock, 9); os.set_inheritable(9, True)
    if env.exists():
        raise ValueError('Another migration already prepared the environment.')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = root/'backups'/('legacy-'+stamp+'-'+str(os.getpid()))
    backup.mkdir(parents=True, mode=0o700)
    backup.chmod(0o700)
    unit = Path('/etc/systemd/system/beeny-panel.service')
    shutil.copy2(unit, backup/'panel.service')
    shutil.copy2(root/'config.json', backup/'config.json')
    (backup/'node-state.json').write_text(json.dumps(primary))
    (backup/'node-state.json').chmod(0o600)
    was_active = subprocess.run(['systemctl','is-active','--quiet','beeny-panel']).returncode == 0
    canonical = vpn/'ta.key'; made_link = False; promoted = False; wrote_env = False
    try:
        subprocess.run(['systemctl','stop','beeny-panel'],check=True)
        with sqlite3.connect(root/'instance/beeny.db') as source, sqlite3.connect(backup/'beeny.db') as target:
            source.backup(target)
        env.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(env, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        wrote_env = True
        with os.fdopen(fd,'w') as stream:
            stream.write(''.join(k+'='+v+'\n' for k,v in values.items()))
        if not canonical.exists():
            canonical.symlink_to(facts['tls']); made_link = True
        promote_primary(root/'instance/beeny.db', primary); promoted = True
        child_env = dict(os.environ, BEENY_UPDATE_LOCK_FD='9')
        subprocess.run(['bash', str(Path(__file__).with_name('update_panel.sh'))], env=child_env, pass_fds=(9,), check=True)
    except BaseException:
        if promoted:
            subprocess.run(['systemctl','stop','beeny-panel','beeny-customer-worker'],check=False)
            with sqlite3.connect(root/'instance/beeny.db') as db:
                db.execute('UPDATE nodes SET api_key=? WHERE id=? AND api_key=?', (primary['api_key'],primary_id,PRIMARY_KEY))
                db.execute('DELETE FROM traffic_baseline')
        if made_link and canonical.is_symlink() and canonical.resolve() == facts['tls'].resolve():
            canonical.unlink()
        if wrote_env:
            env.unlink(missing_ok=True)
        shutil.copy2(backup/'panel.service',unit)
        subprocess.run(['systemctl','daemon-reload'],check=False)
        if was_active:
            subprocess.run(['systemctl','start','beeny-panel'],check=False)
        print('Legacy preparation rolled back. Backup:', backup, file=sys.stderr)
        raise
    print('Legacy upgrade complete. Original account IDs, node IDs and assignments preserved.')
    print('Original login path:', facts['config']['panel_path']+'/login')
    print('Legacy backup:', backup)
    print('Admin credentials remain unchanged. Customer page passwords must be configured separately.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, StopIteration, subprocess.CalledProcessError) as exc:
        # Never print exception strings that could contain URLs/tokens from external tools.
        if isinstance(exc, ValueError):
            print(str(exc),file=sys.stderr)
        else:
            print('Legacy migration failed. Check the preceding output and backup; no certificates were regenerated.',file=sys.stderr)
        sys.exit(1)
