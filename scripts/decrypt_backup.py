"""Decrypt an offsite snapshot; authenticate fully before exposing plaintext."""
import os,sys,tempfile
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes

def decrypt(source,target,keyfile):
    if target.exists():raise ValueError('Destination already exists.')
    if source.stat().st_size<35:raise ValueError('Invalid encrypted backup.')
    with source.open('rb') as src:
        header=src.read(19)
        if header[:7]!=b'BEENYB1':raise ValueError('Unrecognised backup format.')
        src.seek(-16,2);tag=src.read(16);remaining=source.stat().st_size-35;src.seek(19)
        decoder=Cipher(algorithms.AES(keyfile.read_bytes()),modes.GCM(header[7:],tag)).decryptor()
        fd,temp=tempfile.mkstemp(prefix='.beeny-decrypt-',dir=target.parent)
        try:
            with os.fdopen(fd,'wb') as out:
                while remaining:
                    chunk=src.read(min(1024*1024,remaining))
                    if not chunk:raise ValueError('Truncated backup.')
                    remaining-=len(chunk);out.write(decoder.update(chunk))
                out.write(decoder.finalize())
            os.link(temp,target)
        finally:Path(temp).unlink(missing_ok=True)
    return target
if __name__=='__main__':
    if len(sys.argv)!=4:raise SystemExit('Usage: decrypt_backup.py encrypted-file output.tar.gz encryption-key-file')
    print(decrypt(*map(Path,sys.argv[1:])))
