"""Per-account, per-peer abuse guard. Never bans a shared NAT globally."""
import hashlib,ipaddress
from datetime import datetime,timedelta
from types import SimpleNamespace

def peer_ip(address):
    value=str(address)
    if value.startswith('['):value=value[1:value.index(']')]
    elif value.count(':')==1:value=value.rsplit(':',1)[0]
    return str(ipaddress.ip_address(value))

def register(db):
    class Attempt(db.Model):
        __tablename__='vpn_excess_attempts'
        key=db.Column(db.String(64),primary_key=True)
        user_id=db.Column(db.Integer,nullable=False,index=True)
        address=db.Column(db.String(45),nullable=False,index=True)
        created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
    class Peer(db.Model):
        __tablename__='vpn_admission_peer_addresses'
        key=db.Column(db.String(64),primary_key=True)
        user_id=db.Column(db.Integer,nullable=False,index=True)
        address=db.Column(db.String(45),nullable=False)
    def remember(key,uid,address):
        if not db.session.get(Peer,key):db.session.add(Peer(key=key,user_id=uid,address=peer_ip(address)))
    class Ban(db.Model):
        __tablename__='vpn_peer_bans'
        user_id=db.Column(db.Integer,primary_key=True)
        address=db.Column(db.String(45),primary_key=True)
        until=db.Column(db.DateTime,nullable=False,index=True)
    def blocked(uid,address,now=None):
        try:ip=peer_ip(address)
        except ValueError:return False
        row=db.session.get(Ban,(uid,ip))
        return bool(row and row.until>(now or datetime.utcnow()))
    def active(uid):return Ban.query.filter(Ban.user_id==uid,Ban.until>datetime.utcnow()).first() is not None
    def record(uid,address,identity,protected=(),now=None):
        now=now or datetime.utcnow()
        try:ip=peer_ip(address)
        except ValueError:return False
        primary=set()
        for value in protected:
            try:primary.add(peer_ip(value))
            except ValueError:pass
        if ip in primary:return False
        if blocked(uid,address,now):return True
        # Re-observing one connection or retrying one HTTP request is not a new attempt.
        key=hashlib.sha256(f'{uid}|{ip}|{identity}'.encode()).hexdigest()
        if db.session.get(Attempt,key):return False
        Attempt.query.filter(Attempt.created_at<now-timedelta(hours=1)).delete(synchronize_session=False)
        db.session.add(Attempt(key=key,user_id=uid,address=ip,created_at=now));db.session.flush()
        count=Attempt.query.filter(Attempt.user_id==uid,Attempt.address==ip,Attempt.created_at>=now-timedelta(minutes=10)).count()
        if count<10:return False
        row=db.session.get(Ban,(uid,ip))
        if row:row.until=now+timedelta(minutes=30)
        else:db.session.add(Ban(user_id=uid,address=ip,until=now+timedelta(minutes=30)))
        import logging
        logging.warning('Beeny peer restriction created account_id=%s address=%s duration_seconds=1800 reason=10_distinct_excess_attempts',uid,ip)
        return True
    return SimpleNamespace(Attempt=Attempt,Ban=Ban,Peer=Peer,remember=remember,blocked=blocked,record=record,active=active)


def register_routes(app,db,guard,User,panel_path):
    from flask import jsonify,request,abort
    from flask_login import login_required,current_user
    @app.route(panel_path.rstrip('/')+'/api/vpn/peer-bans',methods=['GET','POST'])
    @login_required
    def peer_bans():
        if current_user.role!='owner':abort(403)
        if request.method=='POST':
            data=request.get_json(silent=True) or {}
            if type(data.get('user_id')) is not int:abort(400)
            try:address=peer_ip(data.get('address',''))
            except ValueError:abort(400)
            row=db.session.get(guard.Ban,(data['user_id'],address))
            if row:db.session.delete(row)
            # Clearing the matching recent attempts prevents an immediate re-ban.
            guard.Attempt.query.filter_by(user_id=data['user_id'],address=address).delete(synchronize_session=False)
            db.session.commit();return jsonify(success=True,message='Peer restriction cleared. Account status and traffic are unchanged.')
        rows=db.session.query(guard.Ban,User.username).join(User,User.id==guard.Ban.user_id).filter(guard.Ban.until>datetime.utcnow()).order_by(guard.Ban.until).limit(200).all()
        return jsonify(success=True,rows=[dict(user_id=b.user_id,username=name,address=b.address,until=b.until.isoformat()+'Z') for b,name in rows])
