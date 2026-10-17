"""Integer Toman pricing. Client totals are never accepted as payment prices."""
DEFAULT_PRICING = dict(enabled=False, base=0, per_gb=0, per_day=0, per_device=0)


def quote(policy, days, quota, devices):
    try:
        values = [str(value).strip() for value in (days, quota, devices)]
        if any(not value.isascii() or not value.isdigit() for value in values):
            raise ValueError
        days, quota, devices = map(int, values)
        if not (1 <= days <= 3650 and 1 <= quota <= 1000000 and 1 <= devices <= 100):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('زمان، حجم و تعداد دستگاه باید عدد صحیح و در محدوده مجاز باشند.') from None
    if not policy.get('enabled'):
        raise ValueError('سرویس سفارشی توسط مدیر فعال نشده است.')
    price = int(policy['base']) + quota*int(policy['per_gb']) + days*int(policy['per_day']) + (devices-1)*int(policy['per_device'])
    if not 1 <= price <= 1000000000:
        raise ValueError('قیمت این ترکیب معتبر نیست؛ ترکیب دیگری انتخاب کنید یا با مدیر تماس بگیرید.')
    return dict(id='custom', title=f'سفارشی · {days} روز · {quota} گیگ · {devices} دستگاه',
                days=days, quota=quota, devices=devices, price=price, pricing=dict(policy),
                quota_mode='metered',throttle_down_kbps=2000,throttle_up_kbps=2000)


def with_gift(plan, days=0, quota=0):
    """Add complimentary service without changing the server-calculated price."""
    amounts=[]
    for value,limit in ((days,3650),(quota,1000000)):
        text=str(value).strip()
        if not text.isascii() or not text.isdigit() or not 0<=int(text)<=limit:
            raise ValueError('Gift days and data must be non-negative integers within the service limits.')
        amounts.append(int(text))
    result=dict(plan)
    result['gift_days'],result['gift_quota']=amounts
    result['billable_days']=int(plan['days'])
    result['billable_quota']=int(plan['quota'])
    result['days']=int(plan['days'])+amounts[0]
    result['quota']=int(plan['quota'])+amounts[1] if int(plan['quota']) else 0
    if result['days']>3650 or result['quota']>1000000:
        raise ValueError('Total service including gifts exceeds the allowed limit.')
    return result


def service_allowance(plan):
    """Old invoices stay unchanged; snapshot gifts apply once at fulfillment."""
    if 'billable_days' in plan:return dict(plan)
    return with_gift(plan,plan.get('gift_days',0),plan.get('gift_quota',0))
