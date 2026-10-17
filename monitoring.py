"""Read-only node telemetry, retained peaks and explicitly uncertain capacity guidance."""
import json, math, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from types import SimpleNamespace
import requests
from flask import abort,jsonify,request
from flask_login import current_user,login_required

def number(value,low=0,high=1e15):
    try:
        n=float(value)
        return n if math.isfinite(n) and low<=n<=high else None
    except (ValueError,TypeError):return None

def clean(payload):
    if not isinstance(payload,dict) or not any(k in payload for k in ('cpu','memory','disk','cpu_per_core')):return None
    cores=payload.get('cpu_per_core',[])
    if not isinstance(cores,list) or len(cores)>1024:return None
    cores=[v for v in (number(c,0,100) for c in cores) if v is not None]
    raw_tuning=payload.get('tuning')
    tuning={k:str(raw_tuning.get(k,''))[:32] for k in ('protocol','tun_mtu','topology')} if isinstance(raw_tuning,dict) else None
    if tuning is not None:tuning['tcp_nodelay']=raw_tuning.get('tcp_nodelay') is True
    return dict(tuning=tuning,metrics_schema=payload.get('metrics_schema') if payload.get('metrics_schema')==1 else None,cpu=number(payload.get('cpu'),0,100),core=max(cores) if cores else None,
        cores=cores,ram=number(payload.get('memory'),0,100),disk=number(payload.get('disk'),0,100),
        rx=number(payload.get('rx_mbps')),tx=number(payload.get('tx_mbps')),
        connections=number(payload.get('connections'),0,1000000),pool=number(payload.get('pool_capacity'),0,1000000),
        steal=number(payload.get('cpu_steal'),0,100),cpu_cores=number(payload.get('cpu_cores'),1,1024),
        memory_total=number(payload.get('memory_total')),interface=str(payload.get('interface',''))[:64],
        vpn_active=payload.get('vpn_active') if isinstance(payload.get('vpn_active'),bool) else None,
        uptime=number(payload.get('uptime')),boot_id=str(payload.get('boot_id',''))[:100])

def capacity(rows,pool,link_mbps):
    """No sales limit or resource-free capacity claims. No load generation."""
    valid=[r for r in rows if r['available'] and r['core'] is not None and r['connections'] is not None]
    peak=max((r['connections'] for r in valid),default=None)
    safe=[r for r in valid if r['core']<75 and (r['ram'] is not None and r['ram']<80)
          and (not link_mbps or (r['rx'] is not None and r['tx'] is not None and max(r['rx'],r['tx'])<link_mbps*.75))]
    tested=max((r['connections'] for r in safe),default=None)
    result=dict(observed_peak=peak,observed_with_headroom=tested,estimated_connections=None,confidence='insufficient',
        reason='Collect at least 24 hours including the busy period. Online devices are not necessarily transferring data.')
    if len(valid)<240 or (valid[-1]['at']-valid[0]['at']).total_seconds()<23*3600:return result
    loaded=[r for r in valid if r['connections']>=10 and r['core']>=20 and r['ram']<80]
    if not loaded:
        result['reason']='No representative busy load observed; extrapolation from an idle server is unreliable.';return result
    estimates=[]
    for r in loaded:
        limit=r['connections']*75/max(r['core'],1)
        if link_mbps and r['rx'] is not None and r['tx'] is not None:
            limit=min(limit,r['connections']*link_mbps*.75/max(r['rx'],r['tx'],.1))
        estimates.append(limit)
    estimates.sort();estimate=math.floor(estimates[int((len(estimates)-1)*.1)])
    if pool is not None:estimate=min(estimate,int(pool))
    result.update(estimated_connections=max(0,estimate),confidence='low',reason='Conservative linear estimate for similar usage only; CPU, traffic mix and network paths can change. Not an account sales limit.' if link_mbps else 'CPU-only estimate; provider bandwidth is unknown. Not a validated server capacity or account sales limit.')
    return result

