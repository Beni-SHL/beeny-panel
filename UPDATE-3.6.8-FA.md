# آپدیت Beeny Panel 3.6.8

این نسخه ادامهٔ 3.6.7 است. نصب روی سرور واقعی از این محیط انجام نشده است. علت قطعی جاری، با تست محلی اثبات نمی‌شود؛ پیش از تغییرات عملیاتی، بخش عیب‌یابی راهنمای OPERATIONS-3.6.8-FA.md را اجرا کنید.

## ۱. سرور اصلی

فایل `beeny-panel-manual-update-3.6.8.zip` را در `/root` سرور اصلی بگذارید. سپس:

```bash
python3 -m zipfile -t /root/beeny-panel-manual-update-3.6.8.zip
python3 -m zipfile -e /root/beeny-panel-manual-update-3.6.8.zip /root/beeny-update-3.6.8
cd /root/beeny-update-3.6.8
bash scripts/update_panel.sh --check
```

اگر بررسی سازگاری موفق بود:

```bash
bash scripts/update_panel.sh
cat /opt/beeny-panel/VERSION
systemctl is-active beeny-panel beeny-customer-worker beeny-privileged openvpn-server@server
```

باید نسخهٔ `3.6.8` و چهار خط `active` ببینید. آپدیت معمولی OpenVPN را ری‌استارت نمی‌کند، مصرف/حجم/تاریخ حساب را ریست نمی‌کند و گواهی‌ها را تعویض نمی‌کند. پنل، worker و helper ممکن است کوتاه دوباره راه‌اندازی شوند. از کد و دیتابیس پشتیبان گرفته می‌شود و بررسی ورود/دیتابیس انجام می‌شود. جدول‌های جدید کنترل تلاش اضافه در مهاجرت افزایشی ساخته می‌شوند.

## ۲. نود انگلیس و سایر نودها

فایل `beeny-node-update-3.6.8.zip` را داخل `/root` **خود نود** بگذارید:

```bash
python3 -m zipfile -t /root/beeny-node-update-3.6.8.zip
python3 -m zipfile -e /root/beeny-node-update-3.6.8.zip /root/beeny-node-update-3.6.8
cd /root/beeny-node-update-3.6.8
bash scripts/update_node_speed.sh
systemctl is-active beeny-node-bridge openvpn-server@server
```

این مرحله bridge امن موجود را آپدیت می‌کند؛ OpenVPN را ری‌استارت نمی‌کند. تنظیم HTTPS و کلید ایجنت فعلی حفظ می‌شود. قابلیت جدید شبکه به `network-policy-v3` نیاز دارد؛ پنل ایجنت قدیمی را برای اعمال ناقص قوانین جدید قبول نمی‌کند. اگر bridge امن قبلاً نصب نشده، این اسکریپت مخصوص ارتقاست و جای نصب اولیه را نمی‌گیرد.

## ۳. کارهایی که جداگانه تصمیم می‌گیرید

- اعمال مسیر مستقیم روی اتصال‌ها: Settings → Network rules → Iran & direct routes؛ فقط پس از تأیید قوانین و در زمان مناسب، دکمهٔ راه‌اندازی مجدد را بزنید. نشست‌های همان نود یک‌بار دوباره وصل می‌شوند.
- کنترل فوری اتصال اضافه: راهنمای Admission در OPERATIONS را انجام دهید. بدون آن، پایش دوره‌ای اتصال اضافه را قطع می‌کند و تعداد تلاش‌ها را ثبت می‌کند؛ اتصال اضافه ممکن است تا نوبت پایش برقرار بماند.
- WARP: نصب بسته فقط کلاینت رسمی را نصب می‌کند؛ ثبت‌نام، اتصال یا تغییر خودکار مسیر پیش‌فرض انجام نمی‌دهد. نصب‌های خارجی و دادهٔ ثبت‌نام قبلی خودکار بازنویسی نمی‌شوند.
- هیچ دستور ریست ترافیک، تعویض CA یا دانلود دوبارهٔ کانفیگ مشتری برای آپدیت معمولی لازم نیست.

اگر سرویس فعال نبود، خروجی زیر را بررسی کنید و آپدیت را پشت سر هم تکرار نکنید:

```bash
journalctl -u beeny-panel -u beeny-customer-worker -u beeny-privileged -n 80 --no-pager -o cat
```
