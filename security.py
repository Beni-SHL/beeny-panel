"""Central CSRF, login throttling, roles, TOTP and durable administrative audit."""
import base64, hashlib, hmac, json, secrets, struct, time
from datetime import datetime, timedelta
from types import SimpleNamespace
from flask import abort, request, session, g, render_template, redirect, flash, has_request_context
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash
from cryptography.fernet import Fernet
from sqlalchemy import event, inspect,update

ROLES = {'owner','support','finance','seller','viewer'}
SECRET_WORDS = ('password','secret','token','key','csrf','receipt','avatar')

def totp(secret, counter):
    digest=hmac.new(base64.b32decode(secret),struct.pack('>Q',counter),hashlib.sha1).digest()
    offset=digest[-1]&15
    return f'{(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%1000000:06d}'

def register(app,db,Admin,features,panel_path):
    class AdminNodeGrant(db.Model):
        __tablename__='admin_node_grants'
        admin_id=db.Column(db.Integer,primary_key=True)
        node_id=db.Column(db.Integer,primary_key=True)
    base=panel_path.rstrip('/')
    dummy_hash=generate_password_hash(secrets.token_urlsafe(32))
    def normal_code(value):return str(value or '').strip().lower().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789'))
    cipher=Fernet(base64.urlsafe_b64encode(hashlib.sha256((app.secret_key+'admin-totp').encode()).digest()))
    class Attempt(db.Model):
        __tablename__='admin_login_attempts'
        id=db.Column(db.String(64),primary_key=True)
        failures=db.Column(db.Integer,default=0,nullable=False)
        blocked_until=db.Column(db.DateTime)
        updated_at=db.Column(db.DateTime,default=datetime.utcnow,index=True)
    class Audit(db.Model):
        __tablename__='admin_audit'
        id=db.Column(db.Integer,primary_key=True)
        admin_id=db.Column(db.Integer,index=True)
        username=db.Column(db.String(100))
        action=db.Column(db.String(100))
        details=db.Column(db.Text)
        created_at=db.Column(db.DateTime,default=datetime.utcnow,index=True)
        address=db.Column(db.String(64))
    def address():
        import ipaddress
        value=request.remote_addr or ''
        if value in {'127.0.0.1','::1'}:
            try:value=str(ipaddress.ip_address(request.headers.get('X-Real-IP',value)))
            except ValueError:pass
        return value
    def csrf():
        session.setdefault('_customer_csrf',secrets.token_urlsafe(32))
        return session['_customer_csrf']
    def check_csrf():
        expected=session.get('_customer_csrf','')
        supplied=request.headers.get('X-CSRF-Token') or request.form.get('csrf','')
        if not expected or not hmac.compare_digest(expected,supplied):abort(400,'Expired or invalid request. Refresh the page and try again.')
    def role_allowed(endpoint):
        role=getattr(current_user,'role','owner') or 'owner'
        if role=='owner':return True
        if endpoint in {'static','admin_language_save'}:return True
        if endpoint=='download_config':return role in {'seller','support'}
        if endpoint=='sales_page':return request.method=='GET' and role in {'seller','finance'} and not g.get('admin_node_ids') is not None
        if role=='finance' and endpoint in {'sales_page','financial_adjustment','renewal_receipt','renewal_detail'} and request.method=='GET':return True
        if role=='seller' and endpoint in {'admin_notifications','renewal_inbox','renewal_detail','renewal_receipt','system_settings','general_settings','settings','traffic_page'}:return False
        if request.method in {'GET','HEAD','OPTIONS'}:
            if endpoint in {'backup_page','backup_list','download_backup','renewal_receipt','renewal_detail','reseller_admin','customer_settings','notification_settings','panel_admins','audit_page','update_page','nodes_page','health_page'}:return False
            return True
        if endpoint in {'logout','revoke_panel_session','logout_all_panel_sessions','admin_notifications_read','admin_notifications_clear','admin_notification_delete','security_page'}:return True
        if role=='viewer':return False
        if role=='support':return endpoint in {'ticket_reply','ticket_update','ticket_delete','admin_devices'}
        if role=='finance':return endpoint in {'review_renewal','retry_notification','delete_renewal','financial_adjustment','create_invoice'}
        if role=='seller':return endpoint in {'add_user','edit_user','rotate_account_link','set_customer_access','share_account_telegram','bulk_users','ticket_reply','admin_devices'}
        return False
    @event.listens_for(db.session.session_factory.class_, 'do_orm_execute')
    def scope_sellers(state):
        uid=g.get('seller_id') if has_request_context() else None
        allowed=g.get('admin_node_ids') if has_request_context() else None
        if allowed is not None and state.is_select:
            from sqlalchemy.orm import with_loader_criteria
            from app import User,Node,UserNode
            permitted=tuple(allowed)
            # Shared accounts with an out-of-scope node stay hidden, avoiding partial edits.
            visible=db.select(UserNode.user_id).where(UserNode.node_id.in_(permitted))
            outside=db.select(UserNode.user_id).where(UserNode.node_id.notin_(permitted))
            criterion=User.id.in_(visible)&User.id.notin_(outside)
            state.statement=state.statement.options(with_loader_criteria(Node,Node.id.in_(permitted),include_aliases=True),with_loader_criteria(User,criterion,include_aliases=True))
            from app import support
            state.statement=state.statement.options(with_loader_criteria(support.Ticket,support.Ticket.user_id.in_(visible)&support.Ticket.user_id.notin_(outside),include_aliases=True))
        if uid is not None and state.is_select:
            from sqlalchemy.orm import with_loader_criteria
            from app import User
            state.statement=state.statement.options(with_loader_criteria(User,lambda cls: cls.owner_id==uid,include_aliases=True))
    @app.before_request
    def guard():
        g.audit_changes=[]
        if request.endpoint=='vpn_admission':return
        if current_user.is_authenticated and '/c/' not in request.path:
            g.audit_actor=(current_user.id,current_user.username)
            if current_user.role!='owner' and current_user.node_scope:
                g.admin_node_ids=[row.node_id for row in AdminNodeGrant.query.filter_by(admin_id=current_user.id)]
                from app import User,support
                args=request.view_args or {}
                if 'user_id' in args and not User.query.filter_by(id=args['user_id']).first():abort(404)
                if 'username' in args and not User.query.filter_by(username=args['username']).first():abort(404)
                if 'ticket_id' in args and not support.Ticket.query.filter_by(id=args['ticket_id']).first():abort(404)
            if current_user.role=='seller':
                g.seller_id=current_user.id
                from app import User
                args=request.view_args or {}
                if 'user_id' in args and not User.query.filter_by(id=args['user_id'],owner_id=current_user.id).first():abort(404)
                if 'username' in args and not User.query.filter_by(username=args['username'],owner_id=current_user.id).first():abort(404)
            if not role_allowed(request.endpoint):abort(403,'Your role does not permit this operation.')
        if request.method in {'POST','PUT','PATCH','DELETE'} and '/c/' not in request.path and (current_user.is_authenticated or request.endpoint=='login'):check_csrf()
    def authorize(admin,password,code):
        code=normal_code(code)
        key=hashlib.sha256((address()+'|'+str(request.form.get('username',''))[:64].lower()).encode()).hexdigest()
        row=db.session.get(Attempt,key)
        ipkey=hashlib.sha256(('ip|'+address()).encode()).hexdigest()
        iprow=db.session.get(Attempt,ipkey)
        now=datetime.utcnow()
        if any(item and item.blocked_until and item.blocked_until>now for item in (row,iprow)):return False,'Too many attempts. Try again later.'
        password_valid=isinstance(password,str) and len(password)<=256 and check_password_hash(admin.password if admin else dummy_hash,password)
        valid=bool(admin and password_valid)
        if valid and admin.totp_secret:
            valid=False
            if isinstance(code,str) and code.isdigit() and len(code)==6:
                secret=cipher.decrypt(admin.totp_secret.encode()).decode()
                for counter in range(int(time.time()/30)-1,int(time.time()/30)+2):
                    if counter>(admin.totp_counter if admin.totp_counter is not None else -1) and hmac.compare_digest(totp(secret,counter),code):
                        previous=admin.totp_counter if admin.totp_counter is not None else -1
                        changed=db.session.execute(update(Admin).where(Admin.id==admin.id,Admin.totp_counter==previous).values(totp_counter=counter)).rowcount
                        valid=changed==1;break
            if not valid and code:
                hashes=json.loads(admin.recovery_codes or '[]')
                for index,value in enumerate(hashes):
                    if check_password_hash(value,code):
                        before=admin.recovery_codes;hashes.pop(index)
                        changed=db.session.execute(update(Admin).where(Admin.id==admin.id,Admin.recovery_codes==before).values(recovery_codes=json.dumps(hashes))).rowcount
                        valid=changed==1;break
        if valid:
            if row:db.session.delete(row)
            db.session.commit();return True,''
        if not row:row=Attempt(id=key,failures=0);db.session.add(row)
        row.failures+=1;row.updated_at=now
        if not iprow:iprow=Attempt(id=ipkey,failures=0);db.session.add(iprow)
        iprow.failures+=1;iprow.updated_at=now
        if iprow.failures>=20:iprow.blocked_until=now+timedelta(minutes=15)
        if row.failures>=5:row.blocked_until=now+timedelta(minutes=min(60,2**min(row.failures-5,5)))
        db.session.commit();return False,'Invalid credentials or verification code.'
    @event.listens_for(db.session.session_factory.class_,'before_flush')
    def capture_changes(orm,context,instances):
        if not has_request_context() or not getattr(g,'audit_actor',None):return
        for obj in list(orm.new)+list(orm.dirty)+list(orm.deleted):
            if obj.__class__.__name__ not in {'User','Admin','Node','RenewalRequest'}:continue
            changes={'operation':'create' if obj in orm.new else 'delete' if obj in orm.deleted else 'update'}
            for attr in inspect(obj).attrs:
                if any(word in attr.key.lower() for word in SECRET_WORDS):continue
                if attr.history.has_changes():changes[attr.key]=dict(before=[str(v) for v in attr.history.deleted],after=[str(v) for v in attr.history.added])
            if changes:g.audit_changes.append(dict(model=obj.__class__.__name__,id=getattr(obj,'id',None),changes=changes))
    @app.after_request
    def record(response):
        if request.method not in {'POST','PUT','PATCH','DELETE'} or not getattr(g,'audit_actor',None):return response
        uid,name=g.audit_actor
        details=dict(result=response.status_code,parameters={k:v for k,v in (request.view_args or {}).items() if k!='token'},changes=getattr(g,'audit_changes',[]))
        db.session.add(Audit(admin_id=uid,username=name,action=request.endpoint or 'unknown',address=address(),details=json.dumps(details,ensure_ascii=False)))
        try:db.session.commit()
        except Exception:db.session.rollback();app.logger.error('Administrative audit write failed.')
        return response
    @app.context_processor
    def context():return dict(admin_csrf=csrf,admin_role=lambda:getattr(current_user,'role','owner'))
    @app.route(base+'/settings/security',methods=['GET','POST'])
    @login_required
    def security_page():
        codes=None
        if request.method=='POST':
            if not check_password_hash(current_user.password,request.form.get('current_password','')):abort(400,'Current password is incorrect.')
            if request.form.get('action')=='disable':
                if not current_user.totp_secret:abort(400)
                secret=cipher.decrypt(current_user.totp_secret.encode()).decode()
                if not any(hmac.compare_digest(totp(secret,c),normal_code(request.form.get('code',''))) for c in range(int(time.time()/30)-1,int(time.time()/30)+2)):abort(400,'Verification code is incorrect.')
                current_user.totp_secret=None;current_user.recovery_codes='[]';current_user.totp_counter=-1
            else:
                secret=session.get('totp_setup')
                if not secret:abort(400)
                counter=int(time.time()/30)
                matched=next((c for c in range(counter-1,counter+2) if hmac.compare_digest(totp(secret,c),normal_code(request.form.get('code','')))),None)
                if matched is None:abort(400,'Verification code is incorrect.')
                current_user.totp_secret=cipher.encrypt(secret.encode()).decode();current_user.totp_counter=matched
                codes=[secrets.token_hex(6) for _ in range(8)]
                current_user.recovery_codes=json.dumps([generate_password_hash(code) for code in codes]);session.pop('totp_setup',None)
            db.session.commit()
            from app import panel_sessions
            panel_sessions.revoke_all(current_user.id,keep=session.get('panel_session_token'))
            flash('Security settings saved. Other sessions were revoked.','success')
        if not current_user.totp_secret:session.setdefault('totp_setup',base64.b32encode(secrets.token_bytes(20)).decode())
        return render_template('security.html',secret=session.get('totp_setup') if not current_user.totp_secret else None,codes=codes,enabled=bool(current_user.totp_secret),panel_path=panel_path)
    @app.get(base+'/settings/audit')
    @login_required
    def audit_page():
        page=max(1,request.args.get('page',1,type=int))
        rows=Audit.query.order_by(Audit.id.desc()).paginate(page=page,per_page=50,error_out=False)
        return render_template('audit.html',rows=rows,panel_path=panel_path)
    @app.post(base+'/settings/audit/clear')
    @login_required
    def clear_audit():
        if current_user.role!='owner':abort(403)
        Audit.query.delete();db.session.commit()
        flash('Audit history cleared. This operation is recorded.','success')
        return redirect(base+'/settings/audit')
    @app.route(base+'/settings/admins',methods=['GET','POST'])
    @login_required
    def panel_admins():
        if request.method=='POST':
            if request.form.get('id'):
                admin=db.session.get(Admin,request.form.get('id',type=int)) or abort(404)
                role=request.form.get('role')
                if role not in ROLES:abort(400)
                if admin.role=='owner' and role!='owner':
                    count=db.select(db.func.count(Admin.id)).where(Admin.role=='owner').scalar_subquery()
                    changed=db.session.execute(update(Admin).where(Admin.id==admin.id,count>1).values(role=role).execution_options(synchronize_session=False)).rowcount
                    if changed!=1:abort(400,'The last owner cannot be removed.')
                    db.session.refresh(admin)
                else:admin.role=role
            else:
                username=request.form.get('username','').strip();password=request.form.get('password','');role=request.form.get('role')
                import re
                if not re.fullmatch(r'[A-Za-z0-9_.-]{3,50}',username) or not 12<=len(password)<=256 or role not in ROLES:abort(400)
                if Admin.query.filter_by(username=username).first():abort(409,'Username already exists.')
                admin=Admin(username=username,password=generate_password_hash(password),role=role);db.session.add(admin)
            from app import Node
            scoped=request.form.get('node_scope')=='1'
            if scoped and admin.role not in {'seller','support','viewer'}:abort(400,'Node scope is available for seller, support and viewer; owner/finance are global roles.')
            try:ids={int(value) for value in request.form.getlist('nodes')}
            except ValueError:abort(400,'Invalid node selection.')
            if scoped and (not ids or not ids.issubset({n.id for n in Node.query.all()})):abort(400,'Select valid nodes.')
            admin.node_scope=scoped;db.session.flush()
            AdminNodeGrant.query.filter_by(admin_id=admin.id).delete()
            if scoped:
                for nid in ids:db.session.add(AdminNodeGrant(admin_id=admin.id,node_id=nid))
            db.session.commit()
            from app import panel_sessions
            panel_sessions.revoke_all(admin.id)
            return redirect(base+('/settings/general?tab=administrators#administrators' if request.form.get('return_to')=='general' else '/settings/admins'))
        from app import Node
        return render_template('admins.html',nodes=Node.query.order_by(Node.name).all(),grants={(x.admin_id,x.node_id) for x in AdminNodeGrant.query.all()},admins=Admin.query.order_by(Admin.id).all(),roles=sorted(ROLES),panel_path=panel_path)
    return SimpleNamespace(authorize=authorize,csrf=csrf,Audit=Audit,Attempt=Attempt,check_csrf=check_csrf,AdminNodeGrant=AdminNodeGrant)
