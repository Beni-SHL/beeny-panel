"""Custom representative tariffs and extra catalog plans using existing orders."""
import json,secrets
from functools import wraps
from types import SimpleNamespace
from flask import abort,flash,jsonify,redirect,request,session
from flask_login import current_user,login_required
from sqlalchemy import update
from pricing import quote

def register(app,db,User,features,credit,commissions,resellers,panel_path):
    base=panel_path.rstrip('/')
    class CustomPolicy(db.Model):
        __tablename__='representative_custom_tariffs'
        reseller_id=db.Column(db.Integer,primary_key=True)
        enabled=db.Column(db.Boolean,nullable=False,default=False)
        base=db.Column(db.BigInteger,nullable=False,default=0)
        per_gb=db.Column(db.BigInteger,nullable=False,default=0)
        per_day=db.Column(db.BigInteger,nullable=False,default=0)
        per_device=db.Column(db.BigInteger,nullable=False,default=0)
        max_percent=db.Column(db.Integer,nullable=False,default=50)
        sale_percent=db.Column(db.Integer,nullable=False,default=0)
    def transactional(fn):
        @wraps(fn)
        def wrapper(*args,**kwargs):
            try:return fn(*args,**kwargs)
            except Exception:db.session.rollback();raise
        return wrapper
    def custom(uid):return db.session.get(CustomPolicy,uid)
    def policy(row):return dict(enabled=bool(row and row.enabled),**{key:int(getattr(row,key,0)) for key in ['base','per_gb','per_day','per_device']})
    def custom_quote(uid,days,quota,devices):
        row=custom(uid)
        if not credit.mode(uid) or not row or not row.enabled:raise ValueError('سرویس دلخواه برای این نماینده فعال نیست.')
        plan=quote(policy(row),days,quota,devices);cost=plan['price']
        if not 0<=row.sale_percent<=row.max_percent<=1000:raise ValueError('تعرفه نماینده نیاز به بررسی مدیر دارد.')
        retail=cost+cost*row.sale_percent//100
        if retail>1000000000:raise ValueError('قیمت این ترکیب از سقف مجاز بیشتر است.')
        plan.update(price=retail,commission_base=cost,commission_reseller=uid,commission_maximum=min(1000000000,cost+cost*row.max_percent//100),commission_amount=retail-cost,title_en=f'Custom · {plan["days"]} days · {plan["quota"]} GB · {plan["devices"]} devices')
        return plan
    def customer_quote(user,days,quota,devices):
        if user.reseller_id and credit.mode(user.reseller_id):return custom_quote(user.reseller_id,days,quota,devices)
        return quote(features.settings()['custom_pricing'],days,quota,devices)
    def retail_policy(uid):
        row=custom(uid);cfg=policy(row)
        if row:
            for key in ['base','per_gb','per_day','per_device']:cfg[key]+=cfg[key]*row.sale_percent//100
        return cfg
    from pathlib import Path
    translations=json.loads((Path(__file__).parent/'static/i18n/representative-admin-en.json').read_text())
    @app.context_processor
    def context():
        lang=session.get('rep_admin_language',getattr(current_user,'language','en') if current_user.is_authenticated else 'en')
        return dict(rep_admin_language=lang,rep_t=lambda text:translations.get(text,text) if lang=='en' else text,rep_custom_policy=custom)
    @app.post(base+'/settings/representative-credit/language')
    @login_required
    def representative_language():
        if current_user.role!='owner':abort(403)
        features.verify_csrf();lang=request.form.get('language')
        if lang not in {'fa','en'}:abort(400)
        session['rep_admin_language']=lang
        tab=request.form.get('tab','overview');uid=request.form.get('reseller_id',0,type=int) or 0
        if tab not in {'overview','register','manage','prices','nodes','receipts','payouts','orders','cancellations','reports'}:tab='overview'
        return redirect(base+'/settings/representative-credit?tab='+tab+'&reseller_id='+str(uid))
    @app.post(base+'/settings/representative-credit/catalog')
    @login_required
    @transactional
    def catalog():
        if current_user.role!='owner':abort(403)
        features.verify_csrf();uid=request.form.get('reseller_id',type=int)
        if not db.session.get(resellers.Profile,uid):abort(404)
        action=request.form.get('action')
        if action=='custom_policy':
            row=custom(uid)
            if not row:row=CustomPolicy(reseller_id=uid);db.session.add(row)
            values={key:request.form.get(key,type=int) for key in ['base','per_gb','per_day','per_device']}
            maximum=request.form.get('max_percent',type=int)
            if any(v is None or not 0<=v<=1000000000 for v in values.values()) or maximum is None or not 0<=maximum<=1000:abort(400,'Invalid custom tariff')
            enabled=request.form.get('enabled')=='1'
            if enabled and not any(values.values()):abort(400,'At least one custom tariff must be positive.')
            for key,value in values.items():setattr(row,key,value)
            row.enabled=enabled;row.max_percent=maximum;row.sale_percent=min(row.sale_percent or 0,maximum)
            db.session.commit();flash('Custom tariff saved. Existing orders retain their prices.','success')
        elif action=='add_plan':
            title=request.form.get('title','').strip();title_en=request.form.get('title_en','').strip()
            vals={key:request.form.get(key,type=int) for key in ['days','quota','devices','price','maximum']}
            limits={'days':3650,'quota':1000000,'devices':100,'price':1000000000,'maximum':1000000000}
            if not 1<=len(title)<=100 or len(title_en)>120 or any(v is None or not 1<=v<=limits[k] for k,v in vals.items()) or vals['maximum']<vals['price']:abort(400,'Invalid plan details')
            from speed_policy import validate_policy
            try:speed=validate_policy(request.form.get('quota_mode','metered'),request.form.get('throttle_down_kbps',2000),request.form.get('throttle_up_kbps',2000),vals['quota'])
            except ValueError as error:abort(400,str(error))
            setting=db.session.get(features.CustomerSetting,'plans')
            if not setting:
                setting=features.CustomerSetting(key='plans',value=json.dumps(features.settings()['plans'],ensure_ascii=False));db.session.add(setting);db.session.flush()
            old=setting.value;plans=json.loads(old)
            if len(plans)>=50:abort(409,'Maximum 50 catalog plans; disable unwanted plans in representative price rules.')
            ref=request.form.get('reference','')
            if len(ref)!=32 or any(c not in '0123456789abcdef' for c in ref):abort(400)
            pid='p-'+ref[:20]
            if any(p['id']==pid for p in plans):return redirect(base+'/settings/representative-credit?tab=prices&reseller_id='+str(uid))
            plan=dict(id=pid,title=title,title_en=title_en,**{k:vals[k] for k in ['days','quota','devices','price']},**speed)
            plans.append(plan)
            changed=db.session.execute(update(features.CustomerSetting).where(features.CustomerSetting.key=='plans',features.CustomerSetting.value==old).values(value=json.dumps(plans,ensure_ascii=False))).rowcount
            if changed!=1:abort(409,'Catalog changed; reload and retry.')
            db.session.add(commissions.Rate(reseller_id=uid,plan_id=pid,base_price=vals['price'],maximum=vals['maximum'],sale_price=vals['price'],enabled=True))
            db.session.commit();flash('Plan added to the catalog and enabled for the selected representative.','success')
        else:abort(400)
        return redirect(base+'/settings/representative-credit?tab=prices&reseller_id='+str(uid))
    @app.post(base+'/c/<token>/reseller/credit/quote')
    def quote_route(token):
        user=features.resolve_account(token);features.verify_csrf()
        if not credit.allow_create(user.id):return jsonify(error='ساخت حساب برای این نماینده فعال نیست.'),403
        try:plan=custom_quote(user.id,request.form.get('custom_days'),request.form.get('custom_quota'),request.form.get('custom_devices'))
        except ValueError as e:return jsonify(error=str(e)),400
        return jsonify(price=plan['price'],base=plan['commission_base'],maximum=plan['commission_maximum'])
    @app.post(base+'/c/<token>/reseller/credit/custom-markup')
    @transactional
    def markup(token):
        user=features.resolve_account(token);features.verify_csrf()
        if not credit.allow_create(user.id):abort(403)
        row=custom(user.id) or abort(404);percent=request.form.get('sale_percent',type=int)
        if not row.enabled or percent is None or not 0<=percent<=row.max_percent:return jsonify(error='درصد فروش خارج از بازه مجاز است.'),400
        row.sale_percent=percent;db.session.commit();return jsonify(ok=True,message='درصد فروش سرویس دلخواه ذخیره شد.',percent=percent)
    return SimpleNamespace(CustomPolicy=CustomPolicy,custom=custom,custom_quote=custom_quote,customer_quote=customer_quote,retail_policy=retail_policy)
