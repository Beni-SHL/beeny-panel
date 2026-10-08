"""Additive upgrades only: never rebuild or delete an existing account table."""
from sqlalchemy import inspect, text

ADDITIONS = {
    'user': {'protocol': "VARCHAR(20) DEFAULT 'openvpn'", 'max_devices': 'INTEGER DEFAULT 1',
             'current_devices': 'INTEGER DEFAULT 0', 'expire_date': 'VARCHAR(20)',
             'status': "VARCHAR(20) DEFAULT 'active'", 'online': 'BOOLEAN DEFAULT 0',
             'online_status': "VARCHAR(20) DEFAULT 'offline'", 'traffic_limit': 'INTEGER DEFAULT 10',
             'traffic_usage': 'FLOAT DEFAULT 0', 'traffic_used': 'BIGINT DEFAULT 0',
             'last_session_bytes': 'BIGINT DEFAULT 0', 'customer_paused': 'BOOLEAN NOT NULL DEFAULT 0',
             'pause_sync_pending': 'BOOLEAN NOT NULL DEFAULT 0', 'notification_revision': 'INTEGER NOT NULL DEFAULT 0'},
    'nodes': {'host': 'VARCHAR(255)', 'country': "VARCHAR(50) DEFAULT ''", 'protocol': "VARCHAR(20) DEFAULT 'OpenVPN'",
              'api_key': "VARCHAR(255) DEFAULT ''", 'status': "VARCHAR(20) DEFAULT 'offline'"},
    'traffic_sample': {'last_received': 'BIGINT NOT NULL DEFAULT -1', 'last_sent': 'BIGINT NOT NULL DEFAULT -1'},
    'traffic_daily': {'bytes_received': 'BIGINT NOT NULL DEFAULT 0', 'bytes_sent': 'BIGINT NOT NULL DEFAULT 0'},
    'customer_profiles': {'login_username': 'VARCHAR(100)', 'password_hash': 'VARCHAR(255)', 'auth_version': 'VARCHAR(64)', 'avatar_choice': 'INTEGER'},
    'renewal_requests': {'telegram_sent_ids': "TEXT DEFAULT '[]'"},
}


def upgrade(db):
    existing = inspect(db.engine).get_table_names()
    with db.engine.begin() as connection:
        for table, additions in ADDITIONS.items():
            if table not in existing:
                continue
            columns = {column['name'] for column in inspect(connection).get_columns(table)}
            for name, declaration in additions.items():
                if name not in columns:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {declaration}'))
    db.create_all()
