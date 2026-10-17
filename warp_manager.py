"""Official WARP package lifecycle. Installation never registers or connects the client."""
import fcntl,json,os,shutil,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path('/var/lib/beeny/warp')
REPO=Path('/etc/apt/sources.list.d/beeny-cloudflare-warp.list')
KEY=Path('/usr/share/keyrings/beeny-cloudflare-warp.gpg')

def run(*args,timeout=20,input=None):
    return subprocess.run(list(args),input=input,capture_output=True,check=True,timeout=timeout,env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',NEEDRESTART_MODE='l'))

def supported():
    values={}
    for line in Path('/etc/os-release').read_text().splitlines():
        key,sep,value=line.partition('=')
        if sep:values[key]=value.strip('"')
    distro=values.get('ID');codename=values.get('VERSION_CODENAME')
    if (distro,codename) not in {('ubuntu','jammy'),('ubuntu','noble'),('ubuntu','resolute'),('debian','bookworm'),('debian','trixie')}:raise ValueError('Managed WARP packages support Ubuntu 22.04/24.04/26.04 and Debian 12/13 only.')
    return codename

def save(data):
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=ROOT/'result.tmp';tmp.write_text(json.dumps(data));tmp.chmod(0o600);tmp.replace(ROOT/'result.json')

def in_use():
    from network_policy import load
    return bool(load('active.json',{}).get('policy',{}).get('warp_enabled') or load('pending.json'))

def status():
    result=json.loads((ROOT/'result.json').read_text()) if (ROOT/'result.json').is_file() else None
    if result and result.get('state')=='running' and int(time.time())-result.get('started_at',0)>30:
        try:run('systemctl','is-active','--quiet','beeny-warp-package.service')
        except (OSError,subprocess.SubprocessError):result=dict(result,state='interrupted',message='The package job is no longer active. Check its journal before retrying.')
    return dict(success=True,installed=bool(shutil.which('warp-cli')),managed=(ROOT/'managed').is_file(),in_use=in_use(),job=result)

def queue(action):
    if action not in {'install','remove'}:raise ValueError('Invalid WARP package action.')
    supported()
    state=status()
    if action=='remove' and (not state['managed'] or state['in_use']):raise ValueError('Only a panel-managed WARP installation with no active or pending egress policy may be removed.')
    if action=='install' and state['in_use']:raise ValueError('Disable existing egress policies before installing another WARP client.')
    if action=='install' and state['installed']:raise ValueError('WARP is already installed. Existing installations are not replaced.')
    folder=Path(__file__).resolve().parent;python=sys.executable
    run('systemd-run','--quiet','--collect','--unit=beeny-warp-package','--property=Type=exec','--property=RuntimeMaxSec=15min',python,str(folder/'warp_manager.py'),action)
    return dict(success=True,message='WARP package job queued. Refresh to view the verified result.')

def execute(action):
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (ROOT/'lock').open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=dict(state='running',action=action,started_at=int(time.time()));save(state)
        try:
            codename=supported()
            if action=='install':
                if shutil.which('warp-cli'):raise ValueError('Existing WARP installation is not replaced.')
                prior=Path('/var/lib/cloudflare-warp')
                if prior.is_dir() and any(prior.iterdir()):raise ValueError('Existing WARP registration state must be reviewed manually; automatic reconnection is not permitted.')
                if in_use():raise ValueError('Disable existing egress policies before installing another WARP client.')
                # Install only the key obtained from the provider's fixed HTTPS origin.
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open('https://pkg.cloudflareclient.com/pubkey.gpg',timeout=15) as reply:
                    if reply.geturl()!='https://pkg.cloudflareclient.com/pubkey.gpg':raise ValueError('Unexpected repository key redirect.')
                    public=reply.read(100001)
                if len(public)>100000:raise ValueError('Invalid repository key.')
                key=run('gpg','--batch','--yes','--dearmor',input=public).stdout
                if not key:raise ValueError('Repository key conversion failed.')
                KEY.write_bytes(key);KEY.chmod(0o644)
                REPO.write_text(f'deb [signed-by={KEY}] https://pkg.cloudflareclient.com/ {codename} main\n');REPO.chmod(0o644)
                run('apt-get','update',timeout=300)
                # Claim package ownership before install so a partial package install is removable.
                (ROOT/'managed').write_text('Installed by Beeny; no registration or connection requested.\n')
                run('apt-get','install','-y','cloudflare-warp',timeout=500)
                if not shutil.which('warp-cli'):raise ValueError('Package did not supply warp-cli.')
                state.update(state='succeeded',message='Official WARP client installed. It is not registered or connected; VPN routing is unchanged.')
            elif action=='remove':
                from network_policy import lock
                with lock():
                    if in_use() or not (ROOT/'managed').is_file():raise ValueError('Disable the egress policy before removal.')
                    run('apt-get','remove','-y','cloudflare-warp',timeout=300)
                    if shutil.which('warp-cli'):raise ValueError('The WARP client is still installed.')
                    REPO.unlink(missing_ok=True);KEY.unlink(missing_ok=True);(ROOT/'managed').unlink(missing_ok=True)
                    state.update(state='succeeded',message='Panel-managed WARP package removed. No VPN data or certificates changed.')
            else:raise ValueError('Invalid WARP action.')
        except Exception:
            state.update(state='failed',message='WARP package operation failed. Inspect the beeny-warp-package journal; success is not assumed.')
        state['finished_at']=int(time.time());save(state)
        return state['state']=='succeeded'

if __name__=='__main__':raise SystemExit(0 if execute(sys.argv[1]) else 1)
