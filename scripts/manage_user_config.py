#!/usr/bin/env python3
"""
مدیریت کانفیگ کلاینت‌های OpenVPN برای اعمال محدودیت‌ها
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

# تنظیمات
OPENVPN_CCD_DIR = "/etc/openvpn/ccd"
OPENVPN_SERVICE = "openvpn@server"

class OpenVPNClientManager:
    def __init__(self):
        self.ccd_dir = Path(OPENVPN_CCD_DIR)
        
        # اطمینان از وجود دایرکتوری
        self.ccd_dir.mkdir(exist_ok=True, mode=0o755)
    
    def enable_user(self, username):
        """فعال کردن کاربر (حذف فایل disable)"""
        config_file = self.ccd_dir / username
        
        if config_file.exists():
            with open(config_file, 'r') as f:
                content = f.read()
            
            # حذف خط disable اگر وجود داشته باشد
            if 'disable' in content:
                content = content.replace('disable', '')
                content = '\n'.join([line for line in content.split('\n') if line.strip()])
                
                if content.strip():
                    with open(config_file, 'w') as f:
                        f.write(content)
                else:
                    config_file.unlink()  # حذف فایل خالی
                
                self._reload_openvpn()
                return True
        return False
    
    def disable_user(self, username):
        """غیرفعال کردن کاربر (ایجاد فایل با محتوای disable)"""
        config_file = self.ccd_dir / username
        
        with open(config_file, 'w') as f:
            f.write("disable\n")
        
        self._reload_openvpn()
        
        # قطع اتصالات فعال کاربر
        self._kill_user_connections(username)
        
        return True
    
    def set_user_limit(self, username, limit_gb=None, expire_date=None):
        """
        تنظیم محدودیت‌های کاربر
        limit_gb: محدودیت ترافیک به گیگابایت
        expire_date: تاریخ انقضا (فرمت YYYY-MM-DD)
        """
        config_file = self.ccd_dir / username
        
        content = []
        
        # اضافه کردن کامنت برای شناسایی
        content.append(f"; User: {username}")
        
        if expire_date:
            content.append(f"; Expire: {expire_date}")
        
        if limit_gb:
            content.append(f"; Traffic Limit: {limit_gb} GB")
        
        # نوشتن فایل کانفیگ
        with open(config_file, 'w') as f:
            f.write('\n'.join(content))
        
        self._reload_openvpn()
        return True
    
    def _reload_openvpn(self):
        """Reload OpenVPN برای اعمال تغییرات"""
        try:
            subprocess.run(
                ["systemctl", "reload", OPENVPN_SERVICE],
                capture_output=True,
                check=False
            )
        except Exception as e:
            print(f"Error reloading OpenVPN: {e}")
    
    def _kill_user_connections(self, username):
        """قطع اتصالات فعال یک کاربر"""
        try:
            # استفاده از management interface OpenVPN
            result = subprocess.run(
                ["echo", f"kill {username}", "|", "nc", "127.0.0.1", "7505"],
                capture_output=True,
                shell=True
            )
        except Exception as e:
            print(f"Error killing connections for {username}: {e}")
    
    def update_all_users(self, users):
        """
        بروزرسانی همه کاربران بر اساس وضعیت فعلی
        users: لیست کاربران با attributes:
            - username
            - status (active/expired/disabled)
            - traffic_limit
            - traffic_usage
            - expire_date
        """
        for user in users:
            should_disable = False
            
            # بررسی محدودیت ترافیک
            if user.traffic_limit > 0:
                if user.traffic_usage >= user.traffic_limit:
                    should_disable = True
            
            # بررسی تاریخ انقضا
            try:
                if hasattr(user, 'expire_date') and user.expire_date:
                    expire = datetime.strptime(user.expire_date, "%Y-%m-%d")
                    if expire < datetime.now():
                        should_disable = True
            except:
                pass
            
            # اعمال وضعیت
            if should_disable or user.status != "active":
                if user.status != "expired":
                    user.status = "expired"
                self.disable_user(user.username)
            else:
                self.enable_user(user.username)
        
        return True


# تابع کمکی برای استفاده در پنل
def sync_user_openvpn_status(user):
    """همگام‌سازی یک کاربر با OpenVPN"""
    manager = OpenVPNClientManager()
    
    should_disable = False
    
    if user.traffic_limit > 0 and user.traffic_usage >= user.traffic_limit:
        should_disable = True
    
    try:
        if user.expire_date:
            expire = datetime.strptime(user.expire_date, "%Y-%m-%d")
            if expire < datetime.now():
                should_disable = True
    except:
        pass
    
    if should_disable or user.status != "active":
        if user.status != "expired":
            user.status = "expired"
        manager.disable_user(user.username)
    else:
        manager.enable_user(user.username)
    
    return user.status


if __name__ == "__main__":
    # برای اجرای مستقیم از خط فرمان
    import sys
    sys.path.append('/opt/beeny-panel')
    
    from app import app, db, User
    
    with app.app_context():
        manager = OpenVPNClientManager()
        users = User.query.all()
        
        for user in users:
            should_disable = False
            
            if user.traffic_limit > 0 and user.traffic_usage >= user.traffic_limit:
                should_disable = True
            
            try:
                if user.expire_date:
                    expire = datetime.strptime(user.expire_date, "%Y-%m-%d")
                    if expire < datetime.now():
                        should_disable = True
            except:
                pass
            
            if should_disable:
                if user.status != "expired":
                    user.status = "expired"
                manager.disable_user(user.username)
                print(f"🔴 {user.username}: DISABLED (traffic/expired)")
            else:
                if user.status != "active":
                    user.status = "active"
                manager.enable_user(user.username)
                print(f"🟢 {user.username}: ACTIVE")
        
        db.session.commit()