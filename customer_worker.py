"""Single worker: durable renewal notification retries and Telegram long polling."""
import time
import os
import socket
import urllib3.util.connection as urllib3_connection

# Some VPS networks advertise IPv6 but cannot complete Telegram TLS over it.
# Restrict this worker's HTTP connections; the VPN and host network are unchanged.
if os.environ.get('BEENY_WORKER_FORCE_IPV4', '1') == '1':
    urllib3_connection.allowed_gai_family = lambda: socket.AF_INET

from app import app, db, customer_features, experience

if __name__ == '__main__':
    with app.app_context():
        from migrations import upgrade
        upgrade(db)
    while True:
        with app.app_context():
            try:
                experience.worker_cycle()
                customer_features.deliver_notifications()
                customer_features.poll_bot()
            except Exception:
                db.session.rollback()
                app.logger.warning('Customer worker cycle failed; retrying without exposing credentials.')
        time.sleep(3)
