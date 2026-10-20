#!/usr/bin/env python3
"""Beeny-owned, commit-pinned installers. No curl-to-shell, no floating branch execution."""
import argparse,hashlib,io,json,os,platform,shutil,subprocess,sys,tarfile,tempfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
GO={'x86_64':('amd64','42d158b4d8f7b61ac0a830567c940a86098fb7aac52e467a5ebec03ef5cc2f8d'),
    'aarch64':('arm64','4a97373d49fcacdcf3694fea368a500b00ee3e963974f3e7514132717632f052')}
def fetch(url,digest,limit=160*1024*1024):
    with urllib.request.urlopen(url,timeout=120) as r:blob=r.read(limit+1)
    if len(blob)>limit or hashlib.sha256(blob).hexdigest()!=digest:raise ValueError('Download verification failed; nothing executed.')
    return blob
def extract(blob,dest):
    # Compatible with Python 3.9; reject every link/device/traversal before extracting regular bytes.
    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as archive:
        total=0
        for member in archive.getmembers():
            if member.name.startswith('/') or '..' in Path(member.name).parts or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe source archive member.')
            total+=member.size
            if total>650*1024*1024:raise ValueError('Archive too large.')
        for member in archive.getmembers():
            target=dest/member.name
            if member.isdir():target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.extractfile(member).read());target.chmod(member.mode&0o755)
def toolchain():
    arch,digest=GO[platform.machine()];root=Path('/opt/beeny-toolchain/go1.26.9')
    binary=root/'go/bin/go'
    if not binary.is_file():
        root.mkdir(parents=True,exist_ok=True)
        extract(fetch('https://go.dev/dl/go1.26.9.linux-'+arch+'.tar.gz',digest),root)
    if subprocess.check_output([str(binary),'version'],text=True).split()[2]!='go1.26.9':raise ValueError('Toolchain version mismatch')
    return binary
def install_units():
    for role in ['entry','exit']:
        unit=Path('/etc/systemd/system/beeny-tunnel-'+role+'.service')
        if unit.exists() and '# Managed by Beeny' not in unit.read_text():raise ValueError('Unmanaged unit; no changes made.')
    for role in ['entry','exit']:
        Path('/etc/systemd/system/beeny-tunnel-'+role+'.service').write_text(f'''# Managed by Beeny
[Unit]
Description=Beeny paired tunnel {role}
After=network-online.target
Wants=network-online.target
[Service]
ExecStart={sys.executable} {ROOT}/tunnel_engines.py {role}
WorkingDirectory={ROOT}
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
UnsetEnvironment=HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
[Install]
WantedBy=multi-user.target
''')
    subprocess.run(['systemctl','daemon-reload'],check=True)
def dedicated(name):
    # These projects own DNS/Nginx/routing. Never overwrite a live Beeny host.
    if Path('/etc/beeny-panel/panel.env').exists():raise ValueError(name+' requires a separate host; existing panel installation found.')
    if name in {'doctor','hyperdns'}:
        rows=subprocess.check_output(['ss','-H','-lntup'],text=True)
        for line in rows.splitlines():
            cells=line.split()
            if len(cells)>4:
                addr=cells[4]
                if any(addr.endswith(':'+str(port)) for port in [53,80,443,8080,853,8443]) and not addr.startswith(('127.','[::1]')):
                    raise ValueError('DNS/web port conflict. Use a dedicated clean host.')
