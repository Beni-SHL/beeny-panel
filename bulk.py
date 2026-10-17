"""Previewed background operations with per-account progress and scoped ownership."""
import json,secrets,time,math
from datetime import datetime
from types import SimpleNamespace
from flask import request,session,abort,render_template,redirect,flash
from flask_login import current_user,login_required
from renewal import extend_expiry,activation_error

def register(app,db,User,features,experience,panel_path):
    base=panel_path.rstrip('/')
    class Job(db.Model):
        __tablename__='bulk_account_jobs'
        id=db.Column(db.Integer,primary_key=True)
        admin_id=db.Column(db.Integer,index=True,nullable=False)
        operation=db.Column(db.String(20),nullable=False)
        value=db.Column(db.Integer,nullable=False)
        created_at=db.Column(db.DateTime,default=datetime.utcnow)
    class Item(db.Model):
        __tablename__='bulk_account_items'
        id=db.Column(db.Integer,primary_key=True)
        job_id=db.Column(db.Integer,index=True,nullable=False)
        user_id=db.Column(db.Integer,nullable=False)
        username=db.Column(db.String(100),nullable=False)
        state=db.Column(db.String(20),default='pending',nullable=False)
        detail=db.Column(db.String(200))
    @app.route(base+'/users/bulk',methods=['GET','POST'])
    @login_required
    def bulk_users():
        preview=None
        if request.method=='POST':
            if request.form.get('confirm'):
                saved=session.pop('bulk_preview',None)
                if not saved or not secrets.compare_digest(saved['token'],request.form['confirm']) or saved['expires']<time.time():abort(400,'Preview expired. Preview the changes again.')
                records=User.query.filter(User.id.in_(saved['ids'])).all()
                if len(records)!=len(saved['ids']):abort(409,'The selection changed. Preview again.')
                job=Job(admin_id=current_user.id,operation=saved['operation'],value=saved['value']);db.session.add(job);db.session.flush()
                for user in records:db.session.add(Item(job_id=job.id,user_id=user.id,username=user.username))
                db.session.commit();flash('Job queued. Per-account progress appears below.','success');return redirect(base+'/users/bulk')
            ids=request.form.getlist('users',type=int);operation=request.form.get('operation');value=request.form.get('value',0,type=int)
            if not ids or len(ids)>100 or len(set(ids))!=len(ids) or operation not in {'renew','add_quota','disable','enable'}:abort(400)
            if operation in {'renew','add_quota'} and not 1<=value<=(3650 if operation=='renew' else 1000000):abort(400)
            records=User.query.filter(User.id.in_(ids)).all()
            if len(records)!=len(ids):abort(404)
            preview=dict(ids=ids,operation=operation,value=value,token=secrets.token_urlsafe(32),expires=time.time()+300,names=[u.username for u in records])
            session['bulk_preview']=preview
        jobs=Job.query.order_by(Job.id.desc())
        if current_user.role!='owner':jobs=jobs.filter_by(admin_id=current_user.id)
        jobs=jobs.limit(20).all()
        return render_template('bulk.html',preview=preview,users=User.query.order_by(User.username).limit(1000).all(),jobs=jobs,items={j.id:Item.query.filter_by(job_id=j.id).all() for j in jobs},panel_path=panel_path)
    def cycle():
        from app import Admin
        for item in Item.query.filter_by(state='pending').order_by(Item.id).limit(5).all():
            job=db.session.get(Job,item.job_id);user=db.session.get(User,item.user_id);admin=db.session.get(Admin,job.admin_id)
            if not user or user.username!=item.username or not admin or admin.role not in {'owner','seller'} or (admin.role=='seller' and user.owner_id!=admin.id):item.state='failed';item.detail='Account missing or access no longer permitted.';db.session.commit();continue
            if job.operation=='renew':user.expire_date=extend_expiry(user.expire_date,job.value)
            elif job.operation=='add_quota':user.traffic_limit=max(user.traffic_limit or 0,math.ceil(user.traffic_usage or 0))+job.value
            elif job.operation=='disable':user.status='disabled'
            elif job.operation=='enable':
                if activation_error(user.expire_date,user.traffic_limit or 0,user.traffic_usage or 0, quota_mode=getattr(user,'quota_mode','metered')):item.state='failed';item.detail='Account has expired or exhausted quota.';db.session.commit();continue
                user.status='active'
            item.state='applied';user.pause_sync_pending=True
            from app import security
            db.session.add(security.Audit(admin_id=admin.id,username=admin.username,action='bulk.apply',details=json.dumps(dict(job=job.id,user=item.username,operation=job.operation,value=job.value)),address='worker'))
            db.session.commit()
            try:
                failures=experience.sync_access(user)
                item.state='confirmation_pending' if failures else 'completed';item.detail=', '.join(failures) if failures else 'Applied and confirmed.'
            except Exception:item.state='confirmation_pending';item.detail='Account saved; node confirmation is pending.'
            db.session.commit()
        for item in Item.query.filter(Item.state.in_(['confirmation_pending','applied'])).limit(20).all():
            user=db.session.get(User,item.user_id)
            if user and user.username==item.username and not user.pause_sync_pending:item.state='completed';item.detail='Confirmed by nodes.'
        db.session.commit()
    return SimpleNamespace(Job=Job,Item=Item,cycle=cycle)
