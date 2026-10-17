"""Root-run signed backup rotation with optional AES-GCM encryption and SSH copy."""
import os,json,re,subprocess,fcntl
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from backup_engine import create,safe_file,ENV,BACKUPS

def encrypt(source,destination,key):
    nonce=os.urandom(12);cipher=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor()
    with source.open('rb') as src,destination.open('xb') as dst:
        dst.write(b'BEENYB1'+nonce)
        for block in iter(lambda:src.read(1024*1024),b''):dst.write(cipher.update(block))
        dst.write(cipher.finalize());dst.write(cipher.tag)
    destination.chmod(0o600)

def run():
    BACKUPS.mkdir(exist_ok=True)
    with (BACKUPS/'.scheduled.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        original=safe_file(create(full=True));path=safe_file('scheduled_'+original.name);original.rename(path)
        configfile=ENV.parent/'backup-policy.json'
        cfg=json.loads(configfile.read_text()) if configfile.exists() else {}
        count=int(cfg.get('keep',7))
        if not 2<=count<=90:raise ValueError('Backup retention must be 2–90 snapshots.')
        if cfg.get('ssh_host'):
            host=cfg['ssh_host'];remote=cfg['ssh_directory'];port=int(cfg.get('ssh_port',22));key=Path(cfg['ssh_identity'])
            if not re.fullmatch(r'[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+',host) or not re.fullmatch(r'/[A-Za-z0-9_./-]+',remote) or '..' in remote.split('/') or not 1<=port<=65535:raise ValueError('Invalid SSH backup destination.')
            if key.is_symlink() or not key.is_file() or key.stat().st_uid!=0 or key.stat().st_mode&0o077:raise ValueError('SSH identity must be a private root-owned file.')
            encryption=ENV.parent/'backup-encryption.key'
            if not encryption.exists():
                with os.fdopen(os.open(encryption,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as f:f.write(os.urandom(32))
            output=path.with_name(path.name+'.enc');encrypt(path,output,encryption.read_bytes())
            try:subprocess.run(['scp','-B','-P',str(port),'-i',str(key),'-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10',str(output),host+':'+remote.rstrip('/')+'/'+output.name],check=True,timeout=600)
            finally:output.unlink(missing_ok=True)
        # Rotate only scheduled full snapshots; updater backups and traffic history remain.
        files=sorted(BACKUPS.glob('scheduled_full_*.tar.gz'),key=lambda p:p.stat().st_mtime,reverse=True)
        for old in files[count:]:
            if not old.is_symlink():old.unlink()
        print('Verified backup created:',path.name)

if __name__=='__main__':run()
