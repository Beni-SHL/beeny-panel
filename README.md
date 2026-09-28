# Beeny Panel

OpenVPN management panel for a **fresh Ubuntu 22.04 / 24.04 VPS**. The installer creates a new CA, VPN server, admin account, database, and service. Do not run it on a server containing a VPN or panel that must be preserved.

## Install from GitHub

Upload this repository's source files to `https://github.com/Beni-SHL/beeny-panel` first. Put `install.sh` and `app.py` at the **root**, with the `templates/`, `static/`, `scripts/`, and `node_agent/` folders intact. Do not publish the old VPS database, `panel.env`, CA keys, or user private keys.

```bash
GIT_TERMINAL_PROMPT=0 git -c credential.helper= clone https://github.com/Beni-SHL/beeny-panel.git
cd beeny-panel
bash install.sh --check
bash install.sh --demo
sudo bash install.sh
```

The installer asks for the public VPS IPv4 address and an optional VPN hostname. To keep client profiles stable across an IP change, create a direct DNS A record (for example `vpn.example.com`) pointing to this VPS before installation and enter that hostname at the VPN prompt. OpenVPN profiles then use `remote vpn.example.com PORT`; update the A record when moving the VPN endpoint. Preserve the same CA and client identities on the replacement VPN server if existing profiles must continue working. DNS changes do not bypass DNS blocks or restore access when the hostname itself is blocked. HTTP-only DNS proxies cannot carry OpenVPN TCP.

The installer also asks for VPN TCP port, panel port, panel path, admin credentials and an optional, separate panel HTTPS domain. If the panel domain resolves and Let's Encrypt can issue a certificate, Nginx serves HTTPS and Certbot renews it. If the domain is unavailable, it falls back to `http://VPS_IP:PANEL_PORT/PANEL_PATH/login`. Allow the selected port in the VPS provider firewall as well as UFW. The IP fallback is **unencrypted HTTP**: do not share secret customer links or use sensitive admin credentials there until HTTPS is configured. For certificate issuance the panel domain must point to the VPS and inbound port 80 must work.

The primary server appears as a selectable node, and its name and two-letter country code can be edited. The panel uses the flag emoji for that code. For each customer, an admin can create a random private link from the account profile; regenerating revokes the old link. The Persian, RTL customer page uses a bundled Vazirmatn font and offers account details, daily usage, individual and multi-location OpenVPN profiles, and platform-specific setup links. The customer link does not authenticate to admin routes. Protect the link as a credential because it also permits profile downloads.

## Traffic accounting

The dashboard and Traffic page read a durable SQLite ledger of OpenVPN session bytes. It records daily per-node totals independently of user rows, so deleting a user or resetting a quota does not subtract historical traffic. User daily totals are retained across quota resets for the personal page. Tracking begins when this release first runs: previous, unrecorded usage cannot be reconstructed. Values are OpenVPN client bytes (received + sent), not total host interface traffic; polling can miss a connection that begins and ends entirely between samples. Day buckets use UTC.

Remote nodes need a compatible Beeny Agent at the configured API endpoint. `node_agent/agent.py` contains the `/api/node/set-user-state` endpoint needed to unblock renewed accounts, plus the status-log endpoint needed for remote traffic. Install that updated agent on each remote node using its own service configuration and API key; the primary server requires no agent. A remote update failure is shown on the user's admin profile and in the panel service log.

## Update an existing installed panel

```bash
cd ~/beeny-panel
# After publishing this source to GitHub:
git pull --ff-only
bash scripts/update_panel.sh --check
sudo bash scripts/update_panel.sh
sudo bash scripts/update_panel.sh --verify
```

The updater backs up the application files and preserves `instance/`, `config.json`, `panel.env`, and VPN certificates. It checks the running login and the primary node. New traffic figures start at the moment this version begins collecting them.

## Verify

```bash
python3 -m unittest discover -s tests -v
sudo systemctl status openvpn-server@server beeny-panel beeny-vpn-firewall
sudo journalctl -u beeny-panel -n 100 --no-pager
```

Create a disposable account, connect with its `.ovpn` profile, verify dashboard online status and Traffic after the next status poll, extend its expiry, and try its private link from an unauthenticated browser. Test a remote node separately after updating its agent.

The admin UI inherits legacy routes that should be audited for CSRF and destructive GET requests before deployment beyond a trusted test environment.
