"""Scoped VPN network rules. No global firewall flush, VPN restart or CA edits.
Uses a dedicated nftables table and a source/interface-scoped routing rule.
Domain entries resolve to an explicit IPv4 snapshot, not DPI or DNS interception.
"""
import contextlib,fcntl,hashlib,ipaddress,json,os,re,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path('/etc/openvpn/beeny-network-policy')
CONF=Path('/etc/openvpn/server/server.conf')
TABLE='beeny_policy'; ROUTE_TABLE='51866'; PRIORITY='18766'
WARP_MARK='0xbee9'
WARP_PRESETS={
 'telegram': {'domains':['telegram.org','api.telegram.org','t.me'], 'ips':['149.154.160.0/20','91.108.4.0/22','91.108.8.0/22','91.108.12.0/22','91.108.16.0/22','91.108.20.0/22','91.108.56.0/22']},
 'google': {'domains':['google.com','www.google.com','accounts.google.com','www.gstatic.com'],'ips':[]},
 'spotify': {'domains':['spotify.com','open.spotify.com','accounts.spotify.com','api.spotify.com'],'ips':[]},
 'instagram': {'domains':['instagram.com','www.instagram.com','i.instagram.com','graph.instagram.com'],'ips':[]},
}
BEGIN='# BEGIN BEENY CLIENT BYPASS'; END='# END BEENY CLIENT BYPASS'

def run(*args,input=None,check=True):
    return subprocess.run(list(args),input=input,text=True,capture_output=True,timeout=20,check=check)

def lines(value,limit):
    if not isinstance(value,str) or len(value)>150000:raise ValueError('Invalid rule list.')
    out=list(dict.fromkeys(x.strip() for x in value.splitlines() if x.strip() and not x.lstrip().startswith('#')))
    if len(out)>limit:raise ValueError('Too many rules.')
    return out

def validate(data):
    if not isinstance(data,dict):raise ValueError('Invalid network policy.')
    result={}
    for key,limit in [('blocked_ips',1000),('bypass_ips',4096),('warp_ips',1000)]:
        nets=[]
        for value in lines(data.get(key,''),limit):
            net=ipaddress.ip_network(value,strict=False)
            if net.version!=4 or net.prefixlen==0:raise ValueError('Use specific IPv4 networks; a default route is not permitted.')
            nets.append(net)
        result[key]='\n'.join(str(n) for n in ipaddress.collapse_addresses(nets))
    for key in ('blocked_domains','bypass_domains','warp_domains'):
        domains=[]
        for value in lines(data.get(key,''),40):
            try:value=value.lower().rstrip('.').encode('idna').decode('ascii')
            except UnicodeError:raise ValueError('Enter valid hostnames without a scheme, path or wildcard.')
            if not re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}',value):raise ValueError('Enter hostnames without a scheme, path or wildcard.')
            domains.append(value)
        result[key]='\n'.join(domains)
    ports=[]
    for value in lines(data.get('blocked_ports',''),100):
        if not re.fullmatch(r'\d{1,5}(?:-\d{1,5})?',value):raise ValueError('Use a port or a port range, one per line.')
        parts=[int(v) for v in value.split('-')]
        if not 1<=parts[0]<=parts[-1]<=65535:raise ValueError('Invalid port range.')
        ports.append('-'.join(str(v) for v in parts))
    result['blocked_ports']='\n'.join(ports)
    for key in ('torrent_ports','warp_enabled'):
        if not isinstance(data.get(key,False),bool):raise ValueError('Invalid policy switch.')
        result[key]=data.get(key,False)
    interface=data.get('warp_interface','')
    if not isinstance(interface,str) or (interface and not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}',interface)):raise ValueError('Invalid egress interface.')
    if result['warp_enabled'] and not interface:raise ValueError('Select the existing WARP tunnel interface.')
    result['warp_interface']=interface
    mode=data.get('warp_mode','all' if data.get('warp_enabled') and 'warp_presets' not in data else 'selected')
    if mode not in {'all','selected'}:raise ValueError('Invalid WARP routing mode.')
    presets=data.get('warp_presets',[])
    if not isinstance(presets,list) or any(not isinstance(k,str) or k not in WARP_PRESETS for k in presets):raise ValueError('Invalid WARP destination preset.')
    result.update(warp_mode=mode,warp_presets=sorted(set(presets)))
    return result

