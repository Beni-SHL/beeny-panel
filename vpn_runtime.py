"""Explicit single-listener transport changes, with durable timed rollback.

One active transport per node preserves existing accounting, admission and PKI.
TCP and UDP keep independent ports; changing transport never creates a second,
unaccounted VPN instance. Profile downloads read this runtime source of truth.
"""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path('/etc/openvpn/beeny-runtime')
CONFIG = Path('/etc/openvpn/server/server.conf')
SERVICE = 'openvpn-server@server'

def run(*args, check=True):
    return subprocess.run(args, capture_output=True, text=True, check=check, timeout=35)

def save(name, value):
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = ROOT / name
    temp = target.with_suffix('.tmp')
    with temp.open('w') as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, target)

def load(name, default=None):
    path = ROOT / name
    return json.loads(path.read_text()) if path.is_file() else default

@contextlib.contextmanager
def lock():
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (ROOT / 'lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield

def settings(text):
    found = {}
    for line in text.splitlines():
        parts = shlex.split(line, comments=True)
        if parts and parts[0] in {'port', 'proto', 'local', 'config', 'port-share'}:
            if parts[0] in found:raise ValueError('Duplicate OpenVPN listener directives require manual review.')
            found[parts[0]] = parts[1:]
    if 'config' in found or 'port-share' in found:
        raise ValueError('Included configuration or port-sharing requires manual review.')
    proto = found.get('proto', ['udp'])[0]
    if proto not in {'tcp', 'tcp-server', 'udp', 'tcp4-server', 'udp4'}:
        raise ValueError('Only IPv4 TCP-server and UDP listeners are supported here.')
    return dict(proto='tcp' if proto.startswith('tcp') else 'udp',
                port=port(found.get('port', ['1194'])[0]), local=found.get('local', ['0.0.0.0'])[0])

def port(value):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,5}', str(value)) or not 1 <= int(value) <= 65535:
        raise ValueError('Port must be 1–65535.')
    return int(value)

def transform(text, proto, chosen):
    if proto not in {'tcp', 'udp'}:raise ValueError('Protocol must be TCP or UDP.')
    settings(text)
    replacement = {'port': 'port ' + str(port(chosen)), 'proto': 'proto ' + ('tcp-server' if proto == 'tcp' else 'udp')}
    seen = set(); result = []
    for line in text.splitlines():
        parts = shlex.split(line, comments=True)
        key = parts[0] if parts else ''
        if key in replacement:
            result.append(replacement[key]); seen.add(key)
        else:result.append(line)
    result.extend(value for key, value in replacement.items() if key not in seen)
    return '\n'.join(result) + '\n'

def write_config(text):
    if CONFIG.is_symlink():raise ValueError('Symlinked OpenVPN configurations require manual review.')
    stat = CONFIG.stat(); tmp = CONFIG.with_suffix('.beeny.tmp')
    with tmp.open('w') as stream:
        os.chmod(tmp, stat.st_mode & 0o777); os.chown(tmp, stat.st_uid, stat.st_gid)
        stream.write(text); stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp, CONFIG)

def health(proto, chosen):
    run('systemctl', 'is-active', '--quiet', SERVICE)
    pid = run('systemctl', 'show', '-p', 'MainPID', '--value', SERVICE).stdout.strip()
    # Require the actual OpenVPN PID bound to the requested protocol and port.
    output = run('ss', '-H', '-lnpt' if proto == 'tcp' else '-lnpu', 'sport = :' + str(chosen)).stdout
    if not pid.isdigit() or pid == '0' or not re.search(r'pid=' + re.escape(pid) + r'\b', output):
        raise RuntimeError('OpenVPN listener did not pass its protocol/port health check.')

def status():
    text = CONFIG.read_text(); actual = settings(text)
    saved = load('ports.json', {})
    ports = dict(tcp=port(saved.get('tcp', 110)), udp=port(saved.get('udp', 1194)))
    ports[actual['proto']] = actual['port']
    active = run('systemctl', 'is-active', '--quiet', SERVICE, check=False).returncode == 0
    if active:health(actual['proto'], actual['port'])
    pending = load('pending.json')
    return dict(success=True, **actual, tcp_port=ports['tcp'], udp_port=ports['udp'], active=active,
                revision=hashlib.sha256(text.encode()).hexdigest(),
                pending={k: pending[k] for k in ('token', 'deadline')} if pending else None)

