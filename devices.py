"""Separate certificates make permanent per-device access control possible."""
import re,secrets
from datetime import datetime
from types import SimpleNamespace
from flask import abort,request,render_template,redirect,flash
from flask_login import login_required,current_user

def register(app,db,User,Node,UserNode,features,panel_path,is_primary):
    base=panel_path.rstrip('/')
    class RetiredUsername(db.Model):
        __tablename__='retired_vpn_usernames'
        username=db.Column(db.String(100),primary_key=True)
        retired_at=db.Column(db.DateTime,default=datetime.utcnow)
    class Device(db.Model):
        __tablename__='account_devices'
        id=db.Column(db.Integer,primary_key=True)
        user_id=db.Column(db.Integer,index=True,nullable=False)
        name=db.Column(db.String(80),nullable=False)
        common_name=db.Column(db.String(64),unique=True,nullable=False)
        blocked=db.Column(db.Boolean,default=False,nullable=False)
        pending=db.Column(db.Boolean,default=True,nullable=False)
        created_at=db.Column(db.DateTime,default=datetime.utcnow)
    def identities(user):return [(user.username,False)]+[(d.common_name,d.blocked) for d in Device.query.filter_by(user_id=user.id).all()]
    def owner(common_name):
        row=Device.query.filter_by(common_name=common_name).first()
        return db.session.get(User,row.user_id) if row else User.query.filter_by(username=common_name).first()
    def apply(user,device,active):
        from app import sync_primary_access
        from app import representative_credit
        from app import representative_actions
        active=active and not representative_credit.suspended(user) and not representative_actions.blocked(user)
        from cluster import set_user_state_on_node
        failures=[]
        for relation in UserNode.query.filter_by(user_id=user.id).all():
            node=db.session.get(Node,relation.node_id)
            if not node:continue
            if is_primary(node):
                try:sync_primary_access(SimpleNamespace(username=device.common_name,status='active' if active else 'disabled',customer_paused=False),True)
                except Exception:failures.append(node.name)
            else:
                ok,_=set_user_state_on_node(node,device.common_name,active)
                if not ok:failures.append(node.name)
        device.pending=bool(failures);user.pause_sync_pending=bool(failures) or user.pause_sync_pending
        db.session.commit();return failures
    def new_device(user,name):
        name=name.strip()
        if not name or len(name)>80 or Device.query.filter_by(user_id=user.id).count()>=20:abort(400,'Invalid name or device limit reached.')
        common=f'd_{user.id}_{secrets.token_hex(8)}'
        from privileged import call,enabled
        from app import subprocess
        from cluster import create_user_on_node
        try:
            if enabled():call('create_user',username=common)
            else:subprocess.run(['/opt/beeny-panel/scripts/create_vpn_user.sh',common],check=True,timeout=120)
        except Exception:abort(503,'Certificate creation failed. Check service logs.')
        device=Device(user_id=user.id,name=name,common_name=common,blocked=False,pending=True);db.session.add(device);db.session.commit()
        failures=[]
        for relation in UserNode.query.filter_by(user_id=user.id).all():
            node=db.session.get(Node,relation.node_id)
            if node and not is_primary(node):
                result=create_user_on_node(node,SimpleNamespace(username=common))
                if not str(result).startswith('Success:'):failures.append(node.name)
        from renewal import activation_error
        blocked=user.status!='active' or user.customer_paused or activation_error(user.expire_date,user.traffic_limit or 0,user.traffic_usage or 0, quota_mode=getattr(user,'quota_mode','metered'))
        from app import speed_policy
        speed_failures=speed_policy.sync(user)
        failures+=speed_failures
        failures+=apply(user,device,not blocked)
        device.pending=bool(failures);user.pause_sync_pending=user.pause_sync_pending or bool(failures);db.session.commit();return device,failures
    def handle(user,customer,token=None):
        url=base+'/c/'+token+'/devices' if customer else base+'/users/view/'+str(user.id)+'/devices'
        if request.method=='POST':
            features.verify_csrf()
            action=request.form.get('action')
            if action=='add':
                if not customer and current_user.role not in {'owner','seller'}:abort(403)
                _,failures=new_device(user,request.form.get('name',''))
                flash('دستگاه ثبت شد؛ تأیید بعضی نودها هنوز دریافت نشده است.' if failures else 'دستگاه ثبت شد؛ کانفیگ مخصوص آن را دانلود کنید.','warning' if failures else 'success')
            elif action in {'block','unblock'}:
                device=Device.query.filter_by(id=request.form.get('device_id',type=int),user_id=user.id).first_or_404()
                if customer and action=='unblock':abort(403,'فعال‌سازی مجدد دستگاه توسط مدیر انجام می‌شود.')
                device.blocked=action=='block';db.session.commit()
                from renewal import activation_error
                active=not device.blocked and user.status=='active' and not user.customer_paused and not activation_error(user.expire_date,user.traffic_limit or 0,user.traffic_usage or 0, quota_mode=getattr(user,'quota_mode','metered'))
                from app import speed_policy
                speed_failures=speed_policy.sync(user)
                failures=speed_failures+apply(user,device,active)
                flash('وضعیت ذخیره شد؛ تأیید نودها در حال پیگیری است.' if failures else 'وضعیت دستگاه تغییر کرد.','warning' if failures else 'success')
            else:abort(400)
            return redirect(url)
        return render_template('devices.html',rows=Device.query.filter_by(user_id=user.id).order_by(Device.id).all(),user=user,customer=customer,token=token,panel_path=panel_path,device_base=url)
    @app.route(base+'/c/<token>/devices',methods=['GET','POST'])
    def customer_devices(token):return handle(features.resolve_account(token),True,token)
    @app.get(base+'/c/<token>/devices/<int:device_id>/download')
    def customer_device_download(token,device_id):
        user=features.resolve_account(token);row=Device.query.filter_by(id=device_id,user_id=user.id).first_or_404()
        if row.blocked or row.pending:abort(409,'کانفیگ دستگاه مسدود است یا هنوز نودها تأیید نکرده‌اند.')
        from app import build_config
        return build_config(user,request.args.get('node_id',type=int),certificate_username=row.common_name)
    @app.route(base+'/users/view/<int:user_id>/devices',methods=['GET','POST'])
    @login_required
    def admin_devices(user_id):return handle(User.query.get_or_404(user_id),False)
    return SimpleNamespace(RetiredUsername=RetiredUsername,Device=Device,identities=identities,owner=owner,apply=apply)
