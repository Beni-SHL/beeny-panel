"""Bounded cleanup; durable traffic and invoice ledgers are never deleted."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import datetime,timedelta
from app import app,db,security,panel_sessions,customer_features,experience

def cleanup():
    now=datetime.utcnow();old=now-timedelta(days=90)
    security.Attempt.query.filter(security.Attempt.updated_at<old).delete(synchronize_session=False)
    panel_sessions.PanelSession.query.filter(panel_sessions.PanelSession.expires_at<old).delete(synchronize_session=False)
    customer_features.TelegramPair.query.filter(customer_features.TelegramPair.expires_at<now).delete(synchronize_session=False)
    # Never erase unread messages, unsent notifications, invoices or traffic aggregates.
    ids=[row.id for row in experience.Notification.query.filter(experience.Notification.cleared_at<old,experience.Notification.telegram_state.in_(['sent','skipped'])).limit(1000)]
    if ids:
        experience.AdminRead.query.filter(experience.AdminRead.notification_id.in_(ids)).delete(synchronize_session=False)
        experience.Notification.query.filter(experience.Notification.id.in_(ids)).delete(synchronize_session=False)
    security.Audit.query.filter(security.Audit.created_at<now-timedelta(days=365)).delete(synchronize_session=False)
    db.session.commit()
    print('Expired sessions and old cleared notifications cleaned. Traffic and financial ledgers preserved.')
if __name__=='__main__':
    with app.app_context():cleanup()
