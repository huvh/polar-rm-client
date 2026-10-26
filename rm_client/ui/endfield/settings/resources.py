"""本体贴图、字体及原始 Unity 动画的只读入口。"""
from functools import lru_cache
import json
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase, QImage

from ..wiki.motion import WikiMotion
from ....runtime_paths import RuntimePaths

_paths = RuntimePaths.discover()
ASSETS = (_paths.app_root / "rm_client/ui/endfield/settings/assets" if _paths.source_mode
          else _paths.asset("endfield/settings"))


@lru_cache(maxsize=1)
def source():
    return json.loads((ASSETS / "source.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def motion():
    return WikiMotion(source()["clips"])


@lru_cache(maxsize=64)
def texture(name):
    return QImage(str(ASSETS / (name + ".png")))


@lru_cache(maxsize=1)
def font_family():
    path = ASSETS / "defaultfont_cn.ttf"
    if not path.exists():
        path = Path(__file__).parents[1] / "wiki/assets/fonts/NotoSansSC.ttf"
    identity = QFontDatabase.addApplicationFont(str(path))
    families = QFontDatabase.applicationFontFamilies(identity)
    return families[0] if families else "Microsoft YaHei UI"


def ui_font(pixels=24):
    font = QFont(font_family())
    font.setPixelSize(round(pixels))
    return font
