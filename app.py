#!/usr/bin/env python3
"""
Beeny Panel - VPN Management System (Fully Integrated & Fixed)
"""

from flask import Flask, render_template, request, redirect, send_file, jsonify, session, abort
from asset_delivery import register as register_asset_delivery
import subprocess
import os
from threading import Thread
import time
from datetime import datetime, timedelta
import shutil
import json
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
import psutil
from werkzeug.utils import secure_filename
import ssl
import requests
from cluster import node_url
import io
import math
import re
import socket
import secrets
import hashlib
from flask_login import current_user
from privileged import call as privileged_call, enabled as privileged_enabled
from renewal import extend_expiry, activation_error
from traffic_ledger import parse_status, usage_delta

PRIMARY_NODE_KEY = "__beeny_local_primary__"

# Load config
CONFIG_FILE = os.environ.get("BEENY_CONFIG_FILE", "/opt/beeny-panel/config.json")
config = {}
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)

PANEL_PATH = config.get('panel_path', '/')
PANEL_PATH = PANEL_PATH.strip()
if PANEL_PATH != "/":
    PANEL_PATH = "/" + PANEL_PATH.strip("/")
else:
    PANEL_PATH = "/"

app = Flask(__name__, instance_path=os.environ.get("BEENY_INSTANCE_PATH", os.path.abspath(os.path.join(os.path.dirname(__file__), "instance"))))
register_asset_delivery(app)
app.config["SECRET_KEY"] = os.environ.get("BEENY_SECRET_KEY", "")
if not app.config["SECRET_KEY"]:
    raise RuntimeError("BEENY_SECRET_KEY must be set by the installer")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("BEENY_PUBLIC_HTTPS") == "1"
app.config["REMEMBER_COOKIE_SECURE"] = app.config["SESSION_COOKIE_SECURE"]
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=7)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("BEENY_DATABASE_URI", "sqlite:///beeny.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


# ==================== MODELS ====================

class Admin(UserMixin, db.Model):
    language = db.Column(db.String(2),nullable=False,default="en")
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(255))
    role = db.Column(db.String(20), default="owner", nullable=False)
    node_scope = db.Column(db.Boolean,nullable=False,default=False)
    totp_secret = db.Column(db.Text)
    totp_counter = db.Column(db.BigInteger, default=-1)
    recovery_codes = db.Column(db.Text, default="[]")

    def get_id(self):
        token = session.get("panel_session_token")
        return f"{self.id}:{token}" if token else str(self.id)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    owner_id = db.Column(db.Integer, index=True)
    reseller_id = db.Column(db.Integer, index=True)
    protocol = db.Column(db.String(20), default="openvpn")
    max_devices = db.Column(db.Integer, default=1)
    current_devices = db.Column(db.Integer, default=0)
    expire_date = db.Column(db.String(20))
    status = db.Column(db.String(20), default="active")
    disable_reason = db.Column(db.String(20), nullable=False, default="legacy")
    removal_pending = db.Column(db.Boolean, default=False, nullable=False)
    customer_paused = db.Column(db.Boolean, default=False, nullable=False)
    pause_sync_pending = db.Column(db.Boolean, default=False, nullable=False)
    notification_revision = db.Column(db.Integer, default=0, nullable=False)
    online = db.Column(db.Boolean, default=False)
    online_status = db.Column(db.String(20), default="offline")
    quota_mode = db.Column(db.String(20), nullable=False, default='metered')
    throttle_down_kbps = db.Column(db.Integer, nullable=False, default=2000)
    throttle_up_kbps = db.Column(db.Integer, nullable=False, default=2000)
    speed_state = db.Column(db.Text, nullable=False, default='')
    speed_sync_pending = db.Column(db.Boolean, nullable=False, default=False)
    traffic_limit = db.Column(db.Integer, default=10)
    traffic_usage = db.Column(db.Float, default=0)
    traffic_used = db.Column(db.BigInteger, default=0)
    last_session_bytes = db.Column(db.BigInteger, default=0)

@event.listens_for(User.status, 'set', active_history=True)
def remember_account_disable_reason(target, value, previous, initiator):
    if value == 'disabled':target.disable_reason = 'admin'
    elif value == 'active':target.disable_reason = ''

class Node(db.Model):
    __tablename__ = "nodes"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    ip = db.Column(db.String(100), nullable=False)
    host = db.Column(db.String(255))
    country = db.Column(db.String(50), default="")
    protocol = db.Column(db.String(20), default="OpenVPN")
    api_key = db.Column(db.String(255), default="")
    status = db.Column(db.String(20), default="offline")

class UserNode(db.Model):
    __tablename__ = "user_nodes"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    node_id = db.Column(db.Integer)

class UserSession(db.Model):
    __tablename__ = "user_sessions"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100))
    node_id = db.Column(db.Integer)
    connections = db.Column(db.Integer, default=0)
    last_seen = db.Column(db.DateTime)


class TrafficSample(db.Model):
    """Last observed counter for a single OpenVPN session on one server."""
    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.Integer, nullable=False, index=True)
    session_key = db.Column(db.String(512), nullable=False)
    last_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    last_received = db.Column(db.BigInteger, nullable=False, default=0)
    last_sent = db.Column(db.BigInteger, nullable=False, default=0)
    __table_args__ = (db.UniqueConstraint('node_id', 'session_key'),)


class TrafficBaseline(db.Model):
    """First legacy snapshot must not re-count traffic in existing customer quotas."""
    node_id = db.Column(db.Integer, primary_key=True)
    pending = db.Column(db.Boolean, nullable=False, default=True)


class TrafficDaily(db.Model):
    """VPN bytes measured per day and server; independent of user accounts."""
    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.Integer, nullable=False, index=True)
    node_name = db.Column(db.String(100), nullable=False)
    day = db.Column(db.String(10), nullable=False, index=True)
    bytes_total = db.Column(db.BigInteger, nullable=False, default=0)
    bytes_received = db.Column(db.BigInteger, nullable=False, default=0)
    bytes_sent = db.Column(db.BigInteger, nullable=False, default=0)
    __table_args__ = (db.UniqueConstraint('node_id', 'day'),)


class TrafficDailyUser(db.Model):
    """Historic consumption stays visible after the current quota is reset."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    day = db.Column(db.String(10), nullable=False, index=True)
    bytes_total = db.Column(db.BigInteger, nullable=False, default=0)
    __table_args__ = (db.UniqueConstraint('user_id', 'day'),)


class AccountLink(db.Model):
    user_id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


def is_primary_node(node):
    return bool(node and node.api_key == PRIMARY_NODE_KEY)


def ensure_primary_node():
    """Register the VPN on this panel host as a selectable node once."""
    public_host = os.environ.get("BEENY_PUBLIC_HOST", "").strip()
    if not public_host:
        raise RuntimeError("BEENY_PUBLIC_HOST is required for the primary VPN node")
    primary = Node.query.filter_by(api_key=PRIMARY_NODE_KEY).first()
    if primary is None:
        primary = Node(name="Primary server", ip=public_host, host="",
                       country="", protocol="OpenVPN", api_key=PRIMARY_NODE_KEY,
                       status="online")
        db.session.add(primary)
        db.session.flush()
    else:
        primary.ip = public_host
        primary.status = "online"
    # Accounts created by earlier clean-server installs had implicit local access.
    # Explicitly grant that node only where no assignments were recorded.
    for user in User.query.all():
        if not UserNode.query.filter_by(user_id=user.id).first():
            db.session.add(UserNode(user_id=user.id, node_id=primary.id))
    db.session.commit()
    return primary


def sync_primary_access(user, primary_selected):
    from app import representative_credit
    from app import representative_actions
    if representative_credit.suspended(user) or representative_actions.blocked(user):primary_selected=False
    if getattr(user,"id",None) is not None:
        from app import devices
        from types import SimpleNamespace
        for device in devices.Device.query.filter_by(user_id=user.id).all():
            sync_primary_access(SimpleNamespace(username=device.common_name,status="disabled" if device.blocked else user.status,customer_paused=user.customer_paused),primary_selected)
    """Apply the local node selection using OpenVPN's per-client CCD."""
    if privileged_enabled():
        return privileged_call("access", username=user.username, active=bool(user.status == "active" and not user.customer_paused and primary_selected))
    ccd_file = f"/etc/openvpn/ccd/{user.username}"
    if user.status != "active" or getattr(user, 'customer_paused', False) or not primary_selected:
        from vpn_sessions import disable_ccd
        disable_ccd(ccd_file)
        if user.status == "active":
            try:
                with socket.create_connection(("127.0.0.1", 7505), timeout=1) as management:
                    management.sendall(f"kill {user.username}\n".encode("ascii"))
            except OSError:
                pass
    elif os.path.exists(ccd_file):
        from vpn_sessions import enable_ccd
        enable_ccd(ccd_file)


def reconcile_primary_access():
    """Reapply eligible local access after upgrades without resetting quotas.

    Do not reactivate database accounts, grant new node assignments or touch
    users paused by their owner. Existing disabled/expired accounts stay blocked.
    """
    primary = Node.query.filter_by(api_key=PRIMARY_NODE_KEY).first()
    if primary is None:
        return
    users = User.query.join(UserNode, UserNode.user_id == User.id).filter(
        UserNode.node_id == primary.id, User.status == 'active',
        User.customer_paused.is_(False)).all()
    for user in users:
        if activation_error(user.expire_date, user.traffic_limit or 0, user.traffic_usage or 0, quota_mode=getattr(user,'quota_mode','metered')):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}", user.username):
            continue
        try:
            if speed_policy.sync(user):
                user.pause_sync_pending=True
            sync_primary_access(user, True)
        except (OSError, RuntimeError, ValueError):
            user.pause_sync_pending = True
            app.logger.warning("Local access reconciliation failed for account ID %s; queued retry", user.id)
    db.session.commit()


@login_manager.user_loader
def load_user(user_id):
    return panel_sessions.load(str(user_id))


