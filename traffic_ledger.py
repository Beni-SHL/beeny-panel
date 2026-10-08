"""Parse OpenVPN status-version 1/2 snapshots for durable bandwidth accounting."""
import csv
import io


def parse_status(log_text):
    """Return (username, session_key, received, sent, address) per client."""
    if not log_text:
        return []
    reader = csv.reader(io.StringIO(log_text))
    header = None
    legacy = False
    clients = []
    for row in reader:
        if not row:
            continue
        if row[:2] == ['Common Name', 'Real Address']:
            legacy = True
            continue
        if legacy and row[0] in {'ROUTING TABLE', 'GLOBAL STATS', 'END'}:
            legacy = False
        if legacy:
            if len(row) < 5:
                continue
            try:
                received, sent = int(row[2]), int(row[3])
            except ValueError:
                continue
            if received >= 0 and sent >= 0:
                key = '|'.join((row[0], row[1], row[4], ''))
                clients.append((row[0], key, received, sent, row[1]))
            continue
        if row[:2] == ['HEADER', 'CLIENT_LIST']:
            header = {name.strip(): index for index, name in enumerate(row[2:], 1)}
            continue
        if row[0] != 'CLIENT_LIST':
            continue
        def col(name, fallback=None):
            index = header.get(name, fallback) if header else fallback
            return row[index].strip() if index is not None and index < len(row) else ''
        username = col('Common Name', 1)
        address = col('Real Address', 2)
        try:
            received = int(col('Bytes Received', 5))
            sent = int(col('Bytes Sent', 6))
        except ValueError:
            continue
        if not username or received < 0 or sent < 0:
            continue
        # The connected epoch differentiates reconnects; client ID distinguishes
        # simultaneous connections with duplicate-cn on the same server.
        connected = col('Connected Since (time_t)', 8) or col('Connected Since', 7)
        client_id = col('Client ID', 10)
        key = '|'.join((username, address, connected, client_id))
        clients.append((username, key, received, sent, address))
    return clients


def usage_delta(previous, current):
    """A new session or reset counter starts at its current snapshot value."""
    return current if previous is None or current < previous else current - previous
