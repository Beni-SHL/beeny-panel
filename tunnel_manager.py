"""Beeny-paired FRP transport. No shell, arbitrary forward target or proxy protocol.

The entry runs frps; the OpenVPN exit node runs frpc. Every pair pins the
entry certificate and uses a random token. One pair per host, opt-in only.
"""
import base64
import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import urllib.request

ROOT=Path('/etc/openvpn/beeny-tunnel')
BIN=Path('/usr/local/lib/beeny-frp')
MODES={'tls':'tcp','ws-tls':'websocket','quic':'quic'}
VERSION='0.71.1'
from tunnel_engines import MODES as EXTRA_MODES
MODES.update({mode:mode for mode in EXTRA_MODES})

def run(*args,check=True):return subprocess.run(args,capture_output=True,text=True,timeout=20,check=check)
def port(value):
    from vpn_runtime import port as valid
    result=valid(value)
    if result<1024:raise ValueError('Use tunnel ports from 1024 to 65535; panel HTTPS ports are kept separate.')
    return result
def host(value):
    if not isinstance(value,str):raise ValueError('Enter the entry public host.')
    value=value.strip().lower()
    try:return str(ipaddress.ip_address(value))
    except ValueError:
        if len(value)>253 or not value or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in value.split('.')):
            raise ValueError('Enter a domain or IP without a scheme, path or port.')
        return value
def write(name,text):
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=ROOT/name;tmp=target.with_suffix('.tmp')
    with tmp.open('w') as stream:
        os.chmod(tmp,0o600);stream.write(text);stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,target)
def load():
    path=ROOT/'pair.json'
    return json.loads(path.read_text()) if path.is_file() else None
def ready(mode="tls"):
    if mode in EXTRA_MODES:
        return __import__("tunnel_engines").ready(mode)
    for name in ['frpc','frps']:
        binary=BIN/name
        if not binary.is_file() or binary.is_symlink() or binary.stat().st_uid!=0 or binary.stat().st_mode&0o022:
            raise ValueError('Install the verified tunnel engine from the Beeny SSH menu first.')
        if run(str(binary),'--version').stdout.strip()!=VERSION:raise ValueError('Tunnel binary version mismatch. Run the Beeny tunnel installer.')
def active(role):return run('systemctl','is-active','--quiet','beeny-tunnel-'+role,check=False).returncode==0

def cert():
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'beeny-tunnel')])
    now=datetime.now(timezone.utc)
    certificate=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('beeny-tunnel')]),critical=False).sign(key,hashes.SHA256()))
    return certificate.public_bytes(serialization.Encoding.PEM).decode(),key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()

def validate_invitation(value):
    if not isinstance(value,dict) or value.get('version')!=1:raise ValueError('Invalid pairing invitation.')
    mode=value.get('mode')
    if mode not in MODES:raise ValueError('Invalid tunnel transport.')
    token=value.get('token')
    if not isinstance(token,str) or not re.fullmatch(r'[a-f0-9]{64}',token):raise ValueError('Invalid pairing credential.')
    if mode in EXTRA_MODES and value.get('vpn_proto') not in {'tcp','udp'}:raise ValueError('Select the exit VPN protocol and port.')
    if mode=='arange-kcp' and value.get('vpn_proto')=='udp':raise ValueError('Arange KCP supports TCP VPN forwarding in Beeny. Use Noise or BackPack for a UDP VPN.')
    pem=value.get('ca','')
    if not isinstance(pem,str) or len(pem)>5000:raise ValueError('Invalid pairing certificate.')
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    certificate=x509.load_pem_x509_certificate(pem.encode())
    if certificate.not_valid_after_utc<=datetime.now(timezone.utc):raise ValueError('Pairing certificate expired. Re-pair both hosts.')
    return dict(version=1,host=host(value.get('host')),control_port=port(value.get('control_port')),
        public_port=port(value.get('public_port')),mode=mode,token=token,ca=pem,
        fingerprint=certificate.fingerprint(hashes.SHA256()).hex(),**(dict(vpn_port=__import__('vpn_runtime').port(value.get('vpn_port')),vpn_proto=value.get('vpn_proto')) if mode in EXTRA_MODES and value.get('vpn_proto') in {'tcp','udp'} else {}))

