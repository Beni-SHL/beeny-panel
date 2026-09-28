#!/usr/bin/env python3
"""
Beeny Panel - VPN Management System (Fully Integrated & Fixed)
"""

from flask import Flask, render_template, request, redirect, send_file, jsonify, session, abort
import subprocess
import os
from threading import Thread
import time
from datetime import datetime, timedelta
import shutil
import json
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
import psutil
from werkzeug.utils import secure_filename
import ssl
import requests
import io
import math
import re
import socket
import secrets
import hashlib
from renewal import extend_expiry, activation_error
from traffic_ledger import parse_status, usage_delta

PRIMARY_NODE_KEY = "__beeny_local_primary__"

# Load config
CONFIG_FILE = "/opt/beeny-panel/config.json"
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

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("BEENY_SECRET_KEY", "")
if not app.config["SECRET_KEY"]:
    raise RuntimeError("BEENY_SECRET_KEY must be set by the installer")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("BEENY_PUBLIC_HTTPS") == "1"
app.config["REMEMBER_COOKIE_SECURE"] = app.config["SESSION_COOKIE_SECURE"]
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=7)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///beeny.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


# ==================== MODELS ====================

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(255))

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    protocol = db.Column(db.String(20), default="openvpn")
    max_devices = db.Column(db.Integer, default=1)
    current_devices = db.Column(db.Integer, default=0)
    expire_date = db.Column(db.String(20))
    status = db.Column(db.String(20), default="active")
    online = db.Column(db.Boolean, default=False)
    online_status = db.Column(db.String(20), default="offline")
    traffic_limit = db.Column(db.Integer, default=10)
    traffic_usage = db.Column(db.Float, default=0)
    traffic_used = db.Column(db.BigInteger, default=0)
    last_session_bytes = db.Column(db.BigInteger, default=0)

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
    """Apply the local node selection using OpenVPN's per-client CCD."""
    ccd_file = f"/etc/openvpn/ccd/{user.username}"
    if user.status != "active" or not primary_selected:
        os.makedirs("/etc/openvpn/ccd", exist_ok=True)
        with open(ccd_file, "w") as handle:
            handle.write("disable\n")
        if user.status == "active":
            try:
                with socket.create_connection(("127.0.0.1", 7505), timeout=1) as management:
                    management.sendall(f"kill {user.username}\n".encode("ascii"))
            except OSError:
                pass
    elif os.path.exists(ccd_file):
        os.remove(ccd_file)


@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))


# ==================== GLOBAL UTILITIES ====================

def disable_user_globally(user):
    """غیرفعال سازی کامل کاربر (نوشتن فایل disable در ccd) به دلیل اتمام حجم/زمان"""
    username = user.username
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", username):
        return
    ccd_file = f"/etc/openvpn/ccd/{username}"
    try:
        with open(ccd_file, "w") as f: 
            f.write("disable\n")
    except: 
        pass
    kick_user_globally(user)

