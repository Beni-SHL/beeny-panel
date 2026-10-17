"""Revocable panel logins, independent from private customer sessions."""
import hashlib
import ipaddress
import secrets
from datetime import datetime, timedelta
from types import SimpleNamespace
from flask import session, request, render_template, redirect, jsonify, abort
from flask_login import current_user, login_required, logout_user


def register(app, db, Admin, features, panel_path):
    base = panel_path.rstrip('/')

    class PanelSession(db.Model):
        __tablename__ = 'panel_login_sessions'
        id = db.Column(db.String(64), primary_key=True)
        admin_id = db.Column(db.Integer, nullable=False, index=True)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        last_seen = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        expires_at = db.Column(db.DateTime, nullable=False)
        revoked_at = db.Column(db.DateTime)
        address = db.Column(db.String(64))
        browser = db.Column(db.String(250))

    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def start(admin):
        token = secrets.token_urlsafe(32)
        address = request.remote_addr
        if address in {'127.0.0.1','::1'}:
            try:
                address = str(ipaddress.ip_address(request.headers.get('X-Real-IP',address)))
            except ValueError:
                pass
        db.session.add(PanelSession(id=digest(token), admin_id=admin.id,
            expires_at=datetime.utcnow()+timedelta(days=7), address=address,
            browser=request.user_agent.string[:250]))
        db.session.commit()
        session['panel_session_token'] = token
        return f'{admin.id}:{token}'

    def load(identity):
        try:
            if ':' not in identity:
                # Existing fresh signed sessions are enrolled once. Old remembered
                # numeric identities must log in again and cannot bypass revocation.
                return db.session.get(Admin, int(identity)) if session.get('_fresh') else None
            uid, token = identity.split(':', 1)
            row = db.session.get(PanelSession, digest(token))
            if not row or row.admin_id != int(uid) or row.revoked_at or row.expires_at <= datetime.utcnow():
                return None
            session['panel_session_token'] = token
            return db.session.get(Admin, row.admin_id)
        except (ValueError, TypeError):
            return None

    @app.before_request
    def track_panel_session():
        if not current_user.is_authenticated:
            if ':' in str(session.get('_user_id', '')):
                logout_user()
            return
        identity = str(session.get('_user_id', ''))
        if ':' not in identity:
            session['_user_id'] = start(current_user)
        token = session.get('panel_session_token', '')
        row = db.session.get(PanelSession, digest(token))
        if row and (datetime.utcnow()-row.last_seen).total_seconds() > 60:
            row.last_seen = datetime.utcnow()
            db.session.commit()

    @app.get(base+'/sessions')
    @login_required
    def panel_sessions():
        now = datetime.utcnow()
        rows = PanelSession.query.filter(PanelSession.admin_id == current_user.id,
            PanelSession.revoked_at.is_(None), PanelSession.expires_at > now).order_by(PanelSession.last_seen.desc()).all()
        from session_identity import describe
        return render_template('panel_sessions.html', rows=rows,session_device=describe,
            current_id=digest(session.get('panel_session_token','')), panel_path=panel_path)

    def revoke(ids=None):
        query = PanelSession.query.filter_by(admin_id=current_user.id, revoked_at=None)
        if ids is not None:
            query = query.filter(PanelSession.id.in_(ids))
        query.update(dict(revoked_at=datetime.utcnow()), synchronize_session=False)
        db.session.commit()

    @app.post(base+'/sessions/revoke')
    @login_required
    def revoke_panel_session():
        features.verify_csrf()
        target = request.form.get('session_id', '')
        row = db.session.get(PanelSession, target)
        if not row or row.admin_id != current_user.id:
            abort(404)
        revoke([target])
        if target == digest(session.get('panel_session_token','')):
            logout_user()
            return redirect(base+'/login')
        return redirect(base+'/sessions')

    @app.post(base+'/api/logout/all')
    @login_required
    def logout_all_panel_sessions():
        features.verify_csrf()
        revoke()
        logout_user()
        return jsonify(success=True, message='All your panel sessions have been revoked.')

    def revoke_all(admin_id,keep=None):
        query=PanelSession.query.filter_by(admin_id=admin_id,revoked_at=None)
        if keep:query=query.filter(PanelSession.id!=digest(keep))
        query.update(dict(revoked_at=datetime.utcnow()),synchronize_session=False);db.session.commit()

    def end():
        token = session.get('panel_session_token')
        if token:
            revoke([digest(token)])
        session.pop('panel_session_token',None)

    return SimpleNamespace(PanelSession=PanelSession, start=start, load=load, end=end,revoke_all=revoke_all)