def restore(record):
    # Do not overwrite a newer external configuration or silently lose operator changes.
    current = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    if current not in {record['new_revision'], record['old_revision']}:
        raise RuntimeError('External OpenVPN edits detected; manual rollback required. Original is in beeny-runtime/pending.json.')
    write_config(record['previous']); save('ports.json', record['ports'])
    run('systemctl', 'restart', SERVICE)
    previous = settings(record['previous']); health(previous['proto'], previous['port'])
    (ROOT / 'pending.json').unlink()

def handle(action, data=None, revision=None):
    with lock():
        pending = load('pending.json')
        if pending and pending['deadline'] <= time.time():
            restore(pending); pending = None
        if action == 'status':return status()
        if action in {'confirm', 'rollback'}:
            if not pending or pending['token'] != revision:raise ValueError('No matching pending change. Refresh the node.')
            if action == 'rollback':restore(pending)
            else:
                if hashlib.sha256(CONFIG.read_bytes()).hexdigest()!=pending['new_revision']:
                    raise ValueError('OpenVPN changed externally. Do not confirm this pending change.')
                actual = settings(CONFIG.read_text()); health(actual['proto'], actual['port'])
                (ROOT / 'pending.json').unlink()
            return status()
        if action != 'apply':raise ValueError('Invalid listener action.')
        if pending:raise ValueError('Confirm or roll back the pending listener change first.')
        data = data or {}
        if not isinstance(data,dict):raise ValueError('Invalid listener data.')
        current = status()
        if revision != current['revision']:raise ValueError('OpenVPN changed. Refresh before applying.')
        proto = data.get('proto'); ports = dict(tcp=port(data.get('tcp_port')), udp=port(data.get('udp_port')))
        if proto not in ports:raise ValueError('Protocol must be TCP or UDP.')
        before = CONFIG.read_text(); after = transform(before, proto, ports[proto])
        if before == after:
            save('ports.json', ports); return status()
        # A paired exit maps the local listener. Never silently leave its clients
        # pointing at a dead local port after a transport switch.
        pair_file=Path('/etc/openvpn/beeny-tunnel/pair.json')
        if pair_file.is_file():
            pair=json.loads(pair_file.read_text())
            if pair.get('role')=='exit' and run('systemctl','is-active','--quiet','beeny-tunnel-exit',check=False).returncode==0:
                raise ValueError('Disable the paired tunnel before changing this listener, then pair it again with the new port.')
        # Binding is checked before touching the running service; same existing bind is exempt.
        if (proto, ports[proto]) != (current['proto'], current['port']):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM if proto == 'tcp' else socket.SOCK_DGRAM) as probe:
                probe.bind((current['local'], ports[proto]))
        token = uuid.uuid4().hex
        record = dict(token=token, deadline=time.time()+120, previous=before,
                      ports=dict(tcp=current['tcp_port'], udp=current['udp_port']),
                      old_revision=current['revision'], new_revision=hashlib.sha256(after.encode()).hexdigest())
        save('pending.json', record)
        try:
            run('systemd-run', '--quiet', '--collect', '--on-active=120s', '--unit=beeny-vpn-rollback-'+token,
                sys.executable, str(Path(__file__).resolve()), 'expire', token)
        except Exception:
            (ROOT / 'pending.json').unlink(); raise
        try:
            write_config(after); save('ports.json', ports)
            run('systemctl', 'restart', SERVICE); health(proto, ports[proto])
        except Exception:
            restore(record); raise
        return status()

def recover_boot():
    with lock():
        pending=load('pending.json')
        if not pending:return
        current=hashlib.sha256(CONFIG.read_bytes()).hexdigest()
        if current not in {pending['new_revision'],pending['old_revision']}:raise RuntimeError('External edits require manual review before starting OpenVPN.')
        write_config(pending['previous']);save('ports.json',pending['ports']);(ROOT/'pending.json').unlink()

if __name__ == '__main__':
    if sys.argv[1:]==['recover-boot']:
        recover_boot();raise SystemExit(0)
    if len(sys.argv) != 3 or sys.argv[1] != 'expire':raise SystemExit('Only the fixed expiry and boot recovery operations are supported.')
    with lock():
        pending = load('pending.json')
        if pending and pending['token'] == sys.argv[2]:restore(pending)
