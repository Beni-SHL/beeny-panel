"""Process-wide, non-blocking host samples. Never confuse counters with rates."""
import ipaddress, math, os, re, subprocess, threading, time
from pathlib import Path
import psutil
_LOCK=threading.Lock()
_PREVIOUS=None
_CACHE=None

def rate(previous,current):
    if not previous or current['boot_id']!=previous['boot_id'] or current['interface']!=previous['interface']:
        return None,None
    elapsed=current['sample_mono']-previous['sample_mono']
    if not 0<elapsed<=120:return None,None
    if current['received']<previous['received'] or current['sent']<previous['sent']:return None,None
    return ((current['received']-previous['received'])*8/elapsed/1e6,
            (current['sent']-previous['sent'])*8/elapsed/1e6)

def pool_capacity(text):
    """Dynamic pool only; explicit pool overrides server helper defaults."""
    directives={}
    for line in text.splitlines():
        parts=line.split('#',1)[0].split(';',1)[0].split()
        if parts:directives[parts[0]]=parts[1:]
    topology=directives.get('topology',['net30'])[0]
    try:
        if 'ifconfig-pool' in directives:
            a,b=directives['ifconfig-pool'][:2];size=int(ipaddress.IPv4Address(b))-int(ipaddress.IPv4Address(a))+1
            capacity=size if topology=='subnet' else size//4
        else:
            a,mask,*flags=directives['server']
            if 'nopool' in flags:return None
            n=ipaddress.IPv4Network((a,mask),strict=False).num_addresses
            capacity=max(0,n-3) if topology=='subnet' else max(0,n//4-2)
        max_clients=int(directives.get('max-clients',[capacity])[0])
        return max(0,min(capacity,max_clients))
    except (ValueError,KeyError,IndexError):return None

def vpn_details():
    try:
        active=subprocess.run(['systemctl','is-active','--quiet','openvpn-server@server'],timeout=2).returncode==0
        path=Path('/var/log/openvpn-status.log')
        fresh=path.is_file() and 0<=time.time()-path.stat().st_mtime<=90
        connections=None
        if active and fresh:
            from traffic_ledger import parse_status
            connections=len(parse_status(path.read_text()))
        try:
            text=Path('/etc/openvpn/server/server.conf').read_text();pool=pool_capacity(text)
            options={}
            for line in text.splitlines():
                parts=line.split('#',1)[0].split(';',1)[0].split()
                if parts:options[parts[0]]=parts[1:]
            tuning=dict(protocol=options.get('proto',['udp'])[0],tcp_nodelay='tcp-nodelay' in options or options.get('socket-flags')==['TCP_NODELAY'],
                tun_mtu=options.get('tun-mtu',['1500'])[0],topology=options.get('topology',['net30'])[0])
        except OSError:pool=None;tuning=None
        return dict(vpn_active=active,status_fresh=fresh,connections=connections,pool_capacity=pool,tuning=tuning)
    except (OSError,subprocess.SubprocessError):return dict(vpn_active=None,status_fresh=False,connections=None,pool_capacity=None)

def snapshot():
    global _PREVIOUS,_CACHE
    with _LOCK:
        now=time.monotonic()
        if _CACHE and now-_CACHE['sample_mono']<2:return dict(_CACHE)
        counters=psutil.net_io_counters(pernic=True,nowrap=False)
        interface=os.environ.get('BEENY_MONITOR_INTERFACE','').strip()
        if not interface:
            routes=[]
            for line in Path('/proc/net/route').read_text().splitlines()[1:]:
                p=line.split()
                if len(p)>6 and p[1]=='00000000' and int(p[3],16)&1 and not p[0].startswith(('lo','tun','tap','wg','warp','docker','veth')):
                    routes.append((int(p[6]),p[0]))
            if routes:interface=min(routes)[1]
        if interface not in counters:raise ValueError('Physical interface unavailable; set BEENY_MONITOR_INTERFACE explicitly.')
        times=psutil.cpu_times(percpu=True)
        memory=psutil.virtual_memory();disk=psutil.disk_usage('/')
        current=dict(metrics_schema=1,interface=interface,boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            received=counters[interface].bytes_recv,sent=counters[interface].bytes_sent,sample_mono=now,
            sampled_at=time.time(),uptime=max(0,int(time.time()-psutil.boot_time())),cpu=None,cpu_per_core=[],
            cpu_cores=len(times),memory=memory.percent,memory_total=memory.total,memory_used=memory.total-memory.available,
            disk=disk.percent,disk_total=disk.total,disk_used=disk.used,load=list(os.getloadavg()),cpu_steal=None)
        serial=[dict(total=sum(t)-getattr(t,'guest',0)-getattr(t,'guest_nice',0),idle=t.idle+getattr(t,'iowait',0),steal=getattr(t,'steal',0)) for t in times]
        prev=_PREVIOUS
        if prev and prev['boot_id']==current['boot_id'] and len(prev['_times'])==len(serial):
            cores=[];steal=[]
            for a,b in zip(prev['_times'],serial):
                total=b['total']-a['total']
                if total<=0:break
                cores.append(round(max(0,min(100,100*(total-(b['idle']-a['idle']))/total)),2))
                steal.append(max(0,100*(b['steal']-a['steal'])/total))
            if len(cores)==len(serial):current.update(cpu=round(sum(cores)/len(cores),2),cpu_per_core=cores,cpu_steal=round(sum(steal)/len(steal),2))
        current['rx_mbps'],current['tx_mbps']=rate(prev,current)
        current.update(vpn_details())
        _PREVIOUS=dict(current,_times=serial);_CACHE=current
        return dict(current)
