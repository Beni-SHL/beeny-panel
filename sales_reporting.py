"""Legacy pure summary retained only for compatibility tests; production uses financial_reporting."""
from sales_engine import category

def summarize(invoices, refunds, payments, now):
    months=[]
    for offset in range(11,-1,-1):
        year,month=divmod(now.year*12+now.month-1-offset,12)
        months.append(dict(month=f'{year:04d}-{month+1:02d}',direct=0,representative=0,debt=0,total=0))
    buckets={x['month']:x for x in months};references={}
    for row in invoices:
        channel=category(row.snapshot,row.source_reference);references[row.source_reference]=channel
        bucket=buckets.get(row.created_at.strftime('%Y-%m'))
        if bucket:bucket[channel]+=row.amount
    for row in refunds:
        channel=references.get(row['reference']);bucket=buckets.get(row['date'].strftime('%Y-%m'))
        if bucket and channel:bucket[channel]-=row['amount']
    for row in payments:
        bucket=buckets.get(row['date'].strftime('%Y-%m'))
        if bucket:bucket['debt']+=row['amount']
    maximum=max(1,max(abs(x[k]) for x in months for k in ('direct','representative','debt')))
    for bucket in months:
        bucket['total']=sum(bucket[k] for k in ('direct','representative','debt'))
        for key in ('direct','representative','debt'):bucket[key+'_height']=abs(bucket[key])*100/maximum
    return months
