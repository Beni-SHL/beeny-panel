## Release 2.2.0 — customer experience

- 20 original fluffy monster avatars; a stable random default, customer choice and private photo uploads (20 MiB).
- Animated blue Telegram card, larger profile, a notification bell for customers and admins, low-data and low-time warnings, and smooth feedback dialogs.
- Approve & renew applies the saved plan once: add days/data, set device allowance, preserve usage and personal pause, and notify the paired customer through the portal and Telegram.
- Delete renewal requests and their receipt files. Notification delivery supports one primary and up to 10 additional admin chat IDs and retries only failed recipients.
- Multiple payment cards in six colors with a swipeable selector; optional plan discount badges and original prices.
- Customer pause enforces local/remote VPN access without overriding administrator restrictions. Failed node confirmations remain visible and are retried.
- Searchable continuous account list, batches up to 200, alphabetical sorting, login password visibility, and one-copy customer access messages.

### Upgrade an existing 2.1.x panel manually

Upload the full release ZIP to `/root` using MobaXterm, then run:

```bash
unzip -q /root/beeny-panel-manual-update-2.2.0.zip -d /root/beeny-update-2.2.0
cd /root/beeny-update-2.2.0
sudo bash scripts/update_panel.sh --check
sudo bash scripts/apply_experience_update.sh
```

The updater backs up code, database, environment and service files before switching. Accounts, node IDs/assignments, VPN certificates, admin/customer credentials, settings, uploads and traffic history are preserved. Failed health checks restore the prior application and Python environment. The existing panel URL is retained. Do not run the new-server installer on an existing server.

### GitHub release and new installation

Extract the GitHub-ready ZIP into your repository checkout, then run `git add -A`, `git commit -m "Release Beeny Panel 2.2.0"` and `git push origin main` on separate lines. After publishing, existing 2.1.x panels can use `sudo bash /opt/beeny-panel/scripts/update_panel.sh --github`.

```bash
git clone https://github.com/Beni-SHL/beeny-panel.git
cd beeny-panel
bash install.sh --check
sudo bash install.sh
```

### Configure after updating

In **Customer portal & payments**, save extra bank cards, colors, plan badges/original prices and numeric Telegram admin IDs. Every admin must start the bot. Customers connect from their private page. Notifications about renewals are sent to the currently linked Telegram account; invalidated bindings never receive them.

To share account access in one message, save/generate a customer password and generate its private link in the **same browser tab within 10 minutes**. Copy the ready Persian message. Passwords are hashed on the server; the short-lived draft stays in browser session storage and can be cleared. Existing passwords cannot be retrieved.

Personal pause does not freeze expiry time. An admin-disabled, expired or quota-blocked account cannot be reactivated by the customer. Remote enforcement needs the compatible agent endpoint `/api/node/set-user-state`; lack of confirmation is shown and retried. Renewal requests are approved only after independently verifying the bank transfer. Approvals add purchased GB to the limit, retain already consumed GB, and extend validity from the current expiry (or today when expired).

## Release 2.1.2

- Generate, show and copy secure 20-character customer portal passwords when creating accounts or configuring an existing customer login.
- Photo and receipt uploads now accept up to 20 MiB (JPG, PNG, WebP; at most 40 million pixels). Photos are resized and metadata is removed before private storage.
- Installer configures Nginx for 24 MiB request bodies. Updates adjust the Beeny site with a backup and restore it if Nginx validation or reload fails.
- Telegram worker uses IPv4 by default. Set BEENY_WORKER_FORCE_IPV4=0 in panel.env if your network supports IPv6 and you want dual-stack HTTP connections.
- Existing upgraded 2.1.x servers can apply the smaller package with `bash scripts/apply_account_photo_patch.sh`. Existing users, settings, passwords and VPN certificates are preserved.

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

## Pre-env legacy installations (v2.1.1)

An installation running `app.py` directly without `panel.env` needs the legacy adapter. Publish v2.1.1 first, then run:

```bash
wget -qO /tmp/beeny-update.sh https://raw.githubusercontent.com/Beni-SHL/beeny-panel/main/scripts/update_panel.sh && sudo bash /tmp/beeny-update.sh --github --legacy
```

This mode checks the original `nodes` table, admin password hash format, fixed panel port, CA layout, TCP VPN, tls-auth key and localhost management interface before making changes. It asks you to select the **existing local node ID**, enter that VPS’s public VPN hostname/IP, and indicate whether your current panel URL uses HTTPS. Select the local node, never a remote England node. It preserves the exact panel path (including `@`), ports, user IDs, remote node API keys, and node assignments. It links the existing tls-auth key to the canonical path; the key and server config are never rewritten and OpenVPN is not restarted. Status-version 1 logs are supported without changing VPN config.

The adapter backs up the original SQLite database, service unit, config and selected node state privately, stops only the panel, prepares its environment, promotes the existing local node, and calls the normal updater. Both steps share an update lock. On failure, preparation restores the old local node key/service, removes the newly created environment/link, and restarts the old panel if it was previously running; the normal updater restores code and dependencies. Additive database tables remain. Fresh traffic baselines prevent currently connected users’ old bytes from being charged again. New per-server traffic history begins after the first successful snapshot; old unrecorded history cannot be reconstructed.

Legacy admin usernames/password hashes are retained, but browser sessions expire because a new session secret is generated. Unknown installation layouts, unsupported password hashes, or conflicting TLS keys are rejected without attempting a fresh install. This adapter has automated migration/rollback tests; your VPS still needs an actual connectivity check after updating.

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
