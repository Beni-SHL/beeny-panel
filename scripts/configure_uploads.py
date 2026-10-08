"""Update only the Beeny Nginx site, preserving TLS and proxy settings."""
from datetime import datetime
from pathlib import Path
import re
import shutil
import subprocess


def upload_site_config(original):
    if 'proxy_pass' not in original or not re.search(r'^\s*server_name\s+[^;]+;', original, re.M):
        raise RuntimeError('Unrecognized Beeny Nginx site; configure the upload limit manually.')
    updated = re.sub(r'^\s*client_max_body_size\s+[^;]+;[^\n]*\n?', '', original, flags=re.M)
    return re.sub(r'(^[ \t]*server_name\s+[^;]+;)',
                  r'\1\n    client_max_body_size 24M;', updated, flags=re.M)


def configure():
    site = Path('/etc/nginx/sites-enabled/beeny-panel')
    if not site.is_file():
        print('No Beeny Nginx site found. Set client_max_body_size 24M on your proxy.')
        return
    site = site.resolve()
    original = site.read_text()
    # Remove narrower location limits, then set a limit for every server block.
    updated = upload_site_config(original)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = Path('/root') / ('beeny-nginx-upload-backup-' + stamp + '.conf')
    shutil.copy2(site, backup)
    try:
        site.write_text(updated)
        subprocess.run(['nginx', '-t'], check=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
    except Exception:
        shutil.copy2(backup, site)
        subprocess.run(['nginx', '-t'], check=False)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=False)
        raise
    print('Nginx upload limit set to 24M. Backup:', backup)


if __name__ == '__main__':
    configure()
