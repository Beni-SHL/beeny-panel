"""Private support threads shared only with authorised administrators."""
from datetime import datetime,timedelta
from types import SimpleNamespace
from flask import request,abort,render_template,redirect,flash,send_file
from flask_login import login_required,current_user
from werkzeug.exceptions import HTTPException

def register(app,db,User,features,experience,panel_path):
    base=panel_path.rstrip('/')
    @app.errorhandler(HTTPException)
    def designed_error(error):
        if '/c/' in request.path:
            token=(request.view_args or {}).get('token')
            if not token:
                import re
                match=re.search(r'/c/([A-Za-z0-9_-]{20,})',request.path);token=match.group(1) if match else None
            representative_workspace=False;user=None;profile=None
            from flask import session
            if token and session.get('customer_auth'):
                try:
                    candidate=features.resolve_account(token)
                    if session['customer_auth'].get('user')==candidate.id:
                        user=candidate;profile=db.session.get(features.CustomerProfile,user.id)
                        representative_workspace=__import__('app').representative_credit.mode(user.id)
                except Exception:pass
            return render_template('customer_error.html',token=token,panel_path=panel_path,error=error,user=user,profile=profile,representative_workspace=representative_workspace,rep_section='support' if '/tickets' in request.path else ''),error.code
        if current_user.is_authenticated:
            return render_template('admin_error.html',panel_path=panel_path,error=error),error.code
        return error

    class Ticket(db.Model):
        __tablename__='support_tickets'
        id=db.Column(db.Integer,primary_key=True)
        user_id=db.Column(db.Integer,index=True,nullable=False)
        username=db.Column(db.String(100),nullable=False)
        subject=db.Column(db.String(150),nullable=False)
        status=db.Column(db.String(20),default='open',nullable=False)
        created_at=db.Column(db.DateTime,default=datetime.utcnow,index=True)
        updated_at=db.Column(db.DateTime,default=datetime.utcnow,index=True)
    class Message(db.Model):
        __tablename__='support_messages'
        id=db.Column(db.Integer,primary_key=True)
        ticket_id=db.Column(db.Integer,index=True,nullable=False)
        admin_id=db.Column(db.Integer)
        body=db.Column(db.Text,nullable=False)
        created_at=db.Column(db.DateTime,default=datetime.utcnow)
    def text(name,limit):
        value=request.form.get(name,'').strip()
        if not value or len(value)>limit:abort(400,'Invalid or empty message.')
        return value
    def thread(row):return Message.query.filter_by(ticket_id=row.id).order_by(Message.id).all()
    @app.route(base+'/c/<token>/tickets',methods=['GET','POST'])
    def customer_tickets(token):
        user=features.resolve_account(token)
        if request.method=='POST':
            features.verify_csrf()
            if Ticket.query.filter(Ticket.user_id==user.id,Ticket.created_at>datetime.utcnow()-timedelta(days=1)).count()>=5:abort(429,'تعداد تیکت‌های امروز به سقف مجاز رسیده است.')
            row=Ticket(user_id=user.id,username=user.username,subject=text('subject',150));db.session.add(row);db.session.flush()
            db.session.add(Message(ticket_id=row.id,body=text('message',3000)))
            experience.notify(None,'New support ticket',f'{user.username}: ticket #{row.id}')
            db.session.commit();flash('تیکت ثبت شد؛ پاسخ در همین بخش نمایش داده می‌شود.','success')
            return redirect(base+'/c/'+token+'/tickets/'+str(row.id))
        pagination=Ticket.query.filter_by(user_id=user.id).order_by(Ticket.updated_at.desc(),Ticket.id.desc()).paginate(page=max(1,request.args.get('page',1,type=int)),per_page=12,error_out=False)
        return render_template('tickets.html',rows=pagination.items,pagination=pagination,customer=True,token=token,panel_path=panel_path,user=user,profile=db.session.get(features.CustomerProfile,user.id),representative_workspace=__import__('app').representative_credit.mode(user.id),rep_section='support')
    @app.get(base+'/c/<token>/tickets/new')
    def customer_ticket_new(token):
        user=features.resolve_account(token)
        return render_template('ticket_new.html',token=token,panel_path=panel_path,user=user,profile=db.session.get(features.CustomerProfile,user.id),representative_workspace=__import__('app').representative_credit.mode(user.id),rep_section='support')
    @app.get(base+'/c/<token>/tickets/<int:ticket_id>')
    def customer_ticket_detail(token,ticket_id):
        user=features.resolve_account(token)
        row=Ticket.query.filter_by(id=ticket_id,user_id=user.id).first_or_404()
        return render_template('ticket_detail.html',row=row,messages=thread(row),ticket_profile=db.session.get(features.CustomerProfile,row.user_id),customer=True,token=token,panel_path=panel_path,user=user,profile=db.session.get(features.CustomerProfile,user.id),representative_workspace=__import__('app').representative_credit.mode(user.id),rep_section='support')
    def profile_image(row):
        profile=db.session.get(features.CustomerProfile,row.user_id)
        if not profile or not profile.avatar:abort(404)
        from pathlib import Path
        if Path(profile.avatar).name!=profile.avatar:abort(404)
        path=features.storage/profile.avatar
        if not path.is_file():abort(404)
        return send_file(path,mimetype='image/webp',max_age=3600)
    @app.get(base+'/c/<token>/tickets/<int:ticket_id>/avatar')
    def customer_ticket_avatar(token,ticket_id):
        user=features.resolve_account(token)
        return profile_image(Ticket.query.filter_by(id=ticket_id,user_id=user.id).first_or_404())
    @app.get(base+'/tickets/<int:ticket_id>/avatar')
    @login_required
    def ticket_customer_avatar(ticket_id):
        return profile_image(allowed_ticket(ticket_id))
    @app.post(base+'/c/<token>/tickets/<int:ticket_id>/reply')
    def customer_ticket_reply(token,ticket_id):
        user=features.resolve_account(token);features.verify_csrf()
        row=Ticket.query.filter_by(id=ticket_id,user_id=user.id).first_or_404()
        if row.status=='closed':abort(409,'تیکت بسته شده است؛ تیکت جدید ثبت کنید.')
        if Message.query.filter(Message.ticket_id==row.id,Message.admin_id.is_(None),Message.created_at>datetime.utcnow()-timedelta(minutes=1)).count()>=5:abort(429)
        db.session.add(Message(ticket_id=row.id,body=text('message',3000)));row.updated_at=datetime.utcnow();row.status='open'
        experience.notify(None,'Support reply',f'{user.username}: ticket #{row.id}')
        db.session.commit();return redirect(base+'/c/'+token+'/tickets/'+str(row.id))
    def allowed_ticket(ticket_id):
        row=db.session.get(Ticket,ticket_id) or abort(404)
        if current_user.role=='seller' and not User.query.filter_by(id=row.user_id,owner_id=current_user.id).first():abort(404)
        return row
    @app.get(base+'/tickets')
    @login_required
    def ticket_list():
        query=Ticket.query
        if current_user.role=='seller':query=query.filter(Ticket.user_id.in_(db.select(User.id).where(User.owner_id==current_user.id)))
        pagination=query.order_by(Ticket.updated_at.desc(),Ticket.id.desc()).paginate(page=max(1,request.args.get('page',1,type=int)),per_page=12,error_out=False)
        return render_template('tickets.html',rows=pagination.items,pagination=pagination,customer=False,panel_path=panel_path)
    @app.get(base+'/tickets/<int:ticket_id>')
    @login_required
    def ticket_detail(ticket_id):
        row=allowed_ticket(ticket_id)
        return render_template('ticket_detail.html',row=row,messages=thread(row),ticket_profile=db.session.get(features.CustomerProfile,row.user_id),customer=False,panel_path=panel_path)
    @app.post(base+'/tickets/<int:ticket_id>/delete')
    @login_required
    def ticket_delete(ticket_id):
        if current_user.role not in {'owner','support'}:abort(403)
        row=allowed_ticket(ticket_id)
        Message.query.filter_by(ticket_id=row.id).delete()
        db.session.delete(row);db.session.commit()
        flash('Conversation deleted.','success')
        return redirect(base+'/tickets')
    @app.post(base+'/tickets/<int:ticket_id>/reply')
    @login_required
    def ticket_reply(ticket_id):
        row=allowed_ticket(ticket_id)
        db.session.add(Message(ticket_id=row.id,admin_id=current_user.id,body=text('message',3000)))
        row.updated_at=datetime.utcnow();row.status='answered'
        if User.query.filter_by(id=row.user_id).first():experience.notify(row.user_id,'پاسخ پشتیبانی',f'پاسخ تیکت «{row.subject}» در بخش پشتیبانی آماده است.')
        db.session.commit();return redirect(base+'/tickets/'+str(row.id))
    @app.post(base+'/tickets/<int:ticket_id>/status')
    @login_required
    def ticket_update(ticket_id):
        row=allowed_ticket(ticket_id);status=request.form.get('status')
        if status not in {'open','closed'}:abort(400)
        row.status=status;row.updated_at=datetime.utcnow();db.session.commit();return redirect(base+'/tickets/'+str(row.id))
    return SimpleNamespace(Ticket=Ticket,Message=Message)
