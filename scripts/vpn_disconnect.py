#!/usr/bin/python3
"""Durable terminal counters written by OpenVPN; never invoke shell commands."""
import hashlib,json,os,re,time
from pathlib import Path

def capture(env,root=Path('/var/lib/beeny-vpn-events')):
    name=env.get('common_name','');host=env.get('trusted_ip',env.get('trusted_ip6',''));port=env.get('trusted_port','');since=env.get('time_unix','')
    if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}',name) or not port.isdigit() or not since.isdigit():return
    import ipaddress
    address=ipaddress.ip_address(host);peer=(f'[{address}]:{port}' if address.version==6 else f'{address}:{port}')
    received=int(env.get('bytes_received','0'));sent=int(env.get('bytes_sent','0'))
    if min(received,sent)<0 or max(received,sent)>2**63-1:return
    record=dict(username=name,address=peer,since=since,received=received,sent=sent,finished=int(time.time()),signal=str(env.get('signal',''))[:80],platform=str(env.get('IV_PLAT',''))[:40],client=str(env.get('IV_GUI_VER',''))[:160])
    key=hashlib.sha256(f'{name}|{peer}|{since}'.encode()).hexdigest();target=root/(key+'.json')
    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(record,stream)
    private=Path('/etc/openvpn/beeny-admission.json')
    if private.is_file():
        try:
            from vpn_admission import admission
            admission(env,json.loads(private.read_text()),action='disconnect')
        except Exception:pass # The next authenticated status snapshot reconciles stale leases.
if __name__=='__main__':
    try:capture(os.environ)
    except FileExistsError:pass
    except Exception:raise SystemExit(1)
