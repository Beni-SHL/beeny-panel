"""Privileged, account-scoped IPv4/IPv6 tunnel shaping; no public-interface qdisc edits.
HTB shares each account's rate across its certificates on one node. IFB shapes upload.
Policies persist; a small root-side watcher catches new connections without restarting VPN.
"""
import csv,hashlib,io,ipaddress,json,logging,os,re,subprocess,threading,time
from pathlib import Path
LOCK=threading.RLock()
ROOT='7bee:'
STORE=Path(os.environ.get('BEENY_SPEED_POLICY_FILE','/etc/openvpn/beeny-speed-policies.json'))
STATE={}
STOP=threading.Event()
LAST_ERROR=False

def run(*args):
    return subprocess.run(list(args),check=True,capture_output=True,text=True,timeout=8).stdout

def validate(account,names,down,up):
    if not isinstance(account,str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}',account):raise ValueError('Invalid certificate account.')
    if not isinstance(names,list) or not 1<=len(names)<=101 or account not in names:raise ValueError('Invalid certificate list.')
    for name in names:
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}',name):raise ValueError('Invalid certificate.')
    if type(down) is not int or type(up) is not int or not ((down==up==0) or (1<=down<=1000000 and 1<=up<=1000000)):raise ValueError('Invalid speed; use 64–1000000 kbit/s, or zero to remove.')
    return dict(names=sorted(set(names)),down=down,up=up)

def read():
    if not STORE.exists():return {}
    data=json.loads(STORE.read_text())
    if not isinstance(data,dict) or len(data)>10000:raise ValueError('Invalid stored speed policies.')
    return {key:validate(key,**value) for key,value in data.items()}

def save(data):
    STORE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STORE.with_suffix('.tmp')
    fd=os.open(tmp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(data,stream)
    os.replace(tmp,STORE)

def sessions(text):
    header=None;result=[]
    delimiter='\t' if 'HEADER\tCLIENT_LIST' in text else ','
    for row in csv.reader(io.StringIO(text),delimiter=delimiter):
        if row[:2]==['HEADER','CLIENT_LIST']:header={key:i for i,key in enumerate(row[2:],1)}
        elif header and row and row[0]=='CLIENT_LIST':
            def value(key):
                index=header.get(key)
                return row[index] if index is not None and index<len(row) else ''
            for key in ['Virtual Address','Virtual IPv6 Address']:
                raw=value(key)
                if not raw:continue
                address=ipaddress.ip_address(raw)
                if address.is_unspecified or address.is_loopback or address.is_multicast:raise ValueError('Invalid tunnel client IP.')
                result.append((value('Common Name'),str(address)))
    if header is None:raise ValueError('OpenVPN management status is incomplete.')
    return result

def tunnel_for(address):
    rows=json.loads(run('ip','-j','route','get',address))
    device=rows[0].get('dev','') if rows else ''
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}',device):raise ValueError('Tunnel interface unavailable.')
    links=json.loads(run('ip','-j','-d','link','show','dev',device))
    kind=(links[0].get('linkinfo') or {}).get('info_kind') if links else None
    # Reject DCO, Ethernet and default routes: never shape an unrelated host link.
    if kind!='tun':raise ValueError('Speed limits require a userspace TUN interface; DCO is unsupported.')
    return device

def plans(policies,connected,resolve=tunnel_for):
    owners={}
    for account,policy in policies.items():
        for name in policy['names']:
            if name in owners:raise ValueError('Certificate belongs to multiple speed policies.')
            owners[name]=account
    groups={}
    for name,address in connected:
        account=owners.get(name)
        if not account:continue
        interface=resolve(address);group=groups.setdefault(interface,{})
        group.setdefault(account,dict(**policies[account],addresses=[]))['addresses'].append(address)
    for group in groups.values():
        # IDs are unique within this complete interface plan; all device IPs share one class.
        for index,account in enumerate(sorted(group),1):
            group[account]['classid']=format(index,'x');group[account]['addresses']=sorted(set(group[account]['addresses']))
    return groups

def qdiscs(device):return json.loads(run('tc','-j','qdisc','show','dev',device))

def ensure_root(device):
    root=next((q for q in qdiscs(device) if q.get('root')),None)
    if root and root.get('handle')==ROOT:
        if root.get('kind')!='htb':raise ValueError('Owned qdisc has an unexpected type.')
        return
    if root and root.get('kind') not in {'noqueue','pfifo_fast','fq_codel'} and not (root.get('kind')=='fq' and root.get('handle')=='0:'):raise ValueError('Tunnel already has custom traffic control.')
    run('tc','qdisc','replace','dev',device,'root','handle',ROOT,'htb','default','0')

