"""Account-scoped OpenVPN sessions; no certificate-wide kill for a single device."""
import csv
import hashlib
import io
import re
import socket
import time


def disable_ccd(path):
    """Readable OpenVPN deny directive, preserving existing routes and addresses."""
    from pathlib import Path
    path=Path(path)
    if path.is_symlink():raise ValueError('CCD symlinks are not supported.')
    created=not path.parent.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    if created:path.parent.chmod(0o755)
    original=path.read_bytes() if path.is_file() else b''
    if not any(line.strip()==b'disable' for line in original.splitlines()):
        path.write_bytes(original+(b'\n' if original and not original.endswith(b'\n') else b'')+b'disable\n')
    path.chmod(0o644)


def enable_ccd(path):
    """Remove only the blocking directive, preserving addresses and routes."""
    from pathlib import Path
    path = Path(path)
    if path.is_symlink():
        raise ValueError('CCD symlinks are not supported.')
    if not path.is_file():
        return
    path.chmod(0o644)
    original = path.read_bytes()
    cleaned = b''.join(line for line in original.splitlines(keepends=True)
                       if line.strip() != b'disable')
    if cleaned == original:
        return
    if cleaned.strip():
        path.write_bytes(cleaned)
    else:
        path.unlink()


def parse_sessions(text, username):
    delimiter = '\t' if 'HEADER\tCLIENT_LIST' in text else ','
    header = None
    result = []
    for row in csv.reader(io.StringIO(text), delimiter=delimiter):
        if row[:2] == ['HEADER', 'CLIENT_LIST']:
            header = {name: idx for idx, name in enumerate(row[2:], 1)}
        elif row and row[0] == 'CLIENT_LIST' and header:
            def field(name):
                idx = header.get(name)
                return row[idx] if idx is not None and idx < len(row) else ''
            if field('Common Name') != username:
                continue
            cid = field('Client ID')
            if not re.fullmatch(r'\d{1,12}', cid):
                continue
            address = field('Real Address')
            since = field('Connected Since (time_t)')
            fingerprint = hashlib.sha256(f'{username}|{cid}|{address}|{since}'.encode()).hexdigest()
            try:
                received, sent = int(field('Bytes Received')), int(field('Bytes Sent'))
            except ValueError:
                continue
            result.append(dict(id=cid, fingerprint=fingerprint, address=address,
                virtual_address=field('Virtual Address'), connected_epoch=int(since) if since.isdigit() else 0, connected=field('Connected Since'),
                received=max(0, received), sent=max(0, sent)))
    if header is None:
        raise RuntimeError('OpenVPN did not return a supported session snapshot.')
    return result


class Management:
    def __enter__(self):
        import os
        port=int(os.environ.get('BEENY_MANAGEMENT_PORT','7505'))
        if not 1<=port<=65535:raise RuntimeError('Invalid management port.')
        unix_path=os.environ.get('BEENY_MANAGEMENT_SOCKET','')
        if unix_path:
            if not unix_path.startswith('/run/') or len(unix_path)>100:raise RuntimeError('Invalid management socket path.')
            self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(3);self.sock.connect(unix_path)
        else:self.sock = socket.create_connection(('127.0.0.1', port), timeout=3)
        self.sock.settimeout(3)
        self.stream = self.sock.makefile('rb')
        password_file=os.environ.get('BEENY_MANAGEMENT_PASSWORD_FILE','')
        if password_file:
            from pathlib import Path
            password=Path(password_file).read_text().strip()
            if not password or '\n' in password or '\r' in password:raise RuntimeError('Invalid management credential.')
            self.sock.sendall((password+'\n').encode())
        return self

    def __exit__(self, *args):
        self.stream.close()
        self.sock.close()

    def command(self, command, status=False):
        self.sock.sendall((command+'\n').encode('ascii'))
        lines = []
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            raw = self.stream.readline(65536)
            if not raw:
                raise RuntimeError('OpenVPN management connection closed.')
            line = raw.decode('utf-8', errors='replace').rstrip('\r\n')
            lines.append(line)
            if line.startswith('ERROR:'):
                raise RuntimeError('OpenVPN rejected the management command.')
            if (status and line == 'END') or (not status and line.startswith('SUCCESS:')):
                return '\n'.join(lines)
        raise RuntimeError('OpenVPN management response timed out.')


def local_sessions(username):
    from privileged import enabled,call
    if enabled():return call("sessions",username=username)
    with Management() as management:
        return parse_sessions(management.command('status 3', status=True), username)


def disconnect_session(username, client_id, fingerprint):
    from privileged import enabled,call
    if enabled():return call("disconnect",username=username,id=client_id,fingerprint=fingerprint)
    if not re.fullmatch(r'\d{1,12}', str(client_id)) or not re.fullmatch(r'[a-f0-9]{64}', str(fingerprint)):
        raise ValueError('Invalid session identifier.')
    with Management() as management:
        # Re-read immediately on the SAME connection; stale IDs never fall back to killing a username.
        sessions = parse_sessions(management.command('status 3', status=True), username)
        target = next((s for s in sessions if s['id'] == str(client_id) and s['fingerprint'] == fingerprint), None)
        if not target:
            raise ValueError('Session ended or changed. Refresh the connection list.')
        import logging
        logging.warning('Beeny requested a single-session disconnect username=%s session_id=%s peer=%s',username,client_id,target['address'])
        management.command('client-kill '+str(client_id))
