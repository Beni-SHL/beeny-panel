#!/usr/bin/env python3
"""Read-only outage evidence; excludes private keys, tokens and panel environment."""
import subprocess,re,json,sys
from pathlib import Path
from datetime import datetime,timezone

def sanitize(text):
    text=re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----','[PRIVATE KEY REDACTED]',text,flags=re.S)
    text=re.sub(r'/bot[0-9]+:[A-Za-z0-9_-]+','/bot[REDACTED]',text)
    text=re.sub(r"(?i)Bearer\s+[^\s\"']+",'Bearer [REDACTED]',text)
    text=re.sub(r'(?i)(api[_-]?key|password|secret|token)([=:]\s*)[^\s,;]+',r'\1\2[REDACTED]',text)
    return text

def collect():
    sections=['BEENY VPN DIAGNOSTICS '+datetime.now(timezone.utc).isoformat()]
    commands=[['systemctl','status','openvpn-server@server','beeny-panel','beeny-customer-worker','beeny-privileged','beeny-node-bridge','--no-pager','--full'],['journalctl','-u','openvpn-server@server','--since','30 minutes ago','--no-pager','-o','short-iso'],['journalctl','-u','beeny-panel','-u','beeny-customer-worker','-u','beeny-privileged','-u','beeny-node-bridge','-u','beeny-pki.service','--since','30 minutes ago','-n','200','--no-pager','-o','short-iso'],['systemctl','is-active','pritunl'],['ip','-j','link','show'],['tc','-s','qdisc','show']]
    for command in commands:
        try:reply=subprocess.run(command,capture_output=True,text=True,timeout=15);sections+=['$ '+' '.join(command),reply.stdout[-30000:],reply.stderr[-1000:]]
        except (OSError,subprocess.TimeoutExpired) as error:sections.append(type(error).__name__)
    log=Path('/var/log/openvpn.log')
    if log.is_file():
        with log.open('rb') as f:
            f.seek(max(0,log.stat().st_size-150000));lines=f.read().decode(errors='replace').splitlines()
        signals=[line for line in lines if re.search('SIGTERM|SIGUSR1|Inactivity|AUTH_FAILED|VERIFY ERROR|CRL|client-kill|kill |Connection reset|TLS Error|ping-restart|process exiting|Initialization Sequence',line)]
        sections+=['VPN log decisions / recent signals','\n'.join(signals[-100:])]
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    try:
        import network_policy
        policy=network_policy.handle('status');active=policy.get('active',{});rules=active.get('policy',{})
        sections+=['Selected node network policy',json.dumps(dict(nft_available=policy.get('nft_available'),rules_present=policy.get('rules_present'),topology=active.get('topology'),counts={k:len(rules.get(k,'').splitlines()) for k in ['blocked_ips','blocked_domains','bypass_ips','bypass_domains']},diagnostics=policy.get('diagnostics')),ensure_ascii=False)]
    except Exception as error:sections+=['Network diagnostics unavailable: '+type(error).__name__]
    events=[]
    for path in list(Path('/var/lib/beeny-vpn-events').glob('*.json'))[:500]:
        try:
            if path.is_symlink() or path.stat().st_size>2048:continue
            row=json.loads(path.read_text());events.append({k:row.get(k) for k in ('username','finished','signal','platform','client')})
        except (ValueError,OSError):pass
    sections+=['Pending disconnect events (acknowledged events may already be removed)',json.dumps(sorted(events,key=lambda v:v.get('finished') or 0)[-20:],ensure_ascii=False)]
    return sanitize('\n'.join(sections))
if __name__=='__main__':print(collect())