# ==================== GLOBAL UTILITIES ====================

def disable_user_globally(user):
    if getattr(user,'id',None) is not None:
        try:experience.sync_access(user)
        except (OSError,RuntimeError):user.pause_sync_pending=True
        return
    """غیرفعال سازی کامل کاربر (نوشتن فایل disable در ccd) به دلیل اتمام حجم/زمان"""
    username = user.username
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}", username):
        return
    if privileged_enabled():
        try: privileged_call("access",username=username,active=False)
        except RuntimeError: user.pause_sync_pending=True
        kick_user_globally(user)
        return
    ccd_file = f"/etc/openvpn/ccd/{username}"
    try:
        with open(ccd_file, "w") as f:
            f.write("disable\n")
    except:
        pass
    kick_user_globally(user)

def kick_user_globally(user):
    if getattr(user,"id",None) is not None and not getattr(user,"_individual",False):
        from types import SimpleNamespace
        for device in devices.Device.query.filter_by(user_id=user.id).all():kick_user_globally(SimpleNamespace(id=user.id,username=device.common_name,_individual=True))
    """فقط اخراج آنی کاربر از کل نودها و سرور اصلی، بدون دستکاری فایل ccd
       این مورد مشکل Ghost Connections را وقتی دیوایس اضافه متصل می‌شود حل میکند"""
    username = user.username
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}", username):
        return
    try:
        if privileged_enabled():privileged_call("kick",username=username)
        else:
            with socket.create_connection(("127.0.0.1", 7505), timeout=1) as management:
                management.sendall(f"kill {username}\n".encode("ascii"))
    except:
        pass

    try:
        relations = UserNode.query.filter_by(user_id=user.id).all()
        for rel in relations:
            node = Node.query.get(rel.node_id)
            if node and not is_primary_node(node):
                target = node.host if node.host else node.ip
                if not target: continue
                address=node_url(node)

                requests.post(
                    f"{address}/api/node/kill-user",
                    json={"username": username},
                    headers={"Authorization": f"Bearer {node.api_key}"},
                    timeout=2
                )
    except:
        pass


def update_openvpn_status():
    """Count deltas from each VPN session into a durable, per-node daily ledger."""
    customer_features.expire_receipt_grants()
    nodes = Node.query.all()
    presence = {}
    today = datetime.utcnow().date().isoformat()
    from node_snapshots import collect
    records=[]
    for n in nodes:
        try:records.append((n.id,is_primary_node(n),'' if is_primary_node(n) else node_url(n),n.api_key))
        except ValueError:continue
    snapshots=collect(records,privileged_enabled,privileged_call)
    for node in nodes:
        try:
            snapshot=snapshots.get(node.id)
            if not snapshot:raise RuntimeError('Node snapshot unavailable')
            log=snapshot.get('log','');terminal_events=snapshot.get('events',[])
            node_api_address='' if is_primary_node(node) else node_url(node)
            clients = parse_status(log)
            admission.sync(node.id,clients)
            from terminal_traffic import merge_events
            prefixes=['|'.join([e['username'],e['address'],str(e['since'])])+'|' for e in terminal_events]
            from sqlalchemy import or_
            sample_keys=[]
            for start in range(0,len(prefixes),100):
                conditions=[TrafficSample.session_key.startswith(prefix,autoescape=True) for prefix in prefixes[start:start+100]]
                sample_keys.extend(row.session_key for row in TrafficSample.query.filter(TrafficSample.node_id==node.id,or_(*conditions)))
            clients,terminal_keys=merge_events(clients,terminal_events,sample_keys)
            node.status = 'online'
            seen = set()
            baseline = db.session.get(TrafficBaseline, node.id)
            baseline_only = bool(baseline and baseline.pending)
            for username, session_key, received, sent, address in clients:
                if session_key in seen:
                    continue
                seen.add(session_key)
                sample = TrafficSample.query.filter_by(node_id=node.id, session_key=session_key).first()
                legacy_baseline = baseline_only or (sample and (sample.last_received < 0 or sample.last_sent < 0))
                diff_received = 0 if legacy_baseline else usage_delta(sample.last_received if sample else None, received)
                diff_sent = 0 if legacy_baseline else usage_delta(sample.last_sent if sample else None, sent)
                diff = diff_received + diff_sent
                if sample:
                    sample.last_bytes = received + sent
                    sample.last_received = received
                    sample.last_sent = sent
                else:
                    db.session.add(TrafficSample(node_id=node.id, session_key=session_key,
                                                 last_bytes=received + sent,
                                                 last_received=received, last_sent=sent))
                if diff:
                    daily = TrafficDaily.query.filter_by(node_id=node.id, day=today).first()
                    if daily is None:
                        daily = TrafficDaily(node_id=node.id, node_name=node.name, day=today,
                                             bytes_total=0, bytes_received=0, bytes_sent=0)
                        db.session.add(daily)
                        db.session.flush()
                    daily.bytes_total += diff
                    daily.bytes_received += diff_received
                    daily.bytes_sent += diff_sent
                account=devices.owner(username)
                account_name=account.username if account else username
                details = presence.setdefault(account_name, {"bytes": 0, "connections": 0, "address": address})
                details["bytes"] += diff
                details["connections"] += int(session_key not in terminal_keys)
                user = account
                if user and diff:
                    db.session.execute(db.update(User).where(User.id==user.id).values(traffic_used=db.func.coalesce(User.traffic_used,0)+diff))
                    user_daily = TrafficDailyUser.query.filter_by(user_id=user.id, day=today).first()
                    if user_daily is None:
                        user_daily = TrafficDailyUser(user_id=user.id, day=today, bytes_total=0)
                        db.session.add(user_daily)
                        db.session.flush()
                    user_daily.bytes_total += diff
            if baseline:
                baseline.pending = False
            db.session.commit()
            ack=[event['event_id'] for event in terminal_events if event.get('event_id') and any(key.startswith('|'.join([event['username'],event['address'],str(event['since'])])+'|') for key in terminal_keys)]
            if ack:
                try:
                    if is_primary_node(node):
                        if privileged_enabled():privileged_call('traffic_ack',ids=ack)
                        else:__import__('terminal_traffic').acknowledge(ack)
                    else:requests.post(node_api_address+'/api/node/ack-traffic',json={'ids':ack},headers={'Authorization':'Bearer '+node.api_key},timeout=3).raise_for_status()
                except Exception:app.logger.warning('Terminal traffic acknowledgement pending on node ID %s',node.id)
        except Exception:
            app.logger.exception("Could not collect VPN status from node %s", node.name)
            db.session.rollback()
            node.status = 'offline'
            continue
    for user in User.query.all():
        db.session.refresh(user)
        details = presence.get(user.username)
        user.online = bool(details and details["connections"])
        user.online_status = "online" if user.online else "offline"
        user.current_devices = details["connections"] if details else 0
        if details:
            # TrafficSample, account counters and daily ledgers were committed atomically above.
            user.traffic_usage = round(user.traffic_used / 1073741824, 3)
            if details["bytes"] and user.expire_date and user.expire_date.isdigit():
                pending_days=user.expire_date
                user.expire_date = (datetime.now().date() + timedelta(days=int(user.expire_date))).isoformat()
                customer_features.receipt_counter_started(user,pending_days,user.expire_date)
            if user.max_devices and (user.current_devices > user.max_devices or connection_guard.active(user.id)):
                from session_limits import enforce
                from vpn_sessions import local_sessions,disconnect_session
                selected_ids={rel.node_id for rel in UserNode.query.filter_by(user_id=user.id)}
                names=[user.username]+[d.common_name for d in devices.Device.query.filter_by(user_id=user.id)]
                failed=enforce(user,[n for n in nodes if n.id in selected_ids],names,is_primary_node,local_sessions,disconnect_session,guard=connection_guard)
                if failed:app.logger.warning('Session limit reconciliation pending for account ID %s',user.id)
        if details and (user.customer_paused or representative_credit.suspended(user)):
            experience.sync_access(user)
        if activation_error(user.expire_date, user.traffic_limit, user.traffic_usage or 0, quota_mode=getattr(user,'quota_mode','metered')):
            if user.status == "active":
                user.status = "disabled"
                user.disable_reason = "automatic"
            disable_user_globally(user)
        if user.quota_mode=='fair_use' or user.speed_state or user.speed_sync_pending:
            if speed_policy.sync(user):experience.sync_access(user)
    db.session.commit()


def background_updater():
    last_crl=0
    while True:
        try:
            with app.app_context():
                update_openvpn_status()
                if time.monotonic()-last_crl>60:
                    crl_sync.sync();last_crl=time.monotonic()
        except Exception as e:
            print(f"[UPDATER ERROR] {e}", flush=True)
        time.sleep(10)


# ==================== AUTH ROUTES ====================

@app.route(f"{PANEL_PATH}/login" if PANEL_PATH != '/' else "/login", methods=["GET", "POST"])
def login():
    if request.args.get("lang") in {"fa", "en"}:
        session["login_language"] = request.args["lang"]
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        admin = Admin.query.filter_by(username=username).first()
        allowed, error = security.authorize(admin,password,request.form.get("code",""))
        if allowed:
            identity = panel_sessions.start(admin)
            login_user(admin, remember=request.form.get("remember") == "1")
            session["_user_id"] = identity
            return redirect(f"{PANEL_PATH}")
        return render_template("login.html", error=error, panel_path=PANEL_PATH)
    return render_template("login.html", panel_path=PANEL_PATH)

@app.route(f"{PANEL_PATH}/logout" if PANEL_PATH != '/' else "/logout")
@login_required
def logout():
    panel_sessions.end()
    logout_user()
    return redirect(f"{PANEL_PATH}/login" if PANEL_PATH != '/' else "/login")


# ==================== MAIN ROUTES ====================

