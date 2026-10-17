#!/usr/bin/env python3
import json,sqlite3,subprocess,re
from pathlib import Path
root=Path('/opt/beeny-panel')
for command in [['openvpn','--version'],['systemctl','is-active','beeny-panel','beeny-customer-worker','beeny-privileged','openvpn-server@server'],['tc','-s','qdisc','show']]:
    try:
        r=subprocess.run(command,capture_output=True,text=True,timeout=10);print(' '.join(command));print(r.stdout[:3500])
    except Exception as exc:print(type(exc).__name__)
if (root/'instance/beeny.db').is_file():
    with sqlite3.connect('file:'+str(root/'instance/beeny.db')+'?mode=ro',uri=True) as db:
        print('DB integrity:',db.execute('PRAGMA quick_check').fetchone()[0]);print('Accounts:',db.execute('SELECT count(*) FROM user').fetchone()[0])
        bad=[r[0] for r in db.execute('SELECT username FROM user') if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}',r[0])]
        print('Legacy names needing review before strict admission:',bad)
for name in ['/etc/openvpn/server/server.conf','/etc/openvpn/server.conf']:
    p=Path(name)
    if p.is_file():
        print('VPN config:',name)
        for line in p.read_text().splitlines():
            if line.split() and line.split()[0] in {'port','proto','dev','user','group','crl-verify','disable-dco','client-connect','client-disconnect','management','server','server-ipv6'}:print(line)
