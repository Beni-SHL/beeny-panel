import requests
import os

def get_file_content(paths):
    for path in paths:
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read()
    return ""

def bootstrap_node(node):
    try:
        target = node.host if node.host else node.ip
        if not target:
            return False, "Error: Node address is empty"
            
        host_address = target.strip()
        if not host_address.startswith("http://") and not host_address.startswith("https://"):
            host_url = f"http://{host_address}"
        else:
            host_url = host_address
            
        if ":" not in host_url.replace("http://", "").replace("https://", ""):
            host_url = f"{host_url}:5001"

        ca_crt = get_file_content(["/etc/openvpn/easy-rsa/pki/ca.crt", "/etc/openvpn/server/ca.crt", "/etc/openvpn/ca.crt"])
        ta_key = get_file_content(["/etc/openvpn/easy-rsa/ta.key", "/etc/openvpn/server/ta.key", "/etc/openvpn/ta.key"])
        server_crt = get_file_content(["/etc/openvpn/easy-rsa/pki/issued/server.crt", "/etc/openvpn/server/server.crt"])
        server_key = get_file_content(["/etc/openvpn/easy-rsa/pki/private/server.key", "/etc/openvpn/server/server.key"])
        dh_pem = get_file_content(["/etc/openvpn/easy-rsa/pki/dh.pem", "/etc/openvpn/dh.pem"])
        crl_pem = get_file_content(["/etc/openvpn/crl.pem", "/etc/openvpn/easy-rsa/pki/crl.pem"])
        server_conf = get_file_content(["/etc/openvpn/server/server.conf", "/etc/openvpn/server.conf"])

        if server_conf:
            server_conf = server_conf.replace("/etc/openvpn/easy-rsa/pki/ca.crt", "/etc/openvpn/ca.crt")
            server_conf = server_conf.replace("/etc/openvpn/easy-rsa/pki/issued/server.crt", "/etc/openvpn/server/server.crt")
            server_conf = server_conf.replace("/etc/openvpn/easy-rsa/pki/private/server.key", "/etc/openvpn/server/server.key")
            server_conf = server_conf.replace("/etc/openvpn/easy-rsa/pki/dh.pem", "/etc/openvpn/dh.pem")
            server_conf = server_conf.replace("/etc/openvpn/easy-rsa/ta.key", "/etc/openvpn/ta.key")

        payload = {
            "ca_crt": ca_crt,
            "ta_key": ta_key,
            "server_crt": server_crt,
            "server_key": server_key,
            "dh_pem": dh_pem,
            "crl_pem": crl_pem, 
            "server_conf": server_conf
        }
        
        headers = {"Authorization": f"Bearer {node.api_key}"}
        response = requests.post(f"{host_url}/api/node/bootstrap-openvpn", json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return True, "Bootstrap successful"
        else:
            return False, f"Failed: {response.text}"
            
    except Exception as e:
        return False, f"Exception: {str(e)}"
        
def create_user_on_node(node, user):
    try:
        target = node.host if node.host else node.ip
        if not target:
            return "Error: Node address is empty"
            
        host_address = target.strip()
        if not host_address.startswith("http://") and not host_address.startswith("https://"):
            host_url = f"http://{host_address}"
        else:
            host_url = host_address
            
        if ":" not in host_url.replace("http://", "").replace("https://", ""):
            host_url = f"{host_url}:5001"

        username = user.username
        try:
            with open(f"/etc/openvpn/easy-rsa/pki/issued/{username}.crt", "r") as f:
                cert_data = f.read()
            with open(f"/etc/openvpn/easy-rsa/pki/private/{username}.key", "r") as f:
                key_data = f.read()
        except Exception as e:
            return f"Error reading local certs for {username}: {str(e)}"

        payload = {
            "username": username,
            "cert": cert_data.strip(),
            "key": key_data.strip()
        }
        
        headers = {"Authorization": f"Bearer {node.api_key}"}
        
        response = requests.post(
            f"{host_url}/api/node/install-cert",
            json=payload,
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            return f"Success: {response.json().get('message', 'User synced')}"
        else:
            return f"Failed with status {response.status_code}: {response.text}"
            
    except Exception as e:
        return f"Exception during cluster sync: {str(e)}"

def delete_user_on_node(node, username):
    """Deletes or disconnects the user from a specific node."""
    try:
        target = node.host if node.host else node.ip
        if not target:
            return False
            
        host_address = target.strip()
        if not host_address.startswith("http://") and not host_address.startswith("https://"):
            host_url = f"http://{host_address}"
        else:
            host_url = host_address
            
        if ":" not in host_url.replace("http://", "").replace("https://", ""):
            host_url = f"{host_url}:5001"

        headers = {"Authorization": f"Bearer {node.api_key}"}
        payload = {"username": username}
        
        response = requests.post(f"{host_url}/api/node/delete-user", json=payload, headers=headers, timeout=5)
        
        # Fallback to kill-user if delete is not supported by older node agents
        if response.status_code == 404:
            response = requests.post(f"{host_url}/api/node/kill-user", json=payload, headers=headers, timeout=3)
        return response.status_code == 200
    except Exception as e:
        return False


def set_user_state_on_node(node, username, active):
    """Ask a compatible Beeny Agent to apply renewal/disable immediately."""
    target = (node.host or node.ip or '').strip()
    if not target:
        return False, 'Node address is missing'
    address = target if target.startswith(('http://', 'https://')) else f'http://{target}'
    if ':' not in address.split('//', 1)[-1]:
        address += ':5001'
    try:
        response = requests.post(f'{address}/api/node/set-user-state',
                                 json={'username': username, 'active': active},
                                 headers={'Authorization': f'Bearer {node.api_key}'}, timeout=5)
        response.raise_for_status()
        return True, ''
    except requests.RequestException as exc:
        return False, str(exc)
