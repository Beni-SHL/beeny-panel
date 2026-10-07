from flask import Flask, request, jsonify
from config import AGENT_API_KEY, AGENT_PORT
import subprocess
import os
import re
import socket

app = Flask(__name__)

def verify_api_key():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "): return False
    return auth.replace("Bearer ", "") == AGENT_API_KEY

@app.route("/api/node/stats")
def stats():
    if not verify_api_key(): return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"status": "online"})

@app.route("/api/node/bootstrap-openvpn", methods=["POST"])
def bootstrap_openvpn():
    if not verify_api_key(): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    try:
        os.makedirs("/etc/openvpn/server", exist_ok=True)
        os.makedirs("/etc/openvpn/ccd", exist_ok=True)

        if data.get("ca_crt"):
            with open("/etc/openvpn/ca.crt", "w") as f: f.write(data.get("ca_crt"))
        if data.get("ta_key"):
            with open("/etc/openvpn/ta.key", "w") as f: f.write(data.get("ta_key"))
        if data.get("server_crt"):
            with open("/etc/openvpn/server/server.crt", "w") as f: f.write(data.get("server_crt"))
        if data.get("server_key"):
            with open("/etc/openvpn/server/server.key", "w") as f: f.write(data.get("server_key"))
        if data.get("dh_pem"):
            with open("/etc/openvpn/dh.pem", "w") as f: f.write(data.get("dh_pem"))
        if data.get("crl_pem"):
            with open("/etc/openvpn/crl.pem", "w") as f: f.write(data.get("crl_pem"))
        if data.get("server_conf"):
            with open("/etc/openvpn/server/server.conf", "w") as f: f.write(data.get("server_conf"))

        # ðŸ”¥ Ø§ØµÙ„Ø§Ø­: Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø§Ø² Ù†Ø§Ù… Ø¯Ø±Ø³Øª Ø³Ø±ÙˆÛŒØ³
        subprocess.run(["systemctl", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "enable", "openvpn-server@server"], check=False)
        subprocess.run(["systemctl", "restart", "openvpn-server@server"], check=False)
        return jsonify({"success": True, "message": "Bootstrap completed"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/node/install-cert", methods=["POST"])
def install_cert():
    if not verify_api_key(): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    username = data.get("username")
    if not username or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", username): return jsonify({"error": "invalid"}), 400
    try:
        os.makedirs("/etc/openvpn/users", exist_ok=True)
        with open(f"/etc/openvpn/users/{username}.crt", "w") as f: f.write(data.get("cert"))
        with open(f"/etc/openvpn/users/{username}.key", "w") as f: f.write(data.get("key"))
        ccd = f"/etc/openvpn/ccd/{username}"
        if os.path.exists(ccd):
            os.remove(ccd)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/node/status-log", methods=["GET"])
def get_status_log():
    if not verify_api_key(): return jsonify({"error": "Unauthorized"}), 401
    try:
        # فرستادن لاگ مصرفی نود برای سرور مرکزی
        if os.path.exists("/var/log/openvpn-status.log"):
            with open("/var/log/openvpn-status.log", "r") as f:
                return jsonify({"success": True, "log": f.read()})
        return jsonify({"success": True, "log": ""})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/node/kill-user", methods=["POST"])
def kill_user():
    if not verify_api_key(): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    username = data.get("username")
    if not username or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", username):
        return jsonify({"error": "invalid"}), 400
    try:
        # ۱. مسدودسازی دائمی کاربر روی این نود
        os.makedirs("/etc/openvpn/ccd", exist_ok=True)
        with open(f"/etc/openvpn/ccd/{username}", "w") as f:
            f.write("disable\n")

        # ۲. شوت کردنِ آنی کاربر از تونل (از طریق پورت مدیریت اوپن‌وی‌پی‌ان)
        try:
            with socket.create_connection(("127.0.0.1", 7505), timeout=1) as conn:
                conn.sendall(f"kill {username}\n".encode("ascii"))
        except OSError: pass
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@app.route("/api/node/set-user-state", methods=["POST"])
def set_user_state():
    if not verify_api_key(): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    username = data.get("username", "")
    active = data.get("active")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", username) or not isinstance(active, bool):
        return jsonify({"error": "Invalid account state"}), 400
    try:
        os.makedirs("/etc/openvpn/ccd", exist_ok=True)
        path = f"/etc/openvpn/ccd/{username}"
        if active:
            if os.path.exists(path): os.remove(path)
        else:
            with open(path, "w") as handle: handle.write("disable\n")
            try:
                with socket.create_connection(("127.0.0.1", 7505), timeout=1) as conn:
                    conn.sendall(f"kill {username}\n".encode("ascii"))
            except OSError: pass
        return jsonify({"success": True})
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/node/delete-user", methods=["POST"])
def delete_user():
    if not verify_api_key(): return jsonify({"error": "Unauthorized"}), 401
    username = (request.get_json(silent=True) or {}).get("username", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", username):
        return jsonify({"error": "Invalid username"}), 400
    try:
        os.makedirs('/etc/openvpn/ccd', exist_ok=True)
        with open(f'/etc/openvpn/ccd/{username}', 'w') as handle:
            handle.write('disable\n')
        for suffix in ('.crt', '.key'):
            path = f'/etc/openvpn/users/{username}{suffix}'
            if os.path.exists(path): os.remove(path)
        try:
            with socket.create_connection(('127.0.0.1', 7505), timeout=1) as conn:
                conn.sendall(f'kill {username}\n'.encode('ascii'))
        except OSError: pass
        return jsonify({'success': True})
    except OSError as exc:
        return jsonify({'error': str(exc)}), 500

# Account-scoped session controls. This module must ship with the updated agent.
@app.post('/api/node/sessions')
def account_sessions():
    if not verify_api_key(): return jsonify({'error': 'Unauthorized'}), 401
    from vpn_sessions import local_sessions
    data = request.get_json(silent=True) or {}
    username = data.get('username', '')
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', username):
        return jsonify({'error': 'Invalid username'}), 400
    try:
        return jsonify(sessions=local_sessions(username))
    except (OSError, RuntimeError):
        return jsonify(error='Management interface unavailable'), 503

@app.post('/api/node/disconnect-session')
def account_disconnect():
    if not verify_api_key(): return jsonify({'error': 'Unauthorized'}), 401
    from vpn_sessions import disconnect_session
    data = request.get_json(silent=True) or {}
    username = data.get('username', '')
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', username):
        return jsonify({'error': 'Invalid username'}), 400
    try:
        disconnect_session(username, data.get('id', ''), data.get('fingerprint', ''))
        return jsonify(success=True)
    except ValueError:
        return jsonify(error='Session changed; refresh the list'), 409
    except (OSError, RuntimeError):
        return jsonify(error='Management interface unavailable'), 503

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=AGENT_PORT)

