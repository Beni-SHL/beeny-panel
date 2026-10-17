"""Trim only excess connections; retain the oldest account sessions across nodes."""
import requests
import time

# 240-second server keepalive timeout plus one reconciliation margin.
RECONNECT_GRACE_SECONDS = 270
_RECONNECT_WINDOWS = {}

def enforce(user,nodes,names,is_primary,local_get,local_kill,guard=None):
    from cluster import node_url
    sessions=[];errors=[]
    for node in nodes:
        try:
            for name in names:
                if is_primary(node):rows=local_get(name)
                else:
                    r=requests.get(node_url(node)+'/api/node/sessions',params={'username':name},headers={'Authorization':'Bearer '+node.api_key},timeout=(2,3));r.raise_for_status();data=r.json()
                    if not data.get('success'):raise RuntimeError('Unconfirmed node snapshot')
                    rows=data['sessions']
                for row in rows:sessions.append((node,name,row))
        except Exception:errors.append(node.id)
    # Never evict on an incomplete global snapshot. Retry when all nodes answer.
    if errors:return errors
    sessions.sort(key=lambda item:(int(item[2].get('connected_epoch') or 0),item[0].id,int(item[2]['id'])))
    kept=sessions[:max(1,user.max_devices)]
    protected=[r['address'] for _,_,r in kept if not guard.blocked(user.id,r['address'])] if guard else []
    excess=sessions[max(1,user.max_devices):]
    if guard:
        excess+=[x for x in kept if guard.blocked(user.id,x[2]['address'])]
    now = time.time()
    signature = tuple((n.id, nm, r["fingerprint"]) for n, nm, r in kept)
    cache_key = getattr(user, "id", None)
    window = _RECONNECT_WINDOWS.get(cache_key)
    if excess and (not window or window[0] != signature):
        starts = [int(r.get("connected_epoch") or 0) for _, _, r in excess]
        start = min([now] + [x for x in starts if 0 < x <= now])
        window = (signature, start)
        _RECONNECT_WINDOWS[cache_key] = window
    if not excess:
        _RECONNECT_WINDOWS.pop(cache_key, None)
    for node,name,row in excess:
        banned = bool(guard and guard.blocked(user.id, row["address"]))
        since = int(row.get("connected_epoch") or 0)
        # A stale TCP session can survive until ping-restart. Do not repeatedly
        # kill its fresh replacement while that timeout is still running.
        # This is a bounded grace period, not proof of device identity.
        if not banned and since > 0 and 0 <= now - since < RECONNECT_GRACE_SECONDS and window and now - window[1] < RECONNECT_GRACE_SECONDS:
            continue
        if guard:
            guard.record(user.id,row['address'],str(node.id)+'|'+row['fingerprint'],protected)
        import logging
        logging.warning('VPN session removal account_id=%s node_id=%s session_id=%s reason=connection_limit_or_peer_ban',getattr(user,'id','unknown'),node.id,row['id'])
        try:
            if is_primary(node):local_kill(name,row['id'],row['fingerprint'])
            else:
                r=requests.post(node_url(node)+'/api/node/disconnect-session',json={'username':name,'id':row['id'],'fingerprint':row['fingerprint']},headers={'Authorization':'Bearer '+node.api_key},timeout=(2,3));r.raise_for_status()
                if not r.json().get('success'):raise RuntimeError('Disconnect not confirmed')
        except ValueError:pass # Stale session already disconnected; no username fallback.
        except Exception:errors.append(node.id)
    return errors
