"""Revolving representative credit; principal debt and renewal earnings remain separate.
Payment approval reuses RenewalRequest/BaleOrder, not an independent checkout ledger.
All monetary amounts are integer Toman. Existing representatives are opt-in only.
"""
import hashlib,json,re,secrets,hmac,csv,io,math
from datetime import datetime,timedelta
from types import SimpleNamespace
from functools import wraps
from flask import abort,flash,redirect,render_template,request,session,Response
from flask_login import current_user,login_required
from sqlalchemy import update,CheckConstraint
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash,check_password_hash

def register(app,db,User,Node,UserNode,AccountLink,features,experience,commerce,resellers,commissions,panel_path):
    base=panel_path.rstrip('/')
    def transactional(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            try:return fn(*args,**kwargs)
            except Exception:
                db.session.rollback()
                raise
        return wrapped
    class Account(db.Model):
        __tablename__='representative_credit_accounts'
        __table_args__=(CheckConstraint('debt >= 0 AND credit_limit >= debt',name='credit_debt_bounds'),)
        reseller_id=db.Column(db.Integer,primary_key=True)
        enabled=db.Column(db.Boolean,nullable=False,default=False)
        credit_limit=db.Column(db.BigInteger,nullable=False,default=0)
        debt=db.Column(db.BigInteger,nullable=False,default=0)
        locked=db.Column(db.Boolean,nullable=False,default=False)
        suspended=db.Column(db.Boolean,nullable=False,default=False)
        locked_reason=db.Column(db.String(20),nullable=False,default='financial')
        suspended_reason=db.Column(db.String(20),nullable=False,default='financial')
        portal_token=db.Column(db.String(43))
    class Entry(db.Model):
        __tablename__='representative_credit_entries'
        id=db.Column(db.Integer,primary_key=True)
        reference=db.Column(db.String(80),nullable=False,unique=True)
        reseller_id=db.Column(db.Integer,nullable=False,index=True)
        kind=db.Column(db.String(30),nullable=False)
        amount=db.Column(db.BigInteger,nullable=False)
        debt_after=db.Column(db.BigInteger,nullable=False)
        details=db.Column(db.Text,nullable=False,default='{}')
        created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
    class Margin(db.Model):
        __tablename__='representative_credit_margins'
        order_id=db.Column(db.Integer,primary_key=True)
        reseller_id=db.Column(db.Integer,nullable=False,index=True)
        user_id=db.Column(db.Integer,nullable=False,index=True)
        base_amount=db.Column(db.BigInteger,nullable=False)
        sale_amount=db.Column(db.BigInteger,nullable=False)
        state=db.Column(db.String(20),nullable=False,default='pending')
    def account(uid):return db.session.get(Account,uid)
    def mode(uid):
        row=account(uid);return bool(row and row.enabled)
    def suspended(user):
        uid=getattr(user,'reseller_id',None)
        row=account(uid) if uid else None
        return bool(row and row.suspended)
    def suspension_reason(user):
        uid=getattr(user,'reseller_id',None);row=account(uid) if uid else None
        return row.suspended_reason if row and row.suspended else ''
    def allow_create(uid):
        row=account(uid)
        user=db.session.get(User,uid)
        return bool(user and not user.removal_pending and row and row.enabled and not row.locked and not row.suspended and commissions.active(uid))
    def journal(uid,kind,amount,reference,details=None):
        row=account(uid)
        db.session.refresh(row)
        metadata=dict(details or {});metadata['credit_limit']=row.credit_limit
        db.session.add(Entry(reseller_id=uid,kind=kind,amount=amount,reference=reference,debt_after=row.debt,details=json.dumps(metadata,ensure_ascii=False)))
    def children_pending(uid,blocked):
        for child in User.query.filter_by(reseller_id=uid):
            child.pause_sync_pending=True
            experience.notify(child.id,'اشتراک موقتاً متوقف شد' if blocked else 'محدودیت نمایندگی برداشته شد',
                ('اشتراک شما به علت پرداخت نکردن بدهی نماینده قطع شده است. برای پیگیری با پشتیبانی تماس بگیرید.' if account(uid).suspended_reason=='financial' else 'اشتراک‌های این نماینده توسط مدیر تعلیق شده‌اند. برای پیگیری با پشتیبانی تماس بگیرید.') if blocked else 'بدهی یا محدودیت نماینده تعیین تکلیف شد؛ اتصال با رعایت اعتبار و وضعیت حساب شما بازگردانده می‌شود.')
    def sync_children(uid):
        failures=0
        for child in User.query.filter_by(reseller_id=uid).limit(20):
            try:failures+=bool(experience.sync_access(child))
            except Exception:
                db.session.rollback();child=db.session.get(User,child.id);child.pause_sync_pending=True;db.session.commit();failures+=1
        return failures
    def on_provision(order,confirmed=False):
        memo=db.session.get(Margin,order.id)
        user=db.session.get(User,order.user_id)
        if memo and order.state=='completed' and user and (confirmed or not user.pause_sync_pending) and not suspended(user):
            memo.state='completed'
            rep=db.session.get(User,order.reseller_id)
            commissions.notify_manager('rep-account:'+order.reference,f'✅ اکانت جدید نمایندگی ساخته شد\nنماینده: {rep.username if rep else order.reseller_id}\nنام اکانت: {order.username}')
    @transactional
    def cancel(order,amount=None,sale_refund=None):
        memo=db.session.get(Margin,order.id)
        if not memo or memo.state not in {'pending','completed'}:abort(409,'برگشت مالی این فروش قبلاً انجام شده یا وضعیتش معتبر نیست.')
        refund=memo.base_amount if amount is None else amount
        retail=memo.sale_amount if sale_refund is None else sale_refund
        if type(refund) is not int or not 1<=refund<=memo.base_amount or type(retail) is not int or not refund<=retail<=memo.sale_amount:abort(400,'مبلغ برگشت معتبر نیست.')
        a=account(order.reseller_id) or abort(409)
        old=a.debt;reduction=min(old,refund);excess=refund-reduction
        changed=db.session.execute(update(Account).where(Account.reseller_id==order.reseller_id,Account.debt==old).values(debt=old-reduction)).rowcount
        if changed!=1:abort(409,'Debt changed; reconciliation required')
        if excess:
            wallet=db.session.get(commerce.Wallet,order.reseller_id)
            if not wallet:wallet=commerce.Wallet(user_id=order.reseller_id,balance=0);db.session.add(wallet);db.session.flush()
            changed=db.session.execute(update(commerce.Wallet).where(commerce.Wallet.user_id==order.reseller_id,commerce.Wallet.balance+excess<=10000000000).values(balance=commerce.Wallet.balance+excess)).rowcount
            if changed!=1:abort(409)
            db.session.add(commerce.Entry(user_id=order.reseller_id,amount=excess,reason='اعتبار نقدی سفارش لغوشده پس از بازپرداخت بدهی',reference='credit-refund:'+order.reference))
        was_delivered=memo.state=='completed'
        memo.state=('refunded' if refund==memo.base_amount and retail==memo.sale_amount else 'partially_refunded') if was_delivered else 'cancelled'
        journal(order.reseller_id,'cancel',-reduction,'credit-cancel:'+order.reference,{'wallet_credit':excess,'base_amount':refund,'sale_amount':retail,'original_base':memo.base_amount,'original_sale':memo.sale_amount,'delivered':was_delivered,'order_id':order.id})
        release_financial(account(order.reseller_id))
    def release_financial(a):
        if a.debt!=0:return
        if a.locked and a.locked_reason=='financial':a.locked=False
        if a.suspended and a.suspended_reason=='financial':a.suspended=False;children_pending(a.reseller_id,False)
    @transactional
    def approve_debt(row):
        plan=json.loads(row.plan);amount=plan.get('price');uid=row.user_id
        if type(amount) is not int or not 1<=amount<=100000000:abort(400,'Invalid debt payment')
        a=account(uid) or abort(409,'Representative credit account missing')
        old_debt=a.debt;paid=min(old_debt,amount)
        changed=db.session.execute(update(Account).where(Account.reseller_id==uid,Account.debt==old_debt).values(debt=old_debt-paid)).rowcount
        if changed!=1:abort(409,'Debt changed; retry verification')
        journal(uid,'payment',-paid,'debt:'+row.billing_reference,{'request_id':row.id,'paid':amount,'excess':amount-paid,'source':plan.get('payment_source','receipt')})
        excess=amount-paid
        if excess:
            wallet=db.session.get(commerce.Wallet,uid)
            if not wallet:wallet=commerce.Wallet(user_id=uid,balance=0);db.session.add(wallet);db.session.flush()
            changed=db.session.execute(update(commerce.Wallet).where(commerce.Wallet.user_id==uid,commerce.Wallet.balance+excess<=10000000000).values(balance=commerce.Wallet.balance+excess)).rowcount
            if changed!=1:abort(409,'Wallet overflow; reconcile payment')
            db.session.add(commerce.Entry(user_id=uid,amount=excess,reason='اضافه پرداخت بدهی نمایندگی',reference='debt-extra:'+row.billing_reference))
        a=account(uid)
        release_financial(a)
        experience.notify(uid,'پرداخت بدهی تأیید شد',f'{paid:,} تومان از بدهی کم شد و اعتبار فروش برگشت داده شد.'+(f' اضافه پرداخت {excess:,} تومان به کیف پول نقدی شما رفت.' if excess else ''))
        experience.notify(None,'Representative debt paid',f'Representative #{uid}: {paid:,} Toman principal repaid; excess {excess:,}.')
    @transactional
    def offset(uid,amount,reference):
        old_entry=Entry.query.filter_by(reference='debt-offset:'+reference).first()
        if old_entry:
            if old_entry.reseller_id!=uid:abort(404)
            return
        a=account(uid) or abort(404)
        entries=commissions.Earning.query.filter_by(reseller_id=uid,state='available').order_by(commissions.Earning.id).all()
        total=sum(e.amount-e.offset_used for e in entries)
        if type(amount) is not int or amount<1 or amount>a.debt or amount>total:abort(409,'Available income or debt is insufficient')
        changed=db.session.execute(update(Account).where(Account.reseller_id==uid,Account.debt>=amount).values(debt=Account.debt-amount)).rowcount
        if changed!=1:abort(409)
        remaining=amount
        for earning in entries:
            old=earning.offset_used;take=min(remaining,max(0,earning.amount-old))
            if not take:continue
            changed=db.session.execute(update(commissions.Earning).where(commissions.Earning.id==earning.id,commissions.Earning.state=='available',commissions.Earning.offset_used==old).values(offset_used=old+take)).rowcount
            if changed!=1:db.session.rollback();abort(409,'Income changed; retry')
            remaining-=take
            if not remaining:break
        if remaining:db.session.rollback();abort(409)
        journal(uid,'offset',-amount,'debt-offset:'+reference)
        a=account(uid)
        release_financial(a)
        experience.notify(uid,'بدهی از درآمد تمدید پرداخت شد',f'{amount:,} تومان از درآمد قابل برداشت برای کاهش بدهی استفاده شد.')
    @transactional
    def cash_offset(uid,amount,reference):
        existing=Entry.query.filter_by(reference='debt-wallet:'+reference).first()
        if existing:
            if existing.reseller_id!=uid:abort(404)
            return
        a=account(uid) or abort(404)
        if type(amount) is not int or not 1<=amount<=a.debt:abort(400)
        changed=db.session.execute(update(commerce.Wallet).where(commerce.Wallet.user_id==uid,commerce.Wallet.balance>=amount).values(balance=commerce.Wallet.balance-amount)).rowcount
        if changed!=1:db.session.rollback();abort(409,'Cash wallet balance insufficient')
        changed=db.session.execute(update(Account).where(Account.reseller_id==uid,Account.debt>=amount).values(debt=Account.debt-amount)).rowcount
        if changed!=1:db.session.rollback();abort(409,'Debt changed; retry')
        db.session.add(commerce.Entry(user_id=uid,amount=-amount,reason='پرداخت بدهی از کیف پول نقدی',reference='debt-wallet:'+reference))
        journal(uid,'wallet_payment',-amount,'debt-wallet:'+reference)
        release_financial(account(uid))
    def payment_plan(uid,amount):
        a=account(uid) or abort(404)
        if not a.enabled:abort(403,'Credit model not enabled')
        if type(amount) is not int or not 1<=amount<=min(a.debt,100000000):abort(400,'Amount must not exceed current debt')
        return dict(id='reseller-debt',kind='reseller_debt',title='پرداخت بدهی نمایندگی',price=amount,days=0,quota=0,devices=0)
    def create(user):
        uid=user.id
        if not allow_create(uid):abort(403,'ساخت حساب برای این نماینده متوقف است.')
        ref=request.form.get('reference','')
        if not re.fullmatch('[a-f0-9]{32}',ref):abort(400)
        old=resellers.Order.query.filter_by(reference=ref).first()
        if old:
            if old.reseller_id!=uid:abort(409)
            return
        from app import representative_catalog
        if request.form.get('plan_id')=='custom':
            try:plan=representative_catalog.custom_quote(uid,request.form.get('custom_days'),request.form.get('custom_quota'),request.form.get('custom_devices'))
            except ValueError as error:abort(400,str(error))
        else:plan=next((dict(p) for p in commissions.customer_settings(SimpleNamespace(reseller_id=uid),features.settings())['plans'] if p['id']==request.form.get('plan_id')),None)
        if not plan:abort(400,'Plan not available')
        username=request.form.get('username','').strip();password=request.form.get('password','') or secrets.token_urlsafe(18);nid=request.form.get('node_id',type=int)
        if not re.fullmatch('[A-Za-z0-9_-][A-Za-z0-9_.-]{2,63}',username) or not 12<=len(password)<=256:abort(400,'Username or password invalid')
        if not db.session.get(resellers.Grant,(uid,nid)) or not db.session.get(Node,nid):abort(403)
        from app import devices
        if User.query.filter_by(username=username).first() or db.session.get(devices.RetiredUsername,username):abort(409,'Username already used')
        price=plan['commission_base'];plan['credit_sale']=True
        changed=db.session.execute(update(Account).where(Account.reseller_id==uid,Account.enabled.is_(True),Account.locked.is_(False),Account.suspended.is_(False),Account.debt+price<=Account.credit_limit).values(debt=Account.debt+price)).rowcount
        if changed!=1:db.session.rollback();abort(409,'اعتبار قابل استفاده کافی نیست؛ بدهی را پرداخت کنید.')
        token_new=secrets.token_urlsafe(32)
        child=User(username=username,reseller_id=uid,protocol='openvpn',expire_date=(datetime.utcnow().date()+timedelta(days=plan['days'])).isoformat(),traffic_limit=plan['quota'],max_devices=plan['devices'],quota_mode=plan.get('quota_mode','metered'),throttle_down_kbps=plan.get('throttle_down_kbps',2000),throttle_up_kbps=plan.get('throttle_up_kbps',2000),status='disabled',customer_paused=True)
        db.session.add(child);db.session.flush()
        db.session.add(UserNode(user_id=child.id,node_id=nid))
        db.session.add(AccountLink(user_id=child.id,token_hash=hashlib.sha256(token_new.encode()).hexdigest()))
        db.session.add(features.CustomerProfile(user_id=child.id,login_username=username,password_hash=generate_password_hash(password),auth_version=secrets.token_hex(24)))
        order=resellers.Order(reference=ref,reseller_id=uid,user_id=child.id,node_id=nid,username=username,amount=price,snapshot=json.dumps(plan,ensure_ascii=False),portal_token=token_new)
        db.session.add(order);db.session.flush()
        from app import representative_actions
        representative_actions.remember(child,uid,password)
        db.session.add(Margin(order_id=order.id,reseller_id=uid,user_id=child.id,base_amount=price,sale_amount=plan['price']))
        journal(uid,'issue',price,'credit-issue:'+ref,{'order_id':order.id,'sale_price':plan['price']})
        db.session.commit();resellers.provision(order)
        flash('حساب تحویل شد.' if order.state=='completed' else 'اعتبار رزرو شد؛ ساخت نود در انتظار تکمیل است و دوباره کسر نمی‌شود.','success' if order.state=='completed' else 'warning')
    @app.context_processor
    def context():return dict(representative_credit_mode=mode,representative_suspended=suspended,representative_suspension_reason=suspension_reason)
    class Statement(db.Model):
        __tablename__='representative_credit_statements'
        id=db.Column(db.Integer,primary_key=True)
        reference=db.Column(db.String(32),nullable=False,unique=True)
        reseller_id=db.Column(db.Integer,nullable=False,index=True)
        payload=db.Column(db.Text,nullable=False)
        created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
    def report(uid):
        today=datetime.utcnow().date();period=request.args.get('period','month')
        start=today.replace(day=1) if period=='month' else today-timedelta(days=today.weekday()) if period=='week' else today if period=='day' else today.replace(month=1,day=1) if period=='year' else None
        end=today+timedelta(days=1)
        if start is None:
            try:start=datetime.strptime(request.args.get('from',''),'%Y-%m-%d').date();end=datetime.strptime(request.args.get('to',''),'%Y-%m-%d').date()+timedelta(days=1)
            except ValueError:abort(400,'Invalid report period')
        if start>=end or (end-start).days>3660:abort(400)
        begin=datetime.combine(start,datetime.min.time());finish=datetime.combine(end,datetime.min.time())
        entries=Entry.query.filter(Entry.reseller_id==uid,Entry.created_at>=begin,Entry.created_at<finish).order_by(Entry.id).all()
        margin_rows=db.session.query(Margin,resellers.Order).join(resellers.Order,Margin.order_id==resellers.Order.id).filter(Margin.reseller_id==uid,Margin.state.in_(['completed','refunded','partially_refunded']),resellers.Order.updated_at>=begin,resellers.Order.updated_at<finish).all()
        margins=[m for m,o in margin_rows];order_map={m.order_id:o for m,o in margin_rows}
        earnings=commissions.Earning.query.filter(commissions.Earning.reseller_id==uid,commissions.Earning.created_at>=begin,commissions.Earning.created_at<finish).order_by(commissions.Earning.id).all()
        refunds=commissions.Refund.query.join(commissions.Earning,commissions.Refund.earning_id==commissions.Earning.id).filter(commissions.Earning.reseller_id==uid,commissions.Refund.created_at>=begin,commissions.Refund.created_at<finish).all()
        reversed_income=sum(db.session.get(commissions.Earning,r.earning_id).amount for r in refunds)
        payouts=commissions.Settlement.query.filter(commissions.Settlement.reseller_id==uid,commissions.Settlement.state=='paid',commissions.Settlement.paid_at>=begin,commissions.Settlement.paid_at<finish).all()
        reversals=[json.loads(e.details) for e in entries if e.kind=='cancel' and json.loads(e.details).get('delivered')]
        reversed_margin=sum(e['sale_amount']-e['base_amount'] for e in reversals)
        a=account(uid);db.session.refresh(a)
        opening=Entry.query.filter(Entry.reseller_id==uid,Entry.created_at<begin).order_by(Entry.created_at.desc(),Entry.id.desc()).first()
        closing=Entry.query.filter(Entry.reseller_id==uid,Entry.created_at<finish).order_by(Entry.created_at.desc(),Entry.id.desc()).first()
        return dict(opening_debt=opening.debt_after if opening else 0,closing_debt=closing.debt_after if closing else 0,period=period,start=start.isoformat(),end=(end-timedelta(days=1)).isoformat(),timezone='UTC',issued_at=datetime.utcnow().isoformat(),username=(db.session.get(User,uid).username if db.session.get(User,uid) else str(uid)),initial_orders=[dict(order_id=m.order_id,username=order_map[m.order_id].username,base=m.base_amount,retail=m.sale_amount,margin=m.sale_amount-m.base_amount,markup_percent=round((m.sale_amount-m.base_amount)*100/m.base_amount,2),fulfilled_at=order_map[m.order_id].updated_at.isoformat()) for m in margins],initial_count=len(margins),cash_received=sum(json.loads(e.details).get('paid',-e.amount) for e in entries if e.kind=='payment'),overpayment=sum(json.loads(e.details).get('excess',0) for e in entries if e.kind=='payment'),initial_sales=sum(m.sale_amount for m in margins),initial_base=sum(m.base_amount for m in margins),initial_margin=sum(m.sale_amount-m.base_amount for m in margins)-reversed_margin,initial_refunds=sum(e['sale_amount'] for e in reversals),renewal_margin=sum(max(0,e.amount) for e in earnings)-reversed_income,commission_refunds=reversed_income,renewal_held=sum(e.amount for e in earnings if e.state=='held'),debt_collected=-sum(e.amount for e in entries if e.kind=='payment'),offset=-sum(e.amount for e in entries if e.kind=='offset'),wallet_applied=-sum(e.amount for e in entries if e.kind=='wallet_payment'),payouts=sum(p.amount for p in payouts),current_debt=a.debt,current_credit=a.credit_limit-a.debt,available_income=commissions.sums(uid)['available'],credit_entries=[dict(date=e.created_at.isoformat(),kind=e.kind,amount=e.amount,debt_after=e.debt_after,reference=e.reference) for e in entries],earnings=[dict(date=e.created_at.isoformat(),username=e.username,amount=e.amount,offset_used=e.offset_used,state=e.state,reference=e.reference) for e in earnings])
    @app.post(base+'/c/<token>/reseller/credit/statements')
    @transactional
    def issue_statement(token):
        user=features.resolve_account(token);features.verify_csrf()
        if not account(user.id):abort(404)
        ref=request.form.get('reference','')
        if not re.fullmatch('[a-f0-9]{32}',ref):abort(400)
        old=Statement.query.filter_by(reference=ref).first()
        if old:
            if old.reseller_id!=user.id:abort(404)
            return redirect(base+'/c/'+token+'/reseller/credit/statements/'+str(old.id))
        row=Statement(reference=ref,reseller_id=user.id,payload='{}');db.session.add(row)
        try:
            db.session.flush();row.payload=json.dumps(report(user.id),ensure_ascii=False);db.session.commit()
        except IntegrityError:db.session.rollback();abort(409,'Statement already issued; reload')
        return redirect(base+'/c/'+token+'/reseller/credit/statements/'+str(row.id))
    def statement_response(row,token=None):
        data=json.loads(row.payload)
        if request.args.get('format')=='csv':
            buf=io.StringIO();writer=csv.writer(buf);writer.writerow(['date','type','amount_toman','debt_after','reference'])
            for e in data['credit_entries']:writer.writerow([e['date'],e['kind'],e['amount'],e['debt_after'],e['reference']])
            writer.writerow([]);writer.writerow(['date','customer','base_toman','retail_toman','margin_toman','markup_percent'])
            for e in data['initial_orders']:
                name=e['username'];name="'"+name if name and name[0] in '=+-@' else name
                writer.writerow([e['fulfilled_at'],name,e['base'],e['retail'],e['margin'],e['markup_percent']])
            writer.writerow([]);writer.writerow(['date','customer','commission_toman','used_for_debt','state','reference'])
            for e in data['earnings']:
                name=e['username'];name="'"+name if name and name[0] in '=+-@' else name
                writer.writerow([e['date'],name,e['amount'],e['offset_used'],e['state'],e['reference']])
            return Response('﻿'+buf.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename="beeny-statement-{row.id}.csv"','Cache-Control':'private, no-store'})
        return render_template('representative_statement.html',statement=row,data=data,panel_path=panel_path,token=token)
    @app.get(base+'/c/<token>/reseller/credit/statements/<int:statement_id>')
    def view_statement(token,statement_id):
        user=features.resolve_account(token);row=db.session.get(Statement,statement_id)
        if not row or row.reseller_id!=user.id:abort(404)
        return statement_response(row,token)
    @app.post(base+'/settings/representative-credit/<int:uid>/statements')
    @login_required
    @transactional
    def owner_issue_statement(uid):
        if current_user.role!='owner':abort(403)
        features.verify_csrf()
        if not account(uid):abort(404)
        ref=request.form.get('reference','')
        if not re.fullmatch('[a-f0-9]{32}',ref):abort(400)
        row=Statement.query.filter_by(reference=ref).first()
        if row and row.reseller_id!=uid:abort(404)
        if not row:
            row=Statement(reference=ref,reseller_id=uid,payload='{}');db.session.add(row)
            try:
                db.session.flush();row.payload=json.dumps(report(uid),ensure_ascii=False);db.session.commit()
            except IntegrityError:db.session.rollback();abort(409,'Statement already issued; reload')
        return redirect(base+'/settings/representative-credit/statements/'+str(row.id))
    @app.get(base+'/settings/representative-credit/statements/<int:statement_id>')
    @login_required
    def owner_statement(statement_id):
        if current_user.role!='owner':abort(403)
        return statement_response(db.session.get(Statement,statement_id) or abort(404))
    @app.route(base+'/representatives/login',methods=['GET','POST'])
    def representative_login():
        lang=request.args.get('lang',session.get('customer_language','fa'))
        session['customer_language']=lang if lang in {'fa','en'} else 'fa'
        error=None;status=200
        if request.method=='POST':
            features.verify_csrf();key=hmac.new(app.secret_key.encode(),('representative|'+str(request.remote_addr)).encode(),hashlib.sha256).hexdigest()
            attempt=db.session.get(features.CustomerLoginAttempt,key)
            if attempt and attempt.window_start<datetime.utcnow()-timedelta(minutes=15):attempt.failures=0;attempt.window_start=datetime.utcnow()
            if attempt and attempt.failures>=10:db.session.commit();return render_template('representative_login.html',error='۱۵ دقیقه بعد دوباره تلاش کنید.',panel_path=panel_path),429
            name=request.form.get('username','').strip();password=request.form.get('password','')
            profiles=features.CustomerProfile.query.filter_by(login_username=name).limit(2).all()
            profile=profiles[0] if len(profiles)==1 else None;a=account(profile.user_id) if profile else None
            if profile and a and a.enabled and profile.password_hash and len(password)<=256 and check_password_hash(profile.password_hash,password):
                user=db.session.get(User,a.reseller_id)
                if user:
                    if not profile.auth_version:profile.auth_version=secrets.token_hex(24)
                    link=db.session.get(AccountLink,user.id)
                    if not a.portal_token or not link or hashlib.sha256(a.portal_token.encode()).hexdigest()!=link.token_hash:
                        a.portal_token=secrets.token_urlsafe(32)
                        if not link:link=AccountLink(user_id=user.id);db.session.add(link)
                        link.token_hash=hashlib.sha256(a.portal_token.encode()).hexdigest()
                    session['customer_auth']=dict(user=user.id,version=profile.auth_version,link=link.token_hash,expires=(datetime.utcnow()+timedelta(hours=12)).timestamp())
                    if attempt:db.session.delete(attempt)
                    db.session.commit();return redirect(base+'/c/'+a.portal_token+'/reseller/credit')
            if not attempt:attempt=features.CustomerLoginAttempt(key=key,failures=0);db.session.add(attempt)
            attempt.failures+=1;db.session.commit();error='نام کاربری یا رمز نادرست است.';status=401
        return render_template('representative_login.html',error=error,panel_path=panel_path),status
    @app.route(base+'/c/<token>/reseller/credit/<section>',methods=['GET','POST'])
    @app.route(base+'/c/<token>/reseller/credit',methods=['GET','POST'])
    @transactional
    def workspace(token,section='overview'):
        if section not in {'overview','create','accounts','debt','income','prices','reports','cancellations'}:abort(404)
        user=features.resolve_account(token);a=account(user.id)
        if not a:abort(404)
        if request.method=='POST':
            features.verify_csrf();action=request.form.get('action');ref=request.form.get('reference','')
            if not re.fullmatch('[a-f0-9]{32}',ref):abort(400)
            try:
                if action=='create':create(user)
                elif action=='offset':offset(user.id,request.form.get('amount',type=int),ref);db.session.commit();sync_children(user.id)
                elif action=='cash_offset':cash_offset(user.id,request.form.get('amount',type=int),ref);db.session.commit();sync_children(user.id)
                elif action=='receipt':
                    old=features.RenewalRequest.query.filter_by(billing_reference=ref).first()
                    if old:
                        if old.user_id!=user.id:abort(409)
                        return redirect(request.path)
                    plan=payment_plan(user.id,request.form.get('amount',type=int));cfg=features.settings()
                    card=next((c for c in cfg['bank_cards'] if c['id']==request.form.get('card_id')),None)
                    if not card:abort(400,'Payment card missing')
                    if features.RenewalRequest.query.filter_by(user_id=user.id,status='pending').first():abort(409,'A payment is already pending')
                    image=request.files.get('receipt');
                    if not image:abort(400,'Receipt required')
                    try:filename=features.store_image(image.stream.read(20*1024*1024+1))
                    except ValueError as error:abort(400,str(error))
                    plan['payment_card']=dict(card)
                    row=features.RenewalRequest(user_id=user.id,username=user.username,source='reseller_debt',plan=json.dumps(plan,ensure_ascii=False),billing_reference=ref,receipt=filename,name=user.username,contact=request.form.get('contact','')[:120],note='پرداخت بدهی نماینده')
                    try:
                        db.session.add(row);db.session.flush();commissions.claim_receipt(filename,'debt:'+ref);db.session.commit()
                    except Exception:
                        db.session.rollback();(features.storage/filename).unlink(missing_ok=True);raise
                    flash('رسید بدهی ثبت شد؛ پس از تأیید مدیر، اعتبار خودکار برمی‌گردد.','success')
                elif action=='retry':
                    if not allow_create(user.id):abort(403)
                    order=resellers.Order.query.filter_by(id=request.form.get('order_id',type=int),reseller_id=user.id).first_or_404();resellers.provision(order)
                else:abort(400)
            except IntegrityError:db.session.rollback();abort(409,'Duplicate financial operation')
            return redirect(request.path)
        profile=db.session.get(features.CustomerProfile,user.id)
        wallet=db.session.get(commerce.Wallet,user.id)
        q=request.args.get('q','').strip()[:64]
        query=resellers.Order.query.filter_by(reseller_id=user.id)
        if q:query=query.filter(resellers.Order.username.contains(q,autoescape=True))
        rows=query.order_by(resellers.Order.id.desc()).paginate(page=max(1,request.args.get('page',1,type=int) or 1),per_page=12,error_out=False)
        children={u.id:u for u in User.query.filter(User.reseller_id==user.id,User.id.in_([o.user_id for o in rows.items]))}
        original_margin=db.session.query(db.func.sum(Margin.sale_amount-Margin.base_amount)).filter(Margin.reseller_id==user.id,Margin.state.in_(['completed','refunded','partially_refunded'])).scalar() or 0
        returned=[json.loads(e.details) for e in Entry.query.filter_by(reseller_id=user.id,kind='cancel') if json.loads(e.details).get('delivered')]
        margin_total=original_margin-sum(e['sale_amount']-e['base_amount'] for e in returned)
        totals=commissions.sums(user.id)
        from app import representative_actions
        from app import balepay_orders
        withdrawals=commissions.Settlement.query.filter_by(reseller_id=user.id).order_by(commissions.Settlement.id.desc()).paginate(page=max(1,request.args.get('page',1,type=int) or 1),per_page=12,error_out=False)
        debt_payments=features.RenewalRequest.query.filter_by(user_id=user.id,source='reseller_debt').order_by(features.RenewalRequest.id.desc()).paginate(page=max(1,request.args.get('page',1,type=int) or 1),per_page=12,error_out=False)
        online_debt=balepay_orders.query.filter(balepay_orders.user_id==user.id,db.func.json_extract(balepay_orders.plan_json,'$.kind')=='reseller_debt').order_by(balepay_orders.created_at.desc()).paginate(page=max(1,request.args.get('online_page',1,type=int) or 1),per_page=12,error_out=False)
        cancellations=representative_actions.Cancellation.query.filter_by(reseller_id=user.id).order_by(representative_actions.Cancellation.id.desc()).paginate(page=max(1,request.args.get('page',1,type=int) or 1),per_page=12,error_out=False)
        return render_template('representative_credit.html',rep_section=section,withdrawals=withdrawals,debt_payments=debt_payments,online_debt=online_debt,cancellations=cancellations,cancellation_map={c.order_id:c for c in representative_actions.Cancellation.query.filter(representative_actions.Cancellation.order_id.in_([o.id for o in rows.items]))},cash_balance=wallet.balance if wallet else 0,profile=profile,statements=Statement.query.filter_by(reseller_id=user.id).order_by(Statement.id.desc()).limit(24).all(),report=report(user.id),token=token,panel_path=panel_path,user=user,credit=a,credit_available=max(0,a.credit_limit-a.debt),margin=margin_total,margins={m.order_id:m for m in Margin.query.filter(Margin.reseller_id==user.id,Margin.order_id.in_([o.id for o in rows.items]))},income=totals,plans=commissions.customer_settings(SimpleNamespace(reseller_id=user.id),features.settings())['plans'],nodes=resellers.nodes_for(user.id),reference=secrets.token_hex(16),debt_reference=secrets.token_hex(16),offset_reference=secrets.token_hex(16),customer_settings=features.settings(),orders=rows,children=children,valid_links={o.id:bool((link:=db.session.get(AccountLink,o.user_id)) and link.token_hash==hashlib.sha256(o.portal_token.encode()).hexdigest()) for o in rows.items},login_names={uid:((p.login_username if (p:=db.session.get(features.CustomerProfile,uid)) else None) or child.username) for uid,child in children.items()},search=q,entries=Entry.query.filter_by(reseller_id=user.id).order_by(Entry.id.desc()).limit(50).all(),pending=features.RenewalRequest.query.filter_by(user_id=user.id,status='pending').first(),payments=features.RenewalRequest.query.filter_by(user_id=user.id,source='reseller_debt').order_by(features.RenewalRequest.id.desc()).limit(20).all(),minimum=db.session.get(commissions.Policy,user.id).minimum,can_create=allow_create(user.id))
    @app.route(base+'/settings/representative-credit',methods=['GET','POST'])
    @login_required
    @transactional
    def manage():
        if current_user.role!='owner':abort(403)
        uid=request.values.get('reseller_id',type=int)
        if request.method=='POST':
            features.verify_csrf();a=account(uid);action=request.form.get('action')
            if action=='cancellation_policy':
                hours=request.form.get('max_hours',type=int);usage=request.form.get('max_usage_gb',type=float)
                if hours is None or not 0<=hours<=87600 or usage is None or not math.isfinite(usage) or not 0<=usage<=1000000:abort(400,'مهلت و سقف مصرف لغو معتبر نیست.')
                features.set_setting('credit_cancel_max_hours',str(hours));features.set_setting('credit_cancel_max_usage_gb',str(usage));db.session.commit()
                flash('مهلت و سقف مصرف لغو ذخیره شد؛ خارج از این بازه تأیید استثنا و دلیل مدیر لازم است.','success')
                return redirect(base+'/settings/representative-credit?tab=cancellations')
            if action in {'policy','pay','reject_settlement','refund'}:
                app.view_functions['commission_admin']()
                return redirect(base+'/settings/representative-credit?tab='+('prices' if action=='policy' else 'payouts')+'&reseller_id='+str(uid or request.form.get('reseller_id',type=int) or 0))
            if action=='pending_refund':
                # Reuse the original owner-only cancellation endpoint for unfulfilled orders.
                from werkzeug.datastructures import ImmutableMultiDict
                request.form=ImmutableMultiDict(list(request.form.items())+[('action','refund')])
                # Replace action rather than trusting a second form value.
                fields=request.form.to_dict();fields['action']='refund';request.form=ImmutableMultiDict(fields)
                app.view_functions['reseller_admin']()
                return redirect(base+'/settings/representative-credit?tab=orders')
            if action=='nodes':
                if not a or not db.session.get(resellers.Profile,uid):abort(404)
                nids=request.form.getlist('nodes',type=int)
                if not nids or len(nids)!=len(set(nids)) or Node.query.filter(Node.id.in_(nids)).count()!=len(nids):abort(400,'حداقل یک نود معتبر انتخاب کنید.')
                resellers.Grant.query.filter_by(user_id=uid).delete()
                for nid in nids:db.session.add(resellers.Grant(user_id=uid,node_id=nid))
                db.session.commit();flash('مجوز نودهای نماینده ذخیره شد؛ حساب‌های قبلی جابه‌جا نشدند.','success')
                return redirect(base+'/settings/representative-credit?tab=nodes&reseller_id='+str(uid))
            if action=='register':
                name=request.form.get('username','').strip();password=request.form.get('password','');limit=request.form.get('credit_limit',type=int)
                nids=request.form.getlist('nodes',type=int)
                if not re.fullmatch('[A-Za-z0-9_-][A-Za-z0-9_.-]{2,63}',name) or not 12<=len(password)<=256 or limit is None or not 0<=limit<=10000000000 or not nids:abort(400,'Invalid representative registration')
                from app import devices
                if User.query.filter_by(username=name).first() or db.session.get(devices.RetiredUsername,name):abort(409,'Username already exists or is retired')
                if len(nids)!=len(set(nids)) or Node.query.filter(Node.id.in_(nids)).count()!=len(nids):abort(400,'Invalid nodes')
                user=User(username=name,status='active',traffic_limit=0,expire_date='-',protocol='openvpn')
                db.session.add(user)
                try:db.session.flush()
                except IntegrityError:db.session.rollback();abort(409,'Username already registered')
                uid=user.id
                db.session.add(resellers.Profile(user_id=uid,enabled=True))
                for nid in nids:db.session.add(resellers.Grant(user_id=uid,node_id=nid))
                db.session.add(commissions.Policy(reseller_id=uid,enabled=True,invite=secrets.token_urlsafe(32)))
                for plan in features.settings()['plans']:
                    db.session.add(commissions.Rate(reseller_id=uid,plan_id=plan['id'],base_price=plan['price'],maximum=min(1000000000,plan['price']*2),sale_price=plan['price'],enabled=True))
                raw=secrets.token_urlsafe(32)
                db.session.add(features.CustomerProfile(user_id=uid,login_username=name,password_hash=generate_password_hash(password),auth_version=secrets.token_hex(24),avatar_choice=1))
                db.session.add(AccountLink(user_id=uid,token_hash=hashlib.sha256(raw.encode()).hexdigest()))
                a=Account(reseller_id=uid,enabled=True,credit_limit=limit,debt=0,portal_token=raw);db.session.add(a);db.session.flush()
                journal(uid,'limit',0,'credit-register:'+secrets.token_hex(16),{'credit_limit':limit})
            elif action=='configure':
                if not db.session.get(resellers.Profile,uid) or not commissions.mode(uid):abort(400,'Configure commission representative and price rules first')
                limit=request.form.get('credit_limit',type=int)
                if limit is None or not 0<=limit<=10000000000 or (a and limit<a.debt):abort(400,'Limit cannot be below debt')
                if not a:a=Account(reseller_id=uid);db.session.add(a);db.session.flush()
                enabled=request.form.get('enabled')=='1'
                if enabled and not a.enabled and commissions.Sale.query.filter(commissions.Sale.reseller_id==uid,commissions.Sale.state.in_(['pending','provisioning'])).first():abort(409,'Resolve pending direct sales before enabling the credit model')
                if not enabled and (a.debt or resellers.Order.query.filter(resellers.Order.reseller_id==uid,resellers.Order.state.in_(['pending','working'])).first()):abort(409,'Resolve debt and provisioning before disabling credit mode')
                old=a.credit_limit
                changed=db.session.execute(update(Account).where(Account.reseller_id==uid,Account.debt<=limit,db.or_(db.literal(enabled),Account.debt==0)).values(credit_limit=limit,enabled=enabled)).rowcount
                if changed!=1:db.session.rollback();abort(409,'Debt changed; retry credit policy')
                journal(uid,'limit',0,'credit-limit:'+secrets.token_hex(16),{'before':old,'after':limit,'enabled':enabled})
            elif action in {'lock','unlock','suspend','restore'}:
                if not a:abort(404)
                if action in {'lock','unlock'}:
                    a.locked=action=='lock'
                    if a.locked:
                        a.locked_reason=request.form.get('reason','financial')
                        if a.locked_reason not in {'financial','other'}:abort(400)
                else:
                    desired=action=='suspend'
                    if desired:
                        a.suspended_reason=request.form.get('reason','financial')
                        if a.suspended_reason not in {'financial','other'}:abort(400)
                    if a.suspended!=desired:a.suspended=desired;children_pending(uid,desired)
                journal(uid,action,0,'credit-control:'+secrets.token_hex(16))
            else:abort(400)
            db.session.commit()
            if action in {'suspend','restore'}:sync_children(uid)
            flash('تنظیمات نمایندگی ذخیره شد؛ تأیید نودهای در دسترس‌نبودن در صف پیگیری می‌ماند.','success')
            return redirect(base+'/settings/representative-credit?tab=manage&reseller_id='+str(uid))
        users={u.id:u for u in User.query.all()};selected=account(uid) if uid else None
        from app import representative_actions
        tab=request.args.get('tab','overview')
        if tab not in {'overview','register','manage','prices','nodes','receipts','payouts','orders','cancellations','reports'}:abort(404)
        return render_template('representative_credit_admin.html',tab=tab,legacy_sales=commissions.Sale.query.order_by(commissions.Sale.id.desc()).paginate(page=max(1,request.args.get('legacy_page',1,type=int) or 1),per_page=12,error_out=False),cancellations=representative_actions.Cancellation.query.order_by(representative_actions.Cancellation.id.desc()).paginate(page=max(1,request.args.get('page',1,type=int) or 1),per_page=15,error_out=False),payouts=commissions.Settlement.query.order_by(commissions.Settlement.id.desc()).paginate(page=max(1,request.args.get('page',1,type=int) or 1),per_page=15,error_out=False),earnings=commissions.Earning.query.order_by(commissions.Earning.id.desc()).limit(60).all(),orders=resellers.Order.query.order_by(resellers.Order.id.desc()).paginate(page=max(1,request.args.get('page',1,type=int) or 1),per_page=15,error_out=False),plans=features.settings()['plans'],policy=db.session.get(commissions.Policy,uid) if uid else None,rates={rate.plan_id:rate for rate in commissions.Rate.query.filter_by(reseller_id=uid)},grants={g.node_id for g in resellers.Grant.query.filter_by(user_id=uid)},child_users=users,income=commissions.sums(uid) if uid else commissions.sums(),panel_path=panel_path,profiles=resellers.Profile.query.all(),users=users,selected=selected,selected_id=uid,statements=Statement.query.filter_by(reseller_id=uid).order_by(Statement.id.desc()).limit(24).all() if uid else [],report=report(uid) if selected else None,statement_reference=secrets.token_hex(16),child_count=User.query.filter_by(reseller_id=uid).count() if selected else 0,sync_pending=User.query.filter_by(reseller_id=uid,pause_sync_pending=True).count() if selected else 0,nodes=Node.query.order_by(Node.name).all(),accounts=Account.query.all(),entries=Entry.query.filter_by(reseller_id=uid).order_by(Entry.id.desc()).limit(100).all() if uid else [],pending=features.RenewalRequest.query.filter_by(source='reseller_debt',status='pending').order_by(features.RenewalRequest.id).all())
    sync_cursor=[0]
    def cycle():
        from app import representative_actions
        representative_actions.cycle()
        rows=User.query.join(Account,User.reseller_id==Account.reseller_id).filter(User.pause_sync_pending.is_(True),User.id>sync_cursor[0]).order_by(User.id).limit(20).all()
        if not rows:
            sync_cursor[0]=0
            rows=User.query.join(Account,User.reseller_id==Account.reseller_id).filter(User.pause_sync_pending.is_(True)).order_by(User.id).limit(20).all()
        for child in rows:
            try:experience.sync_access(child)
            except Exception:
                db.session.rollback();child=db.session.get(User,child.id);child.pause_sync_pending=True;db.session.commit()
            sync_cursor[0]=child.id
        for memo in Margin.query.filter_by(state='pending').limit(10):
            order=db.session.get(resellers.Order,memo.order_id)
            if not order:continue
            if allow_create(order.reseller_id) and ((order.state=='pending' and order.updated_at<datetime.utcnow()-timedelta(seconds=60)) or (order.state=='working' and order.updated_at<datetime.utcnow()-timedelta(minutes=5))):resellers.provision(order)
            user=db.session.get(User,order.user_id)
            if order.state=='completed' and user and user.status=='active' and not user.pause_sync_pending and not suspended(user):on_provision(order,confirmed=True)
        db.session.commit()
    def detach(uid):
        a=account(uid)
        if a:
            from app import balepay_orders
            if features.RenewalRequest.query.filter_by(user_id=uid,status='pending').first() or balepay_orders.query.filter(balepay_orders.user_id==uid,balepay_orders.status.in_(['pending','superseded','processing'])).first():abort(409,'Financial payment attempts must be reconciled; archive or lock instead of deleting.')
            if a.debt or a.suspended or resellers.Order.query.filter(resellers.Order.reseller_id==uid,resellers.Order.state.in_(['pending','working'])).first():abort(409,'Resolve representative debt and pending orders before deleting')
            a.enabled=False;a.reseller_id=-uid
            for model in (Entry,Margin,Statement):model.query.filter_by(reseller_id=uid).update({'reseller_id':-uid})
        Margin.query.filter_by(user_id=uid).update({'user_id':-uid})
    return SimpleNamespace(Account=Account,Entry=Entry,Margin=Margin,Statement=Statement,cycle=cycle,mode=mode,suspended=suspended,allow_create=allow_create,approve_debt=approve_debt,offset=offset,payment_plan=payment_plan,on_provision=on_provision,cancel=cancel,detach=detach,sync_children=sync_children)
