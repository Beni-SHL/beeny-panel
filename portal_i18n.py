"""Translate rendered customer UI without altering markup, scripts or private user content."""
import re
from html.parser import HTMLParser
from flask import request, session

PAIRS = '''بنی پنل|Beeny Panel
سلام،|Hello,
به فضای خودت خوش آمدی|Welcome to your space
همه‌چیز برای اتصال راحت، همین‌جاست.|Everything you need for a smooth connection.
حساب شخصی شما|Your personal account
فضای شخصی شما|Your personal space
فضای من|MY SPACE
حساب من|My account
حساب کاربری|Account
نمای کلی|Overview
مصرف و اعتبار|Usage & allowance
فایل‌های اتصال|Connection files
تمدید سرویس|Renew service
اتصال‌های فعال|Active connections
راهنمای نصب|Installation guide
همراه شما هستیم|We are here for you
برای راهنمایی، با پشتیبانی تماس بگیرید.|Contact support if you need a hand.
ارتباط با پشتیبانی|Contact support
موجودی کیف پول|Wallet balance
افزایش موجودی +|Add funds +
تغییر عکس پروفایل|Change profile photo
انتخاب عکس پروفایل|Choose profile photo
ذخیره عکس|Save photo
کنترل اتصال حساب|Connection control
توقف اتصال؛ اعتبار زمانی ادامه دارد.|Pause connection; account validity continues.
تأیید نودها در حال پیگیری است.|Waiting for node confirmation.
فعال‌بودن اتصال حساب|Account connection enabled
حساب محدود|Restricted account
متوقف|Paused
فعال|Active
آنلاین|Online
آفلاین|Offline
مصرف دوره فعلی|Current period usage
حجم باقی‌مانده|Remaining data
اعتبار باقی‌مانده|Remaining validity
دستگاه‌های همزمان|Concurrent devices
حساب فعال|Active account
نامحدود|Unlimited
بیش از حد مجاز مصرف شده|Data allowance exceeded
آماده برای استفاده|Ready to use
گیگابایت|GB
دستگاه همزمان|concurrent devices
تومان|Toman
روز اعتبار|days validity
روز|days
از|of
توازن مصرف|Data balance
باقی‌مانده|Remaining
مصرف‌شده|Used
تصویر واضح از مصرف شما|Your usage at a glance
روند مصرف روزانه|Daily usage
مصرف واقعی|Actual usage
مصرف امروز|Today’s usage
برای دیدن تاریخ و مقدار مصرف، روی نمودار بزنید.|Select a chart bar to see its date and usage.
مشاهده داده‌های نمودار|View chart data
گیگابایت در بازه انتخابی|GB in selected period
هنوز مصرفی برای این بازه ثبت نشده است. پس از استفاده از VPN، نمودار اینجا نمایش داده می‌شود.|No usage in this period yet. Your chart appears after using the VPN.
مصرف ثبت‌شده؛ حتی پس از تمدید و صفر شدن دوره حفظ می‌شود. روزها بر مبنای UTC هستند.|Historical usage is retained after renewals and period resets. Days use UTC.
کانفیگ‌های شما|Your configurations
یک کلیک تا اتصال|One click to connect
کانفیگ چندموقعیتی|Multi-location profile
همه موقعیت‌ها|All locations
دانلود کانفیگ|Download configuration
هنوز موقعیتی برای حساب شما تعیین نشده است.|No location has been assigned to your account yet.
حساب شما، همیشه همراهتان|YOUR ACCOUNT ON THE GO
حسابت همیشه همراهت|Your account, always with you
حجم و اعتبار را ببینید، کانفیگ بگیرید و رسید تمدید را مستقیم از ربات ارسال کنید.|Check usage and validity, download profiles and send renewal receipts through the bot.
اتصال به تلگرام|Connect Telegram
اتصال دوباره به تلگرام|Reconnect Telegram
ربات هنوز توسط مدیر فعال نشده است.|The administrator has not enabled the bot yet.
اتصال با لینک یک‌بارمصرف؛ حساب مدیریت در دسترس شما قرار نمی‌گیرد.|Connect using a one-time link. Your connection never grants admin access.
حساب متصل است|Account linked
اتصال سریع و خصوصی|Quick, private connection
ادامه یک تجربه روان|KEEP THE CONNECTION GOING
سرویس خود را انتخاب کنید|Choose your service
قیمت‌ها به تومان|Prices in Toman
انتخاب سرویس تمدید|Choose a renewal plan
انتخاب محبوب|Popular choice
حد مصرف منصفانه|Fair-use allowance
٪ تخفیف|% off
سرویس دلخواه خود را بسازید|Build your own plan
زمان، حجم و تعداد دستگاه همزمان را انتخاب کنید. مبلغ نهایی هنگام ثبت درخواست توسط سرور محاسبه می‌شود.|Choose days, data and concurrent devices. The server calculates your final price when submitting.
اعتبار (روز)|Validity (days)
حجم (گیگابایت)|Data (GB)
اطلاعات واریز|Payment information
مبلغ قابل پرداخت|Amount due
مبلغ سرویس انتخابی را به کارت زیر واریز کنید.|Transfer the selected plan price to the card below.
کارت به کارت|Bank transfer
کپی شماره کارت فعلی|Copy visible card number
با فلش‌ها یا کشیدن کارت، بین کارت‌ها جابه‌جا شوید. دکمهٔ کپی، شمارهٔ کارتِ همین اسلاید را کپی می‌کند.|Use the arrows or swipe to browse cards. Copy uses the currently visible card.
بعد از واریز، تصویر رسید را ارسال کنید|Upload your receipt after transferring
کد تخفیف (اختیاری)|Discount code (optional)
بررسی کد|Check code
نام پرداخت‌کننده|Payer name
شماره تماس یا آیدی تلگرام|Phone number or Telegram username
برای انتخاب عکس رسید کلیک کنید|Choose receipt image
تصویر رسید واریز|Transfer receipt image
JPG، PNG یا WebP · حداکثر ۲۰ مگابایت|JPG, PNG or WebP · up to 20 MB
توضیح (اختیاری)|Note (optional)
ثبت درخواست و ارسال رسید|Submit request & receipt
رسید همراه مشخصات حساب برای مدیر ارسال می‌شود.|Your receipt and account details are sent to the administrator.
«نامحدود» با حد مصرف منصفانه پلن ارائه می‌شود. آپلود رسید به معنای تأیید پرداخت نیست؛ مدیر واریز را بررسی می‌کند.|Unlimited plans include the stated fair-use allowance. A receipt does not confirm payment; the administrator reviews the transfer.
پیگیری درخواست‌های شما|Track your requests
درخواست #|Request #
در انتظار بررسی|Awaiting review
تمدید انجام شد|Renewed
رد شده|Rejected
شروع ساده روی هر دستگاه|GET STARTED ON ANY DEVICE
برنامه را نصب کنید، متصل شوید|Install the app and connect
اندروید|Android
آیفون و آیپد|iPhone & iPad
ویندوز و مک|Windows & macOS
لینوکس|Linux
OpenVPN Connect را از Google Play نصب کنید.|Install OpenVPN Connect from Google Play.
OpenVPN Connect را از App Store نصب کنید.|Install OpenVPN Connect from the App Store.
فایل کانفیگ را دانلود کنید و در برنامه Import Profile → File را انتخاب کنید.|Download your profile and select Import Profile → File in the app.
مجوز ساخت VPN را تأیید کنید و اتصال را روشن کنید.|Allow the VPN permission and enable the connection.
فایل کانفیگ را در Files ذخیره کنید.|Save your profile in Files.
داخل برنامه Import Profile → File را بزنید، فایل را انتخاب و Add کنید.|In the app select Import Profile → File, choose your file and tap Add.
کلید اتصال را روشن کنید و مجوز VPN را تأیید کنید.|Enable the connection switch and allow VPN access.
نسخه رسمی OpenVPN Connect را نصب کنید.|Install the official OpenVPN Connect app.
در برنامه Import Profile → File را بزنید و فایل را وارد کنید.|Select Import Profile → File and import your profile.
فایل را وارد و پروفایل را فعال کنید.|Import the file and activate the profile.
دانلود برای مک و لینوکس ↗|Download for macOS & Linux ↗
راهنمای رسمی OpenVPN برای لینوکس|Official OpenVPN guide for Linux
استفاده کنید. پس از نصب کلاینت، فایل کانفیگ همین حساب را وارد کنید.|After installing the client, import this account’s profile.
کنارت هستیم|WE ARE HERE FOR YOU
چطور کمکت کنیم؟|How can we help?
سؤالت را بپرس؛ پاسخ‌ها در گفت‌وگوی خصوصی تو می‌مانند.|Ask a question; replies stay in your private conversation.
＋ تیکت جدید|＋ New ticket
گفت‌وگوهای من ↗|My conversations ↗
یک پیام تا راه‌حل|ONE MESSAGE CLOSER TO A SOLUTION
با خیال راحت بپرس|Ask with confidence
هر موضوع، یک گفت‌وگوی خصوصی؛ پاسخ‌ها را همین‌جا دنبال کن.|One private conversation per topic. Follow replies here.
تیکت جدید|New ticket
موضوع را کوتاه بنویس و جزئیات مشکل را در پیام توضیح بده.|Use a short subject and describe your issue in the message.
موضوع|Subject
پیام شما|Your message
گفت‌وگوی خصوصی · تا ۳۰۰۰ کاراکتر|Private conversation · up to 3,000 characters
ارسال تیکت ←|Send ticket →
بازگشت به پیام‌ها|Back to conversations
پشتیبانی|Support
ارسال پاسخ|Send reply
کیف پول|Wallet
افزایش موجودی|Add funds
مبلغ دلخواه را به تومان وارد کنید.|Enter your desired amount in Toman.
مبلغ شارژ (تومان)|Top-up amount (Toman)
نام و نام خانوادگی|Full name
اطلاعات واریز هنوز ثبت نشده است؛ با پشتیبانی تماس بگیرید.|Payment details are not configured yet. Contact support.
ثبت رسید و درخواست شارژ|Submit receipt & top-up request
ثبت رسید به معنای شارژ فوری نیست؛ مدیر ابتدا واریز را بررسی می‌کند.|Submitting a receipt does not add funds immediately. The administrator reviews it first.
درخواست‌های شارژ|Top-up requests
توضیح اختیاری|Optional note
واریز و رسید|Transfer & receipt
مبلغ واریز|Transfer amount
مبلغ|Amount
کیف پول و درخواست‌ها|Wallet & requests
بازگشت به حساب|Back to account
مبلغ را به کارت نمایش‌داده‌شده واریز کنید و تصویر رسید را بفرستید.|Transfer to the visible card and upload your receipt.
نمایندگی من|My reseller workspace
نمایندگی|Reseller
نمایندگی بنی|Beeny reseller
فضای کاری نمایندگی|RESELLER WORKSPACE
خرید و تمدید از موجودی|Buy & renew from wallet
پلن آماده بخر یا سرویس دلخواه بساز؛ حساب‌هایت را از موجودی تمدید کن.|Buy a preset or create a custom plan. Renew accounts using your wallet.
ساخت حساب|Create account
نام کاربری|Username
رمز صفحهٔ کاربر|Customer portal password
✦ ساخت رمز|✦ Generate password
◉ نمایش|◉ Show
نود مجاز|Allowed node
سرویس|Service
ادامه برای واریز|Continue to payment
＋ ساخت و پرداخت از موجودی|＋ Create & pay from wallet
حساب‌ها و سفارش‌ها|Accounts & orders
اولین حساب خود را بسازید.|Create your first account.
↻ تلاش دوباره بدون پرداخت مجدد|↻ Retry without paying again
↗ صفحهٔ کاربر|↗ Customer page
↓ کانفیگ|↓ Profile
⧉ متن آمادهٔ ارسال حساب|⧉ Prepared account message
⧉ کپی لینک، نام کاربری و رمز|⧉ Copy link, username & password
رمز تعیین‌شدهٔ کاربر|Customer’s current password
رمز حساب‌های قبلی قابل بازیابی نیست؛ برای متن کامل، رمز فعلی را اینجا وارد کنید.|Old passwords cannot be recovered. Enter the current password locally for the full message.
تمدید از اعتبار کیف پول|Renew using wallet credit
سرویس را انتخاب کنید؛ مبلغ قبل از تأیید نمایش داده می‌شود.|Choose a plan. The price appears before confirmation.
↻ تمدید و پرداخت از موجودی|↻ Renew & pay from wallet
تمدیدهای اخیر|Recent renewals
دستگاه‌ها|Devices
IP، زمان اتصال و مصرف هر اتصال به تفکیک سرور.|IP address, connection time and usage by server.
تازه‌سازی|Refresh
حجم حساب|Account data
موقعیت|Location
امنیت حساب شما|YOUR ACCOUNT SECURITY
لینک این صفحه شخصی است؛ محرمانه نگه دارید.|This page link is private. Keep it confidential.
بنی پنل · تجربه‌ای ساده، اتصال مطمئن|Beeny Panel · Smooth experience, reliable connection
بنی پنل · همراه شما در هر اتصال|Beeny Panel · With you on every connection
گزارش درخواست|Request status
متوجه شدم|Got it
تغییر تم|Change theme
خروج از حساب|Sign out
خروج|Sign out
انتخاب آواتار دلخواه|Choose your avatar
۲۹ دوست پشمالو منتظر شما هستند|29 fluffy friends await you
شخصیت مورد علاقه‌تان را انتخاب کنید؛ یا با دکمه کنار عکس پروفایل، عکس خودتان را آپلود کنید.|Choose your favorite character, or upload a photo using the button beside your avatar.
ذخیره آواتار انتخاب‌شده|Save selected avatar
آواتار شماره|Avatar number
۷ روز|7 days
۱۴ روز|14 days
۳۰ روز|30 days
دستگاه|devices
دانلود|Download
تمدید|Renewal
۰ تومان|0 Toman
یک لحظه صبر کنید|Please wait
اطلاعات کارت هنوز ثبت نشده است.|Card details have not been configured yet.
اطلاعات پرداخت یا دریافت درخواست‌ها هنوز توسط مدیر تکمیل نشده است.|The administrator has not completed payment settings yet.
یک درخواست در انتظار بررسی دارید؛ از بخش پیگیری یا پشتیبانی اقدام کنید.|You have a pending request. Check its status or contact support.
حساب توسط مدیر محدود شده است؛ برای تمدید با پشتیبانی تماس بگیرید.|Your account is restricted by the administrator. Contact support to renew.
حساب توسط مدیر غیرفعال شده است|Disabled by administrator
حساب غیرفعال|Inactive account
تاریخ|Date
مصرف|Usage
'''
TRANSLATIONS=dict(line.split('|',1) for line in PAIRS.strip().splitlines())
TRANSLATIONS.update({'ورود به حساب':'Sign in','رمز عبور':'Password','رمز عبور شما':'Enter your password','نام کاربری شما':'Enter your username','نمایش رمز':'Show password','رنگ صفحه':'Color theme','همه‌چیز برای یک اتصال راحت':'Everything for a smooth connection','دسترسی هنوز توسط مدیر فعال نشده است.':'Access has not been enabled by the administrator yet.','برای بازیابی رمز با پشتیبانی تماس بگیرید.':'Contact support to recover your password.','فضای امن حساب شما':'Your secure account space','بدون سقف حجم':'Unlimited data'})

