#!/usr/bin/env python3
"""
بررسی خودکار کاربران و غیرفعال کردن آنهایی که ترافیک یا زمانشان تمام شده
"""

import os
import sys
from datetime import datetime

# اضافه کردن مسیر پنل به PATH
sys.path.append('/opt/beeny-panel')

from app import app, db, User

def check_and_disable_users():
    """بررسی کاربران و غیرفعال کردن موارد منقضی شده"""
    
    with app.app_context():
        users = User.query.all()
        disabled_count = 0
        
        for user in users:
            should_disable = False
            reason = ""
            
            # بررسی محدودیت ترافیک
            if user.traffic_limit > 0:
                if user.traffic_usage >= user.traffic_limit:
                    should_disable = True
                    reason = f"traffic exceeded ({user.traffic_usage}/{user.traffic_limit} GB)"
            
            # بررسی تاریخ انقضا
            try:
                if user.expire_date and user.expire_date != "-":
                    expire = datetime.strptime(user.expire_date, "%Y-%m-%d")
                    if expire < datetime.now():
                        should_disable = True
                        reason = f"expired on {user.expire_date}"
            except Exception as e:
                print(f"Error checking expiry for {user.username}: {e}")
            
            # اعمال وضعیت
            if should_disable:
                ccd_file = f"/etc/openvpn/ccd/{user.username}"
                
                if not os.path.exists(ccd_file):
                    with open(ccd_file, "w") as f:
                        f.write("disable\n")
                
                os.system(
                    f"echo 'kill {user.username}' | nc 127.0.0.1 7505 2>/dev/null"
                )
                
                if user.status != "disabled":
                    user.status = "disabled"
                    disabled_count += 1
                    print(f"[DISABLED] {user.username}")
            else:
                if user.status != "active":
                    user.status = "active"
                    print(f"🟢 {user.username}: ACTIVE")
                    
                    # حذف فایل disable اگه وجود داشته باشد
                    ccd_file = f"/etc/openvpn/ccd/{user.username}"
                    if os.path.exists(ccd_file):
                        os.remove(ccd_file)
        
        db.session.commit()
        print(f"[{datetime.now()}] Check completed. {disabled_count} users disabled.")
        return disabled_count

if __name__ == "__main__":
    check_and_disable_users()