"""Single-level representative sales. Integer Toman, immutable price snapshots,
manual bank verification, durable provisioning and a separate settlement ledger.
Existing prepaid representatives are never converted implicitly.
"""
import hashlib, json, math, re, secrets
from datetime import datetime, timedelta
from types import SimpleNamespace
from flask import jsonify, abort, flash, redirect, render_template, request, session, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash


def register(app, db, User, Node, UserNode, AccountLink, features, experience, commerce, resellers, panel_path):
    base = panel_path.rstrip('/')
    class Policy(db.Model):
        __tablename__ = 'commission_policies'
        reseller_id = db.Column(db.Integer, primary_key=True)
        enabled = db.Column(db.Boolean, nullable=False, default=False)
        invite = db.Column(db.String(43), unique=True, nullable=False)
        minimum = db.Column(db.BigInteger, nullable=False, default=50000)
    class Rate(db.Model):
        __tablename__ = 'commission_rates'
        reseller_id = db.Column(db.Integer, primary_key=True)
        plan_id = db.Column(db.String(80), primary_key=True)
        base_price = db.Column(db.BigInteger, nullable=False)
        maximum = db.Column(db.BigInteger, nullable=False)
        sale_price = db.Column(db.BigInteger, nullable=False)
        enabled = db.Column(db.Boolean, nullable=False, default=True)
    class Sale(db.Model):
        __tablename__ = 'commission_sales'
        id = db.Column(db.Integer, primary_key=True)
        reference = db.Column(db.String(32), nullable=False, unique=True)
        tracking = db.Column(db.String(43), nullable=False, unique=True)
        reseller_id = db.Column(db.Integer, nullable=False, index=True)
        user_id = db.Column(db.Integer, index=True)
        node_id = db.Column(db.Integer, nullable=False)
        username = db.Column(db.String(64), nullable=False)
        password_hash = db.Column(db.String(255), nullable=False, default='')
        plan = db.Column(db.Text, nullable=False)
        receipt = db.Column(db.String(80), nullable=False)
        receipt_digest = db.Column(db.String(64), unique=True, nullable=False)
        name = db.Column(db.String(100), nullable=False)
        contact = db.Column(db.String(120), nullable=False)
        state = db.Column(db.String(20), nullable=False, default='pending', index=True)
        order_id = db.Column(db.Integer, unique=True)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        reviewed_at = db.Column(db.DateTime)
        admin_id = db.Column(db.Integer)
        ip_digest = db.Column(db.String(64), nullable=False)
        next_attempt = db.Column(db.DateTime,default=datetime.utcnow,nullable=False)
        attempts = db.Column(db.Integer,default=0,nullable=False)
    class Earning(db.Model):
        __tablename__ = 'commission_earnings'
        id = db.Column(db.Integer, primary_key=True)
        reference = db.Column(db.String(80), unique=True, nullable=False)
        reseller_id = db.Column(db.Integer, nullable=False, index=True)
        user_id = db.Column(db.Integer, nullable=False)
        username = db.Column(db.String(100), nullable=False)
        amount = db.Column(db.BigInteger, nullable=False)
        sale_amount = db.Column(db.BigInteger, nullable=False)
        base_amount = db.Column(db.BigInteger, nullable=False)
        snapshot = db.Column(db.Text, nullable=False)
        state = db.Column(db.String(20), nullable=False, default='held', index=True)
        settlement_id = db.Column(db.Integer, index=True)
        offset_used = db.Column(db.BigInteger,nullable=False,default=0)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    class Settlement(db.Model):
        __tablename__ = 'commission_settlements'
        id = db.Column(db.Integer, primary_key=True)
        reference = db.Column(db.String(32), unique=True, nullable=False)
        reseller_id = db.Column(db.Integer, nullable=False, index=True)
        amount = db.Column(db.BigInteger, nullable=False)
        state = db.Column(db.String(20), nullable=False, default='requested')
        destination = db.Column(db.String(200), nullable=False)
        receipt = db.Column(db.String(80), default='')
        payment_reference = db.Column(db.String(100), unique=True)
        admin_id = db.Column(db.Integer)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        paid_at = db.Column(db.DateTime)
    class Refund(db.Model):
        __tablename__ = 'commission_refunds'
        id = db.Column(db.Integer, primary_key=True)
        earning_id = db.Column(db.Integer, unique=True)
        sale_id = db.Column(db.Integer, unique=True)
        amount = db.Column(db.BigInteger, nullable=False)
        payment_reference = db.Column(db.String(100), unique=True, nullable=False)
        reason = db.Column(db.String(250), nullable=False)
        admin_id = db.Column(db.Integer, nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    db.Index('commission_unique_pending_username',Sale.username,unique=True,sqlite_where=Sale.state.in_(['pending','provisioning']),postgresql_where=Sale.state.in_(['pending','provisioning']))
    db.Index('commission_one_pending_settlement',Settlement.reseller_id,unique=True,sqlite_where=Settlement.state=='requested',postgresql_where=Settlement.state=='requested')
    class Receipt(db.Model):
        __tablename__='commission_receipt_registry'
        digest=db.Column(db.String(64),primary_key=True)
        reference=db.Column(db.String(100),nullable=False,unique=True)
        created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)
    def claim_receipt(filename,reference):
        digest=hashlib.sha256((features.storage/filename).read_bytes()).hexdigest()
        if db.session.get(Receipt,digest):raise ValueError('این رسید قبلاً ثبت شده است.')
        db.session.add(Receipt(digest=digest,reference=reference))
        return digest

    class Alert(db.Model):
        __tablename__='commission_admin_alerts'
        id=db.Column(db.Integer,primary_key=True)
        reference=db.Column(db.String(100),nullable=False,unique=True)
        body=db.Column(db.Text,nullable=False)
        sent=db.Column(db.Text,nullable=False,default='[]')
        completed=db.Column(db.Boolean,nullable=False,default=False)
        attempts=db.Column(db.Integer,nullable=False,default=0)
        next_attempt=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
    def alert(reference,body):
        if not Alert.query.filter_by(reference=reference).first():db.session.add(Alert(reference=reference,body=body))
    def deliver_alerts():
        cfg=features.settings()
        recipients=list(dict.fromkeys(v for v in [cfg['admin_chat_id']]+cfg['admin_chat_ids'].split(',') if re.fullmatch(r'-?\d{1,20}',v or '')))
        if not recipients:return
        for row in Alert.query.filter(Alert.completed.is_(False),Alert.attempts<8,Alert.next_attempt<=datetime.utcnow()).limit(5):
            sent=json.loads(row.sent)
            try:
                for recipient in recipients:
                    if recipient in sent:continue
                    features.telegram('sendMessage',dict(chat_id=recipient,text=row.body))
                    sent.append(recipient);row.sent=json.dumps(sent);db.session.commit()
                row.completed=True
            except Exception:
                row.attempts+=1;row.next_attempt=datetime.utcnow()+timedelta(seconds=min(3600,30*2**row.attempts))
                app.logger.warning('Commission notification %s delivery pending.',row.id)
            db.session.commit()

    def owner():
        if not current_user.is_authenticated or current_user.role != 'owner': abort(403)
    def mode(uid):
        row = db.session.get(Policy, uid)
        return bool(row and row.enabled)
    def active(uid):
        from app import representative_credit
        a=representative_credit.Account.query.get(uid)
        if a and (a.locked or a.suspended):return False
        profile = db.session.get(resellers.Profile, uid)
        user = db.session.get(User, uid)
        return bool(mode(uid) and profile and profile.enabled and user and user.status == 'active')
    def offers(uid):
        plans = {p['id']:p for p in features.settings()['plans']}
        result = []
        for rate in Rate.query.filter_by(reseller_id=uid, enabled=True).order_by(Rate.plan_id):
            if rate.plan_id in plans and 1 <= rate.base_price <= rate.sale_price <= rate.maximum <= 1000000000:
                result.append(dict(plans[rate.plan_id], price=rate.sale_price, commission_base=rate.base_price,
                                   commission_reseller=uid, commission_maximum=rate.maximum, commission_amount=rate.sale_price-rate.base_price))
        return result
    def customer_plan(user, plan):
        if not user.reseller_id or not mode(user.reseller_id): return plan
        from app import representative_credit
        credit=representative_credit.mode(user.reseller_id)
        if (credit and representative_credit.suspended(user)) or (not credit and not active(user.reseller_id)): raise ValueError('فروش نماینده موقتاً متوقف است؛ با پشتیبانی تماس بگیرید.')
        if plan['id']=='custom' and credit:
            from app import representative_catalog
            selected=representative_catalog.custom_quote(user.reseller_id,plan['days'],plan['quota'],plan['devices'])
        else:selected = next((p for p in offers(user.reseller_id) if p['id']==plan['id']), None)
        if not selected: raise ValueError('این سرویس در پلن‌های مجاز نماینده نیست.')
        assigned = {r.node_id for r in UserNode.query.filter_by(user_id=user.id)}
        granted = {r.node_id for r in resellers.Grant.query.filter_by(user_id=user.reseller_id)}
        if not assigned or assigned-granted: raise ValueError('نود این حساب نیاز به بررسی مدیر دارد.')
        return selected
    def customer_settings(user, cfg):
        if not user.reseller_id or not mode(user.reseller_id): return cfg
        result = dict(cfg, plans=offers(user.reseller_id))
        from app import representative_catalog
        result['custom_pricing'] = representative_catalog.retail_policy(user.reseller_id) if __import__('app').representative_credit.mode(user.reseller_id) else dict(cfg['custom_pricing'], enabled=False)
        return result
    def snapshot_discount(plan, code):
        if plan.get('commission_reseller') and code.strip():
            raise ValueError('کد تخفیف برای قیمت اختصاصی نمایندگی قابل استفاده نیست.')
    def book(reference, user, plan):
        uid = plan.get('commission_reseller')
        if not uid: return
        if type(uid) is not int or type(plan.get('commission_base')) is not int or not 1 <= plan['commission_base'] <= plan['price'] <= 1000000000:
            raise ValueError('Invalid commission snapshot')
        if Earning.query.filter_by(reference=reference).first(): return
        db.session.add(Earning(reference=reference, reseller_id=uid, user_id=user.id, username=user.username,
                               amount=plan['price']-plan['commission_base'], sale_amount=plan['price'],
                               base_amount=plan['commission_base'], snapshot=json.dumps(plan, ensure_ascii=False)))
    def release(reference, confirmed=False):
        row = Earning.query.filter_by(reference=reference, state='held').first()
        if not row: return
        user = db.session.get(User, row.user_id)
        from app import representative_credit
        from app import representative_actions
        if not user or user.status!='active' or representative_credit.suspended(user) or representative_actions.blocked(user): return
        if not confirmed and experience.sync_access(user): return
        changed = db.session.execute(update(Earning).where(Earning.id==row.id, Earning.state=='held').values(state='available')).rowcount
        if changed:
            experience.notify(row.reseller_id, 'پورسانت فروش ثبت شد', f'{row.username} · {row.amount:,} تومان؛ آماده درخواست تسویه.')
        db.session.commit()
    def finish_order(order):
        sale = Sale.query.filter_by(order_id=order.id, state='provisioning').first()
        if not sale or order.state!='completed': return
        user = db.session.get(User, order.user_id)
        if not user or experience.sync_access(user): return
        changed = db.session.execute(update(Sale).where(Sale.id==sale.id, Sale.state=='provisioning').values(state='completed')).rowcount
        if not changed: db.session.rollback();return
        plan=json.loads(sale.plan);ref='commission:'+sale.reference
        book(ref, user, plan)
        if not commerce.Invoice.query.filter_by(source_reference=ref).first():
            cost=''
            db.session.add(commerce.Invoice(source_reference=ref,request_id=0,user_id=user.id,username=user.username,
                           amount=plan['price'],cost=int(cost)*plan['quota'] if cost.isdigit() else None,
                           commission=plan['commission_amount'],snapshot=sale.plan))
        experience.notify(user.id,'اکانت شما آماده است','پرداخت تأیید و سرویس فعال شد؛ کانفیگ را از پروفایل دریافت کنید.')
        db.session.commit();release(ref,confirmed=True)
    def cycle():
        from app import representative_credit
        representative_credit.cycle()
        # Do not reprovision unrelated prepaid orders or change quotas during upgrade.
        for sale in Sale.query.filter(Sale.state=='provisioning',Sale.next_attempt<=datetime.utcnow()).order_by(Sale.id).limit(3):
            sale.attempts+=1;sale.next_attempt=datetime.utcnow()+timedelta(seconds=min(900,30*2**min(sale.attempts,5)))
            db.session.commit()
            order=db.session.get(resellers.Order,sale.order_id)
            if order:
                if order.state!='completed':resellers.provision(order)
                finish_order(order)
        for row in Earning.query.filter_by(state='held').order_by(db.func.random()).limit(10):
            release(row.reference)
        deliver_alerts()
    def sums(uid=None):
        query=Earning.query
        if uid is not None:query=query.filter_by(reseller_id=uid)
        totals={state:0 for state in ('held','available','reserved','settled')}
        for row in query:
            if row.state in totals:totals[row.state]+=row.amount-row.offset_used
        totals['sales']=sum(r.sale_amount for r in query if r.amount>=0 and r.state!='reversed')
        payouts=Settlement.query.filter_by(state='paid')
        if uid is not None:payouts=payouts.filter_by(reseller_id=uid)
        totals['settled']=sum(r.amount for r in payouts)
        return totals
    def save_receipt(upload):
        from customer_features import MAX_UPLOAD
        if not upload:abort(400,'تصویر رسید لازم است.')
        filename=features.store_image(upload.stream.read(MAX_UPLOAD+1))
        digest=hashlib.sha256((features.storage/filename).read_bytes()).hexdigest()
        # Exact normalized-image duplicate protection; bank verification remains manual.
        if db.session.get(Receipt,digest) or Sale.query.filter_by(receipt_digest=digest).first():
            (features.storage/filename).unlink(missing_ok=True);abort(409,'این رسید قبلاً ثبت شده است.')
        return filename,digest
    def private_image(filename):
        if not re.fullmatch(r'[a-f0-9]+\.(jpg|webp|png)',filename or ''):abort(404)
        path=features.storage/filename
        if not path.is_file():abort(404)
        response=send_file(path);response.headers['Cache-Control']='no-store';return response
    def common(uid):
        p=db.session.get(Policy,uid)
        return dict(commission_policy=p,commission_offers=offers(uid),commission_totals=sums(uid),
                    commission_earnings=Earning.query.filter_by(reseller_id=uid).order_by(Earning.id.desc()).limit(50).all(),
                    commission_rates={r.plan_id:r for r in Rate.query.filter_by(reseller_id=uid)},
                    commission_settlements=Settlement.query.filter_by(reseller_id=uid).order_by(Settlement.id.desc()).limit(30).all(),
                    sale_link=request.host_url.rstrip('/')+base+'/r/'+p.invite if p else '',
                    settlement_reference=secrets.token_hex(16))
    @app.context_processor
    def context():
        def label(state):
            en=session.get('customer_language','fa')=='en'
            labels={'pending':('در انتظار بررسی','Awaiting review'),'provisioning':('در حال ساخت','Provisioning'),
                    'completed':('تکمیل‌شده','Completed'),'working':('در حال ساخت','Provisioning'),
                    'cancelled':('لغوشده','Cancelled'),'rejected':('ردشده','Rejected'),
                    'available':('قابل تسویه','Available'),'held':('در انتظار تأیید سرویس','Awaiting service confirmation'),
                    'reserved':('رزروشده برای تسویه','Reserved for payout'),'settled':('تسویه‌شده','Settled'),
                    'reversed':('برگشت‌خورده','Refunded'),'refunded':('برگشت وجه','Refunded')}
            return labels.get(state,(state,state))[1 if en else 0]
        return dict(commission_mode=mode,commission_has_account=lambda uid:bool(db.session.get(Policy,uid)),commission_label=label)
    @app.after_request
    def protect_purchase(response):
        if request.path.startswith(base+'/r/'):
            response.headers['Cache-Control']='no-store'
            response.headers['Referrer-Policy']='no-referrer'
            response.headers['X-Robots-Tag']='noindex, nofollow'
        return response
    @app.before_request
    def upload_limit():
        if request.endpoint in {'commission_shop','commission_manage','commission_admin'}:
            from customer_features import MAX_UPLOAD
            request.max_content_length=MAX_UPLOAD+1024*1024
    @app.route(base+'/r/<invite>',methods=['GET','POST'])
    def commission_shop(invite):
        policy=Policy.query.filter_by(invite=invite,enabled=True).first_or_404()
        from app import representative_credit
        if representative_credit.mode(policy.reseller_id):abort(410,'This representative now creates accounts through their private credit workspace.')
        if not active(policy.reseller_id):abort(404)
        allowed_nodes=Node.query.join(resellers.Grant,resellers.Grant.node_id==Node.id).filter(resellers.Grant.user_id==policy.reseller_id).all()
        cfg=features.settings();plans=offers(policy.reseller_id)
        if request.method=='POST':
            features.verify_csrf()
            ref=request.form.get('reference','')
            if not re.fullmatch('[a-f0-9]{32}',ref):abort(400)
            existing=Sale.query.filter_by(reference=ref).first()
            if existing:
                if session.get('commission_tracking')!=existing.tracking:abort(409)
                return redirect(base+'/r/order/'+existing.tracking)
            ip=hashlib.sha256((request.remote_addr or '').encode()).hexdigest()
            if Sale.query.filter(Sale.ip_digest==ip,Sale.created_at>=datetime.utcnow()-timedelta(days=1)).count()>=5:abort(429,'سقف درخواست امروز تکمیل شده است.')
            plan=next((p for p in plans if p['id']==request.form.get('plan_id')),None)
            node=next((n for n in allowed_nodes if n.id==request.form.get('node_id',type=int)),None)
            if not plan or not node:abort(400)
            name=request.form.get('username','').strip();password=request.form.get('password','')
            from app import devices
            if not re.fullmatch('[A-Za-z0-9_-][A-Za-z0-9_.-]{2,63}',name) or not 12<=len(password)<=256:abort(400,'نام کاربری و رمز معتبر وارد کنید.')
            if User.query.filter_by(username=name).first() or db.session.get(devices.RetiredUsername,name) or Sale.query.filter(Sale.username==name,Sale.state.in_(['pending','provisioning'])).first():abort(409,'نام کاربری قبلاً استفاده شده است.')
            contact=request.form.get('contact','').strip();buyer=request.form.get('name','').strip()
            if not buyer or not contact:abort(400)
            card=next((c for c in cfg['bank_cards'] if c['id']==request.form.get('card_id')),None)
            if not card:abort(400,'مدیر باید کارت پرداخت را تنظیم کند.')
            filename,digest=save_receipt(request.files.get('receipt'));tracking=secrets.token_urlsafe(32)
            try:
                row=Sale(reference=ref,tracking=tracking,reseller_id=policy.reseller_id,node_id=node.id,username=name,
                         password_hash=generate_password_hash(password),plan=json.dumps(dict(plan,payment_card=card),ensure_ascii=False),
                         receipt=filename,receipt_digest=digest,name=buyer[:100],contact=contact[:120],ip_digest=ip)
                claim_receipt(filename,'sale:'+ref)
                db.session.add(row);db.session.flush()
                experience.notify(None,'Commission sale awaiting payment review',f'{name} · {plan["price"]:,} Toman · representative #{policy.reseller_id}')
                experience.notify(policy.reseller_id,'سفارش فروش جدید',f'{name} · در انتظار تأیید پرداخت مدیر')
                alert('sale:'+ref,f'خرید جدید نمایندگی #{policy.reseller_id}\nکاربر: {name}\nمبلغ: {plan["price"]:,} تومان\nبررسی رسید از صندوق فروش پورسانتی پنل مدیریت · سفارش #{row.id}')
                db.session.commit()
            except (IntegrityError,ValueError):
                db.session.rollback();(features.storage/filename).unlink(missing_ok=True);abort(409,'رسید یا سفارش تکراری است.')
            except Exception:
                db.session.rollback();(features.storage/filename).unlink(missing_ok=True);raise
            session['commission_tracking']=tracking
            return redirect(base+'/r/order/'+tracking)
        return render_template('commission_shop.html',panel_path=panel_path,token=None,plans=plans,nodes=allowed_nodes,
                    customer_settings=cfg,reference=secrets.token_hex(16),representative=db.session.get(User,policy.reseller_id))
    @app.get(base+'/r/order/<tracking>')
    def commission_tracking(tracking):
        row=Sale.query.filter_by(tracking=tracking).first_or_404()
        order=db.session.get(resellers.Order,row.order_id) if row.order_id else None
        link=db.session.get(AccountLink,row.user_id) if row.user_id else None
        portal=base+'/c/'+order.portal_token if row.state=='completed' and order and link and link.token_hash==hashlib.sha256(order.portal_token.encode()).hexdigest() else ''
        response=app.make_response(render_template('commission_tracking.html',token=None,panel_path=panel_path,row=row,portal=portal))
        response.headers['Cache-Control']='no-store';return response
    def approve(sale):
        if sale.state=='completed':return
        if sale.state=='provisioning':
            order=db.session.get(resellers.Order,sale.order_id);resellers.provision(order);finish_order(order);return
        if not active(sale.reseller_id) or not db.session.get(resellers.Grant,(sale.reseller_id,sale.node_id)):abort(409,'Representative or node permission is unavailable.')
        changed=db.session.execute(update(Sale).where(Sale.id==sale.id,Sale.state=='pending').values(state='provisioning',reviewed_at=datetime.utcnow(),admin_id=current_user.id)).rowcount
        if changed!=1:db.session.rollback();abort(409)
        from app import devices
        if User.query.filter_by(username=sale.username).first() or db.session.get(devices.RetiredUsername,sale.username):db.session.rollback();abort(409,'Username no longer available; reject and resolve the payment.')
        plan=json.loads(sale.plan);token=secrets.token_urlsafe(32)
        from app import sales_engine
        sales_engine.receipt('commission:'+sale.reference,sale.user_id,'representative',int(plan['price']),'receipt',sale.reviewed_at)
        child=User(username=sale.username,reseller_id=sale.reseller_id,protocol='openvpn',max_devices=plan['devices'],
                   expire_date=(datetime.utcnow().date()+timedelta(days=plan['days'])).isoformat(),traffic_limit=plan['quota'],
                   quota_mode=plan.get('quota_mode','metered'),throttle_down_kbps=plan.get('throttle_down_kbps',2000),
                   throttle_up_kbps=plan.get('throttle_up_kbps',2000),status='disabled',customer_paused=True)
        try:
            db.session.add(child);db.session.flush();sale.user_id=child.id
            db.session.add(UserNode(user_id=child.id,node_id=sale.node_id))
            db.session.add(features.CustomerProfile(user_id=child.id,login_username=child.username,password_hash=sale.password_hash,auth_version=secrets.token_hex(24)))
            db.session.add(AccountLink(user_id=child.id,token_hash=hashlib.sha256(token.encode()).hexdigest()))
            order=resellers.Order(reference=sale.reference,reseller_id=sale.reseller_id,user_id=child.id,node_id=sale.node_id,
                         username=child.username,amount=plan['price'],snapshot=json.dumps(dict(plan,commission_sale=sale.id)),portal_token=token)
            db.session.add(order);db.session.flush();sale.order_id=order.id;sale.password_hash='';db.session.commit()
        except IntegrityError:db.session.rollback();abort(409,'Account or order already exists.')
        resellers.provision(order);finish_order(order)
    @app.route(base+'/settings/commissions',methods=['GET','POST'])
    @login_required
    def commission_admin():
        owner()
        if request.method=='GET':return redirect(base+'/settings/representative-credit?tab=prices&reseller_id='+str(request.args.get('reseller_id',0,type=int)))
        if request.method=='POST':
            features.verify_csrf();action=request.form.get('action')
            if action=='policy':
                uid=request.form.get('reseller_id',type=int)
                if not db.session.get(resellers.Profile,uid):abort(400,'Configure representative and node permissions first.')
                p=db.session.get(Policy,uid)
                minimum=request.form.get('minimum',50000,type=int)
                if minimum is None or not 1<=minimum<=1000000000:abort(400)
                if not p:p=Policy(reseller_id=uid,invite=secrets.token_urlsafe(32));db.session.add(p)
                enabled=request.form.get('enabled')=='1'
                from app import representative_credit
                if not enabled and representative_credit.mode(uid):abort(409,'Disable the credit model after resolving debt before changing commission mode.')
                if p.enabled!=enabled and (Settlement.query.filter_by(reseller_id=uid,state='requested').first() or Earning.query.filter_by(reseller_id=uid,state='held').first()):abort(409,'Resolve pending settlements and held commissions before changing mode.')
                if p.enabled!=enabled and Sale.query.filter(Sale.reseller_id==uid,Sale.state.in_(['pending','provisioning'])).first():abort(409,'Resolve pending sales before changing the sales mode.')
                p.enabled=enabled;p.minimum=minimum
                for plan in features.settings()['plans']:
                    key=plan['id'];low=request.form.get('base_'+key,type=int);high=request.form.get('max_'+key,type=int)
                    if low is None or high is None or not 1<=low<=high<=1000000000:abort(400,'Invalid price boundaries.')
                    rate=db.session.get(Rate,(uid,key))
                    if not rate:rate=Rate(reseller_id=uid,plan_id=key,sale_price=low);db.session.add(rate)
                    rate.base_price=low;rate.maximum=high;rate.sale_price=max(low,min(high,rate.sale_price));rate.enabled=request.form.get('plan_'+key)=='1'
                db.session.commit();flash('تعرفه‌ها و قواعد فروش ذخیره شد؛ سوابق قبلی حفظ شدند.','success')
            elif action in {'pay','reject_settlement'}:
                row=db.session.get(Settlement,request.form.get('settlement_id',type=int)) or abort(404)
                if row.state!='requested':abort(409,'Settlement already reviewed.')
                filename=''
                if action=='pay':
                    payment=request.form.get('payment_reference','').strip()
                    if not 3<=len(payment)<=100 or Settlement.query.filter_by(payment_reference=payment).first():abort(400,'Unique bank transfer reference required.')
                    filename,_=save_receipt(request.files.get('receipt'))
                try:
                    changed=db.session.execute(update(Settlement).where(Settlement.id==row.id,Settlement.state=='requested').values(
                        state='paid' if action=='pay' else 'rejected',admin_id=current_user.id,
                        receipt=filename,payment_reference=payment if action=='pay' else None,paid_at=datetime.utcnow() if action=='pay' else None)).rowcount
                    if action=='pay':claim_receipt(filename,'settlement:'+str(row.id))
                    if changed!=1:abort(409)
                    db.session.execute(update(Earning).where(Earning.settlement_id==row.id,Earning.state=='reserved').values(
                        state='settled' if action=='pay' else 'available',settlement_id=row.id if action=='pay' else None))
                    experience.notify(row.reseller_id,'تسویه پورسانت پرداخت شد' if action=='pay' else 'درخواست تسویه رد شد',f'درخواست #{row.id} · {row.amount:,} تومان')
                    db.session.commit()
                except (IntegrityError,ValueError):
                    db.session.rollback()
                    if filename:(features.storage/filename).unlink(missing_ok=True)
                    abort(409,'Duplicate transfer receipt or reference.')
                except Exception:
                    db.session.rollback()
                    if filename:(features.storage/filename).unlink(missing_ok=True)
                    raise
            elif action=='refund':
                earning=db.session.get(Earning,request.form.get('earning_id',type=int)) or abort(404)
                if earning.amount<0 or earning.state in {'reserved','reversed'} or Refund.query.filter_by(earning_id=earning.id).first():abort(409,'Reject a reserved settlement first; this sale can be refunded only once.')
                payment=request.form.get('payment_reference','').strip();reason=request.form.get('reason','').strip()
                if not 3<=len(payment)<=100 or not 3<=len(reason)<=250:abort(400)
                if Refund.query.filter_by(payment_reference=payment).first():abort(409,'Bank refund reference already recorded.')
                original=earning.state
                changed=db.session.execute(update(Earning).where(Earning.id==earning.id,Earning.state==original,Earning.offset_used==earning.offset_used).values(state='reversed')).rowcount
                if changed!=1:abort(409)
                db.session.add(Refund(earning_id=earning.id,amount=earning.sale_amount,payment_reference=payment,reason=reason,admin_id=current_user.id))
                if original=='settled' or earning.offset_used:
                    db.session.add(Earning(reference='refund:'+earning.reference,reseller_id=earning.reseller_id,user_id=earning.user_id,
                               username=earning.username,amount=-(earning.amount if original=='settled' else earning.offset_used),sale_amount=0,base_amount=0,snapshot=earning.snapshot,state='available'))
                user=db.session.get(User,earning.user_id)
                if user:user.status='disabled';user.pause_sync_pending=True;experience.notify(user.id,'پرداخت سرویس برگشت داده شد','برای وضعیت سرویس با مدیر تماس بگیرید.')
                experience.notify(earning.reseller_id,'اصلاح پورسانت فروش',f'{earning.username} · برگشت وجه ثبت شد؛ سهم این سفارش اصلاح شد.')
                db.session.commit()
                if user:experience.sync_access(user)
                flash('برگشت وجه ثبت و حساب مسدود شد؛ واریز بانکی باید واقعاً توسط مدیر انجام شده باشد.','success')
            else:abort(400)
            return redirect(base+'/settings/commissions')
        selected=request.args.get('reseller_id',type=int)
        profiles=resellers.Profile.query.all();users={u.id:u for u in User.query.all()}
        return render_template('commission_admin.html',panel_path=panel_path,profiles=profiles,users=users,selected=selected,
             policy=db.session.get(Policy,selected) if selected else None,plans=features.settings()['plans'],
             rates={r.plan_id:r for r in Rate.query.filter_by(reseller_id=selected)},totals=sums(),
             settlements=Settlement.query.order_by(Settlement.id.desc()).limit(60).all(),
             earnings=Earning.query.order_by(Earning.id.desc()).limit(60).all(),
             refunds=Refund.query.order_by(Refund.id.desc()).limit(60).all(),
            policies={p.reseller_id:p for p in Policy.query.all()},per_rep={p.user_id:sums(p.user_id) for p in profiles})
    @app.route(base+'/settings/commissions/sales/<int:sale_id>',methods=['GET','POST'])
    @login_required
    def commission_manage(sale_id):
        owner();sale=db.session.get(Sale,sale_id) or abort(404)
        if request.method=='POST':
            features.verify_csrf()
            if request.form.get('action')=='approve':approve(sale)
            elif request.form.get('action')=='reject':
                changed=db.session.execute(update(Sale).where(Sale.id==sale.id,Sale.state=='pending').values(state='rejected',reviewed_at=datetime.utcnow(),admin_id=current_user.id)).rowcount
                if not changed:db.session.rollback();abort(409)
                sale.password_hash='';experience.notify(sale.reseller_id,'سفارش فروش تأیید نشد',sale.username);db.session.commit()
            elif request.form.get('action')=='refund_failed':
                if sale.state!='provisioning':abort(409)
                order=db.session.get(resellers.Order,sale.order_id) or abort(409)
                payment=request.form.get('payment_reference','').strip();reason=request.form.get('reason','').strip()
                if not 3<=len(payment)<=100 or not 3<=len(reason)<=250:abort(400)
                if Refund.query.filter_by(payment_reference=payment).first():abort(409,'Bank refund reference already recorded.')
                changed=db.session.execute(update(Sale).where(Sale.id==sale.id,Sale.state=='provisioning').values(state='refunded')).rowcount
                if changed!=1:db.session.rollback();abort(409,'Sale state changed; refresh before recording a refund.')
                changed=db.session.execute(update(resellers.Order).where(resellers.Order.id==order.id,db.or_(resellers.Order.state.in_(['pending','completed']),db.and_(resellers.Order.state=='working',resellers.Order.updated_at<datetime.utcnow()-timedelta(minutes=5)))).values(state='cancelled',updated_at=datetime.utcnow())).rowcount
                if changed!=1:db.session.rollback();abort(409,'Provision is actively working; retry after it finishes.')
                sale.state='refunded';sale.password_hash=''
                user=db.session.get(User,sale.user_id)
                if user:user.status='disabled';user.customer_paused=True;user.pause_sync_pending=True
                db.session.add(Refund(sale_id=sale.id,amount=json.loads(sale.plan)['price'],payment_reference=payment,reason=reason,admin_id=current_user.id))
                experience.notify(sale.reseller_id,'وجه سفارش ناموفق برگشت داده شد',sale.username)
                db.session.commit()
                if user:experience.sync_access(user)
            else:abort(400)
            return redirect(request.path)
        return render_template('commission_sale.html',row=sale,plan=json.loads(sale.plan),panel_path=panel_path)
    @app.get(base+'/settings/commissions/sales')
    @login_required
    def commission_sales():
        owner();q=request.args.get('q','').strip()[:64];state=request.args.get('state','pending')
        query=Sale.query
        if state in {'pending','provisioning','completed','rejected'}:query=query.filter_by(state=state)
        if q:query=query.filter(Sale.username.contains(q,autoescape=True))
        page=query.order_by(Sale.id.desc()).paginate(page=max(1,request.args.get('page',1,type=int) or 1),per_page=20,error_out=False)
        return render_template('commission_sales.html',rows=page,search=q,state=state,panel_path=panel_path)
    @app.get(base+'/settings/commissions/sales/<int:sale_id>/receipt')
    @login_required
    def commission_sale_receipt(sale_id):owner();return private_image((db.session.get(Sale,sale_id) or abort(404)).receipt)
    @app.route(base+'/c/<token>/reseller/commission',methods=['GET','POST'])
    def commission_workspace(token):
        user=features.resolve_account(token)
        if not db.session.get(Policy,user.id):abort(404)
        from app import representative_credit
        if request.method=='GET' and representative_credit.mode(user.id):return redirect(base+'/c/'+token+'/reseller/credit')
        # Locked representatives retain financial history; sales mutation requires active permission.
        if request.method=='POST':
            features.verify_csrf();action=request.form.get('action')
            if action=='price':
                ajax=request.headers.get('X-Requested-With')=='XMLHttpRequest'
                def price_error(status,code,message):
                    if ajax:return jsonify(ok=False,code=code,error=message),status
                    abort(status,message)
                if not active(user.id):return price_error(403,'sales_unavailable','نمایندگی قفل یا غیرفعال است؛ مجوز فروش را با مدیر بررسی کنید.')
                rate=db.session.get(Rate,(user.id,request.form.get('plan_id')))
                if not rate:return price_error(404,'plan_missing','این پلن برای نماینده تعریف نشده است.')
                if not rate.enabled:return price_error(403,'plan_disabled','فروش این پلن توسط مدیر غیرفعال شده است.')
                price=request.form.get('price',type=int)
                if price is None:return price_error(400,'invalid_price','قیمت را به تومان و به صورت عدد صحیح وارد کنید.')
                if not rate.base_price<=price<=rate.maximum:return price_error(400,'price_out_of_range',f'قیمت باید بین {rate.base_price:,} و {rate.maximum:,} تومان باشد.')
                rate.sale_price=price;db.session.commit()
                if request.headers.get('X-Requested-With')=='XMLHttpRequest':return jsonify(ok=True,price=price,base=rate.base_price,message='قیمت فروش ذخیره شد؛ سفارش‌های قبلی تغییر نکردند.')
                flash('قیمت فروش ذخیره شد. سفارش‌های قبلی تغییر نکردند.','success')
            elif action=='settlement':
                ref=request.form.get('reference','');destination=request.form.get('destination','').strip()
                if not re.fullmatch('[a-f0-9]{32}',ref) or not 8<=len(destination)<=200:abort(400)
                old=Settlement.query.filter_by(reference=ref).first()
                if old:
                    if old.reseller_id!=user.id:abort(409)
                    return redirect(base+'/c/'+token+'/reseller/credit/'+('prices' if action=='price' else 'income')) if representative_credit.mode(user.id) else redirect(request.path)
                # SQLite writers serialize; every earning is compare-and-set reserved.
                entries=Earning.query.filter_by(reseller_id=user.id,state='available').all();total=sum(r.amount-r.offset_used for r in entries)
                if total<db.session.get(Policy,user.id).minimum or total<=0:abort(409,'مبلغ قابل تسویه به حداقل نرسیده است.')
                if Settlement.query.filter_by(reseller_id=user.id,state='requested').first():abort(409,'یک درخواست تسویه در انتظار بررسی دارید.')
                row=Settlement(reference=ref,reseller_id=user.id,amount=total,destination=destination)
                try:db.session.add(row);db.session.flush()
                except IntegrityError:db.session.rollback();abort(409,'یک درخواست تسویه در انتظار بررسی دارید.')
                for entry in entries:
                    changed=db.session.execute(update(Earning).where(Earning.id==entry.id,Earning.state=='available',Earning.offset_used==entry.offset_used).values(state='reserved',settlement_id=row.id)).rowcount
                    if changed!=1:db.session.rollback();abort(409,'موجودی تغییر کرده؛ دوباره تلاش کنید.')
                experience.notify(None,'Commission settlement requested',f'Representative #{user.id} · {total:,} Toman · settlement #{row.id}')
                alert('settlement:'+ref,f'درخواست تسویه نماینده #{user.id}\nمبلغ: {total:,} تومان\nدرخواست #{row.id} را از بخش پورسانت مدیریت بررسی کنید.')
                db.session.commit();flash('درخواست تسویه ثبت شد. این مبلغ تا بررسی مدیر رزرو است.','success')
            else:abort(400)
            return redirect(base+'/c/'+token+'/reseller/credit/'+('prices' if action=='price' else 'income')) if representative_credit.mode(user.id) else redirect(request.path)
        q=request.args.get('q','').strip()[:64]
        query=resellers.Order.query.filter_by(reseller_id=user.id)
        if q:query=query.filter(resellers.Order.username.contains(q,autoescape=True))
        rows=query.order_by(resellers.Order.id.desc()).paginate(page=max(1,request.args.get('page',1,type=int) or 1),per_page=12,error_out=False)
        children={u.id:u for u in User.query.filter_by(reseller_id=user.id)}
        valid_links={order.id:bool((link:=db.session.get(AccountLink,order.user_id)) and link.token_hash==hashlib.sha256(order.portal_token.encode()).hexdigest()) for order in rows.items}
        return render_template('commission_workspace.html',token=token,panel_path=panel_path,user=user,active=active(user.id),
             orders=rows,children=children,valid_links=valid_links,login_names={uid:(db.session.get(features.CustomerProfile,uid).login_username or u.username) if db.session.get(features.CustomerProfile,uid) else u.username for uid,u in children.items()},search=q,sales=Sale.query.filter_by(reseller_id=user.id).order_by(Sale.id.desc()).limit(20).all(),**common(user.id))
    @app.get(base+'/c/<token>/reseller/commission/settlements/<int:settlement_id>/receipt')
    def commission_customer_receipt(token,settlement_id):
        user=features.resolve_account(token);row=Settlement.query.filter_by(id=settlement_id,reseller_id=user.id).first_or_404();return private_image(row.receipt)
    @app.get(base+'/settings/commissions/settlements/<int:settlement_id>/receipt')
    @login_required
    def commission_admin_receipt(settlement_id):owner();return private_image((db.session.get(Settlement,settlement_id) or abort(404)).receipt)
    def detach(uid):
        Rate.query.filter_by(reseller_id=uid).delete();Policy.query.filter_by(reseller_id=uid).delete()
        for model in (Sale,Earning,Settlement):
            for row in model.query.filter_by(reseller_id=uid):row.reseller_id=-uid
        for model in (Sale,Earning):
            for row in model.query.filter_by(user_id=uid):row.user_id=-uid
    return SimpleNamespace(Policy=Policy,Rate=Rate,Sale=Sale,Earning=Earning,Settlement=Settlement,Refund=Refund,
         active=active,mode=mode,notify_manager=alert,claim_receipt=claim_receipt,Receipt=Receipt,Alert=Alert,deliver_alerts=deliver_alerts,customer_plan=customer_plan,customer_settings=customer_settings,snapshot_discount=snapshot_discount,
         book=book,release=release,cycle=cycle,finish_order=finish_order,approve=approve,detach=detach,sums=sums)
