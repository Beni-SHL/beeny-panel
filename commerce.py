"""Integer-Toman wallets, immutable invoices and configurable sales discounts."""
import json,re,secrets,math
from datetime import datetime,timedelta
from types import SimpleNamespace
from flask import request,abort,render_template,redirect,flash
from flask_login import current_user,login_required
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

def register(app,db,User,features,experience,panel_path):
    base=panel_path.rstrip('/')
    class Wallet(db.Model):
        __tablename__='customer_wallets'
        user_id=db.Column(db.Integer,primary_key=True)
        balance=db.Column(db.BigInteger,nullable=False,default=0)
    class Entry(db.Model):
        __tablename__='wallet_entries'
        id=db.Column(db.Integer,primary_key=True)
        user_id=db.Column(db.Integer,index=True,nullable=False)
        amount=db.Column(db.BigInteger,nullable=False)
        reason=db.Column(db.String(250),nullable=False)
        admin_id=db.Column(db.Integer)
        reference=db.Column(db.String(64),unique=True,nullable=False)
        created_at=db.Column(db.DateTime,default=datetime.utcnow,index=True)
    class Invoice(db.Model):
        __tablename__='sales_invoices'
        id=db.Column(db.Integer,primary_key=True)
        request_id=db.Column(db.Integer,nullable=False)
        payment_state=db.Column(db.String(20),nullable=False,default='paid')
        source_reference=db.Column(db.String(64),unique=True,nullable=False)
        user_id=db.Column(db.Integer,index=True,nullable=False)
        username=db.Column(db.String(100),nullable=False)
        seller_id=db.Column(db.Integer,index=True)
        amount=db.Column(db.BigInteger,nullable=False)
        cost=db.Column(db.BigInteger)
        commission=db.Column(db.BigInteger,nullable=False,default=0)
        snapshot=db.Column(db.Text,nullable=False)
        created_at=db.Column(db.DateTime,default=datetime.utcnow,index=True)
    class Coupon(db.Model):
        __tablename__='sales_coupons'
        code=db.Column(db.String(30),primary_key=True)
        percent=db.Column(db.Integer,nullable=False)
        limit=db.Column(db.Integer,nullable=False)
        used=db.Column(db.Integer,nullable=False,default=0)
        expires=db.Column(db.String(10),nullable=False)
        active=db.Column(db.Boolean,nullable=False,default=True)
    def record_invoice(row):
        if not row.billing_reference:row.billing_reference=secrets.token_hex(16)
        if Invoice.query.filter_by(source_reference=row.billing_reference).first():return
        user=db.session.get(User,row.user_id);plan=json.loads(row.plan);plan=dict(plan,payment_source=row.source)
        cost=''
        percent=int(features.get_setting('sales_commission_percent','0'))
        from app import commissions
        if plan.get('commission_reseller'):
            commissions.book(row.billing_reference,user,plan)
            db.session.add(Invoice(source_reference=row.billing_reference,request_id=row.id,user_id=user.id,username=user.username,
                  amount=plan['price'],cost=int(cost)*plan['quota'] if cost.isdigit() else None,
                  commission=plan['price']-plan['commission_base'],snapshot=json.dumps(plan,ensure_ascii=False)))
            return
        seller=user.owner_id if user else None
        from app import Admin
        owner=db.session.get(Admin,seller) if seller else None
        commission=plan['price']*percent//100 if owner and owner.role=='seller' else 0
        db.session.add(Invoice(source_reference=row.billing_reference,request_id=row.id,user_id=row.user_id,username=row.username,seller_id=seller,
                 amount=int(plan['price']),cost=int(cost)*int(plan['quota']) if cost.isdigit() else None,commission=commission,snapshot=json.dumps(plan,ensure_ascii=False)))
    def discount(plan,code):
        code=code.strip().upper()
        if code and not features.settings()['coupons_enabled']:raise ValueError('Discount codes are disabled.')
        from app import commissions
        commissions.snapshot_discount(plan,code)
        if not code:return plan
        row=db.session.get(Coupon,code)
        if not row or not row.active or row.expires<datetime.utcnow().date().isoformat():raise ValueError('کد تخفیف نامعتبر یا منقضی است.')
        changed=db.session.execute(update(Coupon).where(Coupon.code==code,Coupon.active.is_(True),Coupon.used<Coupon.limit).values(used=Coupon.used+1)).rowcount
        if changed!=1:raise ValueError('ظرفیت کد تخفیف تمام شده است.')
        result=dict(plan);result['original_price']=int(plan['price']);result['price']=max(1,int(plan['price'])*(100-row.percent)//100);result['coupon']=code
        return result
    def monthly_sales(query):
        from financial_reporting import report
        from app import sales_engine,commissions
        return report(db,query,Invoice,sales_engine.Receipt,commissions,features,datetime.utcnow())
    @app.route(base+'/settings/sales',methods=['GET','POST'])
    @login_required
    def sales_page():
        if request.method=='POST':abort(405)
        query=Invoice.query
        if current_user.role=='seller':query=query.filter_by(seller_id=current_user.id)
        rows=query.order_by(Invoice.id.desc()).limit(100).all()
        revenue=db.session.query(db.func.sum(Invoice.amount)).filter(Invoice.seller_id==current_user.id).scalar() if current_user.role=='seller' else db.session.query(db.func.sum(Invoice.amount)).scalar()
        refunded_refs=set()
        if current_user.role=='owner':
            from app import commissions
            refunded_refs={r.reference for r in commissions.Earning.query.filter_by(state='reversed')}
            revenue=(revenue or 0)-(db.session.query(db.func.sum(commissions.Refund.amount)).filter(commissions.Refund.earning_id.is_not(None)).scalar() or 0)
        monthly=monthly_sales(query)
        current_start=datetime.strptime(monthly[-1]['month'],'%Y-%m')
        from sqlalchemy import case
        safe_snapshot=case((db.func.json_valid(Invoice.snapshot)==1,Invoice.snapshot),else_='{}')
        plan_id=db.func.json_extract(safe_snapshot,'$.id')
        days=db.func.json_extract(safe_snapshot,'$.days');quota=db.func.json_extract(safe_snapshot,'$.quota');devices_count=db.func.json_extract(safe_snapshot,'$.devices')
        groups=query.with_entities(plan_id,days,quota,devices_count,db.func.count(Invoice.id),db.func.sum(Invoice.amount)).filter(Invoice.created_at>=current_start).group_by(plan_id,days,quota,devices_count).order_by(db.func.sum(Invoice.amount).desc()).limit(50).all()
        return render_template('sales.html',sales_groups=groups,monthly=monthly,rows=rows,refunded_refs=refunded_refs,revenue=revenue or 0,coupons=Coupon.query.order_by(Coupon.code).all() if current_user.role=='owner' else [],panel_path=panel_path,coupons_enabled=features.settings()['coupons_enabled'],cost=features.get_setting('sales_cost_per_gb',''),commission=features.get_setting('sales_commission_percent','0'))
    @app.post(base+'/settings/sales/coupon-visibility')
    @login_required
    def coupon_visibility():
        if current_user.role!='owner':abort(403)
        features.verify_csrf()
        features.set_setting('coupons_enabled','1' if request.form.get('enabled')=='1' else '0')
        db.session.commit()
        return redirect(base+'/settings/sales')

    @app.post(base+'/settings/sales/coupons')
    @login_required
    def create_coupon():
        code=request.form.get('code','').strip().upper();percent=request.form.get('percent',type=int);limit=request.form.get('limit',type=int);expires=request.form.get('expires','')
        if not re.fullmatch(r'[A-Z0-9_-]{3,30}',code) or percent is None or not 1<=percent<=99 or limit is None or not 1<=limit<=100000 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',expires):abort(400)
        try:date=datetime.strptime(expires,'%Y-%m-%d').date()
        except ValueError:abort(400)
        if date<datetime.utcnow().date() or db.session.get(Coupon,code):abort(400)
        db.session.add(Coupon(code=code,percent=percent,limit=limit,expires=expires));db.session.commit();return redirect(base+'/settings/sales')
    @app.post(base+'/settings/sales/coupons/<code>/disable')
    @login_required
    def disable_coupon(code):
        row=db.session.get(Coupon,code) or abort(404);row.active=False;db.session.commit();return redirect(base+'/settings/sales')
    @app.route(base+'/users/view/<int:user_id>/wallet',methods=['GET','POST'])
    @login_required
    def financial_adjustment(user_id):
        from removal_guard import claim
        claim(db,User,user_id)
        user=User.query.get_or_404(user_id)
        wallet=db.session.get(Wallet,user.id)
        if not wallet:wallet=Wallet(user_id=user.id,balance=0);db.session.add(wallet);db.session.commit()
        if request.method=='POST':
            amount=request.form.get('amount',type=int);reason=request.form.get('reason','').strip();reference=request.form.get('reference','')
            if amount is None or not 1<=abs(amount)<=1000000000 or not 1<=len(reason)<=250 or not re.fullmatch(r'[A-Za-z0-9_-]{32,64}',reference):abort(400)
            if Entry.query.filter_by(reference=reference).first():return redirect(base+'/users/view/'+str(user.id)+'/wallet')
            changed=db.session.execute(update(Wallet).where(Wallet.user_id==user.id,Wallet.balance+amount>=0,Wallet.balance+amount<=10000000000).values(balance=Wallet.balance+amount)).rowcount
            if changed!=1:abort(409,'Invalid resulting wallet balance.')
            db.session.add(Entry(user_id=user.id,amount=amount,reason=reason,reference=reference,admin_id=current_user.id))
            experience.notify(user.id,'موجودی کیف پول تغییر کرد',f'{amount:+,} تومان · {reason}')
            db.session.commit();return redirect(base+'/users/view/'+str(user.id)+'/wallet')
        return render_template('wallet.html',customer=False,user=user,wallet=wallet,entries=Entry.query.filter_by(user_id=user.id).order_by(Entry.id.desc()).limit(100).all(),reference=secrets.token_urlsafe(32),panel_path=panel_path)
    @app.route(base+'/c/<token>/wallet',methods=['GET','POST'])
    def customer_wallet(token):
        user=features.resolve_account(token);wallet=db.session.get(Wallet,user.id)
        if not wallet:wallet=Wallet(user_id=user.id,balance=0);db.session.add(wallet);db.session.commit()
        if request.method=='POST':
            features.verify_csrf()
            from removal_guard import claim
            claim(db,User,user.id)
            if request.form.get('action')=='topup':
                from customer_features import MAX_UPLOAD
                cfg=features.settings();amount=request.form.get('amount',type=int)
                reference=request.form.get('reference','')
                if not re.fullmatch(r'[a-f0-9]{32}',reference):abort(400,'درخواست معتبر نیست؛ صفحه را تازه کنید.')
                existing=features.RenewalRequest.query.filter_by(billing_reference=reference,user_id=user.id).first()
                if existing:return redirect(base+'/c/'+token+'/wallet')
                if amount is None or not 1000<=amount<=100000000:abort(400,'مبلغ شارژ باید بین ۱٬۰۰۰ و ۱۰۰٬۰۰۰٬۰۰۰ تومان باشد.')
                card=next((c for c in cfg['bank_cards'] if c['id']==request.form.get('card_id')),None)
                if not card:abort(400,'اطلاعات کارت بانکی معتبر نیست؛ با پشتیبانی تماس بگیرید.')
                if features.RenewalRequest.query.filter_by(user_id=user.id,status='pending').first():abort(409,'یک درخواست در انتظار بررسی دارید؛ نتیجه را از کیف پول پیگیری کنید.')
                if features.RenewalRequest.query.filter(features.RenewalRequest.user_id==user.id,features.RenewalRequest.created_at>=datetime.utcnow()-timedelta(days=1)).count()>=5:abort(429,'سقف درخواست‌های امروز تکمیل شده است.')
                receipt=request.files.get('receipt');name=request.form.get('name','').strip();contact=request.form.get('contact','').strip()
                if not receipt or not name or not contact:abort(400,'نام، راه ارتباطی و تصویر رسید را وارد کنید.')
                try:filename=features.store_image(receipt.stream.read(MAX_UPLOAD+1))
                except ValueError as error:abort(400,str(error))
                plan=dict(id='wallet-topup',title='شارژ کیف پول',price=amount,days=0,quota=0,devices=0,payment_card=dict(card))
                row=features.RenewalRequest(user_id=user.id,username=user.username,source='wallet_topup',billing_reference=reference,plan=json.dumps(plan,ensure_ascii=False),receipt=filename,name=name[:100],contact=contact[:120],note=request.form.get('note','')[:500])
                try:
                    db.session.add(row);db.session.flush()
                    from app import commissions
                    commissions.claim_receipt(filename,'renewal:'+row.billing_reference)
                    experience.notify(None,'Wallet top-up requested',f'{user.username}: {amount:,} Toman · request #{row.id}')
                    db.session.commit()
                except (IntegrityError,ValueError):
                    db.session.rollback();(features.storage/filename).unlink(missing_ok=True);abort(409,'رسید تکراری یا درخواست در انتظار بررسی است.')
                except Exception:
                    db.session.rollback();(features.storage/filename).unlink(missing_ok=True);raise
                flash('رسید شارژ ثبت شد. پس از تأیید واریز، مبلغ به کیف پول شما اضافه می‌شود.','success')
                return redirect(base+'/c/'+token+'/wallet')
            if user.status!='active':abort(403,'حساب محدود شده است؛ برای تمدید با مدیر تماس بگیرید.')
            cfg=features.settings();plan=next((dict(p) for p in cfg['plans'] if p['id']==request.form.get('plan_id')),None)
            if not plan:abort(400)
            from app import commissions
            try:plan=commissions.customer_plan(user,plan)
            except ValueError as error:abort(400,str(error))
            reference=request.form.get('reference','')
            if not re.fullmatch(r'[A-Za-z0-9_-]{32,64}',reference):abort(400)
            if Entry.query.filter_by(reference=reference).first():return redirect(base+'/c/'+token+'/wallet')
            if features.RenewalRequest.query.filter_by(user_id=user.id,status='pending').first():abort(409,'ابتدا درخواست در انتظار بررسی را پیگیری کنید.')
            try:plan=discount(plan,request.form.get('coupon',''))
            except ValueError as e:db.session.rollback();abort(400,str(e))
            changed=db.session.execute(update(Wallet).where(Wallet.user_id==user.id,Wallet.balance>=plan['price']).values(balance=Wallet.balance-plan['price'])).rowcount
            if changed!=1:db.session.rollback();abort(409,'موجودی کیف پول کافی نیست.')
            row=features.RenewalRequest(user_id=user.id,username=user.username,plan=json.dumps(plan,ensure_ascii=False),receipt='',source='wallet',email_state='skipped',telegram_state='skipped',status='pending')
            db.session.add(row);db.session.flush()
            db.session.add(Entry(user_id=user.id,amount=-plan['price'],reason=f'خرید سرویس، درخواست #{row.id}',reference=reference))
            failures=experience.approve_renewal(row)
            flash('خرید و تمدید انجام شد؛ تأیید بعضی نودها در حال پیگیری است.' if failures else 'خرید و تمدید با موفقیت انجام شد.','success')
            return redirect(base+'/c/'+token+'/wallet')
        return render_template('wallet.html',customer=True,user=user,token=token,wallet=wallet,entries=Entry.query.filter_by(user_id=user.id).order_by(Entry.id.desc()).limit(100).all(),plans=__import__('app').commissions.customer_settings(user,features.settings())['plans'],reference=secrets.token_urlsafe(32),topup_reference=secrets.token_hex(16),customer_settings=features.settings(),topups=features.RenewalRequest.query.filter_by(user_id=user.id,source='wallet_topup').order_by(features.RenewalRequest.id.desc()).limit(10).all(),has_pending=bool(features.RenewalRequest.query.filter_by(user_id=user.id,status='pending').first()),panel_path=panel_path)
    return SimpleNamespace(Wallet=Wallet,Entry=Entry,Invoice=Invoice,Coupon=Coupon,record_invoice=record_invoice,discount=discount)