TRANSLATIONS.update({'مرکز پشتیبانی': 'Support center', 'کنار شما هستیم': 'Here for you', 'سؤال یا مشکلی دارید؟ گفت\u200cوگو را از همین\u200cجا شروع کنید.': 'Have a question? Start a conversation here.', 'گفت\u200cوگو': 'Conversation', 'گفت\u200cوگوهای شما': 'Your conversations', 'پاسخ\u200cها در همین\u200cجا نمایش داده می\u200cشوند': 'Replies will appear here', 'در انتظار پاسخ': 'Awaiting reply', 'پاسخ داده شد': 'Answered', 'بسته شده': 'Closed', 'هنوز گفت\u200cوگویی ندارید': 'No conversations yet', 'اولین پیامتان را بفرستید؛ تیم پشتیبانی همین\u200cجا پاسخ می\u200cدهد.': 'Send your first message; our support team will reply here.', 'تیکت جدید': 'New ticket', 'موضوع': 'Subject', 'پیام': 'Message', 'ارسال پیام': 'Send message', 'ثبت تیکت': 'Submit ticket', 'اتصال': 'Connection', 'زمان اتصال': 'Connected since', 'قطع این اتصال': 'Disconnect', 'اتصال فعالی ندارد.': 'No active connections.', 'نودی به این حساب اختصاص نیافته است.': 'No node assigned to this account.', 'IP، زمان اتصال و مصرف هر اتصال به تفکیک سرور.': 'IP address, connection time and usage by server.', 'امنیت حساب شما': 'Your account security', 'تازه\u200cسازی': 'Refresh', 'بازگشت به حساب': 'Back to account', 'OpenVPN · سرور اصلی': 'OpenVPN · Primary server', 'OpenVPN · نود اتصال': 'OpenVPN · Connection node', 'اطلاعات این نود در دسترس نیست؛ وضعیت رابط مدیریت و نسخه ایجنت باید بررسی شود.': 'Node information is unavailable. Please contact support.', 'دستگاه همزمان': 'simultaneous devices', 'روز اعتبار': 'days of validity', 'دستگاه': 'devices', 'حساب\u200cها و سفارش\u200cها': 'Accounts and orders', 'ساخت حساب': 'Create account', 'ساخت رمز': 'Generate password', 'اطلاعات واریز': 'Payment details', 'حساب حذف شد؛ سوابق پرداخت حفظ شدند.': 'Account deleted; payment history preserved.'})

