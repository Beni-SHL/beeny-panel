"""Add telemetry and safe session control alongside an existing node agent."""
import os,re,secrets,time,subprocess
from pathlib import Path
from flask import Flask,request,jsonify,Response
import requests
from host_traffic import metrics
from vpn_sessions import local_sessions,disconnect_session
app=Flask(__name__);app.config['MAX_CONTENT_LENGTH']=4*1024*1024
KEY=os.environ.get('BEENY_AGENT_KEY','');LEGACY_PORT=int(os.environ.get('BEENY_LEGACY_AGENT_PORT','6200'))
ALLOWED={'tunnel','vpn-runtime','network-policy','set-crl','ack-traffic','bootstrap-openvpn','install-cert','delete-user','kill-user','set-user-state','sessions','disconnect-session','status-log','stats','set-speed-policy','speed-status'}
@app.before_request
def authorize():
    supplied=request.headers.get('Authorization','').removeprefix('Bearer ')
    if not KEY or not secrets.compare_digest(supplied,KEY):return jsonify(error='Unauthorized'),401
@app.route('/api/node/<method>',methods=['GET','POST'])
def api(method):
    if method not in ALLOWED:return jsonify(error='Unsupported endpoint'),404
    if method in {'status-log','stats'}:
        if request.method!='GET':return jsonify(error='Invalid method'),405
        status=subprocess.run(['systemctl','is-active','--quiet','openvpn-server@server'],timeout=5).returncode==0
        path=Path('/var/log/openvpn-status.log');age=time.time()-path.stat().st_mtime if path.exists() else None
        return jsonify(events=__import__('terminal_traffic').read_events(),success=True,status='online' if status else 'offline',vpn_active=status,status_age=age,log=path.read_text() if status and age is not None and age<90 else '',metrics=metrics(),agent_version='3.7.4',capabilities=['vpn-runtime-v1','network-policy-v4','network-policy-v3','network-policy-v2','network-policy-v1','monitoring-v1','host-traffic','set-user-state','sessions','disconnect-session','speed-policy'])
    if method=='speed-status':
        if request.method!='GET':return jsonify(error='Invalid method'),405
        import bandwidth
        return jsonify(success=not bandwidth.LAST_ERROR),503 if bandwidth.LAST_ERROR else 200
    data=request.get_json(silent=True) or {}
    if method=='tunnel':
        if request.method!='POST':return jsonify(error='Invalid method'),405
        try:return jsonify(__import__('tunnel_manager').handle(data.get('action'),data.get('data')))
        except ValueError as exc:return jsonify(success=False,message=str(exc)),400
        except Exception:
            app.logger.error('Tunnel operation failed')
            return jsonify(success=False,message='Tunnel operation failed. Check the tunnel journal.'),503
    if method=='vpn-runtime':
        if request.method!='POST':return jsonify(error='Invalid method'),405
        try:return jsonify(__import__('vpn_runtime').handle(data.get('action'),data.get('data'),data.get('revision')))
        except ValueError as exc:return jsonify(success=False,message=str(exc)),400
        except Exception:
            app.logger.exception('VPN listener change failed')
            return jsonify(success=False,message='Listener change failed. Check node logs; unconfirmed changes roll back.'),503
    if method=='network-policy':
        if request.method!='POST':return jsonify(error='Invalid method'),405
        try:return jsonify(__import__('network_policy').handle(data.get('action'),data.get('policy'),data.get('revision')))
        except ValueError as exc:return jsonify(success=False,error=str(exc)),400
        except Exception:
            app.logger.exception('Network policy operation failed')
            return jsonify(success=False,error='Network policy operation failed. Check node logs; pending changes roll back automatically.'),503
    if method=='set-crl':
        if request.method!='POST':return jsonify(error='Invalid method'),405
        try:return jsonify(__import__('crl_sync').install_crl(data.get('crl')))
        except Exception:return jsonify(success=False,error='CRL verification failed; check CA and core configuration'),409
    if method=='ack-traffic':
        if request.method!='POST':return jsonify(error='Invalid method'),405
        try:return jsonify(__import__('terminal_traffic').acknowledge(data.get('ids')))
        except ValueError:return jsonify(error='Invalid event acknowledgement'),400
    if method=='set-speed-policy':
        if request.method!='POST':return jsonify(error='Invalid method'),405
        try:
            import bandwidth
            return jsonify(bandwidth.set_policy(data.get('username'),data.get('names'),data.get('down'),data.get('up')))
        except Exception as exc:
            app.logger.error('Speed policy failure: %s; stderr=%s',type(exc).__name__,str(getattr(exc,'stderr','') or '')[:2000])
            app.logger.exception('Speed policy traceback')
            return jsonify(success=False,error='Speed policy failed. Check bridge logs and TUN support.'),503
    user=request.args.get('username','') if request.method=='GET' else data.get('username','')
    if method in {'set-user-state','sessions','disconnect-session','kill-user','delete-user'}:
        if not isinstance(user,str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}',user):return jsonify(error='Invalid account'),400
        try:
            if method=='sessions':return jsonify(success=True,sessions=local_sessions(user))
            if request.method!='POST':return jsonify(error='Invalid method'),405
            if method=='disconnect-session':disconnect_session(user,data.get('id'),data.get('fingerprint'));return jsonify(success=True)
            if method=='kill-user':
                for connection in local_sessions(user):disconnect_session(user,connection['id'],connection['fingerprint'])
                return jsonify(success=True)
            active=False if method=='delete-user' else data.get('active')
            if not isinstance(active,bool):return jsonify(error='Invalid state'),400
            path=Path('/etc/openvpn/ccd')/user
            if active:
                from vpn_sessions import enable_ccd
                enable_ccd(path)
            else:
                from vpn_sessions import disable_ccd
                disable_ccd(path)
                running=subprocess.run(['systemctl','is-active','--quiet','openvpn-server@server'],timeout=5).returncode==0
                if running:
                    for connection in local_sessions(user):disconnect_session(user,connection['id'],connection['fingerprint'])
            return jsonify(success=True)
        except Exception:return jsonify(success=False,error='Node operation failed. Check bridge service logs.'),503
    if request.method!='POST':return jsonify(error='Invalid method'),405
    # Only loopback forwarding to an already installed agent; no arbitrary URLs.
    try:
        session=requests.Session();session.trust_env=False
        response=session.post(f'http://127.0.0.1:{LEGACY_PORT}/api/node/{method}',json=data,headers={'Authorization':'Bearer '+KEY},timeout=15)
        return Response(response.content,status=response.status_code,content_type=response.headers.get('Content-Type','application/json'))
    except requests.RequestException:return jsonify(error='Legacy agent unavailable'),503
if __name__=='__main__':
    from waitress import serve
    if not KEY:raise SystemExit('Missing node API key.')
    import bandwidth
    bandwidth.start()
    serve(app,host='127.0.0.1',port=6201,threads=8)
