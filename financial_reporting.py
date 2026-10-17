"""SQL-aggregated UTC sales, receipts, refunds and commission; never mix them."""
from datetime import datetime
from sqlalchemy import case,and_,or_,func

def report(db,query,Invoice,Receipt,commissions,features,now):
    months=[]
    for offset in range(11,-1,-1):
        year,month=divmod(now.year*12+now.month-1-offset,12)
        months.append(dict(month=f'{year:04d}-{month+1:02d}',direct=0,representative=0,debt=0,total=0,count=0,unpaid=0,cash=0,refund=0,commission=0,payouts=0))
    first=datetime.strptime(months[0]['month'],'%Y-%m');end=datetime(now.year+int(now.month==12),now.month%12+1,1)
    buckets={m['month']:m for m in months}
    safe=case((func.json_valid(Invoice.snapshot)==1,Invoice.snapshot),else_='{}')
    rep=or_(func.json_extract(safe,'$.commission_reseller').notin_([0,'']),func.json_extract(safe,'$.representative_id').is_not(None),Invoice.source_reference.like('reseller:%'),Invoice.source_reference.like('reseller-renew:%'),Invoice.source_reference.like('commission:%'))
    category=case((rep,'representative'),else_='direct')
    month=func.strftime('%Y-%m',Invoice.created_at)
    grouped=query.with_entities(month,category,func.sum(Invoice.amount),func.count(Invoice.id),func.sum(case((Invoice.payment_state=='unpaid',Invoice.amount),else_=0)),func.sum(Invoice.commission)).filter(Invoice.created_at>=first,Invoice.created_at<end).group_by(month,category).all()
    for key,channel,amount,count,unpaid,commission in grouped:
        row=buckets[key];row[channel]+=amount or 0;row['count']+=count;row['unpaid']+=unpaid or 0;row['commission']+=commission or 0
    from flask_login import current_user
    if current_user.role!='seller':
        for key,channel,amount in db.session.query(func.strftime('%Y-%m',Receipt.created_at),Receipt.channel,func.sum(Receipt.amount)).filter(Receipt.created_at>=first,Receipt.created_at<end).group_by(func.strftime('%Y-%m',Receipt.created_at),Receipt.channel):
            buckets[key]['cash']+=amount
            if channel=='principal':buckets[key]['debt']+=amount
        # Each bank refund is an outflow once, including initial sale refunds.
        for key,amount in db.session.query(func.strftime('%Y-%m',commissions.Refund.created_at),func.sum(commissions.Refund.amount)).filter(commissions.Refund.created_at>=first,commissions.Refund.created_at<end).group_by(func.strftime('%Y-%m',commissions.Refund.created_at)):
            buckets[key]['refund']+=amount
    if current_user.role!='seller':
        for key,amount in db.session.query(func.strftime('%Y-%m',commissions.Settlement.paid_at),func.sum(commissions.Settlement.amount)).filter(commissions.Settlement.state=='paid',commissions.Settlement.paid_at>=first,commissions.Settlement.paid_at<end).group_by(func.strftime('%Y-%m',commissions.Settlement.paid_at)):
            buckets[key]['payouts']+=amount
    for row in months:
        row['total']=row['cash']-row['refund']
        row['sales']=row['direct']+row['representative']
        row['after_payouts']=row['total']-row['payouts']
    maximum=max(1,max(abs(row[key]) for row in months for key in ('direct','representative','total')))
    for row in months:
        for key in ('direct','representative','debt','total'):
            row[key+'_height']=abs(row[key])*100/maximum
    return months
