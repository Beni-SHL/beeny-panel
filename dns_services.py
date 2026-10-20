"""Explicit per-account SmartDNS delivery; independent DNS accounts are never silently provisioned."""
import ipaddress,json,plistlib,re,secrets,socket,struct,time,uuid
from urllib.parse import urlsplit
from flask import abort,jsonify,render_template,request,Response
from flask_login import current_user,login_required
PROVIDERS={'doctor':'Doctor DNS','hyperdns':'HyperDNS'}
def clean(body):
    if not isinstance(body,dict):raise ValueError('Invalid DNS settings.')
    provider=body.get('provider')
    if provider not in PROVIDERS:raise ValueError('Select a DNS provider.')
    ip=ipaddress.ip_address(str(body.get('address','')).strip())
    if not ip.is_global:raise ValueError('Use a public DNS server address.')
    def https(value):
        value=str(value or '').strip();u=urlsplit(value)
        if value and (len(value)>2048 or u.scheme!='https' or not u.hostname or u.username or u.password or u.fragment):raise ValueError('Use an HTTPS URL without login information or fragments.')
        if u.hostname:
            try:literal=ipaddress.ip_address(u.hostname)
            except ValueError:
                if not re.fullmatch(r'[a-zA-Z0-9.-]+',u.hostname) or '.' not in u.hostname:raise ValueError('Invalid public service hostname.')
            else:
                if not literal.is_global:raise ValueError('Use a public service address.')
        return value
    dot=str(body.get('dot_host','')).strip().lower()
    if dot and (len(dot)>253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}',dot)):raise ValueError('DoT requires a valid certificate hostname, without a port.')
    return dict(provider=provider,address=str(ip),doh_url=https(body.get('doh_url')),dot_host=dot,
                portal_url=https(body.get('portal_url')),enabled=body.get('enabled') is True)
def probe(address):
    ip=ipaddress.ip_address(address)
    if not ip.is_global:raise ValueError('Use a public DNS address.')
    ident=secrets.randbelow(65536);question=b'\x07example\x03com\x00'+struct.pack('!HH',1,1)
    packet=struct.pack('!HHHHHH',ident,0x0100,1,0,0,0)+question
    start=time.monotonic()
    with socket.socket(socket.AF_INET6 if ip.version==6 else socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.settimeout(4);sock.connect((str(ip),53));sock.send(packet);answer=sock.recv(4096)
    if len(answer)<12:raise ValueError('Invalid DNS response.')
    rid,flags,_,count,_,_=struct.unpack('!HHHHHH',answer[:12]);rcode=flags&15
    if rid!=ident or not flags&0x8000:raise ValueError('Invalid DNS response identifier.')
    return dict(answered=True,rcode=rcode,answers=count,latency_ms=round((time.monotonic()-start)*1000),usable=rcode==0 and count>0)
def profile(cfg,label):
    dns={'ServerAddresses':[cfg['address']]}
    if cfg['doh_url']:dns.update(DNSProtocol='HTTPS',ServerURL=cfg['doh_url'])
    elif cfg['dot_host']:dns.update(DNSProtocol='TLS',ServerName=cfg['dot_host'])
    else:raise ValueError('Configure DoH or DoT before downloading an Apple DNS profile.')
    return plistlib.dumps(dict(PayloadContent=[dict(PayloadType='com.apple.dnsSettings.managed',PayloadVersion=1,
        PayloadIdentifier='com.beeny.dns.settings',PayloadUUID=str(uuid.uuid4()),PayloadDisplayName=label,DNSSettings=dns)],
        PayloadType='Configuration',PayloadVersion=1,PayloadIdentifier='com.beeny.dns',PayloadUUID=str(uuid.uuid4()),PayloadDisplayName=label))
def register(app,db,User,Node,UserNode,features,panel_path):
    base=panel_path.rstrip('/')
    def records():
        try:return json.loads(features.get_setting('dns_service_bindings','{}'))
        except ValueError:return {}
    def assigned(user):
        ids={r.node_id for r in UserNode.query.filter_by(user_id=user.id)}
        result=[]
        for key,cfg in records().items():
            if key.startswith(str(user.id)+':') and cfg.get('enabled'):
                node_id=int(key.split(':')[1]);node=db.session.get(Node,node_id)
                if node_id in ids and node:result.append(dict(cfg,node_name=node.name,node_id=node.id))
        return result
    @app.context_processor
    def context():return dict(account_dns_services=assigned)
    @app.get(base+'/settings/dns-services')
    @login_required
    def dns_settings():
        if current_user.role!='owner':abort(403)
        return render_template('dns_services.html',nodes=Node.query.order_by(Node.name).all(),users=User.query.order_by(User.username).all(),panel_path=panel_path)
    @app.route(base+'/api/settings/dns-services/<int:user_id>/<int:node_id>',methods=['GET','POST'])
    @login_required
    def dns_settings_action(user_id,node_id):
        if current_user.role!='owner':abort(403)
        if not db.session.get(User,user_id) or not db.session.get(Node,node_id):abort(404)
        if not UserNode.query.filter_by(user_id=user_id,node_id=node_id).first():return jsonify(success=False,message='Assign this node to the account first.'),400
        key=str(user_id)+':'+str(node_id);rows=records()
        if request.method=='GET':
            response=jsonify(success=True,settings=rows.get(key));response.headers['Cache-Control']='no-store';return response
        body=request.get_json(silent=True)
        try:
            if not isinstance(body,dict):raise ValueError('Invalid request.')
            if body.get('action')=='delete':rows.pop(key,None)
            elif body.get('action')=='probe':
                cfg=clean(body.get('data'));result=probe(cfg['address']);return jsonify(success=True,result=result)
            elif body.get('action')=='save':rows[key]=clean(body.get('data'))
            else:raise ValueError('Invalid DNS action.')
            features.set_setting('dns_service_bindings',json.dumps(rows));db.session.commit()
            return jsonify(success=True,message='DNS service saved. Upstream account permissions are managed separately.')
        except (ValueError,OSError):return jsonify(success=False,message='Check the public DNS settings, reachability and upstream IP allowlist.'),400
    @app.get(base+'/c/<token>/dns')
    def customer_dns(token):
        user=features.resolve_account(token)
        return render_template('customer_dns.html',user=user,token=token,portal_base=base+'/c/'+token,services=assigned(user),panel_path=panel_path)
    @app.get(base+'/c/<token>/dns/<int:node_id>.mobileconfig')
    def customer_dns_profile(token,node_id):
        user=features.resolve_account(token);cfg=next((row for row in assigned(user) if row['node_id']==node_id),None)
        if not cfg:abort(404)
        try:blob=profile(cfg,'Beeny · '+PROVIDERS[cfg['provider']])
        except ValueError:abort(400)
        return Response(blob,mimetype='application/x-apple-aspen-config',headers={'Content-Disposition':'attachment; filename="Beeny-DNS.mobileconfig"','Cache-Control':'no-store'})
    return assigned