TRANSLATIONS.update({'ایجاد تیکت':'Create ticket','شارژ کیف پول':'Top up wallet','موجودی':'Balance','حساب‌های شما':'Your accounts','نودهای مجاز':'Allowed nodes','نماد دوست‌داشتنی خود را انتخاب کنید':'Choose your avatar','انتخاب آواتار دلخواه':'Choose your avatar'})

TRANSLATIONS.update({'آموزش\u200cهای ویدئویی': 'Video tutorials', 'تمدید پس از تأیید مدیر انجام می\u200cشود.': 'Renewal takes effect after administrator approval.', 'کانفیگ را از بخش «کانفیگ\u200cهای شما» بگیرید.': 'Download your profile from Connection files.', 'گفت\u200cوگوهای من': 'My conversations', 'اعتبار شما، در یک نگاه': 'Your balance at a glance', 'کیف پول من': 'My wallet', 'شارژ حساب، خرید سرویس و تاریخچهٔ پرداخت\u200cها در یک جای امن.': 'Top up, buy services and review payments in one secure place.', 'موجودی قابل استفاده': 'Available balance', 'برای تمدید از اعتبارتان استفاده کنید؛ شارژ جدید پس از تأیید واریز اضافه می\u200cشود.': 'Use your balance to renew. Top-ups are added after payment approval.', 'تأیید و شارژ': 'Review & top up', 'تغییر مبلغ': 'Change amount', 'راه ارتباطی': 'Contact details', 'موجودی کافی نیست؛ ابتدا کیف پول را شارژ کنید.': 'Insufficient balance. Top up your wallet first.', 'قیمت نهایی و کد تخفیف روی سرور بررسی می\u200cشود.': 'The final price and coupon are verified by the server.', 'تاریخچهٔ تراکنش\u200cها': 'Transaction history', 'اولین تراکنش شما در راه است': 'Your first transaction awaits', 'بعد از شارژ یا خرید، جزئیات تراکنش همین\u200cجا ثبت می\u200cشود.': 'Your top-ups and purchases will appear here.', 'دستگاه\u200cهای حساب': 'Account devices', 'نام دستگاه': 'Device name', 'ساخت کانفیگ دستگاه': 'Create device profile', 'هنوز دستگاهی ثبت نشده است.': 'No registered devices yet.', 'برای هر دستگاه کانفیگ مستقل بسازید. مسدود کردن آن، اتصال مجدد همان کانفیگ را هم قطع می\u200cکند. کانفیگ قدیمی مشترک، به یک دستگاه مشخص وابسته نیست.': 'Create a separate profile for each device. Blocking it prevents reconnection with that profile. Legacy shared profiles do not identify individual devices.', 'قطع اتصال، دسترسی دائمی دستگاه را لغو نمی\u200cکند؛ کانفیگ معتبر می\u200cتواند دوباره وصل شود. برای مسدودسازی کامل حساب با مدیر تماس بگیرید. مدل گوشی از OpenVPN قابل شناسایی نیست.': 'Disconnecting ends this session; a valid profile can reconnect. Contact support to block the account. OpenVPN does not identify phone models.', 'تنظیم دلخواه': 'Custom service', 'محاسبه با تعرفهٔ اختصاصی مدیر': 'Calculated using your assigned rates', 'حجم GB': 'Quota (GB)', 'قیمت قطعی از سمت سرور و بر اساس تعرفهٔ مدیر محاسبه می\u200cشود.': 'The server calculates the final price using your assigned rates.', 'سفارش ناموفق غیرفعال می\u200cماند و بدون پرداخت دوباره قابل پیگیری است. رمز فقط برای همین ارسال، موقت در مرورگر نگه داشته می\u200cشود.': 'Unsuccessful orders stay disabled and can be retried without a second charge. The password is held temporarily in this browser for sharing.', 'لینک این حساب توسط مدیر تغییر کرده است؛ لینک تازه را از مدیر بگیرید.': 'The administrator changed this link. Ask for the new link.', 'تمدید از کیف پول': 'Renew from wallet', 'روزها و حجم به حساب اضافه می\u200cشوند؛ مصرف و توقف شخصی پاک نمی\u200cشوند. تعداد دستگاه مطابق پلن انتخابی می\u200cشود.': 'Days and quota are added without resetting usage or personal pause. The device limit follows the selected plan.', 'در انتظار تأیید نودها': 'Awaiting node confirmation', 'مسدود': 'Blocked', 'دانلود کانفیگ این دستگاه': 'Download device profile', 'مسدود کردن دستگاه': 'Block device', 'فعال\u200cسازی دوباره': 'Unblock device'})

