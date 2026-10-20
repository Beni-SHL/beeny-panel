#!/usr/bin/env python3
"""Install only pinned, SHA-256 checked upstream FRP binaries and Beeny units."""
import hashlib
import io
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request

VERSION='0.71.1'
DIGESTS={'x86_64':('amd64','1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803'),
         'aarch64':('arm64','8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019')}

def download():
    if platform.machine() not in DIGESTS:raise ValueError('The managed tunnel supports amd64 and arm64 Linux hosts.')
    arch,digest=DIGESTS[platform.machine()]
    name=f'frp_{VERSION}_linux_{arch}'
    url=f'https://github.com/fatedier/frp/releases/download/v{VERSION}/{name}.tar.gz'
    with urllib.request.urlopen(url,timeout=60) as reply:data=reply.read(40*1024*1024+1)
    if len(data)>40*1024*1024 or hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Tunnel download checksum mismatch. Nothing installed.')
    result={}
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
        for binary in ['frpc','frps']:
            member=archive.getmember(name+'/'+binary)
            if not member.isfile() or member.size>40*1024*1024:raise ValueError('Unexpected tunnel archive.')
            result[binary]=archive.extractfile(member).read()
    return result

def main():
    if os.geteuid()!=0:raise SystemExit('Run from the Beeny SSH menu as root.')
    for role in ['entry','exit']:
        target=Path('/etc/systemd/system/beeny-tunnel-'+role+'.service')
        if target.exists() and '# Managed by Beeny' not in target.read_text():raise SystemExit('Unmanaged tunnel unit exists; review it before installing.')
    # Do not replace a running pair or unrelated administrator files.
    for role in ['entry','exit']:
        if subprocess.run(['systemctl','is-active','--quiet','beeny-tunnel-'+role]).returncode==0:
            raise SystemExit('Disable the managed tunnel in Settings before installing its engine.')
    data=download();root=Path('/usr/local/lib/beeny-frp');root.mkdir(parents=True,exist_ok=True,mode=0o755)
    for name,blob in data.items():
        temp=root/(name+'.new');temp.write_bytes(blob);temp.chmod(0o755);os.replace(temp,root/name)
    for role,binary in [('entry','frps'),('exit','frpc')]:
        target=Path('/etc/systemd/system/beeny-tunnel-'+role+'.service')
        if target.exists() and '# Managed by Beeny' not in target.read_text():raise SystemExit('Unmanaged tunnel unit exists; review it before installing.')
        target.write_text(f'''# Managed by Beeny
[Unit]
Description=Beeny paired tunnel {role}
After=network-online.target
Wants=network-online.target
[Service]
UnsetEnvironment=HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
ExecStart={root}/{binary} -c /etc/openvpn/beeny-tunnel/{binary}.toml
Restart=on-failure
RestartSec=3
User=root
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
[Install]
WantedBy=multi-user.target
''')
    subprocess.run(['systemctl','daemon-reload'],check=True)
    print('Verified FRP '+VERSION+' installed. Pair hosts in Settings → Paired tunnels. No tunnel or VPN was started.')
if __name__=='__main__':main()
