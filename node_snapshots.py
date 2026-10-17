"""Bounded parallel I/O, with no database/session access in worker threads."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import os,time,subprocess,requests
from pathlib import Path

def collect(records,privileged_enabled,privileged_call):
    def load(record):
        ident,local,url,key=record
        if local:
            if privileged_enabled():return privileged_call('status_log')
            path=Path('/var/log/openvpn-status.log')
            if subprocess.run(['systemctl','is-active','--quiet','openvpn-server@server'],timeout=5).returncode or not os.path.isfile(str(path)) or time.time()-os.path.getmtime(str(path))>90:raise RuntimeError('Local status unavailable')
            from terminal_traffic import read_events
            with open(path,encoding='utf-8') as stream:log=stream.read()
            return dict(log=log,events=read_events())
        r=requests.get(url+'/api/node/status-log',headers={'Authorization':'Bearer '+key},timeout=(2,3));r.raise_for_status()
        payload=r.json()
        if not isinstance(payload,dict) or not isinstance(payload.get('log'),str) or not payload['log'].strip():raise RuntimeError('Empty node status')
        if 'vpn_active' in payload and payload['vpn_active'] is not True:raise RuntimeError('Node VPN is stopped')
        if 'status_age' in payload and (payload['status_age'] is None or payload['status_age']>90):raise RuntimeError('Node status is stale')
        return payload
    result={}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures={pool.submit(load,record):record[0] for record in records}
        for future in as_completed(futures):
            try:result[futures[future]]=future.result()
            except Exception:result[futures[future]]=None
    return result
