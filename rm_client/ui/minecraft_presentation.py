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
    """Vanilla providers at their native raster, on a shared logical baseline.

    Unihex has sixteen rows for an eight-unit-high Minecraft glyph.  Keep both
    rows per GUI unit all the way to the destination, rather than decimating a
    character to eight pixels before enlarging the HUD.  ASCII still comes from
    the original bitmap provider; no system-font substitution is involved.
    """

    raster_scale = 2
    baseline = 7

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
                        if char != "\0":
                            self.providers.setdefault(char, (texture, x*cell_w, y*cell_h, cell_w, cell_h,
                                int(provider.get("height", 8)), int(provider.get("ascent", 7))))
        self._glyphs = OrderedDict()
        self._glyph_tops = {}
        self._layouts = OrderedDict()
        self._images = OrderedDict()

    def glyph(self, char):
        if char in self._glyphs:
            self._glyphs.move_to_end(char); return self._glyphs[char]
        top = 0.0
        if char == " ":
            image = QImage(8, 16, QImage.Format_ARGB32_Premultiplied); image.fill(Qt.transparent); advance = 4.0
        elif char in self.providers:
            texture, x, y, w, h, height, ascent = self.providers[char]
            factor = height / h
            right = max((px for px in range(w) if any(texture.pixelColor(x+px, y+py).alpha()
                         for py in range(h))), default=-1)
            # BitmapProvider rounds ink width before adding one GUI unit of
            # spacing. Do not stretch the 9x12 accented sheet into a square.
            advance = math.floor((right+1)*factor + 0.5) + 1
            image = texture.copy(x, y, w, h).scaled(max(1, round(w*factor*2)), height*2,
                Qt.IgnoreAspectRatio, Qt.FastTransformation)
            top = float(self.baseline - ascent)
        elif 32 <= ord(char) < 127 and self.bitmap.available:
            code = self.bitmap._code(char)
            image = self.bitmap.texture.copy((code & 15)*8, (code >> 4)*8, 8, 8)
            image = image.scaled(16, 16, Qt.IgnoreAspectRatio, Qt.FastTransformation)
            advance = float(self.bitmap.logical_width(char))
        else:
            bits = self.hex_data.get(ord(char))
            if bits is None:
                # Missing optional Unihex/provider files must not recursively
                # ask for a missing '?' forever. Cache the fallback too.
                if char != "?":
                    image, advance = self.glyph("?")
                    top = self._glyph_tops["?"]
                else:
                    code = self.bitmap._code("?")
                    image = self.bitmap.texture.copy((code & 15)*8, (code >> 4)*8, 8, 8)
                    if image.isNull():
                        image = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
                        image.fill(Qt.transparent)
                    image = image.scaled(16, 16, Qt.IgnoreAspectRatio, Qt.FastTransformation)
                    advance = float(self.bitmap.logical_width("?"))
            else:
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
        self._glyph_tops[char] = top
        while len(self._glyphs)>512:
            removed, _ = self._glyphs.popitem(last=False)
            self._glyph_tops.pop(removed, None)
        return image, advance

    def _layout(self, text):
        """Cache the complete formatted/fallback run, not just single glyphs."""
        text = str(text)
        if text in self._layouts:
            self._layouts.move_to_end(text)
            return self._layouts[text]
        width=0.0;bold=False;index=0;color=None;top=0.0;bottom=8.0;runs=[]
        while index<len(text):
            char=text[index];index+=1
            if char=="§" and index<len(text):
                code=text[index].lower();index+=1
                if code=="l":bold=True
                elif code in COLORS:color=code;bold=False
                elif code=="r":color=None;bold=False
                continue
            glyph, advance = self.glyph(char)
            glyph_top = self._glyph_tops[char]
            top = min(top, glyph_top)
            bottom = max(bottom, glyph_top + glyph.height()/self.raster_scale)
            runs.append((width, glyph, glyph_top, color, bold))
            width+=advance+(1 if bold else 0)
        result = (width, top, bottom, tuple(runs))
        self._layouts[text] = result
        while len(self._layouts)>256:self._layouts.popitem(last=False)
        return result

    def width(self, text):
        return self._layout(text)[0]

    def height(self, text, shadow=True):
        _, top, bottom, _ = self._layout(text)
        return bottom-top+(1 if shadow else 0)

    def image(self, text, base=QColor("#ffffff"), shadow=True):
        key = (str(text), base.rgba(), bool(shadow))
        if key in self._images:
            self._images.move_to_end(key); return self._images[key]
        width, top, bottom, runs = self._layout(key[0])
        pad = 1 if shadow else 0
        image = QImage(max(1, math.ceil((width+pad)*self.raster_scale)),
            math.ceil((bottom-top+pad)*self.raster_scale), QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(self.raster_scale); image.fill(Qt.transparent)
        p = QPainter(image); p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        for x, glyph, glyph_top, code, bold in runs:
            color = QColor(COLORS[code]) if code is not None else base
            def tinted(c):
                tile = glyph.copy(); painter = QPainter(tile)
                painter.setCompositionMode(QPainter.CompositionMode_SourceIn); painter.fillRect(tile.rect(),c); painter.end()
                return tile
            target = QRectF(x, glyph_top-top, glyph.width()/self.raster_scale, glyph.height()/self.raster_scale)
            if shadow:
                shade = QColor(color.red()//4,color.green()//4,color.blue()//4,color.alpha())
                p.drawImage(target.translated(1,1), tinted(shade))
            p.drawImage(target, tinted(color))
            if bold: p.drawImage(target.translated(1,0), tinted(color))
        p.end(); self._images[key] = image
        while len(self._images)>256: self._images.popitem(last=False)
        return image

    def draw(self, painter, rect, text, scale=1.0, align=Qt.AlignLeft, shadow=True, base=QColor("#ffffff")):
        image = self.image(text,base=base,shadow=shadow)
        w, h = image.width()/image.devicePixelRatio()*scale, image.height()/image.devicePixelRatio()*scale
        x = rect.right()-w if align & Qt.AlignRight else rect.center().x()-w/2 if align & Qt.AlignHCenter else rect.left()
        y = rect.center().y()-h/2
        painter.save(); painter.setClipRect(rect,Qt.IntersectClip)
        painter.setRenderHint(QPainter.SmoothPixmapTransform,False)
        painter.drawImage(QRectF(x,y,w,h),image); painter.restore()


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
