#!/usr/bin/env python3
"""
Beeny Panel - VPN Management System (Fully Integrated & Fixed)
"""

from flask import Flask, render_template, request, redirect, send_file, jsonify, session
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
import re
import socket
from renewal import extend_expiry, activation_error

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
            if node:
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
    """تجمیع حجم مصرفی و وضعیت آنلاین کاربران از تمام سرورها به صورت غیرمسدودکننده"""
    online_users = {}
    
    def parse_log_data(log_text):
        if not log_text: return
        for line in log_text.splitlines():
            if line.startswith("CLIENT_LIST"):
                parts = line.strip().split(",")
                if len(parts) >= 7:
                    username = parts[1]
                    try:
                        total_bytes = int(parts[5]) + int(parts[6])
                        if username not in online_users:
                            online_users[username] = {"bytes": total_bytes, "connections": 1}
                        else:
                            online_users[username]["connections"] += 1
                            online_users[username]["bytes"] += total_bytes
                    except: pass

    try:
        if os.path.exists("/var/log/openvpn-status.log"):
            with open("/var/log/openvpn-status.log", "r") as f:
                parse_log_data(f.read())
    except: pass
    
    try:
        nodes = Node.query.all()
        for node in nodes:
            if node.status == "offline": continue
            try:
                target = node.host if node.host else node.ip
                if not target: continue
                address = target.strip()
                if not address.startswith("http"): address = f"http://{address}"
                if ":" not in address.replace("http://", "").replace("https://", ""): address = f"{address}:5001"
                
                r = requests.get(
                    f"{address}/api/node/status-log", 
                    headers={"Authorization": f"Bearer {node.api_key}"}, 
                    timeout=1.0
                )
                if r.status_code == 200:
                    parse_log_data(r.json().get("log", ""))
            except: pass
    except: pass
        
    for user in User.query.all():
        if user.username in online_users:
            current_bytes = online_users[user.username]["bytes"]
            device_count = online_users[user.username]["connections"]
            
            if user.traffic_used is None: user.traffic_used = 0
            if user.last_session_bytes is None: user.last_session_bytes = 0
            
            if user.last_session_bytes == -1:
                diff = 0
            elif current_bytes >= user.last_session_bytes:
                diff = current_bytes - user.last_session_bytes
            else:
                diff = current_bytes
            
            user.traffic_used += diff
            user.last_session_bytes = current_bytes
            user.traffic_usage = round(user.traffic_used / 1073741824, 2)
            user.online_status = "online"
            user.online = True
            user.current_devices = device_count
            
            # --- منطق استارت تاریخ انقضا در اولین اتصال ---
            if user.traffic_usage > 0 and user.expire_date and user.expire_date.isdigit():
                days_to_add = int(user.expire_date)
                user.expire_date = (datetime.now() + timedelta(days=days_to_add)).strftime("%Y-%m-%d")
            
            # --- تفکیک اخراج موقت (دیوایس) از غیرفعال شدن کامل (حجم) ---
            if (user.traffic_limit > 0 and user.traffic_usage >= user.traffic_limit):
                user.status = "disabled"
                disable_user_globally(user)
            elif (user.max_devices and device_count > user.max_devices):
                kick_user_globally(user) # فقط کیک میکنه تا وقتی یکی از دیوایس ها قطع شد بلافاصله بتونه وصل بشه
                
        else:
            user.online_status = "offline"
            user.online = False
            user.current_devices = 0
            
        try:
            if user.expire_date and not user.expire_date.isdigit() and user.expire_date != "-":
                if datetime.strptime(user.expire_date, "%Y-%m-%d").date() < datetime.now().date():
                    user.status = "disabled"
                    disable_user_globally(user)
        except: pass
        
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
            login_user(admin)
            return redirect(f"{PANEL_PATH}")
        return render_template("login.html", error="Invalid username or password", panel_path=PANEL_PATH)
    return render_template("login.html", panel_path=PANEL_PATH)

@app.route(f"{PANEL_PATH}/logout" if PANEL_PATH != '/' else "/logout")
@login_required
def logout():
    logout_user()
    return redirect(f"{PANEL_PATH}/login" if PANEL_PATH != '/' else "/login")


# ==================== MAIN ROUTES ====================

@app.route('/client/login', methods=['GET', 'POST'])
def client_login():
    if os.environ.get("BEENY_ENABLE_CLIENT_PORTAL") != "1":
        return "Client portal disabled", 404
    if request.method == 'POST':
        username = request.form.get('username')
        user = User.query.filter_by(username=username).first()
        if user:
            session['client_user'] = user.username
            return redirect('/client/dashboard')
        return render_template('client_login.html', error="کاربر یافت نشد")
    return render_template('client_login.html')

