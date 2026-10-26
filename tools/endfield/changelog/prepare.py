"""将游戏公告页的官方静态资源和本体字体制成本地更新日志资源包。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

CDN = "https://web.hycdn.cn/endfield/webview/_bulletin/"
ENTRY = "https://ef-webview.hypergryph.com/page/game_bulletin"
FONTS = ("HarmonyOS_Sans_Medium.woff2", "HarmonyOS_Sans_Bold.woff2",
         "HarmonyOS_Sans_SC_Medium.woff2", "HarmonyOS_Sans_SC_Bold.woff2")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source: Path, fonts: Path, output: Path) -> None:
    """只替换资源地址和日志数据接口，保留原页面组件、CSS 与动画。"""
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix in (".js", ".css", ".html"):
            text = path.read_text(encoding="utf-8")
            text = text.replace(CDN, "./")
            for host in ("https://web.hycdn.cn/webview/static/fonts/",
                         "https://web-static.hg-cdn.com/webview/static/fonts/"):
                text = text.replace(host, "./fonts/")
            if path.name.startswith("commons.") and path.suffix == ".js":
                if text.count("var bt=It;") != 1:
                    raise ValueError("公告页数据接口边界已变化，请重新审查原始页面")
                text = text.replace("var bt=It;", "var bt=window.POLAR_CHANGELOG_API;")
                # 标签文案适配终端；布局、交互与原动画组件不变。
                for old, new in (("活动公告", "更新日志"), ("游戏公告", "功能变更"),
                                 ("资讯速报", "使用说明")):
                    text = text.replace('"' + old + '"', '"' + new + '"')
                for key, old, new in (("events", "Events", "Changelog"),
                                      ("updates", "Updates", "Changes"), ("news", "News", "Help")):
                    text = text.replace('"game.menu.' + key + '":"' + old + '"',
                                        '"game.menu.' + key + '":"' + new + '"')
            if path.name == "index.html":
                text = text.replace('<div id="root"></div>',
                                    '<div id="root"></div><script src="adapter.js"></script>')
            target.write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(path, target)
        records.append({"output": relative.as_posix(),
                        "source": ENTRY if path.name == "index.html" else CDN + relative.as_posix(),
                        "source_sha256": digest(path), "sha256": digest(target)})
    for name in FONTS:
        target = output / "fonts" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(fonts / name, target)
        records.append({"output": "fonts/" + name, "source": "game/sdkresources/font/" + name,
                        "source_sha256": digest(fonts / name), "sha256": digest(target)})
    adapter = Path(__file__).resolve().parents[3] / "rm_client/ui/endfield/changelog/adapter.js"
    shutil.copyfile(adapter, output / "adapter.js")
    records.append({"output": "adapter.js", "source": "client local content/close adapter",
                    "source_sha256": digest(adapter), "sha256": digest(output / "adapter.js")})
    (output / "PROVENANCE.json").write_text(json.dumps({
        "origin": "Game WebviewConfig/BulletinConfig.bin -> targets.game.entry; official static page",
        "entry": ENTRY, "files": records,
        "adaptation": "Relative local URLs, local changelog data port, client tab labels only. "
                      "Original components, styles, dimensions and CSS motion retained.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--fonts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.fonts, args.out)
