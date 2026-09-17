"""Original mod items and game-native formatted pixel text.

Font/damage sprites are local game resources; mod items are original.
Images are cached; no 3D engine, network, per-frame model rebuild, glass material
or control publisher is introduced.
"""
from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
import json
import math
from pathlib import Path
import zipfile

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from .minecraft_mod_items import recipe_for, crafted_item, MODULE_RECIPES, CATEGORY_RECIPES


COLORS = dict(zip("0123456789abcdef", (
    "#000000", "#0000aa", "#00aa00", "#00aaaa", "#aa0000", "#aa00aa", "#ffaa00", "#aaaaaa",
    "#555555", "#5555ff", "#55ff55", "#55ffff", "#ff5555", "#ff55ff", "#ffff55", "#ffffff")))


def plain_text(text: str) -> str:
    result = []; index = 0
    while index < len(text):
        if text[index] == "§" and index + 1 < len(text): index += 2
        else: result.append(text[index]); index += 1
    return "".join(result)


@lru_cache(maxsize=2)
def _hex_font(path: str) -> dict[int, bytes]:
    if not Path(path).is_file(): return {}
    with zipfile.ZipFile(path) as archive:
        data = archive.read(next(name for name in archive.namelist() if name.endswith(".hex")))
    return {int(code, 16): bytes.fromhex(bits.decode("ascii"))
            for line in data.splitlines() if b":" in line
            for code, bits in [line.split(b":", 1)]}


class MinecraftStyledFont:
    """Vanilla bitmap provider + actual Unihex CJK, not a smooth system font."""
    def __init__(self, bitmap, asset_root: Path):
        self.bitmap = bitmap
        root = Path(asset_root)
        self.hex_data = _hex_font(str(root / "unifont.zip"))
        self.providers = {}
        config = root / "font_default.json"
        if config.is_file():
            for provider in json.loads(config.read_text(encoding="utf-8"))["providers"]:
                if provider.get("type") != "bitmap": continue
                texture = QImage(str(root / Path(provider["file"]).name)).convertToFormat(QImage.Format_ARGB32_Premultiplied)
                if texture.isNull(): continue
                rows = provider["chars"]; cell_w = texture.width() // len(rows[0]); cell_h = texture.height() // len(rows)
                for y, row in enumerate(rows):
                    for x, char in enumerate(row):
                        if char != "\0": self.providers.setdefault(char, (texture, x*cell_w, y*cell_h, cell_w, cell_h))
        self._glyphs = OrderedDict()
        self._images = OrderedDict()

    def glyph(self, char):
        if char in self._glyphs:
            self._glyphs.move_to_end(char); return self._glyphs[char]
        if char == " ":
            image = QImage(8, 16, QImage.Format_ARGB32_Premultiplied); image.fill(Qt.transparent); advance = 4.0
        elif char in self.providers:
            texture, x, y, w, h = self.providers[char]
            image = texture.copy(x, y, w, h).scaled(16, 16, Qt.IgnoreAspectRatio, Qt.FastTransformation)
            right = max((px for px in range(16) if any(image.pixelColor(px, py).alpha() for py in range(16))), default=2)
            advance = (right+1)/2+1
        else:
            bits = self.hex_data.get(ord(char))
            if bits is None: return self.glyph("?")
            width = len(bits)//2  # sixteen rows, each 8/16/24/32 bits wide
            image = QImage(width, 16, QImage.Format_ARGB32_Premultiplied); image.fill(Qt.transparent)
            stride = width//8
            for y in range(16):
                row = int.from_bytes(bits[y*stride:(y+1)*stride], "big")
                for x in range(width):
                    if row & (1 << (width-x-1)): image.setPixelColor(x, y, QColor("#ffffff"))
            occupied = [x for x in range(width) if any(image.pixelColor(x,y).alpha() for y in range(16))]
            full = 0x3001 <= ord(char) <= 0x30ff or 0x3200 <= ord(char) <= 0x9fff or 0xff01 <= ord(char) <= 0xff5e
            left, right = (0, width-1) if full else (min(occupied,default=0), max(occupied,default=width-1))
            image = image.copy(left, 0, right-left+1, 16); advance = image.width()/2+1
        self._glyphs[char] = (image, advance)
        while len(self._glyphs)>512: self._glyphs.popitem(last=False)
        return image, advance

    def width(self, text):
        width=0.0;bold=False;index=0
        while index<len(text):
            char=text[index];index+=1
            if char=="§" and index<len(text):
                code=text[index].lower();index+=1
                if code=="l":bold=True
                elif code in COLORS or code=="r":bold=False
                continue
            width+=self.glyph(char)[1]+(1 if bold else 0)
        return width

    def image(self, text, base=QColor("#ffffff"), shadow=True):
        key = (text, base.rgba(), shadow)
        if key in self._images:
            self._images.move_to_end(key); return self._images[key]
        image = QImage(max(1, math.ceil(self.width(text)*2+2)), 18, QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(2); image.fill(Qt.transparent)
        p = QPainter(image); p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        x = 0.0; color = base; bold = False; index = 0
        while index < len(text):
            char = text[index]; index += 1
            if char == "§" and index < len(text):
                code = text[index].lower(); index += 1
                if code in COLORS: color, bold = QColor(COLORS[code]), False
                elif code == "l": bold = True
                elif code == "r": color, bold = base, False
                continue
            glyph, advance = self.glyph(char)
            def tinted(c):
                tile = glyph.copy(); painter = QPainter(tile)
                painter.setCompositionMode(QPainter.CompositionMode_SourceIn); painter.fillRect(tile.rect(),c); painter.end()
                return tile
            target = QRectF(x, 0, glyph.width()/2, 8)
            if shadow:
                shade = QColor(color.red()//4,color.green()//4,color.blue()//4,color.alpha())
                p.drawImage(target.translated(1,1), tinted(shade))
            p.drawImage(target, tinted(color))
            if bold: p.drawImage(target.translated(1,0), tinted(color))
            x += advance+(1 if bold else 0)
        p.end(); self._images[key] = image
        while len(self._images)>256: self._images.popitem(last=False)
        return image

    def draw(self, painter, rect, text, scale=1.0, align=Qt.AlignLeft, shadow=True, base=QColor("#ffffff")):
        image = self.image(text,base=base,shadow=shadow)
        w, h = image.width()/2*scale, image.height()/2*scale
        x = rect.right()-w if align & Qt.AlignRight else rect.center().x()-w/2 if align & Qt.AlignHCenter else rect.left()
        painter.save(); painter.setClipRect(rect,Qt.IntersectClip)
        painter.setRenderHint(QPainter.SmoothPixmapTransform,False)
        painter.drawImage(QRectF(x,rect.center().y()-h/2,w,h),image); painter.restore()


class MinecraftItemAtlas:
    def __init__(self, root: Path):
        self.images = {path.stem:QImage(str(path)) for path in (Path(root)/"items").glob("*.png")}
        self.custom = {recipe:crafted_item(recipe) for recipe in set(MODULE_RECIPES.values())|set(CATEGORY_RECIPES.values())}

    def item_name(self, name, category="System"):
        return recipe_for(name,category)

    def image(self, name, category="System"):
        key=self.item_name(name,category)
        if key not in self.custom:self.custom[key]=crafted_item(key)
        return self.custom[key]
