"""Owner-managed private portal content and durable announcement acknowledgements."""
import json
import secrets
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from types import SimpleNamespace
from flask import request, abort, render_template, redirect, send_file, jsonify, session
from flask_login import login_required, current_user
from werkzeug.exceptions import HTTPException


def register(app, db, User, features, panel_path):
    base = panel_path.rstrip('/')
    video_storage=Path(app.instance_path)/'customer_videos'
    max_video=200*1024*1024
    if app.config.get('MAX_CONTENT_LENGTH') is None:app.config['MAX_CONTENT_LENGTH']=24*1024*1024
    class Announcement(db.Model):
        __tablename__ = 'portal_announcements'
        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(120), nullable=False)
        body = db.Column(db.Text, nullable=False)
        title_en = db.Column(db.String(120), default='')
        body_en = db.Column(db.Text, default='')
        active = db.Column(db.Boolean, default=True, nullable=False)
        icon = db.Column(db.String(20), default='info', nullable=False)
        color = db.Column(db.String(20), default='blue', nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow)
    class Seen(db.Model):
        __tablename__ = 'portal_announcement_seen'
        user_id = db.Column(db.Integer, primary_key=True)
        announcement_id = db.Column(db.Integer, primary_key=True)
        seen_at = db.Column(db.DateTime, default=datetime.utcnow)

    def config():
        try:
            value = json.loads(features.get_setting('portal_content', '{}'))
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}
    def safe_url(value, telegram=False):
        value = value.strip()
        if not value: return ''
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Use a valid HTTPS URL.')
        if telegram and parsed.hostname.lower() not in {'t.me', 'telegram.me'}:
            raise ValueError('Telegram links must use https://t.me/.')
        if len(value) > 1000: raise ValueError('URL is too long.')
        return value
    def owner():
        if (getattr(current_user, 'role', 'owner') or 'owner') != 'owner': abort(403)
    def clean_text(key, limit, required=False):
        value = request.form.get(key, '').strip()
        if len(value) > limit or (required and not value): raise ValueError('Missing or oversized text.')
        return value
    def upload_image(key):
        file = request.files.get(key)
        return features.store_image(file.stream.read(20*1024*1024+1),avatar=key!='cover',cover=key=='cover') if file and file.filename else None
    def remove_image(name):
        if name and Path(name).name == name: (features.storage/name).unlink(missing_ok=True)

    def remove_video(name):
        if re.fullmatch(r'[a-f0-9]{48}\.(mp4|webm)',name or ''):(video_storage/name).unlink(missing_ok=True)
    def store_video(file):
        extension=Path(file.filename or '').suffix.lower()
        if extension not in {'.mp4','.webm'}:raise ValueError('Choose an MP4 or WebM video, up to 200 MB.')
        probe=shutil.which('ffprobe')
        if not probe:raise ValueError('Video validation is unavailable. Install ffmpeg on the panel server.')
        video_storage.mkdir(parents=True,exist_ok=True,mode=0o700)
        name=secrets.token_hex(24)+extension;path=video_storage/name
        try:
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            size=0
            with os.fdopen(fd,'wb') as output:
                while True:
                    chunk=file.stream.read(65536)
                    if not chunk:break
                    size+=len(chunk)
                    if size>max_video:raise ValueError('Video must be at most 200 MB.')
                    output.write(chunk)
            if not size:raise ValueError('Video file is empty.')
            result=subprocess.run([probe,'-protocol_whitelist','file,pipe','-v','error','-show_entries','format=format_name:stream=codec_type,codec_name','-of','json',str(path)],capture_output=True,text=True,timeout=20)
            try:metadata=json.loads(result.stdout)
            except ValueError:raise ValueError('The video file could not be read.')
            streams=metadata.get('streams',[]);codecs={row.get('codec_name') for row in streams if row.get('codec_type')=='video'}
            container=metadata.get('format',{}).get('format_name','')
            audio={row.get('codec_name') for row in streams if row.get('codec_type')=='audio'}
            if result.returncode or not codecs:raise ValueError('The uploaded file is not a valid video.')
            if extension=='.mp4' and ('mp4' not in container or codecs!={'h264'}):raise ValueError('For MP4, use H.264 video for mobile compatibility.')
            if extension=='.webm' and ('webm' not in container or not codecs<={'vp8','vp9','av1'}):raise ValueError('Choose a valid WebM video.')
            if extension=='.mp4' and not audio<={'aac','mp3'}:raise ValueError('Use AAC audio for an MP4 tutorial.')
            if extension=='.webm' and not audio<={'opus','vorbis'}:raise ValueError('Use Opus or Vorbis audio for WebM.')
            return name
        except subprocess.TimeoutExpired:
            path.unlink(missing_ok=True);raise ValueError('Video validation timed out. Try a smaller video.')
        except Exception:
            path.unlink(missing_ok=True);raise

    @app.route(base+'/settings/portal-content', methods=['GET', 'POST'])
    @login_required
    def portal_content_settings():
        owner(); cfg = config(); error = None
        new_images=[];new_videos=[]
        if request.method == 'POST':
            features.verify_csrf()
            try:
                action = request.form.get('action', 'settings')
                if action == 'settings':
                    cfg['channel'] = safe_url(request.form.get('channel', ''), True)
                    cfg['group'] = safe_url(request.form.get('group', ''), True)
                    avatar = upload_image('support_avatar')
                    if avatar:
                        old = cfg.get('support_avatar'); cfg['support_avatar'] = avatar
                    else: old = None
                    features.set_setting('portal_content', json.dumps(cfg)); db.session.commit(); remove_image(old)
                elif action == 'video':
                    videos = cfg.get('videos', [])
                    existing=next((v for v in videos if v['id']==request.form.get('id')),None)
                    if not existing and len(videos) >= 40: raise ValueError('Maximum 40 tutorials.')
                    video = dict(id=existing['id'] if existing else secrets.token_hex(12), title=clean_text('title', 120, True),
                                 title_en=clean_text('title_en',120), url=safe_url(request.form.get('url', '')))
                    upload=request.files.get('video_file')
                    if upload and upload.filename:
                        if video['url']:raise ValueError('Choose either an uploaded file or an HTTPS link, not both.')
                        video['file']=store_video(upload);new_videos.append(video['file'])
                    elif not video['url'] and existing and existing.get('file'):video['file']=existing['file']
                    if not video['url'] and not video.get('file'): raise ValueError('Upload a video or enter a direct HTTPS video URL.')
                    new_cover=upload_image('cover')
                    if new_cover:new_images.append(new_cover)
                    video['cover'] = new_cover or (existing.get('cover') if existing else None)
                    if existing: videos=[video if v['id']==existing['id'] else v for v in videos]
                    else: videos.append(video)
                    cfg['videos'] = videos
                    features.set_setting('portal_content', json.dumps(cfg)); db.session.commit()
                    if existing and new_cover:remove_image(existing.get('cover'))
                    if existing and existing.get('file')!=video.get('file'):remove_video(existing.get('file'))
                elif action == 'delete_video':
                    vid = request.form.get('id'); old = next((v for v in cfg.get('videos',[]) if v['id']==vid),None)
                    cfg['videos'] = [v for v in cfg.get('videos',[]) if v['id']!=vid]
                    features.set_setting('portal_content', json.dumps(cfg)); db.session.commit()
                    if old: remove_image(old.get('cover'));remove_video(old.get('file'))
                elif action in {'announcement','edit_announcement'}:
                    icon=request.form.get('icon','info');color=request.form.get('color','blue')
                    if icon not in {'info','bell','check','warning','gift','sparkles','maintenance'} or color not in {'blue','green','amber','rose','violet','slate'}:
                        raise ValueError('Choose a supported icon and color.')
                    values=dict(title=clean_text('title',120,True),body=clean_text('body',4000,True),title_en=clean_text('title_en',120),body_en=clean_text('body_en',4000),icon=icon,color=color)
                    if action=='edit_announcement':
                        row=db.session.get(Announcement,request.form.get('id',type=int))
                        if not row:abort(404)
                        changed=any(getattr(row,key)!=value for key,value in values.items())
                        for key,value in values.items():setattr(row,key,value)
                        if changed:Seen.query.filter_by(announcement_id=row.id).delete()
                    else:db.session.add(Announcement(**values))
                    db.session.commit()
                elif action=='delete_announcement':
                    row=db.session.get(Announcement,request.form.get('id',type=int))
                    if not row:abort(404)
                    Seen.query.filter_by(announcement_id=row.id).delete();db.session.delete(row);db.session.commit()
                elif action == 'toggle_announcement':
                    row = db.session.get(Announcement, request.form.get('id', type=int))
                    if not row: abort(404)
                    row.active = not row.active; db.session.commit()
                else: abort(400)
                if request.accept_mimetypes.best=='application/json':return jsonify(ok=True,redirect=request.path)
                return redirect(request.path)
            except ValueError as exc:
                db.session.rollback(); error = str(exc)
                for name in new_images:remove_image(name)
                for name in new_videos:remove_video(name)
                cfg=config()
                if request.accept_mimetypes.best=='application/json':return jsonify(ok=False,error=error),400
            except Exception:
                db.session.rollback()
                for name in new_images:remove_image(name)
                for name in new_videos:remove_video(name)
                raise
        return render_template('portal_content_settings.html', cfg=cfg, panel_path=panel_path, announcements=Announcement.query.order_by(Announcement.id.desc()).limit(100).all(), error=error)

    @app.get(base+'/c/<token>/learn')
    def customer_learn(token):
        features.resolve_account(token)
        return render_template('customer_learn.html', token=token, panel_path=panel_path, cfg=config())

    @app.get(base+'/c/<token>/video/<video_id>')
    def customer_tutorial_video(token,video_id):
        features.resolve_account(token)
        video=next((v for v in config().get('videos',[]) if v.get('id')==video_id),None)
        name=video.get('file') if video else None
        if not re.fullmatch(r'[a-f0-9]{48}\.(mp4|webm)',name or ''):abort(404)
        path=video_storage/name
        if not path.is_file():abort(404)
        response=send_file(path,mimetype='video/mp4' if name.endswith('.mp4') else 'video/webm',conditional=True,max_age=0)
        response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.get(base+'/c/<token>/media/<name>')
    def customer_content_media(token, name):
        features.resolve_account(token); cfg=config()
        permitted={cfg.get('support_avatar')} | {v.get('cover') for v in cfg.get('videos',[])}
        if name not in permitted or Path(name).name != name: abort(404)
        path=features.storage/name
        if not path.is_file(): abort(404)
        return send_file(path, mimetype='image/webp', max_age=3600)

    @app.get(base+'/settings/portal-content/videos/<video_id>')
    @login_required
    def owner_tutorial_video(video_id):
        owner();video=next((v for v in config().get('videos',[]) if v.get('id')==video_id),None)
        name=video.get('file') if video else None
        if not re.fullmatch(r'[a-f0-9]{48}\.(mp4|webm)',name or '') or not (video_storage/name).is_file():abort(404)
        response=send_file(video_storage/name,mimetype='video/mp4' if name.endswith('.mp4') else 'video/webm',conditional=True,max_age=0)
        response.headers['Cache-Control']='private, no-store';return response

    @app.get(base+'/settings/portal-content/avatar')
    @login_required
    def support_staff_avatar():
        name=config().get('support_avatar')
        if not name or Path(name).name!=name or not (features.storage/name).is_file(): abort(404)
        return send_file(features.storage/name, mimetype='image/webp', max_age=3600)

    @app.post(base+'/c/<token>/announcements/<int:announcement_id>/seen')
    def announcement_seen(token, announcement_id):
        user=features.resolve_account(token); features.verify_csrf()
        row=db.session.get(Announcement, announcement_id)
        if not row or not row.active: abort(404)
        if not db.session.get(Seen,(user.id,row.id)):
            db.session.add(Seen(user_id=user.id,announcement_id=row.id)); db.session.commit()
        return jsonify(ok=True)

    @app.post(base+'/c/<token>/language')
    def customer_language(token):
        features.resolve_account(token); features.verify_csrf()
        language=request.form.get('language')
        if language not in {'fa','en'}: abort(400)
        session['customer_language']=language
        return redirect(base+'/c/'+token)

    @app.before_request
    def login_language():
        if request.endpoint=='customer_login' and request.args.get('lang') in {'fa','en'}:
            session['customer_language']=request.args['lang']

    @app.before_request
    def content_upload_limit():
        if request.endpoint=='portal_content_settings':request.max_content_length=max_video+21*1024*1024
        elif request.endpoint=='upload_backup':request.max_content_length=224*1024*1024
    # Run before the security guard reads multipart form data for CSRF.
    app.before_request_funcs[None].remove(content_upload_limit)
    app.before_request_funcs[None].insert(0,content_upload_limit)

    @app.context_processor
    def context():
        args=request.view_args or {}; token=args.get('token'); cfg=config()
        pending=[]
        if token and request.endpoint=='customer_portal':
            try:
                user=features.resolve_account(token)
            except HTTPException:
                user=None
            pending=Announcement.query.filter(Announcement.active.is_(True),~db.exists().where(
                (Seen.user_id==(user.id if user else -1))&(Seen.announcement_id==Announcement.id))).order_by(Announcement.id).limit(10).all() if user else []
        return dict(portal_content=cfg, portal_announcements=pending,community_admin=features.settings().get('admin_telegram',''),
                    customer_language=session.get('customer_language','fa'))
    return SimpleNamespace(Announcement=Announcement, Seen=Seen, config=config,store_video=store_video,video_storage=video_storage)
