"""Host interface traffic independent of account deletion, quota resets or VPN sessions."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import psutil

def metrics():
    from host_metrics import snapshot
    try:return snapshot()
    except (OSError,ValueError):return None

def register(db):
    class Sample(db.Model):
        __tablename__='host_traffic_sample'
        node_id=db.Column(db.Integer,primary_key=True)
        interface=db.Column(db.String(64),nullable=False)
        boot_id=db.Column(db.String(64),nullable=False)
        received=db.Column(db.BigInteger,nullable=False)
        sent=db.Column(db.BigInteger,nullable=False)
        checked_at=db.Column(db.DateTime,default=datetime.utcnow)
    class Daily(db.Model):
        __tablename__='host_traffic_daily'
        id=db.Column(db.Integer,primary_key=True)
        node_id=db.Column(db.Integer,index=True,nullable=False)
        node_name=db.Column(db.String(100),nullable=False)
        day=db.Column(db.String(10),index=True,nullable=False)
        received=db.Column(db.BigInteger,default=0,nullable=False)
        sent=db.Column(db.BigInteger,default=0,nullable=False)
        __table_args__=(db.UniqueConstraint('node_id','day'),)
    def record(node_id,node_name,payload):
        if not isinstance(payload,dict):return False
        try:
            received=int(payload['received']);sent=int(payload['sent']);interface=str(payload['interface']);boot=str(payload['boot_id'])
            if not 0<=received<2**63 or not 0<=sent<2**63 or not 1<=len(interface)<=64 or not 1<=len(boot)<=64:return False
        except (KeyError,ValueError,TypeError):return False
        sample=db.session.get(Sample,node_id)
        if not sample:
            db.session.add(Sample(node_id=node_id,interface=interface,boot_id=boot,received=received,sent=sent));return True
        if interface!=sample.interface:delta_in=delta_out=0
        elif boot!=sample.boot_id:delta_in,delta_out=received,sent
        else:delta_in=received-sample.received if received>=sample.received else received;delta_out=sent-sample.sent if sent>=sample.sent else sent
        sample.interface=interface;sample.boot_id=boot;sample.received=received;sample.sent=sent;sample.checked_at=datetime.utcnow()
        if delta_in or delta_out:
            day=datetime.utcnow().date().isoformat();row=Daily.query.filter_by(node_id=node_id,day=day).first()
            if not row:row=Daily(node_id=node_id,node_name=node_name,day=day,received=0,sent=0);db.session.add(row)
            row.received+=delta_in;row.sent+=delta_out
        return True
    return SimpleNamespace(Sample=Sample,Daily=Daily,record=record)
