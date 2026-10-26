"""本体按键图标、输入弹窗和keysetting控制器的只读数据。"""
from functools import lru_cache
import json
from pathlib import Path
import struct

from PySide6.QtGui import QImage

from ....runtime_paths import RuntimePaths
from ..wiki.motion import WikiMotion

_paths = RuntimePaths.discover()
ASSETS = (_paths.app_root/"rm_client/ui/endfield/keybinds/assets" if _paths.source_mode
          else _paths.asset("endfield/keybinds"))


@lru_cache(maxsize=1)
def source():
    return json.loads((ASSETS/"source.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def motion():
    return WikiMotion(source()["clips"])


@lru_cache(maxsize=128)
def texture(name):
    return QImage(str(ASSETS/(name+".png")))


def key_texture(key):
    return texture(source()["icons"].get(key,"icon_key_"+key.lower()))


@lru_cache(maxsize=1)
def highlight_frames():
    """保留Unity StreamedClip的三次多项式系数，按原始时间采样。"""
    values = source()["highlight_stream"]["data"]
    raw = struct.pack("<"+"I"*len(values),*values)
    offset, frames = 0, []
    while offset < len(raw):
        at,count = struct.unpack_from("<fi",raw,offset)
        offset += 8
        for _ in range(count):
            index,*coefficients = struct.unpack_from("<i4f",raw,offset)
            offset += 20
            if index == 0 and at >= 0:
                frames.append((at,coefficients))
    return frames


def highlight_alpha(at):
    frames = highlight_frames()
    start,coefficients = next((item for item in reversed(frames) if item[0] <= at),frames[0])
    a,b,c,d = coefficients
    elapsed = max(0,at-start)
    return max(0,min(1,((a*elapsed+b)*elapsed+c)*elapsed+d))
