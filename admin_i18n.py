"""Explicit template translations: never translate usernames or stored customer text."""
from flask import request,jsonify,session
from flask_login import current_user,login_required
PAIRS='''Entry host|میزبان ورودی
Exit host|میزبان خروجی
1 · Entry host|۱ · میزبان ورودی
2 · Exit host|۲ · میزبان خروجی
Entry public domain or IP|دامنه یا IP عمومی ورودی
Via entry tunnel|از طریق تونل ورودی
Smart DNS|دی‌ان‌اس هوشمند
Doctor DNS & HyperDNS · account-specific delivery and diagnostics|Doctor DNS و HyperDNS · تنظیم اختصاصی حساب و بررسی اتصال
Installation|نصب و راه‌اندازی
Account access|دسترسی حساب
Subscriber DNS|دی‌ان‌اس مشترک
Test DNS|آزمایش DNS
Connect an entry host to an OpenVPN exit node in any country, with direct and tunnel downloads.|اتصال میزبان ورودی به نود OpenVPN خروجی در هر کشور، همراه با دانلود مستقیم و تونلی.
Install the verified engine on both hosts using the Beeny SSH menu. Create the entry host, then import its private invitation on the exit node. Either host can be in any country. Keep the invitation secret.|موتور بررسی‌شده را از منوی SSH بنی روی هر دو میزبان نصب کنید. ورودی را بسازید و دعوت خصوصی آن را روی نود خروجی وارد کنید. هر دو میزبان می‌توانند در هر کشوری باشند. دعوت را محرمانه نگه دارید.
Payment review|بررسی پرداخت
Check the saved order and receipt before approving payment.|پیش از تأیید پرداخت، سفارش ثبت‌شده و رسید را بررسی کنید.
Routing mode|حالت مسیریابی
Selected destinations only|فقط مقصدهای انتخاب‌شده
All VPN IPv4 traffic|تمام ترافیک IPv4 وی‌پی‌ان
Custom WARP domains|دامنه‌های دلخواه برای WARP
Custom WARP IPv4 networks|آی‌پی‌ها و شبکه‌های دلخواه برای WARP
Presets cover common endpoints, not every media CDN. Hostname rules use an IPv4 snapshot; preview again to refresh addresses.|پیش‌فرض‌ها مقصدهای رایج را پوشش می‌دهند، نه تمام سرورهای رسانه. قوانین دامنه بر اساس آی‌پی‌های فعلی هستند؛ برای تازه‌سازی دوباره پیش‌نمایش بگیرید.
Host maintenance|نگهداری سرور
Controlled jobs with explicit outcomes; VPN connections are not restarted.|عملیات کنترل‌شده با نتیجه مشخص؛ اتصال‌های وی‌پی‌ان راه‌اندازی مجدد نمی‌شوند.
Refresh maintenance status|تازه‌سازی وضعیت نگهداری
Enable BBR|فعال‌سازی BBR
Restore TCP settings|بازگردانی تنظیمات TCP
Restart panel services|راه‌اندازی مجدد سرویس‌های پنل
BBR uses the existing kernel and affects new TCP connections. Live interface queue settings are not replaced.|BBR از کرنل فعلی استفاده می‌کند و روی اتصال‌های TCP جدید اثر دارد. صف فعال رابط شبکه جایگزین نمی‌شود.
For administrator access, backup, SSL and GitHub updates, run beeny over SSH. Saved passwords cannot be displayed; reset them securely.|برای مدیریت دسترسی مدیران، پشتیبان‌گیری، SSL و آپدیت گیت‌هاب، دستور beeny را در SSH اجرا کنید. رمز ذخیره‌شده قابل نمایش نیست؛ می‌توانید آن را تغییر دهید.
Run this maintenance operation?|این عملیات نگهداری اجرا شود؟
Show password|نمایش رمز واردشده
Hide password|پنهان کردن رمز
Clear log|پاک کردن گزارش
records|رکورد
Maintenance queued. Refresh status to see the result.|عملیات در صف قرار گرفت؛ برای دیدن نتیجه وضعیت را تازه کنید.
Current status loaded.|وضعیت فعلی دریافت شد.
Dashboard|داشبورد
Users|کاربران
Settings|تنظیمات
General|عمومی
General settings|تنظیمات عمومی
Panel access|دسترسی پنل
Administrators|مدیران
My security|امنیت حساب من
Active sessions|نشست‌های فعال
Administrator username|نام کاربری مدیر
Panel path|مسیر پنل
Current password|رمز عبور فعلی
New password|رمز عبور جدید
Confirm new password|تکرار رمز عبور جدید
Save changes|ذخیره تغییرات
Nodes & health|نودها و سلامت اتصال
Check all nodes|بررسی همه نودها
Add node|افزودن نود
Edit node|ویرایش نود
Save node|ذخیره نود
Name|نام
Country code|کد کشور
VPN address|آدرس اتصال وی‌پی‌ان
Agent HTTPS address|آدرس HTTPS ایجنت
API key|کلید API
Protocol|پروتکل
Monitoring & capacity|پایش و ظرفیت
Monitoring|پایش
Refresh|تازه‌سازی
System|سیستم
System services|سرویس‌های سیستم
Resource monitoring|پایش منابع
Restart service|راه‌اندازی مجدد سرویس
Refresh status|تازه‌سازی وضعیت
Checking…|در حال بررسی…
HTTPS & certificate renewal|HTTPS و تمدید گواهی
Test renewal|آزمایش تمدید
Check & renew|بررسی و تمدید
Enable automatic renewal|فعال‌سازی تمدید خودکار
Disable Beeny timer|غیرفعال کردن زمان‌بندی بنی
Backups|نسخه‌های پشتیبان
Backups & recovery|پشتیبان‌گیری و بازیابی
Accounts & database|حساب‌ها و پایگاه داده
Create database snapshot|ساخت نسخه پایگاه داده
Complete recovery backup|پشتیبان کامل بازیابی
Create complete backup|ساخت پشتیبان کامل
Import a signed backup|ورود نسخه پشتیبان امضاشده
Backup file|فایل پشتیبان
Validate & upload|اعتبارسنجی و بارگذاری
Refresh list|تازه‌سازی فهرست
Connection addresses & fair use|آدرس اتصال و مصرف منصفانه
Service controls|کنترل سرویس‌ها
Certificates & client profiles|گواهی‌ها و کانفیگ کاربران
Service plans|پلن‌های سرویس
Edit plan|ویرایش پلن
New plan|پلن جدید
＋ Add plan|＋ افزودن پلن
Back to plans|بازگشت به پلن‌ها
Save plan|ذخیره پلن
Manage plans|مدیریت پلن‌ها
Active|فعال
Disabled|غیرفعال
Status|وضعیت
Toman|تومان
Username|نام کاربری
Devices|دستگاه‌ها
Loading...|در حال بارگذاری…
Online|آنلاین
Cancel|انصراف
Online Now|اکنون آنلاین
Total Users|تعداد کاربران
Traffic Used|مصرف ترافیک
Newest First|جدیدترین‌ها
Highest Usage|بیشترین مصرف
Lowest Usage|کمترین مصرف
Oldest First|قدیمی‌ترین‌ها
All Protocols|همه پروتکل‌ها
All Status|همه وضعیت‌ها
Days Left|روزهای باقی‌مانده
Reason|دلیل
Running|در حال اجرا
Max Devices|حداکثر دستگاه‌ها
Expire Date|تاریخ انقضا
Sales & invoices|فروش و صورت‌حساب‌ها
Account status|وضعیت حساب
Today|امروز
Operation|عملیات
Telegram & email|تلگرام و ایمیل
Near Limit|نزدیک سقف مصرف
Online First|آنلاین‌ها در ابتدا
filters applied live|فیلترها به‌صورت زنده اعمال می‌شوند
Profile|پروفایل
Edit|ویرایش
Download Config|دانلود کانفیگ
Last 30 days|۳۰ روز گذشته
Disk|دیسک
Used|مصرف‌شده
⌫ Delete|⌫ حذف
Traffic Limit (GB)|سقف مصرف (گیگابایت)
Node access · optional|دسترسی نود · اختیاری
Restrict account tools to selected nodes|محدود کردن ابزار حساب به نودهای انتخابی
Panel|پنل
Plan|پلن
Payment|پرداخت
Previous|قبلی
Next|بعدی
Edit User|ویرایش کاربر
All accounts|همه حساب‌ها
Edit account|ویرایش حساب
Simultaneous devices|دستگاه‌های هم‌زمان
Allowed nodes|نودهای مجاز
Current expiry|انقضای فعلی
Add data · GB|افزایش حجم · گیگابایت
Customer page login|ورود به صفحه مشتری
Customer login username|نام کاربری ورود مشتری
Bulk operations|عملیات گروهی
Traffic|ترافیک
Portal content|محتوای پنل کاربر
Customer & payments|مشتریان و پرداخت‌ها
Support inbox|صندوق پشتیبانی
Renewal inbox|درخواست‌های تمدید
Representatives & credit|نمایندگان و اعتبار
View all users|مشاهده همه کاربران
Allowed Nodes|نودهای مجاز
Account operations|عملیات حساب
Confirm this exact change|تأیید همین تغییر
Queue these changes|ثبت تغییرات در صف
Accounts|حساب‌ها
Select visible|انتخاب موارد نمایان
Clear|پاک کردن
Add validity days|افزایش روز اعتبار
Add GB to quota|افزایش سقف حجم
Disable accounts|غیرفعال کردن حساب‌ها
Enable eligible accounts|فعال کردن حساب‌های واجد شرایط
Days / GB|روز / گیگابایت
Preview changes|پیش‌نمایش تغییرات
Recent jobs|عملیات اخیر
No jobs queued yet.|عملیاتی در صف نیست.
Refresh progress|تازه‌سازی پیشرفت
VPN access|دسترسی وی‌پی‌ان
Audit log|گزارش فعالیت مدیران
Live Directory|فهرست زنده
Error Loading Users|خطا در بارگذاری کاربران
Add|افزودن
Original view|نمای اصلی
Compact list|فهرست فشرده
Name A–Z|نام از الف تا ی
Name Z–A|نام از ی تا الف
No users found.|کاربری پیدا نشد.
No servers|سروری وجود ندارد
Allowed Servers|سرورهای مجاز
Representative|نماینده
Choose representative|انتخاب نماینده
Load policy|بارگذاری تنظیمات
Minimum settlement · Toman|حداقل تسویه · تومان
Manager base|قیمت پایه مدیر
Maximum retail|حداکثر قیمت فروش
Available · Toman|قابل برداشت · تومان
Settlement requests|درخواست‌های تسویه
Bank transfer reference|شماره پیگیری انتقال
Transfer receipt|رسید انتقال
No settlement requests yet.|درخواست تسویه‌ای ثبت نشده است.
CONTROL CENTER|مرکز کنترل
INFRASTRUCTURE|زیرساخت
TRANSPORT SECURITY|امنیت ارتباط
Saving…|در حال ذخیره…
Saved.|ذخیره شد.
Save failed.|ذخیره انجام نشد.
Passwords do not match.|رمزهای عبور یکسان نیستند.
Plan saved.|پلن ذخیره شد.
Node saved.|نود ذخیره شد.
Node checks completed.|بررسی نودها پایان یافت.
Refresh this page and retry the form.|صفحه را تازه‌سازی و دوباره تلاش کنید.
General settings saved.|تنظیمات عمومی ذخیره شد.
Account security, panel access and administrator permissions.|امنیت حساب، دسترسی پنل و مجوزهای مدیران.
Changing your credentials signs out existing sessions. Changing the access path also restarts the panel.|تغییر اطلاعات ورود، نشست‌های فعلی را خارج می‌کند. تغییر مسیر دسترسی، پنل را نیز راه‌اندازی مجدد می‌کند.
Manage connection endpoints and inspect the most recent health check.|مدیریت آدرس اتصال نودها و مشاهدهٔ آخرین نتیجهٔ بررسی سلامت.
The panel certificate protects browser access. VPN client certificates have a separate lifecycle.|گواهی پنل از ارتباط مرورگر محافظت می‌کند. گواهی‌های کاربران وی‌پی‌ان چرخهٔ جداگانه‌ای دارند.
Loading certificate status…|در حال دریافت وضعیت گواهی…
Inspect actual service state and request a controlled restart.|مشاهدهٔ وضعیت واقعی سرویس‌ها و درخواست راه‌اندازی مجدد کنترل‌شده.
Includes users, settings, orders and financial records. VPN keys and uploaded receipts require a complete backup.|شامل کاربران، تنظیمات، سفارش‌ها و سوابق مالی است. برای کلیدهای وی‌پی‌ان و رسیدها، پشتیبان کامل بگیرید.
Includes the database, panel files, private uploads, environment and OpenVPN certificate files. Keep downloads private.|شامل پایگاه داده، فایل‌های پنل، آپلودهای خصوصی، تنظیمات محیط و گواهی‌های اوپن‌وی‌پی‌ان است. فایل دانلودشده را محرمانه نگه دارید.
Import accepts a complete .tar.gz backup signed by this installation. A different installation needs its original signing key through the recovery procedure.|فایل پشتیبان کامل با پسوند tar.gz و امضای همین نصب پذیرفته می‌شود. بازیابی نصب دیگر به کلید امضای اصلی آن نیاز دارد.
Active server configuration and VPN lifecycle. Changing the connection address is managed separately.|تنظیمات فعال سرور و مدیریت وی‌پی‌ان. تغییر آدرس اتصال در بخش دسترسی وی‌پی‌ان انجام می‌شود.
Reading server configuration…|در حال خواندن تنظیمات سرور…
HTTPS renewal does not change VPN profiles. CA, server and client certificates are managed separately by the PKI audit. Network configuration changes require checking compatibility and a maintenance window.|تمدید HTTPS کانفیگ کاربران را تغییر نمی‌دهد. گواهی مرجع، سرور و کاربر جداگانه در بررسی PKI مدیریت می‌شوند. تغییر تنظیمات شبکه به بررسی سازگاری و زمان نگهداری نیاز دارد.
Each plan has a separate editor. Existing invoices retain their original service snapshot.|هر پلن صفحهٔ ویرایش جداگانه دارد. مشخصات سرویس در فاکتورهای قبلی تغییر نمی‌کند.
Remove representative|حذف نماینده
Type the representative username|نام کاربری نماینده را وارد کنید
Remove this representative and all listed child accounts; preserve financial history.|این نماینده و تمام کاربران فهرست‌شده حذف شوند؛ سوابق مالی حفظ شوند.
Confirm removal|تأیید حذف
Configuration, connectivity and security in one place.|تنظیمات، ارتباطات و امنیت در یک محل.
Panel access, administrators and personal security|دسترسی پنل، مدیران و امنیت حساب
Connection addresses and fair-use limits|آدرس‌های اتصال و محدودیت مصرف منصفانه
Bots and delivery settings|ربات‌ها و تنظیمات ارسال پیام
Locations, connection endpoints and diagnostics|لوکیشن‌ها، آدرس‌های اتصال و عیب‌یابی
Administrative activity|فعالیت‌های مدیریتی
Certificates and secure access|گواهی‌ها و دسترسی امن
Services and server operations|سرویس‌ها و عملیات سرور
Database backups and restore|پشتیبان‌گیری و بازیابی پایگاه داده
VPN service configuration|تنظیمات سرویس وی‌پی‌ان
Live server resources|منابع زندهٔ سرور
Customer and payment settings saved.|تنظیمات کاربران و پرداخت ذخیره شد.
Plans changed in another session. Reload before saving.|پلن‌ها در نشست دیگری تغییر کرده‌اند. پیش از ذخیره، صفحه را تازه‌سازی کنید.
Save settings|ذخیره تنظیمات
Plan title|عنوان پلن
English title|عنوان انگلیسی
English badge|نشان انگلیسی
Price · Toman|قیمت · تومان
Original price · optional|قیمت اصلی · اختیاری
Complimentary days on admin creation|روز هدیه هنگام ساخت توسط مدیر
Complimentary GB on admin creation|گیگابایت هدیه هنگام ساخت توسط مدیر
NETWORK POLICY|قوانین شبکه
Network rules & WARP|قوانین شبکه و وارپ
VPN destination policies and client bypass routes|قوانین مقصد و مسیرهای مستقیم کاربران
Rules apply only to VPN client traffic on the selected node.|قوانین فقط بر ترافیک کاربران وی‌پی‌ان در نود انتخاب‌شده اعمال می‌شوند.
Node|نود
Read current policy|خواندن تنظیمات فعلی
Blocked IPv4 networks|شبکه‌های IPv4 مسدود
Blocked hostnames · IPv4 snapshot|دامنه‌های مسدود · آدرس‌های فعلی IPv4
Hostname blocking resolves current IPv4 addresses. Shared IPs may affect other sites; encrypted DNS, IPv6 and changing addresses are not covered. Preview again to refresh the snapshot.|دامنه‌ها به آدرس‌های فعلی IPv4 تبدیل می‌شوند. آی‌پی مشترک ممکن است روی سایت‌های دیگر اثر بگذارد؛ DNS رمزگذاری‌شده، IPv6 و تغییر آدرس‌ها پوشش داده نمی‌شوند. برای به‌روزرسانی آدرس‌ها دوباره پیش‌نمایش بگیرید.
Blocked TCP and UDP destination ports|پورت‌های مقصد مسدود TCP و UDP
Client bypass IPv4 networks|شبکه‌های IPv4 با مسیر مستقیم کاربر
Bypass uses the client original gateway. Enter verified CIDRs; no geographic list is inferred. It takes effect after a planned OpenVPN restart and client reconnect, subject to client support.|مسیر مستقیم از دروازهٔ اصلی دستگاه کاربر استفاده می‌کند. فهرست CIDR معتبر وارد کنید؛ کشور آدرس‌ها خودکار تعیین نمی‌شود. اجرای آن به راه‌اندازی مجدد برنامه‌ریزی‌شدهٔ اوپن‌وی‌پی‌ان، اتصال مجدد و پشتیبانی کلاینت نیاز دارد.
Restrict common BitTorrent ports · 6881–6889 and 6969|محدودسازی پورت‌های رایج بیت‌تورنت · ۶۸۸۱ تا ۶۸۸۹ و ۶۹۶۹
Port restrictions are not BitTorrent detection. Encrypted or alternate-port torrent traffic can bypass them.|محدودسازی پورت، تشخیص بیت‌تورنت نیست. تورنت رمزگذاری‌شده یا روی پورت دیگر می‌تواند از این محدودیت عبور کند.
Route VPN IPv4 traffic through an existing WARP tunnel|عبور ترافیک IPv4 وی‌پی‌ان از تونل وارپ موجود
Existing egress tunnel interface|رابط تونل خروجی موجود
WARP must already be installed, connected and permitted by your firewall. This does not change the server default route. Verify traffic before confirming; an unavailable egress tunnel may interrupt VPN client traffic.|وارپ باید از قبل نصب و متصل باشد و فایروال عبور ترافیک را مجاز بداند. مسیر پیش‌فرض سرور تغییر نمی‌کند. قبل از تأیید، ترافیک را بررسی کنید؛ قطع تونل خروجی ممکن است ارتباط کاربران را مختل کند.
Validate & preview|اعتبارسنجی و پیش‌نمایش
Apply temporarily · 120 seconds|اعمال موقت · ۱۲۰ ثانیه
Check a VPN connection now. Confirm within 120 seconds or the previous rules will return automatically. No VPN restart is performed.|اکنون یک اتصال وی‌پی‌ان را بررسی کنید. تا ۱۲۰ ثانیه تأیید کنید؛ در غیر این صورت قوانین قبلی خودکار برمی‌گردند. وی‌پی‌ان راه‌اندازی مجدد نمی‌شود.
Traffic works · confirm|ترافیک برقرار است · تأیید
Restore previous rules|بازگردانی قوانین قبلی
Current policy loaded.|تنظیمات فعلی خوانده شد.
Preview ready. No rules changed.|پیش‌نمایش آماده است. هیچ قانونی تغییر نکرده است.
A network change awaits confirmation.|یک تغییر شبکه در انتظار تأیید است.
Network policy confirmed.|قوانین شبکه تأیید شد.
Previous network policy restored.|قوانین قبلی شبکه بازگردانده شد.
Rules affect only the selected node.|قوانین فقط روی نود انتخاب‌شده اثر دارند.
Install the nftables package on the selected node first.|ابتدا بستهٔ nftables را روی نود انتخاب‌شده نصب کنید.
Configured policy is not active in the firewall. Preview and apply again; check boot service logs.|تنظیمات ذخیره‌شده در فایروال فعال نیست. دوباره پیش‌نمایش و اعمال کنید و لاگ سرویس راه‌اندازی را بررسی کنید.
A removal hold is active. Failed deletion can be retried, or the hold can be cleared without restoring deleted accounts.|نگه‌داشت حذف فعال است. می‌توانید حذف ناموفق را دوباره انجام دهید یا نگه‌داشت را بردارید؛ حساب‌های حذف‌شده برنمی‌گردند.
Clear removal hold|برداشتن نگه‌داشت حذف
Account removal is in progress. Contact the administrator before creating a new request.|حساب در حال حذف است. پیش از ثبت درخواست جدید با مدیر تماس بگیرید.
Save Changes|ذخیره تغییرات
Create User|ساخت کاربر
Create New User|ساخت کاربر جدید
Edit User Profile|ویرایش پروفایل کاربر
0 = Unlimited|۰ = نامحدود
Leave empty or '-' for no expiration|برای بدون انقضا، خالی یا خط تیره بگذارید
Set 0 for Unlimited traffic|برای حجم نامحدود، صفر وارد کنید
Select Allowed Nodes|انتخاب نودهای مجاز
?? No nodes found. Please add a node in the settings first.|نودی یافت نشد. ابتدا از تنظیمات نود اضافه کنید.
BUSINESS OVERVIEW|نمای کلی کسب‌وکار
Approved service purchases, captured as permanent invoice records.|خریدهای تأییدشده با ثبت دائمی فاکتور.
Lifetime net invoiced sales|فروش خالص فاکتورشده از ابتدا
Monthly revenue · last 12 months|درآمد ماهانه · ۱۲ ماه اخیر
CUSTOMER OFFERS|پیشنهادهای مشتریان
Create a discount code|ایجاد کد تخفیف
Show and enable customer discount codes|نمایش و فعال‌سازی کد تخفیف مشتریان
Save|ذخیره
Control the discount, usage limit and expiry date.|درصد تخفیف، سقف استفاده و تاریخ انقضا را تنظیم کنید.
Code|کد
Discount (%)|تخفیف (درصد)
Maximum uses|سقف تعداد استفاده
Expires (UTC)|انقضا (UTC)
Create discount|ایجاد تخفیف
Disable|غیرفعال
Service mix · current UTC month|ترکیب سرویس‌ها · ماه جاری UTC
Credit-funded initial representative accounts are tracked separately in|حساب‌های اولیهٔ ساخته‌شده با اعتبار نمایندگی جداگانه گزارش می‌شوند در
Credit & representatives → Reports|اعتبار و نمایندگان ← گزارش‌ها
; they are not cash-paid invoices.|؛ این موارد فاکتور پرداخت نقدی نیستند.
Accounts / renewals|حساب‌ها / تمدیدها
Invoiced Toman|مبلغ فاکتور · تومان
No service sales this month.|در این ماه فروشی ثبت نشده است.
Latest invoices|آخرین فاکتورها
Costs and commissions are saved at approval|هزینه و پورسانت هنگام تأیید ثبت می‌شوند
Invoice|فاکتور
Customer|مشتری
Paid (Toman)|پرداخت‌شده (تومان)
Commission|پورسانت
Refunded · see commission adjustments|بازپرداخت‌شده · اصلاحات پورسانت را ببینید
Confirm received|تأیید دریافت
No approved service purchases yet. New invoices appear here after renewal approval.|هنوز خرید تأییدشده‌ای وجود ندارد. پس از تأیید تمدید، فاکتور در اینجا نمایش داده می‌شود.
ACCOUNTABILITY|پاسخ‌گویی
Administrative audit|گزارش فعالیت مدیران
Who changed an account, what changed and when. Passwords and tokens are excluded.|چه کسی، چه زمانی و چه تغییری در حساب داده است. رمزها و توکن‌ها ثبت نمی‌شوند.
⌫ Clear log|⌫ پاک‌کردن گزارش
Time (UTC)|زمان (UTC)
Administrator|مدیر
Details|جزئیات
View|مشاهده
No administrative activity recorded yet.|هنوز فعالیت مدیریتی ثبت نشده است.
Panel login sessions|نشست‌های ورود پنل
Your management logins. Revoked sessions must sign in again.|نشست‌های ورود مدیریتی شما. نشست لغوشده باید دوباره وارد شود.
Back to security|بازگشت به امنیت
No active sessions.|نشست فعالی وجود ندارد.
SYSTEM CENTER|مرکز سیستم
Server Management|مدیریت سرور
Monitor system resources, services and server status in real-time.|پایش زندهٔ منابع، سرویس‌ها و وضعیت سرور.
Hostname|نام میزبان
CPU|پردازنده
RAM|حافظهٔ رم
CPU Cores|هسته‌های پردازنده
Load 1min|بار یک دقیقه
Memory|حافظه
Uptime|زمان روشن‌بودن
Last boot|آخرین راه‌اندازی
Running Services|سرویس‌های فعال
Database|پایگاه داده
Web Server|وب‌سرور
VPN Core|هستهٔ وی‌پی‌ان
PARTNER PAYMENT INBOX|صندوق پرداخت نمایندگان
Review. Verify. Deliver.|بررسی، تأیید، تحویل.
Account creation starts after bank verification. Retries never charge a wallet or duplicate earnings.|ساخت حساب پس از تأیید واریز آغاز می‌شود. تلاش مجدد باعث برداشت دوباره از کیف پول یا تکرار درآمد نمی‌شود.
No orders in this view.|در این بخش سفارشی وجود ندارد.
VPN ACCESS|دسترسی وی‌پی‌ان
Client profile endpoints|آدرس‌های اتصال کانفیگ کاربر
Change each node's public VPN address without changing its agent API address.|آدرس عمومی اتصال هر نود را مستقل از آدرس API ایجنت تغییر دهید.
What changes?|چه چیزی تغییر می‌کند؟
VPN domain or IP|دامنه یا آی‌پی وی‌پی‌ان
Empty = existing node / installer address.|خالی = آدرس فعلی نود یا نصب اولیه.
Transport|روش انتقال
Must match the running server. Changing this does not reconfigure OpenVPN.|باید با سرور فعال یکسان باشد. تغییر این گزینه تنظیمات اوپن‌وی‌پی‌ان را تغییر نمی‌دهد.
VPN port|پورت وی‌پی‌ان
Save client endpoints|ذخیره آدرس‌های اتصال
CRL & core synchronization|همگام‌سازی CRL و هسته
REQUEST CHECK|بررسی درخواست
Back to dashboard|بازگشت به داشبورد
CUSTOMER EXPERIENCE|تجربهٔ مشتری
Customer portal & payments|پنل کاربر و پرداخت‌ها
Configure payment details, plans and receipt delivery.|تنظیم اطلاعات پرداخت، پلن‌ها و ارسال رسید.
Renewal inbox →|صندوق تمدید ←
Payment card|کارت پرداخت
Displayed only on customers' private pages.|فقط در صفحهٔ خصوصی مشتری نمایش داده می‌شود.
Bank name|نام بانک
Card number|شماره کارت
Card holder|دارندهٔ کارت
Card color|رنگ کارت
Support contacts|راه‌های تماس پشتیبانی
Customers see these contact details on their page and in the bot.|این اطلاعات تماس در صفحهٔ کاربر و ربات نمایش داده می‌شود.
Admin Telegram username|نام کاربری تلگرام مدیر
Support phone|تلفن پشتیبانی
Admin notification email|ایمیل اعلان مدیر
Additional payment cards|کارت‌های پرداخت بیشتر
Add up to 7 cards. Customers swipe between cards; the displayed card is copied and recorded with their receipt.|تا ۷ کارت اضافه کنید. کاربر با کشیدن، بین کارت‌ها جابه‌جا می‌شود؛ کارت نمایش‌داده‌شده کپی و همراه رسید ثبت می‌شود.
Color|رنگ
Remove card|حذف کارت
+ Add card|+ افزودن کارت
Custom service price calculator|محاسبهٔ قیمت سرویس دلخواه
Enable custom services|فعال‌سازی سرویس دلخواه
Preview calculation|پیش‌نمایش محاسبه
Create a new service or open an existing plan in its own editor.|سرویس تازه بسازید یا هر پلن را در صفحهٔ ویرایش خودش باز کنید.
Requests stay in the inbox even if notification delivery fails. The background worker retries delivery; use Retry in the inbox after correcting settings.|درخواست حتی با خطای ارسال اعلان در صندوق باقی می‌ماند. سرویس پس‌زمینه ارسال را تکرار می‌کند؛ پس از اصلاح تنظیمات می‌توانید از گزینهٔ تلاش مجدد استفاده کنید.
PAYMENTS|پرداخت‌ها
Payments & renewals|پرداخت‌ها و تمدیدها
Verify each transfer before crediting a wallet or renewing an account.|پیش از شارژ کیف پول یا تمدید حساب، واریز را بررسی کنید.
Payment settings →|تنظیمات پرداخت ←
A clear inbox|صندوق خالی است
New receipts will appear here.|رسیدهای جدید اینجا نمایش داده می‌شوند.
← Previous|→ قبلی
Next →|بعدی ←
Remove representative & accounts|حذف نماینده و حساب‌هایش
BEENY PARTNERS|نمایندگان بنی
Back to inbox|بازگشت به صندوق
Paid by:|پرداخت‌کننده:
Contact:|راه تماس:
Verify the actual bank deposit. Receipt duplicate checks cannot prove payment or detect all altered images.|واریز واقعی بانک را بررسی کنید. کنترل تکراری‌بودن رسید، اثبات پرداخت یا تشخیص تمام تصاویر ویرایش‌شده نیست.
Refund a failed provision|بازپرداخت ساخت ناموفق
Completed refund bank reference|شماره پیگیری بازپرداخت انجام‌شده
Cancel provision & record full refund|لغو ساخت و ثبت بازپرداخت کامل
NOTIFICATION DELIVERY|ارسال اعلان
Configure receipt delivery and administrator notifications.|تنظیم ارسال رسید و اعلان‌های مدیران.
Administrator notification email|ایمیل اعلان‌های مدیر
Telegram bot & admin delivery|ربات تلگرام و ارسال به مدیر
Bot username|نام کاربری ربات
Bot token|توکن ربات
Remove saved bot token|حذف توکن ذخیره‌شدهٔ ربات
Admin numeric chat ID|شناسهٔ عددی چت مدیر
Additional admin chat IDs|شناسهٔ چت مدیران دیگر
Email delivery (SMTP)|ارسال ایمیل (SMTP)
Each email includes the plan snapshot, account details and receipt image.|هر ایمیل شامل مشخصات پلن، اطلاعات حساب و تصویر رسید است.
SMTP hostname|نام میزبان SMTP
Port|پورت
Encryption|رمزنگاری
SSL (usually 465)|SSL (معمولاً ۴۶۵)
STARTTLS (usually 587)|STARTTLS (معمولاً ۵۸۷)
SMTP username|نام کاربری SMTP
SMTP password / app password|رمز SMTP یا رمز برنامه
Remove saved SMTP password|حذف رمز ذخیره‌شدهٔ SMTP
Sender email|ایمیل فرستنده
Leave secret fields blank to keep saved credentials. Payment cards and plans are unchanged.|برای حفظ اطلاعات محرمانهٔ فعلی، فیلدهای رمز را خالی بگذارید. کارت‌ها و پلن‌ها تغییر نمی‌کنند.
Save notification settings|ذخیره تنظیمات اعلان
Server Online|سرور آنلاین
Lifetime Tracked Traffic|ترافیک ثبت‌شده از ابتدا
Cumulative total|مجموع انباشته
Never resets|بدون ریست
Registered|ثبت‌شده
Connected|متصل
Non-expired|منقضی‌نشده
Expiring|نزدیک انقضا
Within 7d|تا ۷ روز
Traffic Overview|نمای کلی مصرف
Last 7 days · GB consumed|۷ روز اخیر · مصرف گیگابایت
Total Used|مصرف کل
Avg / User|میانگین هر کاربر
Peak Day|روز اوج
Protocol Split|تفکیک پروتکل
Distribution|توزیع
Total|مجموع
Online Users|کاربران آنلاین
Currently connected|اکنون متصل
No users connected right now|اکنون کاربری متصل نیست
Expiring Soon|نزدیک انقضا
Next 7 days|۷ روز آینده
No users expiring soon|کاربری نزدیک انقضا نیست
Quick Actions|دسترسی سریع
Add User|افزودن کاربر
All Users|تمام کاربران
Restart VPN|راه‌اندازی مجدد وی‌پی‌ان
Logs|گزارش‌ها
Certificates|گواهی‌ها
Reports|گزارش‌ها
HOST NETWORK · UTC|شبکهٔ میزبان · UTC
Server interface traffic|ترافیک رابط سرور
NETWORK / ANALYTICS|شبکه / تحلیل
Traffic intelligence|تحلیل ترافیک
Measured OpenVPN consumption across the primary server and connected nodes.|مصرف اندازه‌گیری‌شدهٔ اوپن‌وی‌پی‌ان در سرور اصلی و نودهای متصل.
All-time VPN traffic|ترافیک وی‌پی‌ان از ابتدا
Retained after accounts are deleted or reset|پس از حذف یا ریست کاربران نیز حفظ می‌شود
Outbound to clients|ارسال به کاربران
VPN server bytes sent|بایت ارسالی سرور وی‌پی‌ان
Inbound from clients|دریافت از کاربران
VPN server bytes received|بایت دریافتی سرور وی‌پی‌ان
Today (UTC)|امروز (UTC)
All nodes combined|مجموع تمام نودها
Daily measured totals|مجموع اندازه‌گیری روزانه
Servers tracked|سرورهای پایش‌شده
Including historic servers|شامل سرورهای قبلی
DAILY VOLUME|حجم روزانه
Each bar is real VPN bytes collected from OpenVPN status counters.|هر ستون، بایت واقعی ثبت‌شده از شمارنده‌های وضعیت اوپن‌وی‌پی‌ان است.
SERVER BREAKDOWN|تفکیک سرورها
Usage by node|مصرف به تفکیک نود
Includes server history even if an account was removed.|سوابق سرور پس از حذف حساب هم حفظ می‌شود.
Usage appears after the first client session is sampled.|مصرف پس از اولین نمونه‌برداری از اتصال کاربر نمایش داده می‌شود.
Accounting scope|محدودهٔ محاسبه
View profile|مشاهده پروفایل
Service & invoice|سرویس و فاکتور
Build from|روش ساخت
Manual service|سرویس دستی
Existing plan|پلن موجود
Internal / complimentary · no sale|داخلی / هدیه · بدون فروش
Unpaid · invoice only|پرداخت‌نشده · فقط فاکتور
Received · verified by owner|دریافت‌شده · تأیید مالک
Verified bank / cash reference|شماره پیگیری تأییدشدهٔ بانکی یا نقدی
Complimentary days|روز هدیه
Complimentary data · GB|حجم هدیه · گیگابایت
Gifts are added after pricing and do not increase the invoice amount.|هدیه پس از محاسبهٔ قیمت اضافه می‌شود و مبلغ فاکتور را افزایش نمی‌دهد.
Account details|مشخصات حساب
Connection identity and device allowance.|شناسهٔ اتصال و تعداد دستگاه مجاز.
Letters, numbers, dots, underscore and hyphen.|حروف، اعداد، نقطه، زیرخط و خط تیره.
OpenVPN · TCP|اوپن‌وی‌پی‌ان · TCP
OpenVPN is the available protocol on this server.|پروتکل قابل استفاده روی این سرور، اوپن‌وی‌پی‌ان است.
Activation requires available time and data.|فعال‌سازی به زمان و حجم معتبر نیاز دارد.
Optional credentials for the private customer page. OpenVPN connects using the account certificate.|اطلاعات ورود اختیاری صفحهٔ خصوصی کاربر. اتصال اوپن‌وی‌پی‌ان با گواهی حساب انجام می‌شود.
Customer password|رمز کاربر
Data allowance|اعتبار حجم
Set a total allowance, or add data to an existing account.|سقف حجم را تنظیم کنید یا به حساب موجود حجم اضافه کنید.
Total data limit · GB|سقف حجم کل · گیگابایت
0 means unlimited data.|صفر یعنی حجم نامحدود.
Adds to the current limit. If unlimited, starts from used data.|به سقف فعلی اضافه می‌شود. در حالت نامحدود، از حجم مصرف‌شده شروع می‌شود.
Reset recorded usage to zero|صفرکردن مصرف ثبت‌شده
Use when starting a new billing cycle.|برای شروع دورهٔ مالی تازه استفاده کنید.
Validity|اعتبار زمانی
Extend validity · days|افزایش اعتبار · روز
Leave blank to keep the current date.|برای حفظ تاریخ فعلی خالی بگذارید.
Start renewal from|شروع تمدید از
An expired account starts from today.|حساب منقضی‌شده از امروز شروع می‌شود.
Or set an exact expiry|یا تعیین تاریخ انقضای دقیق
If filled, this date takes priority over renewal days.|در صورت تکمیل، این تاریخ بر تعداد روز تمدید اولویت دارد.
Validity period · days|دورهٔ اعتبار · روز
Maximum 3,650 days.|حداکثر ۳۶۵۰ روز.
Begin counting|شروع شمارش
On first connection|هنگام اولین اتصال
Remove expiry date|حذف تاریخ انقضا
Takes priority over the date and renewal fields.|بر فیلدهای تاریخ و تمدید اولویت دارد.
This server|این سرور
Changes are applied when you save.|تغییرات هنگام ذخیره اعمال می‌شوند.
ACCOUNT SECURITY|امنیت حساب
Two-step verification|تأیید دومرحله‌ای
Your security settings apply to your own administrator account.|این تنظیمات امنیتی مربوط به حساب مدیریتی خود شماست.
Add this secret to an authenticator app, then enter its six-digit code.|این کلید را در برنامهٔ رمزساز اضافه کنید و کد شش‌رقمی آن را وارد کنید.
Save these recovery codes securely. Each works once.|کدهای بازیابی را در جای امن نگه دارید. هر کد فقط یک بار قابل استفاده است.
Authenticator code|کد رمزساز
Community & support|جامعه و پشتیبانی
Telegram channel|کانال تلگرام
Telegram group|گروه تلگرام
Support team avatar (JPG, PNG or WebP, up to 20 MB)|آواتار تیم پشتیبانی (JPG، PNG یا WebP تا ۲۰ مگابایت)
Current support avatar|آواتار فعلی پشتیبانی
Save community settings|ذخیره تنظیمات جامعه
Video tutorials|آموزش‌های ویدئویی
Persian title|عنوان فارسی
Video file · optional, up to 200 MB|فایل ویدئو · اختیاری، تا ۲۰۰ مگابایت
Video URL · alternative to upload|آدرس ویدئو · جایگزین آپلود
Cover image|تصویر کاور
＋ Add tutorial|＋ افزودن آموزش
Replace video file · optional, up to 200 MB|جایگزینی فایل ویدئو · اختیاری، تا ۲۰۰ مگابایت
Uploaded video stored privately. Leave file and URL empty to keep it.|ویدئوی آپلودشده خصوصی نگهداری می‌شود. برای حفظ آن، فایل و آدرس را خالی بگذارید.
HTTPS URL · clear it before uploading a replacement|آدرس HTTPS · پیش از آپلود جایگزین، آن را پاک کنید
Replace cover|جایگزینی کاور
Save tutorial|ذخیره آموزش
Preview ↗|پیش‌نمایش ↗
Delete|حذف
Customer announcements|اطلاعیه‌های مشتریان
Colored announcement cards appear below the customer avatar until dismissed. Editing an announcement shows it again.|اطلاعیهٔ رنگی تا زمان بستن، زیر آواتار مشتری نمایش داده می‌شود. ویرایش اطلاعیه باعث نمایش دوبارهٔ آن می‌شود.
Publish announcement|انتشار اطلاعیه
Save announcement|ذخیره اطلاعیه
Loading telemetry…|در حال دریافت داده‌های پایش…
All nodes|تمام نودها
24 hours|۲۴ ساعت
7 days|۷ روز
30 days|۳۰ روز
Measurements are collected every 30 seconds, even with this page closed.|حتی با بسته‌بودن این صفحه، هر ۳۰ ثانیه نمونه‌برداری انجام می‌شود.
Preparing node history…|در حال آماده‌سازی تاریخچهٔ نود…
How to read capacity|روش خواندن ظرفیت
Address slots|ظرفیت آدرس‌ها
are a configuration limit, not a hardware benchmark.|محدودیت تنظیمات است و آزمون توان سخت‌افزار نیست.
Observed with headroom|مشاهده‌شده با ظرفیت آزاد
Connection details, usage and renewal controls for this account.|اطلاعات اتصال، مصرف و کنترل تمدید این حساب.
Active connections|اتصال‌های فعال
Account created. Download the VPN profile below.|حساب ساخته شد. کانفیگ وی‌پی‌ان را از پایین دانلود کنید.
Account changes saved.|تغییرات حساب ذخیره شد.
Data used|حجم مصرف‌شده
Time remaining|زمان باقی‌مانده
Active devices|دستگاه‌های فعال
Usage and access|مصرف و دسترسی
Live account details from this panel.|اطلاعات زندهٔ حساب از همین پنل.
Expiry|انقضا
Connection|اتصال
Renew this account|تمدید این حساب
Add days|افزودن روز
Count from|محاسبه از
Reset used data|ریست حجم مصرف‌شده
Apply changes|اعمال تغییرات
New customer password|رمز جدید کاربر
Save customer credentials|ذخیره اطلاعات ورود کاربر
Private customer page|صفحهٔ خصوصی کاربر
Share this link now|اکنون این لینک را ارسال کنید
Preview customer page|پیش‌نمایش صفحهٔ کاربر
Share access in one message|ارسال اطلاعات دسترسی در یک پیام
Clear private draft|پاک‌کردن پیش‌نویس خصوصی
VPN configuration|کانفیگ وی‌پی‌ان
No node is assigned.|نودی اختصاص داده نشده است.
Account actions|عملیات حساب
Change limits, validity, nodes or device allowance.|تغییر محدودیت‌ها، اعتبار، نودها یا تعداد دستگاه.
Open full account settings|بازکردن تمام تنظیمات حساب
Back to accounts|بازگشت به حساب‌ها
← Payment inbox|→ صندوق پرداخت
⤢ View receipt|⤢ مشاهده رسید
Paid from wallet|پرداخت از کیف پول
Email:|ایمیل:
Telegram:|تلگرام:
× Reject|× رد
↻ Retry|↻ تلاش مجدد
CUSTOMER EXPERIENCE / PAYMENTS|تجربهٔ مشتری / پرداخت‌ها
BalePay Gateway|درگاه بله‌پی
Configure the secure WordPress payment bridge.|تنظیم پل پرداخت امن وردپرس.
Connection settings|تنظیمات اتصال
Securely connect your WordPress checkout bridge.|اتصال امن به پل پرداخت وردپرس.
WordPress checkout URL|آدرس پرداخت وردپرس
Shared HMAC secret|کلید مشترک HMAC
Bale bot username|نام کاربری ربات بله
Invoice title (order number is generated automatically)|عنوان صورتحساب (شماره سفارش خودکار ساخته می‌شود)
Invoice description|توضیح صورتحساب
Gateway availability|وضعیت دسترسی درگاه
Disabling payments blocks new orders, but existing paid orders can still be reconciled.|غیرفعال‌کردن پرداخت، سفارش جدید را متوقف می‌کند؛ پرداخت‌های قبلی همچنان قابل تطبیق هستند.
Enable BalePay|فعال‌سازی بله‌پی
Accept new payment requests|پذیرش درخواست پرداخت جدید
Test mode|حالت آزمایشی
Use the Bale test provider|استفاده از پذیرندهٔ آزمایشی بله
Security|امنیت
Save gateway settings →|ذخیره تنظیمات درگاه ←
Recent payment attempts|آخرین تلاش‌های پرداخت
Latest 50 orders. Superseded attempts are retained for delayed payment reconciliation.|۵۰ سفارش اخیر. تلاش‌های جایگزین‌شده برای تطبیق پرداخت دیرهنگام حفظ می‌شوند.
Order|سفارش
Account|حساب
Amount (IRR)|مبلغ (ریال)
Created (UTC)|ایجاد (UTC)
No payment attempts yet.|هنوز تلاش پرداختی ثبت نشده است.
TEAM ACCESS|دسترسی تیم
Administrators & roles|مدیران و نقش‌ها
Owner: all operations. Support: tickets. Finance: renewals. Seller: their own accounts. Viewer: read access.|مالک: تمام عملیات. پشتیبانی: تیکت‌ها. مالی: تمدیدها. فروشنده: حساب‌های خودش. مشاهده‌گر: فقط مشاهده.
Add administrator|افزودن مدیر
Password|رمز عبور
Role|نقش
Seller, support and viewer only. Unchecked = existing global role access. Mixed-location accounts outside this scope stay hidden.|فقط برای فروشنده، پشتیبانی و مشاهده‌گر. بدون انتخاب = دسترسی سراسری نقش فعلی. حساب‌های دارای نود خارج از محدوده پنهان می‌مانند.
Create administrator|ایجاد مدیر
Existing administrators|مدیران موجود
Save role & revoke sessions|ذخیره نقش و لغو نشست‌ها
Account profile|پروفایل حساب
Disable access on all assigned nodes|قطع دسترسی در تمام نودهای اختصاص‌یافته
REPRESENTATIVES|نمایندگان
Representative accounts|حساب‌های نمایندگی
Permissions & tariff|مجوزها و تعرفه
Select customer|انتخاب مشتری
Choose an account|انتخاب حساب
Load account|نمایش حساب
Enable representative workspace|فعال‌سازی فضای نمایندگی
Permitted nodes|نودهای مجاز
Custom creation & renewal tariff · integer Toman|تعرفهٔ ساخت و تمدید دلخواه · تومان صحیح
Customer & payments → Plans & pricing|کاربران و پرداخت‌ها ← پلن‌ها و قیمت‌ها
✓ Save permissions|✓ ذخیره مجوزها
Active representatives|نمایندگان فعال
Wallet ledger|دفتر کیف پول
No representatives configured.|نماینده‌ای تنظیم نشده است.
Latest orders|آخرین سفارش‌ها
× Cancel & return credit|× لغو و بازگردانی اعتبار
No orders yet.|هنوز سفارشی وجود ندارد.
. Customer overrides are ignored.|. قیمت‌های اختصاصی مشتری در اینجا اعمال نمی‌شوند.
A link is active. Generate a new one to copy it again.|یک لینک فعال است. برای کپی دوباره، لینک جدید بسازید.
A representative lock stops new sales without disconnecting existing customers. Mode switches do not migrate old payments or wallet balances.|قفل نماینده فروش تازه را متوقف می‌کند و اتصال مشتریان قبلی را قطع نمی‌کند. تغییر مدل، پرداخت‌های قدیمی یا موجودی کیف پول را جابه‌جا نمی‌کند.
Add New User|افزودن کاربر جدید
Add days or data, reset usage, and update the account status. Empty fields keep their current values.|روز یا حجم اضافه کنید، مصرف را ریست کنید و وضعیت حساب را تغییر دهید. فیلد خالی مقدار فعلی را حفظ می‌کند.
After enabling CRL verification, revocations from the primary CA propagate to compatible nodes. Missing endpoints or a different CA leave synchronization pending.|پس از فعال‌سازی بررسی CRL، ابطال گواهی‌های مرجع اصلی به نودهای سازگار منتقل می‌شود. نبود مسیر API یا تفاوت مرجع گواهی، همگام‌سازی را معلق نگه می‌دارد.
Already-paid commission becomes a deduction from future earnings. Reserved earnings require rejecting their settlement first.|پورسانت پرداخت‌شده از درآمد آینده کسر می‌شود. برای درآمد رزروشده، ابتدا درخواست تسویه را رد کنید.
BEENY PARTNERS · OWNER|نمایندگان بنی · مالک
BULK OPERATIONS|عملیات گروهی
Base + days × day rate + GB × GB rate + extra devices × device rate. Set a positive rate to offer custom services. Preset services keep their approved prices.|مبلغ پایه + روز × تعرفه روز + گیگابایت × تعرفه حجم + دستگاه اضافه × تعرفه دستگاه. برای سرویس دلخواه، تعرفهٔ مثبت تعیین کنید. پلن آماده قیمت مصوب خودش را دارد.
Blue: direct invoiced sales. Purple: representative invoiced sales. Green/red: net verified cash receipts after refunds. Wallet spending is a sale, not new cash. Credit grants and internal offsets are excluded. Older payments without retained verification records cannot be reconstructed automatically.|آبی: فروش مستقیم فاکتورشده. بنفش: فروش نماینده. سبز/قرمز: خالص وجه تأییدشده پس از بازپرداخت. خرج کیف پول فروش است، نه دریافت وجه تازه. اعطای اعتبار و تهاتر داخلی محاسبه نمی‌شوند. پرداخت قدیمی بدون سابقهٔ تأیید قابل بازسازی خودکار نیست.
Catalog prices and custom tariffs are calculated on the server. Unpaid sales are invoiced without counting cash.|قیمت پلن و تعرفهٔ دلخواه روی سرور محاسبه می‌شود. فروش پرداخت‌نشده فاکتور می‌شود اما دریافت وجه محسوب نمی‌شود.
Choose a representative to set their sales boundaries.|برای تعیین محدودهٔ فروش، نماینده را انتخاب کنید.
Choose the combined profile or download one of this account's allowed nodes.|کانفیگ ترکیبی یا کانفیگ یکی از نودهای مجاز این حساب را دانلود کنید.
Choose the explicit service policy in the user editor or Customer & payments → Renewal plans. Existing accounts remain metered; a zero quota keeps its previous unlimited behavior. Both the primary server and remote nodes need Linux TUN, HTB/IFB and the updated Beeny speed agent. OpenVPN DCO and multiple TUN interfaces require deployment changes and are rejected automatically.|سیاست سرویس را در ویرایش کاربر یا پلن‌های تمدید انتخاب کنید. حساب‌های قبلی حجمی باقی می‌مانند؛ حجم صفر رفتار نامحدود قبلی را حفظ می‌کند. سرور اصلی و نودها به Linux TUN، ‏HTB/IFB و ایجنت سرعت به‌روز نیاز دارند. DCO و چند رابط TUN به تغییر نصب نیاز دارند و خودکار پذیرفته نمی‌شوند.
Commission model · replaces prepaid creation for this representative|مدل پورسانتی · جایگزین ساخت پیش‌پرداخت این نماینده
Community links, support identity, video tutorials and login announcements.|لینک‌های جامعه، هویت پشتیبانی، آموزش‌های ویدئویی و اطلاعیه‌های ورود.
Configure commission selling|تنظیم فروش پورسانتی
Configure representatives and node grants first.|ابتدا نمایندگان و نودهای مجاز را تنظیم کنید.
Create a bot with @BotFather. Both the customer and admin must start the bot. Run /id in a private chat to see your numeric chat ID.|با BotFather ربات بسازید. مشتری و مدیر هر دو باید ربات را شروع کنند. برای دیدن شناسهٔ عددی چت، دستور /id را در چت خصوصی بفرستید.
Create a secret link for this account. Creating another link immediately revokes the old one.|برای حساب لینک محرمانه بسازید. ساخت لینک تازه، لینک قبلی را فوراً باطل می‌کند.
Credentials are encrypted at rest. Leave password fields empty to preserve current values. Configure the same shared secret in WordPress.|اطلاعات محرمانه به‌صورت رمزگذاری‌شده ذخیره می‌شوند. برای حفظ رمز فعلی، فیلد را خالی بگذارید. همین کلید مشترک را در وردپرس نیز ثبت کنید.
Custom tariff: base + GB × rate + days × rate + additional devices × rate. Configure it in Customer & payments → Pricing. Unlimited data requires a catalog plan with a fair-use allowance.|تعرفهٔ دلخواه: مبلغ پایه + حجم × تعرفه + روز × تعرفه + دستگاه اضافه × تعرفه. در بخش قیمت‌گذاری تنظیم کنید. حجم نامحدود به پلن آماده با حد مصرف منصفانه نیاز دارد.
Customers pay the main manager. Enable individual plans and define a base price and maximum selling price. Existing orders keep their snapshots.|مشتریان به مدیر اصلی پرداخت می‌کنند. پلن‌ها، قیمت پایه و سقف فروش را تعیین کنید. مشخصات ثبت‌شدهٔ سفارش‌های قبلی حفظ می‌شوند.
Days|روز
Disconnect ends this session. A device with a valid shared configuration can reconnect. The account-wide disable button blocks reconnections on nodes that confirm the change. Permanent blocking of one device requires a separate certificate for that device.|قطع اتصال فقط همین نشست را می‌بندد. دستگاه با کانفیگ مشترک معتبر می‌تواند دوباره متصل شود. غیرفعال‌سازی حساب، اتصال مجدد را روی نودهای تأییدکننده مسدود می‌کند. مسدودسازی دائمی یک دستگاه به گواهی اختصاصی آن نیاز دارد.
English title|عنوان انگلیسی
Estimates require at least 24 hours and representative load. They are advisory, low confidence and never block account creation. Hardware cannot determine how many accounts you should sell.|برآورد به حداقل ۲۴ ساعت و بار واقعی نیاز دارد. تخمینی با اطمینان پایین است و ساخت حساب را محدود نمی‌کند. مشخصات سخت‌افزار به‌تنهایی تعداد حساب قابل فروش را تعیین نمی‌کند.
Fair-use speed limits|محدودیت سرعت مصرف منصفانه
INFRASTRUCTURE / LIVE OBSERVABILITY|زیرساخت / پایش زنده
If the hostname or port changes, the customer must download and import the new profile. Saving here does not change the OpenVPN listening port, routing or certificates.|اگر نام میزبان یا پورت تغییر کند، کاربر باید کانفیگ تازه دانلود و وارد کند. ذخیره در اینجا، پورت شنود اوپن‌وی‌پی‌ان، مسیریابی یا گواهی‌ها را تغییر نمی‌دهد.
Immutable earnings & refund adjustments|درآمد ثابت و اصلاحات بازپرداخت
Live OpenVPN sessions, grouped by server. IP addresses identify connections; OpenVPN does not report a phone model or hardware ID.|نشست‌های زندهٔ اوپن‌وی‌پی‌ان به تفکیک سرور. آی‌پی اتصال را مشخص می‌کند؛ اوپن‌وی‌پی‌ان مدل گوشی یا شناسهٔ سخت‌افزار را گزارش نمی‌کند.
Manage node grants and prepaid representatives. Commission selling has a separate financial workspace.|مدیریت نودهای مجاز و نمایندگان پیش‌پرداخت. فروش پورسانتی فضای مالی جداگانه دارد.
Measured on each server's default network interface, including all applications. These counters survive account deletion and quota resets. Recording begins when telemetry is enabled; this is measured traffic, not an imported provider invoice.|اندازه‌گیری روی رابط پیش‌فرض شبکهٔ هر سرور و شامل تمام برنامه‌هاست. حذف حساب و ریست حجم، شمارنده را پاک نمی‌کند. ثبت از زمان فعال‌شدن پایش آغاز می‌شود؛ این مقدار ترافیک اندازه‌گیری‌شده است، نه صورتحساب واردشده از میزبان.
New downloads from the customer portal use the saved address and port. Imported OpenVPN profiles do not update themselves. For a stable hostname, keep its DNS record in DNS-only mode and update its IP when moving the VPN; certificates, keys, port and server configuration must remain compatible.|دانلودهای جدید از آدرس و پورت ذخیره‌شده استفاده می‌کنند. کانفیگ واردشده خودکار به‌روز نمی‌شود. برای نام میزبان ثابت، رکورد DNS را بدون پروکسی نگه دارید و هنگام جابه‌جایی سرور آی‌پی آن را عوض کنید؛ گواهی، کلید، پورت و تنظیمات باید سازگار بمانند.
New passwords are held temporarily in this tab for up to 10 minutes. After generating the link, copy this ready-to-send Persian message.|رمز تازه حداکثر ۱۰ دقیقه در همین تب نگهداری می‌شود. پس از ساخت لینک، متن فارسی آمادهٔ ارسال را کپی کنید.
No nodes available. Restart the panel service to register the primary server.|نودی موجود نیست. برای ثبت سرور اصلی، سرویس پنل را راه‌اندازی مجدد کنید.
No recorded refunds.|بازپرداختی ثبت نشده است.
One-level commissions, verified payments and traceable settlements. Purchase wallets stay separate.|پورسانت تک‌سطحی، پرداخت تأییدشده و تسویهٔ قابل پیگیری. کیف پول خرید جداست.
PARTNER DIRECTORY|فهرست نمایندگان
PARTNER POLICY|سیاست نمایندگی
PAYOUT DESK|میز تسویه
Preset creation and renewal plans use the approved retail prices from|پلن‌های آمادهٔ ساخت و تمدید از قیمت مصوب این بخش استفاده می‌کنند:
Preview before applying. Up to 100 accounts per job; existing consumption and historical traffic are preserved.|قبل از اعمال پیش‌نمایش بگیرید. هر عملیات حداکثر ۱۰۰ حساب؛ مصرف فعلی و سوابق ترافیک حفظ می‌شوند.
Re-assign Nodes|تخصیص دوبارهٔ نودها
Real measurements. Every node. Capacity guidance grounded in observed load.|اندازه‌گیری واقعی برای هر نود؛ راهنمای ظرفیت بر اساس بار مشاهده‌شده.
Receipts are sent as documents. Customers link their account using a one-time button from their private page. Username alone never grants account access. Bot links expire after 30 days; rotating a customer's private link revokes bot access.|رسید به‌صورت فایل ارسال می‌شود. مشتری با دکمهٔ یک‌بارمصرف صفحهٔ خصوصی، حساب را متصل می‌کند. نام کاربری به‌تنهایی دسترسی نمی‌دهد. لینک ربات پس از ۳۰ روز منقضی می‌شود و تعویض لینک خصوصی مشتری، دسترسی ربات را لغو می‌کند.
Record full refund & suspend account|ثبت بازپرداخت کامل و تعلیق حساب
Refund transfer history|سوابق انتقال بازپرداخت
Refund transfer reference|شماره پیگیری بازپرداخت
Refunds require a completed manual bank transfer. They suspend account access; consumed data and historical records remain intact.|بازپرداخت به انتقال بانکی انجام‌شده نیاز دارد. دسترسی حساب تعلیق می‌شود؛ حجم مصرف‌شده و سوابق حفظ می‌شوند.
Representatives at a glance|نمایندگان در یک نگاه
Sales that add up.|فروش با حساب روشن.
Select where this account may connect. The primary server is a selectable node, just like every other location.|نودهای مجاز اتصال را انتخاب کنید. سرور اصلی مانند لوکیشن‌های دیگر قابل انتخاب است.
Separate credentials for the customer page. These never grant admin access. Changing the password revokes previous sessions and bot bindings.|اطلاعات ورود جداگانهٔ صفحهٔ کاربر است و دسترسی مدیریت نمی‌دهد. تغییر رمز، نشست‌ها و اتصال‌های قبلی ربات را لغو می‌کند.
The account was saved, but a remote node did not confirm the update. Check the panel service log and update Beeny Agent on that node.|حساب ذخیره شد اما نود راه‌دور تغییر را تأیید نکرد. لاگ سرویس پنل را بررسی و ایجنت آن نود را به‌روز کنید.
These figures count client VPN bytes (received + sent). They do not include non-VPN system traffic. The ledger is independent of a user's current quota and remains intact after a user is deleted or usage is reset. Data collection starts when this version is installed; earlier usage cannot be reconstructed from current sessions.|این ارقام مجموع بایت دریافت و ارسال کاربران وی‌پی‌ان هستند و ترافیک سایر برنامه‌ها را شامل نمی‌شوند. دفتر ترافیک از حجم فعلی کاربر مستقل است و با حذف حساب یا ریست مصرف پاک نمی‌شود. ثبت از نصب این نسخه آغاز می‌شود؛ مصرف گذشته از نشست فعلی قابل بازسازی نیست.
Toman total = base fee + GB × GB rate + days × daily rate + extra simultaneous devices × device rate. One device is included. These rates apply to custom services only.|مبلغ تومان = هزینهٔ پایه + حجم × تعرفهٔ گیگ + روز × تعرفهٔ روز + دستگاه هم‌زمان اضافه × تعرفهٔ دستگاه. یک دستگاه در قیمت پایه است. این تعرفه‌ها فقط برای سرویس دلخواه هستند.
Traffic is the physical host interface, including services other than OpenVPN. Mbps = megabits per second. Peaks are sampled; short bursts may be missed. Probe time measures panel-to-agent API response, not the customer's VPN latency. Raw history: 48 hours; hourly peaks: 90 days. Gaps remain unknown.|ترافیک مربوط به رابط فیزیکی میزبان و شامل سرویس‌های غیر وی‌پی‌ان است. Mbps یعنی مگابیت بر ثانیه. اوج‌ها نمونه‌برداری می‌شوند و جهش کوتاه ممکن است ثبت نشود. زمان بررسی، پاسخ API ایجنت به پنل است، نه پینگ وی‌پی‌ان مشتری. تاریخچهٔ خام: ۴۸ ساعت؛ اوج ساعتی: ۹۰ روز. فاصله‌های بدون داده نامشخص می‌مانند.
Upload MP4/WebM (up to 200 MB) or use a direct HTTPS URL. MP4 with H.264/AAC is recommended. Videos load only when the customer presses Play; covers are saved as landscape 16:9 WebP (1280 × 720), without cropping text or logos.|فایل MP4 یا WebM تا ۲۰۰ مگابایت آپلود کنید یا لینک مستقیم HTTPS بدهید. MP4 با H.264/AAC پیشنهاد می‌شود. ویدئو فقط با زدن پخش بارگیری می‌شود؛ کاور با نسبت افقی ۱۶:۹ و فرمت WebP، بدون بریدن متن و لوگو ذخیره می‌شود.
Use numeric chat IDs, separated by commas. Up to 10 additional recipients; each admin must start the bot.|شناسه‌های عددی چت را با ویرگول جدا کنید. حداکثر ۱۰ گیرندهٔ بیشتر؛ هر مدیر باید ربات را شروع کند.
Users List|فهرست کاربران
Validity (Days from first connect)|اعتبار (روز از اولین اتصال)
Validity (Days)|اعتبار (روز)
Verified, delivered sales will appear here.|فروش تأییدشده و تحویل‌شده اینجا نمایش داده می‌شود.
accounts provisioned|حساب تحویل‌شده
means that many devices were seen connected while measured resources stayed below the guidance thresholds; it does not prove they were all downloading.|یعنی این تعداد دستگاه هنگام آزادبودن منابع مشاهده شده‌اند؛ این عدد ثابت نمی‌کند همه هم‌زمان دانلود می‌کرده‌اند.
selected · maximum 100 accounts. Searching keeps your selection.|انتخاب‌شده · حداکثر ۱۰۰ حساب. جست‌وجو انتخاب شما را حفظ می‌کند.
↗ Commission sales & settlements|↗ فروش پورسانتی و تسویه‌ها
Fixed data · stop at limit|حجم مشخص · قطع در پایان حجم
Fair use · reduce speed at limit|مصرف منصفانه · کاهش سرعت در پایان حجم
Service policy|سیاست سرویس
Speed after fair use|سرعت پس از حد مصرف منصفانه
Download · kbit/s|دانلود · کیلوبیت بر ثانیه
Upload · kbit/s|آپلود · کیلوبیت بر ثانیه
Domain|دامنه
Issuer|صادرکننده
Expiry (UTC)|انقضا (UTC)
Days remaining|روز باقی‌مانده
Certificate status|وضعیت گواهی
Unknown|نامشخص
Service|سرویس
Cipher|الگوریتم رمزنگاری
Authentication digest|الگوریتم احراز اصالت
Address pool|محدودهٔ آدرس
Server configuration loaded.|تنظیمات سرور خوانده شد.
Download|دانلود
Restore|بازیابی
No backups yet.|هنوز پشتیبانی ساخته نشده است.
Working…|در حال انجام…
Set up an authenticator|راه‌اندازی رمزساز
Enable two-step verification|فعال‌سازی تأیید دومرحله‌ای
Disable two-step verification|غیرفعال‌سازی تأیید دومرحله‌ای
Lock|قفل
Unlock|بازکردن قفل
Active|فعال
Disabled|غیرفعال
Online|آنلاین
Offline|آفلاین
owner|مالک
support|پشتیبانی
finance|مالی
seller|فروشنده
viewer|مشاهده‌گر
Configured|تنظیم‌شده
Base fee|هزینهٔ پایه
Each day|هر روز
Each GB|هر گیگابایت
Each extra device|هر دستگاه اضافه
Customer page login|ورود صفحهٔ کاربر
Username already exists.|این نام کاربری از قبل وجود دارد.
Days|روز
GB|گیگابایت
Devices|دستگاه‌ها
Badge|نشان
Save changes|ذخیره تغییرات
Security settings saved. Other sessions were revoked.|تنظیمات امنیتی ذخیره شد. نشست‌های دیگر لغو شدند.
2000 kbit/s = 2 Mbps. Fair use needs a positive GB allowance.|۲۰۰۰ کیلوبیت = ۲ مگابیت بر ثانیه. مصرف منصفانه به سقف حجم مثبت نیاز دارد.
WORKSPACE|فضای کاری
Device certificates|گواهی دستگاه‌ها
Wallet & payments|کیف پول و پرداخت‌ها
Persian message|متن فارسی
English message|متن انگلیسی
Icon|آیکن
Delete this item permanently?|این مورد برای همیشه حذف شود؟
'''
PAIRS+='''
CONTROL CENTER|مرکز کنترل
Your workspace, infrastructure and operations. One connected control center.|فضای کاری، زیرساخت و عملیات؛ همه در یک مرکز کنترل منسجم.
Workspace|فضای کاری
Infrastructure|زیرساخت
Operations|عملیات
Account, administrators and access|حساب، مدیران و دسترسی‌ها
Pricing, plans and payment methods|قیمت‌گذاری، پلن‌ها و روش‌های پرداخت
Bots, delivery and notifications|ربات‌ها، ارسال پیام و اعلان‌ها
Community, videos and announcements|جامعه، ویدئوها و اطلاعیه‌ها
Locations, live checks and node endpoints|موقعیت‌ها، بررسی سلامت و آدرس نودها
Certificate health and renewal jobs|وضعیت گواهی و عملیات تمدید
Core facts, sessions and profiles|اطلاعات هسته، نشست‌ها و کانفیگ‌ها
Destination policies and direct routes|قوانین مقصد و مسیرهای مستقیم
Measured load and node capacity|بار اندازه‌گیری‌شده و ظرفیت نودها
Inspect and control running services|بررسی و کنترل سرویس‌های فعال
Account database and complete backups|پایگاه دادهٔ حساب‌ها و پشتیبان کامل
Trace administrative changes|پیگیری تغییرات مدیریتی
Account security, panel access and administrator permissions.|امنیت حساب، دسترسی پنل و مجوزهای مدیران.
Security|امنیت
Changing your credentials signs out existing sessions. Changing the access path also restarts the panel.|تغییر اطلاعات ورود، نشست‌های فعلی را خارج می‌کند. تغییر مسیر دسترسی، پنل را نیز دوباره راه‌اندازی می‌کند.
Only the owner can change panel access.|فقط مالک می‌تواند دسترسی پنل را تغییر دهد.
Two-step verification and recovery codes|تأیید دومرحله‌ای و کدهای بازیابی
Review and revoke management sessions|بررسی و لغو نشست‌های مدیریتی
Global role access|دسترسی سراسری نقش
Selected nodes|نودهای انتخاب‌شده
Node access|دسترسی نود
Saving permissions revokes this administrator’s existing sessions.|ذخیرهٔ مجوزها نشست‌های فعلی این مدیر را لغو می‌کند.
Nodes|نودها
Location|موقعیت
No nodes registered.|هنوز نودی ثبت نشده است.
Primary server|سرور اصلی
Leave blank to keep current value|برای حفظ مقدار فعلی خالی بگذارید
Last check|آخرین بررسی
Latency|تأخیر
Healthy|سالم
Needs check|نیازمند بررسی
Not checked yet|هنوز بررسی نشده
Node health|سلامت نودها
Purpose|کاربرد
Action|عملیات
Actions|عملیات
Panel HTTPS|گواهی HTTPS پنل
Days remaining|روز باقی‌مانده
Verify domain validation|بررسی اعتبارسنجی دامنه
Run a dry-run before relying on automatic renewal.|پیش از اتکا به تمدید خودکار، یک آزمایش تمدید اجرا کنید.
Automatic schedule|زمان‌بندی خودکار
Check certificate now|بررسی گواهی
Certbot renews only when needed. A successful renewal reloads Nginx; VPN profiles are unaffected.|سرت‌بات فقط در صورت نیاز گواهی را تمدید می‌کند. پس از موفقیت، تنظیمات انجین‌اکس بازخوانی می‌شود و کانفیگ وی‌پی‌ان کاربران تغییر نمی‌کند.
Standalone validation needs a compatible webroot, nginx or DNS setup before unattended renewal. The panel reports this limitation instead of silently stopping your web server.|اعتبارسنجی مستقل برای تمدید خودکار به تنظیم سازگار وب‌روت، انجین‌اکس یا DNS نیاز دارد. پنل این محدودیت را اعلام می‌کند و وب‌سرور را خودسرانه متوقف نمی‌کند.
No operation has been requested yet.|هنوز عملیاتی درخواست نشده است.
Renewing the website certificate does not replace customer VPN profiles.|تمدید گواهی وب‌سایت، کانفیگ وی‌پی‌ان کاربران را تعویض نمی‌کند.
Database snapshots and complete panel/VPN archives are listed together below.|نسخه‌های پایگاه داده و پشتیبان کامل پنل و وی‌پی‌ان در فهرست زیر قرار دارند.
Import backup|ورود پشتیبان
Search backups…|جست‌وجوی پشتیبان‌ها…
Loading backups…|در حال دریافت فهرست پشتیبان‌ها…
Created|زمان ساخت
Size|حجم
The database includes accounts and financial history. A complete backup also includes private uploads and VPN keys. Store the signing key separately for disaster recovery.|پایگاه داده شامل حساب‌ها و سوابق مالی است. پشتیبان کامل، فایل‌های خصوصی و کلیدهای وی‌پی‌ان را هم دارد. کلید امضای پشتیبان را برای بازیابی اضطراری جدا نگه دارید.
CA, server and client certificates follow the PKI audit and CRL workflow. Review the installed audit timer before changing them.|گواهی مرجع، سرور و کاربران زیر نظر فرایند بررسی PKI و فهرست ابطال هستند. پیش از تغییر، زمان‌بندی بررسی نصب‌شده را بازبینی کنید.
VPN certificates|گواهی‌های وی‌پی‌ان
Network changes and VPN restarts require a planned maintenance window. Nothing is reset from this page.|تغییرات شبکه و راه‌اندازی مجدد وی‌پی‌ان را در زمان نگهداری انجام دهید. این صفحه چیزی را بازنشانی نمی‌کند.
Restarting OpenVPN disconnects current sessions on this server.|راه‌اندازی مجدد اوپن‌وی‌پی‌ان اتصال‌های فعلی این سرور را قطع می‌کند.
A focused catalog. Each service has its own editor.|فهرست منظم سرویس‌ها؛ هر سرویس صفحهٔ ویرایش جداگانه دارد.
Search plans…|جست‌وجوی پلن‌ها…
No plans yet.|هنوز پلنی ساخته نشده است.
Applied when an administrator creates an account from this plan.|هنگام ساخت حساب از این پلن توسط مدیر اعمال می‌شود.
Blocking|مسدودسازی
Iran & direct routes|ایران و مسیر مستقیم
Direct IPv4 networks|شبکه‌های IPv4 مستقیم
Direct domains · one per line|دامنه‌های مستقیم؛ هر دامنه در یک خط
Port restrictions & BitTorrent|محدودیت پورت و بیت‌تورنت
Domains are resolved to current IPv4 addresses. Shared addresses may affect other websites; preview shows the exact rules before applying.|دامنه‌ها به آدرس‌های IPv4 فعلی تبدیل می‌شوند. مسدودکردن آدرس مشترک ممکن است روی سایت‌های دیگر اثر بگذارد؛ قوانین دقیق را پیش از اعمال در پیش‌نمایش بررسی کنید.
Encrypted or alternate-port BitTorrent requires traffic inspection beyond port rules. This switch does not claim to detect all torrent traffic.|تشخیص بیت‌تورنت رمزگذاری‌شده یا روی پورت‌های دیگر به بررسی فراتر از قوانین پورت نیاز دارد. این گزینه همهٔ ترافیک تورنت را شناسایی نمی‌کند.
Import registered Iran IPv4 resources, review them, then preview. Nothing is applied by importing.|فهرست IPv4 ثبت‌شده برای ایران را دریافت و بررسی کنید، سپس پیش‌نمایش بگیرید. دریافت فهرست هیچ قانونی را اعمال نمی‌کند.
Country registration is not guaranteed physical geolocation. Domains use a current IPv4 snapshot, not every .ir domain. Client bypass takes effect after a planned VPN restart and reconnect, subject to client route support.|کشور ثبت‌شده لزوماً موقعیت واقعی شبکه نیست. دامنه‌ها با IPv4 فعلی‌شان ثبت می‌شوند و شامل همهٔ دامنه‌های ir نیستند. مسیر مستقیم پس از راه‌اندازی برنامه‌ریزی‌شدهٔ وی‌پی‌ان و اتصال دوباره، با پشتیبانی کلاینت اعمال می‌شود.
Enable WARP egress for this node|فعال‌سازی خروجی وارپ برای این نود
Select the actual WARP TUN or WireGuard interface. The server default route stays unchanged. Verify client traffic before confirming; a disconnected egress tunnel can interrupt VPN traffic.|رابط واقعی تونل وارپ را انتخاب کنید. مسیر پیش‌فرض سرور تغییر نمی‌کند. پیش از تأیید، ترافیک کاربر را بررسی کنید؛ قطع تونل خروجی می‌تواند ترافیک وی‌پی‌ان را مختل کند.
Remove representative|حذف نماینده
Child accounts|حساب‌های زیرمجموعه
Review before removal|بررسی پیش از حذف
Financial history is preserved. Removing an account does not refund a completed sale.|سوابق مالی حفظ می‌شود. حذف حساب، فروش تکمیل‌شده را بازپرداخت نمی‌کند.
Resolve these items first|ابتدا این موارد را تعیین تکلیف کنید
Clear removal hold|لغو توقف فرایند حذف
Type the representative username|نام کاربری نماینده را وارد کنید
Confirm removal|تأیید حذف
Settle the representative debt before removal.|پیش از حذف، بدهی نماینده را تسویه کنید.
Settle outstanding representative earnings first.|ابتدا درآمد پرداخت‌نشدهٔ نماینده را تعیین تکلیف کنید.
Resolve pending payout requests.|درخواست‌های برداشت معلق را تعیین تکلیف کنید.
Resolve remaining wallet balances for these accounts.|موجودی باقی‌ماندهٔ کیف پول این حساب‌ها را تعیین تکلیف کنید.
Resolve pending receipts.|رسیدهای در انتظار بررسی را تعیین تکلیف کنید.
Reconcile open online payment attempts.|پرداخت‌های آنلاین باز را تطبیق و تعیین تکلیف کنید.
Wait for account provisioning to finish.|منتظر تکمیل ساخت حساب‌ها بمانید.
Resolve pending representative sales.|فروش‌های معلق نماینده را تعیین تکلیف کنید.
Resolve pending account cancellations.|درخواست‌های لغو حساب را تعیین تکلیف کنید.
Search all accounts…|جست‌وجو بین همهٔ حساب‌ها…
'''
PAIRS+='''
A queued job is not a successful renewal. Its final result appears below.|قرارگرفتن در صف به معنی تمدید موفق نیست. نتیجهٔ نهایی در پایین نمایش داده می‌شود.
Certificate health, scheduled renewal and a visible result for every operation.|وضعیت گواهی، تمدید زمان‌بندی‌شده و نتیجهٔ مشخص هر عملیات.
Complimentary allowance|اعتبار هدیه
Confirmation required|نیازمند تأیید
Gifts increase the service allowance, never the invoice price.|هدیه به اعتبار سرویس اضافه می‌شود و هزینهٔ فاکتور را افزایش نمی‌دهد.
IPv4 network rules are applied only to clients on the selected VPN node.|قوانین IPv4 فقط روی کاربران وی‌پی‌ان نود انتخاب‌شده اعمال می‌شود.
Load Iran prefixes · RIPE|دریافت شبکه‌های ایران از RIPE
Locations, connectivity and health checks in one workspace.|موقعیت‌ها، اتصال‌ها و بررسی سلامت در یک فضای کاری.
Protect account data and restore with a clear, verified history.|حفاظت از اطلاعات حساب‌ها و بازیابی با سابقهٔ روشن و قابل بررسی.
Real service state, controlled actions and clear outcomes.|وضعیت واقعی سرویس‌ها، عملیات کنترل‌شده و نتایج مشخص.
Roles and node access, managed in the General workspace.|مدیریت نقش‌ها و دسترسی نودها در تنظیمات عمومی.
Route VPN IPv4 traffic through an existing connected tunnel.|هدایت ترافیک IPv4 وی‌پی‌ان از تونل خروجی متصل.
Selected destinations use the customer’s original internet connection.|مقصدهای انتخاب‌شده از اینترنت اصلی کاربر عبور می‌کنند.
Separate controls for blocking, direct routing and an existing WARP tunnel.|کنترل جداگانهٔ مسدودسازی، مسیر مستقیم و تونل وارپ موجود.
Service allowance, price and complimentary benefits.|اعتبار سرویس، قیمت و مزایای هدیه.
Your active VPN core, without hidden resets or unrelated controls.|اطلاعات هستهٔ فعال وی‌پی‌ان و کنترل‌های مرتبط آن.
Destination blocking|مسدودسازی مقصد
WARP egress|خروجی وارپ
Core configuration|تنظیمات هسته
Service details|جزئیات سرویس
Price & policy|قیمت و قوانین
Panel certificate|گواهی پنل
Renewal workflow|فرایند تمدید
Last operation|آخرین عملیات
Validation method|روش اعتبارسنجی
An active renewal timer was detected.|زمان‌بندی فعال تمدید شناسایی شد.
No active renewal timer was detected.|زمان‌بندی فعالی برای تمدید پیدا نشد.
Standalone validation must be reconfigured before these renewal actions can run.|پیش از اجرای تمدید، روش اعتبارسنجی مستقل باید تنظیم مجدد شود.
Queueing operation…|در حال ثبت عملیات…
The job is still pending. Refresh status or inspect its journal before retrying.|عملیات هنوز در انتظار است. پیش از تلاش دوباره، وضعیت را تازه‌سازی یا گزارش سرویس را بررسی کنید.
No child accounts.|حساب زیرمجموعه‌ای وجود ندارد.
Remove this representative and all listed child accounts; preserve financial history.|این نماینده و همهٔ حساب‌های فهرست‌شده حذف شوند؛ سوابق مالی حفظ شود.
A removal hold is active. Failed deletion can be retried, or the hold can be cleared without restoring deleted accounts.|فرایند حذف متوقف شده است. می‌توانید دوباره تلاش کنید یا توقف را بردارید؛ حساب‌های حذف‌شده بازنمی‌گردند.
Management and customer pages|صفحه‌های مدیریت و کاربران
Notifications, payments and background work|اعلان‌ها، پرداخت‌ها و کارهای پس‌زمینه
VPN connections and transport|اتصال‌ها و انتقال ترافیک وی‌پی‌ان
Iran prefixes imported for review.|شبکهٔ ایران برای بررسی دریافت شد.
Imported for review. Preview before applying.|برای بررسی دریافت شد. پیش از اعمال، پیش‌نمایش بگیرید.
'''
PAIRS+='''
Change language|تغییر زبان
'''
PAIRS+='''
Backup list unavailable. Refresh after checking the service.|فهرست پشتیبان‌ها در دسترس نیست. پس از بررسی سرویس، فهرست را تازه‌سازی کنید.
'''
PAIRS+='''
Error loading users|دریافت کاربران ناموفق بود
No users found.|کاربری پیدا نشد.
Smart Multi-Location|چند موقعیت هوشمند
No servers|بدون سرور
Allowed Servers|سرورهای مجاز
active|فعال
inactive|غیرفعال
disabled|غیرفعال
failed|خطا
activating|در حال راه‌اندازی
'''
PAIRS+='''
Unlimited|نامحدود
Expired|منقضی
'''
PAIRS+='''
Official client installation does not register, connect or change server routing. Existing third-party installations are preserved.|نصب کلاینت رسمی، ثبت‌نام، اتصال یا مسیریابی سرور را تغییر نمی‌دهد. نصب‌های قبلی و ابزارهای دیگر حفظ می‌شوند.
WARP package status|وضعیت بستهٔ وارپ
Install WARP client|نصب کلاینت وارپ
Remove managed WARP|حذف وارپ نصب‌شده با پنل
Checking the running VPN configuration…|در حال بررسی تنظیمات در حال اجرای وی‌پی‌ان…
Restart VPN & deliver routes|راه‌اندازی مجدد و ارسال مسیرها
This deliberate action reconnects all VPN sessions on this node. It never resets accounts or traffic.|این عملیات اتصال‌های وی‌پی‌ان همین نود را دوباره برقرار می‌کند. حساب‌ها و مصرف را بازنشانی نمی‌کند.
Applied rule counters & diagnostics|شمارندهٔ قوانین و عیب‌یابی
Server configuration is loaded. Reconnect the client to receive current routes.|تنظیمات سرور خوانده شده است. برای دریافت مسیرهای فعلی، کلاینت را دوباره متصل کنید.
Direct routes require a planned VPN restart, then client reconnect.|مسیرهای مستقیم به راه‌اندازی برنامه‌ریزی‌شدهٔ وی‌پی‌ان و اتصال دوبارهٔ کلاینت نیاز دارند.
Restart OpenVPN on this node? All current sessions will reconnect.|اوپن‌وی‌پی‌ان این نود دوباره راه‌اندازی شود؟ همهٔ نشست‌های فعلی دوباره متصل می‌شوند.
No rule counters available.|شمارندهٔ قوانین در دسترس نیست.
Run this WARP package operation on the selected node? No automatic registration or connection is performed.|عملیات بستهٔ وارپ روی نود انتخاب‌شده اجرا شود؟ ثبت‌نام یا اتصال خودکار انجام نمی‌شود.
Installed|نصب‌شده
Not installed|نصب نشده
Managed by panel|مدیریت‌شده با پنل
External or absent|نصب خارجی یا نصب‌نشده
Browser details|جزئیات مرورگر
Address|آدرس
Last seen|آخرین حضور
Payment status|وضعیت پرداخت
Request|درخواست
Amount|مبلغ
Open|مشاهده
Previous|قبلی
Next|بعدی
Payment settings|تنظیمات پرداخت
Pending|در انتظار بررسی
Completed|تأییدشده
Rejected|ردشده
All|همه
The device model is shown only when the browser reports it; otherwise the operating system and browser are displayed.|مدل دستگاه فقط وقتی نمایش داده می‌شود که مرورگر آن را ارسال کند؛ در غیر این صورت سیستم‌عامل و مرورگر نشان داده می‌شود.
Ten distinct excess connection attempts from a secondary IP within ten minutes block that IP for this account for thirty minutes. Existing primary peers are protected. Immediate rejection requires the admission hook on every assigned node; otherwise the periodic connection monitor removes excess sessions.|پس از ۱۰ تلاش مجزای اتصال اضافه از IP ثانویه در ۱۰ دقیقه، همان IP برای این حساب ۳۰ دقیقه مسدود می‌شود. IP اتصال‌های اصلی محافظت می‌شود. رد فوری به فعال‌بودن admission روی تمام نودهای حساب نیاز دارد؛ در غیر این صورت پایش دوره‌ای اتصال اضافه را قطع می‌کند.
'''
PAIRS+='''
Temporary peer restrictions|محدودیت موقت IPها
Restrictions apply to one account and IP, not to every user on that internet connection.|محدودیت برای یک حساب و IP است، نه برای همهٔ کاربران آن اینترنت مشترک.
No temporary restrictions.|محدودیت موقتی وجود ندارد.
Clear restriction|رفع محدودیت
Clear this account/IP restriction?|محدودیت این حساب و IP برداشته شود؟
Peer restriction cleared. Account status and traffic are unchanged.|محدودیت IP برداشته شد. وضعیت حساب و مصرف تغییر نکرد.
'''
PAIRS+='''
This device|این دستگاه
Other device|دستگاه دیگر
Sign out|خروج
Revoke session|لغو نشست
Logout|خروج
'''
PAIRS+='''
Large route lists can slow initial connection or exceed a client’s limits. Review imported networks; a smaller destination list is preferable when possible.|فهرست بزرگ مسیرها ممکن است اتصال اولیه را کند کند یا از محدودیت کلاینت بیشتر باشد. شبکه‌های واردشده را بازبینی کنید؛ در صورت امکان فهرست کوچک‌تر مقصدها بهتر است.
'''
PAIRS+='''
WARP package job queued. Refresh to view the verified result.|عملیات بستهٔ وارپ در صف قرار گرفت. برای دیدن نتیجهٔ نهایی وضعیت را تازه کنید.
Official WARP client installed. It is not registered or connected; VPN routing is unchanged.|کلاینت رسمی وارپ نصب شد. هنوز ثبت‌نام یا متصل نشده و مسیریابی وی‌پی‌ان تغییر نکرده است.
Panel-managed WARP package removed. No VPN data or certificates changed.|بستهٔ وارپِ مدیریت‌شده با پنل حذف شد. اطلاعات و گواهی‌های وی‌پی‌ان تغییر نکردند.
WARP package operation failed. Inspect the beeny-warp-package journal; success is not assumed.|عملیات بستهٔ وارپ ناموفق بود. گزارش سرویس beeny-warp-package را بررسی کنید.
The package job is no longer active. Check its journal before retrying.|کار بسته دیگر فعال نیست. پیش از تلاش دوباره گزارش آن را بررسی کنید.
Only a panel-managed WARP installation with no active or pending egress policy may be removed.|فقط وارپ نصب‌شده با پنل و بدون سیاست خروجی فعال یا معلق قابل حذف است.
WARP is already installed. Existing installations are not replaced.|وارپ از قبل نصب است. نصب قبلی جایگزین نمی‌شود.
Disable existing egress policies before installing another WARP client.|پیش از نصب کلاینت وارپ دیگر، سیاست‌های خروجی موجود را غیرفعال کنید.
OpenVPN restarted. Existing sessions reconnect and receive the direct routes. No traffic or certificates were reset.|اوپن‌وی‌پی‌ان دوباره راه‌اندازی شد. نشست‌ها پس از اتصال دوباره مسیرهای مستقیم را دریافت می‌کنند. مصرف و گواهی‌ها بازنشانی نشدند.
A destination cannot be both blocked and routed directly. Remove the overlapping entries.|یک مقصد نمی‌تواند هم مسدود و هم مستقیم باشد. موارد هم‌پوشان را حذف کنید.
running|در حال اجرا
succeeded|موفق
interrupted|متوقف‌شده
'''
TRANSLATIONS=dict(line.split('|',1) for line in PAIRS.splitlines() if '|' in line)
TRANSLATIONS.update({
  "Transport & ports": "پروتکل و پورت‌ها",
  "Paired tunnels": "تونل بین دو سرور",
  "Change the actual OpenVPN listener and keep new client downloads in sync.": "پورت و پروتکل سرویس واقعی OpenVPN را تغییر دهید؛ کانفیگ‌های جدید با آن هماهنگ می‌شوند.",
  "One active transport per node. TCP and UDP ports are saved separately. Switching restarts this node VPN and reconnects its users. Certificates and account traffic are preserved.": "هر نود یک پروتکل فعال دارد. پورت‌های TCP و UDP جدا ذخیره می‌شوند. تغییر پروتکل، سرویس همان نود را ری‌استارت می‌کند و کاربران دوباره متصل می‌شوند. گواهی‌ها و مصرف حساب‌ها حفظ می‌شوند.",
  "Open the selected protocol and port in the provider firewall first. Existing imported profiles must be downloaded again. Confirm within 120 seconds after testing a new connection; otherwise the previous listener is restored.": "ابتدا پورت و پروتکل انتخابی را در فایروال دیتاسنتر باز کنید. کانفیگ‌های قبلی باید دوباره دانلود و وارد برنامه شوند. پس از آزمایش اتصال، تا ۱۲۰ ثانیه تغییر را تأیید کنید؛ در غیر این صورت تنظیم قبلی برمی‌گردد.",
  "Active transport": "پروتکل فعال",
  "TCP port": "پورت TCP",
  "UDP port": "پورت UDP",
  "Apply listener": "اعمال روی سرویس",
  "Confirm connection works": "اتصال سالم است؛ تأیید تغییر",
  "Roll back": "بازگشت به تنظیم قبلی",
  "I accept that users on this node will reconnect.": "می‌پذیرم که اتصال کاربران این نود هنگام تغییر دوباره برقرار می‌شود.",
  "Applied temporarily. Test a new VPN connection and confirm within 120 seconds.": "تغییر موقت اعمال شد. اتصال جدید را آزمایش کنید و تا ۱۲۰ ثانیه تأیید کنید.",
  "Listener verified. New downloads use the active transport and port.": "تنظیم سرویس بررسی شد. کانفیگ‌های جدید از پورت و پروتکل فعال استفاده می‌کنند.",
  "Connect an entry host to an OpenVPN exit node in any country, with direct and tunnel downloads.": "سرور ورودی را به نود OpenVPN خروجی در هر کشوری وصل کنید؛ دانلود مستقیم و تونلی کنار هم در دسترس است.",
  "Install the verified engine on both hosts using the Beeny SSH menu. Create the entry host, then import its private invitation on the exit node. Either host can be in any country. Keep the invitation secret.": "موتور تونل را از منوی SSH بنی روی هر دو سرور نصب کنید. پنل دیگری لازم نیست. ابتدا سرور ورودی را بسازید، سپس دعوت‌نامه خصوصی آن را روی نود خروجی وارد کنید. دعوت‌نامه را محرمانه نگه دارید.",
  "TLS, WebSocket + TLS and QUIC encrypt the link with a pinned certificate. They do not guarantee access during a national shutdown or prevent fingerprinting. The entry and exit hosts must be able to reach each other.": "حالت‌های TLS، WebSocket + TLS و QUIC ارتباط را با گواهی تأییدشده رمز می‌کنند. عبور هنگام قطع اینترنت بین‌الملل یا غیرقابل‌شناسایی بودن تضمین نمی‌شود. دو سرور باید امکان ارتباط با یکدیگر داشته باشند.",
  "Selected host": "سرور انتخاب‌شده",
  "Enable tunnel": "فعال‌سازی تونل",
  "Disable tunnel": "غیرفعال‌سازی تونل",
  "Export private invitation": "دریافت دعوت‌نامه خصوصی",
  "1 · Entry host": "۱ · میزبان ورودی",
  "2 · Exit host": "۲ · میزبان خروجی",
  "Entry public domain or IP": "دامنه یا IP عمومی سرور ورودی",
  "Tunnel transport": "روش انتقال تونل",
  "Control port": "پورت ارتباط دو سرور",
  "Public VPN port": "پورت ورودی کاربران",
  "Create entry & download invitation": "ساخت ورودی و دریافت دعوت‌نامه",
  "Private pairing invitation": "دعوت‌نامه خصوصی اتصال",
  "Pair & enable": "اتصال دو سرور و فعال‌سازی",
  "Connection notes": "نکات اتصال",
  "Open the control port (TCP for TLS/WebSocket, TCP and UDP for QUIC) and the public VPN port in the provider firewall. Use ports not occupied by this host VPN or website.": "پورت ارتباط دو سرور را با TCP برای TLS و WebSocket، و با TCP و UDP برای QUIC باز کنید. پورت ورودی کاربران را هم با پروتکل VPN در فایروال دیتاسنتر باز کنید. پورت‌ها نباید در اختیار VPN یا وب‌سایت این سرور باشند.",
  "Select the exit node above. Paste the invitation exported by the entry Beeny panel. The current OpenVPN transport and port are detected automatically. No CA or user certificate is replaced.": "نود خروجی را از بالای صفحه انتخاب کنید. دعوت‌نامه دریافت‌شده از پنل بنی ورودی را وارد کنید. پورت و پروتکل فعال OpenVPN خودکار تشخیص داده می‌شود. CA و گواهی کاربران تغییر نمی‌کند.",
  "Direct profiles use the exit node address; tunnel profiles use the entry host address. Download links appear for paired exit nodes after refreshing the customer page. Disabling the tunnel removes tunnel downloads; direct profiles continue working.": "کانفیگ مستقیم آدرس نود خروجی و کانفیگ تونلی آدرس سرور ورودی را دارد. پس از اتصال دو سرور و تازه‌سازی صفحه کاربر، لینک تونلی برای نود خروجی ظاهر می‌شود. با غیرفعال‌سازی تونل، لینک تونلی حذف می‌شود و مسیر مستقیم باقی می‌ماند.",
  "The VPN sees the forwarding host IP for tunneled connections. Device limits remain account-based, but IP restrictions cannot distinguish original client IPs through this relay. Re-pair after changing the exit listener. Pair certificates last one year.": "در اتصال تونلی، VPN آدرس سرور واسط را می‌بیند. محدودیت دستگاه همچنان برای هر حساب اعمال می‌شود، اما محدودیت IP نمی‌تواند IP اصلی کاربران پشت واسط را تفکیک کند. پس از تغییر پورت یا پروتکل خروجی، دو سرور را دوباره متصل کنید. اعتبار گواهی اتصال یک سال است.",
  "Dokodemo-door is a destination forwarder, not an encrypted tunnel by itself. It is not offered as an anti-filtering transport.": "dokodemo-door ترافیک را به مقصد مشخص می‌فرستد و به‌تنهایی تونل رمز‌شده نیست؛ به‌عنوان روش ضدشناسایی ارائه نشده است.",
  "Direct": "مستقیم",
  "Via entry tunnel": "از طریق تونل ورودی",
  "Tunnel status refreshed.": "وضعیت تونل به‌روز شد.",
  "Tunnel operation completed.": "عملیات تونل انجام شد.",
  "Enabled": "فعال",
  "Disabled": "غیرفعال",
  "Proxy registered": "مسیر تونل ثبت شده",
  "Waiting for registration": "در انتظار ثبت مسیر تونل",
  "Ready for pairing.": "آماده اتصال دو سرور است.",
  "Install the tunnel engine from the Beeny SSH menu first.": "ابتدا موتور تونل را از منوی SSH بنی نصب کنید.",
  "Invalid pairing invitation.": "دعوت‌نامه اتصال معتبر نیست.",
  "Working…": "در حال انجام…",
  "No nodes available.": "نودی ثبت نشده است.",
  "Use the secured HTTPS node bridge first.": "ابتدا API امن HTTPS نود را راه‌اندازی کنید.",
  "Update this node bridge to 3.7.0 before changing listeners.": "پیش از تغییر پورت، عامل این نود را به ۳.۷.۰ ارتقا دهید.",
  "Update this node bridge to 3.7.0 before pairing tunnels.": "پیش از اتصال تونل، عامل این نود را به ۳.۷.۰ ارتقا دهید.",
  "Acknowledge the VPN reconnect before applying.": "قبل از اعمال تغییر، اتصال دوباره کاربران را تأیید کنید.",
  "Could not verify this node listener. Check its helper/bridge logs.": "بررسی سرویس این نود انجام نشد. لاگ سرویس کمکی یا عامل نود را بررسی کنید.",
  "Disable the paired tunnel before changing this listener, then pair it again with the new port.": "ابتدا تونل را غیرفعال کنید؛ سپس پورت را تغییر دهید و تونل را با پورت جدید دوباره متصل کنید."
})

def register(app,db,Admin,panel_path):
    def language():return getattr(current_user,'language','en') if current_user.is_authenticated else 'en'
    def translate(text):return TRANSLATIONS.get(text,text) if language()=='fa' else text
    @app.context_processor
    def context():return dict(admin_t=translate,admin_language=language(),admin_dictionary=(TRANSLATIONS if language()=='fa' else {}))
    @app.post(panel_path.rstrip('/')+'/api/admin/language')
    @login_required
    def admin_language_save():
        lang=request.form.get('language')
        if lang not in {'fa','en'}:return jsonify(success=False,message='Invalid language'),400
        admin=db.session.get(Admin,current_user.id);admin.language=lang;session.pop('rep_admin_language',None);db.session.commit()
        return jsonify(success=True)
