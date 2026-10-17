"""Explicit quota policies and owner-controlled client endpoints."""
import hashlib,ipaddress,json,re,time
_HEALTH_CACHE={}
from types import SimpleNamespace
from flask import abort,flash,redirect,render_template,request
from flask_login import current_user,login_required
import requests
from renewal import activation_error

def validate_policy(mode,down=2000,up=2000,quota=1):
    if mode not in {'metered','fair_use'}:raise ValueError('Choose metered or fair-use service.')
    try:down=int(down);up=int(up)
    except (ValueError,TypeError):raise ValueError('Speed must be an integer in kbit/s.') from None
    if not 64<=down<=1000000 or not 64<=up<=1000000:raise ValueError('Use 64–1000000 kbit/s for each direction.')
    if mode=='fair_use' and (quota is None or float(quota)<=0):raise ValueError('Fair-use accounts need a positive quota.')
    return dict(quota_mode=mode,throttle_down_kbps=down,throttle_up_kbps=up)

def endpoint(host,port):
    host=host.strip().lower()
    try:host=str(ipaddress.ip_address(host))
    except ValueError:
        if len(host)>253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in host.split('.')):raise ValueError('Enter a domain or IP without a scheme, path or port.')
    try:port=int(port)
    except (ValueError,TypeError):raise ValueError('Port must be 1–65535.') from None
    if not 1<=port<=65535:raise ValueError('Port must be 1–65535.')
    return dict(host=host,port=port)

def limited(user):
    return (getattr(user,'quota_mode','metered')=='fair_use' and user.traffic_limit>0 and
            (user.traffic_usage or 0)>=user.traffic_limit and user.status=='active' and not user.customer_paused and
            not activation_error(user.expire_date,0,0))

def register(app,db,User,Node,UserNode,features,panel_path,is_primary_node):
    base=panel_path.rstrip('/')
    def endpoints():
        try:return json.loads(features.get_setting('vpn_client_endpoints','{}'))
        except (ValueError,TypeError):return {}
    @app.route(base+'/settings/vpn-access',methods=['GET','POST'])
    @login_required
    def vpn_access_settings():
        if current_user.role!='owner':abort(403)
        error=None;values=endpoints();nodes=Node.query.order_by(Node.name).all()
        if request.method=='POST':
            features.verify_csrf()
            try:
                values={}
                for node in nodes:
                    host=request.form.get('host_'+str(node.id),'').strip()
                    if host:
                        values[str(node.id)]=endpoint(host,request.form.get('port_'+str(node.id),110))
                        proto=request.form.get('proto_'+str(node.id),'tcp')
                        if proto not in {'tcp','udp'}:raise ValueError('Protocol must be TCP or UDP.')
                        values[str(node.id)]['proto']=proto
                features.set_setting('vpn_client_endpoints',json.dumps(values));db.session.commit()
                flash('Client profile endpoints saved. Re-download profiles to use changed addresses.','success')
                return redirect(request.path)
            except ValueError as exc:error=str(exc)
        return render_template('vpn_access_settings.html',panel_path=panel_path,nodes=nodes,values=values,error=error)
    def remote(node,default_host,default_port):
        saved=endpoints().get(str(node.id))
        if saved:
            result=endpoint(saved['host'],saved['port'])
            if saved.get('proto')=='udp':result['proto']='udp'
            return result
        return dict(host=default_host,port=int(default_port))
    def node_call(node,method,data=None):
        from cluster import node_url
        url=node_url(node)+'/api/node/'+method
        response=requests.post(url,json=data,headers={'Authorization':'Bearer '+node.api_key},timeout=12) if data is not None else requests.get(url,headers={'Authorization':'Bearer '+node.api_key},timeout=6)
        if response.status_code!=200 or not response.json().get('success'):raise RuntimeError('Node speed operation was not confirmed.')
    def sync(user):
        from app import devices
        from privileged import enabled,call
        import bandwidth
        desired=limited(user)
        if desired and user.throttle_down_kbps is None:user.throttle_down_kbps=2000
        if desired and user.throttle_up_kbps is None:user.throttle_up_kbps=2000
        try:previous=json.loads(user.speed_state or '{}')
        except ValueError:previous={}
        selected={rel.node_id for rel in UserNode.query.filter_by(user_id=user.id)}
        names=[user.username]+[d.common_name for d in devices.Device.query.filter_by(user_id=user.id)]
        state=dict(nodes=sorted(selected),names=sorted(names),down=user.throttle_down_kbps,up=user.throttle_up_kbps,allocation='shared-v1') if desired else {}
        if not state and not previous and not user.speed_sync_pending:return []
        failures=[]
        for nid in sorted(selected|set(previous.get('nodes',[]))):
            node=db.session.get(Node,nid)
            if not node:continue
            down=max(1,user.throttle_down_kbps//max(1,len(selected))) if desired and nid in selected else 0
            up=max(1,user.throttle_up_kbps//max(1,len(selected))) if down else 0
            try:
                if state==previous and not user.speed_sync_pending:
                    if is_primary_node(node):
                        if enabled():call('speed_status')
                        elif bandwidth.LAST_ERROR:raise RuntimeError('Speed watcher failed.')
                    else:
                        checked,ok=_HEALTH_CACHE.get(node.id,(0,False))
                        if time.monotonic()-checked>30:
                            try:node_call(node,'speed-status');ok=True
                            except Exception:_HEALTH_CACHE[node.id]=(time.monotonic(),False);raise
                            _HEALTH_CACHE[node.id]=(time.monotonic(),ok)
                        if not ok:raise RuntimeError('Node speed watcher unavailable.')
                else:
                    payload=dict(username=user.username,names=names,down=int(down),up=int(up))
                    if is_primary_node(node):
                        if enabled():call('speed_policy',**payload)
                        else:bandwidth.set_policy(payload['username'],names,payload['down'],payload['up'])
                    else:node_call(node,'set-speed-policy',payload)
            except Exception:failures.append(node.name)
        user.speed_sync_pending=bool(failures)
        if not failures:user.speed_state=json.dumps(state) if state else ''
        db.session.commit()
        return failures
    @app.context_processor
    def context():return dict(customer_speed_limited=limited,node_crl_state=lambda ident:db.session.get(__import__('app').crl_sync.State,ident))
    return SimpleNamespace(sync=sync,endpoints=endpoints,remote=remote,limited=limited)
