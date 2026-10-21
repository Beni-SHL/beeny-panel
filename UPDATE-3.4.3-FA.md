# آپدیت 3.4.3 — اسکرول و لودینگ

بک‌گراند اصلی حذف نشده است. رزولوشن رندر محدود، نرخ رندر حداکثر حدود 30 فریم، و رندر بک‌گراند هنگام اسکرول/پنهان بودن صفحه متوقف می‌شود. blur کارت‌ها روی دسکتاپ سبک‌تر و روی موبایل با ظاهر شیشه‌ای بدون نمونه‌برداری زنده جایگزین شده است. انیمیشن‌های تزئینی هنگام اسکرول مکث و سپس ادامه دارند.

لودینگ فارسی/انگلیسی در صفحات مدیر و مشتری اضافه شد. نمایش اولیه منتظر آماده‌شدن فونت با مهلت محدود می‌ماند؛ انتقال صفحه و بخش داخلی لودینگ دارند. تایمر خروج اضطراری مانع گیرکردن پوشش می‌شود. دانلود فایل پوشش انتقال ندارد.

۱۵۵ تست پاس شد. بررسی مرورگری لودینگ، انتقال بخش، توقف/ادامه پس از اسکرول و صفحات مدیریت/کاربر در موبایل و دسکتاپ موفق بود. بهبود نرخ فریم روی گوشی واقعی هنوز اندازه‌گیری نشده است.

## فقط سرور اصلی

فایل beeny-panel-manual-update-3.4.3.zip را در /root آپلود کنید. هر مرحله در صورت خطا متوقف شود:

```bash
python3 -m zipfile -t /root/beeny-panel-manual-update-3.4.3.zip
python3 -m zipfile -e /root/beeny-panel-manual-update-3.4.3.zip /root/beeny-update-3.4.3
cd /root/beeny-update-3.4.3
bash scripts/update_panel.sh --check
```

بعد از موفقیت بررسی:

```bash
bash scripts/update_panel.sh
cat /opt/beeny-panel/VERSION
systemctl is-active beeny-panel beeny-customer-worker beeny-privileged openvpn-server@server
```

نسخه باید 3.4.3 و چهار سرویس active باشند. مرورگر با Ctrl+F5 تازه شود؛ در موبایل صفحه بسته و دوباره باز شود. مصرف و تنظیمات حفظ می‌شوند و OpenVPN ری‌استارت نمی‌شود. برای این اصلاح، آپدیت نود انگلیس لازم نیست.

## گیت‌هاب

```cmd
cd /d "%USERPROFILE%\beeny-panel-upload"
tar -xf "%USERPROFILE%\Downloads\beeny-panel-github-ready-3.4.3.zip" -C .
git add -A
git diff --cached --check
git commit -m "Release Beeny Panel 3.4.3 scroll performance"
git push origin main
```

این نسخه سیستم پورسانت جدید اضافه نمی‌کند؛ موجودی ساخت اکانت نماینده همچنان از کیف پول فعلی محاسبه می‌شود.
