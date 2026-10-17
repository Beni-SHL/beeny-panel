#!/usr/bin/env python3
"""Rebuild local CSS bundles in the existing cascade order; keep original sources editable."""
import json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'style-bundles.json').read_text())
for target,sources in manifest.items():
    parts=[]
    for source in sources:
        path=root/'static'/source
        if path.parent!=root/'static/css' or not path.is_file():raise ValueError('Invalid stylesheet source')
        parts.append('/* '+source+' */\n'+re.sub(r'@charset\s+[^;]+;','',path.read_text()))
    (root/'static/css'/target).write_text('\n'.join(parts)+'\n')
print('Local style bundles rebuilt')
