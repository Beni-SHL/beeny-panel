"""Account-scoped OpenVPN sessions; no certificate-wide kill for a single device."""
import csv
import hashlib
import io
import re
import socket
import time


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
                virtual_address=field('Virtual Address'), connected=field('Connected Since'),
                received=max(0, received), sent=max(0, sent)))
    if header is None:
        raise RuntimeError('OpenVPN did not return a supported session snapshot.')
    return result


class Management:
    def __enter__(self):
        self.sock = socket.create_connection(('127.0.0.1', 7505), timeout=3)
        self.sock.settimeout(3)
        self.stream = self.sock.makefile('rb')
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
    with Management() as management:
        return parse_sessions(management.command('status 3', status=True), username)


def disconnect_session(username, client_id, fingerprint):
    if not re.fullmatch(r'\d{1,12}', str(client_id)) or not re.fullmatch(r'[a-f0-9]{64}', str(fingerprint)):
        raise ValueError('Invalid session identifier.')
    with Management() as management:
        # Re-read immediately on the SAME connection; stale IDs never fall back to killing a username.
        sessions = parse_sessions(management.command('status 3', status=True), username)
        target = next((s for s in sessions if s['id'] == str(client_id) and s['fingerprint'] == fingerprint), None)
        if not target:
            raise ValueError('Session ended or changed. Refresh the connection list.')
        management.command('client-kill '+str(client_id))
