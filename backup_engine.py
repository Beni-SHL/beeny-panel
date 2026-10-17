"""Signed, complete backups with SQLite snapshots and bounded staged restore."""
import hashlib,hmac,json,os,re,shutil,sqlite3,tarfile,tempfile,time
from pathlib import Path,PurePosixPath
PANEL=Path('/opt/beeny-panel');VPN=Path('/etc/openvpn');ENV=Path('/etc/beeny-panel/panel.env');BACKUPS=PANEL/'backups'
MAX_BYTES=10*1024**3

def safe_file(name):
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.(?:db|tar\.gz)',name):raise ValueError('Invalid backup filename.')
    path=BACKUPS/name
    if path.is_symlink() or path.resolve().parent!=BACKUPS.resolve():raise ValueError('Unsafe backup path.')
    return path

def signing_key():
    path=ENV.parent/'backup-signing.key'
    if not path.exists():
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as f:f.write(os.urandom(32))
    return path.read_bytes()

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def snapshot(source,target):
    with sqlite3.connect(f'file:{source}?mode=ro',uri=True) as src,sqlite3.connect(target) as dst:
        if src.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Database integrity check failed.')
        src.backup(dst)

def create(full=True):
    BACKUPS.mkdir(parents=True,exist_ok=True)
    name=('full_' if full else 'db_')+time.strftime('%Y%m%dT%H%M%S')+'_'+os.urandom(4).hex()+('.tar.gz' if full else '.db')
    target=safe_file(name)
    try:
        with tempfile.TemporaryDirectory(prefix='beeny-backup-') as temp:
            stage=Path(temp);dbfile=stage/'snapshot.db';snapshot(PANEL/'instance/beeny.db',dbfile)
            if not full:
                shutil.copy2(dbfile,target)
                sig=hmac.new(signing_key(),digest(target).encode(),hashlib.sha256).hexdigest()
                target.with_suffix('.db.sig').write_text(sig)
            else:
                files={'panel/instance/beeny.db':dbfile,'env/panel.env':ENV}
                for base,prefix in [(PANEL,'panel'),(VPN,'vpn')]:
                    for file in base.rglob('*'):
                        relative=file.relative_to(base)
                        if base==PANEL and any(p in {'backups','venv','.venv-releases','.git','__pycache__'} for p in relative.parts):continue
                        if base==PANEL and str(relative).startswith('instance/beeny.db'):continue
                        if file.is_file() and (not file.is_symlink() or file.resolve().is_relative_to(base.resolve())):files[prefix+'/'+relative.as_posix()]=file
                manifest={name:dict(sha256=digest(file),size=file.stat().st_size) for name,file in files.items()}
                payload=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()
                envelope=dict(version=1,files=manifest,signature=hmac.new(signing_key(),payload,hashlib.sha256).hexdigest())
                manifestfile=stage/'manifest.json';manifestfile.write_text(json.dumps(envelope));files['manifest.json']=manifestfile
                with tarfile.open(target,'w:gz',dereference=True) as archive:
                    for name,file in files.items():archive.add(file,arcname=name,recursive=False)
                # Creation performs the same integrity checks as restore.
                validate(target)
        target.chmod(0o640)
        try:import pwd;os.chown(target,0,pwd.getpwnam('beeny').pw_gid)
        except KeyError:pass
        return target.name
    except Exception:
        target.unlink(missing_ok=True)
        target.with_suffix('.db.sig').unlink(missing_ok=True)
        raise

def validate(path,stage=None):
    if path.suffix=='.db':
        sig=path.with_suffix('.db.sig')
        if not sig.is_file() or not hmac.compare_digest(sig.read_text().strip(),hmac.new(signing_key(),digest(path).encode(),hashlib.sha256).hexdigest()):raise ValueError('Unsigned or modified database backup.')
        with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Invalid database backup.')
        return {'database':True}
    with tarfile.open(path,'r:gz') as archive:
        entries=archive.getmembers();seen=set();total=0
        for item in entries:
            parts=PurePosixPath(item.name).parts
            if item.name in seen or not item.isfile() or item.name.startswith('/') or '..' in parts or not parts or (parts[0] not in {'panel','vpn','env'} and item.name!='manifest.json'):raise ValueError('Unsafe archive member.')
            if parts[0]=='env' and item.name!='env/panel.env':raise ValueError('Unexpected environment file.')
            if parts[0]=='panel' and any(p in {'backups','venv','.venv-releases','.git'} for p in parts):raise ValueError('Unexpected application path.')
            seen.add(item.name);total+=item.size
            if item.size<0 or total>MAX_BYTES or len(seen)>100000:raise ValueError('Backup exceeds safe limits.')
        info=archive.getmember('manifest.json')
        if info.size>10*1024**2:raise ValueError('Oversized backup manifest.')
        envelope=json.load(archive.extractfile(info));manifest=envelope['files']
        signature=hmac.new(signing_key(),json.dumps(manifest,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature,envelope.get('signature','')):raise ValueError('Backup signature is invalid. Legacy unsigned archives require offline migration.')
        if seen!={'manifest.json',*manifest.keys()}:raise ValueError('Backup members do not match its signed manifest.')
        if 'panel/instance/beeny.db' not in manifest or 'env/panel.env' not in manifest:raise ValueError('Incomplete full backup.')
        for item in entries:
            if item.name=='manifest.json':continue
            h=hashlib.sha256();out=None
            if stage:
                out=Path(stage)/item.name;out.parent.mkdir(parents=True,exist_ok=True);handle=out.open('wb')
            else:handle=None
            with archive.extractfile(item) as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):
                    h.update(block)
                    if handle:handle.write(block)
            if handle:handle.close()
            if h.hexdigest()!=manifest[item.name]['sha256'] or item.size!=manifest[item.name]['size']:raise ValueError('Corrupted backup content.')
        if stage:
            with sqlite3.connect(f'file:{Path(stage)/"panel/instance/beeny.db"}?mode=ro',uri=True) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Restored database failed integrity validation.')
        return dict(files=len(manifest),bytes=total)

