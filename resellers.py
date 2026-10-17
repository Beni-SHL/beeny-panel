"""Customer representatives: scoped nodes, atomic credit reservations and durable provisioning.
A failed provision remains paid and disabled until retry or an owner-approved refund.
No server configuration, private API keys or administrator login is exposed.
"""
import hashlib,json,math,re,secrets,subprocess
from datetime import datetime,timedelta
from types import SimpleNamespace
from flask import abort,flash,redirect,render_template,request
from flask_login import current_user,login_required
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash
from renewal import extend_expiry

def register(app,db,User,Node,UserNode,AccountLink,features,experience,commerce,panel_path,is_primary_node):
    base=panel_path.rstrip('/')
    class Profile(db.Model):
        __tablename__='reseller_profiles'
        user_id=db.Column(db.Integer,primary_key=True)
        enabled=db.Column(db.Boolean,nullable=False,default=False)
        base=db.Column(db.BigInteger,nullable=False,default=0)
        per_gb=db.Column(db.BigInteger,nullable=False,default=0)
        per_day=db.Column(db.BigInteger,nullable=False,default=0)
        per_device=db.Column(db.BigInteger,nullable=False,default=0)
    class Grant(db.Model):
        __tablename__='reseller_node_grants'
        user_id=db.Column(db.Integer,primary_key=True)
        node_id=db.Column(db.Integer,primary_key=True)
    class Order(db.Model):
        __tablename__='reseller_orders'
        id=db.Column(db.Integer,primary_key=True)
        reference=db.Column(db.String(32),unique=True,nullable=False)
        reseller_id=db.Column(db.Integer,index=True,nullable=False)
        user_id=db.Column(db.Integer,index=True,nullable=False)
        node_id=db.Column(db.Integer,nullable=False)
        username=db.Column(db.String(64),nullable=False)
        amount=db.Column(db.BigInteger,nullable=False)
        snapshot=db.Column(db.Text,nullable=False)
        state=db.Column(db.String(20),nullable=False,default='pending')
        error=db.Column(db.String(250),default='')
        created_at=db.Column(db.DateTime,default=datetime.utcnow)
        updated_at=db.Column(db.DateTime,default=datetime.utcnow)
        # The link is password protected; no customer password is stored here.
        portal_token=db.Column(db.String(43),nullable=False)
    class Renewal(db.Model):
        __tablename__='reseller_renewals'
        id=db.Column(db.Integer,primary_key=True)
        reference=db.Column(db.String(32),unique=True,nullable=False)
        reseller_id=db.Column(db.Integer,index=True,nullable=False)
        user_id=db.Column(db.Integer,index=True,nullable=False)
        username=db.Column(db.String(64),nullable=False)
        amount=db.Column(db.BigInteger,nullable=False)
        snapshot=db.Column(db.Text,nullable=False)
        created_at=db.Column(db.DateTime,default=datetime.utcnow)
    def allowed(user):
        from app import representative_credit
        a=representative_credit.Account.query.get(user.id)
        if a and (a.locked or a.suspended):abort(403,'Representative is locked or suspended')
        profile=db.session.get(Profile,user.id)
        if not profile or not profile.enabled or user.status!='active':abort(403,'دسترسی نمایندگی فعال نیست؛ با مدیر تماس بگیرید.')
        return profile
    def nodes_for(uid):
        return Node.query.join(Grant,Grant.node_id==Node.id).filter(Grant.user_id==uid).order_by(Node.name).all()
    def policy(p):return {k:int(getattr(p,k)) for k in ('base','per_gb','per_day','per_device')}
    def quote(p,days,quota,devices):
        if not 1<=days<=3650 or not 1<=quota<=100000 or not 1<=devices<=20:abort(400,'حجم، زمان یا تعداد دستگاه معتبر نیست.')
        price=p.base+p.per_day*days+p.per_gb*quota+p.per_device*(devices-1)
        if not 1<=price<=1000000000:abort(400,'تعرفه معتبر نیست؛ با مدیر تماس بگیرید.')
        return int(price)
    def selected_plan(profile):
        plan_id=request.form.get('plan_id','custom')
        if plan_id=='custom':
            values={key:request.form.get(key,type=int) for key in ('days','quota','devices')}
            if any(value is None for value in values.values()):abort(400)
            return dict(values,id='custom',title='سرویس دلخواه',price=quote(profile,**values),rates=policy(profile))
        plan=next((dict(p) for p in features.settings()['plans'] if p['id']==plan_id),None)
        if not plan:abort(400,'پلن انتخاب‌شده موجود نیست.')
        limits={'days':3650,'quota':100000,'devices':20,'price':1000000000}
        if any(type(plan.get(k)) is not int or not 1<=plan[k]<=maximum for k,maximum in limits.items()):
            abort(400,'مشخصات پلن معتبر نیست؛ با مدیر تماس بگیرید.')
        return plan
    def renew_child(representative,profile,token):
        reference=request.form.get('reference','')
        if not re.fullmatch(r'[a-f0-9]{32}',reference):abort(400)
        child=User.query.filter_by(id=request.form.get('user_id',type=int),reseller_id=representative.id).first_or_404()
        old=Renewal.query.filter_by(reference=reference).first()
        if old:
            if old.reseller_id!=representative.id or old.user_id!=child.id:abort(409)
            return redirect(base+'/c/'+token+'/reseller')
        # A representative cannot reverse a manager's disabled status.
        if child.status!='active':abort(409,'حساب توسط مدیر محدود شده یا ساخت آن کامل نشده است؛ با مدیر تماس بگیرید.')
        assigned={row.node_id for row in UserNode.query.filter_by(user_id=child.id).all()}
        granted={row.node_id for row in Grant.query.filter_by(user_id=representative.id).all()}
        if not assigned or assigned-granted:abort(403,'نود حساب در مجوز فعلی نمایندگی نیست.')
        if not Order.query.filter_by(user_id=child.id,reseller_id=representative.id,state='completed').first():abort(409)
        plan=selected_plan(profile);price=plan['price']
        try:new_expiry=extend_expiry(child.expire_date,plan['days'],today=datetime.utcnow().date())
        except ValueError:abort(409,'تاریخ ذخیره‌شده معتبر نیست؛ مدیر باید آن را اصلاح کند.')
        changed=db.session.execute(update(commerce.Wallet).where(commerce.Wallet.user_id==representative.id,commerce.Wallet.balance>=price).values(balance=commerce.Wallet.balance-price)).rowcount
        if changed!=1:db.session.rollback();abort(409,'موجودی کافی نیست؛ ابتدا کیف پول را شارژ کنید.')
        # Compare-and-set prevents an overlapping admin edit from being overwritten.
        changed=db.session.execute(update(User).where(User.id==child.id,User.reseller_id==representative.id,
            User.status=='active',User.expire_date==child.expire_date,User.traffic_limit==child.traffic_limit,
            User.traffic_usage==child.traffic_usage,User.max_devices==child.max_devices).values(
            expire_date=new_expiry,traffic_limit=max(child.traffic_limit or 0,math.ceil(child.traffic_usage or 0))+plan['quota'],
            quota_mode=plan.get('quota_mode',child.quota_mode),throttle_down_kbps=plan.get('throttle_down_kbps',child.throttle_down_kbps),throttle_up_kbps=plan.get('throttle_up_kbps',child.throttle_up_kbps),max_devices=plan['devices'],pause_sync_pending=True,notification_revision=(child.notification_revision or 0)+1)).rowcount
        if changed!=1:db.session.rollback();abort(409,'اطلاعات حساب تغییر کرده است؛ صفحه را تازه کنید و دوباره اقدام کنید.')
        snapshot=dict(plan,representative_id=representative.id,operation='reseller_renewal')
        ref='reseller-renew:'+reference
        try:
            db.session.add(Renewal(reference=reference,reseller_id=representative.id,user_id=child.id,username=child.username,amount=price,snapshot=json.dumps(snapshot,ensure_ascii=False)))
            db.session.add(commerce.Entry(user_id=representative.id,amount=-price,reason='تمدید حساب '+child.username,reference=ref))
            cost=''
            db.session.add(commerce.Invoice(source_reference=ref,request_id=0,user_id=child.id,username=child.username,amount=price,
                cost=int(cost)*plan['quota'] if cost.isdigit() else None,commission=0,snapshot=json.dumps(snapshot,ensure_ascii=False)))
            experience.notify(child.id,'حساب شما تمدید شد',f'{plan["days"]} روز و {plan["quota"]} گیگابایت اضافه شد؛ مصرف قبلی حفظ شده است.')
            experience.notify(representative.id,'تمدید انجام شد',f'{child.username} · {price:,} تومان از کیف پول کسر شد.')
            experience.notify(None,'Representative renewal',f'{child.username} renewed by representative #{representative.id}.')
            db.session.commit()
        except IntegrityError:
            db.session.rollback();abort(409,'درخواست تکراری است؛ موجودی دوباره کسر نشد.')
        child=db.session.get(User,child.id)
        try:errors=experience.sync_access(child)
        except Exception:
            errors=['pending'];app.logger.warning('Representative renewal access sync pending for user %s.',child.id)
        flash('تمدید ثبت شد؛ همگام‌سازی نود در حال پیگیری است.' if errors else 'تمدید انجام شد؛ تاریخچه و مصرف حساب حفظ شد.','warning' if errors else 'success')
        return redirect(base+'/c/'+token+'/reseller')
    def provision(order):
        # Claim once. A timed-out process may be retried after its lease expires.
        stamp=datetime.utcnow()
        claimed=db.session.execute(update(Order).where(Order.id==order.id,db.or_(Order.state=='pending',db.and_(Order.state=='working',Order.updated_at<stamp-timedelta(minutes=5)))).values(state='working',updated_at=stamp)).rowcount
        db.session.commit()
        if claimed!=1:return
        user=db.session.get(User,order.user_id);representative=db.session.get(User,order.reseller_id)
        try:
            if not user or not representative:raise RuntimeError('Account unavailable')
            allowed(representative)
            node=db.session.get(Node,order.node_id)
            if not node or not db.session.get(Grant,(representative.id,node.id)):raise RuntimeError('Node grant removed')
            from app import sync_primary_access,privileged_enabled,privileged_call
            from cluster import create_user_on_node,set_user_state_on_node
            # Deny access before issuing the certificate; the debit is already durable.
            sync_primary_access(user,False)
            if not is_primary_node(node):
                ok,_=set_user_state_on_node(node,user.username,False)
                if not ok:raise RuntimeError('Compatible node state API required')
            if privileged_enabled():privileged_call('create_user',username=user.username)
            else:subprocess.run(['/opt/beeny-panel/scripts/create_vpn_user.sh',user.username],check=True,timeout=120,capture_output=True)
            if not is_primary_node(node):
                if not str(create_user_on_node(node,user)).startswith('Success:'):raise RuntimeError('Certificate sync failed')
                ok,_=set_user_state_on_node(node,user.username,False)
                if not ok:raise RuntimeError('Node state not confirmed')
            # Recheck after external operations, so a removed grant cannot activate.
            db.session.expire_all();user=db.session.get(User,order.user_id);representative=db.session.get(User,order.reseller_id);allowed(representative)
            if not db.session.get(Grant,(representative.id,order.node_id)):raise RuntimeError('Node grant removed')
            if order.state!='working':raise RuntimeError('Order no longer pending')
            user.status='active';user.customer_paused=False;user.pause_sync_pending=True
            order.state='completed';order.error='';order.updated_at=datetime.utcnow()
            if not json.loads(order.snapshot).get('commission_sale') and not json.loads(order.snapshot).get('credit_sale') and not commerce.Invoice.query.filter_by(source_reference='reseller:'+order.reference).first():
                cost=''
                snapshot=json.loads(order.snapshot);snapshot.setdefault('id','reseller');snapshot.setdefault('title','حساب نمایندگی');snapshot.update(operation='reseller_create',representative_id=order.reseller_id,node_id=order.node_id)
                db.session.add(commerce.Invoice(source_reference='reseller:'+order.reference,request_id=0,user_id=user.id,username=user.username,amount=order.amount,cost=int(cost)*int(snapshot['quota']) if cost.isdigit() else None,commission=0,snapshot=json.dumps(snapshot)))
            from app import representative_credit
            experience.notify(representative.id,'حساب نمایندگی ساخته شد',f'{user.username} · {order.amount:,} تومان')
            db.session.commit()
        except Exception:
            db.session.rollback();order=db.session.get(Order,order.id)
            if order and order.state=='working':
                order.state='pending';order.error='ساخت یا تأیید نود کامل نشد. اعتبار رزرو است؛ دوباره تلاش کنید یا با مدیر تماس بگیرید.';order.updated_at=datetime.utcnow();db.session.commit()
            app.logger.warning('Reseller order %s pending; provisioning did not complete.',order.id if order else 'missing')
            return
        # Once activated an order is completed even if a node needs a retry.
        try:
            failures=experience.sync_access(user)
            if not failures:
                from app import representative_credit
                representative_credit.on_provision(order,confirmed=True);db.session.commit()
        except Exception:app.logger.warning('Reseller order %s activation awaits reconciliation.',order.id)
    @app.context_processor
    def context():
        def enabled(uid):
            row=db.session.get(Profile,uid)
            from app import commissions
            return bool((row and row.enabled) or db.session.get(commissions.Policy,uid))
        def private_enabled(token):
            try:return enabled(features.resolve_account(token).id)
            except Exception:return False
        return dict(is_reseller=enabled,customer_reseller_enabled=private_enabled)
    @app.route(base+'/settings/resellers',methods=['GET','POST'])
    @login_required
    def reseller_admin():
        if current_user.role!='owner':abort(403)
        if request.method=='GET':return redirect(base+'/settings/representative-credit?tab=nodes&reseller_id='+str(request.args.get('user_id',0,type=int)))
        if request.method=='POST':
            features.verify_csrf()
            if request.form.get('action') in {'lock','unlock','delete_representative'}:
                uid=request.form.get('user_id',type=int)
                profile=db.session.get(Profile,uid) or abort(404)
                if request.form['action']=='delete_representative':
                    return redirect(base+f'/settings/representatives/{uid}/remove')
                else:
                    profile.enabled=request.form['action']=='unlock'
                    if profile.enabled and not Grant.query.filter_by(user_id=uid).first():abort(409,'Assign at least one node before unlocking.')
                    flash('Representative access updated. VPN accounts were not changed.','success')
                db.session.commit()
            elif request.form.get('action')=='refund':
                order=db.session.get(Order,request.form.get('order_id',type=int)) or abort(404)
                stamp=datetime.utcnow()
                if json.loads(order.snapshot).get('commission_sale'):abort(409,'Use commission payment review; this order did not debit a wallet.')
                changed=db.session.execute(update(Order).where(Order.id==order.id,db.or_(Order.state=='pending',db.and_(Order.state=='working',Order.updated_at<stamp-timedelta(minutes=5)))).values(state='cancelled',updated_at=stamp)).rowcount
                if changed!=1:db.session.rollback();abort(409,'Only a pending, unactivated order can be refunded.')
                user=db.session.get(User,order.user_id)
                if user:user.status='disabled';user.customer_paused=True
                if json.loads(order.snapshot).get('credit_sale'):
                    from app import representative_credit
                    representative_credit.cancel(order)
                else:
                    changed=db.session.execute(update(commerce.Wallet).where(commerce.Wallet.user_id==order.reseller_id).values(balance=commerce.Wallet.balance+order.amount)).rowcount
                    if changed!=1:db.session.rollback();abort(409,'Wallet unavailable.')
                    db.session.add(commerce.Entry(user_id=order.reseller_id,amount=order.amount,reason='برگشت اعتبار سفارش نمایندگی #'+str(order.id),reference='reseller-refund:'+order.reference,admin_id=current_user.id))
                experience.notify(order.reseller_id,'اعتبار سفارش بازگشت داده شد',f'سفارش #{order.id} لغو شد؛ {order.amount:,} تومان برگشت داده شد.')
                db.session.commit();flash('Pending order cancelled and credit returned once.','success')
            else:
                uid=request.form.get('user_id',type=int);user=db.session.get(User,uid) or abort(404)
                rates={k:request.form.get(k,type=int) for k in ('base','per_gb','per_day','per_device')}
                if any(v is None or not 0<=v<=1000000000 for v in rates.values()):abort(400,'Enter non-negative Toman rates.')
                enabled=request.form.get('enabled')=='1';ids=request.form.getlist('nodes',type=int)
                if len(set(ids))!=len(ids) or set(ids)-{n.id for n in Node.query.all()}:abort(400,'Invalid node grant.')
                if enabled and (not ids or (not any(rates.values()) and not features.settings()['plans'])):abort(400,'Set approved plans or a tariff, and at least one permitted node.')
                profile=db.session.get(Profile,uid)
                if not profile:profile=Profile(user_id=uid);db.session.add(profile)
                profile.enabled=enabled
                for key,value in rates.items():setattr(profile,key,value)
                Grant.query.filter_by(user_id=uid).delete()
                for nid in ids:db.session.add(Grant(user_id=uid,node_id=nid))
                if not db.session.get(commerce.Wallet,uid):db.session.add(commerce.Wallet(user_id=uid,balance=0))
                db.session.commit();flash('Representative permissions and tariffs saved.','success')
            return redirect(base+'/settings/resellers')
        profiles=Profile.query.all();selected=request.args.get('user_id',type=int);profile=db.session.get(Profile,selected) if selected else None
        return render_template('reseller_admin.html',panel_path=panel_path,users=User.query.order_by(User.username).all(),nodes=Node.query.order_by(Node.name).all(),profiles=profiles,selected=selected,profile=profile,grants={g.node_id for g in Grant.query.filter_by(user_id=selected).all()} if selected else set(),wallets={w.user_id:w.balance for w in commerce.Wallet.query.all()},orders=Order.query.order_by(Order.id.desc()).limit(100).all())
    @app.route(base+'/c/<token>/reseller',methods=['GET','POST'])
    def customer_reseller(token):
        representative=features.resolve_account(token)
        from app import commissions
        if commissions.mode(representative.id):
            return redirect(base+'/c/'+token+'/reseller/commission')
        profile=allowed(representative)
        if request.method=='POST':
            features.verify_csrf()
            if request.form.get('action')=='renew':return renew_child(representative,profile,token)
            if request.form.get('action')=='retry':
                order=Order.query.filter_by(id=request.form.get('order_id',type=int),reseller_id=representative.id).first_or_404()
                provision(order);return redirect(base+'/c/'+token+'/reseller')
            reference=request.form.get('reference','')
            if not re.fullmatch(r'[a-f0-9]{32}',reference):abort(400)
            existing=Order.query.filter_by(reference=reference).first()
            if existing:
                if existing.reseller_id!=representative.id:abort(409)
                return redirect(base+'/c/'+token+'/reseller')
            username=request.form.get('username','').strip();password=request.form.get('password','')
            if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{2,63}',username) or not 12<=len(password)<=256:abort(400,'نام کاربری حداقل ۳ و رمز حداقل ۱۲ کاراکتر باشد.')
            plan=selected_plan(profile)
            days,quota,devices,price=(plan[key] for key in ('days','quota','devices','price'))
            nid=request.form.get('node_id',type=int)
            node=db.session.get(Node,nid)
            if not node or not db.session.get(Grant,(representative.id,nid)):abort(403,'این نود در مجوز نمایندگی شما نیست.')
            from app import devices as device_registry
            if User.query.filter_by(username=username).first() or db.session.get(device_registry.RetiredUsername,username):abort(409,'نام کاربری موجود است؛ نام دیگری انتخاب کنید.')
            # Conditional UPDATE is the authoritative balance check under concurrency.
            changed=db.session.execute(update(commerce.Wallet).where(commerce.Wallet.user_id==representative.id,commerce.Wallet.balance>=price).values(balance=commerce.Wallet.balance-price)).rowcount
            if changed!=1:db.session.rollback();abort(409,'موجودی کافی نیست؛ ابتدا کیف پول را شارژ کنید.')
            token_new=secrets.token_urlsafe(32)
            child=User(quota_mode=plan.get('quota_mode','metered'),throttle_down_kbps=plan.get('throttle_down_kbps',2000),throttle_up_kbps=plan.get('throttle_up_kbps',2000),username=username,reseller_id=representative.id,protocol='openvpn',max_devices=devices,expire_date=(datetime.utcnow().date()+timedelta(days=days)).isoformat(),traffic_limit=quota,status='disabled',customer_paused=True)
            try:
                db.session.add(child);db.session.flush()
                db.session.add(UserNode(user_id=child.id,node_id=nid))
                db.session.add(features.CustomerProfile(user_id=child.id,login_username=username,password_hash=generate_password_hash(password),auth_version=secrets.token_hex(24)))
                db.session.add(AccountLink(user_id=child.id,token_hash=hashlib.sha256(token_new.encode()).hexdigest()))
                snapshot=json.dumps(plan,ensure_ascii=False)
                order=Order(reference=reference,reseller_id=representative.id,user_id=child.id,node_id=nid,username=username,amount=price,snapshot=snapshot,portal_token=token_new)
                db.session.add(order)
                db.session.add(commerce.Entry(user_id=representative.id,amount=-price,reason='ساخت حساب نمایندگی '+username,reference='reseller:'+reference))
                db.session.commit()
            except IntegrityError:
                db.session.rollback();abort(409,'درخواست تکراری یا نام کاربری موجود است.')
            provision(order)
            flash('حساب ساخته شد.' if order.state=='completed' else 'سفارش ثبت شد؛ ساخت نود نیاز به پیگیری دارد. اعتبار دوباره کسر نمی‌شود.','success' if order.state=='completed' else 'warning')
            return redirect(base+'/c/'+token+'/reseller')
        wallet=db.session.get(commerce.Wallet,representative.id)
        search=request.args.get('q','').strip()[:64]
        query=Order.query.filter_by(reseller_id=representative.id)
        if search:query=query.filter(db.func.lower(Order.username).contains(search.lower(),autoescape=True))
        total=query.count();pages=max(1,math.ceil(total/12))
        page=max(1,min(request.args.get('page',1,type=int) or 1,pages))
        rows=query.order_by(db.func.lower(Order.username),Order.id.desc()).offset((page-1)*12).limit(12).all()
        children={u.id:u for u in User.query.filter_by(reseller_id=representative.id).all()}
        valid_links={order.id:bool((link:=db.session.get(AccountLink,order.user_id)) and link.token_hash==hashlib.sha256(order.portal_token.encode()).hexdigest()) for order in rows}
        renewals=Renewal.query.filter_by(reseller_id=representative.id).order_by(Renewal.id.desc()).limit(100).all()
        return render_template('reseller.html',panel_path=panel_path,token=token,profile=profile,policy=policy(profile),nodes=nodes_for(representative.id),orders=rows,children=children,balance=wallet.balance if wallet else 0,reference=secrets.token_hex(16),plans=features.settings()['plans'],login_names={uid:(db.session.get(features.CustomerProfile,uid).login_username or children[uid].username) if db.session.get(features.CustomerProfile,uid) else children[uid].username for uid in children},renewals=renewals,renew_references={uid:secrets.token_hex(16) for uid in children},valid_links=valid_links,search=search,page=page,pages=pages,total_orders=total)
    @app.post(base+'/c/<token>/reseller/users/<int:user_id>/delete')
    def reseller_delete(token,user_id):
        representative=features.resolve_account(token);allowed(representative)
        features.verify_csrf()
        child=User.query.filter_by(id=user_id,reseller_id=representative.id).first_or_404()
        order=Order.query.filter_by(user_id=child.id,reseller_id=representative.id).first_or_404()
        if order.state in {'pending','working'}:abort(409,'Resolve the pending order before deleting this account.')
        from app import remove_vpn_account
        remove_vpn_account(child)
        flash('حساب حذف شد؛ سوابق پرداخت حفظ شدند.','success')
        return redirect(base+'/c/'+token+'/reseller')
    @app.get(base+'/c/<token>/reseller/users/<int:user_id>/download')
    def reseller_download(token,user_id):
        representative=features.resolve_account(token);allowed(representative)
        child=User.query.filter_by(id=user_id,reseller_id=representative.id).first_or_404()
        order=Order.query.filter_by(user_id=child.id,reseller_id=representative.id,state='completed').first_or_404()
        if not db.session.get(Grant,(representative.id,order.node_id)):abort(403)
        from app import build_config
        return build_config(child,order.node_id)
    return SimpleNamespace(Profile=Profile,Grant=Grant,Order=Order,Renewal=Renewal,provision=provision,quote=quote,nodes_for=nodes_for)
