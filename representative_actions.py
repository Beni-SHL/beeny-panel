"""Representative delivery credentials and owner-reviewed sale cancellation.
No plaintext passwords are stored; archive and financial reversal are distinct.
"""
import base64,hashlib,json,secrets,math
from datetime import datetime
from functools import wraps
from types import SimpleNamespace
from cryptography.fernet import Fernet,InvalidToken
from flask import abort,flash,jsonify,redirect,request,session,send_file
from flask_login import current_user,login_required
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash,generate_password_hash

def register(app,db,User,features,experience,commerce,resellers,commissions,credit,panel_path):
    base=panel_path.rstrip('/')
    class Credential(db.Model):
        __tablename__='representative_delivery_credentials'
        user_id=db.Column(db.Integer,primary_key=True)
        reseller_id=db.Column(db.Integer,nullable=False,index=True)
        encrypted=db.Column(db.Text,nullable=False)
        password_digest=db.Column(db.String(64),nullable=False)
        created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
    class Cancellation(db.Model):
        __tablename__='representative_sale_cancellations'
        id=db.Column(db.Integer,primary_key=True)
        order_id=db.Column(db.Integer,nullable=False,unique=True)
        reseller_id=db.Column(db.Integer,nullable=False,index=True)
        user_id=db.Column(db.Integer,nullable=False,index=True)
        username=db.Column(db.String(100),nullable=False)
        reason=db.Column(db.String(500),nullable=False)
        state=db.Column(db.String(20),nullable=False,default='pending',index=True)
        kind=db.Column(db.String(20),nullable=False,default='refund')
        base_amount=db.Column(db.BigInteger,nullable=False)
        sale_amount=db.Column(db.BigInteger,nullable=False)
        refund_percent=db.Column(db.Integer,nullable=False,default=100)
        base_refund=db.Column(db.BigInteger)
        sale_refund=db.Column(db.BigInteger)
        admin_id=db.Column(db.Integer)
        review_note=db.Column(db.String(500),nullable=False,default='')
        customer_refund_reference=db.Column(db.String(100),nullable=True,unique=True)
        usage_at_review=db.Column(db.Float)
        created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
        reviewed_at=db.Column(db.DateTime)
        completed_at=db.Column(db.DateTime)
    def transactional(fn):
        @wraps(fn)
        def wrapper(*args,**kwargs):
            try:return fn(*args,**kwargs)
            except IntegrityError:
                db.session.rollback();abort(409,'درخواست هم‌زمان یا تکراری است؛ صفحه را تازه کنید.')
            except Exception:db.session.rollback();raise
        return wrapper
    def cipher():
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256((app.secret_key+'|representative-delivery-v1').encode()).digest()))
    def remember(user,uid,password):
        profile=db.session.get(features.CustomerProfile,user.id)
        if not profile:abort(409)
        row=db.session.get(Credential,user.id)
        if not row:row=Credential(user_id=user.id,reseller_id=uid);db.session.add(row)
        row.encrypted=cipher().encrypt(password.encode()).decode()
        row.password_digest=hashlib.sha256(profile.password_hash.encode()).hexdigest()
    def blocked(user):
        if not getattr(user,'id',None):return False
        return Cancellation.query.filter(Cancellation.user_id==user.id,Cancellation.state.in_(['applying','completed'])).first() is not None
    def in_review(user):
        return Cancellation.query.filter(Cancellation.user_id==user.id,Cancellation.state.in_(['pending','applying','completed'])).first() is not None
    def cancellation_policy():
        try:hours=int(features.get_setting('credit_cancel_max_hours','48'));usage=float(features.get_setting('credit_cancel_max_usage_gb','0.1'))
        except (TypeError,ValueError):hours=48;usage=0.1
        return dict(hours=max(0,min(87600,hours)),usage=usage if math.isfinite(usage) and 0<=usage<=1000000 else 0.1)
    def financial_guard(user):
        from app import balepay_orders
        if features.RenewalRequest.query.filter_by(user_id=user.id,status='pending').first():abort(409,'ابتدا درخواست پرداخت یا تمدید در انتظار بررسی را تعیین تکلیف کنید.')
        if balepay_orders.query.filter(balepay_orders.user_id==user.id,balepay_orders.status.in_(['pending','superseded','processing'])).first():abort(409,'ابتدا پرداخت آنلاین در جریان را تعیین تکلیف کنید؛ پرداخت دیرهنگام باید بررسی شود.')
        wallet=db.session.get(commerce.Wallet,user.id)
        if wallet and wallet.balance:abort(409,'حساب موجودی کیف پول دارد؛ مدیر باید ابتدا موجودی را تعیین تکلیف کند.')
    def scope(token,uid):
        rep=features.resolve_account(token);features.verify_csrf()
        if not credit.mode(rep.id):abort(403)
        child=User.query.filter_by(id=uid,reseller_id=rep.id).first_or_404()
        order=resellers.Order.query.filter_by(reseller_id=rep.id,user_id=uid).first_or_404()
        return rep,child,order
    @app.post(base+'/c/<token>/reseller/users/<int:uid>/delivery')
    @transactional
    def delivery(token,uid):
        rep,child,order=scope(token,uid)
        if order.state!='completed' or in_review(child):abort(409,'این حساب آماده تحویل نیست.')
        profile=db.session.get(features.CustomerProfile,uid) or abort(409)
        row=db.session.get(Credential,uid);password=None
        if row and row.reseller_id==rep.id and row.password_digest==hashlib.sha256((profile.password_hash or '').encode()).hexdigest():
            try:password=cipher().decrypt(row.encrypted.encode()).decode()
            except InvalidToken:pass
        if not password:
            if request.form.get('reset')!='1':
                return jsonify(reset_required=True,message='رمز قدیمی قابل بازیابی نیست. با تأیید شما، رمز ورود صفحه مشتری تعویض و متن آماده صادر می‌شود؛ کانفیگ VPN تغییر نمی‌کند.'),409
            password=secrets.token_urlsafe(18)
            profile.password_hash=generate_password_hash(password);profile.auth_version=secrets.token_hex(24)
            remember(child,rep.id,password)
            experience.notify(child.id,'رمز ورود صفحه حساب تغییر کرد','نماینده رمز ورود صفحه حساب شما را تعویض کرد. رمز جدید را از او دریافت کنید؛ فایل اتصال VPN تغییر نکرده است.')
        if not profile.password_hash or not check_password_hash(profile.password_hash,password):abort(409)
        from app import AccountLink
        link=db.session.get(AccountLink,uid)
        if not link or link.token_hash!=hashlib.sha256(order.portal_token.encode()).hexdigest():abort(409,'لینک مشتری تغییر کرده است؛ مدیر باید لینک تحویل را بررسی کند.')
        db.session.commit()
        en=session.get('customer_language','fa')=='en'
        url=request.host_url.rstrip('/')+base+'/c/'+order.portal_token
        text=(f'Hello 👋\nYour Beeny account is ready.\n\nProfile: {url}\nUsername: {profile.login_username or child.username}\nPassword: {password}\n\nView usage, download your configuration and renew from your private profile. Keep these details private.' if en else f'سلام 👋\nاکانت شما در بنی پنل آماده است.\n\nپروفایل: {url}\nنام کاربری: {profile.login_username or child.username}\nرمز ورود: {password}\n\nبرای مشاهده مصرف، دریافت کانفیگ و تمدید وارد پروفایل شوید. این اطلاعات خصوصی است.')
        response=jsonify(text=text);response.headers['Cache-Control']='private, no-store';return response
    @app.post(base+'/c/<token>/reseller/users/<int:uid>/cancel')
    @transactional
    def request_cancel(token,uid):
        rep,child,order=scope(token,uid)
        old=Cancellation.query.filter_by(order_id=order.id).first()
        if old:
            flash('درخواست این فروش قبلاً ثبت شده؛ نتیجه را در بخش لغو فروش ببینید.','warning')
            return redirect(base+'/c/'+token+'/reseller/credit/cancellations')
        memo=db.session.get(credit.Margin,order.id)
        if order.state!='completed' or not memo or memo.state!='completed':abort(409,'فقط فروش تحویل‌شده قابل درخواست لغو است؛ سفارش ناموفق را مدیر لغو می‌کند.')
        financial_guard(child)
        reason=request.form.get('reason','').strip()
        if not 3<=len(reason)<=500:abort(400,'دلیل لغو را بنویسید.')
        row=Cancellation(order_id=order.id,reseller_id=rep.id,user_id=uid,username=child.username,reason=reason,base_amount=memo.base_amount,sale_amount=memo.sale_amount)
        db.session.add(row);db.session.flush()
        experience.notify(None,'درخواست لغو فروش نماینده',f'{rep.username} · {child.username} · درخواست #{row.id}')
        db.session.commit();flash('درخواست لغو ثبت شد؛ تا تأیید مدیر هیچ اعتباری برنمی‌گردد.','success')
        return redirect(base+'/c/'+token+'/reseller/credit/cancellations')
    @transactional
    def finalize(row):
        if row.state=='completed':return True
        if row.state!='applying':return False
        child=db.session.get(User,row.user_id) or abort(409,'حساب بایگانی‌شونده پیدا نشد.')
        # Access is persistently denied even if another editor sets status active.
        errors=experience.sync_access(child)
        if errors:return False
        # Serialize final money changes with concurrent node/worker/admin actions.
        claimed=db.session.execute(update(Cancellation).where(Cancellation.id==row.id,Cancellation.state=='applying').values(state='finalizing')).rowcount
        if claimed!=1:db.session.rollback();return False
        db.session.refresh(child);financial_guard(child)
        child.status='disabled';child.customer_paused=True;child.pause_sync_pending=False
        order=db.session.get(resellers.Order,row.order_id) or abort(409)
        memo=db.session.get(credit.Margin,order.id) or abort(409)
        if row.kind=='refund':
            if order.state!='completed' or memo.state!='completed':abort(409,'فروش قبلاً اصلاح شده است.')
            credit.cancel(order,amount=row.base_refund if row.base_refund is not None else row.base_amount,sale_refund=row.sale_refund if row.sale_refund is not None else row.sale_amount)
            order.state='cancelled';order.error='لغو فروش با تأیید مدیر؛ حساب بایگانی شد.'
            # Do not change order.updated_at: retain the original fulfillment date.
        else:order.state='archived'
        db.session.get(Cancellation,row.id).state='completed'
        db.session.get(Cancellation,row.id).completed_at=datetime.utcnow()
        credential=db.session.get(Credential,child.id)
        if credential:db.session.delete(credential)
        experience.notify(row.reseller_id,'لغو فروش تأیید شد' if row.kind=='refund' else 'حساب بایگانی شد',f'{child.username} · '+(('بهای پایه برگشت داده شد و خالص سود فروش اولیه صفر شد؛ پورسانت تمدیدهای قبلی مستقل باقی ماند.' if row.refund_percent==100 else f'لغو با بازپرداخت {row.refund_percent}٪ انجام شد؛ بهای پایه و سود فروش متناسب اصلاح شدند. پورسانت تمدیدهای قبلی مستقل است.') if row.kind=='refund' else 'دسترسی بسته شد؛ بدهی و اعتبار فروش تغییر نکرد.'))
        experience.notify(child.id,'حساب بسته شد','این حساب با درخواست نماینده بسته شده است. برای پیگیری با پشتیبانی تماس بگیرید.')
        db.session.commit();credit.sync_children(row.reseller_id);return True
    @app.post(base+'/settings/representative-credit/cancellations/<int:cid>/review')
    @login_required
    @transactional
    def review_cancel(cid):
        if current_user.role!='owner':abort(403)
        features.verify_csrf();row=db.session.get(Cancellation,cid) or abort(404)
        if row.state=='completed':return redirect(base+'/settings/representative-credit?tab=cancellations')
        action=request.form.get('action');note=request.form.get('review_note','').strip()[:500]
        if action=='reject':
            changed=db.session.execute(update(Cancellation).where(Cancellation.id==cid,Cancellation.state=='pending').values(state='rejected',admin_id=current_user.id,review_note=note,reviewed_at=datetime.utcnow())).rowcount
            if changed!=1:abort(409,'فقط درخواست بررسی‌نشده قابل رد است.')
            experience.notify(row.reseller_id,'درخواست لغو فروش رد شد',row.username+' · '+note)
            db.session.commit()
        elif action=='approve':
            if row.state not in {'pending','applying'}:abort(409,'درخواست لغو در این وضعیت قابل تأیید نیست.')
            if row.state=='pending':
                child=db.session.get(User,row.user_id) or abort(409);financial_guard(child)
                percentage=request.form.get('refund_percent',100,type=int)
                if percentage is None or not 1<=percentage<=100:abort(400,'درصد بازپرداخت باید بین ۱ و ۱۰۰ باشد.')
                base_refund=row.base_amount*percentage//100;sale_refund=row.sale_amount*percentage//100
                if base_refund<1:abort(400,'مبلغ برگشت بهای پایه کمتر از یک تومان است.')
                order=db.session.get(resellers.Order,row.order_id) or abort(409)
                policy=cancellation_policy()
                outside=(datetime.utcnow()-order.created_at).total_seconds()>policy['hours']*3600 or (child.traffic_usage or 0)>policy['usage']
                if outside and (request.form.get('override')!='1' or len(note)<3):abort(409,'این فروش خارج از مهلت یا سقف مصرف لغو است؛ تأیید استثنا و دلیل بررسی مدیر را ثبت کنید.')
                transfer=request.form.get('customer_refund_reference','').strip()
                if not 3<=len(transfer)<=100:abort(400,'مرجع بازپرداخت وجه مشتری را ثبت کنید؛ پنل انتقال بانکی انجام نمی‌دهد.')
                if Cancellation.query.filter(Cancellation.id!=cid,Cancellation.customer_refund_reference==transfer,Cancellation.state.in_(['applying','completed'])).first():abort(409,'مرجع بازپرداخت تکراری است.')
                changed=db.session.execute(update(Cancellation).where(Cancellation.id==cid,Cancellation.state=='pending').values(state='applying',admin_id=current_user.id,review_note=note,customer_refund_reference=transfer,refund_percent=percentage,base_refund=base_refund,sale_refund=sale_refund,usage_at_review=child.traffic_usage or 0,reviewed_at=datetime.utcnow())).rowcount
                if changed!=1:abort(409)
                child.status='disabled';child.customer_paused=True;child.pause_sync_pending=True
                db.session.commit();row=db.session.get(Cancellation,cid)
            done=finalize(row)
            flash('لغو انجام شد؛ بهای پایه و سود فروش طبق درصد تأییدشده اصلاح شدند.' if done else 'دسترسی در حال بسته‌شدن روی نودهاست؛ برگشت مالی بعد از تأیید همه نودها انجام می‌شود.','success' if done else 'warning')
        else:abort(400)
        return redirect(base+'/settings/representative-credit?tab=cancellations')
    @app.post(base+'/c/<token>/reseller/users/<int:uid>/archive')
    @transactional
    def archive(token,uid):
        rep,child,order=scope(token,uid)
        if in_review(child):abort(409,'درخواست لغو این حساب در جریان است یا حساب بایگانی شده است.')
        if order.state!='completed':abort(409)
        financial_guard(child);memo=db.session.get(credit.Margin,order.id) or abort(409)
        row=Cancellation.query.filter_by(order_id=order.id).first()
        if row:
            if row.state!='rejected':abort(409)
            row.review_note='درخواست لغو رد شده بود؛ اکنون بایگانی بدون برگشت اعتبار. '+row.review_note
            row.kind='archive';row.state='applying'
        else:
            row=Cancellation(order_id=order.id,reseller_id=rep.id,user_id=uid,username=child.username,reason='بستن حساب بدون برگشت اعتبار',kind='archive',state='applying',base_amount=memo.base_amount,sale_amount=memo.sale_amount)
            db.session.add(row)
        child.status='disabled';child.customer_paused=True;child.pause_sync_pending=True;db.session.commit()
        done=finalize(row);flash('حساب بایگانی شد؛ بدهی و اعتبار تغییر نکرد.' if done else 'حساب در حال بسته‌شدن است؛ تأیید نودها در صف است.','success' if done else 'warning')
        return redirect(base+'/c/'+token+'/reseller/credit/accounts')
    @app.after_request
    def private_responses(response):
        if request.endpoint=='delivery':
            response.headers['Cache-Control']='private, no-store'
            response.headers['Referrer-Policy']='no-referrer'
        return response
    @app.context_processor
    def context():
        labels={'pending':('در انتظار بررسی','Awaiting review'),'applying':('در انتظار تأیید نود','Awaiting node confirmation'),'completed':('تکمیل‌شده','Completed'),'rejected':('ردشده','Rejected'),'requested':('درخواست‌شده','Requested'),'paid':('پرداخت‌شده','Paid'),'available':('قابل استفاده','Available'),'held':('در انتظار تأیید','Held'),'reserved':('رزروشده','Reserved'),'settled':('تسویه‌شده','Settled'),'reversed':('برگشت‌خورده','Reversed'),'working':('در حال ساخت','Provisioning'),'cancelled':('لغوشده','Cancelled'),'archived':('بایگانی‌شده','Archived'),'issue':('صدور اعتبار','Credit issued'),'payment':('پرداخت بدهی','Debt payment'),'offset':('تهاتر درآمد','Income offset'),'wallet_payment':('پرداخت از کیف پول','Wallet payment'),'cancel':('برگشت بهای پایه','Base reversal'),'limit':('تغییر سقف اعتبار','Credit limit'),'lock':('لاک ساخت','Locked'),'unlock':('رفع لاک','Unlocked'),'suspend':('تعلیق اشتراک‌ها','Suspended'),'restore':('رفع تعلیق','Restored'),'superseded':('جایگزین‌شده؛ نیاز به بررسی','Superseded'),'processing':('در حال تأیید','Verifying'),'failed':('ناموفق','Failed'),'expired':('منقضی‌شده','Expired')}
        def label(state,en=False):return labels.get(state,(state,state))[1 if en else 0]
        def page_url(page,key='page'):
            from urllib.parse import urlencode
            args=request.args.to_dict();args[key]=page
            return request.path+'?'+urlencode(args)
        return dict(rep_state=label,rep_page_url=page_url,representative_account_closed=blocked,representative_account_closing=in_review,rep_cancellation_policy=cancellation_policy)
    @app.get(base+'/c/<token>/reseller/credit/payments/<int:rid>/receipt')
    def debt_receipt(token,rid):
        user=features.resolve_account(token)
        row=features.RenewalRequest.query.filter_by(id=rid,user_id=user.id,source='reseller_debt').first_or_404()
        if not row.receipt:abort(404)
        from pathlib import Path
        name=Path(row.receipt)
        if name.name!=row.receipt or name.suffix not in {'.jpg','.webp','.png'}:abort(404)
        path=features.storage/name
        if not path.is_file():abort(404)
        response=send_file(path,mimetype='image/webp' if name.suffix=='.webp' else 'image/jpeg')
        response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff';return response
    @app.post(base+'/settings/representative-credit/sales/<int:sid>/review')
    @login_required
    @transactional
    def legacy_sale_review(sid):
        if current_user.role!='owner':abort(403)
        app.view_functions['commission_manage'](sale_id=sid)
        return redirect(base+'/settings/representative-credit?tab=orders')
    @app.post(base+'/settings/representative-credit/receipts/<int:rid>/review')
    @login_required
    @transactional
    def debt_review(rid):
        if current_user.role!='owner':abort(403)
        row=db.session.get(features.RenewalRequest,rid) or abort(404)
        if row.source!='reseller_debt':abort(404)
        app.view_functions['review_renewal'](request_id=rid)
        return redirect(base+'/settings/representative-credit?tab=receipts')
    @app.before_request
    def guards():
        # Remove old hard-delete semantics only for credit representatives.
        if request.endpoint=='reseller_delete':
            rep=features.resolve_account(request.view_args['token'])
            if credit.mode(rep.id):abort(409,'از بایگانی یا درخواست لغو فروش استفاده کنید؛ حذف مستقیم حساب اعتباری مجاز نیست.')
        if request.method=='POST' and request.view_args and 'token' in request.view_args and request.endpoint in {'submit_renewal','customer_wallet','balepay_start','customer_pause'}:
            user=features.resolve_account(request.view_args['token'])
            if in_review(user):abort(409,'این حساب در حال لغو یا بایگانی است؛ پرداخت جدید و فعال‌سازی مجاز نیست.')
    def cycle():
        for row in Cancellation.query.filter_by(state='applying').order_by(Cancellation.id).limit(10):
            try:finalize(row)
            except Exception:db.session.rollback();app.logger.warning('Representative cancellation %s awaits reconciliation.',row.id)
    def detach(uid):
        if Cancellation.query.filter(Cancellation.user_id==uid,Cancellation.state.in_(['pending','applying'])).first():abort(409,'درخواست لغو فروش در جریان است؛ حساب را حذف نکنید.')
        row=db.session.get(Credential,uid)
        if row:db.session.delete(row)
    return SimpleNamespace(Credential=Credential,Cancellation=Cancellation,remember=remember,blocked=blocked,in_review=in_review,cycle=cycle,detach=detach)
