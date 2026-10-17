"""Fixed administrator commands; password travels through stdin only."""
import sys,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
def change(action,username,password):
    from app import app,db,Admin,panel_sessions,security
    from werkzeug.security import generate_password_hash
    if action not in {'add','password'} or not re.fullmatch(r'[A-Za-z0-9_.-]{1,50}',username):raise ValueError('Invalid administrator action or username.')
    if not 12<=len(password)<=256:raise ValueError('Use 12 to 256 password characters.')
    with app.app_context():
        admin=Admin.query.filter_by(username=username).first()
        if action=='add':
            if admin:raise ValueError('Administrator already exists.')
            admin=Admin(username=username,role='owner');db.session.add(admin)
        elif not admin:raise ValueError('Administrator not found.')
        admin.password=generate_password_hash(password);db.session.flush()
        # Revoke every login after changing access, preserving existing 2FA.
        from datetime import datetime
        panel_sessions.PanelSession.query.filter_by(admin_id=admin.id,revoked_at=None).update(dict(revoked_at=datetime.utcnow()),synchronize_session=False)
        db.session.add(security.Audit(admin_id=admin.id,username='root (SSH)',action='admin_'+action,details=__import__('json').dumps({'username':username}),address='local'))
        db.session.commit()
if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit('Usage: manage_admin.py add|password USERNAME (password on stdin)')
    try:change(sys.argv[1],sys.argv[2],sys.stdin.readline().rstrip('\n'))
    except ValueError as exc:raise SystemExit(str(exc))
    print('Administrator access updated; existing sessions revoked.')
