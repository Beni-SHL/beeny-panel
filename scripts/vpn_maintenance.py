#!/usr/bin/env python3
"""Root-only PKI audit and explicit, backed-up renewal/revocation. Never replace the CA."""
import argparse,fcntl,json,os,re,shutil,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
PKI=Path('/etc/openvpn/easy-rsa/pki');RSA=PKI.parent/'easyrsa';CONF=Path('/etc/openvpn/server/server.conf')
def run(*args):return subprocess.run(list(args),check=True,text=True,capture_output=True,timeout=180,env=dict(os.environ,EASYRSA_BATCH='1',EASYRSA_PKI=str(PKI))).stdout.strip()
def valid_name(name):
    if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}',name):raise ValueError('Invalid certificate name')
    return name

def audit():
    result=[]
    for file in [PKI/'ca.crt',*sorted((PKI/'issued').glob('*.crt'))]:
        if not file.is_file():continue
        try:
            expires=run('openssl','x509','-in',str(file),'-enddate','-noout').split('=',1)[1]
            epoch=datetime.strptime(expires,'%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc).timestamp()
            result.append(dict(name=file.stem,days=int((epoch-time.time())//86400),expires=expires))
        except Exception:result.append(dict(name=file.stem,error='Certificate cannot be parsed'))
    return result

def refresh_crl():
    if not CONF.is_file():raise ValueError('OpenVPN configuration missing')
    ca_line=re.search(r'^ca\s+(\S+)\s*$',CONF.read_text(),re.M)
    if not ca_line or run('openssl','x509','-in',ca_line[1],'-fingerprint','-sha256','-noout')!=run('openssl','x509','-in',str(PKI/'ca.crt'),'-fingerprint','-sha256','-noout'):
        raise ValueError('CA mismatch: refresh the CRL at its issuing panel and deploy it; no changes made.')
    run(str(RSA),'gen-crl');target=Path('/etc/openvpn/crl.pem');tmp=target.with_suffix('.new');shutil.copyfile(PKI/'crl.pem',tmp);tmp.chmod(0o644);os.replace(tmp,target)

def revoke_all_serials(text,name):
    """Revoke every still-valid index entry for an exact CN, including renewed certificates."""
    now=datetime.now(timezone.utc).strftime('%y%m%d%H%M%SZ');lines=[]
    for line in text.splitlines():
        row=line.split('\t')
        if len(row)>=6 and row[0]=='V' and re.search(r'(?:^|/)CN='+re.escape(name)+r'(?:/|$)',row[5]):row[0]='R';row[2]=now
        lines.append('\t'.join(row))
    return '\n'.join(lines)+'\n'

def mutate(action,name,apply=False):
    valid_name(name)
    if name=='ca':raise ValueError('CA rotation requires a separate migration; it cannot be renewed as a client.')
    if not CONF.is_file():raise ValueError('OpenVPN configuration missing')
    ca_line=re.search(r'^ca\s+(\S+)\s*$',CONF.read_text(),re.M)
    if not ca_line or run('openssl','x509','-in',ca_line[1],'-fingerprint','-sha256','-noout')!=run('openssl','x509','-in',str(PKI/'ca.crt'),'-fingerprint','-sha256','-noout'):
        raise ValueError('Local PKI CA differs from the deployed VPN CA. Renew at the issuing panel, then deploy the certificate; do not replace this node CA.')
    if action=='renew':
        version=run(str(RSA),'--version');match=re.search(r'\b(\d+)\.(\d+)\.(\d+)\b',version)
        if not match or tuple(map(int,match.groups()))<(3,1,1) or tuple(map(int,match.groups()))==(3,2,0):
            raise ValueError('Use Easy-RSA 3.1.1+ (not 3.2.0). Older renew commands may replace private keys.')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+str(os.getpid());backup=Path('/root/beeny-pki-backups')/stamp;backup.mkdir(parents=True,mode=0o700);shutil.copytree(PKI,backup/'pki')
    deployed={}
    for file in [Path('/etc/openvpn/server/server.crt'),Path('/etc/openvpn/server/server.key'),Path('/etc/openvpn/crl.pem')]:
        if file.exists():shutil.copy2(file,backup/file.name);deployed[file]=backup/file.name
    try:
        if action=='revoke':
            run(str(RSA),'revoke',name)
            index=PKI/'index.txt';staged=index.with_suffix('.beeny-new');staged.write_text(revoke_all_serials(index.read_text(),name));staged.chmod(0o600);os.replace(staged,index)
            refresh_crl()
            from vpn_sessions import disable_ccd,local_sessions,disconnect_session
            disable_ccd(Path('/etc/openvpn/ccd')/name)
            for session in local_sessions(name):disconnect_session(name,session['id'],session['fingerprint'])
        else:
            # Supported by Easy-RSA 3.0/3.1; a failure leaves the backed-up PKI restored.
            run(str(RSA),'renew',name)
            run('openssl','verify','-CAfile',str(PKI/'ca.crt'),str(PKI/'issued'/f'{name}.crt'))
            if run('openssl','x509','-in',str(PKI/'issued'/f'{name}.crt'),'-pubkey','-noout')!=run('openssl','pkey','-in',str(backup/'pki/private'/f'{name}.key'),'-pubout'):
                raise ValueError('Renewal unexpectedly changed the certificate key')
            if name=='server':
                config=CONF.read_text();match=re.search(r'^cert\s+(\S+)\s*$',config,re.M)
                if not match:raise ValueError('Server certificate path missing')
                target=Path(match[1])
                if not target.is_absolute() or target.is_symlink() or not target.is_relative_to('/etc/openvpn'):raise ValueError('Unsupported deployed certificate path')
                # Renew must preserve the deployed key; never silently rotate a private key.
                keymatch=re.search(r'^key\s+(\S+)\s*$',config,re.M)
                if not keymatch:raise ValueError('Server key missing')
                certpub=run('openssl','x509','-in',str(PKI/'issued'/f'{name}.crt'),'-pubkey','-noout')
                keypub=run('openssl','pkey','-in',keymatch[1],'-pubout')
                if certpub!=keypub:raise ValueError('Renewed certificate key mismatch')
                stage=target.with_suffix('.staged');shutil.copyfile(PKI/'issued'/f'{name}.crt',stage);stage.chmod(0o644)
                if apply:
                    shutil.copy2(target,backup/'deployed-server.crt');os.replace(stage,target)
                    try:run('systemctl','restart','openvpn-server@server');run('systemctl','is-active','--quiet','openvpn-server@server')
                    except Exception:
                        shutil.copy2(backup/'deployed-server.crt',target);run('systemctl','restart','openvpn-server@server');raise
                else:print('Server certificate staged. Apply in a maintenance window; a VPN restart reconnects clients.')
            else:
                print('Client certificate renewed. Re-download and import the updated profile; an embedded expired certificate cannot update itself.')
    except Exception:
        shutil.rmtree(PKI);shutil.copytree(backup/'pki',PKI)
        for target,saved in deployed.items():shutil.copy2(saved,target)
        raise
    print('PKI backup:',backup)

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['audit','maintain','refresh-crl','renew','revoke']);p.add_argument('name',nargs='?');p.add_argument('--apply',action='store_true');args=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run as root')
    lock=Path('/etc/openvpn/.beeny-pki.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX)
    if args.action in {'audit','maintain'}:
        result=audit();print(json.dumps(result,indent=2))
        if args.action=='maintain':
            refresh_crl()
            if any(r.get('days',366)<30 for r in result):print('WARNING: PKI renewal needed; run renew NAME, and renew server --apply during maintenance.')
    elif args.action=='refresh-crl':refresh_crl()
    else:
        if not args.name:p.error('Certificate name required')
        mutate(args.action,args.name,args.apply)
if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]));main()
