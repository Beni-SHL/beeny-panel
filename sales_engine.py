"""Sales are existing invoices. Receipts are an immutable money journal, not orders."""
import json,secrets
from datetime import datetime
from types import SimpleNamespace
from flask import abort,request,redirect
from flask_login import login_required,current_user
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from pricing import quote,with_gift

def category(snapshot,reference=''):
    try:p=json.loads(snapshot) if isinstance(snapshot,str) else snapshot
    except (ValueError,TypeError):p={}
    return 'representative' if p.get('commission_reseller') or p.get('representative_id') or p.get('commission_sale') or reference.startswith(('reseller:','reseller-renew:','commission:')) else 'direct'

def register(app,db,commerce,features,panel_path):
    base=panel_path.rstrip('/')
    class Receipt(db.Model):
        __tablename__='sales_receipts'
        id=db.Column(db.Integer,primary_key=True)
        reference=db.Column(db.String(120),nullable=False,unique=True)
        user_id=db.Column(db.Integer,index=True)
        channel=db.Column(db.String(30),nullable=False)
        amount=db.Column(db.BigInteger,nullable=False)
        method=db.Column(db.String(30),nullable=False)
        bank_reference=db.Column(db.String(100),unique=True)
        created_at=db.Column(db.DateTime,index=True,default=datetime.utcnow,nullable=False)
    def receipt(reference,uid,channel,amount,method,at=None,bank=None):
        if Receipt.query.filter_by(reference=reference).first():return
        if type(amount) is not int or amount<=0:raise ValueError('Receipt amount must be positive integer Toman.')
        db.session.add(Receipt(reference=reference,user_id=uid,channel=channel,amount=amount,method=method,created_at=at or datetime.utcnow(),bank_reference=bank))
    def renewal_receipt(row):
        if row.source=='wallet':return
        p=json.loads(row.plan);ref='renewal:'+(row.billing_reference or ('legacy-'+str(row.id)))
        amount=int(p['price'])
        if row.source=='reseller_debt':
            from app import representative_credit
            entry=representative_credit.Entry.query.filter_by(reference='debt:'+row.billing_reference).first() if row.billing_reference else None
            account=representative_credit.Account.query.filter_by(reseller_id=row.user_id).first()
            principal=-entry.amount if entry else min(account.debt,amount) if account else 0
            if principal:receipt(ref,row.user_id,'principal',principal,row.source,row.reviewed_at)
            if amount>principal:receipt(ref+':excess',row.user_id,'wallet_topup',amount-principal,row.source,row.reviewed_at)
        else:
            channel='wallet_topup' if row.source=='wallet_topup' else category(p)
            receipt(ref,row.user_id,channel,amount,row.source or 'receipt',row.reviewed_at)
    def backfill():
        # Only retained, explicitly approved payments. Deleted/unknown history is never invented.
        from app import commissions
        from sqlalchemy import exists,literal
        R=features.RenewalRequest
        rows=R.query.filter(R.status=='completed',R.reviewed_at.is_not(None),R.source!='wallet',R.billing_reference.is_not(None),~exists().where(Receipt.reference==literal('renewal:')+R.billing_reference)).yield_per(200)
        count=0
        for row in rows:
            if row.source=='reseller_debt':
                from app import representative_credit
                if not representative_credit.Entry.query.filter_by(reference='debt:'+row.billing_reference).first():continue
            renewal_receipt(row);count+=1
            if count%200==0:db.session.commit()
        for sale in commissions.Sale.query.filter(commissions.Sale.state.in_(['provisioning','completed']),commissions.Sale.reviewed_at.is_not(None),~exists().where(Receipt.reference==literal('commission:')+commissions.Sale.reference)).yield_per(200):
            receipt('commission:'+sale.reference,sale.user_id,'representative',int(json.loads(sale.plan)['price']),'receipt',sale.reviewed_at);count+=1
        db.session.commit();return count
    def options():return features.settings()
    def prepare(form):
        mode=form.get('sale_mode','internal')
        if mode=='internal':
            if current_user.role!='owner' and form.get('sale_mode'):abort(403)
            return form,None
        if mode not in {'catalog','manual'}:abort(400,'Invalid sale mode.')
        cfg=options()
        if mode=='catalog':
            plan=next((dict(p) for p in cfg['plans'] if p['id']==form.get('sale_plan')),None)
            if not plan:abort(400,'Select an existing service.')
        else:
            try:plan=quote(cfg['custom_pricing'],form.get('expire_days'),form.get('traffic_limit'),form.get('max_devices'))
            except ValueError as exc:abort(400,str(exc))
        try:
            manual_gift=with_gift(plan,form.get('gift_days','0'),form.get('gift_quota','0'))
            plan=with_gift(plan,manual_gift['gift_days']+int(plan.get('gift_days',0)),manual_gift['gift_quota']+int(plan.get('gift_quota',0)))
        except ValueError as exc:abort(400,str(exc))
        state=form.get('sale_payment','unpaid')
        if state not in {'paid','unpaid'}:abort(400)
        if state=='paid' and current_user.role!='owner':abort(403,'Only the owner can confirm a direct payment.')
        bank=form.get('sale_bank_reference','').strip()
        if state=='paid' and not 3<=len(bank)<=100:abort(400,'Enter the payment reference after checking the transfer.')
        if bank and Receipt.query.filter_by(bank_reference=bank).first():abort(409,'Payment reference already used.')
        form=form.copy()
        for key,value in dict(expire_days=plan['days'],traffic_limit=plan['quota'],max_devices=plan['devices'],quota_mode=plan.get('quota_mode','metered'),throttle_down_kbps=plan.get('throttle_down_kbps',2000),throttle_up_kbps=plan.get('throttle_up_kbps',2000)).items():form[key]=str(value)
        return form,dict(plan=plan,state=state,bank=bank)
    def direct_invoice(user,sale):
        if not sale:return
        plan=dict(sale['plan'],operation='direct_create',payment_source='manual_sale',sale_mode='catalog' if sale['plan']['id']!='custom' else 'manual')
        ref='direct:'+secrets.token_hex(16)
        db.session.add(commerce.Invoice(request_id=0,source_reference=ref,user_id=user.id,username=user.username,seller_id=user.owner_id,amount=int(plan['price']),cost=None,commission=0,snapshot=json.dumps(plan,ensure_ascii=False),payment_state=sale['state']))
        if sale['state']=='paid':receipt(ref,user.id,'direct',int(plan['price']),'manual',bank=sale['bank'])
    @app.post(base+'/settings/sales/invoices/<int:ident>/paid')
    @login_required
    def settle_direct_invoice(ident):
        if current_user.role!='owner':abort(403)
        features.verify_csrf()
        row=db.session.get(commerce.Invoice,ident) or abort(404)
        if json.loads(row.snapshot).get('operation')!='direct_create':abort(400)
        if row.payment_state=='paid':return redirect(base+'/settings/sales')
        bank=request.form.get('bank_reference','').strip()
        if not 3<=len(bank)<=100:abort(400,'Payment reference required.')
        changed=db.session.execute(update(commerce.Invoice).where(commerce.Invoice.id==ident,commerce.Invoice.payment_state=='unpaid').values(payment_state='paid')).rowcount
        if changed!=1:abort(409)
        receipt(row.source_reference,row.user_id,'direct',row.amount,'manual',bank=bank)
        try:db.session.commit()
        except IntegrityError:db.session.rollback();abort(409,'Payment already registered.')
        return redirect(base+'/settings/sales')
    @app.context_processor
    def context():return dict(direct_sale_options=options)
    return SimpleNamespace(Receipt=Receipt,receipt=receipt,renewal_receipt=renewal_receipt,prepare=prepare,direct_invoice=direct_invoice,backfill=backfill)