def install(name):
    if os.geteuid()!=0:raise ValueError('Run as root.')
    if platform.machine() not in GO:raise ValueError('Supported Linux architectures: amd64 / arm64.')
    pins=json.loads((ROOT/'integration-sources.json').read_text());pin=pins[name]
    if name in {'arange','backpack'}:
        if str(ROOT) not in {'/opt/beeny-panel','/opt/beeny-node-bridge'}:raise ValueError('Install/update Beeny first, then run its installed integration manager under /opt.')
        for role in ['entry','exit']:
            if subprocess.run(['systemctl','is-active','--quiet','beeny-tunnel-'+role]).returncode==0:raise ValueError('Disable the paired tunnel before installing engines.')
        for role in ['entry','exit']:
            unit=Path('/etc/systemd/system/beeny-tunnel-'+role+'.service')
            if unit.exists() and '# Managed by Beeny' not in unit.read_text():raise ValueError('Unmanaged tunnel unit; nothing changed.')
    else:dedicated(name)
    with tempfile.TemporaryDirectory(prefix='beeny-verified-') as tmp:
        path=Path(tmp);extract(fetch(pin['url'],pin['sha256']),path)
        source=next(path.iterdir())
        if name in {'arange','backpack','hyperdns'}:
            if name=='arange':
                subprocess.run(['apt-get','update'],check=True)
                subprocess.run(['apt-get','install','-y','build-essential','libpcap-dev'],check=True)
            go=toolchain();target=path/'engine'
            env=dict({k:v for k,v in os.environ.items() if k.lower() not in {'http_proxy','https_proxy','all_proxy'}},GOMAXPROCS='2',GOTOOLCHAIN='local',GOSUMDB='sum.golang.org',GOPROXY='https://proxy.golang.org,direct')
            # Use upstream go.sum checksum verification; never launch an upstream install script to compile.
            subprocess.run([str(go),'mod','verify'],cwd=source,env=env,check=True)
            subprocess.run([str(go),'build','-p=2','-mod=readonly','-trimpath','-o',str(target), './cmd/hyperdns' if name=='hyperdns' else '.'],cwd=source,env=env,check=True)
            if name=='hyperdns':
                import secrets
                dest=Path('/opt/hyperdns')
                if dest.exists():raise ValueError('Existing HyperDNS install; no data overwritten.')
                unit=Path('/etc/systemd/system/hyperdns.service')
                if unit.exists():raise ValueError('Existing HyperDNS unit; no changes made.')
                dest.mkdir(parents=True,mode=0o700)
                shutil.copy2(target,dest/'hyperdns');(dest/'hyperdns').chmod(0o755)
                cfg=json.loads((source/'config.example.json').read_text());password=secrets.token_urlsafe(24)
                cfg['server']['admin_password']=password;cfg['server']['api_key']=secrets.token_urlsafe(32)
                cfg['server']['api_bind']='127.0.0.1';cfg['access']['allow_all']=False
                (dest/'config.json').write_text(json.dumps(cfg,indent=2));(dest/'config.json').chmod(0o600)
                shutil.copy2(source/'scripts/hyperdns.service',unit)
                shutil.copy2(source/'version.json',dest/'version.json')
                link=Path('/usr/local/bin/hdns')
                if not link.exists():link.symlink_to(dest/'hyperdns')
                subprocess.run(['systemctl','daemon-reload'],check=True)
                subprocess.run(['systemctl','enable','--now','hyperdns'],check=True)
                subprocess.run(['systemctl','is-active','--quiet','hyperdns'],check=True)
                print('HyperDNS installed with whitelist enabled. Administrator: admin')
                print('Initial password (store privately): '+password)
                print('Open configuration: sudo hdns. Use a real domain/certificate before publishing DoH/DoT.')
            else:
                dest=Path('/usr/local/lib/beeny-engines');dest.mkdir(parents=True,exist_ok=True)
                staged=dest/(name+'.new');shutil.copy2(target,staged);staged.chmod(0o755);os.replace(staged,dest/name)
                manifest=json.loads((dest/'installed.json').read_text()) if (dest/'installed.json').exists() else {}
                manifest[name]=dict(commit=pin['commit'],sha256=hashlib.sha256((dest/name).read_bytes()).hexdigest())
                (dest/'installed.json').write_text(json.dumps(manifest));(dest/'installed.json').chmod(0o600)
                install_units();print('Installed. Pair in Settings → Paired tunnels. No VPN was restarted.')
        else:
            if name=='dragon':
                os_release=Path('/etc/os-release').read_text()
                if '\nID=debian\n' not in '\n'+os_release:raise ValueError('Dragon Fruit Relay supports Debian; use a separate Debian host.')
            dest=Path('/opt/beeny-upstream')/name
            if dest.exists():raise ValueError('Existing upstream installation; use its own upgrade manager.')
            shutil.copytree(source,dest)
            subprocess.run(['bash',str(dest/('doctor-dns.sh' if name=='doctor' else 'install.sh'))],cwd=dest,check=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('engine',choices=['arange','backpack','dragon','doctor','hyperdns'],nargs='?');args=parser.parse_args()
    if not args.engine:
        print('1 Arange | 2 BackPack | 3 Dragon Fruit (dedicated Debian) | 4 Doctor DNS (dedicated) | 5 HyperDNS (dedicated)')
        choice=input('Choose (0 cancels): ').strip()
        if choice not in {'1','2','3','4','5'}:return
        args.engine=['arange','backpack','dragon','doctor','hyperdns'][int(choice)-1]
    install(args.engine)
if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.SubprocessError) as e:raise SystemExit(str(e))