def register(app,db,Node,panel_path,is_primary,privileged_enabled,privileged_call):
    class Setting(db.Model):
        __tablename__='monitoring_node_settings'
        node_id=db.Column(db.Integer,primary_key=True)
        link_mbps=db.Column(db.Float)
    class Point(db.Model):
        __tablename__='monitoring_points'
        id=db.Column(db.Integer,primary_key=True)
        node_id=db.Column(db.Integer,nullable=False,index=True)
        at=db.Column(db.DateTime,nullable=False,index=True)
        available=db.Column(db.Boolean,nullable=False)
        cpu=db.Column(db.Float);core=db.Column(db.Float);ram=db.Column(db.Float);disk=db.Column(db.Float)
        rx=db.Column(db.Float);tx=db.Column(db.Float);connections=db.Column(db.Integer)
        latency=db.Column(db.Float);vpn_active=db.Column(db.Boolean)
        __table_args__=(db.Index('ix_monitor_node_time','node_id','at'),)
    class Hour(db.Model):
        __tablename__='monitoring_hours'
        id=db.Column(db.Integer,primary_key=True)
        node_id=db.Column(db.Integer,nullable=False,index=True)
        at=db.Column(db.DateTime,nullable=False,index=True)
        samples=db.Column(db.Integer,default=0,nullable=False)
        available=db.Column(db.Integer,default=0,nullable=False)
        cpu=db.Column(db.Float);core=db.Column(db.Float);ram=db.Column(db.Float);disk=db.Column(db.Float)
        rx=db.Column(db.Float);tx=db.Column(db.Float);connections=db.Column(db.Integer)
        __table_args__=(db.UniqueConstraint('node_id','at'),)
    class Latest(db.Model):
        __tablename__='monitoring_latest'
        node_id=db.Column(db.Integer,primary_key=True)
        at=db.Column(db.DateTime,nullable=False)
        available=db.Column(db.Boolean,nullable=False)
        payload=db.Column(db.Text,nullable=False)
    fields=('cpu','core','ram','disk','rx','tx','connections')
    scan_lock=threading.Lock();started=threading.Event();last_cleanup=[0]
    def record(node_id,payload,latency,now=None):
        now=now or datetime.utcnow();data=clean(payload);available=data is not None
        latest=db.session.get(Latest,node_id)
        if latest and 0<=(now-latest.at).total_seconds()<20:return False
        if not latest:latest=Latest(node_id=node_id);db.session.add(latest)
        latest.at=now;latest.available=available;latest.payload=json.dumps(data or {})
        point=Point(node_id=node_id,at=now,available=available,latency=latency,vpn_active=data['vpn_active'] if data else None)
        if data:
            for key in fields:setattr(point,key,data[key])
        db.session.add(point)
        hour_at=now.replace(minute=0,second=0,microsecond=0)
        bucket=Hour.query.filter_by(node_id=node_id,at=hour_at).first()
        if not bucket:bucket=Hour(node_id=node_id,at=hour_at,samples=0,available=0);db.session.add(bucket)
        bucket.samples+=1;bucket.available+=int(available)
        if data:
            for key in fields:
                value=data[key];previous=getattr(bucket,key)
                if value is not None:setattr(bucket,key,value if previous is None else max(value,previous))
        return True
    def probe(n):
        ident,local,url,key=n;start=time.monotonic()
        try:
            if local:
                if privileged_enabled():payload=privileged_call('host_metrics')
                else:
                    from host_metrics import snapshot
                    payload=snapshot()
            else:
                r=requests.get(url+'/api/node/stats',headers={'Authorization':'Bearer '+key},timeout=(2,4))
                r.raise_for_status();payload=r.json().get('metrics')
            return ident,payload,round((time.monotonic()-start)*1000,1)
        except Exception:return ident,None,round((time.monotonic()-start)*1000,1)
    def scan():
        if not scan_lock.acquire(blocking=False):return
        try:
            from cluster import node_url
            records=[]
            for n in Node.query.all():
                try:records.append((n.id,is_primary(n),'' if is_primary(n) else node_url(n),n.api_key))
                except ValueError:record(n.id,None,None)
            # This is independent of the per-account enforcement loop.
            with ThreadPoolExecutor(max_workers=8) as pool:
                for ident,payload,latency in pool.map(probe,records):record(ident,payload,latency)
            if time.monotonic()-last_cleanup[0]>3600:
                Point.query.filter(Point.at<datetime.utcnow()-timedelta(days=2)).delete(synchronize_session=False)
                Hour.query.filter(Hour.at<datetime.utcnow()-timedelta(days=90)).delete(synchronize_session=False)
                last_cleanup[0]=time.monotonic()
            db.session.commit()
        finally:scan_lock.release()
    def start():
        if started.is_set():return
        started.set()
        def loop():
            while True:
                before=time.monotonic()
                try:
                    with app.app_context():scan()
                except Exception:app.logger.exception('Monitoring scan failed; retrying')
                time.sleep(max(1,30-(time.monotonic()-before)))
        threading.Thread(target=loop,name='node-monitoring',daemon=True).start()
    def point_dict(r):
        return dict(at=r.at,available=bool(r.available),**{k:getattr(r,k) for k in fields})
    @app.route(panel_path.rstrip('/')+'/api/monitoring',methods=['GET'])
    @login_required
    def monitoring_data():
        try:days=int(request.args.get('days','1'))
        except ValueError:abort(400)
        if days not in (1,7,30):abort(400)
        now=datetime.utcnow();cutoff=now-timedelta(days=days)
        nodes=Node.query.order_by(Node.id).all();ids=[n.id for n in nodes]
        if len(ids)>200:abort(400,'Monitoring view supports up to 200 nodes.')
        settings={s.node_id:s.link_mbps for s in Setting.query.filter(Setting.node_id.in_(ids))}
        latest={s.node_id:s for s in Latest.query.filter(Latest.node_id.in_(ids))}
        model=Point if days==1 else Hour
        grouped={n.id:[] for n in nodes}
        for row in model.query.filter(model.node_id.in_(ids),model.at>=cutoff).order_by(model.at):grouped[row.node_id].append(row)
        raw_grouped={n.id:[] for n in nodes}
        for row in Point.query.filter(Point.node_id.in_(ids),Point.at>=now-timedelta(days=2)).order_by(Point.at):raw_grouped[row.node_id].append(point_dict(row))
        out=[]
        for node in nodes:
            last=latest.get(node.id);data=json.loads(last.payload) if last else {}
            age=max(0,(now-last.at).total_seconds()) if last else None
            fresh=bool(last and last.available and age<=90)
            rows=[point_dict(r) for r in grouped[node.id]]
            for r in rows:
                if days!=1:r['available']=bool(r['available'])
            peaks={k:max((r[k] for r in rows if r['available'] and r[k] is not None),default=None) for k in fields}
            # Capacity estimates always use paired raw samples, never unrelated hourly maxima.
            raw=raw_grouped[node.id]
            guidance=capacity(raw,data.get('pool'),settings.get(node.id))
            if not fresh:guidance.update(estimated_connections=None,confidence='unavailable',reason='Node telemetry is unavailable or stale. Historical observations are not current capacity.')
            peak_times={k:next((r['at'].isoformat()+'Z' for r in reversed(rows) if r['available'] and r[k] is not None and r[k]==peaks[k]),None) for k in fields}
            alerts=[]
            if not fresh:alerts.append('Telemetry unavailable or stale; capacity is unknown. Update/check this node agent.')
            elif data.get('vpn_active') is False:alerts.append('OpenVPN is stopped.')
            if fresh:
                if data.get('metrics_schema')!=1:alerts.append('Legacy agent: update this node to obtain per-core CPU and real network rates.')
                if (data.get('core') or 0)>=85:alerts.append('A CPU core is heavily loaded.')
                if (data.get('ram') or 0)>=85:alerts.append('Memory pressure is high.')
                if (data.get('steal') or 0)>=10:alerts.append('High CPU steal: the VPS host may be oversubscribed.')
                link=settings.get(node.id)
                if link and max(data.get('rx') or 0,data.get('tx') or 0)>=link*.85:alerts.append('Traffic is approaching the configured provider port limit.')
                if data.get('pool') is not None and data.get('connections') is not None and data['pool']-data['connections']<=5:alerts.append('VPN address pool is nearly full.')
            performance=[]
            tuning=data.get('tuning')
            if tuning:
                if tuning['protocol'].startswith('tcp'):
                    performance.append('TCP transport: test UDP on the actual customer network before changing it. UDP availability is not guaranteed.')
                    if not tuning['tcp_nodelay']:performance.append('TCP_NODELAY is not explicit in this configuration. Review the OpenVPN version and measure before enabling it during maintenance.')
                performance.append('MTU '+tuning['tun_mtu']+' / '+tuning['topology']+'. MTU must be tested on the affected path; no automatic change is applied.')
            performance.append('To measure customer connection time, RTT, jitter and download/upload speed, test from the customer device while connected. Host telemetry and agent response time cannot measure that path.')
            history=[]
            # Bound UI points to 180 bins; retain maxima and gaps, not rounded fake zeroes.
            width=max(1,math.ceil(len(rows)/180))
            for i in range(0,len(rows),width):
                group=rows[i:i+width];entry=dict(at=group[-1]['at'].isoformat()+'Z')
                for k in fields:entry[k]=max((r[k] for r in group if r['available'] and r[k] is not None),default=None)
                history.append(entry)
            sample_count=len(rows) if days==1 else sum(r.samples for r in grouped[node.id])
            available_count=sum(r['available'] for r in rows) if days==1 else sum(r.available for r in grouped[node.id])
            out.append(dict(id=node.id,name=node.name,local=is_primary(node),fresh=fresh,age=age,checked_at=last.at.isoformat()+'Z' if last else None,
                current=data if fresh else None,last_known=data,peaks=peaks,peak_times=peak_times,history=history,capacity=guidance,alerts=alerts,performance=performance,
                link_mbps=settings.get(node.id),samples=sample_count,availability=round(available_count*100/sample_count,1) if sample_count else None,
                pool_free=max(0,int(data['pool']-data['connections'])) if fresh and data.get('pool') is not None and data.get('connections') is not None else None))
        response=jsonify(nodes=out,days=days,interval_seconds=30,raw_retention_hours=48,hourly_retention_days=90,
            note='Sampled peaks, not continuous maxima. Host traffic includes all services. API latency is not client VPN latency.')
        response.headers['Cache-Control']='no-store';return response
    @app.route(panel_path.rstrip('/')+'/api/monitoring/settings',methods=['POST'])
    @login_required
    def monitoring_settings():
        if getattr(current_user,'role','owner')!='owner':abort(403)
        from app import security
        security.check_csrf()
        try:node_id=int(request.form['node_id'])
        except (KeyError,ValueError):abort(400)
        Node.query.get_or_404(node_id)
        raw=request.form.get('link_mbps','').strip()
        value=number(raw,1,1000000) if raw else None
        if raw and value is None:abort(400,'Enter the provider port speed in Mbps, or leave blank.')
        setting=db.session.get(Setting,node_id)
        if not setting:setting=Setting(node_id=node_id);db.session.add(setting)
        setting.link_mbps=value;db.session.commit();return jsonify(success=True)
    return SimpleNamespace(Point=Point,Hour=Hour,Latest=Latest,Setting=Setting,record=record,scan=scan,start=start)
