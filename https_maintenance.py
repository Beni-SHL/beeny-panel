"""Bounded HTTPS renewal jobs; never alters OpenVPN or stops Nginx."""
import json,os,re,shutil,subprocess,time
from pathlib import Path
ROOT=Path('/var/lib/beeny/https')
UNIT='beeny-https-renew'

def run(*args):
    return subprocess.run(list(args),capture_output=True,text=True,check=True,timeout=15)

def config():
    from privileged_server import https_status
    status=https_status()
    if not status.get('success'):raise ValueError(status.get('message','Certificate unavailable'))
    domain=status.get('cert_name',status['domain'])
    path=Path('/etc/letsencrypt/renewal')/(domain+'.conf')
    if not path.is_file():raise ValueError('Matching Certbot renewal configuration is missing.')
    source=path.read_text()
    # Standalone validation can require stopping a live web server. Do not do that automatically.
    match=re.search(r'^authenticator\s*=\s*(\S+)',source,re.M)
    if not match or match[1]=='standalone':raise ValueError('Renewal uses standalone validation. Configure webroot, nginx or DNS validation before enabling unattended renewal.')
    certbot=shutil.which('certbot')
    if not certbot:raise ValueError('Certbot is not installed.')
    return domain,certbot

def schedule(action, detached=False):
    if action not in {'test','renew','enable','disable'}:raise ValueError('Invalid HTTPS action.')
    if action in {'enable','disable'} and not detached:
        if action=='enable':config()
        run('systemd-run','--quiet','--collect','--unit=beeny-https-control','--property=Type=exec','/opt/beeny-panel/venv/bin/python','/opt/beeny-panel/https_maintenance.py',action)
        return dict(success=True,queued=True,message='Scheduler change queued. Refresh to verify the actual timer state.')
    if action=='disable':
        run('systemctl','disable','--now',UNIT+'.timer')
        return dict(success=True,message='Beeny HTTPS timer disabled; other certificate schedules are unchanged.')
    domain,certbot=config()
    if action=='enable':
        unit=Path('/etc/systemd/system')
        service='[Unit]\nDescription=Beeny panel HTTPS certificate renewal\n[Service]\nType=oneshot\nExecStart=/opt/beeny-panel/venv/bin/python /opt/beeny-panel/https_maintenance.py renew\nTimeoutStartSec=15min\n'
        timer='[Unit]\nDescription=Beeny panel certificate renewal schedule\n[Timer]\nOnCalendar=*-*-* 00,12:00:00\nRandomizedDelaySec=3600\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
        for suffix,text in [('service',service),('timer',timer)]:
            path=unit/(UNIT+'.'+suffix);temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(text);temporary.chmod(0o644);os.replace(temporary,path)
        run('systemctl','daemon-reload');run('systemctl','enable','--now',UNIT+'.timer')
        return dict(success=True,message='Automatic renewal scheduled twice daily; use Test renewal to verify domain validation.')
    # One fixed unit prevents concurrent clicks from spawning duplicate renewal jobs.
    run('systemd-run','--quiet','--collect','--unit=beeny-https-manual','--property=Type=exec','/opt/beeny-panel/venv/bin/python','/opt/beeny-panel/https_maintenance.py',action)
    return dict(success=True,queued=True,message='Renewal job queued. Refresh to see its verified result.')

def execute(action):
    import fcntl
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (ROOT/'lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=dict(action=action,started_at=int(time.time()),state='running')
        def save():
            temp=ROOT/'result.tmp';temp.write_text(json.dumps(result));temp.chmod(0o600);os.replace(temp,ROOT/'result.json')
        save()
        try:
            domain,certbot=config()
            args=[certbot,'renew','--cert-name',domain,'--non-interactive']
            if action=='test':args+=['--dry-run']
            elif action!='renew':raise ValueError('Invalid action.')
            subprocess.run(args,check=True,capture_output=True,text=True,timeout=800)
            if action=='renew':
                run('nginx','-t');run('systemctl','reload','nginx')
            result.update(state='succeeded',message='Renewal test passed.' if action=='test' else 'Renewal check completed; Nginx reloaded. Certificates not yet due are kept.')
        except Exception:
            result.update(state='failed',message='Renewal failed. Inspect the HTTPS job journal; no success is assumed.')
        finally:
            result['finished_at']=int(time.time());save()
        return result['state']=='succeeded'

if __name__=='__main__':
    import sys
    action=sys.argv[1]
    if action in {'enable','disable'}:
        try:
            result=schedule(action,detached=True);result.update(state='succeeded',action=action,finished_at=int(time.time()))
        except Exception:
            result=dict(state='failed',action=action,message='Scheduler configuration failed; inspect beeny-https-control journal.',finished_at=int(time.time()))
        ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
        target=ROOT/'result.json';temporary=ROOT/'control-result.tmp';temporary.write_text(json.dumps(result));temporary.chmod(0o600);os.replace(temporary,target)
        raise SystemExit(0 if result['state']=='succeeded' else 1)
    raise SystemExit(0 if execute(action) else 1)
