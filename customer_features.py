from pricing import quote, DEFAULT_PRICING
"""Customer workspace, private uploads, renewal inbox and Telegram workflow."""
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import time
import smtplib
import ssl
import warnings
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import requests
from flask import abort, flash, redirect, render_template, request, send_file, session, url_for, jsonify
from flask_login import login_required,current_user
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.exc import IntegrityError

DEFAULT_PLANS = [
    dict(id='monthly', title='۱ ماهه نامحدود', days=30, devices=1, quota=100, price=250000),
    dict(id='duo', title='۱ ماهه دو کاربره', days=30, devices=2, quota=100, price=340000),
    dict(id='two', title='۲ ماهه', days=60, devices=1, quota=200, price=450000),
    dict(id='three', title='۳ ماهه', days=90, devices=1, quota=300, price=650000),
]
MAX_UPLOAD = 20 * 1024 * 1024
FA_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def clean_image(data, avatar=False, cover=False):
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError('تصویر باید حداکثر ۲۰ مگابایت باشد.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'} or source.width * source.height > 40000000:
                    raise ValueError('تصویر JPG، PNG یا WebP با ابعاد مناسب انتخاب کنید.')
                source.load()
                image = ImageOps.exif_transpose(source).convert('RGB')
                if cover:
                    image = ImageOps.pad(image,(1280,720),method=Image.Resampling.LANCZOS,color='#101827')
                elif avatar:
                    image = ImageOps.fit(image, (320, 320))
                else:
                    image.thumbnail((1800, 1800))
                output = io.BytesIO()
                if cover:
                    image.save(output,'WEBP',quality=82,method=6)
                elif avatar:
                    image.save(output, 'WEBP', quality=72, method=6)
                else:
                    image.save(output, 'JPEG', quality=88)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('فایل تصویر قابل خواندن نیست.') from exc


