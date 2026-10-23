"""Validated, public presentation tokens; only the owner may change global themes."""
import copy,json,re,hmac
from types import SimpleNamespace
from flask import abort,jsonify,render_template,request,session
from flask_login import login_required,current_user

PRESETS={
 'iris':dict(light='#6854cf',dark='#bcacff'),
 'sunrise':dict(light='#bd4c28',dark='#ffbf7b'),
 'jade':dict(light='#16785e',dark='#7de7b7'),
 'ocean':dict(light='#2463bc',dark='#98c8ff'),
 'rose':dict(light='#b43b72',dark='#ffafd1'),
}
DEFAULT={scope:dict(avatar_colors=scope=='customer',background_intensity=80,
    dark=dict(colors=['#101c2a','#273cb6','#292c3e'] if scope=='customer' else ['#1e3cc8','#06081e','#96d7ff'],colored=True,blur=6,opacity=34,shade=8,saturation=150,tint='#202329',icons='#b8a8ff',titles='#e7e4ff',buttons='#b4a5ff'),
    light=dict(colors=['#7878bc','#a496d5','#aeaeae'] if scope=='customer' else ['#dadce7','#fffdfd','#e2f3f4'],colored=True,blur=6,opacity=32,shade=100,saturation=140,tint='#edf0ff',icons='#6951c9',titles='#393052',buttons='#6854cf')) for scope in ('admin','customer')}

NAV_ITEMS={
 'overview':('users','حساب من','My account'), 'renew':('renew','تمدید','Renew'),
 'configs':('download','دانلود','Downloads'), 'tickets':('support','پشتیبانی','Support'),
 'wallet':('wallet','کیف پول','Wallet'), 'devices':('devices','دستگاه‌ها','Devices')}
DEFAULT['customer'].update(navigation=dict(items=['overview','renew','configs','tickets'],liquid_background=True,liquid_buttons=False),
 avatar=dict(ring=True,animated=True,backlight=True,strength=45,color='#7d8dff',effect='breathe',speed=4))
for mode in ('light','dark'):
 DEFAULT['customer'][mode]['background_intensity']=80
 DEFAULT['customer'][mode].update(welcome='#247da4' if mode=='light' else '#8ddbe9',subtitle='#626a79' if mode=='light' else '#b2bdcc',online='#19835b' if mode=='light' else '#68e2ad',offline='#68717e' if mode=='light' else '#bdc6d2',nav_icons='#485162' if mode=='light' else '#d7dfeb',nav_active='#6854cf' if mode=='light' else '#c4b7ff')

