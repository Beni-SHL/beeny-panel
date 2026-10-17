"""Read bounded disconnect records; watermark processing lives in TrafficSample."""
import json,re
from pathlib import Path

def read_events(root=Path('/var/lib/beeny-vpn-events')):
    result=[]
    if not root.is_dir():return result
    for p in sorted(root.glob('*.json'))[:500]:
        if p.is_symlink() or p.stat().st_size>2048:continue
        try:
            row=json.loads(p.read_text())
            if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}',row['username']):continue
            if not str(row['since']).isdigit() or min(row['received'],row['sent'])<0:continue
            row['event_id']=p.stem;result.append(row)
        except (ValueError,KeyError,OSError,TypeError):continue
    return result

def merge_events(clients,events,samples):
    """Terminal totals replace a matching live snapshot; do not add another session."""
    result=list(clients);terminal=set()
    for event in events:
        prefix='|'.join([event['username'],event['address'],str(event['since'])])+'|'
        matching=[key for key in samples if key.startswith(prefix)]
        live=next((row for row in result if row[1].startswith(prefix)),None)
        key=live[1] if live else matching[0] if len(matching)==1 else prefix
        if len(matching)>1:continue # Ambiguous identity is never charged twice.
        result=[row for row in result if row[1]!=key]
        result.append((event['username'],key,event['received'],event['sent'],event['address']))
        terminal.add(key)
    return result,terminal

def acknowledge(ids,root=Path('/var/lib/beeny-vpn-events')):
    if not isinstance(ids,list) or len(ids)>500:raise ValueError('Invalid acknowledgement')
    for ident in ids:
        if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{64}',ident):raise ValueError('Invalid event ID')
    for ident in ids:
        file=root/(ident+'.json')
        if not file.is_symlink():file.unlink(missing_ok=True)
    return dict(success=True)
