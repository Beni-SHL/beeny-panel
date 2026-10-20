# آپدیت ۳.۶.۳

- تنظیمات یکپارچه: VPN access، Telegram & email، Node health، Administrators، Audit log و Nodes.
- حذف گزینه Update panel از منو؛ اسکریپت آپدیت دستی حفظ شده است.
- حذف فرم هزینه هر گیگ و جدول هزینه تخمینی؛ حفظ سوابق قبلی و پورسانت فروشنده قدیمی.
- گزارش ۱۲ ماهه UTC: فروش مستقیم، تمدید مشتری نماینده و اصل بدهی پرداخت‌شده. بازپرداخت در ماه ثبت خودش کسر می‌شود. اعتبار اولیه و تسویه داخلی درآمد محسوب نمی‌شوند. این گزارش سود خالص نیست.
- انتخاب چند نود در فرم ثبت نماینده کشویی است؛ فرم ادمین مدیریتی فعلاً مجوز نودمحور ندارد.
- رنگ آواتار نمایندگی، کنتراست دکمه‌ها در دو تم و آیکن +.

ZIP را در /root آپلود کنید:

```bash
python3 -m zipfile -t /root/beeny-panel-manual-update-3.6.3.zip
python3 -m zipfile -e /root/beeny-panel-manual-update-3.6.3.zip /root/beeny-update-3.6.3
cd /root/beeny-update-3.6.3
bash scripts/update_panel.sh --check
bash scripts/update_panel.sh
cat /opt/beeny-panel/VERSION
systemctl is-active beeny-panel beeny-customer-worker beeny-privileged openvpn-server@server
```

نود انگلیس و افزونه وردپرس به آپدیت نیاز ندارند. آپدیتر از اطلاعات نسخه قبلی پشتیبان می‌گیرد. سرویس پنل بازراه‌اندازی می‌شود؛ OpenVPN بازراه‌اندازی نمی‌شود و ترافیک ریست نمی‌شود.

تست‌های خودکار اجرا شده‌اند؛ بررسی بصری در مرورگر واقعی و اجرای روی VPS انجام نشده است.
