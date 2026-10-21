"""Owner-requested, commit-pinned updates from the fixed public Beeny repository.

The worker runs in its own systemd unit so restarting the web app/helper cannot
terminate an update. Only the existing backed-up updater applies a release.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path('/var/lib/beeny-updates')
APP = Path(__file__).resolve().parent
REPO = 'https://github.com/Beni-SHL/beeny-panel.git'
API = 'https://api.github.com/repos/Beni-SHL/beeny-panel'
ACTIVE = {'queued', 'fetching', 'installing'}


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', value):
        raise ValueError('Invalid release version.')
    return tuple(map(int, value.split('.')))


def installed():
    return (APP / 'VERSION').read_text().strip()


def save(name, value):
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = ROOT / name
    with tempfile.NamedTemporaryFile(mode='w', dir=ROOT, delete=False) as f:
        os.chmod(f.name, 0o600)
        json.dump(value, f)
        temp = f.name
    os.replace(temp, target)


def read(name):
    try:
        return json.loads((ROOT / name).read_text())
    except FileNotFoundError:
        return None


def fetch(url):
    # Every caller constructs this URL from a fixed host and a validated commit.
    req = urllib.request.Request(url, headers={'User-Agent': 'Beeny-panel-updater', 'Accept': 'application/vnd.github+json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=12) as response:
        data = response.read(262145)
    if len(data) > 262144:
        raise ValueError('GitHub response is too large.')
    return data


def check():
    # Branch refs contain only the head identifier, not a potentially huge diff.
    head = json.loads(fetch(API + '/git/ref/heads/main'))
    commit = head.get('object', {}).get('sha', '')
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('GitHub returned an invalid commit.')
    latest = fetch('https://raw.githubusercontent.com/Beni-SHL/beeny-panel/' + commit + '/VERSION').decode().strip()
    current = installed()
    update = dict(version=latest, commit=commit, checked_at=time.time(), available=version(latest) > version(current))
    save('release.json', update)
    return status()


def status():
    release, job = read('release.json'), read('job.json')
    if job and job['state'] in ACTIVE and time.time() - job['updated_at'] > 3600:
        # A lost worker must not leave an apparently running update forever.
        probe = subprocess.run(['systemctl', 'is-active', '--quiet', 'beeny-panel-update-' + job['id']], timeout=5)
        if probe.returncode:
            job.update(state='failed', message='Update worker stopped. Inspect its journal before retrying.', updated_at=time.time())
    if release:
        release['available'] = version(release['version']) > version(installed())
    return dict(success=True, installed=installed(), repository=REPO.removesuffix('.git'), branch='main', release=release, job=job)


def queue(commit):
    if not isinstance(commit, str) or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Check the GitHub version before installing.')
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (ROOT / 'queue.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = status()
        if state['job'] and state['job']['state'] in ACTIVE:
            raise ValueError('An update is already running.')
        release = state['release']
        if not release or release['commit'] != commit or time.time() - release['checked_at'] > 1800:
            raise ValueError('The version check expired. Check GitHub again.')
        if not release['available']:
            raise ValueError('No newer release is available.')
        token = secrets.token_hex(12)
        job = dict(id=token, commit=commit, version=release['version'], state='queued', updated_at=time.time(), message='Update queued.')
        save('job.json', job)
        try:
            subprocess.run(['systemd-run', '--quiet', '--collect', '--on-active=2s', '--unit=beeny-panel-update-' + token,
                            '--property=UMask=0077', '--property=RuntimeMaxSec=3600',
                            '/usr/bin/python3', str(APP / 'panel_update.py'), '--worker', token], check=True, timeout=10, capture_output=True)
        except Exception:
            job.update(state='failed', message='The update worker could not start.', updated_at=time.time())
            save('job.json', job)
            raise
    return status()


def execute(token):
    if os.geteuid() != 0 or not re.fullmatch('[0-9a-f]{24}', token):
        raise ValueError('Invalid update worker.')
    with (ROOT / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        job = read('job.json')
        if not job or job['id'] != token or job['state'] != 'queued':
            raise ValueError('Stale update worker.')
        def stage(state, message):
            job.update(state=state, message=message, updated_at=time.time())
            save('job.json', job)
        try:
            stage('fetching', 'Downloading the verified GitHub commit.')
            env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
            with tempfile.TemporaryDirectory(prefix='beeny-update-') as checkout:
                def git(*args):
                    return subprocess.run(['git', '-c', 'credential.helper=', '-C', checkout, *args], env=env, capture_output=True, text=True, check=True, timeout=180)
                git('init', '--quiet')
                git('fetch', '--depth', '1', REPO, job['commit'])
                git('checkout', '--detach', 'FETCH_HEAD')
                if git('rev-parse', 'HEAD').stdout.strip() != job['commit']:
                    raise ValueError('Downloaded commit does not match the checked release.')
                source = Path(checkout)
                target = (source / 'VERSION').read_text().strip()
                if target != job['version'] or version(target) <= version(installed()):
                    raise ValueError('Release version changed. Check GitHub again.')
                stage('installing', 'Creating backups, installing and checking panel health. The panel may briefly reconnect.')
                with (ROOT / ('update-' + token + '.log')).open('w') as log:
                    os.chmod(log.name, 0o600)
                    subprocess.run(['bash', str(source / 'scripts/update_panel.sh')], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=3000)
                if installed() != target:
                    raise ValueError('Installed version did not match the requested release.')
                stage('completed', 'Update completed and panel health verified.')
        except Exception:
            stage('failed', 'Update failed. Inspect the update journal and backup report before retrying.')
            raise


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--worker':
        raise SystemExit('Use the panel update queue.')
    execute(sys.argv[2])
