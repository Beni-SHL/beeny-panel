"""Verified atomic CRL deployment; reject a CRL not signed by this VPN's CA."""
import hashlib,json,re,subprocess,tempfile
from pathlib import Path
from datetime import datetime,timezone
VPN_ROOT=Path('/etc/openvpn')

def install_crl(pem,config=Path('/etc/openvpn/server/server.conf')):
    if not isinstance(pem,str) or not 100<=len(pem)<=512*1024:raise ValueError('Invalid CRL size')
    text=config.read_text();ca=re.search(r'^ca\s+(\S+)\s*$',text,re.M);crl=re.search(r'^crl-verify\s+(\S+)\s*$',text,re.M)
    if not ca or not crl:raise ValueError('Enable CRL verification in the VPN configuration first')
    target=Path(crl[1]);authority=Path(ca[1])
    if not target.is_absolute() or not target.is_relative_to(VPN_ROOT) or target.is_symlink():raise ValueError('Unsupported CRL deployment path')
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=target.parent,prefix='.beeny-crl-',delete=False) as stream:stream.write(pem);temp=Path(stream.name)
        subprocess.run(['openssl','crl','-in',str(temp),'-verify','-CAfile',str(authority),'-noout'],check=True,capture_output=True,timeout=10)
        dates=subprocess.run(['openssl','crl','-in',str(temp),'-lastupdate','-nextupdate','-noout'],check=True,capture_output=True,text=True,timeout=10).stdout
        values=dict(line.split('=',1) for line in dates.splitlines() if '=' in line)
        now=datetime.now(timezone.utc)
        start=datetime.strptime(values['lastUpdate'],'%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
        end=datetime.strptime(values['nextUpdate'],'%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
        if not start<=now<end:raise ValueError('CRL validity window is invalid')
        if target.is_file():
            old_dates=subprocess.run(['openssl','crl','-in',str(target),'-lastupdate','-noout'],check=True,capture_output=True,text=True,timeout=10).stdout
            old_start=datetime.strptime(old_dates.strip().split('=',1)[1],'%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
            if start<old_start:raise ValueError('Refusing an older CRL')
        if target.is_file():
            newnum=subprocess.run(['openssl','crl','-in',str(temp),'-crlnumber','-noout'],check=True,capture_output=True,text=True,timeout=10).stdout.strip().split('=',1)[-1]
            oldnum=subprocess.run(['openssl','crl','-in',str(target),'-crlnumber','-noout'],check=True,capture_output=True,text=True,timeout=10).stdout.strip().split('=',1)[-1]
            if newnum.startswith('0x') and oldnum.startswith('0x'):
                if int(newnum,16)<int(oldnum,16) or (int(newnum,16)==int(oldnum,16) and target.read_text()!=pem):raise ValueError('Refusing a non-increasing CRL number')
        temp.chmod(0o644);temp.replace(target);temp=None
    finally:
        if temp:temp.unlink(missing_ok=True)
    return dict(success=True,digest=hashlib.sha256(pem.encode()).hexdigest())

def register(app,db,Node,is_primary,privileged_enabled,privileged_call):
    class State(db.Model):
        __tablename__='node_crl_sync'
        node_id=db.Column(db.Integer,primary_key=True)
        digest=db.Column(db.String(64))
        pending=db.Column(db.Boolean,nullable=False,default=True)
    def sync():
        import requests
        from cluster import node_url
        try:
            pem=privileged_call('crl_material')['crl'] if privileged_enabled() else Path('/etc/openvpn/crl.pem').read_text()
            digest=hashlib.sha256(pem.encode()).hexdigest()
        except (OSError,RuntimeError):return
        for node in Node.query.all():
            if is_primary(node):continue
            state=db.session.get(State,node.id)
            if state and state.digest==digest and not state.pending:continue
            if not state:state=State(node_id=node.id);db.session.add(state)
            try:
                r=requests.post(node_url(node)+'/api/node/set-crl',json={'crl':pem},headers={'Authorization':'Bearer '+node.api_key},timeout=(2,4));r.raise_for_status()
                if not r.json().get('success') or r.json().get('digest')!=digest:raise RuntimeError('CRL not confirmed')
                state.digest=digest;state.pending=False
            except Exception:state.pending=True
        db.session.commit()
    return type('CrlSync',(),{'State':State,'sync':staticmethod(sync)})()