def kick_user_globally(user):
    """فقط اخراج آنی کاربر از کل نودها و سرور اصلی، بدون دستکاری فایل ccd
       این مورد مشکل Ghost Connections را وقتی دیوایس اضافه متصل می‌شود حل میکند"""
    username = user.username
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", username):
        return
    try:
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
                address = target.strip()
                if not address.startswith("http"): address = f"http://{address}"
                if ":" not in address.replace("http://", "").replace("https://", ""): address = f"{address}:5001"
                
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
    nodes = Node.query.all()
    presence = {}
    today = datetime.utcnow().date().isoformat()
    for node in nodes:
        try:
            if is_primary_node(node):
                with open("/var/log/openvpn-status.log", encoding="utf-8") as stream:
                    log = stream.read()
            else:
                target = (node.host or node.ip).strip()
                if not target:
                    continue
                address = target if target.startswith(("http://", "https://")) else f"http://{target}"
                if ":" not in address.split("//", 1)[-1]:
                    address += ":5001"
                response = requests.get(f"{address}/api/node/status-log",
                                        headers={"Authorization": f"Bearer {node.api_key}"}, timeout=3)
                response.raise_for_status()
                log = response.json().get("log", "")
            clients = parse_status(log)
            node.status = 'online'
            seen = set()
            for username, session_key, received, sent, address in clients:
                if session_key in seen:
                    continue
                seen.add(session_key)
                sample = TrafficSample.query.filter_by(node_id=node.id, session_key=session_key).first()
                diff_received = usage_delta(sample.last_received if sample else None, received)
                diff_sent = usage_delta(sample.last_sent if sample else None, sent)
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
                details = presence.setdefault(username, {"bytes": 0, "connections": 0, "address": address})
                details["bytes"] += diff
                details["connections"] += 1
                user = User.query.filter_by(username=username).first()
                if user and diff:
                    user_daily = TrafficDailyUser.query.filter_by(user_id=user.id, day=today).first()
                    if user_daily is None:
                        user_daily = TrafficDailyUser(user_id=user.id, day=today, bytes_total=0)
                        db.session.add(user_daily)
                        db.session.flush()
                    user_daily.bytes_total += diff
            db.session.commit()
        except Exception:
            app.logger.exception("Could not collect VPN status from node %s", node.name)
            db.session.rollback()
            node.status = 'offline'
            continue
    for user in User.query.all():
        details = presence.get(user.username)
        user.online = bool(details)
        user.online_status = "online" if details else "offline"
        user.current_devices = details["connections"] if details else 0
        if details:
            user.traffic_used = (user.traffic_used or 0) + details["bytes"]
            user.traffic_usage = round(user.traffic_used / 1073741824, 3)
            if details["bytes"] and user.expire_date and user.expire_date.isdigit():
                user.expire_date = (datetime.now().date() + timedelta(days=int(user.expire_date))).isoformat()
            if user.max_devices and user.current_devices > user.max_devices:
                kick_user_globally(user)
        if activation_error(user.expire_date, user.traffic_limit, user.traffic_usage or 0):
            user.status = "disabled"
            disable_user_globally(user)
    db.session.commit()


def background_updater():
    while True:
        try:
            with app.app_context():
                update_openvpn_status()
        except Exception as e:
            print(f"[UPDATER ERROR] {e}", flush=True)
        time.sleep(10)


# ==================== AUTH ROUTES ====================

