"""核验客户端随附资源和当前原生构建；不加载Qt、游戏或设备。"""
import argparse
import hashlib
from importlib import import_module
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def audit(root=ROOT):
    packages = {
        "menu":("tools.endfield.pack","rm_client/ui/endfield/menu/assets"),
        "wiki":("tools.endfield.wiki.check_assets","rm_client/ui/endfield/wiki/assets"),
        "settings":("tools.endfield.settings.check_assets","rm_client/ui/endfield/settings/assets"),
        "keybinds":("tools.endfield.keybinds.check_assets","rm_client/ui/endfield/keybinds/assets"),
        "changelog":("tools.endfield.changelog.check_assets","rm_client/ui/endfield/changelog/assets"),
        "jello":("tools.jello.pack","rm_client/ui/jello"),
    }
    results = {}
    for name,(module,relative) in packages.items():
        path = root/relative
        result = import_module(module).validate(path)
        files = [item for item in path.rglob("*") if item.is_file()]
        if name == 'jello':
            from rm_client.ui.jello.resources import LEGACY_FILES, MANIFEST
            files = [path/MANIFEST, *(path/relative for relative in LEGACY_FILES.values())]
        results[name] = {"path":relative,"files":len(files),"bytes":sum(item.stat().st_size for item in files),
                         "integrity":result}
    # 上游原始导出同时供离线导入器/曲线对照测试使用，不能按运行时引用删除。
    references = {}
    for relative, manifest_name, table in (
            ("assets/endfield_settings", "PROVENANCE.json", "files"),
            ("assets/cs2_scoreboard_source", "provenance.json", "assets")):
        path = root/relative
        data = json.loads((path/manifest_name).read_text(encoding="utf-8"))
        for name, record in data[table].items():
            target = (path/name).resolve()
            if not target.is_relative_to(path.resolve()):
                raise ValueError("Reference entry escapes package: "+name)
            expected = record["sha256"] if isinstance(record, dict) else record
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError("Reference resource changed: "+str(target))
        references[relative] = {"hashed_entries":len(data[table]),
            "role":"offline source/importer regression reference"}
    native = root/"rm_client/ui/endfield/menu/assets/native_renderer"
    current = json.loads((native/"CURRENT.json").read_text(encoding="utf-8"))["directory"]
    obsolete = sorted(item.name for item in native.glob("build_*") if item.name != current)
    if obsolete:
        raise ValueError("Unselected native builds remain in runtime pack: "+", ".join(obsolete))
    return {"status":"PASS","scope":"manifest/source/mesh validation only; no GPU or hardware qualification",
            "current_native_build":current,"packages":results,"reference_packages":references,
            "local_only":"Python environment, personal profiles and imported media are not application source changes"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json",type=Path)
    args = parser.parse_args()
    result = audit()
    if args.json:
        args.json.parent.mkdir(parents=True,exist_ok=True)
        args.json.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
