"""Copy installed-distribution license notices, not private runtime data."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import sys


def collect(destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    entries = []
    for distribution in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].casefold()):
        name, version = distribution.metadata['Name'], distribution.version
        directory = re.sub(r'[^A-Za-z0-9_.-]', '_', name+'-'+version)
        copied = []
        install_root = Path(distribution.locate_file('')).resolve()
        for relative in distribution.files or ():
            # Restrict to license/notice text named in installed wheel RECORD.
            parts = Path(str(relative)).parts
            if not any(any(word in part.casefold() for word in ('license', 'copying', 'notice', 'copyright')) for part in parts):
                continue
            source = Path(distribution.locate_file(relative)).resolve()
            if not source.is_relative_to(install_root) or not source.is_file():
                continue
            if source.suffix.casefold() not in ('', '.txt', '.md', '.rst') or source.stat().st_size > 4*1024*1024:
                continue
            target = destination/directory/Path(str(relative))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append({'file': target.relative_to(destination).as_posix(),
                           'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
        entries.append({'distribution': name, 'version': version,
            'license': distribution.metadata.get('License-Expression') or distribution.metadata.get('License', ''),
            'files': copied})
    python_license = Path(sys.base_prefix)/'LICENSE.txt'
    if not python_license.is_file(): raise RuntimeError('Python runtime license missing')
    shutil.copyfile(python_license, destination/'PYTHON-LICENSE.txt')
    result = {'python_version': sys.version.split()[0], 'distributions': entries,
        'python_license_sha256': hashlib.sha256(python_license.read_bytes()).hexdigest()}
    (destination/'INDEX.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    report = collect(parser.parse_args().out)
    print('Dependency notices:', sum(len(d['files']) for d in report['distributions']), 'files')