@app.route(f"{PANEL_PATH}/login" if PANEL_PATH != '/' else "/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        admin = Admin.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password, password):
            login_user(admin, remember=request.form.get("remember") == "1")
            return redirect(f"{PANEL_PATH}")
        return render_template("login.html", error="Invalid username or password", panel_path=PANEL_PATH)
    return render_template("login.html", panel_path=PANEL_PATH)

@app.route(f"{PANEL_PATH}/logout" if PANEL_PATH != '/' else "/logout")
@login_required
def logout():
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
    return render_template('traffic.html', panel_path=PANEL_PATH, nodes=nodes,
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
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request.form.get("username", "")):
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Username must use only letters, numbers, underscore or hyphen."), 400
    if request.form.get("protocol") != "openvpn":
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Only OpenVPN is supported by this installation."), 400
        
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

    user = User(
        username=request.form["username"],
        protocol=request.form["protocol"],
        max_devices=max_devices,
        expire_date=expire_val,
        status=initial_status,
        traffic_limit=traffic_limit
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
    if User.query.filter_by(username=user.username).first():
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Username already exists."), 409
    try:
        subprocess.run(["/opt/beeny-panel/scripts/create_vpn_user.sh", user.username], check=True, timeout=120)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="VPN certificate creation failed; see the panel service log."), 500

    db.session.add(user)
    db.session.flush()

    for node_id in selected_ids:
        db.session.add(UserNode(user_id=user.id, node_id=node_id))
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
        problem = activation_error(next_expiry, new_limit, usage_after_edit)
        if problem:
            return invalid(problem)

    user.protocol = request.form["protocol"]
    user.max_devices = max_devices
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
            synced, reason = set_user_state_on_node(node, user.username, user.status == 'active')
            if not synced:
                node_sync_failed = True
                app.logger.error('Node status sync failed for %s on %s: %s', user.username, node.name, reason)
    base = PANEL_PATH.rstrip('/')
    return redirect(f"{base}/users/view/{user.id}?notice=updated" + ('&sync_warning=1' if node_sync_failed else ''))

@app.route(f"{PANEL_PATH}/users/delete/<int:user_id>" if PANEL_PATH != '/' else "/users/delete/<int:user_id>")
@login_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    disable_user_globally(user)
    
    # حذف کامل از تمامی نودها
    from cluster import delete_user_on_node
    user_nodes = UserNode.query.filter_by(user_id=user_id).all()
    for rel in user_nodes:
        node = Node.query.get(rel.node_id)
        if node and not is_primary_node(node):
            try: delete_user_on_node(node, user.username)
            except: pass
            
    UserNode.query.filter_by(user_id=user_id).delete()
    AccountLink.query.filter_by(user_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()
    return redirect(f"{PANEL_PATH}/users" if PANEL_PATH != '/' else "/users")


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
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        abort(404)
    digest = hashlib.sha256(token.encode('ascii')).hexdigest()
    link = AccountLink.query.filter_by(token_hash=digest).first()
    if link is None:
        abort(404)
    return User.query.get_or_404(link.user_id)


@app.get(f"{PANEL_PATH}/c/<token>" if PANEL_PATH != '/' else "/c/<token>")
def customer_portal(token):
    user = account_from_token(token)
    assigned = [Node.query.get(rel.node_id) for rel in UserNode.query.filter_by(user_id=user.id).all()]
    since = (datetime.utcnow().date() - timedelta(days=13)).isoformat()
    rows = TrafficDailyUser.query.filter(TrafficDailyUser.user_id == user.id,
                                         TrafficDailyUser.day >= since).order_by(TrafficDailyUser.day).all()
    daily = {row.day: round(row.bytes_total / 1073741824, 3) for row in rows}
    days = [(datetime.utcnow().date() - timedelta(days=offset)).isoformat() for offset in range(13, -1, -1)]
    response = app.make_response(render_template('customer_portal.html', user=user, token=token,
                                                 nodes=[node for node in assigned if node],
                                                 daily=[(day, daily.get(day, 0)) for day in days],
                                                 panel_path=PANEL_PATH,
                                                 remaining=max(0, user.traffic_limit - (user.traffic_usage or 0)) if user.traffic_limit else None))
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


def build_config(user, requested_node_id=None):
    username = user.username
    try:
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
    except OSError:
        app.logger.exception("VPN client material is missing for %s", username)
        return "VPN configuration is unavailable. Check the panel service log for the missing certificate or key.", 503

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
        target = (os.environ.get("BEENY_PUBLIC_HOST", "") if is_primary_node(node_obj)
                  else (node_obj.host or node_obj.ip)).strip()
        target = target.removeprefix("https://").removeprefix("http://").split("/")[0].split(":")[0]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", target):
            raise ValueError("Invalid VPN node address")
        return target

    try:
        remotes_block = "\n".join(
            f"remote {clean_address(node)} {os.environ.get('BEENY_VPN_PORT', '110')}"
            for node in nodes_to_download
        )
    except ValueError:
        return "An assigned node has an invalid VPN address.", 503
    if len(nodes_to_download) > 1:
        remotes_block = "remote-random\n" + remotes_block

    ovpn_template = f"""client
dev tun
proto tcp
{remotes_block.strip()}

resolv-retry infinite
nobind
persist-key
persist-tun

remote-cert-tls server

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
    filename = f"Beeny_{username}_{suffix}.ovpn"
    
    return send_file(mem_file, as_attachment=True, download_name=filename, mimetype='application/x-openvpn-profile')


@app.route(f"{PANEL_PATH}/users/reset_traffic/<int:user_id>" if PANEL_PATH != '/' else "/users/reset_traffic/<int:user_id>")
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
    per_page = request.args.get('per_page', 10, type=int)
    
    query = User.query

    if q: query = query.filter(User.username.ilike(f"%{q}%"))
    if protocol: query = query.filter(User.protocol == protocol)
    if status: query = query.filter(User.status == status)

    if sort_by == 'traffic_desc': query = query.order_by(User.traffic_usage.desc())
    elif sort_by == 'traffic_asc': query = query.order_by(User.traffic_usage.asc())
    elif sort_by == 'oldest': query = query.order_by(User.id.asc())
    else: query = query.order_by(User.id.desc())

    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    users = paginated.items

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
                
        relations = UserNode.query.filter_by(user_id=u.id).all()
        nodes_list_data = []  
        for rel in relations:
            node = Node.query.get(rel.node_id)
            if node: nodes_list_data.append({'id': node.id, 'name': node.name, 'country': node.country})

        users_data.append({
            'id': u.id, 'username': u.username, 'protocol': u.protocol, 'status': u.status,
            'online_status': u.online_status, 'current_devices': u.current_devices, 'max_devices': u.max_devices,
            'expire_days_val': u.expire_date if (u.expire_date and u.expire_date.isdigit()) else '',
            'days_left_text': days_left_text, 'traffic_usage': round(u.traffic_usage or 0, 1), 'traffic_limit': u.traffic_limit or 0,
            'traffic_percent': round(((u.traffic_usage or 0) / u.traffic_limit * 100), 1) if u.traffic_limit and u.traffic_limit > 0 else 0,
            'nodes_list': nodes_list_data   
        })   

    return jsonify({
        'users': users_data,
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
    db_path = "/opt/beeny-panel/instance/beeny.db"
    db_size = 0
    if os.path.exists(db_path):
        db_size = round(os.path.getsize(db_path) / (1024 * 1024), 2)
    
    total_users = User.query.count()
    active_users = User.query.filter_by(status="active").count()
    online_users = User.query.filter_by(online=True).count()
    total_traffic = round(db.session.query(db.func.sum(User.traffic_usage)).scalar() or 0, 1)
    
    return render_template(
        "settings_monitoring.html",
        panel_path=PANEL_PATH,
        db_size=db_size,
        total_users=total_users,
        active_users=active_users,
        online_users=online_users,
        total_traffic=total_traffic
    )


@app.route(f"{PANEL_PATH}/settings/general" if PANEL_PATH != '/' else "/settings/general")
@login_required
def settings_general():
    return render_template("settings_general.html", panel_path=PANEL_PATH)


@app.route(f"{PANEL_PATH}/settings" if PANEL_PATH != '/' else "/settings")
@login_required
def settings():
    try:
        db_path = "/opt/beeny-panel/instance/beeny.db"
        db_size = 0
        if os.path.exists(db_path):
            db_size = round(os.path.getsize(db_path) / (1024 * 1024), 2)
        
        total_users = User.query.count()
        active_users = User.query.filter_by(status="active").count()
        online_users = User.query.filter_by(online=True).count()
        total_traffic = round(db.session.query(db.func.sum(User.traffic_usage)).scalar() or 0, 1)
        
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_cores = psutil.cpu_count()
        memory = psutil.virtual_memory()
        ram_percent = memory.percent
        ram_used = round(memory.used / (1024**3), 1)
        ram_total = round(memory.total / (1024**3), 1)
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_used = round(disk.used / (1024**3), 1)
        disk_free = round(disk.free / (1024**3), 1)
        
        try:
            cpu_temp = psutil.sensors_temperatures().get('coretemp', [{}])[0].get('current', 45)
        except:
            cpu_temp = 45
    except:
        cpu_percent = ram_percent = disk_percent = 0
        cpu_cores = ram_used = ram_total = disk_used = disk_free = cpu_temp = 0
        online_users = db_size = total_users = active_users = total_traffic = 0
    
    return render_template(
        "settings.html",
        db_size=db_size,
        total_users=total_users,
        active_users=active_users,
        online_users=online_users,
        total_traffic=total_traffic,
        cpu_percent=cpu_percent,
        cpu_cores=cpu_cores,
        cpu_temp=cpu_temp,
        memory_percent=ram_percent,
        memory_used=ram_used,
        memory_total=ram_total,
        disk_percent=disk_percent,
        disk_used=disk_used,
        disk_free=disk_free,
        panel_path=PANEL_PATH
    )


# ==================== NODES MANAGEMENT ====================

@app.route(f"{PANEL_PATH}/settings/nodes" if PANEL_PATH != '/' else "/settings/nodes")
@login_required
def nodes_page():
    nodes = Node.query.all()
    for node in nodes:
        if is_primary_node(node):
            node.status = "online"
            continue
        try:
            target = node.host if node.host else node.ip
            if not target:
                node.status = 'offline'
                continue
            host_address = target.strip()
            if not host_address.startswith("http://") and not host_address.startswith("https://"):
                host_url = f"http://{host_address}"
            else:
                host_url = host_address
            if ":" not in host_url.replace("http://", "").replace("https://", ""):
                host_url = f"{host_url}:5001"
                
            r = requests.get(f"{host_url}/api/node/stats", headers={"Authorization": f"Bearer {node.api_key}"}, timeout=3)
            if r.status_code == 200 and r.json().get("status") == "online":
                node.status = "online"
            else:
                node.status = "offline"
        except Exception:
            node.status = "offline"
            
    db.session.commit()
    return render_template("nodes.html", nodes=nodes, panel_path=PANEL_PATH)


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
        return redirect(f"{PANEL_PATH}/settings/nodes" if PANEL_PATH != '/' else "/settings/nodes")
    if request.form.get("api_key") == PRIMARY_NODE_KEY:
        return "Reserved node identifier.", 400
    node.name = name
    node.ip = request.form.get("ip")
    node.host = request.form.get("host")
    node.country = country
    node.protocol = request.form.get("protocol")
    node.api_key = request.form.get("api_key")
    
    db.session.commit()
    return redirect(f"{PANEL_PATH}/settings/nodes")


@app.route(f"{PANEL_PATH}/settings/nodes/delete/<int:node_id>")
@login_required
def delete_node(node_id):
    node = Node.query.get_or_404(node_id)
    if is_primary_node(node):
        return "The primary node cannot be deleted.", 403
    UserNode.query.filter_by(node_id=node_id).delete()
    db.session.delete(node)
    db.session.commit()
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
        return jsonify({"hostname": "Unknown", "cpu": 0, "ram": 0, "disk": 0, "uptime": "Unknown"})


@app.route(f"{PANEL_PATH}/api/system/stats" if PANEL_PATH != '/' else "/api/system/stats")
@login_required
def system_stats():
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_cores = psutil.cpu_count()
        memory = psutil.virtual_memory()
        ram_percent = memory.percent
        ram_used = round(memory.used / (1024**3), 1)
        ram_total = round(memory.total / (1024**3), 1)
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_used = round(disk.used / (1024**3), 1)
        disk_free = round(disk.free / (1024**3), 1)
        net_io = psutil.net_io_counters()
        net_speed = round((net_io.bytes_sent + net_io.bytes_recv) / (1024**2), 1)
        net_tx = round(net_io.bytes_sent / (1024**2), 1)
        net_rx = round(net_io.bytes_recv / (1024**2), 1)
        
        return jsonify({
            'cpu': cpu_percent, 'cpu_cores': cpu_cores, 'ram': ram_percent, 'ram_used': ram_used, 'ram_total': ram_total,
            'disk': disk_percent, 'disk_used': disk_used, 'disk_free': disk_free, 'network': net_speed, 'network_tx': net_tx, 'network_rx': net_rx
        })
    except Exception as e:
        return jsonify({'cpu': 0, 'ram': 0, 'disk': 0, 'network': 0})


@app.route(f"{PANEL_PATH}/api/panel/restart", methods=["POST"])
@login_required
def restart_panel():
    try:
        subprocess.Popen(["bash", "-c", "sleep 1 && systemctl restart beeny-panel"])
        return jsonify({"success": True, "message": "Panel restart initiated"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route(f"{PANEL_PATH}/api/panel/clear-cache", methods=["POST"])
@login_required
def clear_cache():
    try:
        os.system("find /opt/beeny-panel -name '__pycache__' -type d -exec rm -rf {} +")
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
            subprocess.run(['systemctl', 'show', 'openvpn-server@server', '--property=ActiveEnterTimestamp'], capture_output=True, text=True, timeout=5)
            vpn_uptime = "Running"
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
        password = data.get("password", "").strip()
        panel_path = data.get("panel_path", "").strip()

        admin = Admin.query.first()
        changed = False

        if username:
            admin.username = username
            changed = True
        if password:
            admin.password = generate_password_hash(password)
            changed = True

        db.session.commit()

        redirect_url = "/login"
        if panel_path:
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

        session.clear()
        logout_user()

        if changed:
            subprocess.Popen(["bash", "-c", "sleep 2 && systemctl restart beeny-panel"])

        return jsonify({"success": True, "message": "Settings saved successfully. Panel restarting...", "redirect": redirect_url})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route(f"{PANEL_PATH}/api/vpn/restart", methods=["POST"])
@login_required
def restart_vpn():
    try:
        os.system("systemctl restart openvpn-server@server >/dev/null 2>&1")
        return jsonify({'success': True, 'message': 'OpenVPN restarted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route(f"{PANEL_PATH}/api/vpn/reset", methods=["POST"])
@login_required
def reset_vpn():
    try:
        os.system("systemctl stop openvpn-server@server >/dev/null 2>&1")
        time.sleep(2)
        os.system("systemctl start openvpn-server@server >/dev/null 2>&1")
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
        backup_dir = "/opt/beeny-panel/backups"
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_file = f"{backup_dir}/db_{timestamp}.db"
        shutil.copy2("/opt/beeny-panel/instance/beeny.db", backup_file)
        return jsonify({"success": True, "message": "Database backup created", "file": os.path.basename(backup_file)})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route(f"{PANEL_PATH}/api/backup/create-full", methods=["POST"])
@login_required
def create_full_backup():
    try:
        backup_dir = "/opt/beeny-panel/backups"
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archive = f"{backup_dir}/full_{timestamp}.tar.gz"
        subprocess.run(["tar", "-czf", archive, "/opt/beeny-panel/app.py", "/opt/beeny-panel/config.json", "/opt/beeny-panel/templates", "/opt/beeny-panel/static", "/opt/beeny-panel/instance/beeny.db"])
        return jsonify({"success": True, "message": "Full backup created", "file": os.path.basename(archive)})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route(f"{PANEL_PATH}/api/backup/list")
@login_required
def backup_list():
    backup_dir = "/opt/beeny-panel/backups"
    os.makedirs(backup_dir, exist_ok=True)
    files = []
    for f in sorted(os.listdir(backup_dir), reverse=True):
        path = os.path.join(backup_dir, f)
        files.append({"name": f, "size": round(os.path.getsize(path) / 1024 / 1024, 2)})
    return jsonify(files)


@app.route(f"{PANEL_PATH}/api/backup/download/<filename>")
@login_required
def download_backup(filename):
    return send_file(f"/opt/beeny-panel/backups/{filename}", as_attachment=True)


@app.route(f"{PANEL_PATH}/settings/backup" if PANEL_PATH != '/' else "/settings/backup")
@login_required
def backup_page():
    return render_template("backup.html", panel_path=PANEL_PATH)


@app.route(f"{PANEL_PATH}/api/backup/delete/<filename>", methods=["POST"])
@login_required
def delete_backup(filename):
    try:
        backup_file = os.path.join("/opt/beeny-panel/backups", filename)
        if not os.path.exists(backup_file):
            return jsonify({"success": False, "message": "Backup not found"})
        os.remove(backup_file)
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
        filename = secure_filename(file.filename)
        save_path = os.path.join("/opt/beeny-panel/backups", filename)
        file.save(save_path)
        return jsonify({"success": True, "message": "Backup uploaded successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route(f"{PANEL_PATH}/api/backup/restore/<filename>", methods=["POST"])
@login_required
def restore_backup(filename):
    try:
        backup_file = os.path.join("/opt/beeny-panel/backups", filename)
        if not os.path.exists(backup_file):
            return jsonify({"success": False, "message": "Backup file not found"})

        if filename.endswith(".db"):
            shutil.copy2(backup_file, "/opt/beeny-panel/instance/beeny.db")
        elif filename.endswith(".tar.gz"):
            subprocess.run(["tar", "-xzf", backup_file, "-C", "/"])
        else:
            return jsonify({"success": False, "message": "Unsupported backup type"})

        subprocess.Popen(["bash", "-c", "sleep 2 && systemctl restart beeny-panel"])
        return jsonify({"success": True, "message": "Backup restored. Panel restarting..."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route(f"{PANEL_PATH}/api/system/restart/<service>", methods=["POST"])
@login_required
def restart_service(service):
    try:
        if service == "beeny-panel":
            subprocess.Popen(["bash", "-c", "sleep 2 && systemctl restart beeny-panel"])
        else:
            subprocess.run(["systemctl", "restart", service], check=True)
        return jsonify({"success": True, "service": service})
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})
        

@app.route(f"{PANEL_PATH}/settings/ssl" if PANEL_PATH != '/' else "/settings/ssl")
@login_required
def ssl_page():
    return render_template("ssl.html", panel_path=PANEL_PATH)


@app.route(f"{PANEL_PATH}/api/ssl/info", methods=["GET"])
@login_required
def ssl_info():
    try:
        cert_path = "/etc/letsencrypt/live/panel.app2.shop/fullchain.pem"
        if not os.path.exists(cert_path):
            return jsonify({"success": False, "message": "SSL certificate not found"})
        cert = ssl._ssl._test_decode_cert(cert_path)
        expire_date = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
        days_left = (expire_date - datetime.utcnow()).days
        issuer = ""
        for item in cert["issuer"]:
            if item[0][0] == "commonName":
                issuer = item[0][1]
        return jsonify({
            "success": True, "domain": "panel.app2.shop", "issuer": issuer, "expire_date": expire_date.strftime("%Y-%m-%d"),
            "days_left": days_left, "status": "Active" if days_left > 0 else "Expired", "auto_renew": True
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})        


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

        if os.path.exists(config_file):
            with open(config_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("proto "): protocol = line.split()[1].upper()
                    elif line.startswith("port "): port = line.split()[1]
                    elif line.startswith("cipher "): cipher = line.split()[1]
                    elif line.startswith("auth "): auth = line.split()[1]
                    elif line.startswith("server "):
                        parts = line.split()
                        if len(parts) >= 3: network = f"{parts[1]}/24"

        connected_users = 0
        try:
            with open("/var/log/openvpn-status.log", "r") as f:
                for line in f:
                    if line.startswith("CLIENT_LIST"): connected_users += 1
        except: pass

        return jsonify({
            "success": True, "status": "Running" if status == "active" else "Stopped", "protocol": protocol,
            "port": port, "cipher": cipher, "auth": auth, "network": network, "users": connected_users
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


if __name__ == "__main__":
    with app.app_context():
        db.create_all() # ساخت جدول‌ها در صورت عدم وجود
        ensure_primary_node()
    Thread(target=background_updater, daemon=True).start()
    app.run(host=os.environ.get("BEENY_BIND", "127.0.0.1"), port=int(os.environ.get("BEENY_PORT", "8080")), debug=False)
