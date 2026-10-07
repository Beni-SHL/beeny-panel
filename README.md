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

The primary server appears as a selectable node, and its name and two-letter country code can be edited. The panel uses the flag emoji for that code. For each customer, an admin can create a random private link from the account profile; regenerating revokes the old link. The Persian, RTL customer page uses a bundled Vazirmatn font and offers account details, daily usage, individual and multi-location OpenVPN profiles, and platform-specific setup links. The customer link does not authenticate to admin routes. Each customer link now requires an independent customer username and password set by an administrator in the account profile. The password is hashed; changing it or rotating the link revokes active customer sessions. Customer authentication does not grant administrator access. Older customer links stay locked until credentials are set.

## Traffic accounting

The dashboard and Traffic page read a durable SQLite ledger of OpenVPN session bytes. It records daily per-node totals independently of user rows, so deleting a user or resetting a quota does not subtract historical traffic. User daily totals are retained across quota resets for the personal page. Tracking begins when this release first runs: previous, unrecorded usage cannot be reconstructed. Values are OpenVPN client bytes (received + sent), not total host interface traffic; polling can miss a connection that begins and ends entirely between samples. Day buckets use UTC.

Remote nodes need a compatible Beeny Agent at the configured API endpoint. `node_agent/agent.py` contains the `/api/node/set-user-state` endpoint needed to unblock renewed accounts, plus the status-log endpoint needed for remote traffic. Install that updated agent on each remote node using its own service configuration and API key; the primary server requires no agent. A remote update failure is shown on the user's admin profile and in the panel service log.

## Customer workspace and payments (v2.1.0)

The Persian Vazirmatn workspace includes live account counters, a 7/14/30-day usage chart, a quota ring, profile-photo upload, node-specific downloads, local country flags, installation badges and setup instructions. Both dark and light themes work on mobile. Data comes from the ledger, not sample charts; daily buckets use UTC. All new charts, font, icons and flags are served locally.

Open **Customer & payments** to set bank name, card number, cardholder, admin contact details and the four renewal plans. Default prices are 250,000 / 340,000 / 450,000 / 650,000 Toman. The fair-use allowances default to 100 / 100 / 200 / 300 GB and are editable. “Unlimited” on the first plan includes the explicitly displayed 100 GB fair-use limit.

Customers select a service and upload a JPG/PNG/WebP receipt (up to 5 MB). Receipt images are re-encoded and metadata is removed; files have random names outside the public static directory. The server saves the price and terms at submission time. One pending request per account prevents duplicate submissions. Only admins can read receipts. **Renewal inbox** shows status and independent email/Telegram delivery results, with retry controls. The admin verifies payment, renews the actual VPN account through **Edit account**, and marks the request completed; uploading a receipt never automatically activates service.

For email, configure verified SSL/STARTTLS SMTP credentials and sender address. For Telegram, create a bot with BotFather, enter its username/token, start it in the admin’s private chat, run `/id`, and save that numeric chat ID. Start the `beeny-customer-worker` service (automatic with install/update). The worker delivers receipts to configured channels independently and retries failures. Secrets are stored in a private 0600 file under `instance/` and are never returned to the settings page. Delivery still requires real credentials and network access; tests mock external services.

From the authenticated customer page, **Connect Telegram** creates a one-use link valid for 10 minutes. Username alone never links an account. The bot supports account usage/remaining days, config downloads, private profile links, service selection, receipt photos, request history, support and unlinking. Customer profile links from the bot expire after 30 days and still require the customer password. Rotating the private link or changing the customer password revokes the bot binding. Customers and admins must start the bot; it cannot initiate their first chat.

## Active connections

Customer and administrator account pages link to **Active connections**. It queries live OpenVPN management status by account on each assigned node, displays public/virtual address, connection time and session bytes, and disconnects a single client ID after verifying its current account and session fingerprint. Failed or unsupported nodes are shown as unavailable rather than offline. The admin can also disable the entire account on assigned nodes, with a warning if a node does not confirm.

OpenVPN does not expose phone model or a reliable physical-device identifier. Disconnecting a session does not permanently revoke its shared configuration; it may reconnect. Permanent revocation of one device requires an individual certificate for that device. Account-wide disable blocks the shared account; re-enable it through Edit account after resolving quota/expiry limits.

The primary server needs no agent. Remote nodes must update their agent: use `node_agent/agent.py` **and** `node_agent/vpn_sessions.py` in the agent’s existing application directory, preserving its `config.py`, API key and service configuration. The new session endpoints are `/api/node/sessions` and `/api/node/disconnect-session`; `/api/node/set-user-state` applies account enable/disable. The panel updater does not silently replace remote agents or restart OpenVPN.

## Update an existing installed panel

Publish this release to the public main branch first. Run on the panel VPS:

```bash
wget -qO /tmp/beeny-update.sh https://raw.githubusercontent.com/Beni-SHL/beeny-panel/main/scripts/update_panel.sh && sudo bash /tmp/beeny-update.sh --github
```

Or from an existing checkout:

```bash
cd ~/beeny-panel
git pull --ff-only
bash scripts/update_panel.sh --check
sudo bash scripts/update_panel.sh
sudo bash scripts/update_panel.sh --verify
```

The **Update panel** admin section shows the command, version and recovery information. The updater supports installations at `/opt/beeny-panel` with `config.json`, `instance/beeny.db`, a Python `venv`, the systemd panel service and `/etc/beeny-panel/panel.env`, including older releases installed with this repository’s installer. It stops on incompatible layouts rather than replacing an unknown database. Run the fresh installer only on a fresh server.

Updates create private code/config/unit/SQLite backups under `/opt/beeny-panel/backups/update-*`, prepare dependencies in a separate Python environment, apply additive schema migrations and verify the running login and database before starting the customer worker. Accounts, certificates, domain/IP settings, private links, uploaded images and notification secrets are preserved. Failure restores old application files, Python environment and services. Additive database columns remain; the consistent SQLite snapshot is available for manual recovery. Keep backups until you have verified VPN connectivity and customer workflows. The updater never rebuilds the CA or recreates users.

## Verify

```bash
# From the repository checkout on a server with the panel installed:
source /opt/beeny-panel/venv/bin/activate
python3 -m unittest discover -s tests -v
python3 tests/check_updater_rollback.py
sudo systemctl status openvpn-server@server beeny-panel beeny-vpn-firewall beeny-customer-worker
sudo journalctl -u beeny-panel -n 100 --no-pager
```

Create a disposable account, connect with its `.ovpn` profile, verify dashboard online status and Traffic after the next status poll, extend its expiry, and try its private link from an unauthenticated browser. Test a remote node separately after updating its agent.

The admin UI inherits legacy routes that should be audited for CSRF and destructive GET requests before deployment beyond a trusted test environment.
