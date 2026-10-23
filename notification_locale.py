"""Translate product-generated notifications; customer-authored text stays untouched."""
import re
TITLES={
'Account created':'حساب ساخته شد','Account updated':'حساب به‌روزرسانی شد','New renewal request':'درخواست تمدید جدید',
'Wallet credited':'کیف پول شارژ شد','Renewal approved':'تمدید تأیید شد','Renewal request deleted':'درخواست تمدید حذف شد',
'درخواست تمدید ثبت شد':'Renewal request submitted','اطلاعات حساب تغییر کرد':'Account details updated',
'کیف پول شما شارژ شد':'Your wallet was credited','تمدید شما انجام شد':'Your subscription was renewed',
'درخواست حذف شد':'Request deleted','اعتبار حساب رو به پایان است':'Subscription expires soon','حجم حساب رو به پایان است':'Data allowance running low'}
TITLES.update({'Node recovered':'نود دوباره در دسترس است','Node unavailable':'نود در دسترس نیست','New support ticket':'تیکت پشتیبانی جدید','Support reply':'پاسخ پشتیبانی',
'Representative renewal':'تمدید توسط نماینده','Representative debt paid':'بدهی نماینده پرداخت شد','Commission settlement requested':'درخواست تسویه پورسانت','Commission sale awaiting payment review':'فروش در انتظار بررسی پرداخت',
'حساب شما تمدید شد':'Your account was renewed','تمدید انجام شد':'Renewal completed','حساب نمایندگی ساخته شد':'Representative account created','اعتبار سفارش بازگشت داده شد':'Order credit returned',
'پاسخ پشتیبانی':'Support reply','پورسانت فروش ثبت شد':'Sales commission recorded','اکانت شما آماده است':'Your account is ready','سفارش فروش جدید':'New sales order',
'تسویه پورسانت پرداخت شد':'Commission settlement paid','درخواست تسویه رد شد':'Settlement request rejected','پرداخت سرویس برگشت داده شد':'Service payment refunded','اصلاح پورسانت فروش':'Sales commission adjusted',
'سفارش فروش تأیید نشد':'Sales order not approved','وجه سفارش ناموفق برگشت داده شد':'Failed order refunded','اشتراک موقتاً متوقف شد':'Subscription temporarily paused','محدودیت نمایندگی برداشته شد':'Representative restriction lifted',
'پرداخت بدهی تأیید شد':'Debt payment approved','بدهی از درآمد تمدید پرداخت شد':'Debt repaid from renewal income','موجودی کیف پول تغییر کرد':'Wallet balance changed'})
EXACT={
'رسید شما دریافت شد و منتظر بررسی مدیر است.':'Your receipt was received and is awaiting review.',
'مصرف دوره صفر شد؛ تاریخچه مصرف حفظ شده است.':'Period usage was reset; usage history was preserved.',
'اعتبار زمانی':'Expiry date','حجم مجاز':'Data allowance','تعداد دستگاه':'Device limit','وضعیت حساب':'Account status','توقف شخصی':'Personal pause',
'فعال':'Active','محدودشده':'Restricted','متوقف':'Paused','توقف برداشته شد':'Resumed','نامحدود':'Unlimited'}
EXACT.update({'پرداخت تأیید و سرویس فعال شد؛ کانفیگ را از پروفایل دریافت کنید.':'Payment approved and service activated. Download your configuration from your profile.',
'برای وضعیت سرویس با مدیر تماس بگیرید.':'Contact the administrator about your service status.',
'اشتراک شما به علت پرداخت نکردن بدهی نماینده قطع شده است. برای پیگیری با پشتیبانی تماس بگیرید.':'Your subscription is paused because your representative has unpaid debt. Contact support.',
'اشتراک‌های این نماینده توسط مدیر تعلیق شده‌اند. برای پیگیری با پشتیبانی تماس بگیرید.':'This representative was suspended by the administrator. Contact support.',
'بدهی یا محدودیت نماینده تعیین تکلیف شد؛ اتصال با رعایت اعتبار و وضعیت حساب شما بازگردانده می‌شود.':'The representative restriction was resolved. Access resumes subject to account status and allowance.'})
PATTERNS=[
(r'(.+): ticket #(\d+)',r'\1: تیکت #\2'),
(r'Node #(\d+): (.*)',r'نود #\1: \2'),
(r'(.+) renewed by representative #(\d+)\.',r'حساب \1 توسط نماینده #\2 تمدید شد.'),
(r'Representative #(\d+): ([\d,]+) Toman principal repaid; excess ([\d,]+)\.',r'نماینده #\1: مبلغ \2 تومان از بدهی پرداخت شد؛ اضافه پرداخت \3 تومان.'),
(r'Representative #(\d+) · ([\d,]+) Toman · settlement #(\d+)',r'نماینده #\1 · \2 تومان · تسویه #\3'),
(r'(.+) · ([\d,]+) Toman · representative #(\d+)',r'\1 · \2 تومان · نماینده #\3'),
(r'(.+) was added to the panel\.',r'حساب \1 به پنل اضافه شد.'),
(r'(.+): account settings were changed\.',r'\1: تنظیمات حساب تغییر کرد.'),
(r'(.+) submitted a receipt\. Review it in the renewal inbox\.',r'\1 رسید فرستاد. آن را در صندوق تمدید بررسی کنید.'),
(r'Request #(\d+) renewed (.+)\.',r'درخواست #\1 حساب \2 را تمدید کرد.'),
(r'Request #(\d+) and its receipt were deleted\.',r'درخواست #\1 و رسید آن حذف شد.'),
(r'Request #(\d+): ([\d,]+) Toman credited to (.+)\.',r'درخواست #\1: مبلغ \2 تومان به کیف پول \3 اضافه شد.')]
def translate_notification(title,body,language):
    if language=='fa':
        translated=TITLES.get(title,title) if title.isascii() else title
        for pattern,replacement in PATTERNS:
            if re.fullmatch(pattern,body):return translated,re.sub(pattern,replacement,body)
        return translated,body
    translated=TITLES.get(title,title) if not title.isascii() else title
    if body in EXACT:return translated,EXACT[body]
    patterns=[
      (r'([\d.]+) روز از اعتبار شما باقی مانده است\.',r'Your subscription expires in \1 days.'),
      (r'([\d.]+) گیگابایت باقی مانده است\.',r'\1 GB remaining.'),
      (r'درخواست #(\d+) و تصویر رسید توسط مدیر حذف شد\. برای پیگیری با پشتیبانی تماس بگیرید\.',r'Request #\1 and its receipt were removed by the administrator. Contact support for details.'),
      (r'([\d,]+) تومان پس از تأیید رسید #(\d+) به موجودی اضافه شد\. اکنون می‌توانید سرویس را از کیف پول تمدید کنید\.',r'\1 Toman was credited after receipt #\2 was approved. You can now renew using your wallet.'),
      (r'درخواست #(\d+) تأیید شد: (\d+) روز و ([\d.]+) گیگابایت اضافه شد\. توقف شخصی شما، در صورت فعال بودن، حفظ شده است\.',r'Request #\1 approved: \2 days and \3 GB added. Your personal pause setting was preserved.')]
    for pattern,replacement in patterns:
        if re.fullmatch(pattern,body):return translated,re.sub(pattern,replacement,body)
    other_patterns=[
      (r'پاسخ تیکت «(.*)» در بخش پشتیبانی آماده است\.',r'A reply to ticket “\1” is ready in Support.'),
      (r'(\d+) روز و ([\d.]+) گیگابایت اضافه شد؛ مصرف قبلی حفظ شده است\.',r'\1 days and \2 GB were added; previous usage was preserved.'),
      (r'(.+) · ([\d,]+) تومان از کیف پول کسر شد\.',r'\1 · \2 Toman paid from your wallet.'),
      (r'سفارش #(\d+) لغو شد؛ ([\d,]+) تومان برگشت داده شد\.',r'Order #\1 cancelled; \2 Toman returned.'),
      (r'(.+) · ([\d,]+) تومان؛ آماده درخواست تسویه\.',r'\1 · \2 Toman; ready for settlement.'),
      (r'(.+) · در انتظار تأیید پرداخت مدیر',r'\1 · Awaiting payment approval.'),
      (r'درخواست #(\d+) · ([\d,]+) تومان',r'Request #\1 · \2 Toman'),
      (r'(.+) · برگشت وجه ثبت شد؛ سهم این سفارش اصلاح شد\.',r'\1 · Refund recorded; order commission adjusted.'),
      (r'([\d,]+) تومان از درآمد قابل برداشت برای کاهش بدهی استفاده شد\.',r'\1 Toman of withdrawable income was used to reduce debt.'),
      (r'([\d,]+) تومان از بدهی کم شد و اعتبار فروش برگشت داده شد\.(?: اضافه پرداخت ([\d,]+) تومان به کیف پول نقدی شما رفت\.)?',lambda m:f'{m[1]} Toman repaid; sales credit restored.'+(f' Excess {m[2]} Toman credited to your wallet.' if m[2] else '')),
      (r'([+\-\d,]+) تومان · (.*)',r'\1 Toman · \2'),
      (r'(.+) · ([\d,]+) تومان',r'\1 · \2 Toman')]
    for pattern,replacement in other_patterns:
        if re.fullmatch(pattern,body):return translated,re.sub(pattern,replacement,body)
    if title=='اطلاعات حساب تغییر کرد':
        lines=[]
        for line in body.splitlines():
            label,separator,value=line.partition(': ')
            if separator and label in EXACT:lines.append(EXACT[label]+': '+EXACT.get(value,re.sub(r' گیگابایت$', ' GB',value)))
            else:lines.append(EXACT.get(line,line))
        body='\n'.join(lines)
    return translated,body