def load(name,default=None):
    path=ROOT/name
    return json.loads(path.read_text()) if path.is_file() else default

def save(name,data):
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    path=ROOT/name;temp=ROOT/(name+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False));temp.chmod(0o600);os.replace(temp,path)

@contextlib.contextmanager
def lock():
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (ROOT/'lock').open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        yield

def topology():
    text=CONF.read_text();opts={}
    for raw in text.splitlines():
        p=raw.strip().split()
        if p and p[0] in {'server','dev'}:opts[p[0]]=p[1:]
    if len(opts.get('server',[]))!=2:raise ValueError('An IPv4 OpenVPN server network is required.')
    net=ipaddress.ip_network('/'.join(opts['server']),strict=False)
    addresses=json.loads(run('ip','-j','-4','address','show').stdout)
    matches=[row['ifname'] for row in addresses if any(ipaddress.ip_address(a['local']) in net for a in row.get('addr_info',[]) if a.get('family')=='inet')]
    configured=(opts.get('dev') or [''])[0]
    if configured and configured!='tun':matches=[n for n in matches if n==configured]
    if len(matches)!=1 or not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}',matches[0]):raise ValueError('A single active OpenVPN TUN interface must match the server network.')
    return dict(interface=matches[0],subnet=str(net))

def resolve(policy,key='blocked_domains'):
    out={};started=time.monotonic()
    for domain in policy.get(key,'').splitlines():
        # Fixed binary/arguments, bounded subprocess lifetime; no shell.
        if time.monotonic()-started>20:raise ValueError('Hostname resolution took too long. Use a smaller list or explicit IP networks.')
        reply=subprocess.run(['getent','ahostsv4',domain],check=True,text=True,capture_output=True,timeout=3)
        ips=sorted({str(ipaddress.IPv4Address(row.split()[0])) for row in reply.stdout.splitlines() if row.split()})
        if not ips:raise ValueError('A blocked hostname could not be resolved; no rules were applied.')
        out[domain]=ips[:64]
    return out

def compile_rules(policy,topo,resolved,warp_destinations=None):
    tunnel=topo['interface'];blocked=policy['blocked_ips'].splitlines()
    for ips in resolved.values():blocked+=ips
    blocked=[str(n) for n in ipaddress.collapse_addresses(ipaddress.ip_network(x,strict=False) for x in blocked)]
    raw_ports=policy['blocked_ports'].splitlines()+(['6881-6889','6969'] if policy['torrent_ports'] else [])
    intervals=sorted((int(v.split('-')[0]),int(v.split('-')[-1])) for v in raw_ports)
    merged=[]
    for start,end in intervals:
        if merged and start<=merged[-1][1]+1:merged[-1][1]=max(merged[-1][1],end)
        else:merged.append([start,end])
    ports=[str(start) if start==end else f'{start}-{end}' for start,end in merged]
    rules=['table inet '+TABLE+' {',' chain forward { type filter hook forward priority -10; policy accept;']
    if blocked:rules.append('  iifname "'+tunnel+'" ip daddr { '+', '.join(blocked)+' } counter drop')
    if ports:
        for proto in ('tcp','udp'):rules.append('  iifname "'+tunnel+'" '+proto+' dport { '+', '.join(ports)+' } counter drop')
    rules.append(' }')
    if policy['warp_enabled']:
        rules+=[' chain postrouting { type nat hook postrouting priority 90; policy accept;',
                '  iifname "'+tunnel+'" oifname "'+policy['warp_interface']+'" ip saddr '+topo['subnet']+' counter masquerade',' }']
    if policy['warp_enabled'] and policy.get('warp_mode','all')=='selected':
        destinations=warp_destinations or []
        if not destinations:raise ValueError('Selected WARP routing needs resolved destinations.')
        rules+=[' chain prerouting { type filter hook prerouting priority -150; policy accept;',
                '  iifname "'+tunnel+'" ip saddr '+topo['subnet']+' ip daddr { '+', '.join(destinations)+' } counter meta mark set '+WARP_MARK,' }']
    rules.append('}')
    return '\n'.join(rules)+'\n'

