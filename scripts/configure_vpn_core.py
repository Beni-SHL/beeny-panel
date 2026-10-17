#!/usr/bin/env python3
"""Review/apply VPN hardening explicitly. Never run as part of a panel-only update."""
import argparse,json,os,re,shutil,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

def configure(text,proto=None,hook_root="/opt/beeny-panel/scripts",admission=False):
    for directive,path in re.findall(r'^\s*(client-connect|client-disconnect)\s+(\S+)',text,re.M):
        if path!=hook_root+('/vpn_admission.py' if directive=='client-connect' else '/vpn_disconnect.py'):raise ValueError('Existing client hooks need a manual merge; nothing changed.')
    directives={'management':'management /run/openvpn/beeny-management.sock unix','user':'user beeny-vpn','group':'group beeny-vpn','crl-verify':'crl-verify /etc/openvpn/crl.pem','disable-dco':'disable-dco','server-ipv6':'server-ipv6 fd42:bee:8::/64','status-version':'status-version 2','script-security':'script-security 2','client-disconnect':'client-disconnect '+hook_root+'/vpn_disconnect.py'}
    if admission:directives['client-connect']='client-connect '+hook_root+'/vpn_admission.py'
    if proto:directives['proto']='proto '+('tcp-server' if proto=='tcp' else 'udp')
    lines=[];seen=set()
    for line in text.splitlines():
        key=line.strip().split(' ',1)[0]
        if key in directives:
            if key not in seen:lines.append(directives[key]);seen.add(key)
        else:lines.append(line)
    lines.extend(v for k,v in directives.items() if k not in seen)
    for line in ['push "redirect-gateway ipv6"','push "block-ipv6"']:
        if line not in lines:lines.append(line)
    return '\n'.join(lines)+'\n'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--admission',action='store_true');parser.add_argument('--apply',action='store_true');parser.add_argument('--restart',action='store_true');parser.add_argument('--proto',choices=['tcp','udp']);args=parser.parse_args()
    hook_root='/opt/beeny-panel/scripts' if Path('/opt/beeny-panel/app.py').exists() else '/opt/beeny-node-bridge/scripts'
    config=Path('/etc/openvpn/server/server.conf');old=config.read_text();new=configure(old,args.proto,hook_root,args.admission)
    output=subprocess.run(['openvpn','--version'],capture_output=True,text=True,check=True).stdout
    version=re.search(r'OpenVPN\s+(\d+)\.(\d+)',output)
    if not version or tuple(map(int,version.groups()))<(2,5):raise SystemExit('OpenVPN 2.5+ required for this deployment recipe. Audit older installations separately.')
    if tuple(map(int,version.groups()))<(2,6):new=new.replace('disable-dco\n','')
    if not args.apply:print(new);print('Preview only. Use --apply --restart in a maintenance window.');return
    if os.geteuid()!=0:raise SystemExit('Run as root')
    hook=Path(hook_root)/'vpn_disconnect.py'
    if not hook.is_file():raise SystemExit('Install the matching panel/node package first.')
    hook.chmod(0o755)
    if args.admission:
        connect_hook=Path(hook_root)/'vpn_admission.py'
        if not connect_hook.is_file():raise SystemExit('Admission hook missing; install the matching package first.')
        connect_hook.chmod(0o755)
    import fcntl
    lock=Path('/etc/openvpn/.beeny-pki.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX)
    import vpn_maintenance
    try:vpn_maintenance.refresh_crl()
    except (ValueError,subprocess.CalledProcessError):
        # A node without the issuing CA key may use the verified public CRL from the panel.
        import tempfile
        sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
        import crl_sync
        with tempfile.NamedTemporaryFile(mode='w',delete=False) as tmp:tmp.write(new);review=Path(tmp.name)
        try:crl_sync.install_crl(Path('/etc/openvpn/crl.pem').read_text(),review)
        finally:review.unlink(missing_ok=True)
    import pwd,grp
    try:pwd.getpwnam('beeny-vpn')
    except KeyError:subprocess.run(['useradd','--system','--user-group','--home-dir','/nonexistent','--shell','/usr/sbin/nologin','beeny-vpn'],check=True)
    if args.admission:
        private=Path('/etc/openvpn/beeny-admission.json')
        if not private.is_file():raise SystemExit('Export and transfer the node admission file first.')
        json.loads(private.read_text());os.chown(private,0,grp.getgrnam('beeny-vpn').gr_gid);private.chmod(0o640)
    backup=Path('/root/beeny-core-backups')/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+str(os.getpid()));backup.mkdir(parents=True,mode=0o700);shutil.copy2(config,backup/'server.conf')
    runtime=Path('/run/openvpn');runtime.mkdir(exist_ok=True);runtime.chmod(0o700)
    events=Path('/var/lib/beeny-vpn-events');events.mkdir(parents=True,exist_ok=True)
    import pwd,grp
    os.chown(events,pwd.getpwnam('beeny-vpn').pw_uid,grp.getgrnam('beeny-vpn').gr_gid);events.chmod(0o700)
    # The socket directory is recreated at every OpenVPN service startup.
    dropin=Path('/etc/systemd/system/openvpn-server@server.service.d/beeny-runtime.conf');dropin.parent.mkdir(parents=True,exist_ok=True)
    dropin.write_text('[Service]\nExecStartPre=/usr/bin/install -d -m 700 /run/openvpn\n')
    envs=[]
    for env in [Path('/etc/beeny-panel/panel.env'),Path('/etc/beeny-node-bridge/bridge.env')]:
        if env.exists():
            envs.append((env,env.read_text()));shutil.copy2(env,backup/(env.parent.name+'-env'))
    try:
        config.write_text(new)
        for env,content in envs:
            clean=re.sub(r'^BEENY_MANAGEMENT_SOCKET=.*\n?','',content,flags=re.M)
            env.write_text(clean.rstrip()+'\nBEENY_MANAGEMENT_SOCKET=/run/openvpn/beeny-management.sock\n')
        subprocess.run(['systemctl','daemon-reload'],check=True)
        if args.restart:
            subprocess.run(['systemctl','restart','openvpn-server@server'],check=True)
            subprocess.run(['systemctl','is-active','--quiet','openvpn-server@server'],check=True)
            for service in ['beeny-privileged','beeny-node-bridge']:
                if subprocess.run(['systemctl','is-active','--quiet',service]).returncode==0:subprocess.run(['systemctl','restart',service],check=True)
    except Exception:
        config.write_text(old)
        for env,content in envs:env.write_text(content)
        if args.restart:
            subprocess.run(['systemctl','restart','openvpn-server@server'])
            for service in ['beeny-privileged','beeny-node-bridge']:
                if subprocess.run(['systemctl','is-active','--quiet',service]).returncode==0:subprocess.run(['systemctl','restart',service])
        raise
    print('Core configuration saved. Backup:',backup)
    if not args.restart:print('VPN is still using the previous configuration. Restart OpenVPN and helper/bridge together in a maintenance window.')
if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parent));main()
