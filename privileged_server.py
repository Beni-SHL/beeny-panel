"""Root helper: explicit VPN operations and an allowlist of service names."""
import json, os, pwd, re, socket, socketserver, struct, subprocess, threading
from pathlib import Path
from types import SimpleNamespace
SERVICES={'beeny-panel','beeny-customer-worker','openvpn-server@server'}
LOCK=threading.RLock()

def https_status():
    from urllib.parse import urlsplit
    from datetime import datetime, timezone
    import ssl
    base=os.environ.get('BEENY_PANEL_BASE_URL','')
    env=Path('/etc/beeny-panel/panel.env')
    if not base and env.is_file():
        for line in env.read_text().splitlines():
            key,sep,value=line.partition('=')
            if sep and key.strip()=='BEENY_PANEL_BASE_URL':base=value.strip().strip("\"'")
    domain=urlsplit(base).hostname or ''
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?',domain) or '..' in domain:
        return dict(success=False,message='Configure BEENY_PANEL_BASE_URL with the public HTTPS address.')
    live=Path('/etc/letsencrypt/live')
    path=live/domain/'fullchain.pem'
    if not path.is_file():
        candidates=[]
        for candidate in sorted(live.glob('*/fullchain.pem'))[:100]:
            if not re.fullmatch(r'[A-Za-z0-9.-]+',candidate.parent.name):continue
            try:
                decoded=ssl._ssl._test_decode_cert(str(candidate))
                ssl.match_hostname(decoded,domain)
                candidates.append(candidate)
            except (OSError,ValueError,ssl.CertificateError):continue
        if len(candidates)!=1:return dict(success=False,domain=domain,message='No unambiguous managed certificate found for the public hostname.')
        path=candidates[0]
    cert=ssl._ssl._test_decode_cert(str(path))
    try:ssl.match_hostname(cert,domain)
    except ssl.CertificateError:return dict(success=False,domain=domain,message='The managed certificate does not cover the configured public hostname.')
    expiry=datetime.strptime(cert['notAfter'],'%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
    days=(expiry-datetime.now(timezone.utc)).days
    timers=[]
    for unit in ('certbot.timer','snap.certbot.renew.timer','beeny-https-renew.timer'):
        result=subprocess.run(['systemctl','is-active',unit],capture_output=True,text=True,timeout=5)
        if result.returncode==0:timers.append(unit)
    renewal=Path('/etc/letsencrypt/renewal')/(path.parent.name+'.conf')
    source=renewal.read_text() if renewal.is_file() else ''
    auth=re.search(r'^authenticator\s*=\s*(\S+)',source,re.M)
    authenticator=auth[1] if auth else 'unknown'
    return dict(success=True,domain=domain,cert_name=path.parent.name,authenticator=authenticator,renewal_supported=authenticator not in {'standalone','unknown'},issuer=', '.join(value for group in cert.get('issuer',()) for key,value in group if key=='commonName'),expire_date=expiry.strftime('%Y-%m-%d'),days_left=days,status='Active' if days>=0 else 'Expired',auto_renew=bool(timers),renewal_timers=timers,renewal_note='Active scheduler detected; renewal success still depends on domain validation.' if timers else 'No active Certbot timer detected. Cron or external renewal is not assessed.')

def username(value, session_only=False):
    # Session operations compare CN strings; they do not construct paths or shell commands.
    if session_only and isinstance(value,str) and 1 <= len(value) <= 128 and value.isprintable() and not any(c in value for c in "/\\|"):
        return value
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}',value):raise ValueError('Invalid VPN username.')
    return value

