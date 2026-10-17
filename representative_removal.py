"""Owner-only removal with financial preflight and confirmed VPN blocking.
No refund is implied by deleting an identity; historic accounting is retained.
"""
from flask import abort,jsonify,request,render_template
from flask_login import current_user,login_required

def register(app,db,panel_path):
    base=panel_path.rstrip('/')
    @app.route(base+'/settings/representatives/<int:uid>/remove',methods=['GET','POST'])
    @login_required
    def remove_representative(uid):
        if current_user.role!='owner':abort(403)
        from app import User,representative_credit as credit,commissions,resellers,customer_features as features,commerce,balepay_orders,representative_actions,remove_vpn_account
        rep=db.get_or_404(User,uid)
        account=db.session.get(credit.Account,uid)
        if not account and not db.session.get(resellers.Profile,uid) and not db.session.get(commissions.Policy,uid):abort(404)
        if request.method=='POST':
            if request.form.get('confirm')!=rep.username or request.form.get('understood')!='1':
                return jsonify(success=False,message='Enter the exact representative username and confirm removal.'),400
            from sqlalchemy import update,or_
            if request.form.get('action')=='cancel':
                db.session.execute(update(User).where(or_(User.id==uid,User.reseller_id==uid)).values(removal_pending=False))
                db.session.commit()
                return jsonify(success=True,message='Removal hold cleared. The representative remains locked; review permissions before unlocking.',redirect=base+'/settings/representative-credit')
            # Serialize with order creation and freeze every current child in one transaction.
            previous_lock=(account.locked,account.locked_reason) if account else None
            if account:account.locked=True;account.locked_reason='other'
            db.session.execute(update(User).where(or_(User.id==uid,User.reseller_id==uid)).values(removal_pending=True))
            db.session.commit();db.session.expire_all()
        children=User.query.filter_by(reseller_id=uid).order_by(User.id).all()
        ids=[uid]+[u.id for u in children]
        blockers=[]
        if account and account.debt:blockers.append('Settle the representative debt before removal.')
        totals=commissions.sums(uid)
        if any(totals.get(k,0) for k in ('held','available','reserved')):blockers.append('Settle outstanding representative earnings first.')
        if commissions.Settlement.query.filter(commissions.Settlement.reseller_id==uid,commissions.Settlement.state.in_(['requested','processing'])).first():blockers.append('Resolve pending payout requests.')
        if commerce.Wallet.query.filter(commerce.Wallet.user_id.in_(ids),commerce.Wallet.balance!=0).first():blockers.append('Resolve remaining wallet balances for these accounts.')
        if features.RenewalRequest.query.filter(features.RenewalRequest.user_id.in_(ids),features.RenewalRequest.status.in_(['pending','processing'])).first():blockers.append('Resolve pending receipts.')
        if balepay_orders.query.filter(balepay_orders.user_id.in_(ids),balepay_orders.status.in_(['pending','processing','superseded'])).first():blockers.append('Reconcile open online payment attempts.')
        if resellers.Order.query.filter(resellers.Order.reseller_id==uid,resellers.Order.state.in_(['pending','working'])).first():blockers.append('Wait for account provisioning to finish.')
        if commissions.Sale.query.filter(commissions.Sale.reseller_id==uid,commissions.Sale.state.in_(['pending','provisioning'])).first():blockers.append('Resolve pending representative sales.')
        if representative_actions.Cancellation.query.filter(representative_actions.Cancellation.user_id.in_(ids),representative_actions.Cancellation.state.in_(['pending','applying'])).first():blockers.append('Resolve pending account cancellations.')
        if request.method=='GET':return render_template('representative_remove.html',rep=rep,children=children,blockers=blockers,panel_path=panel_path)
        if request.form.get('confirm')!=rep.username or request.form.get('understood')!='1':return jsonify(success=False,message='Enter the exact representative username and confirm removal.'),400
        if blockers:
            from sqlalchemy import update,or_
            db.session.execute(update(User).where(or_(User.id==uid,User.reseller_id==uid)).values(removal_pending=False))
            if account:account.locked,account.locked_reason=previous_lock
            db.session.commit()
            return jsonify(success=False,message=' '.join(blockers)),409
        # Lock before any external work; a failed node response leaves the identity present and retryable.
        if account:account.locked=True;account.locked_reason='other'
        db.session.commit()
        removed=0
        try:
            for child in children:
                remove_vpn_account(child,owner_cascade=True);removed+=1
            # All children are gone; clearing this flag cannot reactivate a child.
            account=db.session.get(credit.Account,uid)
            if account:account.suspended=False
            db.session.commit()
            remove_vpn_account(rep)
        except Exception as error:
            db.session.rollback();app.logger.exception('Representative removal paused for ID %s',uid)
            from werkzeug.exceptions import HTTPException
            detail=error.description if isinstance(error,HTTPException) else 'A node did not confirm blocking. Check node health and service logs.'
            return jsonify(success=False,detail=detail,removed=removed,message=f'Removal paused after {removed} accounts. The representative remains locked. Resolve node or payment issues, then reopen this page and retry.'),409
        return jsonify(success=True,message='Representative and child accounts removed. Financial records preserved; no automatic refunds were issued.',redirect=base+'/settings/representative-credit')
