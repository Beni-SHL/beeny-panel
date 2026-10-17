"""Additive upgrades only: never rebuild or delete an existing account table."""
from sqlalchemy import inspect, text

ADDITIONS = {
    'sales_invoices':{'payment_state':"VARCHAR(20) NOT NULL DEFAULT 'paid'"},
    'commission_earnings': {'offset_used':'BIGINT NOT NULL DEFAULT 0'},
    'balepay_gateway_config': {'encrypted_payment_settings': "TEXT NOT NULL DEFAULT ''"},
    'portal_announcements': {'icon': "VARCHAR(20) NOT NULL DEFAULT 'info'", 'color': "VARCHAR(20) NOT NULL DEFAULT 'blue'"},
    'admin_login_attempts':{'updated_at':'DATETIME'},
    'admin': {'language':"VARCHAR(2) NOT NULL DEFAULT 'en'",'node_scope':'BOOLEAN NOT NULL DEFAULT 0','role': "VARCHAR(20) NOT NULL DEFAULT 'owner'",'totp_secret':'TEXT','totp_counter':'BIGINT DEFAULT -1','recovery_codes':"TEXT DEFAULT '[]'"},
    'user': {'disable_reason':"VARCHAR(20) NOT NULL DEFAULT 'legacy'",'quota_mode':"VARCHAR(20) NOT NULL DEFAULT 'metered'",'throttle_down_kbps':'INTEGER NOT NULL DEFAULT 2000','throttle_up_kbps':'INTEGER NOT NULL DEFAULT 2000','speed_state':"TEXT NOT NULL DEFAULT ''",'speed_sync_pending':'BOOLEAN NOT NULL DEFAULT 0','reseller_id':'INTEGER','owner_id':'INTEGER','protocol': "VARCHAR(20) DEFAULT 'openvpn'", 'max_devices': 'INTEGER DEFAULT 1',
             'current_devices': 'INTEGER DEFAULT 0', 'expire_date': 'VARCHAR(20)',
             'status': "VARCHAR(20) DEFAULT 'active'", 'online': 'BOOLEAN DEFAULT 0',
             'online_status': "VARCHAR(20) DEFAULT 'offline'", 'traffic_limit': 'INTEGER DEFAULT 10',
             'traffic_usage': 'FLOAT DEFAULT 0', 'traffic_used': 'BIGINT DEFAULT 0',
             'removal_pending': 'BOOLEAN NOT NULL DEFAULT 0', 'last_session_bytes': 'BIGINT DEFAULT 0', 'customer_paused': 'BOOLEAN NOT NULL DEFAULT 0',
             'pause_sync_pending': 'BOOLEAN NOT NULL DEFAULT 0', 'notification_revision': 'INTEGER NOT NULL DEFAULT 0'},
    'nodes': {'host': 'VARCHAR(255)', 'country': "VARCHAR(50) DEFAULT ''", 'protocol': "VARCHAR(20) DEFAULT 'OpenVPN'",
              'api_key': "VARCHAR(255) DEFAULT ''", 'status': "VARCHAR(20) DEFAULT 'offline'"},
    'traffic_sample': {'last_received': 'BIGINT NOT NULL DEFAULT -1', 'last_sent': 'BIGINT NOT NULL DEFAULT -1'},
    'traffic_daily': {'bytes_received': 'BIGINT NOT NULL DEFAULT 0', 'bytes_sent': 'BIGINT NOT NULL DEFAULT 0'},
    'customer_profiles': {'login_username': 'VARCHAR(100)', 'password_hash': 'VARCHAR(255)', 'auth_version': 'VARCHAR(64)', 'avatar_choice': 'INTEGER'},
    'account_notifications': {'cleared_at': 'DATETIME'},
    'admin_notification_reads': {'cleared': 'BOOLEAN NOT NULL DEFAULT 0'},
    'renewal_requests': {'billing_reference':'VARCHAR(64)','telegram_sent_ids': "TEXT DEFAULT '[]'"},
}


def upgrade(db):
    existing = inspect(db.engine).get_table_names()
    # Older collectors already charged the current live-session counters to
    # accounts. The first snapshot of the new ledger must establish positions,
    # rather than charge those same bytes again. Never reset this on restart.
    needs_traffic_baseline = 'traffic_sample' not in existing
    with db.engine.begin() as connection:
        for table, additions in ADDITIONS.items():
            if table not in existing:
                continue
            columns = {column['name'] for column in inspect(connection).get_columns(table)}
            for name, declaration in additions.items():
                if name not in columns:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {declaration}'))
    db.create_all()
    if needs_traffic_baseline and 'user' in existing and 'nodes' in existing:
        with db.engine.begin() as connection:
            connection.execute(text('''INSERT INTO traffic_baseline (node_id, pending)
                SELECT id, 1 FROM nodes
                WHERE NOT EXISTS (SELECT 1 FROM traffic_baseline WHERE node_id = nodes.id)
                AND EXISTS (SELECT 1 FROM "user")'''))
