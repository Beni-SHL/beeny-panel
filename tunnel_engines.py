"""Additional paired engines. Restricted to encrypted carriers and local VPN targets."""
import hashlib,json,os
from pathlib import Path
import urllib.request
BIN=Path('/usr/local/lib/beeny-engines')
MODES={'arange-stealth':('arange','stealth'),'arange-kcp':('arange','kcp'),
       'backpack-stealth':('backpack','stealth'),'backpack-kcp':('backpack','kcp')}
def ready(mode):
    name,_=MODES[mode];path=BIN/name
    manifest=json.loads((BIN/'installed.json').read_text()) if (BIN/'installed.json').is_file() else {}
    if (not path.is_file() or path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022
        or hashlib.sha256(path.read_bytes()).hexdigest()!=manifest.get(name,{}).get('sha256')):
        raise ValueError('Install this pinned engine using: sudo beeny → Additional engines.')
def config(v,role,listener=None):
    if v['mode']=='arange-kcp' and v['vpn_proto']=='udp':raise ValueError('Arange KCP supports TCP VPN forwarding in Beeny. Use Noise or BackPack for a UDP VPN.')
    _,carrier=MODES[v['mode']]
    lines=['[server]' if role=='entry' else '[client]',
           ('bind_addr = "0.0.0.0:'+str(v['control_port'])+'"') if role=='entry' else 'remote_addr = '+json.dumps(address(v['host'],v['control_port'])),
           'transport = '+json.dumps(carrier),'token = '+json.dumps(v['token']),
           'skip_optz = true','proxy_protocol = false','pprof = false','sniffer = false',
           'web_bind = "127.0.0.1"','web_port = 17402','log_level = "info"','nodelay = true',
           'keepalive_period = 30','heartbeat = 10','dial_timeout = 10']
    if role=='entry':lines+=['ports = ['+json.dumps(str(v['public_port'])+'=127.0.0.1:'+str(v['vpn_port']))+']','accept_udp = '+str(v['vpn_proto']=='udp').lower()]
    return '\n'.join(lines)+'\n'
def address(host,port):return ('['+host+']' if ':' in host else host)+':'+str(port)
def registered(pair):
    # Live engine state, not a historical journal success or just an active systemd process.
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:17402/stats',timeout=4) as response:data=json.load(response)
        return str(data.get('tunnelStatus','')).startswith('Connected')
    except (OSError,ValueError):return False

def launch(role):
    import tunnel_manager as manager
    pair=manager.load()
    if not pair or pair['role']!=role:raise ValueError('Tunnel role does not match.')
    mode=pair['invitation']['mode']
    if mode in MODES:
        ready(mode);command=[str(BIN/MODES[mode][0]),'-c',str(manager.ROOT/'engine.toml')]
    else:
        name='frps' if role=='entry' else 'frpc';command=[str(manager.BIN/name),'-c',str(manager.ROOT/(name+'.toml'))]
    os.execv(command[0],command)
if __name__=='__main__':
    import sys
    if len(sys.argv)!=2 or sys.argv[1] not in {'entry','exit'}:raise SystemExit('Invalid role')
    launch(sys.argv[1])
