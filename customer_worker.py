"""Single worker: durable renewal notification retries and Telegram long polling."""
import time
from app import app, db, customer_features

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    while True:
        with app.app_context():
            try:
                customer_features.deliver_notifications()
                customer_features.poll_bot()
            except Exception:
                db.session.rollback()
                app.logger.warning('Customer worker cycle failed; retrying without exposing credentials.')
        time.sleep(3)
