"""Owner-only network policy UI; the same fixed operation is supported by node bridges."""
from flask import abort,jsonify,render_template,request
from flask_login import current_user,login_required

def register(app,db,Node,panel_path,is_primary,privileged_enabled,privileged_call):
    base=panel_path.rstrip('/')
    @app.get(base+'/settings/network')
    @login_required
    def network_settings():
        if current_user.role!='owner':abort(403)
        return render_template('network_settings.html',nodes=Node.query.order_by(Node.name).all(),panel_path=panel_path)
    @app.post(base+'/api/settings/network/iran-prefixes')
    @login_required
    def iran_network_prefixes():
        if current_user.role!='owner':abort(403)
        try:
            from iran_network import retrieve
            return jsonify(success=True,**retrieve(app.instance_path))
        except Exception:
            app.logger.exception('Iran resource retrieval failed')
            return jsonify(success=False,message='Iran resource source is unavailable. Paste a verified CIDR list instead.'),503
    @app.post(base+'/api/settings/network/<int:node_id>')
    @login_required
    def network_policy_action(node_id):
        if current_user.role!='owner':abort(403)
        node=db.get_or_404(Node,node_id)
        data=request.get_json(silent=True) or {}
        action=data.get('action')
        if action not in {'status','preview','apply','confirm','rollback','activate-routes','warp-status','warp-install','warp-remove'}:return jsonify(success=False,message='Invalid policy action.'),400
        try:
            if is_primary(node):
                args=dict(action=action,policy=data.get('policy'),revision=data.get('revision'))
                if privileged_enabled():result=privileged_call('network_policy',**args)
                else:
                    from privileged_server import dispatch
                    result=dispatch('network_policy',args)
            else:
                import requests
                from cluster import node_url
                target=node_url(node)
                if not target.startswith('https://'):raise ValueError('Use the secured HTTPS bridge before changing remote network rules.')
                with requests.Session() as session:
                    session.trust_env=False
                    capability=session.get(target+'/api/node/stats',headers={'Authorization':'Bearer '+node.api_key},timeout=(5,10))
                    if not capability.ok or 'network-policy-v4' not in capability.json().get('capabilities',[]):raise ValueError('Update the secured node bridge to 3.6.9 before using these network policies.')
                    reply=session.post(target+'/api/node/network-policy',json=data,headers={'Authorization':'Bearer '+node.api_key},timeout=(5,90))
                result=reply.json()
                if not reply.ok:return jsonify(success=False,message=result.get('error','The node does not support network policies. Update its secured bridge.')),409
            return jsonify(result)
        except ValueError as exc:return jsonify(success=False,message=str(exc)),400
        except Exception:
            app.logger.exception('Network policy action failed on node %s',node_id)
            message='Network operation failed. Check the selected node logs. Unconfirmed changes roll back automatically.'
            if action=='activate-routes':message='VPN restart did not pass its health check. Inspect the OpenVPN journal on this node before retrying.'
            elif action.startswith('warp-'):message='WARP package operation could not be completed or queued. Check the node job journal.'
            return jsonify(success=False,message=message),503

    @app.post(base+'/api/settings/maintenance')
    @login_required
    def maintenance_action():
        if current_user.role!='owner':abort(403)
        data=request.get_json(silent=True) or {}
        if data.get('action') not in {'status','bbr-enable','bbr-restore','panel-restart'}:return jsonify(success=False,message='Invalid maintenance action.'),400
        try:
            if privileged_enabled():result=privileged_call('maintenance',action=data['action'])
            else:
                from privileged_server import dispatch
                result=dispatch('maintenance',dict(action=data['action']))
            return jsonify(result)
        except ValueError as exc:return jsonify(success=False,message=str(exc)),400
        except Exception:
            app.logger.exception('Maintenance action failed')
            return jsonify(success=False,message='Maintenance failed. Check the helper journal.'),503