def clean(data):
    if not isinstance(data,dict) or set(data)!={'admin','customer'}:raise ValueError('Both theme workspaces are required.')
    result=copy.deepcopy(DEFAULT)
    def color(value):
        if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):raise ValueError('Use six-digit hex colors.')
        return value.lower()
    def number(value,lo,hi):
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not lo<=value<=hi:raise ValueError('A theme value is outside its permitted range.')
        return round(value,2)
    for scope in result:
        obj=data[scope]
        if not isinstance(obj,dict) or not {'avatar_colors','background_intensity','dark','light'}<=set(obj) or set(obj)-set(result[scope]):raise ValueError('Invalid workspace settings.')
        if not isinstance(obj['avatar_colors'],bool):raise ValueError('Invalid avatar setting.')
        result[scope]['avatar_colors']=obj['avatar_colors']
        result[scope]['background_intensity']=number(obj['background_intensity'],0,100)
        for mode in ('light','dark'):
            part=obj[mode]
            if not isinstance(part,dict) or set(part)-set(result[scope][mode]) or not (set(DEFAULT['admin'][mode])<=set(part)):raise ValueError('Invalid theme fields.')
            if not isinstance(part['colors'],list) or len(part['colors'])!=3:raise ValueError('Three background colors are required.')
            if not isinstance(part['colored'],bool):raise ValueError('Invalid glass color setting.')
            out=result[scope][mode];out['colored']=part['colored'];out['colors']=[color(v) for v in part['colors']]
            for key in ('tint','icons','titles','buttons'):out[key]=color(part[key])
            if scope=='customer':
                for key in ('welcome','subtitle','online','offline','nav_icons','nav_active'):out[key]=color(part.get(key,DEFAULT[scope][mode][key]))
            for key,limit in [('blur',20),('opacity',95),('shade',100),('saturation',200)]:out[key]=number(part[key],0,limit)
        if scope=='customer':
            for mode in ('light','dark'):
                result[scope][mode]['background_intensity']=number(obj[mode].get('background_intensity',obj['background_intensity']),0,100)
            nav=obj.get('navigation',DEFAULT[scope]['navigation'])
            if not isinstance(nav,dict) or set(nav)!=set(DEFAULT[scope]['navigation']):raise ValueError('Invalid navigation settings.')
            items=nav['items']
            if not isinstance(items,list) or not 1<=len(items)<=len(NAV_ITEMS) or any(not isinstance(v,str) or v not in NAV_ITEMS for v in items) or len(set(items))!=len(items):raise ValueError('Select unique navigation destinations.')
            if any(not isinstance(nav[k],bool) for k in ('liquid_background','liquid_buttons')):raise ValueError('Invalid navigation material.')
            result[scope]['navigation']=copy.deepcopy(nav)
            avatar=obj.get('avatar',DEFAULT[scope]['avatar'])
            if not isinstance(avatar,dict) or set(avatar)-set(DEFAULT[scope]['avatar']) or not {'ring','animated','backlight','strength'}<=set(avatar) or any(not isinstance(avatar[k],bool) for k in ('ring','animated','backlight')):raise ValueError('Invalid avatar settings.')
            if avatar.get('effect','breathe') not in ('static','breathe','rgb','orbit'):raise ValueError('Invalid avatar effect.')
            result[scope]['avatar']={**DEFAULT[scope]['avatar'],**avatar,'strength':number(avatar['strength'],0,100),'color':color(avatar.get('color',DEFAULT[scope]['avatar']['color'])),'speed':number(avatar.get('speed',4),1,12)}
    return result

def register(app,db,features,panel_path):
    def load():
        try:return clean(json.loads(features.get_setting('appearance_v1','null')))
        except (ValueError,TypeError):return copy.deepcopy(DEFAULT)
    @app.context_processor
    def theme_context():
        profile=None
        auth=session.get('customer_auth',{})
        if (request.view_args or {}).get('token') and request.endpoint!='customer_login' and isinstance(auth,dict) and auth.get('user'):
            profile=db.session.get(features.CustomerProfile,auth['user'])
        return dict(theme_config=load(),theme_nav_items=NAV_ITEMS,theme_avatar_choice=(profile.avatar_choice or 1) if profile else 1,theme_custom_avatar=bool(profile and profile.avatar))
    @app.route(panel_path.rstrip('/')+'/settings/theme',methods=['GET','POST'])
    @login_required
    def theme_page():
        if current_user.role!='owner':abort(403)
        if request.method=='GET':return render_template('settings_theme.html',panel_path=panel_path,theme_defaults=DEFAULT,theme_presets=PRESETS)
        supplied=request.headers.get("X-CSRF-Token", "")
        expected=session.get("_customer_csrf", "")
        if not expected or not hmac.compare_digest(supplied,expected):abort(400,"Refresh the page and try again.")
        if request.content_length and request.content_length>16384:abort(413)
        try:settings=clean(request.get_json(silent=True))
        except ValueError as error:return jsonify(success=False,message=str(error)),400
        features.set_setting('appearance_v1',json.dumps(settings,separators=(',',':')))
        db.session.commit()
        return jsonify(success=True,config=settings)
    return SimpleNamespace(load=load)
