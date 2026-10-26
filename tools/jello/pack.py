"""Hash-check/stage Jello resources, without loading Qt or visiting game paths."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from rm_client.ui.jello.resources import LEGACY_FILES, MANIFEST


def validate(root):
    root=Path(root).resolve()
    manifest=root/MANIFEST
    if manifest.stat().st_size > 128*1024:
        raise ValueError('Oversized Jello manifest')
    data=json.loads(manifest.read_text(encoding='utf-8-sig'))
    if data.get('schema')!=1 or set(data.get('files',{}))!=set(LEGACY_FILES.values()):
        raise ValueError('Jello resource inventory differs')
    for old,relative in LEGACY_FILES.items():
        entry=data['files'][relative];path=(root/relative).resolve()
        if not path.is_relative_to(root) or entry.get('legacy_path')!=old:
            raise ValueError('Unsafe Jello resource path')
        if path.stat().st_size != entry['size'] or path.stat().st_size > 8*1024*1024:
            raise ValueError('Jello resource size differs: '+relative)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
            raise ValueError('Jello resource hash differs: '+relative)
    owned={p.relative_to(root).as_posix() for p in root.glob('*/assets/**/*') if p.is_file()}
    if owned!=set(LEGACY_FILES.values()):
        raise ValueError('Unmanifested or missing Jello feature assets')
    return {'status':'JELLO_PACK_VALID','files':len(data['files'])}


def stage(source,destination):
    source,destination=Path(source).resolve(),Path(destination).resolve()
    validate(source)
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Jello staging source/destination must be separate')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError('Jello staging destination must be new or empty')
    destination.mkdir(parents=True,exist_ok=True)
    for relative in LEGACY_FILES.values():
        path=destination/relative;path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/relative,path)
    shutil.copyfile(source/MANIFEST,destination/MANIFEST)
    return validate(destination)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    check=sub.add_parser('check');check.add_argument('--pack',required=True,type=Path)
    copy=sub.add_parser('stage');copy.add_argument('--source',required=True,type=Path)
    copy.add_argument('--destination',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(validate(args.pack) if args.command=='check' else stage(args.source,args.destination)))