def restore(name):
    import subprocess,fcntl
    BACKUPS.mkdir(parents=True,exist_ok=True)
    with (BACKUPS/'.restore.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        source=safe_file(name);validate(source)
        recovery=create(full=True)
        with tempfile.TemporaryDirectory(prefix='beeny-restore-') as temp:
            stage=Path(temp)/'incoming';stage.mkdir()
            rollback=Path(temp)/'previous';rollback.mkdir()
            if source.suffix=='.db':snapshot(source,stage/'database.db')
            else:validate(source,stage)
            mappings=[]
            if source.suffix=='.db':mappings=[(stage/'database.db',PANEL/'instance/beeny.db')]
            else:
                for prefix,root in [('panel',PANEL),('vpn',VPN),('env',ENV.parent)]:
                    for file in (stage/prefix).rglob('*'):
                        if file.is_file():
                            target=root/file.relative_to(stage/prefix)
                            if prefix=='vpn' and target.is_symlink():
                                target=target.resolve()
                                if not target.is_relative_to(VPN.resolve()):raise ValueError('VPN symlink leaves its configuration directory.')
                            mappings.append((file,target))
            for _,target in mappings:
                allowed=any(target.resolve().is_relative_to(root.resolve()) for root in [PANEL,VPN,ENV.parent])
                if not allowed or target.is_symlink():raise ValueError('Unsafe restore destination.')
            services=['beeny-panel','beeny-customer-worker']
            active=[name for name in services if subprocess.run(['systemctl','is-active','--quiet',name],timeout=10).returncode==0]
            subprocess.run(['systemctl','stop',*services],check=True,timeout=30)
            changed=[]
            try:
                for index,(file,target) in enumerate(mappings):
                    old=rollback/str(index)
                    mode=target.stat().st_mode&0o777 if target.exists() else (0o644 if target.is_relative_to(PANEL) and not target.is_relative_to(PANEL/'instance') else 0o600)
                    if target.exists():shutil.copy2(target,old)
                    changed.append((target,old if old.exists() else None))
                    target.parent.mkdir(parents=True,exist_ok=True)
                    temporary=target.with_name(target.name+'.restore-tmp')
                    shutil.copyfile(file,temporary);temporary.chmod(mode);os.replace(temporary,target)
                for suffix in ('-wal','-shm'):Path(str(PANEL/'instance/beeny.db')+suffix).unlink(missing_ok=True)
                harden=PANEL/'scripts/harden_services.sh'
                if harden.exists():subprocess.run(['/bin/bash',str(harden)],check=True,timeout=60)
                if active:subprocess.run(['systemctl','start',*active],check=True,timeout=30)
            except Exception:
                subprocess.run(['systemctl','stop',*services],check=False,timeout=30)
                for target,old in reversed(changed):
                    if old:shutil.copy2(old,target)
                    else:target.unlink(missing_ok=True)
                for suffix in ('-wal','-shm'):Path(str(PANEL/'instance/beeny.db')+suffix).unlink(missing_ok=True)
                harden=PANEL/'scripts/harden_services.sh'
                if harden.exists():subprocess.run(['/bin/bash',str(harden)],check=True,timeout=60)
                if active:subprocess.run(['systemctl','start',*active],check=True,timeout=30)
                raise
        return dict(recovery=recovery)

if __name__=='__main__':
    import sys
    if len(sys.argv)==3 and sys.argv[1]=='restore':restore(sys.argv[2])
    else:print(create(full=True))
