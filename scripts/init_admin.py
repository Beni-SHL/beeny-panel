"""Initialize the first admin. Password is read from stdin, never argv."""
import sys
from werkzeug.security import generate_password_hash
from app import app, db, Admin

if __name__ == '__main__':
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        raise SystemExit('Usage: init_admin.py USERNAME < password_from_stdin')
    password = sys.stdin.readline().rstrip('\n')
    if len(password) < 12:
        raise SystemExit('Admin password must have at least 12 characters')
    with app.app_context():
        db.create_all()
        if Admin.query.first():
            raise SystemExit('Admin already exists; leaving it unchanged')
        db.session.add(Admin(username=sys.argv[1], password=generate_password_hash(password)))
        db.session.commit()
    print('First admin created.')
