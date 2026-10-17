"""Explicit retrieval of registered Iran IPv4 resources; never auto-applies routes."""
import ipaddress,json,time
from pathlib import Path
import requests
URL='https://stat.ripe.net/data/country-resource-list/data.json?resource=IR&v4_format=prefix'

def prefixes(payload):
    rows=payload.get('data',{}).get('resources',{}).get('ipv4')
    if not isinstance(rows,list) or not 1<=len(rows)<=20000:raise ValueError('Iran resource data is missing or oversized.')
    nets=[]
    for value in rows:
        if not isinstance(value,str) or len(value)>80:raise ValueError('Invalid Iran resource entry.')
        if '-' in value:
            start,end=map(ipaddress.IPv4Address,value.split('-',1));nets.extend(ipaddress.summarize_address_range(start,end))
        else:nets.append(ipaddress.IPv4Network(value,strict=False))
    result=list(ipaddress.collapse_addresses(nets))
    if len(result)>4096 or any(n.prefixlen==0 or not n.is_global for n in result):raise ValueError('The resource list cannot be applied safely within the supported route count.')
    return [str(n) for n in result]

def retrieve(instance,refresh=False):
    path=Path(instance)/'iran-network-resources.json'
    if path.is_file() and not refresh:
        try:
            cached=json.loads(path.read_text())
            if time.time()-cached['fetched_at']<86400:return cached
        except (OSError,ValueError,KeyError,TypeError):pass
    with requests.Session() as session:
        session.trust_env=False
        with session.get(URL,stream=True,timeout=(5,15),allow_redirects=False) as response:
            if response.status_code!=200:raise ValueError('Iran resource source did not respond. Paste a verified CIDR list instead.')
            chunks=[];length=0
            for chunk in response.iter_content(65536):
                length+=len(chunk)
                if length>2*1024*1024:raise ValueError('Iran resource response is too large.')
                chunks.append(chunk)
    payload=json.loads(b''.join(chunks))
    result=dict(prefixes=prefixes(payload),fetched_at=int(time.time()),source=URL,query_time=str(payload.get('data',{}).get('query_time','')))
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(result));temp.chmod(0o600);temp.replace(path)
    return result