def revision():
    return hashlib.sha256(json.dumps(load('active.json',{}),sort_keys=True).encode()+CONF.read_bytes()).hexdigest()

def rule_rows():return json.loads(run('ip','-j','-4','rule','show').stdout)

def prepare(data):
    if not shutil.which('nft'):raise ValueError('Install the nftables package on the selected node first.')
    policy=validate(data);topo=topology();resolved=resolve(policy);direct=resolve(policy,'bypass_domains')
    if policy['warp_enabled']:
        if policy['warp_interface']==topo['interface']:raise ValueError('The egress tunnel cannot be the OpenVPN interface.')
        link=json.loads(run('ip','-d','-j','link','show','dev',policy['warp_interface']).stdout)
        if not link or 'UP' not in link[0].get('flags',[]):raise ValueError('The selected egress interface is not up.')
        if link[0].get('linkinfo',{}).get('info_kind') not in {'wireguard','tun'}:raise ValueError('Choose an existing WireGuard or TUN egress interface, not a physical adapter.')
        if not shutil.which('curl'):raise ValueError('Install curl to verify WARP connectivity.')
        probe=run('curl','-4','--interface',policy['warp_interface'],'--connect-timeout','3','--max-time','8','--fail','--silent','--show-error','https://www.cloudflare.com/cdn-cgi/trace').stdout
        if not any(line.strip() in {'warp=on','warp=plus'} for line in probe.splitlines()):raise ValueError('The selected interface is not a verified connected WARP tunnel.')
        # A routing table/priority collision must never overwrite another application's policy.
        active=load('active.json',{}).get('policy',{})
        owned=active.get('warp_enabled',False)
        used=[r for r in rule_rows() if str(r.get('table'))==ROUTE_TABLE or str(r.get('priority'))==PRIORITY]
        routes=json.loads(run('ip','-j','-4','route','show','table',ROUTE_TABLE,check=False).stdout or '[]')
        if (used or routes) and not owned:raise ValueError('The dedicated routing table or priority is already in use.')
        if owned:
            old=load('active.json',{});oldtopo=old.get('topology',{})
            foreign=any(str(r.get('table'))!=ROUTE_TABLE or str(r.get('priority'))!=PRIORITY or r.get('src')!=oldtopo.get('subnet') or r.get('iif')!=oldtopo.get('interface') or (active.get('warp_mode','all')=='selected' and str(r.get('fwmark')) not in {WARP_MARK,str(int(WARP_MARK,16))}) for r in used)
            foreign=foreign or any(r.get('dst')!='default' or r.get('dev')!=active.get('warp_interface') for r in routes)
            if foreign:raise ValueError('Another routing rule now overlaps the reserved policy table. Resolve it before applying.')
    blocked=[ipaddress.ip_network(v) for v in policy['blocked_ips'].splitlines()]
    blocked += [ipaddress.ip_network(v+'/32') for values in resolved.values() for v in values]
    directs=[ipaddress.ip_network(v) for v in policy['bypass_ips'].splitlines()]
    directs += [ipaddress.ip_network(v+'/32') for values in direct.values() for v in values]
    if any(a.overlaps(b) for a in blocked for b in directs):raise ValueError('A destination cannot be both blocked and routed directly. Remove the overlapping entries.')
    warp_destinations=[]
    if policy['warp_enabled'] and policy['warp_mode']=='selected':
        domains=policy['warp_domains'].splitlines();ips=policy['warp_ips'].splitlines()
        for key in policy['warp_presets']:
            domains+=WARP_PRESETS[key]['domains'];ips+=WARP_PRESETS[key]['ips']
        if len(set(domains))>40:raise ValueError('Use at most 40 WARP hostnames including presets.')
        lookup=resolve({'warp_domains':'\n'.join(dict.fromkeys(domains))},'warp_domains')
        ips += [ip for values in lookup.values() for ip in values]
        warp_destinations=[str(n) for n in ipaddress.collapse_addresses(ipaddress.IPv4Network(v,strict=False) for v in ips)]
        if not warp_destinations:raise ValueError('Choose a WARP preset or enter destinations.')
        if any(ipaddress.IPv4Network(v).overlaps(n) for v in warp_destinations for n in blocked+directs):raise ValueError('WARP destinations overlap blocked or direct routes.')
    state=dict(warp_destinations=warp_destinations,policy=policy,topology=topo,resolved=resolved,bypass_resolved=direct,base_revision=revision())
    state['revision']=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest()
    return state