def ensure_upload(device):
    ifb='bny'+hashlib.sha256(device.encode()).hexdigest()[:10]
    found=subprocess.run(['ip','-j','-d','link','show','dev',ifb],capture_output=True,text=True,timeout=8)
    alias='beeny-speed:'+device
    if found.returncode:
        run('ip','link','add',ifb,'type','ifb');run('ip','link','set','dev',ifb,'alias',alias)
    else:
        link=json.loads(found.stdout)[0]
        if link.get('ifalias')!=alias or (link.get('linkinfo') or {}).get('info_kind')!='ifb':raise ValueError('IFB interface conflict.')
    run('ip','link','set','dev',ifb,'up')
    ingress=next((q for q in qdiscs(device) if q.get('kind') in {'ingress','clsact'}),None)
    if ingress:
        filters=json.loads(run('tc','-j','filter','show','dev',device,'ingress'))
        if filters and (found.returncode or any(str(f.get('pref'))!='49152' or f.get('kind')!='matchall' for f in filters)):raise ValueError('Tunnel has foreign ingress filters.')
    else:run('tc','qdisc','add','dev',device,'handle','ffff:','ingress')
    if not ingress or not filters:
        run('tc','filter','add','dev',device,'ingress','protocol','all','pref','49152','handle','1','matchall','action','mirred','egress','redirect','dev',ifb)
    ensure_root(ifb)
    return ifb

def apply_device(device,groups,direction):
    ensure_root(device)
    # This parent is exclusively owned by Beeny. Filter removal prevents stale IP reuse.
    existing=json.loads(run('tc','-j','filter','show','dev',device,'parent',ROOT))
    if existing:run('tc','filter','del','dev',device,'parent',ROOT)
    handle=0
    for account,policy in sorted(groups.items()):
        classid=ROOT+policy['classid'];rate=str(policy[direction])+'kbit'
        run('tc','class','replace','dev',device,'parent',ROOT,'classid',classid,'htb','rate',rate,'ceil',rate,'burst','16k','cburst','16k')
        for address in policy['addresses']:
            handle+=1;version=ipaddress.ip_address(address).version
            run('tc','filter','add','dev',device,'parent',ROOT,'protocol','ip' if version==4 else 'ipv6','pref','100','handle',str(handle),'flower','dst_ip' if direction=='down' else 'src_ip',address,'classid',classid)
    # Unmatched traffic uses HTB's direct queue (default 0), never a shared low-rate class.

def reconcile():
    from vpn_sessions import Management
    with LOCK:
        policies=read()
        if policies:
            with Management() as connection:text=connection.command('status 3',status=True)
            target=plans(policies,sessions(text))
        else:target={}
        for device in sorted(set(target)|set(STATE)):
            group=target.get(device,{})
            if group==STATE.get(device):continue
            if not group:
                # Keep owned qdiscs but remove classifiers: nobody retains an old cap.
                for interface in [device,'bny'+hashlib.sha256(device.encode()).hexdigest()[:10]]:
                    if any(q.get('root') and q.get('handle')==ROOT for q in qdiscs(interface)):
                        if json.loads(run('tc','-j','filter','show','dev',interface,'parent',ROOT)):run('tc','filter','del','dev',interface,'parent',ROOT)
                STATE.pop(device,None);continue
            STATE[device]={'recover':True}
            upload=ensure_upload(device)
            apply_device(upload,group,'up');apply_device(device,group,'down')
            STATE[device]=group
        return dict(success=True,accounts=len(policies),active_addresses=sum(len(p['addresses']) for g in target.values() for p in g.values()))

def set_policy(account,names,down,up):
    global LAST_ERROR
    policy=validate(account,names,down,up)
    with LOCK:
        data=read()
        if down:data[account]=policy
        else:data.pop(account,None)
        if down:
            links=json.loads(run('ip','-j','-d','link','show'))
            configured=os.environ.get('BEENY_TUN_INTERFACE','')
            tunnels=[link['ifname'] for link in links if (link.get('linkinfo') or {}).get('info_kind')=='tun' and (not configured or link['ifname']==configured)]
            if not tunnels:raise ValueError('No supported userspace TUN; disable DCO before enabling fair use.')
            # One running OpenVPN tunnel is required for safe inactive-client probing.
            if len(tunnels)!=1:raise ValueError('Multiple TUN interfaces need explicit deployment review.')
            ensure_root(tunnels[0]);ensure_upload(tunnels[0])
        previous=read();save(data)
        try:
            result=reconcile();LAST_ERROR=False;return result
        except Exception:
            LAST_ERROR=True;save(previous)
            raise

def watch():
    global LAST_ERROR
    # Discover owned qdiscs after helper restarts so stale classifiers can be removed.
    try:
        for q in json.loads(run('tc','-j','qdisc','show')):
            if q.get('root') and q.get('handle')==ROOT and not q.get('dev','').startswith('bny'):STATE[q['dev']]={'recover':True}
    except Exception:logging.warning('Speed watcher capability unavailable; policy requests will report failures.')
    while not STOP.is_set():
        try:reconcile();LAST_ERROR=False
        except Exception:
            LAST_ERROR=True
            logging.warning('Speed reconciliation failed; retained last applied limits. Check tunnel traffic-control support.')
        STOP.wait(3)

def start():
    thread=threading.Thread(target=watch,name='beeny-speed-watch',daemon=True);thread.start();return thread
