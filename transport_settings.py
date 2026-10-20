"""Authenticated per-node listener configuration and runtime profile endpoints."""
import json
from types import SimpleNamespace
from flask import abort, jsonify, render_template, request
from flask_login import current_user, login_required
import requests

def register(app, db, Node, features, panel_path, is_primary):
    base = panel_path.rstrip('/')
    from pathlib import Path
    version=(Path(__file__).parent/'VERSION').read_text().strip()
    @app.context_processor
    def version_context():return dict(panel_version=version)
    def call(node, action, data=None, revision=None):
        payload = dict(action=action, data=data, revision=revision)
        from privileged import enabled, call as privileged_call
        if is_primary(node):
            if enabled():result = privileged_call('vpn_runtime', **payload)
            else:result = __import__('vpn_runtime').handle(**payload)
        else:
            from cluster import node_url
            target = node_url(node)
            if not target.startswith('https://'):raise ValueError('Use the secured HTTPS node bridge first.')
            with requests.Session() as session:
                session.trust_env = False
                reply = session.post(target+'/api/node/vpn-runtime', json=payload,
                    headers={'Authorization': 'Bearer '+node.api_key}, timeout=(5,90))
                if reply.status_code == 404:raise ValueError('Update this node bridge to 3.7.0 before changing listeners.')
                result = reply.json()
        if not result.get('success'):raise ValueError(result.get('message', 'Node did not confirm its listener.'))
        return result

    api=SimpleNamespace(call=call)
    @app.get(base+'/settings/transports')
    @login_required
    def transports_page():
        if current_user.role != 'owner':abort(403)
        try:endpoints = json.loads(features.get_setting('vpn_client_endpoints','{}'))
        except ValueError:endpoints = {}
        return render_template('transports.html', panel_path=panel_path, nodes=Node.query.order_by(Node.name).all(), endpoints=endpoints)

    @app.post(base+'/api/settings/transports/<int:node_id>')
    @login_required
    def transports_action(node_id):
        if current_user.role != 'owner':abort(403)
        node = db.session.get(Node, node_id)
        if not node:abort(404)
        body = request.get_json(silent=True) or {}
        if not isinstance(body,dict):return jsonify(success=False,message='Invalid request.'),400
        try:
            action = body.get('action')
            if action not in {'status','apply','confirm','rollback'}:raise ValueError('Invalid listener action.')
            if action == 'apply' and body.get('accept_disconnect') is not True:
                raise ValueError('Acknowledge the VPN reconnect before applying.')
            host = body.get('host','')
            if not isinstance(host,str):raise ValueError('Enter a valid VPN address.')
            host=host.strip()
            if action == 'apply' and host:
                from speed_policy import endpoint
                endpoint(host,1)
            result = api.call(node, action, body.get('data'), body.get('revision'))
            if action in {'status','apply','confirm','rollback'}:
                values=json.loads(features.get_setting('vpn_client_endpoints','{}'))
                saved=values.setdefault(str(node.id),{})
                saved['managed']=True
                if action=='apply':saved['host']=host
                features.set_setting('vpn_client_endpoints',json.dumps(values));db.session.commit()
            return jsonify(result)
        except ValueError as exc:return jsonify(success=False,message=str(exc)),400
        except Exception:
            app.logger.exception('Transport operation failed on node %s',node_id)
            return jsonify(success=False,message='Could not verify this node listener. Check its helper/bridge logs.'),503
    return api
