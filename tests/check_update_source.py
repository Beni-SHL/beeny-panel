"""Exercise the real Bash source preflight without touching an installed panel."""
from pathlib import Path
import shutil,subprocess,tempfile,zipfile
root=Path(__file__).resolve().parents[1]
# Copy source files with the current manifest, excluding local environments/data.
import json
names=set(json.loads((root/'SOURCE-SHA256.json').read_text()))
names.update(['SOURCE-SHA256.json','GUIDE-3.7.7-FA.md'])
with tempfile.TemporaryDirectory() as tmp:
    stage=Path(tmp)
    for name in names:
        source=root/name
        if source.is_file():
            target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    script=(root/'scripts/update_panel.sh').read_text()
    # Stop before the installed-panel compatibility check: this test never applies code.
    prefix=script.split('[[ -f "$DEST/app.py"',1)[0]
    assert prefix!=script,'Installed-panel preflight boundary not found'
    (stage/'scripts/update_panel.sh').write_text(prefix+'\nprintf "%s\\n" "${FILES[@]}"\n')
    def run():return subprocess.run(['bash',str(stage/'scripts/update_panel.sh'),'--check'],text=True,capture_output=True,timeout=15)
    present=run();assert present.returncode==0,present.stderr
    assert 'GUIDE-3.7.7-FA.md' in present.stdout.splitlines()
    for p in stage.glob('*.md'):p.unlink()
    missing_docs=run();assert missing_docs.returncode==0,missing_docs.stderr
    assert not any(line.endswith('.md') and '/' not in line for line in missing_docs.stdout.splitlines())
    (stage/'app.py').unlink()
    missing_code=run();assert missing_code.returncode!=0
    assert 'Missing update source: app.py' in missing_code.stderr,missing_code.stderr
print('PASS: existing docs included; absent docs tolerated; absent essential code still rejected.')
