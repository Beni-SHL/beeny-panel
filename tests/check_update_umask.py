"""Exercise the updater's actual venv-creation block under its worker umask.
Checks filesystem access bits; this sandbox cannot switch to the service UID.
"""
from pathlib import Path
import os,stat,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
script=(root/'scripts/update_panel.sh').read_text()
a=script.index('(\n  umask 022\n');b=script.index('\n)\n',a)+2
block=script[a:b]
with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp);tmp.chmod(0o755)
    packages=tmp/'.venv-releases';packages.mkdir(mode=0o755)
    venv=packages/'candidate';(tmp/'requirements.txt').write_text('')
    env=dict(os.environ,PIP_NO_INDEX='1',PIP_DISABLE_PIP_VERSION_CHECK='1')
    command='umask 077\nnext_venv="$1"\nROOT_DIR="$2"\n'+block+'\ntouch "$ROOT_DIR/private-after"\n'
    subprocess.run(['bash','-c',command,'test',str(venv),str(tmp)],env=env,check=True,timeout=40,capture_output=True,text=True)
    for directory in [venv,venv/'bin',venv/'lib']:
        assert stat.S_IMODE(directory.stat().st_mode)&stat.S_IXOTH, directory
    assert stat.S_IMODE((venv/'pyvenv.cfg').stat().st_mode)&stat.S_IROTH
    assert stat.S_IMODE((tmp/'private-after').stat().st_mode)==0o600
    assert 'install -d -m 700 "$backup"' in script
    assert 'install -d -m 755 "$DEST/.venv-releases"' in script
    assert script.index('runuser -u beeny -- "$next_venv/bin/python"') < script.index('systemctl stop beeny-panel\n')
print('PASS: staged venv is traversable/readable under worker UMask=0077; subsequent private files stay 0600; service-user check precedes downtime.')