def config_entry(invitation):
    v=invitation
    lines=['udpPacketSize = 2048',f'bindPort = {v["control_port"]}',f'allowPorts = [{{ single = {v["public_port"]} }}]',
           'auth.method = "token"','auth.token = '+json.dumps(v['token']),
           'auth.additionalScopes = ["HeartBeats", "NewWorkConns"]',
           'transport.tls.force = true',f'transport.tls.certFile = "{ROOT}/server.crt"',
           f'transport.tls.keyFile = "{ROOT}/server.key"','maxPortsPerClient = 1']
    if v['mode']=='quic':lines.append('quicBindPort = '+str(v['control_port']))
    return '\n'.join(lines)+'\n'

def config_exit(v,listener):
    # FRP intentionally connects only to the local OpenVPN listener; no arbitrary forwarding.
    return '\n'.join(['udpPacketSize = 2048','serverAddr = '+json.dumps(v['host']),f'serverPort = {v["control_port"]}',
        'auth.method = "token"','auth.token = '+json.dumps(v['token']),
        'auth.additionalScopes = ["HeartBeats", "NewWorkConns"]','loginFailExit = false',
        'transport.protocol = '+json.dumps(MODES[v['mode']]),'transport.tls.enable = true',
        'transport.tls.disableCustomTLSFirstByte = true',f'transport.tls.trustedCaFile = "{ROOT}/ca.crt"',
        'transport.tls.serverName = "beeny-tunnel"','webServer.addr = "127.0.0.1"','webServer.port = 17401',
        'webServer.user = "beeny"','webServer.password = '+json.dumps(v['token']),
        '[[proxies]]','name = "beeny-openvpn"','type = '+json.dumps(listener['proto']),
        'localIP = "127.0.0.1"',f'localPort = {listener["port"]}',f'remotePort = {v["public_port"]}'])+'\n'

def registered(pair):
    if pair['role']!='exit' or not active('exit'):return False
    if pair['invitation']['mode'] in EXTRA_MODES:return __import__('tunnel_engines').registered(pair)
    # FRP admin API is loopback-only, authenticated and queried without environment proxies.
    req=urllib.request.Request('http://127.0.0.1:17401/api/status',headers={'Authorization':'Basic '+base64.b64encode(('beeny:'+pair['invitation']['token']).encode()).decode()})
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req,timeout=3) as reply:rows=json.load(reply)
        return any(row.get('name')=='beeny-openvpn' and row.get('status')=='running' for row in rows.get(pair['listener']['proto'],[]) or [])
    except Exception:return False

def status():
    pair=load()
    if not pair:return dict(success=True,installed=(BIN/'frpc').is_file(),configured=False)
    v=pair['invitation'];enabled=active(pair['role'])
    installed=(__import__('tunnel_engines').BIN/EXTRA_MODES[v['mode']][0]).is_file() if v['mode'] in EXTRA_MODES else (BIN/'frpc').is_file()
    result=dict(success=True,installed=installed,configured=True,role=pair['role'],enabled=enabled,
        host=v['host'],port=v['public_port'],control_port=v['control_port'],mode=v['mode'],fingerprint=v['fingerprint'])
    result['registered']=registered(pair) if pair['role']=='exit' else None
    return result

def endpoint():
    pair=load()
    if not pair or pair['role']!='exit' or not registered(pair):raise ValueError('The paired tunnel is not registered. Use the direct profile or check tunnel health.')
    import vpn_runtime
    live=vpn_runtime.status()
    if any(live[key]!=pair['listener'][key] for key in ['proto','port']):raise ValueError('Re-pair the tunnel after changing the VPN listener.')
    v=pair['invitation'];return dict(host=v['host'],port=v['public_port'],proto=live['proto'])

