#!/usr/bin/python3
import ipaddress,json,os,sys,urllib.request
from pathlib import Path

def admission(env,config,opener=urllib.request.urlopen,action="connect"):
    host=env.get('trusted_ip',env.get('trusted_ip6',''));address=ipaddress.ip_address(host);port=int(env['trusted_port'])
    peer=f'[{address}]:{port}' if address.version==6 else f'{address}:{port}'
    url=config['url']
    if not url.startswith('https://'):raise ValueError('Admission requires HTTPS')
    data=dict(node_id=int(config['node_id']),name=env['common_name'],address=peer,since=env['time_unix'],action=action)
    req=urllib.request.Request(url,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+config['token']})
    with opener(req,timeout=5) as response:return bool(json.load(response).get('allowed'))
if __name__=='__main__':
    try:
        allowed=admission(os.environ,json.loads(Path('/etc/openvpn/beeny-admission.json').read_text()))
        raise SystemExit(0 if allowed else 1)
    except Exception:raise SystemExit(1)
