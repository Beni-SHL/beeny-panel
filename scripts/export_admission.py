#!/usr/bin/env python3
"""Run on the main VPS with its panel environment; transfer each private file to its node."""
import argparse,json,os,sys,re
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import app,db,Node,User,UserNode,devices
from admission import node_token
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('panel_url');p.add_argument('node_id',type=int);p.add_argument('output');args=p.parse_args()
    url=urlsplit(args.panel_url)
    if url.scheme!='https' or not url.hostname or url.username or url.query or url.fragment:p.error('Use the real HTTPS panel base URL including its path')
    with app.app_context():
        if not db.session.get(Node,args.node_id):p.error('Node does not exist')
        unsupported=[u.username for u in User.query.join(UserNode,UserNode.user_id==User.id).filter(UserNode.node_id==args.node_id) if not (1<=len(u.username)<=128 and u.username.isprintable() and not any(c in u.username for c in '/\\|'))]
        if unsupported:p.error('Legacy certificate names need a reviewed mapping before strict admission: '+', '.join(unsupported))
        fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as file:json.dump(dict(url=args.panel_url.rstrip('/')+'/api/vpn/admission',node_id=args.node_id,token=node_token(app.secret_key,args.node_id)),file)
    print('Private node admission file created. Transfer securely; never post its contents.')