def register(app, db, User, AccountLink, TrafficDailyUser, Node, UserNode, resolve_account, build_config, panel_path, is_primary_node):
    base = panel_path.rstrip('/')
    signer = URLSafeTimedSerializer(app.secret_key, salt='beeny-customer-bot-v1')
    storage = Path(app.instance_path) / 'customer_uploads'
    private_file = Path(app.instance_path) / 'customer_notification_secrets.json'

    class CustomerSetting(db.Model):
        __tablename__ = 'customer_settings'
        key = db.Column(db.String(80), primary_key=True)
        value = db.Column(db.Text, nullable=False)

    class CustomerProfile(db.Model):
        __tablename__ = 'customer_profiles'
        user_id = db.Column(db.Integer, primary_key=True)
        avatar = db.Column(db.String(80))
        avatar_choice = db.Column(db.Integer, default=lambda: secrets.randbelow(29) + 1)
        login_username = db.Column(db.String(100))
        password_hash = db.Column(db.String(255))
        auth_version = db.Column(db.String(64))

    class CustomerLoginAttempt(db.Model):
        __tablename__ = 'customer_login_attempts'
        key = db.Column(db.String(64), primary_key=True)
        failures = db.Column(db.Integer, default=0)
        window_start = db.Column(db.DateTime, default=datetime.utcnow)

    class RenewalRequest(db.Model):
        __tablename__ = 'renewal_requests'
        billing_reference=db.Column(db.String(64),default=lambda:secrets.token_hex(16))
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, nullable=False, index=True)
        username = db.Column(db.String(100), nullable=False)
        plan = db.Column(db.Text, nullable=False)
        name = db.Column(db.String(100), default='')
        contact = db.Column(db.String(120), default='')
        note = db.Column(db.String(500), default='')
        receipt = db.Column(db.String(80), nullable=False)
        source = db.Column(db.String(20), default='web')
        status = db.Column(db.String(20), default='pending')
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        reviewed_at = db.Column(db.DateTime)
        email_state = db.Column(db.String(20), default='pending')
        telegram_state = db.Column(db.String(20), default='pending')
        telegram_sent_ids = db.Column(db.Text, default='[]')
        attempts = db.Column(db.Integer, default=0)
        next_attempt = db.Column(db.DateTime, default=datetime.utcnow)
        __table_args__ = (db.Index('uq_pending_renewal_user', 'user_id', unique=True, sqlite_where=db.text("status = 'pending'")),)

    class ReceiptGrant(db.Model):
        __tablename__ = 'receipt_grants'
        request_id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, nullable=False, index=True)
        base_limit = db.Column(db.Integer)
        base_expiry = db.Column(db.String(20))
        applied_limit = db.Column(db.Integer, nullable=False)
        applied_expiry = db.Column(db.String(20))
        start_usage = db.Column(db.Float, nullable=False)
        temporary_only = db.Column(db.Boolean, default=False, nullable=False)
        active = db.Column(db.Boolean, default=True, nullable=False)
        state = db.Column(db.String(20), default='pending', nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        expires_at = db.Column(db.DateTime, nullable=False)

    class TelegramPair(db.Model):
        __tablename__ = 'telegram_pairs'
        digest = db.Column(db.String(64), primary_key=True)
        user_id = db.Column(db.Integer, nullable=False)
        link_hash = db.Column(db.String(64), nullable=False)
        expires_at = db.Column(db.DateTime, nullable=False)

    class TelegramAccount(db.Model):
        __tablename__ = 'telegram_accounts'
        chat_id = db.Column(db.BigInteger, primary_key=True)
        user_id = db.Column(db.Integer, unique=True, nullable=False)
        link_hash = db.Column(db.String(64), nullable=False)
        selected_plan = db.Column(db.String(30))
        selected_at = db.Column(db.DateTime)

    def get_setting(key, default=''):
        row = db.session.get(CustomerSetting, key)
        return row.value if row else default

    def set_setting(key, value):
        row = db.session.get(CustomerSetting, key)
        if row is None:
            row = CustomerSetting(key=key, value=str(value))
            db.session.add(row)
        else:
            row.value = str(value)

    def settings():
        raw = get_setting('plans')
        plans = json.loads(raw) if raw else [dict(plan) for plan in DEFAULT_PLANS]
        for plan in plans:
            plan.setdefault('quota_mode','metered')
            plan.setdefault('throttle_down_kbps',2000)
            plan.setdefault('throttle_up_kbps',2000)
        cards = json.loads(get_setting('bank_cards', '[]'))
        if not cards and get_setting('card_number'):
            cards = [dict(id='primary', bank=get_setting('bank_name'), number=get_setting('card_number'), holder=get_setting('card_holder'), color='violet')]
        return dict(bank_name=get_setting('bank_name'), card_number=get_setting('card_number'),
                    card_holder=get_setting('card_holder'), admin_phone=get_setting('admin_phone'),
                    admin_telegram=get_setting('admin_telegram'), admin_email=get_setting('admin_email'),
                    bot_username=get_setting('bot_username'), admin_chat_id=get_setting('admin_chat_id'),
                    smtp_host=get_setting('smtp_host'), smtp_port=get_setting('smtp_port', '465'),
                    smtp_security=get_setting('smtp_security', 'ssl'), smtp_user=get_setting('smtp_user'),
                    smtp_from=get_setting('smtp_from'), plans=plans, bank_cards=cards,
                    coupons_enabled=get_setting('coupons_enabled','1')=='1', card_color=get_setting('card_color', 'violet'), admin_chat_ids=get_setting('admin_chat_ids'),
                    custom_pricing=json.loads(get_setting('custom_pricing', json.dumps(DEFAULT_PRICING))))

    def admin_recipients(cfg):
        return list(dict.fromkeys(value for value in [cfg['admin_chat_id']]+cfg['admin_chat_ids'].split(',') if value))

    def read_secrets():
        try:
            return json.loads(private_file.read_text())
        except FileNotFoundError:
            return {}

    def save_secrets(values):
        private_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = private_file.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(values, handle)
        os.replace(temporary, private_file)
        os.chmod(private_file, 0o600)

    def csrf():
        if '_customer_csrf' not in session:
            session['_customer_csrf'] = secrets.token_urlsafe(32)
        return session['_customer_csrf']

    def verify_csrf():
        supplied = request.form.get('csrf', '')
        expected = session.get('_customer_csrf', '')
        if not expected or not hmac.compare_digest(supplied, expected):
            abort(400, 'Refresh this page and retry the form.')

    def portal_url(token):
        origin = os.environ.get('BEENY_PANEL_BASE_URL', '').rstrip('/')
        if not origin:
            raise ValueError('BEENY_PANEL_BASE_URL is required for bot links.')
        parsed = urlsplit(origin)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('Invalid public panel URL.')
        return origin + base + '/c/' + token

    def bot_token(user):
        link = db.session.get(AccountLink, user.id)
        if not link:
            raise ValueError('حساب هنوز لینک شخصی ندارد.')
        return 't_' + signer.dumps(dict(user=user.id, link=link.token_hash, nonce=secrets.token_hex(8)))

    def resolve_bot_token(token):
        try:
            data = signer.loads(token[2:], max_age=30 * 86400)
            link = db.session.get(AccountLink, int(data['user']))
            if not link or not hmac.compare_digest(link.token_hash, data['link']):
                abort(404)
            return db.session.get(User, link.user_id) or abort(404)
        except (BadSignature, ValueError, KeyError, TypeError):
            abort(404)

    def account_data(user):
        today = datetime.utcnow().date()
        days = [(today - timedelta(days=offset)).isoformat() for offset in range(29, -1, -1)]
        rows = TrafficDailyUser.query.filter(TrafficDailyUser.user_id == user.id,
                                             TrafficDailyUser.day >= days[0]).all()
        measured = {r.day: r.bytes_total / 1073741824 for r in rows}
        daily = [(day, round(measured.get(day, 0), 4)) for day in days]
        expiry = user.expire_date or '-'
        days_left = None
        expiry_text = 'نامحدود'
        if expiry.isdigit():
            days_left = int(expiry)
            expiry_text = f'{days_left} روز پس از اولین اتصال'
        elif expiry != '-':
            try:
                date = datetime.strptime(expiry, '%Y-%m-%d').date()
                days_left = max(0, (date - today).days)
                expiry_text = expiry
            except ValueError:
                expiry_text = 'نیاز به بررسی مدیر'
        used = float(user.traffic_usage or 0)
        quota = int(user.traffic_limit or 0)
        return dict(used=used, quota=quota, remaining=max(0, quota-used) if quota else None,
                    percent=min(100, used/quota*100) if quota else 0, daily=daily,
                    today=round(measured.get(today.isoformat(), 0), 3),
                    month=round(sum(measured.values()), 3), days_left=days_left, expiry_text=expiry_text)

    def store_image(data, avatar=False, cover=False):
        cleaned = clean_image(data, avatar, cover)
        storage.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = secrets.token_hex(24) + ('.webp' if avatar or cover else '.jpg')
        fd = os.open(storage / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(cleaned)
        return name

    @app.template_filter('usage_size')
    def usage_size(gb):
        gb=float(gb or 0)
        return (f'{gb*1024:,.1f} MB' if gb<1 else f'{gb:,.2f} GB')

    def start_receipt_grant(user, row):
        # Legacy disable causes are ambiguous; only a new automatic expiry/quota
        # block may be temporarily lifted. Manager-disabled accounts stay blocked.
        if row.source not in {'web','portal','telegram'} or not (user.status=='active' or (user.status=='disabled' and getattr(user,'disable_reason','legacy')=='automatic')) or user.customer_paused:
            return None
        if ReceiptGrant.query.filter(ReceiptGrant.user_id==user.id,ReceiptGrant.created_at>=datetime.utcnow()-timedelta(days=30)).first():
            return None
        from datetime import date
        import math
        expiry=user.expire_date
        expired=False
        if expiry and expiry not in {'-',''}:
            if expiry.isdigit():expired=int(expiry)<1
            else:
                try: expired=date.fromisoformat(expiry)<datetime.utcnow().date()
                except ValueError: return None
        usage=float(user.traffic_usage or 0);limit=int(user.traffic_limit or 0)
        if not limit and not expired:
            return None  # Never cap an already unlimited active account.
        temporary=expired or (limit>0 and usage>=limit)
        if user.status=='disabled' and not temporary:return None
        new_limit=math.ceil(usage)+5 if temporary else limit+5
        if expiry and expiry.isdigit():new_expiry=str(max(0,int(expiry))+1)
        elif expiry and expiry not in {'-',''}:
            new_expiry=(max(datetime.utcnow().date(),date.fromisoformat(expiry))+timedelta(days=1)).isoformat()
        else:new_expiry=expiry
        grant=ReceiptGrant(request_id=row.id,user_id=user.id,base_limit=user.traffic_limit,base_expiry=expiry,
            applied_limit=new_limit,applied_expiry=new_expiry,start_usage=usage,temporary_only=temporary,
            expires_at=datetime.utcnow()+timedelta(hours=24))
        db.session.add(grant)
        user.traffic_limit=new_limit;user.expire_date=new_expiry
        if user.status=='disabled':user.status='active'
        user.pause_sync_pending=True;user.speed_sync_pending=True
        from app import experience
        experience.notify(user.id,'اعتبار موقت رسید فعال شد','۵ گیگ حجم و یک روز اعتبار هدیه برای بررسی رسید اضافه شد. با رد یا پایان مهلت، فقط روز هدیه حذف می‌شود؛ مانده حجم تا انقضای اصلی باقی می‌ماند.')
        return grant

    def finish_receipt_grant(row, state):
        grant=db.session.get(ReceiptGrant,row.id)
        if not grant or not grant.active:return False
        from sqlalchemy import update
        changed=db.session.execute(update(ReceiptGrant).where(ReceiptGrant.request_id==row.id,ReceiptGrant.active==True).values(active=False,state=state)).rowcount
        if changed!=1:return False
        user=db.session.get(User,grant.user_id)
        if user:
            # Preserve manager edits made while the receipt was waiting.
            if state=='approved' and user.traffic_limit==grant.applied_limit:user.traffic_limit=grant.base_limit
            if user.expire_date==grant.applied_expiry:user.expire_date=grant.base_expiry
            from renewal import activation_error
            if user.status=='active' and activation_error(user.expire_date,user.traffic_limit or 0,user.traffic_usage or 0,quota_mode=user.quota_mode):
                user.status='disabled';user.disable_reason='automatic'
            user.pause_sync_pending=True;user.speed_sync_pending=True
            if state!='approved':
                from app import experience
                experience.notify(user.id,'اعتبار موقت پایان یافت','روز هدیه رسید پایان یافت؛ مانده حجم، شامل مانده حجم هدیه، تا تاریخ انقضای اصلی حفظ می‌شود. مصرف صفر نشده است.')
        return True

    def receipt_counter_started(user, pending_days, new_expiry):
        grant=ReceiptGrant.query.filter_by(user_id=user.id,active=True).first()
        if grant and grant.base_expiry and grant.base_expiry.isdigit() and grant.applied_expiry==pending_days:
            from datetime import date
            grant.applied_expiry=new_expiry
            grant.base_expiry=(date.fromisoformat(new_expiry)-timedelta(days=1)).isoformat()

    def expire_receipt_grants():
        grants=ReceiptGrant.query.outerjoin(User,User.id==ReceiptGrant.user_id).filter(ReceiptGrant.active==True,db.or_(ReceiptGrant.expires_at<=datetime.utcnow(),db.and_(ReceiptGrant.temporary_only==True,User.traffic_usage>=ReceiptGrant.start_usage+5))).order_by(ReceiptGrant.expires_at).limit(100).all()
        for grant in grants:
            user=db.session.get(User,grant.user_id)
            if grant.expires_at<=datetime.utcnow() or (grant.temporary_only and user and float(user.traffic_usage or 0)>=grant.start_usage+5):
                row=db.session.get(RenewalRequest,grant.request_id)
                if row:finish_receipt_grant(row,'expired')
        db.session.commit()

    def sync_receipt_credit(row):
        user=db.session.get(User,row.user_id)
        if not user or not UserNode.query.filter_by(user_id=user.id).first():return
        from app import experience
        try:experience.sync_access(user)
        except Exception:
            db.session.rollback()
            user=db.session.get(User,row.user_id)
            if user:user.pause_sync_pending=True;user.speed_sync_pending=True;db.session.commit()
            app.logger.warning('Receipt credit node synchronization pending for request %s',row.id)

    def create_request(user, plan_id, receipt_data, name='', contact='', note='', source='web', card_id=None, custom=None, coupon=''):
        from removal_guard import claim
        claim(db,User,user.id)
        from app import representative_actions
        if representative_actions.in_review(user):raise ValueError('حساب در حال لغو یا بایگانی است؛ پرداخت جدید مجاز نیست.')
        cfg = settings()
        from app import representative_catalog
        plan = representative_catalog.customer_quote(user, **(custom or dict(days=None, quota=None, devices=None))) if plan_id == 'custom' else next((p for p in cfg['plans'] if p['id'] == plan_id), None)
        if not plan:
            raise ValueError('سرویس انتخاب‌شده معتبر نیست.')
        from app import commissions
        plan = commissions.customer_plan(user,dict(plan))
        if card_id:
            card = next((c for c in cfg['bank_cards'] if c['id'] == card_id), None)
            if not card:
                raise ValueError('کارت بانکی انتخاب‌شده معتبر نیست.')
            plan['payment_card'] = dict(card)
        if len(cfg['card_number']) != 16 or not cfg['card_holder'] or not cfg['bank_name']:
            raise ValueError('اطلاعات پرداخت هنوز توسط مدیر ثبت نشده است.')
        if not cfg['admin_email'] and not admin_recipients(cfg):
            raise ValueError('دریافت درخواست‌ها هنوز توسط مدیر فعال نشده است.')
        if RenewalRequest.query.filter_by(user_id=user.id, status='pending').first():
            raise ValueError('یک درخواست در انتظار بررسی دارید؛ ابتدا با مدیر پیگیری کنید.')
        count = RenewalRequest.query.filter(RenewalRequest.user_id == user.id,
                    RenewalRequest.created_at >= datetime.utcnow()-timedelta(days=1)).count()
        if count >= 5:
            raise ValueError('تعداد درخواست‌های امروز به سقف مجاز رسیده است.')
        filename = store_image(receipt_data)
        try:
            from app import commerce
            plan=commerce.discount(plan,coupon)
        except Exception:
            db.session.rollback();(storage / filename).unlink(missing_ok=True);raise
        row = RenewalRequest(user_id=user.id, username=user.username, plan=json.dumps(plan, ensure_ascii=False),
                             name=name[:100], contact=contact[:120], note=note[:500], receipt=filename, source=source,billing_reference=secrets.token_hex(16))
        db.session.add(row)
        try:
            db.session.flush()
            commissions.claim_receipt(filename,'renewal:'+row.billing_reference)
            start_receipt_grant(user,row)
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            (storage / filename).unlink(missing_ok=True)
            raise ValueError('یک درخواست در انتظار بررسی دارید.') from exc
        except Exception:
            db.session.rollback()
            (storage / filename).unlink(missing_ok=True)
            raise
        return row

    def private_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.after_request
    def protect_customer_responses(response):
        if request.path.startswith(base+'/c/'):
            private_headers(response)
        return response

    @app.before_request
    def customer_login_gate():
        # Protect every private child route, including new modules and detail pages.
        # An endpoint allowlist silently omitted newly added routes in older releases.
        if not request.path.startswith(base+'/c/') or not (request.view_args or {}).get('token') or request.endpoint=='customer_login':
            return
        token = (request.view_args or {}).get('token', '')
        user = resolve_account(token)
        profile = db.session.get(CustomerProfile, user.id)
        auth = session.get('customer_auth', {})
        link = db.session.get(AccountLink, user.id)
        if not profile or not profile.password_hash or not profile.auth_version or not link or auth.get('user') != user.id or auth.get('version') != profile.auth_version or auth.get('link') != link.token_hash or auth.get('expires', 0) < datetime.utcnow().timestamp():
            return redirect(base+'/c/'+token+'/login')

    @app.route(base+'/c/<token>/login', methods=['GET', 'POST'])
    def customer_login(token):
        user = resolve_account(token)
        profile = db.session.get(CustomerProfile, user.id)
        ready = bool(profile and profile.password_hash and profile.login_username)
        error = None
        status_code = 200
        if request.method == 'POST':
            verify_csrf()
            key = hmac.new(app.secret_key.encode(), (str(user.id)+'|'+str(request.remote_addr)).encode(), hashlib.sha256).hexdigest()
            attempt = db.session.get(CustomerLoginAttempt, key)
            if attempt and attempt.window_start < datetime.utcnow()-timedelta(minutes=15):
                attempt.failures = 0
                attempt.window_start = datetime.utcnow()
            if attempt and attempt.failures >= 10:
                error, status_code = 'تلاش‌های زیادی انجام شده است؛ ۱۵ دقیقه بعد دوباره امتحان کنید.', 429
            else:
                username = request.form.get('username', '').strip()
                password = request.form.get('password', '')
                if ready and len(password) <= 256 and hmac.compare_digest(username.encode(), profile.login_username.encode()) and check_password_hash(profile.password_hash, password):
                    link = db.session.get(AccountLink, user.id)
                    session['customer_auth'] = dict(user=user.id, version=profile.auth_version, link=link.token_hash,
                                                    expires=(datetime.utcnow()+timedelta(hours=12)).timestamp())
                    if attempt:
                        db.session.delete(attempt)
                    db.session.commit()
                    return redirect(base+'/c/'+token)
                if attempt is None:
                    attempt = CustomerLoginAttempt(key=key, failures=0)
                    db.session.add(attempt)
                attempt.failures += 1
                db.session.commit()
                error = 'نام کاربری یا رمز عبور درست نیست.'
                status_code = 401
        return render_template('customer_login.html', token=token, portal_base=base+'/c/'+token,
                               ready=ready, error=error), status_code

    @app.post(base+'/c/<token>/logout')
    def customer_logout(token):
        resolve_account(token)
        verify_csrf()
        session.pop('customer_auth', None)
        return redirect(base+'/c/'+token+'/login')

    @app.post(base+'/users/view/<int:user_id>/portal-access')
    @login_required
    def set_customer_access(user_id):
        verify_csrf()
        user = db.session.get(User, user_id) or abort(404)
        username = request.form.get('portal_username', '').strip()
        password = request.form.get('portal_password', '')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{3,100}', username) or not 12 <= len(password) <= 256:
            flash('Use a 3+ character login name and a password of at least 12 characters.', 'error')
            return redirect(base+'/users/view/'+str(user_id))
        profile = db.session.get(CustomerProfile, user.id)
        if profile is None:
            profile = CustomerProfile(user_id=user.id)
            db.session.add(profile)
        profile.login_username = username
        profile.password_hash = generate_password_hash(password)
        profile.auth_version = secrets.token_hex(24)
        TelegramAccount.query.filter_by(user_id=user.id).delete()
        TelegramPair.query.filter_by(user_id=user.id).delete()
        from app import experience
        experience.notify(user.id, 'مشخصات ورود به‌روز شد', 'مدیر مشخصات ورود صفحه شخصی را تغییر داد؛ نشست‌های قبلی و اتصال قدیمی ربات لغو شدند.')
        db.session.commit()
        flash('Customer login saved. Previous customer sessions and bot bindings have been revoked.', 'success')
        return redirect(base+'/users/view/'+str(user_id))

    def login_config(user_id):
        profile = db.session.get(CustomerProfile, user_id)
        return dict(username=profile.login_username if profile else '', configured=bool(profile and profile.password_hash))

    @app.template_filter('fromjson')
    def fromjson(value):
        return json.loads(value)

    @app.template_filter('cardgroups')
    def cardgroups(value):
        return ' '.join(value[index:index+4] for index in range(0, len(value), 4))

    @app.before_request
    def upload_limit():
        if request.endpoint in {'upload_avatar', 'submit_renewal','customer_wallet'}:
            request.max_content_length = MAX_UPLOAD + 1024 * 1024

    @app.context_processor
    def customer_context():
        return dict(customer_csrf=csrf, customer_base=base, customer_login_config=login_config)

    def render_portal(user, token):
        from app import representative_credit
        if representative_credit.mode(user.id):return redirect(base+'/c/'+token+'/reseller/credit')
        cfg = settings()
        from app import commerce, commissions
        cfg=commissions.customer_settings(user,cfg)
        wallet=db.session.get(commerce.Wallet,user.id)
        nodes = [db.session.get(Node, rel.node_id) for rel in UserNode.query.filter_by(user_id=user.id).all()]
        profile = db.session.get(CustomerProfile, user.id)
        if profile and not profile.avatar_choice:
            profile.avatar_choice = secrets.randbelow(29) + 1
            db.session.commit()
        renewals = RenewalRequest.query.filter_by(user_id=user.id).order_by(RenewalRequest.id.desc()).limit(5).all()
        return render_template('customer_portal.html', user=user, token=token, panel_path=panel_path,
                portal_base=base+'/c/'+token, nodes=[n for n in nodes if n], data=account_data(user),
                profile=profile, customer_settings=cfg, renewals=renewals, receipt_grant=ReceiptGrant.query.filter_by(user_id=user.id,active=True).first(),wallet_balance=wallet.balance if wallet else 0,
                payment_ready=len(cfg['card_number']) == 16 and bool(cfg['card_holder'] and cfg['bank_name'])
                              and bool(cfg['admin_email'] or admin_recipients(cfg)),
                has_pending=any(r.status == 'pending' for r in renewals))

    def session_target(node, username, disconnect=None):
        from vpn_sessions import local_sessions, disconnect_session
        if is_primary_node(node):
            if disconnect:
                disconnect_session(username, disconnect['id'], disconnect['fingerprint'])
                return []
            return local_sessions(username)
        target = (node.host or node.ip or '').strip()
        from cluster import node_url
        address=node_url(node)
        payload = dict(username=username)
        if disconnect:
            payload.update(disconnect)
        response = requests.post(address+'/api/node/'+('disconnect-session' if disconnect else 'sessions'),
            json=payload, headers={'Authorization': 'Bearer '+node.api_key}, timeout=6)
        if response.status_code == 404:
            raise ValueError('Update the node agent to enable session controls.')
        response.raise_for_status()
        result=response.json()
        if result.get('success') is not True:raise ValueError('Agent did not confirm the operation.')
        return result.get('sessions', [])

    def connection_nodes(user):
        return [n for n in (db.session.get(Node, r.node_id) for r in UserNode.query.filter_by(user_id=user.id).all()) if n]

    def connection_page(user, target, customer=False, token=None):
        groups = []
        for node in connection_nodes(user):
            try:
                groups.append(dict(node=node, sessions=session_target(node, user.username), error=False))
            except (OSError, RuntimeError, ValueError, requests.RequestException):
                groups.append(dict(node=node, sessions=[], error=True))
        return render_template('customer_sessions.html' if customer else 'sessions.html', user=user,
             groups=groups, target=target, token=token, panel_path=panel_path)

    def terminate(user):
        verify_csrf()
        try:
            node_id = int(request.form.get('node', ''))
            node = next((n for n in connection_nodes(user) if n.id == node_id), None)
            if node is None:
                abort(404)
            session_target(node, user.username, dict(id=request.form.get('id', ''), fingerprint=request.form.get('fingerprint', '')))
            flash('اتصال قطع شد. دستگاه دارای کانفیگ معتبر می‌تواند دوباره متصل شود.' if request.endpoint == 'customer_disconnect' else 'Connection disconnected. A valid configuration can reconnect.', 'success')
        except (OSError, RuntimeError, ValueError, requests.RequestException):
            flash('قطع اتصال تأیید نشد؛ لیست را تازه کنید و وضعیت نود را بررسی کنید.' if request.endpoint == 'customer_disconnect' else 'Disconnect was not confirmed. Refresh and check the node agent.', 'error')

    @app.get(base+'/c/<token>/sessions')
    def customer_sessions(token):
        return connection_page(resolve_account(token), base+'/c/'+token+'/sessions', True, token)

    @app.post(base+'/c/<token>/sessions')
    def customer_disconnect(token):
        terminate(resolve_account(token))
        return redirect(base+'/c/'+token+'/sessions')

    @app.get(base+'/users/view/<int:user_id>/sessions')
    @login_required
    def admin_sessions(user_id):
        return connection_page(db.get_or_404(User, user_id), base+'/users/view/'+str(user_id)+'/sessions')

    @app.post(base+'/users/view/<int:user_id>/sessions')
    @login_required
    def admin_disconnect(user_id):
        terminate(db.get_or_404(User, user_id))
        return redirect(base+'/users/view/'+str(user_id)+'/sessions')

    @app.post(base+'/users/view/<int:user_id>/suspend')
    @login_required
    def suspend_account(user_id):
        verify_csrf()
        user = db.get_or_404(User, user_id)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', user.username):
            abort(400)
        user.status = 'disabled'
        db.session.commit()
        from app import sync_primary_access
        from cluster import set_user_state_on_node
        failures = []
        for node in connection_nodes(user):
            try:
                if is_primary_node(node):
                    sync_primary_access(user, False)
                    for connection in session_target(node, user.username):
                        session_target(node, user.username, dict(id=connection['id'], fingerprint=connection['fingerprint']))
                else:
                    confirmed, _ = set_user_state_on_node(node, user.username, False)
                    if not confirmed:
                        failures.append(node.name)
            except (OSError, RuntimeError, ValueError, requests.RequestException):
                failures.append(node.name)
        flash('Account disabled. Nodes without confirmation: '+', '.join(failures) if failures else 'Account disabled on assigned nodes. Re-enable it through Edit account.', 'error' if failures else 'success')
        return redirect(base+'/users/view/'+str(user_id)+'/sessions')

    @app.post(base+'/c/<token>/avatar')
    def upload_avatar(token):
        user = resolve_account(token)
        verify_csrf()
        file = request.files.get('avatar')
        try:
            if not file:
                raise ValueError('یک تصویر انتخاب کنید.')
            name = store_image(file.stream.read(MAX_UPLOAD+1), avatar=True)
            row = db.session.get(CustomerProfile, user.id)
            old = row.avatar if row else None
            if row is None:
                row = CustomerProfile(user_id=user.id)
                db.session.add(row)
            row.avatar = name
            db.session.commit()
            if old:
                (storage / old).unlink(missing_ok=True)
            flash('عکس پروفایل ذخیره شد.', 'success')
        except ValueError as exc:
            flash(str(exc), 'error')
        return redirect(base+'/c/'+token+'#profile')

    @app.get(base+'/c/<token>/avatar')
    def avatar(token):
        user = resolve_account(token)
        row = db.session.get(CustomerProfile, user.id)
        if not row or not row.avatar:
            abort(404)
        return private_image(row.avatar)

    @app.post(base+'/c/<token>/avatar/select')
    def select_avatar(token):
        user = resolve_account(token)
        verify_csrf()
        choice = request.form.get('avatar_choice', '')
        if not re.fullmatch(r'[0-9]{1,2}', choice) or not 1 <= int(choice) <= 29:
            abort(400)
        row = db.session.get(CustomerProfile, user.id)
        old = row.avatar
        row.avatar = None
        row.avatar_choice = int(choice)
        db.session.commit()
        if old:
            (storage / old).unlink(missing_ok=True)
        flash('آواتار دلخواه شما ذخیره شد.', 'success')
        return redirect(base+'/c/'+token+'#profile')

    def private_image(filename):
        response = send_file(storage / filename, mimetype='image/webp' if filename.endswith('.webp') else 'image/jpeg')
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.post(base+'/c/<token>/renew/quote')
    def renewal_quote(token):
        user=resolve_account(token);verify_csrf()
        try:
            cfg=settings();plan_id=request.form.get('plan_id')
            from app import representative_catalog
            plan=representative_catalog.customer_quote(user,days=request.form.get('custom_days'),quota=request.form.get('custom_quota'),devices=request.form.get('custom_devices')) if plan_id=='custom' else next((dict(p) for p in cfg['plans'] if p['id']==plan_id),None)
            if not plan:raise ValueError('سرویس معتبر نیست.')
            from app import commissions
            plan=commissions.customer_plan(user,plan)
            code=request.form.get('coupon','').strip().upper();percent=0
            if code and not cfg['coupons_enabled']:raise ValueError('Discount codes are disabled.')
            commissions.snapshot_discount(plan,code)
            if code:
                from app import commerce
                row=db.session.get(commerce.Coupon,code)
                if not row or not row.active or row.used>=row.limit or row.expires<datetime.utcnow().date().isoformat():raise ValueError('کد تخفیف نامعتبر یا منقضی است.')
                percent=row.percent
            return jsonify(price=max(1,int(plan['price'])*(100-percent)//100),coupon=code,percent=percent)
        except ValueError as error:return jsonify(error=str(error)),400

    @app.post(base+'/c/<token>/renew')
    def submit_renewal(token):
        user = resolve_account(token)
        verify_csrf()
        try:
            contact = request.form.get('contact', '').strip()
            name = request.form.get('name', '').strip()
            receipt = request.files.get('receipt')
            if not name or not contact or not receipt:
                raise ValueError('نام، راه ارتباطی و تصویر رسید را کامل کنید.')
            row = create_request(user, request.form.get('plan_id'), receipt.stream.read(MAX_UPLOAD+1),
                                 name, contact, request.form.get('note', ''), card_id=request.form.get('card_id'), coupon=request.form.get('coupon',''),
                                 custom=dict(days=request.form.get('custom_days'), quota=request.form.get('custom_quota'), devices=request.form.get('custom_devices')))
            if db.session.get(ReceiptGrant,row.id):sync_receipt_credit(row)
            flash(f'درخواست شماره {row.id} ثبت شد؛ پس از تأیید واریز توسط مدیر تمدید می‌شود.' + (' ۵ گیگ اعتبار موقت ۲۴ ساعته فعال شد.' if db.session.get(ReceiptGrant,row.id) else ''), 'success')
        except ValueError as exc:
            flash(str(exc), 'error')
        return redirect(base+'/c/'+token+'#renew')

    @app.post(base+'/c/<token>/telegram')
    def pair_telegram(token):
        user = resolve_account(token)
        verify_csrf()
        cfg = settings()
        if not cfg['bot_username'] or not read_secrets().get('bot_token'):
            abort(400, 'Telegram bot is not configured.')
        code = secrets.token_urlsafe(24)
        link = db.session.get(AccountLink, user.id)
        TelegramPair.query.filter_by(user_id=user.id).delete()
        db.session.add(TelegramPair(digest=hashlib.sha256(code.encode()).hexdigest(), user_id=user.id,
                                    link_hash=link.token_hash, expires_at=datetime.utcnow()+timedelta(minutes=10)))
        db.session.commit()
        return redirect('https://t.me/'+cfg['bot_username']+'?start='+code)

    @app.route(base+'/settings/customer', methods=['GET', 'POST'])
    @login_required
    def customer_settings():
        if request.args.get('tab') == 'balepay':
            return app.view_functions['balepay_settings']()
        cfg = settings()
        if request.method == 'POST':
            verify_csrf()
            try:
                values = {key: request.form.get(key, str(cfg[key])).strip() for key in cfg if key not in {'plans','bank_cards','admin_chat_ids','custom_pricing','coupons_enabled'}}
                for key, value in values.items():
                    if len(value) > 255 or '\n' in value or '\r' in value:
                        raise ValueError('Invalid settings value.')
                pricing = dict(enabled=request.form.get('pricing_enabled') == '1')
                for key in ('base','per_gb','per_day','per_device'):
                    value = request.form.get('pricing_'+key, str(cfg['custom_pricing'].get(key,0))).translate(FA_DIGITS)
                    if not value.isdigit() or not 0 <= int(value) <= 1000000000:
                        raise ValueError('Pricing rates must be non-negative integer Toman values.')
                    pricing[key] = int(value)
                if pricing['enabled'] and not any(pricing[k] for k in ('base','per_gb','per_day','per_device')):
                    raise ValueError('Set at least one non-zero pricing rate.')
                values['custom_pricing'] = json.dumps(pricing)
                values['card_number'] = re.sub(r'[\s-]', '', values['card_number'].translate(FA_DIGITS))
                if values['card_number'] and not re.fullmatch(r'\d{16}', values['card_number']):
                    raise ValueError('Card number must contain 16 digits.')
                for key in ('admin_telegram', 'bot_username'):
                    values[key] = values[key].lstrip('@')
                    if values[key] and not re.fullmatch(r'[A-Za-z0-9_]{5,64}', values[key]):
                        raise ValueError('Telegram usernames must contain letters, digits and underscore.')
                if values['admin_phone'] and not re.fullmatch(r'\+?[0-9 ()-]{5,30}', values['admin_phone']):
                    raise ValueError('Enter a valid support phone number.')
                if values['admin_chat_id'] and not re.fullmatch(r'-?\d{1,20}', values['admin_chat_id']):
                    raise ValueError('Use the numeric Telegram chat ID, not the username.')
                recipients = list(dict.fromkeys(re.split(r'[\s,;]+', request.form.get('admin_chat_ids', cfg['admin_chat_ids']).strip())))
                recipients = [value for value in recipients if value]
                if len(recipients) > 10 or any(not re.fullmatch(r'-?\d{1,20}', value) for value in recipients):
                    raise ValueError('Enter up to 10 numeric Telegram chat IDs, separated by commas.')
                values['admin_chat_ids'] = ','.join(recipients)
                colors = {'violet','blue','emerald','sunset','rose','midnight'}
                if values['card_color'] not in colors:
                    values['card_color'] = 'violet'
                cards = []
                if values['card_number']:
                    if not values['bank_name'] or not values['card_holder']:
                        raise ValueError('Bank name and card holder are required.')
                    cards.append(dict(id='primary', bank=values['bank_name'], number=values['card_number'], holder=values['card_holder'], color=values['card_color']))
                extra_numbers = request.form.getlist('extra_card_number')
                extra_banks = request.form.getlist('extra_bank_name')
                extra_holders = request.form.getlist('extra_card_holder')
                extra_colors = request.form.getlist('extra_card_color')
                if len(extra_numbers) > 7 or not len(extra_numbers) == len(extra_banks) == len(extra_holders) == len(extra_colors):
                    raise ValueError('Add at most 7 additional bank cards.')
                for i, number in enumerate(extra_numbers):
                    number = re.sub(r'[\s-]', '', number.translate(FA_DIGITS))
                    if not number:
                        if extra_banks[i].strip() or extra_holders[i].strip():
                            raise ValueError('Complete the number of every added card, or remove the card.')
                        continue
                    if not re.fullmatch(r'\d{16}', number) or not extra_banks[i].strip() or not extra_holders[i].strip() or extra_colors[i] not in colors:
                        raise ValueError('Complete every added card and use a 16 digit number.')
                    if any(len(value) > 100 or '\n' in value or '\r' in value for value in (extra_banks[i], extra_holders[i])):
                        raise ValueError('Invalid bank card details.')
                    cards.append(dict(id='extra-'+str(i), bank=extra_banks[i].strip(), number=number, holder=extra_holders[i].strip(), color=extra_colors[i]))
                values['bank_cards'] = json.dumps(cards, ensure_ascii=False)
                if cards and not values['card_number']:
                    values.update(bank_name=cards[0]['bank'], card_number=cards[0]['number'], card_holder=cards[0]['holder'], card_color=cards[0]['color'])
                    cards[0]['id'] = 'primary'
                    values['bank_cards'] = json.dumps(cards, ensure_ascii=False)
                for key in ('admin_email', 'smtp_from'):
                    if values[key] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', values[key]):
                        raise ValueError('Enter a valid email address.')
                if values['smtp_host'] and not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', values['smtp_host']):
                    raise ValueError('SMTP host must be a hostname without a scheme.')
                if not values['smtp_port'].isdigit() or not 1 <= int(values['smtp_port']) <= 65535:
                    raise ValueError('Invalid SMTP port.')
                if values['smtp_security'] not in {'ssl', 'starttls'}:
                    raise ValueError('Choose SSL or STARTTLS.')
                plans = []
                for default in cfg['plans']:
                    if default['id']+'_title' not in request.form:
                        plans.append(default)
                        continue
                    prefix = default['id']+'_'
                    plan = dict(id=default['id'], title=request.form.get(prefix+'title', '').strip()[:100])
                    if not plan['title']:
                        raise ValueError('Plan title is required.')
                    for key, upper in [('days', 3650), ('devices', 100), ('quota', 1000000), ('price', 1000000000)]:
                        value = request.form.get(prefix+key, '').translate(FA_DIGITS)
                        if not value.isdigit() or not 1 <= int(value) <= upper:
                            raise ValueError('Plan days, devices, fair-use quota and price must be positive integers.')
                        plan[key] = int(value)
                    from speed_policy import validate_policy
                    plan.update(validate_policy(request.form.get(prefix+'quota_mode','metered'),request.form.get(prefix+'throttle_down_kbps',2000),request.form.get(prefix+'throttle_up_kbps',2000),plan['quota']))
                    plan['title_en'] = request.form.get(prefix+'title_en', '').strip()[:120]
                    plan['badge_en'] = request.form.get(prefix+'badge_en', '').strip()[:40]
                    plan['badge'] = request.form.get(prefix+'badge', '').strip()[:40]
                    original = request.form.get(prefix+'original_price', '').strip().translate(FA_DIGITS)
                    if original and (not original.isdigit() or not plan['price'] <= int(original) <= 1000000000):
                        raise ValueError('Original price must be at least the current price.')
                    plan['original_price'] = int(original) if original else 0
                    plans.append(plan)
                secrets_cfg = read_secrets()
                bot_secret = request.form.get('bot_token', '').strip()
                if bot_secret and not re.fullmatch(r'\d{5,20}:[A-Za-z0-9_-]{20,100}', bot_secret):
                    raise ValueError('Invalid Telegram bot token.')
                if bot_secret:
                    secrets_cfg['bot_token'] = bot_secret
                smtp_password = request.form.get('smtp_password', '')
                if smtp_password:
                    secrets_cfg['smtp_password'] = smtp_password
                for key in ('bot_token', 'smtp_password'):
                    if request.form.get('clear_'+key) == '1':
                        secrets_cfg.pop(key, None)
                for key, value in values.items():
                    set_setting(key, value)
                # Dedicated catalog editor owns plan writes; payment settings must not overwrite newer prices.
                if any(p['id']+'_title' in request.form for p in cfg['plans']):
                    set_setting('plans', json.dumps(plans, ensure_ascii=False))
                save_secrets(secrets_cfg)
                db.session.commit()
                if request.headers.get('X-Requested-With')=='XMLHttpRequest':
                    return jsonify(success=True,message='Customer and payment settings saved.')
                flash('Customer and payment settings saved.', 'success')
                return redirect(base+'/settings/customer')
            except ValueError as exc:
                db.session.rollback()
                if request.headers.get('X-Requested-With')=='XMLHttpRequest':
                    return jsonify(success=False,message=str(exc)),400
                flash(str(exc), 'error')
        secrets_cfg = read_secrets()
        return render_template('customer_settings.html', panel_path=panel_path, cfg=cfg,
                    bot_configured=bool(secrets_cfg.get('bot_token')), smtp_configured=bool(secrets_cfg.get('smtp_password')))

    @app.route(base+'/settings/notifications', methods=['GET', 'POST'])
    @login_required
    def notification_settings():
        cfg = settings()
        if request.method == 'POST':
            verify_csrf()
            try:
                keys = ('bot_username', 'admin_chat_id', 'admin_chat_ids', 'admin_email',
                        'smtp_host', 'smtp_port', 'smtp_security', 'smtp_user', 'smtp_from')
                values = {key: request.form.get(key, str(cfg.get(key, ''))).strip() for key in keys}
                if any(len(value) > 255 or '\n' in value or '\r' in value for key, value in values.items() if key != 'admin_chat_ids'):
                    raise ValueError('Invalid settings value.')
                values['bot_username'] = values['bot_username'].lstrip('@')
                if values['bot_username'] and not re.fullmatch(r'[A-Za-z0-9_]{5,64}', values['bot_username']):
                    raise ValueError('Invalid bot username.')
                recipients = list(dict.fromkeys(filter(None, re.split(r'[\s,;]+', values['admin_chat_ids']))))
                if len(recipients) > 10 or any(not re.fullmatch(r'-?\d{1,20}', value) for value in recipients):
                    raise ValueError('Enter up to 10 numeric Telegram chat IDs.')
                values['admin_chat_ids'] = ','.join(recipients)
                if values['admin_chat_id'] and not re.fullmatch(r'-?\d{1,20}', values['admin_chat_id']):
                    raise ValueError('Use the numeric Telegram chat ID, not the username.')
                for key in ('admin_email', 'smtp_from'):
                    if values[key] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', values[key]):
                        raise ValueError('Enter a valid email address.')
                if values['smtp_host'] and not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', values['smtp_host']):
                    raise ValueError('Invalid SMTP hostname.')
                if not values['smtp_port'].isdigit() or not 1 <= int(values['smtp_port']) <= 65535:
                    raise ValueError('Invalid SMTP port.')
                if values['smtp_security'] not in {'ssl', 'starttls'}:
                    raise ValueError('Choose SSL or STARTTLS.')
                secret_values = read_secrets()
                token = request.form.get('bot_token', '').strip()
                if token and not re.fullmatch(r'\d{5,20}:[A-Za-z0-9_-]{20,100}', token):
                    raise ValueError('Invalid Telegram bot token.')
                for key, value in (('bot_token', token), ('smtp_password', request.form.get('smtp_password', ''))):
                    if value:
                        secret_values[key] = value
                    if request.form.get('clear_'+key) == '1':
                        secret_values.pop(key, None)
                for key, value in values.items():
                    set_setting(key, value)
                save_secrets(secret_values)
                db.session.commit()
                flash('Notification settings saved.', 'success')
                return redirect(base+'/settings/notifications')
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), 'error')
        secret_values = read_secrets()
        return render_template('notification_settings.html', panel_path=panel_path, cfg=settings(),
                               bot_configured=bool(secret_values.get('bot_token')),
                               smtp_configured=bool(secret_values.get('smtp_password')))

    @app.get(base+'/settings/update')
    @login_required
    def update_page():
        if current_user.role!='owner':abort(403)
        root = Path(app.root_path)
        version = (root/'VERSION').read_text().strip() if (root/'VERSION').exists() else 'Legacy'
        try:
            release = json.loads((root/'.release.json').read_text())
        except (FileNotFoundError, ValueError):
            release = {}
        return render_template('update.html', panel_path=panel_path, version=version, release=release)

    @app.get(base+'/renewals')
    @login_required
    def renewal_inbox():
        page = max(1, request.args.get('page', 1, type=int))
        status = request.args.get('status', 'pending')
        query = RenewalRequest.query
        if status in {'pending', 'completed', 'rejected'}:
            query = query.filter_by(status=status)
        rows = query.order_by(RenewalRequest.id.desc()).paginate(page=page, per_page=30, error_out=False)
        return render_template('renewal_inbox.html', panel_path=panel_path, rows=rows, status=status)

    @app.get(base+'/renewals/<int:request_id>')
    @login_required
    def renewal_detail(request_id):
        row=db.session.get(RenewalRequest,request_id) or abort(404)
        return render_template('renewal_detail.html',row=row,panel_path=panel_path)

    @app.get(base+'/renewals/<int:request_id>/receipt')
    @login_required
    def renewal_receipt(request_id):
        row = db.session.get(RenewalRequest, request_id) or abort(404)
        return private_image(row.receipt)

    @app.post(base+'/renewals/<int:request_id>/review')
    @login_required
    def review_renewal(request_id):
        verify_csrf()
        row = db.session.get(RenewalRequest, request_id) or abort(404)
        action = request.form.get('action')
        if action not in {'completed', 'rejected', 'retry'}:
            abort(400)
        if action == 'retry':
            row.attempts = 0
            row.next_attempt = datetime.utcnow()
            for channel in ('email', 'telegram'):
                if getattr(row, channel+'_state') != 'sent':
                    setattr(row, channel+'_state', 'pending')
        elif action == 'completed':
            from app import experience
            failures = experience.approve_renewal(row)
            if row.source=='reseller_debt':
                flash('Debt verified; sales credit restored.','success');return redirect(base+'/renewals?status=all')
            if row.source=='wallet_topup':
                flash('Payment verified and wallet credited.','success');return redirect(base+'/renewals?status=all')
            flash('Account renewed. Node confirmation pending: '+', '.join(failures) if failures else 'Account renewed and request completed.', 'warning' if failures else 'success')
            return redirect(base+'/renewals?status=all')
        else:
            if row.status != 'pending':
                abort(409, 'This request has already been reviewed.')
            row.status = action
            finish_receipt_grant(row,'rejected')
            row.reviewed_at = datetime.utcnow()
            from app import experience
            experience.notify(row.user_id, 'پرداخت بدهی رد شد' if row.source=='reseller_debt' else 'درخواست شارژ رد شد' if row.source=='wallet_topup' else 'درخواست تمدید رد شد', f'درخواست #{row.id} تأیید نشد؛ برای پیگیری با مدیر تماس بگیرید.')
        db.session.commit()
        if action=='rejected' and db.session.get(ReceiptGrant,row.id):sync_receipt_credit(row)
        flash('Request updated.', 'success')
        return redirect(base+'/renewals?status=all')

    def telegram(method, payload=None, files=None):
        token = read_secrets().get('bot_token')
        if not token:
            raise ValueError('Bot token is not configured.')
        response = requests.post('https://api.telegram.org/bot'+token+'/'+method,
                                 data=payload or {}, files=files, timeout=35 if method == 'getUpdates' else 15)
        if response.status_code != 200 or not response.json().get('ok'):
            raise RuntimeError('Telegram delivery failed (HTTP '+str(response.status_code)+').')
        return response.json()['result']

    def renewal_message(row):
        plan = json.loads(row.plan)
        if row.source=='reseller_debt':return f'پرداخت بدهی نماینده #{row.id}\nنماینده: {row.username}\nمبلغ: {plan["price"]:,} تومان\nتماس: {row.contact}\nپس از بررسی واریز، تأیید کنید تا بدهی کم و اعتبار فروش برگردد.'
        if row.source=='wallet_topup':return f'درخواست شارژ کیف پول #{row.id}\nکاربر: {row.username}\nمبلغ: {plan["price"]:,} تومان\nنام: {row.name}\nتماس: {row.contact}\n{row.note}\nپس از بررسی واریز، درخواست را در صندوق پرداخت‌ها تأیید کنید.'
        return (f'درخواست تمدید #{row.id}\nکاربر: {row.username}\nسرویس: {plan["title"]}\n'
                f'مبلغ: {plan["price"]:,} تومان\nروز: {plan["days"]} | دستگاه: {plan["devices"]} | حد مصرف: {plan["quota"]} GB\n'
                f'نام: {row.name}\nتماس: {row.contact}\nتوضیح: {row.note}\nمنبع: {row.source}\n'
                'رسید نیاز به تأیید مدیر دارد؛ تأیید و تمدید از صندوق درخواست‌ها انجام می‌شود.')

    def receipt_action(row, chat, action, expires=None):
        expires = expires or int(time.time()) + 7*86400
        value = f'{row.id}:{action}:{expires}:{chat}'
        signature = hmac.new(app.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()[:24]
        return f'br:{row.id}:{action}:{expires}:{signature}'

    def receipt_keyboard(row, chat):
        if row.status != 'pending' or row.source not in {'web','portal','telegram','reseller_debt'} or not str(chat).isdigit():
            return None
        return {'inline_keyboard': [[{'text': 'بررسی و تأیید رسید', 'callback_data': receipt_action(row, chat, 'ask')}]]}

    def review_receipt_callback(callback):
        callback_id = callback.get('id', '')
        def answer(text):
            if callback_id:
                telegram('answerCallbackQuery', dict(callback_query_id=callback_id, text=text))
        info = callback.get('message', {}).get('chat', {})
        sender = callback.get('from', {})
        chat = info.get('id')
        if info.get('type') != 'private' or sender.get('is_bot') or str(chat) != str(sender.get('id')) or str(chat) not in admin_recipients(settings()):
            answer('این عملیات فقط برای مدیر ثبت‌شده مجاز است.'); return
        match = re.fullmatch(r'br:(\d+):(ask|yes|no):(\d+):([a-f0-9]{24})', callback.get('data',''))
        if not match:
            answer('درخواست نامعتبر است.'); return
        request_id, action, expires, supplied = match.groups()
        expected = hmac.new(app.secret_key.encode(), f'{request_id}:{action}:{expires}:{chat}'.encode(), hashlib.sha256).hexdigest()[:24]
        if not hmac.compare_digest(expected, supplied) or not int(time.time()) < int(expires) <= int(time.time())+7*86400+30:
            answer('دکمه منقضی یا نامعتبر است؛ از پنل اقدام کنید.'); return
        row = db.session.get(RenewalRequest, int(request_id))
        if not row or row.source not in {'web','portal','telegram','reseller_debt'}:
            answer('این درخواست قابل بررسی در ربات نیست.'); return
        if row.status != 'pending':
            answer('این درخواست قبلاً بررسی شده است.'); return
        if action == 'no':
            answer('تأیید لغو شد؛ رسید همچنان در انتظار بررسی است.'); return
        plan = json.loads(row.plan)
        if action == 'ask':
            answer('مشخصات درخواست را بررسی کنید.')
            keyboard = {'inline_keyboard': [[{'text':'تأیید پرداخت بدهی' if row.source=='reseller_debt' else 'تأیید و تمدید', 'callback_data':receipt_action(row,chat,'yes',int(expires))}, {'text':'انصراف', 'callback_data':receipt_action(row,chat,'no',int(expires))}]]}
            bot_text(chat, f'رسید #{row.id} — {row.username}\nمبلغ: {int(plan["price"]):,} تومان\nتمدید: {plan["days"]} روز / {plan["quota"]} GB\nفقط پس از بررسی واریز واقعی، تأیید کنید.', keyboard)
            return
        from app import experience, security
        from werkzeug.exceptions import HTTPException
        answer('در حال ثبت تأیید و تمدید…')
        try:
            with app.test_request_context():
                failures = experience.approve_renewal(row)
            db.session.add(security.Audit(username='Telegram admin', action='renewal.approve.telegram', details=json.dumps({'request_id':row.id,'chat_id':str(chat)}), address='telegram'))
            db.session.commit()
        except HTTPException:
            db.session.rollback(); bot_text(chat, 'این درخواست قبلاً بررسی شده یا نیازمند بررسی پنل است.'); return
        except Exception:
            db.session.rollback(); app.logger.warning('Telegram receipt review failed for request %s', row.id)
            bot_text(chat, 'ثبت نتیجه کامل نشد؛ وضعیت درخواست را در پنل بررسی کنید.'); return
        bot_text(chat, (f'رسید #{row.id} تأیید شد؛ بدهی نماینده پرداخت و اعتبار فروش بازگردانده شد.' if row.source=='reseller_debt' else f'رسید #{row.id} تأیید شد و تمدید حساب {row.username} ثبت شد.') + (' همگام‌سازی نود در انتظار بررسی است.' if failures else ''))

    def deliver_notifications():
        cfg = settings()
        candidates = RenewalRequest.query.filter(RenewalRequest.attempts < 8,
                RenewalRequest.next_attempt <= datetime.utcnow(),RenewalRequest.receipt!='',
                db.or_(RenewalRequest.email_state != 'sent', RenewalRequest.telegram_state != 'sent')).limit(20).all()
        for row in candidates:
            if row.email_state == 'sent' and row.telegram_state == 'sent':
                continue
            try:
                attachment = (storage / row.receipt).read_bytes()
            except OSError:
                row.email_state = row.telegram_state = 'failed'
                row.attempts = 8
                db.session.commit()
                app.logger.warning('Renewal %s receipt file is missing', row.id)
                continue
            message = renewal_message(row)
            for channel in ('email', 'telegram'):
                if getattr(row, channel+'_state') == 'sent':
                    continue
                try:
                    if channel == 'telegram':
                        recipients = admin_recipients(cfg)
                        if not recipients or not read_secrets().get('bot_token'):
                            setattr(row, channel+'_state', 'unconfigured')
                            continue
                        delivered = json.loads(row.telegram_sent_ids or '[]')
                        failures = False
                        for recipient in recipients:
                            if recipient in delivered:
                                continue
                            try:
                                telegram('sendDocument', dict(chat_id=recipient, caption=message[:1024], reply_markup=json.dumps(receipt_keyboard(row,recipient) or {'inline_keyboard':[]}, ensure_ascii=False)),
                                         files={'document': ('receipt-'+str(row.id)+'.jpg', attachment, 'image/jpeg')})
                                delivered.append(recipient)
                                row.telegram_sent_ids = json.dumps(delivered)
                                db.session.commit()
                            except Exception:
                                failures = True
                        if failures:
                            raise RuntimeError('One or more Telegram deliveries failed.')
                    else:
                        if not cfg['admin_email'] or not cfg['smtp_host'] or not cfg['smtp_from']:
                            setattr(row, channel+'_state', 'unconfigured')
                            continue
                        email = EmailMessage()
                        email['Subject'] = 'Beeny renewal #'+str(row.id)+' — '+row.username
                        email['From'], email['To'] = cfg['smtp_from'], cfg['admin_email']
                        email.set_content(message)
                        email.add_attachment(attachment, maintype='image', subtype='jpeg', filename='receipt.jpg')
                        factory = smtplib.SMTP_SSL if cfg['smtp_security'] == 'ssl' else smtplib.SMTP
                        kwargs = dict(timeout=15)
                        if cfg['smtp_security'] == 'ssl':
                            kwargs['context'] = ssl.create_default_context()
                        with factory(cfg['smtp_host'], int(cfg['smtp_port']), **kwargs) as smtp:
                            if cfg['smtp_security'] == 'starttls':
                                smtp.ehlo()
                                smtp.starttls(context=ssl.create_default_context())
                                smtp.ehlo()
                            if cfg['smtp_user']:
                                smtp.login(cfg['smtp_user'], read_secrets().get('smtp_password', ''))
                            smtp.send_message(email)
                    setattr(row, channel+'_state', 'sent')
                except Exception:
                    # Do not log exceptions containing Telegram tokens or SMTP passwords.
                    setattr(row, channel+'_state', 'failed')
                    app.logger.warning('Renewal %s: %s notification failed', row.id, channel)
            row.attempts += 1
            row.next_attempt = datetime.utcnow()+timedelta(seconds=min(3600, 30 * 2**row.attempts))
            db.session.commit()

    def bot_text(chat, text, keyboard=None):
        payload = dict(chat_id=chat, text=text)
        if keyboard:
            payload['reply_markup'] = json.dumps(keyboard, ensure_ascii=False)
        return telegram('sendMessage', payload)

    menu = dict(keyboard=[['📊 حساب من', '🔗 صفحه شخصی'], ['📥 کانفیگ', '💳 تمدید'], ['🧾 درخواست‌های من', '☎️ پشتیبانی']], resize_keyboard=True)

    def bound_user(chat):
        binding = db.session.get(TelegramAccount, chat)
        if not binding:
            return None, None
        link = db.session.get(AccountLink, binding.user_id)
        user = db.session.get(User, binding.user_id)
        if not user or not link or link.token_hash != binding.link_hash:
            db.session.delete(binding)
            db.session.commit()
            return None, None
        return user, binding

    def is_linked(user_id):
        binding = TelegramAccount.query.filter_by(user_id=user_id).first()
        link = db.session.get(AccountLink, user_id)
        return bool(binding and link and hmac.compare_digest(binding.link_hash, link.token_hash))

    def process_update(event):
        if event.get('callback_query'):
            review_receipt_callback(event['callback_query'])
            return
        message = event.get('message') or {}
        chat_info = message.get('chat', {})
        if chat_info.get('type') != 'private' or not message.get('from') or message['from'].get('is_bot'):
            return
        chat = int(chat_info['id'])
        text = message.get('text', '').strip()
        if text == '/id':
            bot_text(chat, 'Chat ID: '+str(chat))
            return
        if text.startswith('/start '):
            code = text.split(' ', 1)[1]
            digest = hashlib.sha256(code.encode()).hexdigest()
            pair = db.session.get(TelegramPair, digest)
            if not pair or pair.expires_at < datetime.utcnow():
                bot_text(chat, 'لینک اتصال حساب منقضی شده؛ از صفحه شخصی یک لینک جدید بگیرید.')
                return
            link = db.session.get(AccountLink, pair.user_id)
            if not link or link.token_hash != pair.link_hash or not db.session.get(User, pair.user_id):
                bot_text(chat, 'لینک حساب معتبر نیست.')
                return
            # Consume atomically before binding: a code can never bind two chats.
            user_id, link_hash = pair.user_id, pair.link_hash
            consumed = TelegramPair.query.filter_by(digest=digest).delete()
            if not consumed:
                db.session.rollback()
                return
            TelegramAccount.query.filter(db.or_(TelegramAccount.chat_id == chat, TelegramAccount.user_id == user_id)).delete()
            db.session.add(TelegramAccount(chat_id=chat, user_id=user_id, link_hash=link_hash))
            db.session.commit()
            bot_text(chat, 'حساب شما با موفقیت متصل شد. گزینه موردنظر را انتخاب کنید.', menu)
            return
        user, binding = bound_user(chat)
        if not user:
            bot_text(chat, 'برای مشاهده حساب، از صفحه شخصی دکمه «اتصال به ربات» را بزنید.')
            return
        from app import commissions
        cfg = commissions.customer_settings(user,settings())
        if text in {'/start', '/account', '📊 حساب من'}:
            data = account_data(user)
            remaining = f'{data["remaining"]:.2f} GB' if data['remaining'] is not None else 'نامحدود'
            bot_text(chat, f'👤 {user.username}\nوضعیت: {"فعال" if user.status == "active" else "غیرفعال"}\n'
                     f'مصرف دوره: {data["used"]:.2f} GB\nباقی‌مانده: {remaining}\nمصرف امروز: {data["today"]:.3f} GB\n'
                     f'مصرف ۳۰ روز: {data["month"]:.3f} GB\nاعتبار: {data["expiry_text"]}\n'
                     f'دستگاه همزمان: {user.current_devices or 0}/{user.max_devices}', menu)
        elif text in {'/profile', '🔗 صفحه شخصی'}:
            bot_text(chat, 'صفحه شخصی شما (اعتبار لینک: ۳۰ روز):\n'+portal_url(bot_token(user)))
        elif text in {'/config', '📥 کانفیگ'}:
            with app.test_request_context():
                response = app.make_response(build_config(user))
                if response.status_code != 200:
                    bot_text(chat, 'کانفیگ در دسترس نیست؛ با مدیر تماس بگیرید.')
                    return
                response.direct_passthrough = False
                content = response.get_data()
            telegram('sendDocument', dict(chat_id=chat, caption='کانفیگ اتصال '+user.username),
                     files={'document': (user.username+'.ovpn', content, 'application/octet-stream')})
        elif text in {'/renew', '💳 تمدید'}:
            if not cfg['card_number']:
                bot_text(chat, 'اطلاعات پرداخت هنوز ثبت نشده است.')
                return
            lines = ['سرویس خود را انتخاب کنید:']
            for index, plan in enumerate(cfg['plans'], 1):
                lines.append(f'{index}. {plan["title"]} | {plan["price"]:,} تومان | حد مصرف {plan["quota"]} GB')
            lines.append(f'شماره سرویس (۱ تا {len(cfg["plans"])}) را بفرستید.' if cfg['plans'] else 'پلنی برای تمدید فعال نیست؛ با مدیر تماس بگیرید.')
            bot_text(chat, '\n'.join(lines))
        elif text.translate(FA_DIGITS).isdigit() and 1<=int(text.translate(FA_DIGITS))<=len(cfg['plans']):
            plan = cfg['plans'][int(text.translate(FA_DIGITS))-1]
            binding.selected_plan, binding.selected_at = plan['id'], datetime.utcnow()
            db.session.commit()
            bot_text(chat, f'{plan["title"]}\nمبلغ: {plan["price"]:,} تومان\nبانک: {cfg["bank_name"]}\n'
                     f'کارت: {cfg["card_number"]}\nبه نام: {cfg["card_holder"]}\n'
                     'پس از واریز، عکس رسید را همین‌جا ارسال کنید. نام و شماره تماس را در توضیح عکس بنویسید.')
        elif message.get('photo'):
            if not binding.selected_plan or not binding.selected_at or binding.selected_at < datetime.utcnow()-timedelta(hours=1):
                bot_text(chat, 'ابتدا از بخش تمدید، سرویس خود را انتخاب کنید.')
                return
            try:
                photo = message['photo'][-1]
                if photo.get('file_size', 0) > MAX_UPLOAD:
                    raise ValueError('رسید باید حداکثر ۲۰ مگابایت باشد.')
                info = telegram('getFile', dict(file_id=photo['file_id']))
                file_path = info['file_path']
                if not re.fullmatch(r'[A-Za-z0-9_./-]+', file_path) or '..' in file_path:
                    raise ValueError('تصویر دریافت نشد.')
                secret = read_secrets()['bot_token']
                with requests.get('https://api.telegram.org/file/bot'+secret+'/'+file_path,
                                  timeout=15, stream=True) as response:
                    response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_content(65536):
                        content.extend(chunk)
                        if len(content) > MAX_UPLOAD:
                            raise ValueError('رسید باید حداکثر ۲۰ مگابایت باشد.')
                row = create_request(user, binding.selected_plan, bytes(content),
                          message['from'].get('first_name', ''), 'Telegram chat '+str(chat),
                          message.get('caption', ''), source='telegram')
                binding.selected_plan = None
                db.session.commit()
                if db.session.get(ReceiptGrant,row.id):sync_receipt_credit(row)
                bot_text(chat, f'درخواست #{row.id} ثبت شد. پس از بررسی واریز، مدیر حساب را تمدید می‌کند.' + (' ۵ گیگ اعتبار موقت ۲۴ ساعته فعال شد.' if db.session.get(ReceiptGrant,row.id) else ''), menu)
            except ValueError as exc:
                bot_text(chat, str(exc))
        elif text in {'/cancel', 'لغو'}:
            binding.selected_plan = None
            db.session.commit()
            bot_text(chat, 'انتخاب سرویس لغو شد.', menu)
        elif text in {'/requests', '🧾 درخواست‌های من'}:
            rows = RenewalRequest.query.filter_by(user_id=user.id).order_by(RenewalRequest.id.desc()).limit(5).all()
            labels = {'pending': 'در انتظار بررسی', 'completed': 'تمدید انجام شد', 'rejected': 'رد شده'}
            bot_text(chat, '\n'.join(f'#{r.id} • {json.loads(r.plan)["title"]} • {labels[r.status]}' for r in rows) or 'هنوز درخواستی ثبت نشده است.')
        elif text in {'/support', '☎️ پشتیبانی'}:
            bot_text(chat, 'پشتیبانی:\n'+('\n'.join(filter(None, [cfg['admin_phone'], '@'+cfg['admin_telegram'] if cfg['admin_telegram'] else ''])) or 'از صفحه شخصی پیگیری کنید.'))
        elif text == '/unlink':
            db.session.delete(binding)
            db.session.commit()
            bot_text(chat, 'اتصال ربات به حساب شما حذف شد.')
        else:
            bot_text(chat, 'از منو انتخاب کنید یا /account را بفرستید.', menu)

    def poll_bot():
        if not read_secrets().get('bot_token'):
            return
        offset = int(get_setting('telegram_offset', '0'))
        events = telegram('getUpdates', dict(offset=offset, timeout=20, allowed_updates='["message","callback_query"]'))
        for event in events:
            # At-least-once handling. Request limits prevent duplicate receipt requests on retry.
            process_update(event)
            set_setting('telegram_offset', event['update_id']+1)
            db.session.commit()

    def delete_customer(user_id):
        from app import representative_credit
        from app import representative_actions
        representative_actions.detach(user_id)
        representative_credit.detach(user_id)
        from app import support,commerce,TrafficDailyUser,resellers,portal_content,commissions
        commissions.detach(user_id)
        portal_content.Seen.query.filter_by(user_id=user_id).delete()
        resellers.Grant.query.filter_by(user_id=user_id).delete()
        resellers.Profile.query.filter_by(user_id=user_id).delete()
        for child in User.query.filter_by(reseller_id=user_id).all():child.reseller_id=-user_id
        for order in resellers.Order.query.filter_by(reseller_id=user_id).all():order.reseller_id=-user_id
        for order in resellers.Order.query.filter_by(user_id=user_id).all():order.user_id=-user_id
        for renewal in resellers.Renewal.query.filter_by(reseller_id=user_id).all():renewal.reseller_id=-user_id
        for renewal in resellers.Renewal.query.filter_by(user_id=user_id).all():renewal.user_id=-user_id
        for daily in TrafficDailyUser.query.filter_by(user_id=user_id).all():daily.user_id=-daily.id
        commerce.Wallet.query.filter_by(user_id=user_id).delete()
        for entry in commerce.Entry.query.filter_by(user_id=user_id).all():entry.user_id=-entry.id
        for invoice in commerce.Invoice.query.filter_by(user_id=user_id).all():invoice.user_id=-invoice.id
        for ticket in support.Ticket.query.filter_by(user_id=user_id).all():ticket.user_id=-ticket.id
        profile = db.session.get(CustomerProfile, user_id)
        if profile and profile.avatar:
            (storage / profile.avatar).unlink(missing_ok=True)
        from app import experience
        experience.Notification.query.filter_by(user_id=user_id).delete()
        CustomerProfile.query.filter_by(user_id=user_id).delete()
        TelegramAccount.query.filter_by(user_id=user_id).delete()
        TelegramPair.query.filter_by(user_id=user_id).delete()
        ReceiptGrant.query.filter_by(user_id=user_id).update(dict(user_id=-user_id,active=False,state='deleted'))
        # Keep admin receipt history, but detach it from a potentially reused user ID.
        for historic in RenewalRequest.query.filter_by(user_id=user_id).all():
            historic.user_id = -historic.id

    @app.route(panel_path.rstrip('/')+'/settings/plans',methods=['GET'])
    @login_required
    def plan_catalog():
        if getattr(current_user,'role','')!='owner':abort(403)
        return render_template('plan_catalog.html',plans=settings()['plans'],panel_path=panel_path)

    @app.route(panel_path.rstrip('/')+'/settings/plans/<plan_id>',methods=['GET','POST'])
    @login_required
    def plan_editor(plan_id):
        if getattr(current_user,'role','')!='owner':abort(403)
        import hashlib
        raw_plans=get_setting('plans',None)
        plans=settings()['plans']
        existing=next((p for p in plans if p['id']==plan_id),None)
        if plan_id!='new' and existing is None:abort(404)
        version=hashlib.sha256(json.dumps(plans,sort_keys=True).encode()).hexdigest()
        if request.method=='POST':
            verify_csrf()
            if request.form.get('version')!=version:return jsonify(success=False,message='Plans changed in another session. Reload before saving.'),409
            try:
                plan=dict(existing) if existing else dict(id='plan_'+secrets.token_hex(8))
                for key,limit in [('title',100),('title_en',120),('badge',40),('badge_en',40)]:plan[key]=request.form.get(key,'').strip()[:limit]
                if not plan['title']:raise ValueError('A plan title is required.')
                for key,limit in [('days',3650),('quota',1000000),('devices',100),('price',1000000000)]:
                    value=request.form.get(key,'').translate(FA_DIGITS)
                    if not value.isascii() or not value.isdigit() or not 1<=int(value)<=limit:raise ValueError('Invalid '+key)
                    plan[key]=int(value)
                from speed_policy import validate_policy
                plan.update(validate_policy(request.form.get('quota_mode','metered'),request.form.get('throttle_down_kbps',2000),request.form.get('throttle_up_kbps',2000),plan['quota']))
                for key,limit in [('gift_days',3650),('gift_quota',1000000)]:
                    value=request.form.get(key,'0').translate(FA_DIGITS)
                    if not value.isascii() or not value.isdigit() or not 0<=int(value)<=limit:raise ValueError('Invalid '+key)
                    plan[key]=int(value)
                from pricing import with_gift
                with_gift(plan,plan['gift_days'],plan['gift_quota'])
                original=request.form.get('original_price','0').translate(FA_DIGITS) or '0'
                if not original.isascii() or not original.isdigit():raise ValueError('Invalid original price.')
                plan['original_price']=int(original)
                if plan['original_price'] and not plan['price']<=plan['original_price']<=1000000000:raise ValueError('Original price must be at least the selling price.')
            except ValueError as exc:return jsonify(success=False,message=str(exc)),400
            plans=[plan if row['id']==plan_id else row for row in plans] if existing else plans+[plan]
            # Compare-and-swap guards against two editors committing the same revision.
            from sqlalchemy import update
            from sqlalchemy.exc import IntegrityError
            encoded=json.dumps(plans,ensure_ascii=False)
            try:
                if raw_plans is None:
                    db.session.add(CustomerSetting(key='plans',value=encoded))
                    db.session.flush()
                else:
                    changed=db.session.execute(update(CustomerSetting).where(CustomerSetting.key=='plans',CustomerSetting.value==raw_plans).values(value=encoded),execution_options={'synchronize_session':False}).rowcount
                    if changed!=1:
                        db.session.rollback()
                        return jsonify(success=False,message='Plans changed in another session. Reload before saving.'),409
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                return jsonify(success=False,message='Plans changed in another session. Reload before saving.'),409
            return jsonify(success=True,message='Plan saved.',redirect=panel_path.rstrip('/')+'/settings/plans')
        return render_template('plan_editor.html',plan=existing or {},version=version,panel_path=panel_path)

    return SimpleNamespace(receipt_counter_started=receipt_counter_started, ReceiptGrant=ReceiptGrant, finish_receipt_grant=finish_receipt_grant, expire_receipt_grants=expire_receipt_grants, receipt_action=receipt_action,receipt_keyboard=receipt_keyboard,verify_csrf=verify_csrf, delete_customer=delete_customer, render_portal=render_portal, resolve_bot_token=resolve_bot_token,
            store_image=store_image,deliver_notifications=deliver_notifications, poll_bot=poll_bot, process_update=process_update,
            settings=settings, set_setting=set_setting, save_secrets=save_secrets, create_request=create_request,
            RenewalRequest=RenewalRequest, CustomerSetting=CustomerSetting, CustomerProfile=CustomerProfile,
            get_setting=get_setting, telegram=telegram, bound_user=bound_user, storage=storage, resolve_account=resolve_account, is_linked=is_linked,
            TelegramPair=TelegramPair, TelegramAccount=TelegramAccount, account_data=account_data, CustomerLoginAttempt=CustomerLoginAttempt)