@app.route('/client/dashboard')
def client_dashboard():
    if os.environ.get("BEENY_ENABLE_CLIENT_PORTAL") != "1":
        return "Client portal disabled", 404
    if 'client_user' not in session:
        return redirect('/client/login')
    
    user = User.query.filter_by(username=session['client_user']).first_or_404()
    
    days_left = "-"
    if user.expire_date and user.expire_date.isdigit():
        days_left = f"{user.expire_date} روز (پس از اولین اتصال)"
    elif user.expire_date and user.expire_date != "-":
        days = (datetime.strptime(user.expire_date, "%Y-%m-%d") - datetime.now()).days
        days_left = f"{days} روز" if days >= 0 else "منقضی شده"

    return render_template('client.html', user=user, days_left=days_left)

@app.route(PANEL_PATH)
@login_required
def home():
    online_users = User.query.filter_by(online=True).count()
    expiring_users = 0
    for user in User.query.all():
        try:
            if user.expire_date and user.expire_date != "-":
                expire = datetime.strptime(user.expire_date, "%Y-%m-%d")
                if (expire - datetime.now()).days <= 7:
                    expiring_users += 1
        except:
            pass
    total_traffic = round(db.session.query(db.func.sum(User.traffic_usage)).scalar() or 0, 1)
    total_users = User.query.count()
    active_users = User.query.filter_by(status="active").count()
    openvpn_users = User.query.filter_by(protocol="openvpn").count()
    wireguard_users = User.query.filter_by(protocol="wireguard").count()
    
    return render_template("dashboard.html",
                         panel_path=PANEL_PATH,  
                         online_users=online_users, 
                         expiring_users=expiring_users, 
                         total_traffic=total_traffic, 
                         total_users=total_users, 
                         active_users=active_users, 
                         openvpn_users=openvpn_users, 
                         wireguard_users=wireguard_users)


@app.route(f"{PANEL_PATH}/users" if PANEL_PATH != '/' else "/users")
@login_required
def users():
    nodes = Node.query.all()
    return render_template("users.html", panel_path=PANEL_PATH, nodes=nodes)


@app.route(f"{PANEL_PATH}/users/add" if PANEL_PATH != '/' else "/users/add", methods=["GET", "POST"])
@login_required
def add_user():
    nodes = Node.query.all()
    
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
    expire_val = expire_days if expire_days else "-"
    try:
        max_devices = int(request.form["max_devices"])
        traffic_limit = int(request.form.get("traffic_limit", "0"))
        if max_devices < 1 or traffic_limit < 0:
            raise ValueError()
    except (ValueError, KeyError):
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Check the device and data limits."), 400

    user = User(
        username=request.form["username"],
        protocol=request.form["protocol"],
        max_devices=max_devices,
        expire_date=expire_val,
        status="active",
        traffic_limit=traffic_limit
    )

    selected_nodes = request.form.getlist("nodes")
    try:
        selected_ids = [int(n) for n in selected_nodes]
    except ValueError:
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Invalid node selection."), 400
    if not set(selected_ids).issubset({node.id for node in nodes}):
        return render_template("user_form.html", panel_path=PANEL_PATH, nodes=nodes, mode="add", user=None,
                               error="Invalid node selection."), 400
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

    from cluster import create_user_on_node
    for node_id in selected_nodes:
        node = Node.query.get(int(node_id))
        if node:
            try:
                create_user_on_node(node, user)
            except Exception as e:
                pass

    return redirect(f"{PANEL_PATH}/users?notice=User%20Created" if PANEL_PATH != '/' else "/users?notice=User%20Created")