def nft_apply(rules):
    exists=run('nft','list','table','inet',TABLE,check=False).returncode==0
    batch=('delete table inet '+TABLE+'\n' if exists else '')+rules
    run('nft','-c','-f','-',input=batch)
    run('nft','-f','-',input=batch)

def clear_routes(state):
    if state.get('policy',{}).get('warp_enabled'):
        topo=state['topology']
        for _ in range(8):
            removed=run('ip','-4','rule','del','priority',PRIORITY,'from',topo['subnet'],'iif',topo['interface'],*(['fwmark',WARP_MARK] if state['policy'].get('warp_mode','all')=='selected' else []),'lookup',ROUTE_TABLE,check=False)
            if removed.returncode:break
        run('ip','-4','route','flush','table',ROUTE_TABLE,check=False)

def configure_routes(state,old):
    clear_routes(old)
    if state['policy']['warp_enabled']:
        run('ip','-4','route','replace','table',ROUTE_TABLE,'default','dev',state['policy']['warp_interface'])
        run('ip','-4','rule','add','priority',PRIORITY,'from',state['topology']['subnet'],'iif',state['topology']['interface'],*(['fwmark',WARP_MARK] if state['policy'].get('warp_mode','all')=='selected' else []),'lookup',ROUTE_TABLE)

def client_routes(policy,resolved=None):
    nets=[ipaddress.IPv4Network(v) for v in policy['bypass_ips'].splitlines()]
    for addresses in (resolved or {}).values():nets.extend(ipaddress.IPv4Network(a+'/32') for a in addresses)
    collapsed=list(ipaddress.collapse_addresses(nets))
    if len(collapsed)>4096:raise ValueError('Too many client bypass routes. Reduce the networks or domains.')
    return [f'push "route {net.network_address} {net.netmask} net_gateway"' for net in collapsed]

def bypass(policy,resolved=None):
    text=CONF.read_text()
    if text.count(BEGIN)!=text.count(END) or text.count(BEGIN)>1:raise ValueError('Malformed managed bypass section.')
    if BEGIN in text:text=text[:text.index(BEGIN)]+text[text.index(END)+len(END):]
    entries=client_routes(policy,resolved)
    if entries:text=text.rstrip()+'\n\n'+BEGIN+'\n'+'\n'.join(entries)+'\n'+END+'\n'
    if text==CONF.read_text():return
    st=CONF.stat();temp=CONF.with_name('server.conf.beeny-network-tmp');temp.write_text(text);temp.chmod(st.st_mode&0o777);os.chown(temp,st.st_uid,st.st_gid);os.replace(temp,CONF)

def enact(state):
    old=load('active.json',{})
    # Write recovery metadata before kernel mutations, including helper termination.
    save('active.json',state)
    nft_apply(compile_rules(state['policy'],state['topology'],state['resolved'],state.get('warp_destinations')))
    configure_routes(state,old);bypass(state['policy'],state.get('bypass_resolved',{}))

def restore(previous):
    # Both versions may have routes after a process failure during application.
    clear_routes(load('active.json',{}))
    if previous:
        clear_routes(previous)
        enact(previous)
    else:
        if run('nft','list','table','inet',TABLE,check=False).returncode==0:run('nft','delete','table','inet',TABLE)
        bypass(validate({}));(ROOT/'active.json').unlink(missing_ok=True)

def diagnostics():
    data=dict(client_routes_need_restart=None,admission_hook=False,counters='',notes=[])
    text=CONF.read_text();data['admission_hook']='client-connect ' in text and 'vpn_admission.py' in text
    try:
        start=run('systemctl','show','openvpn-server@server','-p','ExecMainStartTimestampMonotonic','--value').stdout.strip()
        started=time.time()-time.monotonic()+int(start)/1000000
        data['client_routes_need_restart']=bool(int(start)==0 or CONF.stat().st_mtime>started+1)
    except (ValueError,OSError,subprocess.SubprocessError):data['notes'].append('Cannot verify the running VPN configuration; review the service state.')
    if shutil.which('nft'):
        data['counters']=run('nft','list','chain','inet',TABLE,'forward',check=False).stdout[:20000]
    if 'client-to-client' in [line.strip() for line in text.splitlines()]:data['notes'].append('OpenVPN client-to-client forwarding can bypass host firewall rules between VPN clients.')
    return data

