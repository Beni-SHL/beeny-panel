#!/usr/bin/env python3
"""Root-only, fixed SSH menu. Never reveals stored credentials or changes VPN core."""
import getpass,json,os,re,sqlite3,subprocess,sys
from pathlib import Path
SOURCE=Path(__file__).resolve().parent.parent
ROOT=Path('/opt/beeny-panel') if Path('/opt/beeny-panel/app.py').is_file() else SOURCE
sys.path.insert(0,str(ROOT))
def run(*args,**kwargs):return subprocess.run(list(args),check=True,**kwargs)
def admin(action):
    username=input('Administrator username: ').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,50}',username):raise ValueError('Invalid username.')
    password=getpass.getpass('New password (12–256 characters): ')
    if not 12<=len(password)<=256 or password!=getpass.getpass('Repeat password: '):raise ValueError('Passwords do not match or are too short.')
    run('systemd-run','--quiet','--wait','--pipe','--property=User=beeny','--property=WorkingDirectory='+str(ROOT),'--property=EnvironmentFile=/etc/beeny-panel/panel.env',str(ROOT/'venv/bin/python'),str(ROOT/'scripts/manage_admin.py'),action,username,input=password+'\n',text=True)
def status():
    print('Beeny Panel version:',(ROOT/'VERSION').read_text().strip())
    subprocess.run(['systemctl','is-active','beeny-panel','beeny-customer-worker','beeny-privileged','openvpn-server@server'])
    with sqlite3.connect('file:'+str(ROOT/'instance/beeny.db')+'?mode=ro',uri=True) as db:
        for name,role in db.execute('SELECT username,role FROM admin ORDER BY id'):print('Administrator:',name,'|',role)
    cfg=json.loads((ROOT/'config.json').read_text());print('Panel path:',cfg.get('panel_path',''));print('Passwords are hashed and cannot be displayed.')
def ssl():
    domain=input('Public panel hostname (DNS must point here): ').strip().lower()
    email=input('Certificate contact email: ').strip()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?',domain) or '.' not in domain or '..' in domain:raise ValueError('Invalid hostname.')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('Invalid email.')
    run('nginx','-t')
    import tarfile,time
    archive=Path('/root')/('beeny-nginx-before-ssl-'+str(time.time_ns())+'.tar.gz')
    fd=os.open(archive,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    with tarfile.open(archive,'w:gz') as output:output.add('/etc/nginx',arcname='nginx')
    run('apt-get','update');run('apt-get','install','-y','certbot','python3-certbot-nginx')
    run('certbot','--nginx','--non-interactive','--agree-tos','--email',email,'-d',domain,'--redirect')
    run('nginx','-t');run('systemctl','reload','nginx');run('systemctl','enable','--now','certbot.timer')
    env=Path('/etc/beeny-panel/panel.env');lines=env.read_text().splitlines()
    values={'BEENY_PANEL_BASE_URL':'https://'+domain,'BEENY_PUBLIC_HTTPS':'1'}
    result=[line for line in lines if line.partition('=')[0] not in values]
    result += [key+'='+value for key,value in values.items()]
    temp=env.with_suffix('.beeny-ssl.tmp');temp.write_text('\n'.join(result)+'\n');temp.chmod(0o600);os.replace(temp,env)
    run('systemctl','restart','beeny-panel','beeny-customer-worker')
    print('Certificate issued. Confirm the public HTTPS address in Settings → HTTPS. Existing VPN profiles are unchanged.')
def main():
    if os.geteuid()!=0:raise SystemExit('Run with sudo or as root.')
    options=[('Status & administrator usernames',status),('Add owner administrator',lambda:admin('add')),('Reset administrator password',lambda:admin('password')),('Restart panel & worker',lambda:run('systemctl','restart','beeny-panel','beeny-customer-worker')),('Enable BBR',lambda:__import__('maintenance').queue('bbr-enable')),('Restore managed TCP settings',lambda:__import__('maintenance').queue('bbr-restore')),('Install official WARP package',lambda:__import__('warp_manager').queue('install')),('Remove managed WARP package',lambda:__import__('warp_manager').queue('remove')),('Update panel from GitHub',lambda:run('bash',str(ROOT/'scripts/update_panel.sh'),'--github')),('Issue HTTPS certificate (configured Nginx required)',ssl),('Create complete signed backup',lambda:__import__('backup_engine').create(full=True)),('Collect redacted VPN diagnostics',lambda:run(str(ROOT/'venv/bin/python'),str(ROOT/'scripts/collect_vpn_diagnostics.py')))]
    options.insert(0,('Install Beeny Panel',install))
    options.append(('Install verified paired-tunnel engine (FRP TLS / WebSocket+TLS / QUIC)',lambda:run(sys.executable,str(ROOT/'scripts/install_tunnel.py'))))
    options.append(('Additional engines · Arange / BackPack / DFR / DNS',lambda:run(sys.executable,str(ROOT/'scripts/install_integrations.py'))))
    while True:
        print(banner())
        print('Version: '+(ROOT/'VERSION').read_text().strip()+' · '+('Installed' if installed() else 'Not installed'))
        print('0. Exit')
        for i,(label,_) in enumerate(options,1):print(str(i)+'. '+label)
        choice=input('Choose: ').strip()
        if choice=='0':return
        if not choice.isdigit() or not 1<=int(choice)<=len(options):continue
        if int(choice)!=1 and not installed():
            print('Install Beeny Panel first using option 1.');continue
        try:
            result=options[int(choice)-1][1]()
            if result is not None:print(result)
        except (ValueError,OSError,subprocess.SubprocessError) as exc:print('Operation failed:',str(exc))
def installed():return (Path('/opt/beeny-panel')/'instance/beeny.db').is_file()
def install():
    if installed():
        print('Panel is already installed. Use Update panel; installation does not overwrite it.');return
    run('bash',str(SOURCE/'install.sh'))
    if installed():
        print('Installation complete. Open the installed menu with: beeny')
        os.execv('/usr/local/bin/beeny',['beeny'])
def banner():
    # Fixed typography works over SSH without downloading a web font.
    return '''
██████╗ ███████╗███████╗███╗   ██╗██╗   ██╗
██╔══██╗██╔════╝██╔════╝████╗  ██║╚██╗ ██╔╝
██████╔╝█████╗  █████╗  ██╔██╗ ██║ ╚████╔╝
██╔══██╗██╔══╝  ██╔══╝  ██║╚██╗██║  ╚██╔╝
██████╔╝███████╗███████╗██║ ╚████║   ██║
╚═════╝ ╚══════╝╚══════╝╚═╝  ╚═══╝   ╚═╝
              P A N E L  ·  CONTROL CENTER
'''
if __name__=='__main__':
    if '--banner' in sys.argv:print(banner())
    else:main()