@app.route(f"{PANEL_PATH}/users/edit/<int:user_id>" if PANEL_PATH != '/' else "/users/edit/<int:user_id>", methods=["GET", "POST"])
@login_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    nodes = Node.query.all()
    
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
        if max_devices < 1 or new_limit < 0:
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
    if not set(new_node_ids).issubset({node.id for node in nodes}):
        return invalid("Invalid node selection.")

    next_expiry = user.expire_date
    if renewal_days:
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
    else:
        ccd_file = f"/etc/openvpn/ccd/{user.username}"
        if os.path.exists(ccd_file):
            os.remove(ccd_file)
            
    removed_nodes = set(current_node_ids) - set(new_node_ids)
    added_nodes = set(new_node_ids) - set(current_node_ids)
            
    UserNode.query.filter_by(user_id=user.id).delete()
    for node_id in new_node_ids:
        db.session.add(UserNode(user_id=user.id, node_id=int(node_id)))
        
    db.session.commit()
    
    from cluster import create_user_on_node, delete_user_on_node
    # پاک کردن کاربر از نودهایی که تیک آنها برداشته شده (جلوگیری از ماندن کاربر در نودهای اضافی)
    for nid in removed_nodes:
        node = Node.query.get(nid)
        if node:
            try: delete_user_on_node(node, user.username)
            except: pass
            
    # اضافه کردن کاربر به نودهای جدید
    for nid in added_nodes:
        node = Node.query.get(nid)
        if node:
            try: create_user_on_node(node, user)
            except: pass
            
    return redirect(f"{PANEL_PATH}/users?notice=User%20Updated" if PANEL_PATH != '/' else "/users?notice=User%20Updated")

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
        if node:
            try: delete_user_on_node(node, user.username)
            except: pass
            
    UserNode.query.filter_by(user_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()
    return redirect(f"{PANEL_PATH}/users" if PANEL_PATH != '/' else "/users")


@app.route(f"{PANEL_PATH}/users/view/<int:user_id>" if PANEL_PATH != '/' else "/users/view/<int:user_id>")
@login_required
def view_user(user_id):
    user = User.query.get_or_404(user_id)
    try:
        if user.expire_date and user.expire_date.isdigit():
            days_left = f"{user.expire_date} (Starts on connection)"
        elif user.expire_date and user.expire_date != "-":
            days = (datetime.strptime(user.expire_date, "%Y-%m-%d") - datetime.now()).days
            days_left = days if days >= 0 else 0
        else:
            days_left = "-"
    except:
        days_left = "-"
        
    user_nodes = []
    relations = UserNode.query.filter_by(user_id=user.id).all()
    for rel in relations:
        node = Node.query.get(rel.node_id)
        if node:
            user_nodes.append(node)
    
    return render_template("user_profile.html", user=user, days_left=days_left, assigned_nodes=user_nodes, panel_path=PANEL_PATH)


@app.route(f"{PANEL_PATH}/users/download/<username>" if PANEL_PATH != '/' else "/users/download/<username>")
@login_required
def download_config(username):
    user = User.query.filter_by(username=username).first_or_404()
    
    try:
        with open(f"/etc/openvpn/easy-rsa/pki/ca.crt", "r") as f:
            ca_data = f.read()
        with open(f"/etc/openvpn/easy-rsa/ta.key", "r") as f:
            ta_data = f.read()
        with open(f"/etc/openvpn/easy-rsa/pki/issued/{username}.crt", "r") as f:
            cert_raw = f.read()
            cert_match = re.search(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", cert_raw, re.DOTALL)
            cert_data = cert_match.group(0) if cert_match else cert_raw
        with open(f"/etc/openvpn/easy-rsa/pki/private/{username}.key", "r") as f:
            key_data = f.read()
    except Exception as e:
        return f"Error reading local VPN certificates: {str(e)}", 500

    user_nodes_relations = UserNode.query.filter_by(user_id=user.id).all()
    requested_node_id = request.args.get('node_id', type=int)
    
    remotes_block = ""
    
    def clean_address(node_obj):
        target = node_obj.host if node_obj.host else node_obj.ip
        if not target: return "127.0.0.1"
        return target.split(":")[0].strip()
    
    if requested_node_id:
        # فیکس باگ: بررسی اینکه آیا این نود واقعاً به کاربر اختصاص داده شده یا خیر
        if not any(rel.node_id == requested_node_id for rel in user_nodes_relations):
            return "Unauthorized or Node not assigned to this user.", 403
            
        node = Node.query.get(requested_node_id)
        if node:
            clean_ip = clean_address(node)
            remotes_block = f"remote {clean_ip} {os.environ.get('BEENY_VPN_PORT', '110')}"
    else:
        remotes_block = "remote-random\n"
        for rel in user_nodes_relations:
            node = Node.query.get(rel.node_id)
            if node:
                clean_ip = clean_address(node)
                remotes_block += f"remote {clean_ip} {os.environ.get('BEENY_VPN_PORT', '110')}\n"
                
        if not user_nodes_relations:
            public_host = os.environ.get("BEENY_PUBLIC_HOST", "").strip()
            if not public_host:
                return "Public VPN host is not configured", 503
            remotes_block = f"remote {public_host} {os.environ.get('BEENY_VPN_PORT', '110')}"

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
    user.status = "active"
    
    db.session.commit()
    
    ccd_file = f"/etc/openvpn/ccd/{user.username}"
    if os.path.exists(ccd_file):
        os.remove(ccd_file)
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
            'days_left_text': days_left_text, 'traffic_usage': round(u.traffic_usage, 1), 'traffic_limit': u.traffic_limit,
            'traffic_percent': round((u.traffic_usage / u.traffic_limit * 100), 1) if u.traffic_limit > 0 else 0,
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
    node.name = request.form.get("name")
    node.ip = request.form.get("ip")
    node.host = request.form.get("host")
    node.country = request.form.get("country")
    node.protocol = request.form.get("protocol")
    node.api_key = request.form.get("api_key")
    
    db.session.commit()
    return redirect(f"{PANEL_PATH}/settings/nodes")


@app.route(f"{PANEL_PATH}/settings/nodes/delete/<int:node_id>")
@login_required
def delete_node(node_id):
    node = Node.query.get_or_404(node_id)
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
    Thread(target=background_updater, daemon=True).start()
    app.run(host=os.environ.get("BEENY_BIND", "127.0.0.1"), port=int(os.environ.get("BEENY_PORT", "8080")), debug=False)