def dispatch(operation, parameters):
    if operation=='tunnel':
        try:return __import__('tunnel_manager').handle(parameters.get('action'),parameters.get('data'))
        except ValueError as exc:return dict(success=False,message=str(exc))
    if operation=='vpn_runtime':
        try:return __import__('vpn_runtime').handle(parameters.get('action'),parameters.get('data'),parameters.get('revision'))
        except ValueError as exc:return dict(success=False,message=str(exc))
    if operation=='panel_update':
        import panel_update
        action=parameters.get('action')
        if action=='status':return panel_update.status()
        if action=='check':return panel_update.check()
        if action=='install':return panel_update.queue(parameters.get('commit'))
        raise ValueError('Invalid update action.')
    if operation=='maintenance':return __import__('maintenance').queue(parameters.get('action'))
    if operation=='network_policy':return __import__('network_policy').handle(parameters.get('action'),parameters.get('policy'),parameters.get('revision'))
    if operation=='https_action':return __import__('https_maintenance').schedule(parameters.get('action'))
    if operation=='https_status':
        result=https_status()
        path=Path('/var/lib/beeny/https/result.json')
        if path.is_file():result['last_job']=json.loads(path.read_text())
        return result
    if operation=='host_metrics':return __import__('host_metrics').snapshot()
    if operation=='crl_material':return dict(crl=Path('/etc/openvpn/crl.pem').read_text())
    if operation=='traffic_ack':return __import__('terminal_traffic').acknowledge(parameters.get('ids'))
    if operation=='speed_policy':
        import bandwidth
        return bandwidth.set_policy(parameters.get('username'),parameters.get('names'),parameters.get('down'),parameters.get('up'))
    if operation=='speed_status':
        import bandwidth
        if bandwidth.LAST_ERROR:raise RuntimeError('Speed watcher reported an error.')
        return dict(success=True)
    if operation=='service':
        name=parameters.get('name');action=parameters.get('action')
        if name not in SERVICES or action not in {'restart','start','stop','status'}:raise ValueError('Service is not permitted.')
        if action=='status':
            result=subprocess.run(['systemctl','is-active',name],capture_output=True,text=True,timeout=10)
            return dict(active=result.returncode==0,state=result.stdout.strip())
        if name.startswith('beeny-') and action=='restart':
            subprocess.run(['systemd-run','--quiet','--on-active=2s','/bin/systemctl','restart',name],check=True,capture_output=True,timeout=10)
            return dict(queued=True)
        subprocess.run(['systemctl',action,name],check=True,capture_output=True,timeout=30)
        return dict(active=subprocess.run(['systemctl','is-active',name],capture_output=True,timeout=10).returncode==0)
    if operation=='status_log':
        path=Path('/var/log/openvpn-status.log')
        active=dispatch('service',dict(name='openvpn-server@server',action='status'))['active']
        if not active or not path.is_file() or __import__('time').time()-path.stat().st_mtime>90:
            raise RuntimeError('VPN stopped or its status snapshot is stale.')
        return dict(events=__import__('terminal_traffic').read_events(),log=path.read_text(),age=__import__('time').time()-path.stat().st_mtime)
    if operation=='clear_cache':
        import shutil
        path=Path('/opt/beeny-panel/__pycache__')
        if path.exists() and not path.is_symlink():shutil.rmtree(path)
        return True
    if operation=='vpn_info':
        return dict(config=Path('/etc/openvpn/server/server.conf').read_text())
    if operation=='bootstrap_material':
        files=dict(ca_crt='/etc/openvpn/easy-rsa/pki/ca.crt',ta_key='/etc/openvpn/ta.key',server_crt='/etc/openvpn/easy-rsa/pki/issued/server.crt',server_key='/etc/openvpn/easy-rsa/pki/private/server.key',dh_pem='/etc/openvpn/easy-rsa/pki/dh.pem',crl_pem='/etc/openvpn/crl.pem',server_conf='/etc/openvpn/server/server.conf')
        return {k:Path(v).read_text() if Path(v).exists() else '' for k,v in files.items()}
    if operation=='backup_delete':
        import backup_engine
        path=backup_engine.safe_file(parameters.get('name'));path.unlink()
        if path.suffix=='.db':path.with_suffix('.db.sig').unlink(missing_ok=True)
        return True
    if operation=='backup_upload':
        import backup_engine,shutil
        source=parameters.get('source')
        if not isinstance(source,str) or not re.fullmatch(r'[a-f0-9]{32}',source):raise ValueError('Invalid upload source.')
        root=Path('/opt/beeny-panel/instance/backup_uploads');inputfile=root/source
        if inputfile.is_symlink() or not inputfile.resolve().is_relative_to(root.resolve()) or inputfile.stat().st_size>224*1024*1024:raise ValueError('Invalid upload.')
        target=backup_engine.safe_file(parameters.get('name'))
        created=False
        try:
            with target.open('xb') as output:
                created=True
                with inputfile.open('rb') as stream:shutil.copyfileobj(stream,output)
            backup_engine.validate(target)
            target.chmod(0o640);os.chown(target,0,pwd.getpwnam('beeny').pw_gid)
        except Exception:
            if created:target.unlink(missing_ok=True)
            raise
        return True
    if operation in {'backup_create','backup_validate','backup_restore'}:
        import backup_engine
        if operation=='backup_create':return backup_engine.create(full=parameters.get('full',True))
        name=parameters.get('name');path=backup_engine.safe_file(name)
        if operation=='backup_validate':return backup_engine.validate(path)
        backup_engine.validate(path)
        subprocess.run(['systemd-run','--quiet','--on-active=2s','/opt/beeny-panel/venv/bin/python','/opt/beeny-panel/backup_engine.py','restore',name],check=True,capture_output=True,timeout=10)
        return dict(queued=True)
    user=username(parameters.get('username'), session_only=operation in {'sessions','disconnect','kick'})
    from vpn_sessions import local_sessions,disconnect_session,Management
    if operation=='create_user':
        with LOCK:subprocess.run(['/bin/bash','/opt/beeny-panel/scripts/create_vpn_user.sh',user],check=True,capture_output=True,timeout=120)
        return True
    if operation=='material':
        root=Path('/etc/openvpn/easy-rsa/pki')
        return dict(ca=(root/'ca.crt').read_text(),ta=Path('/etc/openvpn/ta.key').read_text(),cert=(root/'issued'/f'{user}.crt').read_text(),key=(root/'private'/f'{user}.key').read_text())
    if operation=='access':
        active=parameters.get('active')
        if not isinstance(active,bool):raise ValueError('Invalid state.')
        path=Path('/etc/openvpn/ccd')/user
        with LOCK:
            if active:
                from vpn_sessions import enable_ccd
                enable_ccd(path)
            else:
                from vpn_sessions import disable_ccd
                disable_ccd(path)
                if dispatch('service',dict(name='openvpn-server@server',action='status'))['active']:
                    for connection in local_sessions(user):disconnect_session(user,connection['id'],connection['fingerprint'])
        return True
    if operation=='sessions':return local_sessions(user)
    if operation=='disconnect':
        disconnect_session(user,parameters.get('id'),parameters.get('fingerprint'));return True
    if operation=='kick':
        for connection in local_sessions(user):disconnect_session(user,connection['id'],connection['fingerprint'])
        return True
    if operation=='backup':
        raise ValueError('Use the dedicated backup command.')
    raise ValueError('Unsupported operation.')

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(15)
        _,uid,_=struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if uid not in {0,pwd.getpwnam('beeny').pw_uid}:return
        try:
            raw=self.rfile.readline(1048577)
            if len(raw)>1048576:raise ValueError('Request too large.')
            data=json.loads(raw)
            result=dispatch(data['operation'],data.get('parameters',{}));response=dict(ok=True,result=result)
        except Exception:
            import logging
            logging.exception('Privileged operation failed')
            response=dict(ok=False,error='Operation failed or was rejected. Check privileged service logs.')
        self.wfile.write(json.dumps(response).encode()+b'\n')

if __name__=='__main__':
    os.environ.pop('BEENY_PRIVILEGE_SOCKET',None)
    import bandwidth
    bandwidth.start()
    path=Path('/run/beeny-panel/privileged.sock');path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():path.unlink()
    with socketserver.ThreadingUnixStreamServer(str(path),Handler) as server:
        os.chown(path,0,pwd.getpwnam('beeny').pw_gid);os.chmod(path,0o660);server.serve_forever()
