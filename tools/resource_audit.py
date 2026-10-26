"""核验客户端随附资源和当前原生构建；不加载Qt、游戏或设备。"""
import argparse
from importlib import import_module
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def audit(root=ROOT):
    packages = {
        "menu":("tools.endfield.pack","rm_client/ui/endfield/menu/assets"),
        "wiki":("tools.endfield.wiki.check_assets","rm_client/ui/endfield/wiki/assets"),
        "settings":("tools.endfield.settings.check_assets","rm_client/ui/endfield/settings/assets"),
        "keybinds":("tools.endfield.keybinds.check_assets","rm_client/ui/endfield/keybinds/assets"),
        "changelog":("tools.endfield.changelog.check_assets","rm_client/ui/endfield/changelog/assets"),
    }
    results = {}
    for name,(module,relative) in packages.items():
        path = root/relative
        result = import_module(module).validate(path)
        files = [item for item in path.rglob("*") if item.is_file()]
        results[name] = {"path":relative,"files":len(files),"bytes":sum(item.stat().st_size for item in files),
                         "integrity":result}
    native = root/"rm_client/ui/endfield/menu/assets/native_renderer"
    current = json.loads((native/"CURRENT.json").read_text(encoding="utf-8"))["directory"]
    obsolete = sorted(item.name for item in native.glob("build_*") if item.name != current)
    if obsolete:
        raise ValueError("Unselected native builds remain in runtime pack: "+", ".join(obsolete))
    return {"status":"PASS","scope":"manifest/source/mesh validation only; no GPU or hardware qualification",
            "current_native_build":current,"packages":results,
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
