"""Private customer activity, durable notifications and customer-controlled pause."""
import json
import math
import secrets
import time
from datetime import datetime, timedelta, date
from types import SimpleNamespace
from flask import abort, jsonify, request, flash, redirect
from flask_login import login_required, current_user
from sqlalchemy import event, inspect, update
from renewal import activation_error, extend_expiry


def register(app, db, User, Node, UserNode, features, panel_path, is_primary_node):
    base = panel_path.rstrip('/')

    class Notification(db.Model):
        __tablename__ = 'account_notifications'
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, index=True)  # NULL is the admin feed.
        title = db.Column(db.String(200), nullable=False)
        body = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        read_at = db.Column(db.DateTime)
        dedupe = db.Column(db.String(200), unique=True)
        telegram_state = db.Column(db.String(20), default='pending')
        cleared_at = db.Column(db.DateTime)
        attempts = db.Column(db.Integer, default=0)
        next_attempt = db.Column(db.DateTime, default=datetime.utcnow)

    class AdminRead(db.Model):
        __tablename__ = 'admin_notification_reads'
        notification_id = db.Column(db.Integer, primary_key=True)
        admin_id = db.Column(db.Integer, primary_key=True)
        cleared = db.Column(db.Boolean, default=False, nullable=False)

    def notify(user_id, title, body, dedupe=None):
        if dedupe and Notification.query.filter_by(dedupe=dedupe).first():
            return
        db.session.add(Notification(user_id=user_id, title=title, body=body, dedupe=dedupe,
                                    telegram_state='pending' if user_id else 'skipped'))

    @event.listens_for(User.traffic_usage, 'set', active_history=True)
    def load_previous_usage(target, value, previous, initiator):
        # Preserve the old value in history even when the attribute expired on commit.
        # The flush listener uses that history to distinguish resets from normal usage.
        pass

    @event.listens_for(db.session.session_factory.class_, 'before_flush')
    def track_changes(session, flush_context, instances):
        for obj in list(session.new):
            if isinstance(obj, User):
                notify(None, 'Account created', f'{obj.username} was added to the panel.')
            if isinstance(obj, features.RenewalRequest):
                notify(None, 'New renewal request', f'{obj.username} submitted a receipt. Review it in the renewal inbox.')
                notify(obj.user_id, 'درخواست تمدید ثبت شد', 'رسید شما دریافت شد و منتظر بررسی مدیر است.')
        names = {'expire_date':'اعتبار زمانی', 'traffic_limit':'حجم مجاز', 'max_devices':'تعداد دستگاه',
                 'status':'وضعیت حساب', 'customer_paused':'توقف شخصی'}
        for obj in list(session.dirty):
            if not isinstance(obj, User):
                continue
            changed = [label for name, label in names.items() if inspect(obj).attrs[name].history.has_changes()]
            usage = inspect(obj).attrs.traffic_usage.history
            reset = bool(usage.deleted and usage.added and (usage.added[0] or 0) < (usage.deleted[0] or 0))
            if reset or any(inspect(obj).attrs[name].history.has_changes() for name in ('expire_date','traffic_limit')):
                obj.notification_revision = (obj.notification_revision or 0)+1
            if reset:
                changed.append('صفرشدن مصرف دوره')
            if changed:
                details = []
                for name, label in names.items():
                    if inspect(obj).attrs[name].history.has_changes():
                        value = getattr(obj, name)
                        if name == 'status':
                            value = 'فعال' if value == 'active' else 'محدودشده'
                        elif name == 'customer_paused':
                            value = 'متوقف' if value else 'توقف برداشته شد'
                        elif name == 'traffic_limit':
                            value = f'{value} گیگابایت' if value else 'نامحدود'
                        details.append(f'{label}: {value}')
                if reset:
                    details.append('مصرف دوره صفر شد؛ تاریخچه مصرف حفظ شده است.')
                notify(obj.id, 'اطلاعات حساب تغییر کرد', '\n'.join(details))
                notify(None, 'Account updated', f'{obj.username}: account settings were changed.')

    def feed(user_id):
        query = Notification.query.filter_by(user_id=user_id)
        if user_id is None:
            cleared_ids = db.select(AdminRead.notification_id).where(AdminRead.admin_id == current_user.id, AdminRead.cleared.is_(True))
            query = query.filter(Notification.id.not_in(cleared_ids))
        else:
            query = query.filter(Notification.cleared_at.is_(None))
        if user_id is None:
            read_ids = db.select(AdminRead.notification_id).where(AdminRead.admin_id == current_user.id)
            unread = query.filter(Notification.id.not_in(read_ids)).count()
        else:
            unread = query.filter(Notification.read_at.is_(None)).count()
        rows = query.order_by(Notification.id.desc()).limit(30).all()
        read_marks = set(db.session.scalars(db.select(AdminRead.notification_id).where(AdminRead.admin_id == current_user.id, AdminRead.notification_id.in_([row.id for row in rows])))) if user_id is None else set()
        return jsonify(unread=unread, latest_id=rows[0].id if rows else 0,
                       items=[dict(id=row.id, title=row.title, body=row.body, read=(row.id in read_marks if user_id is None else row.read_at is not None),
                                   created=row.created_at.isoformat()+'Z') for row in rows])

    @app.get(base+'/c/<token>/notifications')
    def customer_notifications(token):
        return feed(features.resolve_account(token).id)

    @app.post(base+'/c/<token>/notifications/read')
    def customer_notifications_read(token):
        user = features.resolve_account(token)
        features.verify_csrf()
        upto = request.form.get('upto', 0, type=int)
        Notification.query.filter(Notification.user_id == user.id, Notification.id <= upto,
                                  Notification.read_at.is_(None)).update(dict(read_at=datetime.utcnow()))
        db.session.commit()
        return jsonify(ok=True)

    @app.get(base+'/notifications')
    @login_required
    def admin_notifications():
        return feed(None)

    @app.post(base+'/notifications/read')
    @login_required
    def admin_notifications_read():
        features.verify_csrf()
        upto = request.form.get('upto', 0, type=int)
        rows = Notification.query.filter(Notification.user_id.is_(None), Notification.id <= upto).all()
        for row in rows:
            if not db.session.get(AdminRead, (row.id, current_user.id)):
                db.session.add(AdminRead(notification_id=row.id, admin_id=current_user.id))
        db.session.commit()
        return jsonify(ok=True)

    @app.post(base+'/c/<token>/notifications/clear')
    def customer_notifications_clear(token):
        user = features.resolve_account(token)
        features.verify_csrf()
        upto = request.form.get('upto', 0, type=int)
        Notification.query.filter(Notification.user_id == user.id, Notification.id <= upto).update(
            dict(cleared_at=datetime.utcnow(), read_at=datetime.utcnow()))
        db.session.commit()
        return jsonify(ok=True)

    @app.post(base+'/notifications/clear')
    @login_required
    def admin_notifications_clear():
        features.verify_csrf()
        upto = request.form.get('upto', 0, type=int)
        for row in Notification.query.filter(Notification.user_id.is_(None), Notification.id <= upto):
            mark = db.session.get(AdminRead, (row.id, current_user.id))
            if mark is None:
                mark = AdminRead(notification_id=row.id, admin_id=current_user.id)
                db.session.add(mark)
            mark.cleared = True
        db.session.commit()
        return jsonify(ok=True)

    def sync_access(user):
        from app import sync_primary_access, kick_user_globally
        from cluster import set_user_state_on_node,create_user_on_node
        from app import devices
        from types import SimpleNamespace
        registered=devices.Device.query.filter_by(user_id=user.id).all()
        device_failed={device.id:False for device in registered}
        from vpn_sessions import local_sessions, disconnect_session
        db.session.refresh(user)
        from app import speed_policy
        speed_failures=speed_policy.sync(user)
        enabled = user.status == 'active' and not user.customer_paused and not activation_error(
            user.expire_date, user.traffic_limit or 0, user.traffic_usage or 0, quota_mode=getattr(user,'quota_mode','metered'))
        from app import representative_credit
        from app import representative_actions
        enabled=enabled and not representative_credit.suspended(user) and not representative_actions.blocked(user)
        selected = [rel.node_id for rel in UserNode.query.filter_by(user_id=user.id)]
        nodes = Node.query.all()
        failures = list(speed_failures)
        primary_selected = any(is_primary_node(n) and n.id in selected for n in nodes)
        try:
            sync_primary_access(user, primary_selected and bool(enabled))
            if primary_selected:
                connections = local_sessions(user.username)
                if not enabled:
                    for connection in connections:
                        try:
                            disconnect_session(user.username, connection['id'], connection['fingerprint'])
                        except ValueError:
                            # A device which disconnected during the snapshot needs no kick.
                            pass
        except (OSError, RuntimeError):
            failures.append('Primary')
            device_failed={device.id:True for device in registered}
        for node in nodes:
            if node.id in selected and not is_primary_node(node):
                try:
                    from app import devices
                    ok, _ = set_user_state_on_node(node, user.username, bool(enabled))
                    for device in registered:
                        provision=True
                        if device.pending:provision=str(create_user_on_node(node,SimpleNamespace(username=device.common_name))).startswith('Success:')
                        device_ok,_=set_user_state_on_node(node,device.common_name,bool(enabled) and not device.blocked)
                        device_failed[device.id]=device_failed[device.id] or not (device_ok and provision)
                        ok=ok and device_ok and provision
                    if not ok:
                        failures.append(node.name)
                except Exception:
                    failures.append(node.name)
                    device_failed={device.id:True for device in registered}
        for device in registered:device.pending=device_failed[device.id]
        user.pause_sync_pending = bool(failures)
        db.session.commit()
        return failures

    @app.post(base+'/c/<token>/pause')
    def customer_pause(token):
        user = features.resolve_account(token)
        features.verify_csrf()
        desired = request.form.get('paused')
        if desired not in {'0', '1'}:
            abort(400)
        from app import representative_credit
        if desired == '0' and (representative_credit.suspended(user) or user.status != 'active' or activation_error(user.expire_date, user.traffic_limit or 0, user.traffic_usage or 0, quota_mode=getattr(user,'quota_mode','metered'))):
            flash('حساب توسط مدیر یا به‌علت پایان اعتبار محدود شده است؛ برای فعال‌سازی با پشتیبانی تماس بگیرید.', 'error')
            return redirect(base+'/c/'+token+'#profile')
        user.customer_paused = desired == '1'
        user.pause_sync_pending = True
        db.session.commit()
        failures = sync_access(user)
        if failures:
            flash('تغییر ذخیره شد؛ تأیید بعضی نودها دریافت نشده و دوباره تلاش می‌شود.', 'warning')
        else:
            flash('اتصال حساب متوقف شد.' if user.customer_paused else 'توقف شخصی برداشته شد.', 'success')
        return redirect(base+'/c/'+token+'#profile')

    def approve_renewal(row):
        from app import representative_actions
        account_user=db.session.get(User,row.user_id)
        if account_user and representative_actions.blocked(account_user):abort(409,'حساب در حال بایگانی است؛ پرداخت باید توسط مدیر تعیین تکلیف شود.')
        # The conditional UPDATE serializes competing approvals; quota/days apply once.
        changed = db.session.execute(update(features.RenewalRequest).where(
            features.RenewalRequest.id == row.id, features.RenewalRequest.status == 'pending'
        ).values(status='completed', reviewed_at=datetime.utcnow()))
        if changed.rowcount != 1:
            abort(409, 'This request has already been reviewed.')
        user = db.session.get(User, row.user_id)
        if not user:
            db.session.rollback()
            abort(409, 'The account no longer exists.')
        from app import sales_engine
        sales_engine.renewal_receipt(row)
        if row.source=='reseller_debt':
            from app import representative_credit
            representative_credit.approve_debt(row)
            db.session.commit()
            representative_credit.sync_children(user.id)
            return []
        features.finish_receipt_grant(row,'approved')
        plan = json.loads(row.plan)
        if row.source=='wallet_topup':
            from app import commerce
            from flask_login import current_user
            amount=plan.get('price')
            if not isinstance(amount,int) or not 1000<=amount<=100000000:
                db.session.rollback();abort(400,'Invalid wallet top-up amount.')
            wallet=db.session.get(commerce.Wallet,user.id)
            if not wallet:wallet=commerce.Wallet(user_id=user.id,balance=0);db.session.add(wallet);db.session.flush()
            changed=db.session.execute(update(commerce.Wallet).where(commerce.Wallet.user_id==user.id,commerce.Wallet.balance+amount<=10000000000).values(balance=commerce.Wallet.balance+amount)).rowcount
            if changed!=1:db.session.rollback();abort(409,'Wallet balance limit exceeded.')
            db.session.add(commerce.Entry(user_id=user.id,amount=amount,reason=f'شارژ تأییدشده #{row.id}',reference='topup:'+row.billing_reference,admin_id=current_user.id if current_user.is_authenticated else None))
            notify(user.id,'کیف پول شما شارژ شد',f'{amount:,} تومان پس از تأیید رسید #{row.id} به موجودی اضافه شد. اکنون می‌توانید سرویس را از کیف پول تمدید کنید.')
            notify(None,'Wallet credited',f'Request #{row.id}: {amount:,} Toman credited to {user.username}.')
            db.session.commit();return []
        from pricing import service_allowance
        plan=service_allowance(plan)
        user.expire_date = extend_expiry(user.expire_date, int(plan['days']))
        user.traffic_limit = max(user.traffic_limit or 0, math.ceil(user.traffic_usage or 0)) + int(plan['quota'])
        if 'quota_mode' in plan:
            from speed_policy import validate_policy
            for key,value in validate_policy(plan['quota_mode'],plan.get('throttle_down_kbps',2000),plan.get('throttle_up_kbps',2000),plan['quota']).items():setattr(user,key,value)
        user.max_devices = int(plan['devices'])
        user.status = 'active'
        user.pause_sync_pending = True
        notify(user.id, 'تمدید شما انجام شد', f'درخواست #{row.id} تأیید شد: {plan["days"]} روز و {plan["quota"]} گیگابایت اضافه شد. توقف شخصی شما، در صورت فعال بودن، حفظ شده است.')
        notify(None, 'Renewal approved', f'Request #{row.id} renewed {user.username}.')
        from app import commerce
        commerce.record_invoice(row)
        db.session.commit()
        failures=sync_access(user)
        if not failures:
            from app import commissions
            commissions.release(row.billing_reference,confirmed=True)
        return failures

    @app.post(base+'/renewals/<int:request_id>/delete')
    @login_required
    def delete_renewal(request_id):
        features.verify_csrf()
        row = db.session.get(features.RenewalRequest, request_id) or abort(404)
        filename = row.receipt
        # Unlink first: a permission error retains the request for a later retry.
        file = (features.storage/filename).resolve() if filename else None
        if file and file.parent != features.storage.resolve():
            abort(400)
        try:
            if file:file.unlink(missing_ok=True)
        except OSError:
            abort(409, 'Receipt could not be deleted. Check storage permissions.')
        notify(None, 'Renewal request deleted', f'Request #{row.id} and its receipt were deleted.')
        if db.session.get(User, row.user_id):
            notify(row.user_id, 'درخواست حذف شد', f'درخواست #{row.id} و تصویر رسید توسط مدیر حذف شد. برای پیگیری با پشتیبانی تماس بگیرید.')
        db.session.delete(row)
        db.session.commit()
        flash('Request and receipt deleted from the server.', 'success')
        return redirect(base+'/renewals?status=all')

    last_scan = [0]
    def worker_cycle(force_scan=False):
        now = datetime.utcnow()
        if force_scan or time.monotonic()-last_scan[0] > 60:
            for user in User.query.all():
                if user.expire_date and user.expire_date not in {'-', ''} and not user.expire_date.isdigit():
                    try:
                        days = (date.fromisoformat(user.expire_date)-date.today()).days
                        if 0 <= days <= 3:
                            notify(user.id, 'اعتبار حساب رو به پایان است', f'{days} روز از اعتبار شما باقی مانده است.',
                                   f'days:{user.id}:{user.expire_date}:{user.notification_revision}')
                    except ValueError:
                        pass
                remaining = (user.traffic_limit or 0)-(user.traffic_usage or 0)
                if user.traffic_limit and remaining <= max(1, user.traffic_limit*.1):
                    notify(user.id, 'حجم حساب رو به پایان است', f'{max(0,remaining):.2f} گیگابایت باقی مانده است.',
                           f'data:{user.id}:{user.traffic_limit}:{user.expire_date}:{user.notification_revision}')
            db.session.commit()
            for user in User.query.filter_by(pause_sync_pending=True).limit(20):
                sync_access(user)
            last_scan[0] = time.monotonic()
        rows = Notification.query.filter(Notification.user_id.is_not(None), Notification.telegram_state == 'pending',
                Notification.attempts < 8, Notification.next_attempt <= now).order_by(Notification.id).limit(20).all()
        for row in rows:
            binding = features.TelegramAccount.query.filter_by(user_id=row.user_id).first()
            if not binding:
                row.telegram_state = 'skipped'
            else:
                user, _ = features.bound_user(binding.chat_id)
                if not user:
                    row.telegram_state = 'skipped'
                else:
                    try:
                        features.telegram('sendMessage', dict(chat_id=binding.chat_id, text=row.title+'\n'+row.body))
                        row.telegram_state = 'sent'
                    except Exception:
                        row.attempts += 1
                        row.next_attempt = now+timedelta(seconds=min(3600,30*2**row.attempts))
            db.session.commit()

    @app.context_processor
    def context():
        return dict(customer_telegram_connected=features.is_linked,
                    customer_can_enable=lambda user: user.status == 'active' and not __import__('app').representative_credit.suspended(user) and not __import__('app').representative_actions.blocked(user) and not activation_error(user.expire_date, user.traffic_limit or 0, user.traffic_usage or 0, quota_mode=getattr(user,'quota_mode','metered')))

    return SimpleNamespace(Notification=Notification, AdminRead=AdminRead, notify=notify,
                           worker_cycle=worker_cycle, approve_renewal=approve_renewal, sync_access=sync_access)