@app.route(PANEL_PATH)
@login_required
def home():
    online_users_list = User.query.filter_by(online=True).order_by(User.username).limit(6).all()
    online_users = User.query.filter_by(online=True).count()
    today = datetime.now().date()
    expiring_users_list = []
    for user in User.query.all():
        try:
            expiry = datetime.strptime(user.expire_date, "%Y-%m-%d").date()
            if 0 <= (expiry - today).days <= 7:
                expiring_users_list.append(user)
        except (ValueError, TypeError):
            continue
    expiring_users_list.sort(key=lambda u: u.expire_date)
    expiring_users = len(expiring_users_list)
    total_traffic = round((db.session.query(db.func.sum(TrafficDaily.bytes_total)).scalar() or 0) / 1073741824, 2)
    total_users = User.query.count()
    active_users = User.query.filter_by(status="active").count()
    openvpn_users = User.query.filter_by(protocol="openvpn").count()
    wireguard_users = User.query.filter_by(protocol="wireguard").count()
    recent_days = [(today - timedelta(days=i)).isoformat() for i in range(15, -1, -1)]
    recent_totals = dict(db.session.query(TrafficDaily.day, db.func.sum(TrafficDaily.bytes_total))
                         .filter(TrafficDaily.day >= recent_days[0])
                         .group_by(TrafficDaily.day).all())
    preceding_bytes = (db.session.query(db.func.sum(TrafficDaily.bytes_total))
                       .filter(TrafficDaily.day < recent_days[0]).scalar() or 0)
    running = preceding_bytes
    cumulative_traffic = []
    for day in recent_days:
        running += recent_totals.get(day, 0)
        cumulative_traffic.append(round(running / 1073741824, 3))

    return render_template("dashboard.html",
                         panel_path=PANEL_PATH,
                         online_users=online_users,
                         online_users_list=online_users_list,
                         expiring_users=expiring_users,
                         expiring_users_list=expiring_users_list[:6],
                         total_traffic=total_traffic,
                         cumulative_traffic=cumulative_traffic,
                         week_labels=[day[5:] for day in recent_days[-7:]],
                         week_traffic=[round(recent_totals.get(day, 0) / 1073741824, 3) for day in recent_days[-7:]],
                         total_users=total_users,
                         active_users=active_users,
                         openvpn_users=openvpn_users,
                         wireguard_users=wireguard_users)