def activate_client_routes():
    if load('pending.json'):raise ValueError('Confirm or roll back the pending network policy first.')
    state=load('active.json',{})
    if not state.get('policy'):raise ValueError('Apply and confirm the network policy first.')
    # Deliberate UI action only. Never run during installation or an ordinary update.
    import logging
    logging.warning('Beeny requested OpenVPN restart for client route delivery; explicit owner action')
    run('systemctl','restart','openvpn-server@server')
    run('systemctl','is-active','--quiet','openvpn-server@server')
    return dict(success=True,message='OpenVPN restarted. Existing sessions reconnect and receive the direct routes. No traffic or certificates were reset.')

def handle(action,data=None,expected=None):
    if action=='warp-status':return __import__('warp_manager').status()
    if action in {'warp-install','warp-remove'}:return __import__('warp_manager').queue(action.removeprefix('warp-'))
    if action=='activate-routes':
        with lock():return activate_client_routes()
    if action=='status':
        return dict(success=True,diagnostics=diagnostics(),active=load('active.json',{}),pending=load('pending.json'),rules_present=bool(shutil.which('nft')) and run('nft','list','table','inet',TABLE,check=False).returncode==0,nft_available=bool(shutil.which('nft')),revision=revision(),interfaces=[r['ifname'] for r in json.loads(run('ip','-j','link','show').stdout)])
    with lock():
        pending=load('pending.json')
        if action=='confirm':
            if not pending or pending['token']!=expected or pending['deadline']<=time.time():raise ValueError('No matching pending policy. Refresh status.')
            (ROOT/'pending.json').unlink();return dict(success=True,message='Network policy confirmed.')
        if action=='rollback':
            if not pending:raise ValueError('There is no pending change to roll back.')
            restore(pending['previous']);(ROOT/'pending.json').unlink();return dict(success=True,message='Previous network policy restored.')
        if pending:raise ValueError('Confirm or roll back the pending network change first.')
        state=prepare(data)
        rules=compile_rules(state['policy'],state['topology'],state['resolved'],state.get('warp_destinations'))
        if action=='preview':return dict(success=True,preview=rules+'\n# Client bypass routes (after planned restart/reconnect)\n'+'\n'.join(client_routes(state['policy'],state.get('bypass_resolved',{}))),**state)
        if action!='apply':raise ValueError('Invalid policy action.')
        if state['revision']!=expected:raise ValueError('Server settings changed. Preview the rules again before applying.')
        token=os.urandom(16).hex();previous=load('active.json')
        record=dict(token=token,deadline=time.time()+120,previous=previous)
        save('pending.json',record)
        # A detached root-owned rollback job survives panel/bridge failure.
        try:
            run('systemd-run','--quiet','--collect','--on-active=120s','--unit=beeny-network-rollback-'+token,sys.executable,str(Path(__file__).resolve()),'expire',token)
        except Exception:
            (ROOT/'pending.json').unlink(missing_ok=True);raise
        try:enact(state)
        except Exception:
            # Preserve pending record if rollback itself fails, so recovery can retry.
            # Include proposed metadata to remove partially installed routes.
            save('active.json',state)
            restore(previous);(ROOT/'pending.json').unlink(missing_ok=True);raise
        return dict(success=True,token=token,deadline=record['deadline'],message='Applied temporarily. Check VPN traffic and confirm within 120 seconds. Client bypass routes require a planned OpenVPN restart and client reconnect.')

def expire(token):
    with lock():
        pending=load('pending.json')
        if pending and pending['token']==token:
            restore(pending['previous']);(ROOT/'pending.json').unlink()

def boot():
    with lock():
        pending=load('pending.json')
        if pending:
            restore(pending['previous']);(ROOT/'pending.json').unlink()
        active=load('active.json')
        if active:
            active['topology']=topology()
            enact(active)

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='expire':expire(sys.argv[2])
    elif len(sys.argv)==2 and sys.argv[1]=='boot':boot()
    else:raise SystemExit('Only the fixed rollback and boot operations are available.')