TRANSLATIONS.update({'با خیال راحت بپرس':'Ask with confidence','هر موضوع، یک گفت‌وگوی خصوصی؛ پاسخ‌ها را همین‌جا دنبال کن.':'A private conversation for every topic. Follow replies here.'})

TRANSLATIONS.update({'٪':'%','۱':'1','۲':'2','۳':'3'})

def translate(value):
    stripped=value.strip()
    if stripped in TRANSLATIONS:
        return value.replace(stripped,TRANSLATIONS[stripped],1)
    match=re.fullmatch(r'آواتار شماره (\d+)',stripped)
    if match:return value.replace(stripped,'Avatar '+match[1])
    match=re.fullmatch(r'از (\d+) (گیگابایت|دستگاه)',stripped)
    if match:return value.replace(stripped,'of '+match[1]+' '+('GB' if match[2]=='گیگابایت' else 'devices'))
    match=re.fullmatch(r'درخواست #(\d+)',stripped)
    if match:return value.replace(stripped,'Request #'+match[1])
    match=re.fullmatch(r'(\d+) روز · (\d+) (GB|گیگابایت) · (\d+) دستگاه',stripped)
    if match:return value.replace(stripped,match[1]+' days · '+match[2]+' GB · '+match[4]+' devices')
    # Dynamic amount/unit segments retain the original numbers.
    for unit in ('تومان','گیگابایت','روز'):
        if re.fullmatch(r'[\d\s,.٪%−+]+ '+unit, stripped):
            return value.replace(unit, TRANSLATIONS[unit])
    match=re.fullmatch(r'([\d\s,.]+) (روز اعتبار|دستگاه همزمان|دستگاه|موقعیت)',stripped)
    if match:return value.replace(stripped,match[1]+' '+{'روز اعتبار':'days of validity','دستگاه همزمان':'simultaneous devices','دستگاه':'devices','موقعیت':'locations'}[match[2]])
    match=re.fullmatch(r'حد مصرف منصفانه ([\d,.]+) گیگابایت',stripped)
    if match:return value.replace(stripped,'Fair use '+match[1]+' GB')
    prefix=re.match(r'^(✦|＋|↗|⧉|◉|↻|↓|→|✓)\s*(.+)$',stripped)
    if prefix and prefix[2] in TRANSLATIONS:
        return value.replace(prefix[2],TRANSLATIONS[prefix[2]])
    return value

class CustomerHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False);self.parts=[];self.skip=[]
    def handle_starttag(self,tag,attrs):
        raw=self.get_starttag_text()
        for key,value in attrs:
            if key in {'title','aria-label','placeholder','alt'} and value:
                translated=translate(value)
                if translated!=value:raw=raw.replace(value,translated)
        self.parts.append(raw)
        if tag in {'script','style','bdi','textarea','video'}:self.skip.append(tag)
    def handle_startendtag(self,tag,attrs):self.parts.append(self.get_starttag_text())
    def handle_endtag(self,tag):
        self.parts.append('</'+tag+'>')
        if self.skip and self.skip[-1]==tag:self.skip.pop()
    def handle_data(self,data):self.parts.append(data if self.skip else translate(data))
    def handle_entityref(self,name):self.parts.append('&'+name+';')
    def handle_charref(self,name):self.parts.append('&#'+name+';')
    def handle_comment(self,data):self.parts.append('<!--'+data+'-->')
    def handle_decl(self,decl):self.parts.append('<!'+decl+'>')


def register(app):
    @app.after_request
    def customer_translation(response):
        if '/c/' not in request.path or session.get('customer_language','fa')!='en' or response.mimetype!='text/html' or response.direct_passthrough:
            return response
        parser=CustomerHTML();parser.feed(response.get_data(as_text=True));parser.close()
        html=''.join(parser.parts).replace('lang="fa" dir="rtl"','lang="en" dir="ltr"')
        response.set_data(html)
        return response

TRANSLATIONS.update({'✦ اتصال سریع و خصوصی به تلگرام':'✦ Quick, private connection to Telegram','اتصال سریع و خصوصی به تلگرام':'Quick, private connection to Telegram','در حال آماده‌سازی…':'Preparing your page…','نمایندگی من':'Reseller workspace'})
