"""Serialize new account mutations against identity removal.
The conditional UPDATE acquires the same database write lock as deletion before
an order/receipt can be created; it does not reset usage, dates or access.
"""
from flask import abort
from sqlalchemy import update

def claim(db,User,uid):
    changed=db.session.execute(update(User).where(User.id==uid,User.removal_pending.is_(False)).values(removal_pending=False),execution_options={'synchronize_session':False}).rowcount
    if changed!=1:
        db.session.rollback()
        abort(409,'Account removal is in progress. Contact the administrator before creating a new request.')