def handle(action,data=None):
    # Share the durable runtime lock with listener edits and serialize pairing.
    import vpn_runtime
    with vpn_runtime.lock():
        if action=='status':return status()
        if action=='endpoint':return dict(success=True,endpoint=endpoint())
        if action=='export':
            pair=load()
            if not pair or pair['role']!='entry':raise ValueError('Create the entry host first.')
            return dict(success=True,invitation=pair['invitation'])
        if action=='disable':
            for role in ['entry','exit']:run('systemctl','disable','--now','beeny-tunnel-'+role)
            return status()
        if data is not None and not isinstance(data,dict):raise ValueError('Invalid pairing data.')
        pair=load()
        requested_mode=(data or {}).get('mode') if action=='entry' else ((data or {}).get('invitation') or {}).get('mode') if action=='pair' else (pair or {}).get('invitation',{}).get('mode','tls')
        ready(requested_mode)
        if action=='enable':
            if not pair:raise ValueError('Pair the hosts first.')
            if pair['role']=='exit':
                live=vpn_runtime.status()
                if any(live[key]!=pair['listener'][key] for key in ['proto','port']):raise ValueError('Re-pair the tunnel after changing the VPN listener.')
            run('systemctl','enable','--now','beeny-tunnel-'+pair['role']);return status()
        if action not in {'entry','pair'}:raise ValueError('Invalid tunnel action.')
        if pair and any(active(role) for role in ['entry','exit']):raise ValueError('Disable the existing tunnel before re-pairing.')
        with configure_transaction():
            data=data or {}
            if not isinstance(data,dict):raise ValueError('Invalid pairing data.')
            if action=='entry':
                if data.get('mode') not in MODES:raise ValueError('Invalid tunnel transport.')
                pem,key=cert()
                invitation=validate_invitation(dict(version=1,host=data.get('host'),control_port=data.get('control_port'),public_port=data.get('public_port'),mode=data['mode'],ca=pem,token=secrets.token_hex(32),vpn_port=data.get('vpn_port'),vpn_proto=data.get('vpn_proto')))
                if invitation['control_port']==invitation['public_port']:raise ValueError('Control and public tunnel ports must differ.')
                role='entry';text=config_entry(invitation) if invitation['mode'] not in EXTRA_MODES else __import__('tunnel_engines').config(invitation,'entry')
                write('server.crt',pem);write('server.key',key)
                record=dict(role=role,invitation=invitation)
            else:
                invitation=validate_invitation(data.get('invitation'))
                listener=vpn_runtime.status()
                if not listener['active']:raise ValueError('Start OpenVPN before pairing this exit.')
                if listener['local'] not in {'0.0.0.0','127.0.0.1'}:raise ValueError('The OpenVPN listener must accept local loopback connections.')
                if invitation['mode'] in EXTRA_MODES and (invitation.get('vpn_proto')!=listener['proto'] or invitation.get('vpn_port')!=listener['port']):
                    raise ValueError('Invitation VPN protocol/port must match the exit listener.')
                role='exit';write('ca.crt',invitation['ca']);text=config_exit(invitation,listener) if invitation['mode'] not in EXTRA_MODES else __import__('tunnel_engines').config(invitation,'exit',listener)
                record=dict(role=role,invitation=invitation,listener={k:listener[k] for k in ['proto','port']})
            if invitation['mode'] in EXTRA_MODES:
                write('engine.toml',text)
                if not Path('/etc/systemd/system/beeny-tunnel-'+role+'.service').is_file() or 'tunnel_engines.py' not in Path('/etc/systemd/system/beeny-tunnel-'+role+'.service').read_text():
                    raise ValueError('Install the additional engine units from the Beeny SSH menu first.')
            else:
                name='frps' if role=='entry' else 'frpc';write(name+'.toml',text)
                run(str(BIN/name),'verify','-c',str(ROOT/(name+'.toml')))
            write('pair.json',json.dumps(record))
            run('systemctl','enable','--now','beeny-tunnel-'+role)
            if not active(role):raise RuntimeError('Tunnel unit did not become active.')
            result=status()
            if action=='entry':result['invitation']=invitation
            return result
    

@contextlib.contextmanager
def configure_transaction():
    names=['server.crt','server.key','ca.crt','frps.toml','frpc.toml','engine.toml','pair.json']
    previous={name:(ROOT/name).read_text() if (ROOT/name).is_file() else None for name in names}
    try:yield
    except Exception:
        for role in ['entry','exit']:run('systemctl','disable','--now','beeny-tunnel-'+role,check=False)
        for name,text in previous.items():
            if text is None:(ROOT/name).unlink(missing_ok=True)
            else:write(name,text)
        raise
