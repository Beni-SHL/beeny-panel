"""Owner-only tunnel pairing UI and separately authorized profile endpoints."""
import json
from types import SimpleNamespace
from flask import abort,jsonify,render_template,request
from flask_login import current_user,login_required
import requests

def register(app,db,Node,features,panel_path,is_primary):
    base=panel_path.rstrip('/')
    def call(node,action,data=None):
        from privileged import enabled,call as privileged_call
        if is_primary(node):
            if enabled():result=privileged_call('tunnel',action=action,data=data)
            else:result=__import__('tunnel_manager').handle(action,data)
        else:
            from cluster import node_url
            target=node_url(node)
            if not target.startswith('https://'):raise ValueError('Use the secured HTTPS node bridge first.')
            with requests.Session() as session:
                session.trust_env=False
                reply=session.post(target+'/api/node/tunnel',json=dict(action=action,data=data),headers={'Authorization':'Bearer '+node.api_key},timeout=(5,75))
                if reply.status_code==404:raise ValueError('Update this node bridge to 3.7.0 before pairing tunnels.')
                result=reply.json()
        if not result.get('success'):raise ValueError(result.get('message','Tunnel operation failed.'))
        return result
    def configured(node_id):
        try:return str(node_id) in json.loads(features.get_setting('vpn_tunnel_nodes','[]'))
        except ValueError:return False
    def account_nodes(user):
        from app import UserNode
        ids={relation.node_id for relation in UserNode.query.filter_by(user_id=user.id).all()}
        return [node for node in Node.query.filter(Node.id.in_(ids)).order_by(Node.name).all() if configured(node.id)] if ids else []
    api=SimpleNamespace(call=call,configured=configured)
    @app.context_processor
    def context():return dict(node_has_tunnel=configured,account_tunnel_nodes=account_nodes)
    @app.get(base+'/settings/tunnels')
    @login_required
    def tunnels_page():
        if current_user.role!='owner':abort(403)
        return render_template('tunnels.html',panel_path=panel_path,nodes=Node.query.order_by(Node.name).all())
    @app.post(base+'/api/settings/tunnels/<int:node_id>')
    @login_required
    def tunnels_action(node_id):
        if current_user.role!='owner':abort(403)
        node=db.session.get(Node,node_id)
        if not node:abort(404)
        body=request.get_json(silent=True) or {}
        if not isinstance(body,dict):return jsonify(success=False,message='Invalid request.'),400
        action=body.get('action')
        if action not in {'status','entry','pair','export','enable','disable'}:return jsonify(success=False,message='Invalid tunnel action.'),400
        try:
            result=api.call(node,action,body.get('data'))
            if action in {'pair','enable','disable','entry'}:
                ids=set(json.loads(features.get_setting('vpn_tunnel_nodes','[]')))
                if result.get('enabled') and result.get('role')=='exit':ids.add(str(node.id))
                else:ids.discard(str(node.id))
                features.set_setting('vpn_tunnel_nodes',json.dumps(sorted(ids)));db.session.commit()
                # Paired downloads always read the actual listener, even on previously legacy nodes.
                endpoints=json.loads(features.get_setting('vpn_client_endpoints','{}'))
                saved=endpoints.setdefault(str(node.id),{})
                if result.get('role')=='exit':saved['managed']=True
                features.set_setting('vpn_client_endpoints',json.dumps(endpoints));db.session.commit()
            response=jsonify(result);response.headers['Cache-Control']='no-store';return response
        except ValueError as exc:return jsonify(success=False,message=str(exc)),400
        except Exception:
            # Never log invitation/token payloads.
            app.logger.error('Tunnel operation %s failed on node %s',action,node_id)
            return jsonify(success=False,message='Tunnel operation failed. Check the selected node tunnel journal.'),503
    return api
