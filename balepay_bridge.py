"""BalePay WordPress bridge for Beeny Panel 3.5.1; server-authoritative orders."""
import hashlib, hmac, json, os, secrets, time
from datetime import datetime
from urllib.parse import urlencode
from flask import abort, jsonify, redirect, request, render_template, session, flash
from flask_login import login_required, current_user
from sqlalchemy import update
from pricing import quote


def register(app, db, User, features, experience, panel_path):
    base = panel_path.rstrip('/')
    class BaleOrder(db.Model):
        __tablename__ = 'balepay_orders'
        id = db.Column(db.String(40), primary_key=True)
        user_id = db.Column(db.Integer, nullable=False, index=True)
        plan_json = db.Column(db.Text, nullable=False)
        amount_irr = db.Column(db.BigInteger, nullable=False)
        status = db.Column(db.String(24), nullable=False, default='pending')
        payment_id = db.Column(db.String(128), unique=True)
        renewal_id = db.Column(db.Integer, unique=True)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    class BaleGatewayConfig(db.Model):
        __tablename__ = 'balepay_gateway_config'
        id = db.Column(db.Integer, primary_key=True)
        wordpress_url = db.Column(db.String(512), nullable=False, default='')
        encrypted_secret = db.Column(db.Text, nullable=False, default='')
        encrypted_payment_settings = db.Column(db.Text, nullable=False, default='')

    def _fernet():
        import base64
        from cryptography.fernet import Fernet
        key = hashlib.sha256(app.config['SECRET_KEY'].encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    def gateway():
        cfg = db.session.get(BaleGatewayConfig, 1)
        if cfg and cfg.encrypted_secret and cfg.wordpress_url:
            try:
                return _fernet().decrypt(cfg.encrypted_secret.encode()).decode(), cfg.wordpress_url
            except Exception:
                app.logger.exception('BalePay settings could not be decrypted')
        return os.environ.get('BEENY_BALEPAY_SECRET', ''), os.environ.get('BEENY_BALEPAY_WORDPRESS_URL', '')

    def secret():
        return gateway()[0]

    def payment_settings():
        cfg = db.session.get(BaleGatewayConfig, 1)
        if cfg and cfg.encrypted_payment_settings:
            try:
                return json.loads(_fernet().decrypt(cfg.encrypted_payment_settings.encode()).decode())
            except Exception:
                app.logger.exception('BalePay payment settings unreadable')
        return {}

    @app.get(base+'/api/balepay/config')
    def balepay_private_config():
        if not signed('GET',request.path,'',request.headers.get('X-Beeny-Timestamp',''),request.headers.get('X-Beeny-Signature','')):abort(403)
        response = jsonify(payment_settings())
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route(base+'/payments/balepay', methods=['GET','POST'])
    @app.route(base+'/settings/balepay', methods=['GET','POST'])
    @login_required
    def balepay_settings():
        from urllib.parse import urlsplit
        if (getattr(current_user, 'role', 'owner') or 'owner') != 'owner':
            abort(403)
        if '_customer_csrf' not in session:
            session['_customer_csrf'] = secrets.token_urlsafe(32)
        if request.method == 'POST':
            if not hmac.compare_digest(session['_customer_csrf'], request.form.get('csrf','')):
                abort(403)
            url = request.form.get('wordpress_url','').strip().rstrip('/')
            parts = urlsplit(url)
            if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or len(url)>512:
                flash('Enter a valid HTTPS WordPress URL.', 'error')
            else:
                cfg = db.session.get(BaleGatewayConfig, 1)
                if not cfg:
                    cfg = BaleGatewayConfig(id=1)
                    db.session.add(cfg)
                cfg.wordpress_url = url
                new_secret = request.form.get('shared_secret','').strip()
                if new_secret:
                    if len(new_secret) < 32 or len(new_secret)>256:
                        flash('Shared secret must contain at least 32 characters.', 'error')
                        return redirect(base+'/settings/customer?tab=balepay')
                    cfg.encrypted_secret = _fernet().encrypt(new_secret.encode()).decode()
                settings = payment_settings()
                for field in ('bot_username','invoice_title','invoice_description'):
                    settings[field] = request.form.get(field,'').strip()[:255]
                for field in ('bot_token','provider_token','webhook_secret'):
                    if request.form.get(field,'').strip():
                        settings[field] = request.form[field].strip()
                settings['test_mode'] = bool(request.form.get('test_mode'))
                settings['enabled'] = bool(request.form.get('enabled'))
                cfg.encrypted_payment_settings = _fernet().encrypt(json.dumps(settings,ensure_ascii=False).encode()).decode()
                db.session.commit()
                flash('Payment gateway settings saved.', 'success')
                return redirect(base+'/settings/customer?tab=balepay')
        cfg = db.session.get(BaleGatewayConfig, 1)
        _, url = gateway()
        return render_template('settings_balepay.html',panel_path=panel_path, wordpress_url=url, configured=bool(secret()), csrf=session['_customer_csrf'], saved=bool(cfg and cfg.encrypted_secret), payment=payment_settings(), orders=BaleOrder.query.order_by(BaleOrder.created_at.desc()).limit(50).all(), order_users={u.id:u.username for u in User.query.filter(User.id.in_([o.user_id for o in BaleOrder.query.order_by(BaleOrder.created_at.desc()).limit(50).all()])).all()})


    def signed(method, path, body, timestamp, signature):
        if not secret() or not timestamp or not signature:
            return False
        try:
            if abs(time.time()-int(timestamp)) > 300: return False
        except ValueError: return False
        raw = '\n'.join([method, path, timestamp, body]).encode()
        expected = hmac.new(secret().encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @app.context_processor
    def balepay_template():
        return {'balepay_enabled':bool(secret() and gateway()[1] and payment_settings().get('enabled', True))}

    @app.post(base+'/c/<token>/balepay/debt/start')
    @app.post(base+'/c/<token>/balepay/wallet/start')
    @app.post(base+'/c/<token>/balepay/start')
    def balepay_start(token):
        if not secret() or not gateway()[1]:
            abort(503, 'Payment gateway not configured')
        if not payment_settings().get('enabled', True):
            abort(503, 'BalePay is temporarily disabled')
        user = features.resolve_account(token)
        features.verify_csrf()
        cfg = features.settings()
        plan_id = request.form.get('plan_id','')
        try:
            debt_payment=request.path.endswith('/balepay/debt/start')
            wallet_topup=request.path.endswith('/balepay/wallet/start') or debt_payment
            if debt_payment:
                if (request.form.get('amount',type=int) or 0)<1000:raise ValueError('Use bank transfer for repayments below 1,000 Toman')
                from app import representative_credit
                plan=representative_credit.payment_plan(user.id,request.form.get('amount',type=int))
                plan['payment_source']='balepay'
            elif wallet_topup:
                amount=request.form.get('amount',type=int)
                if amount is None or not 1000<=amount<=100000000:raise ValueError('Invalid wallet top-up amount')
                plan=dict(id='wallet-topup',title='شارژ کیف پول',price=amount,days=0,quota=0,devices=0,kind='wallet_topup')
            elif plan_id == 'custom':
                from app import representative_catalog
                plan = representative_catalog.customer_quote(user, days=request.form.get('custom_days'), quota=request.form.get('custom_quota'), devices=request.form.get('custom_devices'))
            else:
                plan = next((dict(p) for p in cfg['plans'] if p['id']==plan_id), None)
            if not plan: raise ValueError('Invalid plan')
            from app import commissions, commerce
            if not wallet_topup:plan = commissions.customer_plan(user, dict(plan))
            coupon = '' if wallet_topup else request.form.get('coupon','').strip().upper()
            if coupon and not cfg['coupons_enabled']:raise ValueError('Discount codes are disabled.')
            if not wallet_topup:commissions.snapshot_discount(plan,coupon)
            percent = 0
            if coupon:
                row = db.session.get(commerce.Coupon,coupon)
                if not row or not row.active or row.used >= row.limit or row.expires < datetime.utcnow().date().isoformat():
                    raise ValueError('Invalid coupon')
                percent = row.percent
            price = max(1,int(plan['price'])*(100-percent)//100)
            if price > 100000000: raise ValueError('Amount exceeds limit')
            plan['price'] = price
            plan['coupon'] = coupon
            plan['payment_test_mode'] = bool(payment_settings().get('test_mode', False))
            if features.RenewalRequest.query.filter_by(user_id=user.id,status='pending').first():
                raise ValueError('A renewal request is already pending')
            if BaleOrder.query.filter_by(user_id=user.id,status='processing').first():
                raise ValueError('A paid order is being reconciled; contact support')
            # A browser cancellation is not proof that money was never paid.
            # Retain old checkout attempts and permit signed late reconciliation.
            db.session.execute(update(BaleOrder).where(
                BaleOrder.user_id == user.id, BaleOrder.status == 'pending'
            ).values(status='superseded'))
            order = BaleOrder(id=secrets.token_hex(16),user_id=user.id,plan_json=json.dumps(plan,ensure_ascii=False),amount_irr=price*10)
            db.session.add(order);db.session.commit()
            url = gateway()[1].rstrip('/') + '/?beeny_pay=' + order.id
            response = redirect(url,code=303)
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        except (ValueError,TypeError,KeyError) as error:
            abort(400,str(error))

    @app.get(base+'/api/balepay/orders/<order_id>')
    def balepay_order_info(order_id):
        if not signed('GET',request.path,'',request.headers.get('X-Beeny-Timestamp',''),request.headers.get('X-Beeny-Signature','')): abort(403)
        order=db.session.get(BaleOrder,order_id)
        if not order:abort(404)
        # Do not mutate pending to expired here: a delayed successful_payment
        # may still need to be reconciled after the checkout window closes.
        plan=json.loads(order.plan_json)
        public_status = ('expired' if order.status=='pending' and (datetime.utcnow()-order.created_at).total_seconds()>3600 else order.status)
        return jsonify(order_id=order.id,order_number=order.id[:8].upper(),status=public_status,amount_irr=order.amount_irr,title=('سفارش شماره '+order.id[:8].upper())[:32],test_mode=bool(plan.get('payment_test_mode',False)),expires_at=int(order.created_at.timestamp())+3600)

    @app.post(base+'/api/balepay/confirm')
    def balepay_confirm():
        body=request.get_data(as_text=True)
        if not signed('POST',request.path,body,request.headers.get('X-Beeny-Timestamp',''),request.headers.get('X-Beeny-Signature','')):abort(403)
        data=request.get_json(silent=True) or {}
        order=db.session.get(BaleOrder,data.get('order_id',''))
        if not order:abort(404)
        if json.loads(order.plan_json).get('payment_test_mode') or data.get('test_mode') is True:
            abort(409, 'Test payments cannot activate real subscriptions')
        if order.status=='completed':
            if data.get('payment_id')!=order.payment_id or data.get('amount_irr')!=order.amount_irr or data.get('currency')!='IRR':abort(409)
            return jsonify(ok=True,status='completed')
        if not isinstance(data.get('amount_irr'),int) or data['amount_irr']!=order.amount_irr or data.get('currency')!='IRR':abort(409)
        payment_id=data.get('payment_id','')
        if not isinstance(payment_id,str) or not 1<=len(payment_id)<=128:abort(400)
        if order.status not in ('pending','superseded','processing'):abort(409)
        if order.status=='processing':
            if order.payment_id!=payment_id or not order.renewal_id:abort(409)
            row=db.session.get(features.RenewalRequest,order.renewal_id)
            if not row:abort(409)
            if row.status=='completed':
                order.status='completed';db.session.commit()
                return jsonify(ok=True,status='completed')
            if row.status!='pending':abort(409)
        else:
            # Atomically claim the payment. Subsequent retries reuse the same renewal.
            changed=db.session.execute(update(BaleOrder).where(BaleOrder.id==order.id,BaleOrder.status.in_(('pending','superseded'))).values(status='processing',payment_id=payment_id)).rowcount
            if changed!=1:db.session.rollback();abort(409)
            user=db.session.get(User,order.user_id)
            if not user:db.session.rollback();abort(409)
            plan=json.loads(order.plan_json)
            row=features.RenewalRequest(user_id=user.id,username=user.username,source='reseller_debt' if plan.get('kind')=='reseller_debt' else 'wallet_topup' if plan.get('kind')=='wallet_topup' else 'balepay',plan=json.dumps(plan,ensure_ascii=False),receipt='',status='pending',billing_reference=order.id,email_state='skipped',telegram_state='skipped')
            db.session.add(row);db.session.flush()
            order.renewal_id=row.id
            db.session.commit()
        # The existing approval routine atomically marks the renewal completed,
        # extends expiry/quota and synchronizes nodes. Never call it twice for
        # an already-completed renewal.
        try:
            experience.approve_renewal(row)
        except Exception:
            db.session.rollback()
            app.logger.exception('BalePay renewal approval needs reconciliation: %s',order.id)
            return jsonify(ok=False,status='processing'),503
        order.status='completed';db.session.commit()
        return jsonify(ok=True,status='completed')

    @app.get(base+'/balepay/result/<order_id>')
    def balepay_public_result(order_id):
        order=db.session.get(BaleOrder,order_id)
        if not order:abort(404)
        from flask import render_template_string
        return render_template_string('<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="refresh" content="10"><title>وضعیت پرداخت</title><style>body{font:16px sans-serif;background:#f6f7fa;display:grid;place-items:center;min-height:90vh}.card{background:#fff;border-radius:20px;padding:30px;text-align:center}</style><div class="card"><h2>وضعیت سفارش</h2><p>{{ status }}</p><p>برای مشاهده حساب، به برگه پرتال شخصی خود بازگردید.</p><a href="{{ home }}">صفحه اصلی بنی پنل</a></div></html>',status={'completed':'پرداخت تأیید شد و سفارش انجام شد.','processing':'پرداخت دریافت شد؛ فعال‌سازی در حال بررسی است.','pending':'هنوز پرداخت تأیید نشده است.','superseded':'این تلاش با سفارش جدید جایگزین شده است؛ نتیجه پرداخت احتمالی همچنان بررسی می‌شود.','expired':'مهلت سفارش پایان یافته است.'}.get(order.status,'وضعیت نیازمند بررسی است.'),home=base or '/')

    @app.get(base+'/c/<token>/balepay/result/<order_id>')
    def balepay_result(token,order_id):
        user=features.resolve_account(token)
        order=db.session.get(BaleOrder,order_id)
        if not order or order.user_id!=user.id:abort(404)
        from flask import render_template_string
        return render_template_string('''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>وضعیت پرداخت</title><style>body{font:16px sans-serif;background:#f5f6fa;display:grid;place-items:center;min-height:90vh}.card{background:white;border-radius:22px;padding:35px;max-width:420px;text-align:center}a{color:#2563eb}</style><div class="card"><h2>وضعیت پرداخت</h2><p>{{ message }}</p><a href="{{ back }}">بازگشت به حساب من</a></div></html>''',message={'completed':'پرداخت تأیید شد و سفارش ثبت گردید.','processing':'پرداخت دریافت شده و فعال‌سازی در حال بررسی است.','pending':'هنوز پرداخت تأیید نشده است.','superseded':'این تلاش با سفارش جدید جایگزین شده است؛ نتیجه پرداخت احتمالی همچنان بررسی می‌شود.','expired':'مهلت این سفارش پایان یافته است.'}.get(order.status,'وضعیت سفارش نیازمند بررسی است.'),back=base+'/c/'+token+'#renew')
    return BaleOrder