@app.get(f"{PANEL_PATH}/traffic" if PANEL_PATH != '/' else "/traffic")
@login_required
def traffic_page():
    today = datetime.utcnow().date()
    start = (today - timedelta(days=29)).isoformat()
    rows = TrafficDaily.query.filter(TrafficDaily.day >= start).all()
    lifetime = db.session.query(db.func.sum(TrafficDaily.bytes_total)).scalar() or 0
    outbound = db.session.query(db.func.sum(TrafficDaily.bytes_sent)).scalar() or 0
    inbound = db.session.query(db.func.sum(TrafficDaily.bytes_received)).scalar() or 0
    today_total = sum(row.bytes_total for row in rows if row.day == today.isoformat())
    node_ids = {row.node_id for row in rows}
    node_ids.update(node.id for node in Node.query.all())
    all_totals = dict(db.session.query(TrafficDaily.node_id, db.func.sum(TrafficDaily.bytes_total))
                      .group_by(TrafficDaily.node_id).all())
    names = {node.id: node.name for node in Node.query.all()}
    for old_id, old_name in db.session.query(TrafficDaily.node_id, TrafficDaily.node_name).distinct().all():
        names.setdefault(old_id, old_name + ' (removed)')
    for row in rows:
        names.setdefault(row.node_id, row.node_name + ' (removed)')
    nodes = [{'name': names.get(node_id, f'Node #{node_id}'),
              'total': round(all_totals.get(node_id, 0) / 1073741824, 3),
              'today': round(sum(row.bytes_total for row in rows if row.node_id == node_id and row.day == today.isoformat()) / 1073741824, 3)}
             for node_id in node_ids]
    nodes.sort(key=lambda item: item['total'], reverse=True)
    days = [(today - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    daily = [{'day': day, 'gb': round(sum(row.bytes_total for row in rows if row.day == day) / 1073741824, 3)} for day in days]
    host_rows=host_traffic.Daily.query.filter(host_traffic.Daily.day>=start).all()
    host_total=db.session.query(db.func.sum(host_traffic.Daily.received+host_traffic.Daily.sent)).scalar() or 0
    host_daily=[dict(day=day,gb=round(sum(r.received+r.sent for r in host_rows if r.day==day)/1073741824,3)) for day in days]
    measured_ids={r.node_id for r in host_traffic.Sample.query.all()}
    missing_hosts=[n.name for n in Node.query.all() if n.id not in measured_ids]
    return render_template('traffic.html',host_total=round(host_total/1073741824,3),host_daily=host_daily,missing_hosts=missing_hosts, panel_path=PANEL_PATH, nodes=nodes,
                           daily=daily, lifetime=round(lifetime / 1073741824, 3),
                           outbound=round(outbound / 1073741824, 3),
                           inbound=round(inbound / 1073741824, 3),
                           today_total=round(today_total / 1073741824, 3),
                           last_30=round(sum(row.bytes_total for row in rows) / 1073741824, 3),
                           sampled_at=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'))


@app.route(f"{PANEL_PATH}/users" if PANEL_PATH != '/' else "/users")
@login_required
def users():
    nodes = Node.query.all()
    return render_template("users.html", panel_path=PANEL_PATH, nodes=nodes)


@app.route(f"{PANEL_PATH}/users/add" if PANEL_PATH != '/' else "/users/add", methods=["GET", "POST"])
@login_required
def add_user():
    nodes = Node.query.all()
    primary_id = next((node.id for node in nodes if is_primary_node(node)), None)

    # متد GET برای نمایش صفحه فرم
    if request.method == "GET":
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None)
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}", request.form.get("username", "")):
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Username must use only letters, numbers, underscore or hyphen."), 400
    if request.form.get("protocol") != "openvpn":
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Only OpenVPN is supported by this installation."), 400

    portal_password = request.form.get("portal_password", "")
    portal_username = request.form.get("portal_username", "").strip() or request.form["username"]
    if portal_password and (not 12 <= len(portal_password) <= 256 or
                            not re.fullmatch(r"[A-Za-z0-9_.-]{3,100}", portal_username)):
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Customer login needs a 3+ character username and a 12+ character password."), 400

    from app import sales_engine
    sale_form,sale_snapshot=sales_engine.prepare(request.form)
    request.form=sale_form
    expire_days = request.form.get("expire_days", "").strip()
    if expire_days and (not expire_days.isdigit() or not 1 <= int(expire_days) <= 3650):
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Validity must be 1–3650 days."), 400
    expiry_start = request.form.get("expiry_start", "first_use")
    if expiry_start not in {"first_use", "today"}:
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Choose a valid validity start."), 400
    expire_val = ((datetime.now().date() + timedelta(days=int(expire_days))).isoformat()
                  if expire_days and expiry_start == "today" else (expire_days or "-"))
    initial_status = request.form.get("status", "active")
    if initial_status not in {"active", "disabled"}:
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Choose a valid account status."), 400
    try:
        max_devices = int(request.form["max_devices"])
        traffic_limit = int(request.form.get("traffic_limit", "0"))
        if max_devices < 1 or max_devices > 100 or traffic_limit < 0 or traffic_limit > 100000:
            raise ValueError()
    except (ValueError, KeyError):
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Check the device and data limits."), 400

    try:
        from speed_policy import validate_policy
        speed_fields=validate_policy(request.form.get('quota_mode','metered'),request.form.get('throttle_down_kbps',2000),request.form.get('throttle_up_kbps',2000),traffic_limit)
    except ValueError as exc:
        return render_template('user_form.html',panel_path=PANEL_PATH,nodes=nodes,mode='add',user=None,error=str(exc)),400
    user = User(
        owner_id=current_user.id,
        username=request.form["username"],
        protocol=request.form["protocol"],
        max_devices=max_devices,
        expire_date=expire_val,
        status=initial_status,
        traffic_limit=traffic_limit,
        **speed_fields
    )

    selected_nodes = request.form.getlist("nodes")
    try:
        selected_ids = [int(n) for n in selected_nodes]
    except ValueError:
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Invalid node selection."), 400
    if not selected_ids or len(set(selected_ids)) != len(selected_ids) or not set(selected_ids).issubset({node.id for node in nodes}):
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Select at least one available node."), 400
    if User.query.filter_by(username=user.username).first() or db.session.get(devices.RetiredUsername,user.username):
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Username already exists or was retired after deletion. Choose a new username."), 409
    try:
        if privileged_enabled():privileged_call("create_user",username=user.username)
        else:subprocess.run(["/opt/beeny-panel/scripts/create_vpn_user.sh", user.username], check=True, timeout=120)
    except (OSError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="VPN certificate creation failed; see the panel service log."), 500

    db.session.add(user)
    db.session.flush()

    if portal_password:
        profile = customer_features.CustomerProfile(
            user_id=user.id, login_username=portal_username,
            password_hash=generate_password_hash(portal_password), auth_version=secrets.token_hex(24))
        db.session.add(profile)

    for node_id in selected_ids:
        db.session.add(UserNode(user_id=user.id, node_id=node_id))
    sales_engine.direct_invoice(user,sale_snapshot)
    db.session.commit()
    sync_primary_access(user, primary_id in selected_ids)
    if user.status == "disabled":
        disable_user_globally(user)

    from cluster import create_user_on_node, set_user_state_on_node
    node_sync_failed = False
    for node_id in selected_nodes:
        node = Node.query.get(int(node_id))
        if node and not is_primary_node(node):
            result = create_user_on_node(node, user)
            if not result.startswith('Success:'):
                node_sync_failed = True
                app.logger.error('Node certificate sync failed for %s on %s: %s', user.username, node.name, result)
            elif user.status != 'active':
                synced, reason = set_user_state_on_node(node, user.username, False)
                if not synced:
                    node_sync_failed = True
                    app.logger.error('Node status sync failed for %s on %s: %s', user.username, node.name, reason)

    base = PANEL_PATH.rstrip('/')
    return redirect(f"{base}/users/view/{user.id}?notice=created" + ('&sync_warning=1' if node_sync_failed else ''))


@app.route(f"{PANEL_PATH}/users/edit/<int:user_id>" if PANEL_PATH != '/' else "/users/edit/<int:user_id>", methods=["GET", "POST"])
@login_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    nodes = Node.query.all()
    primary_id = next((node.id for node in nodes if is_primary_node(node)), None)

    current_node_ids = [rel.node_id for rel in UserNode.query.filter_by(user_id=user.id).all()]

    # متد GET برای نمایش صفحه فرم
    if request.method == "GET":
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="edit", user=user, current_nodes=current_node_ids)

    def invalid(message):
        db.session.rollback()
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="edit", user=user,
                               current_nodes=current_node_ids, error=message), 400

    try:
        max_devices = int(request.form["max_devices"])
        new_limit = int(request.form.get("traffic_limit", "0"))
        traffic_add = request.form.get("traffic_add", "").strip()
        if max_devices < 1 or max_devices > 100 or new_limit < 0 or new_limit > 100000:
            raise ValueError()
        if traffic_add:
            if not traffic_add.isdigit() or not 1 <= int(traffic_add) <= 100000:
                raise ValueError()
            # Zero denotes unlimited, so a quota addition starts from consumed data.
            new_limit = max(new_limit, math.ceil(user.traffic_usage or 0)) + int(traffic_add)
            if new_limit > 100000:
                raise ValueError()
    except (ValueError, KeyError):
        return invalid("Check the device and data limits.")
    try:
        from speed_policy import validate_policy
        speed_fields=validate_policy(request.form.get('quota_mode',user.quota_mode),request.form.get('throttle_down_kbps',user.throttle_down_kbps),request.form.get('throttle_up_kbps',user.throttle_up_kbps),new_limit)
    except ValueError as exc:return invalid(str(exc))
    requested_status = request.form.get("status")
    if request.form.get("protocol") != "openvpn":
        return invalid("Only OpenVPN is supported by this installation.")
    if requested_status not in {"active", "disabled"}:
        return invalid("Choose a valid account status.")
    renewal_days = request.form.get("renewal_days", "").strip()
    if renewal_days and (not renewal_days.isdigit() or not 1 <= int(renewal_days) <= 3650):
        return invalid("Renewal must be 1–3650 days.")
    renewal_mode = request.form.get("renewal_mode", "extend")
    if renewal_mode not in {"extend", "from_today"}:
        return invalid("Choose a valid renewal mode.")
    try:
        new_node_ids = [int(n) for n in request.form.getlist("nodes")]
    except ValueError:
        return invalid("Invalid node selection.")
    if not new_node_ids or len(set(new_node_ids)) != len(new_node_ids) or not set(new_node_ids).issubset({node.id for node in nodes}):
        return invalid("Select at least one available node.")

    next_expiry = user.expire_date
    exact_expiry = request.form.get("set_expiry_date", "").strip()
    if request.form.get("unlimited_time") == "1":
        next_expiry = "-"
    elif exact_expiry:
        try:
            next_expiry = datetime.strptime(exact_expiry, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return invalid("Choose a valid expiry date (YYYY-MM-DD).")
    elif renewal_days:
        try:
            next_expiry = extend_expiry(next_expiry, int(renewal_days), renewal_mode)
        except (ValueError, OverflowError):
            return invalid("Stored expiry date or renewal is invalid.")
    will_reset = request.form.get("reset_traffic") == "1"
    usage_after_edit = 0 if will_reset else (user.traffic_usage or 0)
    if requested_status == "active":
        if representative_actions.blocked(user):return invalid("این حساب بایگانی شده است؛ لغو فروش را با فعال‌سازی دستی برنگردانید.")
        problem = activation_error(next_expiry, new_limit, usage_after_edit, quota_mode=speed_fields['quota_mode'])
        if problem:
            return invalid(problem)

    user.protocol = request.form["protocol"]
    user.max_devices = max_devices
    for key,value in speed_fields.items():setattr(user,key,value)
    user.traffic_limit = new_limit
    user.expire_date = next_expiry
    user.status = requested_status
    if will_reset:
        user.traffic_usage = 0
        user.traffic_used = 0
        user.last_session_bytes = -1
    if user.status == "disabled":
        disable_user_globally(user)
    sync_primary_access(user, primary_id in new_node_ids)

    removed_nodes = set(current_node_ids) - set(new_node_ids)
    added_nodes = set(new_node_ids) - set(current_node_ids)

    UserNode.query.filter_by(user_id=user.id).delete()
    for node_id in new_node_ids:
        db.session.add(UserNode(user_id=user.id, node_id=int(node_id)))

    db.session.commit()

    from cluster import create_user_on_node, delete_user_on_node, set_user_state_on_node
    node_sync_failed = False
    # پاک کردن کاربر از نودهایی که تیک آنها برداشته شده (جلوگیری از ماندن کاربر در نودهای اضافی)
    for nid in removed_nodes:
        node = Node.query.get(nid)
        if node and not is_primary_node(node):
            if not delete_user_on_node(node, user.username):
                node_sync_failed = True

    # اضافه کردن کاربر به نودهای جدید
    for nid in added_nodes:
        node = Node.query.get(nid)
        if node and not is_primary_node(node):
            result = create_user_on_node(node, user)
            if not result.startswith('Success:'):
                node_sync_failed = True
                app.logger.error('Node certificate sync failed for %s on %s: %s', user.username, node.name, result)
    for nid in new_node_ids:
        node = Node.query.get(nid)
        if node and not is_primary_node(node):
            synced, reason = set_user_state_on_node(node, user.username, user.status == 'active' and not user.customer_paused and not representative_credit.suspended(user) and not representative_actions.blocked(user))
            if not synced:
                node_sync_failed = True
                app.logger.error('Node status sync failed for %s on %s: %s', user.username, node.name, reason)
    base = PANEL_PATH.rstrip('/')
    db.session.refresh(user)
    sync_primary_access(user, primary_id in new_node_ids)
    user.pause_sync_pending = node_sync_failed
    db.session.commit()
    return redirect(f"{base}/users/view/{user.id}?notice=updated" + ('&sync_warning=1' if node_sync_failed else ''))

@app.route(f"{PANEL_PATH}/users/delete/<int:user_id>" if PANEL_PATH != '/' else "/users/delete/<int:user_id>", methods=["POST"])
@login_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    remove_vpn_account(user)
    return redirect(f"{PANEL_PATH}/users" if PANEL_PATH != '/' else "/users")


def remove_vpn_account(user,owner_cascade=False):
    """Block every assigned certificate before removing an account; preserve billing history."""
    from app import representative_credit
    if owner_cascade and current_user.role!='owner':abort(403)
    if user.reseller_id and representative_credit.mode(user.reseller_id) and not owner_cascade:abort(409,'حساب مشتری نماینده اعتباری باید از بخش لغو فروش یا بایگانی بسته شود؛ حذف مستقیم مجاز نیست.')
    user_id=user.id
    user.status='disabled'
    user.pause_sync_pending=True
    db.session.commit()
    failures=experience.sync_access(user)
    if failures:
        abort(409,'Account disabled; deletion waits for node confirmation: '+', '.join(failures))
    if not db.session.get(devices.RetiredUsername,user.username):
        db.session.add(devices.RetiredUsername(username=user.username))
    # sync_access confirms access is disabled for the account and every device.
    # Node cleanup is best effort; blocked certificates stay unusable on failure.
    from cluster import delete_user_on_node
    relations=UserNode.query.filter_by(user_id=user_id).all()
    registered=devices.Device.query.filter_by(user_id=user_id).all()
    for rel in relations:
        node=db.session.get(Node,rel.node_id)
        if node and not is_primary_node(node):
            for name in [user.username]+[device.common_name for device in registered]:
                try:delete_user_on_node(node,name)
                except Exception:pass
    UserNode.query.filter_by(user_id=user_id).delete()
    devices.Device.query.filter_by(user_id=user_id).delete()
    customer_features.delete_customer(user_id)
    AccountLink.query.filter_by(user_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()


@app.post((PANEL_PATH.rstrip('/') if PANEL_PATH!='/' else '')+'/users/view/<int:user_id>/share-telegram')
@login_required
def share_account_telegram(user_id):
    from html import escape
    from urllib.parse import urlsplit
    import hashlib,hmac
    customer_features.verify_csrf()
    user=User.query.get_or_404(user_id)
    profile=db.session.get(customer_features.CustomerProfile,user.id)
    password=request.form.get('password','')
    language=request.form.get('language','fa')
    if language not in {'fa','en'}:return jsonify(error='Invalid message language.'),400
    if not profile or not 1<=len(password)<=256 or not check_password_hash(profile.password_hash or '',password):
        return jsonify(error='Enter the current customer password before sending.'),400
    url=request.form.get('url','');parsed=urlsplit(url)
    token=parsed.path.rsplit('/',1)[-1]
    link=db.session.get(AccountLink,user.id)
    prefix=PANEL_PATH.rstrip('/')+'/c/' if PANEL_PATH!='/' else '/c/'
    if parsed.scheme not in {'https','http'} or parsed.netloc!=request.host or parsed.path!=prefix+token or not link or not hmac.compare_digest(link.token_hash,hashlib.sha256(token.encode()).hexdigest()):
        return jsonify(error='Generate a valid private profile link first.'),400
    binding=customer_features.TelegramAccount.query.filter_by(user_id=user.id).first()
    if not binding or binding.chat_id<=0 or not customer_features.is_linked(user.id):
        return jsonify(error='This customer must connect their private Telegram account first.'),409
    if language=='en':
        message=('Hello 👋\nYour Beeny account details:\n\n🔗 Personal page: '+escape(url,quote=False)+
                 '\n👤 Username: <code>'+escape(profile.login_username or user.username,quote=False)+'</code>'+
                 '\n🔐 Password: <code>'+escape(password,quote=False)+'</code>\n\nThese details are private. Keep them confidential.')
    else:
        message=('سلام 👋\nاطلاعات حساب بنی شما:\n\n🔗 صفحهٔ شخصی: '+escape(url,quote=False)+
                 '\n👤 نام کاربری: <code>'+escape(profile.login_username or user.username,quote=False)+'</code>'+
                 '\n🔐 رمز ورود: <code>'+escape(password,quote=False)+'</code>\n\nاین اطلاعات خصوصی است؛ آن را محرمانه نگه دارید.')
    try:customer_features.telegram('sendMessage',dict(chat_id=binding.chat_id,text=message,parse_mode='HTML',disable_web_page_preview=True))
    except Exception:return jsonify(error='Telegram delivery failed. Check the bot settings and connection.'),502
    return jsonify(ok=True)


@app.route(f"{PANEL_PATH}/users/view/<int:user_id>" if PANEL_PATH != '/' else "/users/view/<int:user_id>")
@login_required
def view_user(user_id):
    user = User.query.get_or_404(user_id)
    try:
        if user.expire_date and user.expire_date.isdigit():
            days_left = f"{user.expire_date} days · starts on first use"
        elif user.expire_date and user.expire_date != "-":
            days = (datetime.strptime(user.expire_date, "%Y-%m-%d").date() - datetime.now().date()).days
            days_left = days if days >= 0 else 0
        else:
            days_left = "Unlimited"
    except (ValueError, TypeError):
        days_left = "Unknown"

    user_nodes = []
    relations = UserNode.query.filter_by(user_id=user.id).all()
    for rel in relations:
        node = Node.query.get(rel.node_id)
        if node:
            user_nodes.append(node)

    usage = float(user.traffic_usage or 0)
    limit = int(user.traffic_limit or 0)
    return render_template("user_profile.html", user=user, days_left=days_left,
                           assigned_nodes=user_nodes, panel_path=PANEL_PATH,
                           portal_exists=AccountLink.query.filter_by(user_id=user.id).first() is not None,
                           used_gb=usage, remaining_gb=max(0, limit - usage) if limit else None,
                           usage_percent=min(100, round(usage / limit * 100)) if limit else 0)


@app.post(f"{PANEL_PATH}/users/view/<int:user_id>/portal" if PANEL_PATH != '/' else "/users/view/<int:user_id>/portal")
@login_required
def rotate_account_link(user_id):
    customer_features.verify_csrf()
    user = User.query.get_or_404(user_id)
    token = secrets.token_urlsafe(32)
    row = AccountLink.query.filter_by(user_id=user.id).first()
    if row is None:
        row = AccountLink(user_id=user.id, token_hash='')
        db.session.add(row)
    row.token_hash = hashlib.sha256(token.encode('ascii')).hexdigest()
    row.created_at = datetime.utcnow()
    db.session.commit()
    relations = UserNode.query.filter_by(user_id=user.id).all()
    assigned = [Node.query.get(rel.node_id) for rel in relations]
    base_url = os.environ.get('BEENY_PANEL_BASE_URL')
    if not base_url:
        scheme = 'https' if os.environ.get('BEENY_PUBLIC_HTTPS') == '1' else request.scheme
        base_url = f'{scheme}://{request.host}'
    return render_template('user_profile.html', user=user, panel_path=PANEL_PATH,
                           assigned_nodes=[node for node in assigned if node],
                           portal_exists=True,
                           portal_url=base_url.rstrip('/') + PANEL_PATH.rstrip('/') + '/c/' + token,
                           days_left=user.expire_date or 'Unlimited',
                           used_gb=float(user.traffic_usage or 0),
                           remaining_gb=max(0, user.traffic_limit - (user.traffic_usage or 0)) if user.traffic_limit else None,
                           usage_percent=min(100, round((user.traffic_usage or 0) / user.traffic_limit * 100)) if user.traffic_limit else 0)


def account_from_token(token):
    if token.startswith('t_') and len(token) < 600:
        user=customer_features.resolve_bot_token(token)
        if request.method not in {'GET','HEAD','OPTIONS'}:
            from removal_guard import claim
            claim(db,User,user.id)
        return user
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        abort(404)
    digest = hashlib.sha256(token.encode('ascii')).hexdigest()
    link = AccountLink.query.filter_by(token_hash=digest).first()
    if link is None:
        abort(404)
    user=User.query.get_or_404(link.user_id)
    if request.method not in {'GET','HEAD','OPTIONS'}:
        from removal_guard import claim
        claim(db,User,user.id)
    return user


@app.get(f"{PANEL_PATH}/c/<token>" if PANEL_PATH != '/' else "/c/<token>")
def customer_portal(token):
    user = account_from_token(token)
    response = app.make_response(customer_features.render_portal(user, token))
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@app.get(f"{PANEL_PATH}/c/<token>/download" if PANEL_PATH != '/' else "/c/<token>/download")
def customer_config(token):
    user = account_from_token(token)
    response = app.make_response(build_config(user, request.args.get('node_id', type=int)))
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@app.route(f"{PANEL_PATH}/users/download/<username>" if PANEL_PATH != '/' else "/users/download/<username>")
@login_required
def download_config(username):
    user = User.query.filter_by(username=username).first_or_404()
    return build_config(user, request.args.get('node_id', type=int))


def build_config(user, requested_node_id=None,certificate_username=None):
    username = certificate_username or user.username
    try:
        if privileged_enabled():
            material=privileged_call('material',username=username)
            ca_data,ta_data,cert_raw,key_data=material['ca'],material['ta'],material['cert'],material['key']
            cert_match=re.search(r'-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----',cert_raw,re.DOTALL)
            cert_data=cert_match.group(0) if cert_match else cert_raw
        else:
            with open(f"/etc/openvpn/easy-rsa/pki/ca.crt", "r") as f:
                ca_data = f.read()
            with open("/etc/openvpn/ta.key", "r") as f:
                ta_data = f.read()
            with open(f"/etc/openvpn/easy-rsa/pki/issued/{username}.crt", "r") as f:
                cert_raw = f.read()
                cert_match = re.search(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", cert_raw, re.DOTALL)
                cert_data = cert_match.group(0) if cert_match else cert_raw
            with open(f"/etc/openvpn/easy-rsa/pki/private/{username}.key", "r") as f:
                key_data = f.read()
    except (OSError,RuntimeError):
        app.logger.error('VPN client material unavailable for %s',username)
        return 'VPN configuration is unavailable. Check the panel service log.',503

    user_nodes_relations = UserNode.query.filter_by(user_id=user.id).all()
    assigned_ids = {rel.node_id for rel in user_nodes_relations}
    if requested_node_id is not None and requested_node_id not in assigned_ids:
        return "Node not assigned to this account.", 403
    nodes_to_download = ([Node.query.get(requested_node_id)] if requested_node_id is not None
                         else [Node.query.get(rel.node_id) for rel in user_nodes_relations])
    nodes_to_download = [node for node in nodes_to_download if node]
    if not nodes_to_download:
        return "No available node is assigned to this account.", 409

    def clean_address(node_obj):
        from urllib.parse import urlsplit
        import ipaddress
        target=(os.environ.get('BEENY_PUBLIC_HOST','') if is_primary_node(node_obj) else (node_obj.host or node_obj.ip or '')).strip()
        try:return str(ipaddress.ip_address(target))
        except ValueError:pass
        parsed=urlsplit(target if '://' in target else '//'+target)
        host=parsed.hostname or ''
        from speed_policy import endpoint
        return endpoint(host,110)['host']

    try:
        route_mode=request.args.get('route','direct')
        if route_mode not in {'direct','tunnel'}:return 'Invalid profile route.',400
        def node_remote(node):
            if route_mode=='tunnel':
                if not tunnel_settings.configured(node.id):raise ValueError('This node has no enabled paired tunnel.')
                return tunnel_settings.call(node,'endpoint')['endpoint']
            return {'proto':'tcp'} | speed_policy.remote(node,clean_address(node),os.environ.get('BEENY_VPN_PORT','110'))
        remotes=[node_remote(node) for node in nodes_to_download]
        profile_proto='udp' if all(remote['proto']=='udp' for remote in remotes) else 'tcp'
        remotes_block = "\n".join('remote {host} {port} {proto}'.format(**remote) for remote in remotes)
    except (ValueError,RuntimeError,requests.RequestException):
        return "An assigned node endpoint could not be verified. Check its VPN listener and bridge.", 503
    if len(nodes_to_download) > 1:
        remotes_block = "remote-random\n" + remotes_block

    ovpn_template = f"""client
dev tun
proto {profile_proto}
{remotes_block.strip()}

resolv-retry infinite
nobind
persist-key
persist-tun

remote-cert-tls server
block-ipv6

cipher AES-256-GCM
auth SHA256

key-direction 1
verb 3

<ca>
{ca_data.strip()}
</ca>

<cert>
{cert_data.strip()}
</cert>

<key>
{key_data.strip()}
</key>

<tls-auth>
{ta_data.strip()}
</tls-auth>
"""

    mem_file = io.BytesIO()
    mem_file.write(ovpn_template.encode('utf-8'))
    mem_file.seek(0)

    suffix = f"Node_{requested_node_id}" if requested_node_id else "MultiLocation"
    if route_mode=='tunnel':suffix+='_Tunnel'
    filename = f"Beeny_{username}_{suffix}.ovpn"

    return send_file(mem_file, as_attachment=True, download_name=filename, mimetype='application/x-openvpn-profile')


@app.route(f"{PANEL_PATH}/users/reset_traffic/<int:user_id>" if PANEL_PATH != '/' else "/users/reset_traffic/<int:user_id>", methods=["POST"])
@login_required
def reset_traffic(user_id):
    user = User.query.get_or_404(user_id)
    user.traffic_usage = 0
    user.traffic_used = 0
    user.last_session_bytes = -1
    if not activation_error(user.expire_date, user.traffic_limit, 0):
        user.status = "active"
    primary = Node.query.filter_by(api_key=PRIMARY_NODE_KEY).first()
    selected = bool(primary and UserNode.query.filter_by(user_id=user.id, node_id=primary.id).first())
    sync_primary_access(user, selected)
    db.session.commit()
    return redirect(f"{PANEL_PATH}/users" if PANEL_PATH != '/' else "/users")

@app.route(f"{PANEL_PATH}/api/users/search" if PANEL_PATH != '/' else "/api/users/search")
@login_required
def api_users_search():
    q = request.args.get('q', '').strip()
    protocol = request.args.get('protocol', '').strip()
    status = request.args.get('status', '').strip()
    sort_by = request.args.get('sort', 'newest').strip()

    page = request.args.get('page', 1, type=int)
    per_page = max(1, min(200, request.args.get('per_page', 100, type=int)))
    page = max(1, page)

    query = User.query

    if q:
        q=q[:100]
        literal=q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        query=query.filter(User.username.ilike('%'+literal+'%',escape='\\'))
    if protocol: query = query.filter(User.protocol == protocol)
    if status: query = query.filter(User.status == status)

    if sort_by=='online_first': query=query.order_by(db.case((User.online_status=='online',0),else_=1),User.id.desc())
    elif sort_by == 'traffic_desc': query = query.order_by(User.traffic_usage.desc())
    elif sort_by == 'traffic_asc': query = query.order_by(User.traffic_usage.asc())
    elif sort_by == 'oldest': query = query.order_by(User.id.asc())
    elif sort_by == 'name_asc': query = query.order_by(db.func.lower(User.username).asc(), User.id.asc())
    elif sort_by == 'name_desc': query = query.order_by(db.func.lower(User.username).desc(), User.id.asc())
    else: query = query.order_by(User.id.desc())

    from sqlalchemy import case
    overview = query.order_by(None).with_entities(
        db.func.sum(case((User.online_status == 'online', 1), else_=0)),
        db.func.coalesce(db.func.sum(User.traffic_usage), 0),
        db.func.sum(case((db.and_(User.traffic_limit > 0, User.traffic_usage > User.traffic_limit * .8), 1), else_=0))
    ).first()
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    users = paginated.items

    # Fetch node labels once for this page, rather than two queries per account.
    page_nodes={u.id:[] for u in users}
    if page_nodes:
        for user_id,node in db.session.query(UserNode.user_id,Node).join(Node,UserNode.node_id==Node.id).filter(UserNode.user_id.in_(page_nodes)).all():
            page_nodes[user_id].append({'id':node.id,'name':node.name,'country':node.country,'tunnel':tunnel_settings.configured(node.id)})
    users_data = []
    for u in users:
        days_left_text = "Unlimited"
        if u.expire_date and u.expire_date.isdigit():
            days_left_text = f"{u.expire_date} Days (Starts on connect)"
        elif u.expire_date and u.expire_date != '-':
            try:
                delta = (datetime.strptime(u.expire_date, '%Y-%m-%d').date() - datetime.now().date()).days
                days_left_text = f"{delta} Days left" if delta >= 0 else "Expired"
            except: pass

        nodes_list_data = page_nodes.get(u.id,[])

        users_data.append({
            'id': u.id, 'username': u.username, 'protocol': u.protocol, 'status': u.status,
            'customer_paused': bool(u.customer_paused), 'online_status': u.online_status, 'current_devices': u.current_devices, 'max_devices': u.max_devices,
            'expire_days_val': u.expire_date if (u.expire_date and u.expire_date.isdigit()) else '',
            'days_left_text': days_left_text, 'traffic_usage': round(u.traffic_usage or 0, 1), 'traffic_limit': u.traffic_limit or 0,
            'traffic_percent': round(((u.traffic_usage or 0) / u.traffic_limit * 100), 1) if u.traffic_limit and u.traffic_limit > 0 else 0,
            'nodes_list': nodes_list_data
        })

    return jsonify({
        'users': users_data,
        'overview': {'online': int(overview[0] or 0), 'usage': float(overview[1] or 0), 'near_limit': int(overview[2] or 0)},
        'pagination': {
            'page': paginated.page, 'pages': paginated.pages, 'total': paginated.total,
            'has_prev': paginated.has_prev, 'has_next': paginated.has_next,
            'prev_num': paginated.prev_num, 'next_num': paginated.next_num
        }
    })

# ==================== SETTINGS ROUTES ====================

@app.route(f"{PANEL_PATH}/settings/monitoring" if PANEL_PATH != '/' else "/settings/monitoring")
@login_required
def settings_monitoring():
    return render_template('settings_monitoring.html',panel_path=PANEL_PATH)


@app.route(f"{PANEL_PATH}/settings/general" if PANEL_PATH != '/' else "/settings/general")
@login_required
def settings_general():
    from security import ROLES
    owner=current_user.role=='owner'
    return render_template("settings_general.html",panel_path=PANEL_PATH,admins=Admin.query.order_by(Admin.id).all() if owner else [],roles=sorted(ROLES),nodes=Node.query.order_by(Node.name).all() if owner else [],grants={(x.admin_id,x.node_id) for x in security.AdminNodeGrant.query.all()} if owner else set())


@app.route(f"{PANEL_PATH}/settings" if PANEL_PATH != '/' else "/settings")
@login_required
def settings():
    # The hub is navigation only; live measurements belong to the monitoring collector.
    return render_template("settings.html",panel_path=PANEL_PATH)


# ==================== NODES MANAGEMENT ====================

@app.route(f"{PANEL_PATH}/settings/nodes" if PANEL_PATH != '/' else "/settings/nodes")
@login_required
def nodes_page():
    nodes = Node.query.order_by(Node.id).all()
    return render_template("nodes.html", nodes=nodes, health={r.node_id:r for r in health.Health.query.all()}, panel_path=PANEL_PATH, is_primary=is_primary_node)



@app.route(f"{PANEL_PATH}/settings/nodes/add" if PANEL_PATH != '/' else "/settings/nodes/add", methods=["POST"])
@login_required
def add_node():
    if request.form.get("api_key") == PRIMARY_NODE_KEY:
        return "Reserved node identifier.", 400
    node = Node(
        name=request.form.get("name"),
        ip=request.form.get("ip"),
        host=request.form.get("host", ""),
        country=request.form.get("country"),
        protocol=request.form.get("protocol"),
        api_key=request.form.get("api_key")
    )
    db.session.add(node)
    db.session.commit()

    try:
        from cluster import bootstrap_node
        success, msg = bootstrap_node(node)
        print(f"Node Bootstrap [{node.name}]: {msg}", flush=True)
    except Exception as e:
        print(f"Node Bootstrap Error: {str(e)}", flush=True)

    if request.headers.get("X-Requested-With")=="XMLHttpRequest":return jsonify(success=True,message="Node saved.")
    return redirect(f"{PANEL_PATH}/settings/nodes" if PANEL_PATH != '/' else "/settings/nodes")


@app.route(f"{PANEL_PATH}/settings/nodes/edit/<int:node_id>", methods=["POST"])
@login_required
def edit_node(node_id):
    node = Node.query.get_or_404(node_id)
    country = request.form.get("country", "").strip().upper()
    if country and not re.fullmatch(r"[A-Z]{2}", country):
        return "Use a two-letter country code, such as DE or GB.", 400
    name = request.form.get("name", "").strip()
    if not 1 <= len(name) <= 100:
        return "Enter a node name (1–100 characters).", 400
    if is_primary_node(node):
        node.name = name
        node.country = country
        db.session.commit()
        if request.headers.get("X-Requested-With")=="XMLHttpRequest":return jsonify(success=True,message="Node saved.")
        return redirect(f"{PANEL_PATH}/settings/nodes" if PANEL_PATH != '/' else "/settings/nodes")
    if request.form.get("api_key") == PRIMARY_NODE_KEY:
        return "Reserved node identifier.", 400
    node.name = name
    node.ip = request.form.get("ip")
    node.host = request.form.get("host")
    node.country = country
    node.protocol = request.form.get("protocol")
    if request.form.get("api_key", "").strip():
        node.api_key = request.form["api_key"].strip()

    db.session.commit()
    if request.headers.get("X-Requested-With")=="XMLHttpRequest":return jsonify(success=True,message="Node saved.")
    return redirect(f"{PANEL_PATH}/settings/nodes")


@app.route(f"{PANEL_PATH}/settings/nodes/delete/<int:node_id>", methods=["POST"])
@login_required
def delete_node(node_id):
    node = Node.query.get_or_404(node_id)
    if is_primary_node(node):
        return "The primary node cannot be deleted.", 403
    UserNode.query.filter_by(node_id=node_id).delete()
    db.session.delete(node)
    db.session.commit()
    if request.headers.get("X-Requested-With")=="XMLHttpRequest":return jsonify(success=True,message="Node saved.")
    return redirect(f"{PANEL_PATH}/settings/nodes")


# ==================== API ROUTES ====================

@app.route(f"{PANEL_PATH}/api/system/info")
@login_required
def system_info():
    try:
        import socket
        hostname = socket.gethostname()
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        uptime_seconds = time.time() - psutil.boot_time()
        uptime_days = int(uptime_seconds // 86400)
        uptime_hours = int((uptime_seconds % 86400) // 3600)
        uptime = f"{uptime_days}d {uptime_hours}h"

        return jsonify({
            "hostname": hostname,
            "cpu": cpu,
            "ram": ram.percent,
            "ram_used": round(ram.used / 1024 / 1024 / 1024, 1),
            "ram_total": round(ram.total / 1024 / 1024 / 1024, 1),
            "disk": disk.percent,
            "disk_used": round(disk.used / 1024 / 1024 / 1024, 1),
            "disk_total": round(disk.total / 1024 / 1024 / 1024, 1),
            "uptime": uptime
        })
    except Exception as e:
        return jsonify({"hostname": "Unknown", "cpu": None, "ram": None, "disk": None, "uptime": "Unknown"}),503


@app.route(f"{PANEL_PATH}/api/system/stats" if PANEL_PATH != '/' else "/api/system/stats")
@login_required
def system_stats():
    from host_metrics import snapshot
    from flask import g,abort
    if g.get('admin_node_ids') is not None:
        primary=next((n for n in Node.query.all() if is_primary_node(n)),None)
        if primary is None:abort(403)
    try:
        m=privileged_call('host_metrics') if privileged_enabled() else snapshot()
        rx=m.get('rx_mbps');tx=m.get('tx_mbps')
        return jsonify(cpu=m.get('cpu'),cpu_cores=m.get('cpu_cores'),cpu_per_core=m.get('cpu_per_core'),
            ram=m.get('memory'),ram_used=round(m['memory_used']/1024**3,2),ram_total=round(m['memory_total']/1024**3,2),
            disk=m.get('disk'),disk_used=round(m['disk_used']/1024**3,2),disk_free=round((m['disk_total']-m['disk_used'])/1024**3,2),
            network=(rx+tx)/8 if rx is not None and tx is not None else None,
            network_rx=rx/8 if rx is not None else None,network_tx=tx/8 if tx is not None else None,
            network_unit='MB/s',network_rx_mbps=rx,network_tx_mbps=tx,interface=m['interface'])
    except Exception:
        return jsonify(error='Host telemetry unavailable',cpu=None,ram=None,disk=None,network=None),503


@app.route(f"{PANEL_PATH}/api/panel/restart", methods=["POST"])
@login_required
def restart_panel():
    try:
        from privileged_server import dispatch
        result=privileged_call("service",name="beeny-panel",action="restart") if privileged_enabled() else dispatch("service",dict(name="beeny-panel",action="restart"))
        return jsonify({"success": True, "message": "Panel restart initiated"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route(f"{PANEL_PATH}/api/panel/clear-cache", methods=["POST"])
@login_required
def clear_cache():
    try:
        if privileged_enabled():privileged_call("clear_cache")
        else:
            from pathlib import Path
            for cache in Path("/opt/beeny-panel").glob("__pycache__"):shutil.rmtree(cache)
        return jsonify({"success": True, "message": "Cache cleared"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route(f"{PANEL_PATH}/api/system/uptime" if PANEL_PATH != '/' else "/api/system/uptime")
@login_required
def system_uptime():
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        panel_uptime = f"{hours}h {minutes}m"

        try:
            result=subprocess.run(['systemctl','is-active','openvpn-server@server'],capture_output=True,text=True,timeout=5)
            vpn_uptime='Running' if result.returncode==0 else (result.stdout.strip() or 'Stopped')
        except:
            vpn_uptime = "Unknown"
        return jsonify({'panel_uptime': panel_uptime, 'vpn_uptime': vpn_uptime})
    except Exception as e:
        return jsonify({'panel_uptime': 'Unknown', 'vpn_uptime': 'Unknown'})


@app.route(f"{PANEL_PATH}/api/panel/settings", methods=["POST"])
@login_required
def panel_settings():
    try:
        data = request.get_json()
        username = data.get("username", "").strip()
        password = data.get("password", "")
        panel_path = data.get("panel_path", "").strip()

        admin = db.session.get(Admin,current_user.id)
        if username and (not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}",username) or Admin.query.filter(Admin.username==username,Admin.id!=admin.id).first()):return jsonify(success=False,message="Invalid or already used username."),400
        if panel_path and (len(panel_path)>128 or not re.fullmatch(r"[A-Za-z0-9_@./-]+",panel_path) or ".." in panel_path.split("/")):return jsonify(success=False,message="Invalid panel path."),400
        changed = False
        if not check_password_hash(admin.password,data.get("current_password","")):
            return jsonify(success=False,message="Current password is incorrect."),400
        if password and not 12<=len(password)<=256:
            return jsonify(success=False,message="Password must contain 12 to 256 characters."),400

        if username:
            admin.username = username
            changed = True
        if password:
            admin.password = generate_password_hash(password)
            changed = True

        db.session.commit()

        redirect_url = PANEL_PATH.rstrip("/") + "/login"
        path_changed = bool(panel_path and panel_path.rstrip("/") != PANEL_PATH.rstrip("/"))
        if path_changed:
            panel_path = panel_path.strip()
            if not panel_path.startswith("/"):
                panel_path = "/" + panel_path
            panel_path = panel_path.rstrip("/")
            if panel_path == "":
                panel_path = "/"
            config["panel_path"] = panel_path
            with open(CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=4)
            redirect_url = panel_path + "/login"
            changed = True

        panel_sessions.revoke_all(admin.id)
        session.clear()
        logout_user()

        if path_changed:
            from privileged_server import dispatch
            result=privileged_call("service",name="beeny-panel",action="restart") if privileged_enabled() else dispatch("service",dict(name="beeny-panel",action="restart"))

        return jsonify(success=True, message="Settings saved. Sign in again." if not path_changed else "Settings saved. Panel restarting…", redirect=redirect_url, restarting=path_changed)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route(f"{PANEL_PATH}/api/vpn/restart", methods=["POST"])
@login_required
def restart_vpn():
    try:
        if privileged_enabled(): privileged_call("service",name="openvpn-server@server",action="restart")
        else: subprocess.run(["systemctl","restart","openvpn-server@server"],check=True,timeout=30)
        return jsonify({'success': True, 'message': 'OpenVPN restarted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route(f"{PANEL_PATH}/api/vpn/reset", methods=["POST"])
@login_required
def reset_vpn():
    try:
        if privileged_enabled(): privileged_call("service",name="openvpn-server@server",action="restart")
        else: subprocess.run(["systemctl","restart","openvpn-server@server"],check=True,timeout=30)
        return jsonify({'success': True, 'message': 'OpenVPN config reset completed'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route(f"{PANEL_PATH}/api/reset/panel", methods=["POST"])
@login_required
def reset_panel():
    try:
        users = User.query.all()
        for user in users:
            user.traffic_usage = 0
            user.traffic_used = 0
            user.last_session_bytes = 0
        db.session.commit()
        return jsonify({'success': True, 'message': 'Panel statistics reset completed'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route(f"{PANEL_PATH}/settings/system" if PANEL_PATH != '/' else "/settings/system")
@login_required
def system_settings():
    return render_template("system.html", panel_path=PANEL_PATH)


@app.route(f"{PANEL_PATH}/api/backup/create-db", methods=["POST"])
@login_required
def create_db_backup():
    try:
        if privileged_enabled(): filename=privileged_call('backup_create', full=False)
        else:
            from backup_engine import create
            filename=create(full=False)
        return jsonify(success=True, message="Verified database snapshot created", file=filename)
    except Exception:
        app.logger.exception("Database snapshot failed")
        return jsonify(success=False, message="Backup failed. Check service logs."), 503


@app.route(f"{PANEL_PATH}/api/backup/create-full", methods=["POST"])
@login_required
def create_full_backup():
    try:
        if privileged_enabled(): filename=privileged_call('backup_create', full=True)
        else:
            from backup_engine import create
            filename=create(full=True)
        return jsonify(success=True, message="Verified complete backup created", file=filename)
    except Exception:
        app.logger.exception("Complete backup failed")
        return jsonify(success=False, message="Backup failed. Check service logs."), 503


@app.route(f"{PANEL_PATH}/api/backup/list")
@login_required
def backup_list():
    backup_dir = "/opt/beeny-panel/backups"
    os.makedirs(backup_dir, exist_ok=True)
    files = []
    for f in sorted(os.listdir(backup_dir), reverse=True):
        path = os.path.join(backup_dir, f)
        if os.path.isfile(path) and not os.path.islink(path) and re.fullmatch(r"[A-Za-z0-9_-]+\.(?:db|tar\.gz)",f):
            files.append({"name":f,"size":round(os.path.getsize(path)/1024/1024,2),"kind":"database" if f.endswith(".db") else "complete","created":datetime.utcfromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M UTC")})
    return jsonify(files)


@app.route(f"{PANEL_PATH}/api/backup/download/<filename>")
@login_required
def download_backup(filename):
    from backup_engine import safe_file
    try: path=safe_file(filename)
    except ValueError: abort(404)
    return send_file(path, as_attachment=True)


@app.route(f"{PANEL_PATH}/settings/backup" if PANEL_PATH != '/' else "/settings/backup")
@login_required
def backup_page():
    return render_template("backup.html", panel_path=PANEL_PATH)


@app.route(f"{PANEL_PATH}/api/backup/delete/<filename>", methods=["POST"])
@login_required
def delete_backup(filename):
    try:
        from backup_engine import safe_file
        backup_file = str(safe_file(filename))
        if not os.path.exists(backup_file):
            return jsonify({"success": False, "message": "Backup not found"})
        if privileged_enabled():privileged_call('backup_delete',name=filename)
        else:
            os.remove(backup_file)
            if filename.endswith('.db'):__import__('pathlib').Path(backup_file+'.sig').unlink(missing_ok=True)
        return jsonify({"success": True, "message": "Backup deleted successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route(f"{PANEL_PATH}/api/backup/upload", methods=["POST"])
@login_required
def upload_backup():
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "message": "No file uploaded"})
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"success": False, "message": "No file selected"})
        from backup_engine import safe_file
        filename = secure_filename(file.filename)
        save_path = safe_file(filename)
        if save_path.exists(): return jsonify(success=False,message="A backup with this name already exists."),409
        if not filename.endswith('.tar.gz'): return jsonify(success=False,message="Upload a signed complete .tar.gz backup."),400
        if privileged_enabled():
            from pathlib import Path
            import secrets
            upload_root=Path(app.instance_path)/'backup_uploads';upload_root.mkdir(mode=0o700,exist_ok=True)
            source=secrets.token_hex(16);incoming=upload_root/source
            try:
                with incoming.open('xb') as output:shutil.copyfileobj(file.stream,output)
                privileged_call('backup_upload',source=source,name=filename)
            except Exception:return jsonify(success=False,message="Unsigned, damaged or incompatible backup rejected."),400
            finally:incoming.unlink(missing_ok=True)
        else:
            with save_path.open('xb') as output:shutil.copyfileobj(file.stream,output)
            try:
                from backup_engine import validate
                validate(save_path)
            except Exception:
                save_path.unlink(missing_ok=True)
                return jsonify(success=False,message="Unsigned, damaged or incompatible backup rejected."),400
        return jsonify({"success": True, "message": "Backup uploaded successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route(f"{PANEL_PATH}/api/backup/restore/<filename>", methods=["POST"])
@login_required
def restore_backup(filename):
    try:
        if privileged_enabled(): privileged_call('backup_restore',name=filename)
        else:
            from privileged_server import dispatch
            dispatch('backup_restore',dict(name=filename))
        return jsonify(success=True,message="Validated backup queued for restore. A recovery backup is created first.")
    except Exception:
        app.logger.exception("Backup validation or scheduling failed")
        return jsonify(success=False,message="Backup rejected or restore could not be scheduled. Check service logs."),400


@app.get(f"{PANEL_PATH.rstrip('/')}/api/system/services")
@login_required
def system_services():
    if getattr(current_user,'role','')!='owner':abort(403)
    services={}
    for name in ('beeny-panel','beeny-customer-worker','openvpn-server@server'):
        try:
            if privileged_enabled():services[name]=privileged_call('service',name=name,action='status')
            else:
                from privileged_server import dispatch
                services[name]=dispatch('service',dict(name=name,action='status'))
        except Exception:services[name]=dict(active=None,state='Unknown')
    return jsonify(success=True,services=services)


@app.route(f"{PANEL_PATH}/api/system/restart/<service>", methods=["POST"])
@login_required
def restart_service(service):
    try:
        if privileged_enabled(): result=privileged_call('service',name=service,action='restart')
        else:
            from privileged_server import dispatch
            result=dispatch('service',dict(name=service,action='restart'))
        return jsonify(success=True,service=service,**result)
    except Exception:
        return jsonify(success=False,message="Service restart failed or is not permitted."),503


@app.route(f"{PANEL_PATH}/settings/ssl" if PANEL_PATH != '/' else "/settings/ssl")
@login_required
def ssl_page():
    return render_template("ssl.html", panel_path=PANEL_PATH)


@app.post(PANEL_PATH.rstrip('/')+'/api/ssl/action')
@login_required
def ssl_action():
    if current_user.role!='owner':abort(403)
    action=request.form.get('action')
    try:
        if privileged_enabled():result=privileged_call('https_action',action=action)
        else:
            from https_maintenance import schedule
            result=schedule(action)
        return jsonify(result)
    except ValueError as exc:return jsonify(success=False,message=str(exc)),400
    except Exception:
        app.logger.exception('HTTPS maintenance request failed')
        return jsonify(success=False,message='Could not queue HTTPS action. A job may already be running; refresh status.'),409


@app.route(f"{PANEL_PATH}/api/ssl/info", methods=["GET"])
@login_required
def ssl_info():
    try:
        if privileged_enabled():return jsonify(privileged_call('https_status'))
        from privileged_server import dispatch
        return jsonify(dispatch('https_status',{}))
    except Exception:
        app.logger.exception('HTTPS status unavailable')
        return jsonify(success=False,message='Could not inspect certificate or renewal scheduler.'),503


@app.route(f"{PANEL_PATH}/settings/openvpn" if PANEL_PATH != '/' else "/settings/openvpn")
@login_required
def openvpn_page():
    return render_template("openvpn.html", panel_path=PANEL_PATH)


@app.route(f"{PANEL_PATH}/api/openvpn/info" if PANEL_PATH != '/' else "/api/openvpn/info")
@login_required
def openvpn_info():
    try:
        config_file = "/etc/openvpn/server/server.conf"
        status = subprocess.run(["systemctl", "is-active", "openvpn-server@server"], capture_output=True, text=True).stdout.strip()
        protocol = port = cipher = auth = network = "-"

        if privileged_enabled() or os.path.exists(config_file):
            text=privileged_call('vpn_info')['config'] if privileged_enabled() else open(config_file).read()
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("proto "): protocol = line.split()[1].upper()
                elif line.startswith("port "): port = line.split()[1]
                elif line.startswith("cipher "): cipher = line.split()[1]
                elif line.startswith("auth "): auth = line.split()[1]
                elif line.startswith("server "):
                    parts = line.split()
                    if len(parts) >= 3: network = str(__import__("ipaddress").IPv4Network((parts[1],parts[2]),strict=False))
        connected_users = None
        try:
            log=privileged_call('status_log')['log'] if privileged_enabled() else open('/var/log/openvpn-status.log').read()
            connected_users=len(parse_status(log)) if status=='active' else 0
        except: pass

        return jsonify({
            "success": True, "status": "Running" if status == "active" else "Stopped", "protocol": protocol,
            "port": port, "cipher": cipher, "auth": auth, "network": network, "users": connected_users
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


from customer_features import register as register_customer_features
customer_features = register_customer_features(app, db, User, AccountLink, TrafficDailyUser, Node, UserNode,
                                              account_from_token, build_config, PANEL_PATH, is_primary_node)
from experience import register as register_experience
experience = register_experience(app, db, User, Node, UserNode, customer_features, PANEL_PATH, is_primary_node)

from monitoring import register as register_monitoring
monitoring=register_monitoring(app,db,Node,PANEL_PATH,is_primary_node,privileged_enabled,privileged_call)

from host_traffic import register as register_host_traffic
host_traffic=register_host_traffic(db)

from health import register as register_health
health = register_health(app,db,Node,PANEL_PATH,is_primary_node)

from bulk import register as register_bulk
bulk=register_bulk(app,db,User,customer_features,experience,PANEL_PATH)

from devices import register as register_devices
devices=register_devices(app,db,User,Node,UserNode,customer_features,PANEL_PATH,is_primary_node)

from commerce import register as register_commerce
commerce=register_commerce(app,db,User,customer_features,experience,PANEL_PATH)

from resellers import register as register_resellers
resellers=register_resellers(app,db,User,Node,UserNode,AccountLink,customer_features,experience,commerce,PANEL_PATH,is_primary_node)
from commissions import register as register_commissions
commissions=register_commissions(app,db,User,Node,UserNode,AccountLink,customer_features,experience,commerce,resellers,PANEL_PATH)

from sales_engine import register as register_sales_engine
sales_engine=register_sales_engine(app,db,commerce,customer_features,PANEL_PATH)
from representative_credit import register as register_representative_credit
representative_credit=register_representative_credit(app,db,User,Node,UserNode,AccountLink,customer_features,experience,commerce,resellers,commissions,PANEL_PATH)

from balepay_bridge import register as register_balepay_bridge
balepay_orders = register_balepay_bridge(app,db,User,customer_features,experience,PANEL_PATH)

from representative_actions import register as register_representative_actions
representative_actions=register_representative_actions(app,db,User,customer_features,experience,commerce,resellers,commissions,representative_credit,PANEL_PATH)

from crl_sync import register as register_crl_sync
crl_sync=register_crl_sync(app,db,Node,is_primary_node,privileged_enabled,privileged_call)
from admission import register as register_admission
connection_guard=__import__('connection_guard').register(db)
__import__('connection_guard').register_routes(app,db,connection_guard,User,PANEL_PATH)
admission=register_admission(app,db,User,Node,UserNode,customer_features,devices,representative_credit,representative_actions,PANEL_PATH)
from representative_catalog import register as register_representative_catalog
representative_catalog=register_representative_catalog(app,db,User,customer_features,representative_credit,commissions,resellers,PANEL_PATH)

from support import register as register_support
support = register_support(app,db,User,customer_features,experience,PANEL_PATH)

from security import register as register_security
security = register_security(app,db,Admin,customer_features,PANEL_PATH)
from admin_sessions import register as register_panel_sessions
panel_sessions = register_panel_sessions(app, db, Admin, customer_features, PANEL_PATH)

from portal_content import register as register_portal_content
portal_content = register_portal_content(app, db, User, customer_features, PANEL_PATH)
from portal_i18n import register as register_portal_i18n
register_portal_i18n(app)

from speed_policy import register as register_speed_policy
speed_policy=register_speed_policy(app,db,User,Node,UserNode,customer_features,PANEL_PATH,is_primary_node)
from transport_settings import register as register_transport_settings
transport_settings=register_transport_settings(app,db,Node,customer_features,PANEL_PATH,is_primary_node)
from tunnel_settings import register as register_tunnel_settings
tunnel_settings=register_tunnel_settings(app,db,Node,customer_features,PANEL_PATH,is_primary_node)

from dns_services import register as register_dns_services
register_dns_services(app,db,User,Node,UserNode,customer_features,PANEL_PATH)

from admin_i18n import register as register_admin_i18n
register_admin_i18n(app,db,Admin,PANEL_PATH)

from representative_removal import register as register_representative_removal
register_representative_removal(app,db,PANEL_PATH)

from network_settings import register as register_network_settings
register_network_settings(app,db,Node,PANEL_PATH,is_primary_node,privileged_enabled,privileged_call)

if __name__ == "__main__":
    with app.app_context():
        from migrations import upgrade
        upgrade(db)
        ensure_primary_node()
        reconcile_primary_access()
    monitoring.start()
    Thread(target=background_updater, daemon=True).start()
    app.run(host=os.environ.get("BEENY_BIND", "127.0.0.1"), port=int(os.environ.get("BEENY_PORT", "8080")), debug=False)

