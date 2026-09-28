#!/usr/bin/env python3
"""Optional one-shot status collector; the panel service already runs this periodically."""
import sys
sys.path.insert(0, '/opt/beeny-panel')
from app import app, db, ensure_primary_node, update_openvpn_status

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_primary_node()
        update_openvpn_status()
