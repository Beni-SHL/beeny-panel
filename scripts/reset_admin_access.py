"""Interactive file-based administrator recovery; no heredoc input ambiguity."""
import os,argparse,sqlite3,getpass,secrets
from pathlib import Path
from datetime import datetime
from werkzeug.security import generate_password_hash

def main():
    if os.geteuid()!=0:raise SystemExit('Run as root.')
    parser=argparse.ArgumentParser();parser.add_argument('--username',required=True);parser.add_argument('--disable-2fa',action='store_true');args=parser.parse_args()
    path=Path('/opt/beeny-panel/instance/beeny.db')
    with sqlite3.connect(path) as db:
        row=db.execute('SELECT id,username FROM admin WHERE username=?',(args.username,)).fetchone()
        if not row:raise SystemExit('Administrator not found.')
        password=getpass.getpass('New password (12+ characters): ')
        if not 12<=len(password)<=256 or password!=getpass.getpass('Repeat password: '):raise SystemExit('Invalid password or passwords do not match.')
        backup=Path('/root')/('beeny-admin-recovery-'+datetime.utcnow().strftime('%Y%m%dT%H%M%S')+'-'+secrets.token_hex(4)+'.db')
        fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        with sqlite3.connect(backup) as out:db.backup(out)
        db.execute('UPDATE admin SET password=? WHERE id=?',(generate_password_hash(password),row[0]))
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if args.disable_2fa:
            columns={r[1] for r in db.execute('PRAGMA table_info(admin)')}
            if {'totp_secret','totp_counter','recovery_codes'}.issubset(columns):db.execute("UPDATE admin SET totp_secret=NULL,totp_counter=-1,recovery_codes='[]' WHERE id=?",(row[0],))
        if 'panel_login_sessions' in tables:db.execute('UPDATE panel_login_sessions SET revoked_at=? WHERE admin_id=?',(datetime.utcnow().isoformat(' '),row[0]))
        db.commit()
    print('Password reset; administrator sessions revoked. Backup:',backup)
if __name__=='__main__':main()
