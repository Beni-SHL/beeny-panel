"""Optional shared admission leases: a node cannot grant more account sessions than the panel permits."""
import hashlib,hmac,json,re,time
from datetime import datetime,timedelta
from types import SimpleNamespace
from flask import request,jsonify
from sqlalchemy import update

def node_token(secret,nid):return hmac.new(str(secret).encode(),('beeny-admission-v1:'+str(nid)).encode(),hashlib.sha256).hexdigest()
def lease_key(nid,name,address,since):return hashlib.sha256(f'{nid}|{name}|{address}|{since}'.encode()).hexdigest()

def register(app,db,User,Node,UserNode,features,devices,representatives,actions,panel_path):
    class Lease(db.Model):
        __tablename__='vpn_admission_leases'
        key=db.Column(db.String(64),primary_key=True)
        user_id=db.Column(db.Integer,index=True,nullable=False)
        node_id=db.Column(db.Integer,index=True,nullable=False)
        name=db.Column(db.String(64),nullable=False)
        created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)
        active=db.Column(db.Boolean,default=True,nullable=False)
        closed_at=db.Column(db.DateTime)
    class Snapshot(db.Model):
        __tablename__='vpn_admission_snapshots'
        node_id=db.Column(db.Integer,primary_key=True)
        checked_at=db.Column(db.DateTime,nullable=False)
    def sync(node_id,clients):
        now=datetime.utcnow();row=db.session.get(Snapshot,node_id)
        if row:row.checked_at=now
        else:db.session.add(Snapshot(node_id=node_id,checked_at=now))
        keys=set()
        for name,key,received,sent,address in clients:
            parts=key.split('|')
            if len(parts)<3 or not parts[2].isdigit():continue
            user=devices.owner(name)
            if not user:continue
            ident=lease_key(node_id,name,address,parts[2]);keys.add(ident)
            from app import connection_guard
            connection_guard.remember(ident,user.id,address)
            row=db.session.get(Lease,ident)
            if row:
                if row.closed_at is None:row.active=True
            else:db.session.add(Lease(key=ident,user_id=user.id,node_id=node_id,name=name,active=True))
        for row in Lease.query.filter(Lease.node_id==node_id,Lease.active.is_(True),Lease.created_at<now-timedelta(seconds=30)):
            if row.key not in keys:row.active=False;row.closed_at=now
    @app.post(panel_path.rstrip('/')+'/api/vpn/admission')
    def vpn_admission():
        request.max_content_length=8192
        data=request.get_json(silent=True) or {};nid=data.get('node_id');name=data.get('name','');address=data.get('address','');since=data.get('since','');action=data.get('action')
        if type(nid) is not int or not isinstance(name,str) or not (1<=len(name)<=128 and name.isprintable() and not any(c in name for c in '/\\|')) or not isinstance(address,str) or len(address)>150 or not re.fullmatch(r'[0-9]{1,12}',str(since)) or action not in {'connect','disconnect'}:return jsonify(allowed=False),400
        supplied=request.headers.get('Authorization','').removeprefix('Bearer ')
        if not hmac.compare_digest(supplied,node_token(app.secret_key,nid)) or not db.session.get(Node,nid):return jsonify(allowed=False),403
        ident=lease_key(nid,name,address,str(since));user=devices.owner(name)
        if not user:return jsonify(allowed=False),403
        # Same-account writes serialize concurrent admissions, also across separate panel workers.
        db.session.execute(update(User).where(User.id==user.id).values(traffic_used=User.traffic_used))
        db.session.refresh(user)
        row=db.session.get(Lease,ident)
        if action=='disconnect':
            if row:row.active=False;row.closed_at=datetime.utcnow()
            db.session.commit();return jsonify(allowed=True)
        from renewal import activation_error
        selected=[x.node_id for x in UserNode.query.filter_by(user_id=user.id)]
        device=devices.Device.query.filter_by(common_name=name,user_id=user.id).first()
        if nid not in selected or user.status!='active' or user.customer_paused or (device and device.blocked) or representatives.suspended(user) or actions.blocked(user) or activation_error(user.expire_date,user.traffic_limit,user.traffic_usage or 0,quota_mode=user.quota_mode):db.session.rollback();return jsonify(allowed=False),403
        # All assigned nodes must have a fresh snapshot: never assume missing sessions are zero.
        now=datetime.utcnow()
        for selected_id in selected:
            snapshot=db.session.get(Snapshot,selected_id)
            if not snapshot or snapshot.checked_at<now-timedelta(seconds=90):
                app.logger.warning('Admission denied account_id=%s node_id=%s reason=stale_snapshot selected_node=%s',user.id,nid,selected_id)
                db.session.rollback();return jsonify(allowed=False,reason='Status synchronization pending'),503
        from app import connection_guard
        if connection_guard.blocked(user.id,address):db.session.rollback();return jsonify(allowed=False,reason='Peer temporarily blocked for repeated excess connections',retry_after=1800),403
        if row and row.active:db.session.commit();return jsonify(allowed=True)
        if row and row.closed_at is not None:db.session.rollback();return jsonify(allowed=False,reason='Closed connection identity; reconnect with a new session'),409
        if Lease.query.filter_by(user_id=user.id,active=True).count()>=max(1,user.max_devices):
            # Existing peers are protected from NAT collateral; lookup lease IDs via recent attempts is not needed.
            active_keys=[entry.key for entry in Lease.query.filter_by(user_id=user.id,active=True)]
            protected=[entry.address for entry in connection_guard.Peer.query.filter(connection_guard.Peer.key.in_(active_keys))]
            banned=connection_guard.record(user.id,address,ident,protected)
            db.session.commit();return jsonify(allowed=False,reason='Peer temporarily blocked' if banned else 'Device limit reached',retry_after=1800 if banned else 0),403
        if row:row.active=True;row.created_at=now
        else:db.session.add(Lease(key=ident,user_id=user.id,node_id=nid,name=name,active=True))
        connection_guard.remember(ident,user.id,address)
        db.session.commit();return jsonify(allowed=True)
    return SimpleNamespace(Lease=Lease,Snapshot=Snapshot,sync=sync)
