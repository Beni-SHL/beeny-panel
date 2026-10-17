"""Fixed root maintenance jobs; never accepts commands supplied by the browser."""
import fcntl,json,os,subprocess,sys,time,secrets
from pathlib import Path
ROOT=Path('/var/lib/beeny-maintenance')
CONFIG=Path('/etc/sysctl.d/99-beeny-bbr.conf')
SETTINGS={'net.core.default_qdisc':'fq','net.ipv4.tcp_congestion_control':'bbr'}
def run(*args,check=True):return subprocess.run(list(args),text=True,capture_output=True,check=check,timeout=30)
def save(name,data):
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    p=ROOT/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(data));t.chmod(0o600);os.replace(t,p)
def status():
    values={key:run('sysctl','-n',key).stdout.strip() for key in SETTINGS}
    return dict(success=True,values=values,available=run('sysctl','-n','net.ipv4.tcp_available_congestion_control',check=False).stdout.strip(),managed=(ROOT/'original.json').is_file(),job=json.loads((ROOT/'job.json').read_text()) if (ROOT/'job.json').is_file() else None)
def bbr(action):
    original=ROOT/'original.json'
    if action=='bbr-enable':
        if original.exists():raise ValueError('BBR settings are already managed. Restore them before applying again.')
        if CONFIG.exists():raise ValueError('An existing BBR configuration is not owned by this tool.')
        before={key:run('sysctl','-n',key).stdout.strip() for key in SETTINGS}
        run('modprobe','tcp_bbr')
        if 'bbr' not in run('sysctl','-n','net.ipv4.tcp_available_congestion_control').stdout.split():raise ValueError('This kernel does not provide BBR.')
        save('original.json',before)
        try:
            for key,value in SETTINGS.items():run('sysctl','-w',key+'='+value)
            CONFIG.write_text('# Managed by Beeny maintenance\n'+''.join(k+'='+v+'\n' for k,v in SETTINGS.items()));CONFIG.chmod(0o644)
        except Exception:
            for key,value in before.items():run('sysctl','-w',key+'='+value,check=False)
            CONFIG.unlink(missing_ok=True);original.unlink(missing_ok=True);raise
    else:
        if not original.exists():raise ValueError('No managed BBR changes to restore.')
        before=json.loads(original.read_text())
        if not CONFIG.is_file() or not CONFIG.read_text().startswith('# Managed by Beeny maintenance\n'):raise ValueError('The configuration changed outside this tool; automatic restore refused.')
        for key,value in SETTINGS.items():
            if run('sysctl','-n',key).stdout.strip()!=value:raise ValueError('TCP settings changed outside this tool; automatic restore refused.')
        try:
            for key,value in before.items():run('sysctl','-w',key+'='+value)
        except Exception:
            for key,value in SETTINGS.items():run('sysctl','-w',key+'='+value,check=False)
            raise
        CONFIG.unlink();original.unlink()
def queue(action):
    if action=='status':return status()
    if action not in {'bbr-enable','bbr-restore','panel-restart'}:raise ValueError('Invalid maintenance action.')
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (ROOT/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        job=status().get('job')
        if job and job['state'] in {'queued','running'} and time.time()-job['time']<180:raise ValueError('A maintenance job is still running.')
        token=secrets.token_hex(12);save('job.json',dict(action=action,token=token,state='queued',time=time.time()))
        try:run('systemd-run','--quiet','--collect','--on-active=2s','--unit=beeny-maintenance-'+token,sys.executable,str(Path(__file__).resolve()),action,token)
        except Exception:save('job.json',dict(action=action,token=token,state='failed',time=time.time()));raise
    return dict(success=True,message='Maintenance queued. Refresh status to see the result.')
def execute(action,token):
    if os.geteuid()!=0:raise PermissionError('Run as root.')
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (ROOT/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        job=json.loads((ROOT/'job.json').read_text())
        if job.get('token')!=token or job.get('action')!=action or job.get('state')!='queued':raise ValueError('Stale job.')
        job.update(state='running',time=time.time());save('job.json',job)
        try:
            if action in {'bbr-enable','bbr-restore'}:bbr(action)
            elif action=='panel-restart':run('systemctl','restart','beeny-panel','beeny-customer-worker')
            else:raise ValueError('Invalid maintenance action.')
            job.update(state='completed',message='Completed. No VPN restart was performed.')
        except Exception:
            job.update(state='failed',message='Operation failed. Inspect the maintenance job journal.');raise
        finally:job['time']=time.time();save('job.json',job)
if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit('Use the fixed maintenance queue.')
    execute(sys.argv[1],sys.argv[2])
