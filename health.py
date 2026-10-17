"""Bounded, concurrent node probes. No private certificate material is sent."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime
from pathlib import Path
import time,requests,subprocess
from urllib.parse import urlsplit
from types import SimpleNamespace
from flask import render_template,request,redirect,jsonify
from flask_login import login_required

def register(app,db,Node,panel_path,is_primary):
    class Health(db.Model):
        __tablename__='node_health'
        node_id=db.Column(db.Integer,primary_key=True)
        checked_at=db.Column(db.DateTime)
        ok=db.Column(db.Boolean,default=False)
        latency_ms=db.Column(db.Integer)
        detail=db.Column(db.String(200))
        transport=db.Column(db.String(20))
    def probe(record):
        ident,local,target,key=record;start=time.monotonic();telemetry=None
        try:
            if local:
                result=subprocess.run(['systemctl','is-active','openvpn-server@server'],capture_output=True,text=True,timeout=4)
                path=Path('/var/log/openvpn-status.log');fresh=path.is_file() and time.time()-path.stat().st_mtime<90
                ok=result.returncode==0 and fresh
                detail='VPN active; fresh status' if ok else ('VPN '+(result.stdout.strip() or 'unavailable')+('; status stale' if not fresh else ''))
                transport='local'
                from host_traffic import metrics
                telemetry=metrics()
            else:
                from cluster import node_url
                address=node_url(SimpleNamespace(host=target,ip=target))
                response=requests.get(address.rstrip('/')+'/api/node/status-log',headers={'Authorization':'Bearer '+key},timeout=(2,4))
                response.raise_for_status();payload=response.json();telemetry=payload.get('metrics')
                ok=isinstance(payload.get('log'),str) and bool(payload.get('log'))
                detail='Status endpoint responding' if ok else 'Agent returned an empty status'
                transport='TLS' if address.startswith('https://') else 'legacy HTTP'
            return ident,ok,round((time.monotonic()-start)*1000),detail,transport,telemetry
        except Exception:return ident,False,round((time.monotonic()-start)*1000),'Node probe failed; verify agent, service and network','TLS' if target.startswith('https://') else 'legacy HTTP',None
    def scan():
        records=[(n.id,is_primary(n),(n.host or n.ip or '').strip(),n.api_key or '') for n in Node.query.all()]
        with ThreadPoolExecutor(max_workers=8) as pool:
            for future in as_completed([pool.submit(probe,r) for r in records]):
                ident,ok,latency,detail,transport,telemetry=future.result();row=db.session.get(Health,ident)
                if not row:row=Health(node_id=ident);db.session.add(row)
                previously=row.ok;known=row.checked_at is not None
                from app import host_traffic
                name=next((n.name for n in Node.query.all() if n.id==ident),str(ident))
                host_traffic.record(ident,name,telemetry)
                row.checked_at=datetime.utcnow();row.ok=ok;row.latency_ms=latency;row.detail=detail;row.transport=transport
                if known and previously!=ok:
                    from app import experience
                    experience.notify(None,'Node recovered' if ok else 'Node unavailable',f'Node #{ident}: {detail}')
        db.session.commit()
    @app.route(panel_path.rstrip('/')+'/settings/health',methods=['GET','POST'])
    @login_required
    def health_page():
        if request.method=='POST':
            scan()
            if request.headers.get('X-Requested-With')=='XMLHttpRequest':return jsonify(success=True,message='Node checks completed.')
        return redirect(panel_path.rstrip('/')+'/settings/nodes')
    return SimpleNamespace(scan=scan,Health=Health)
