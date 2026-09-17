"""Original mod items/operator preview and game-native formatted pixel text.

Font/damage sprites are local game resources; mod items/operator are original.
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

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
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


class MinecraftPlayerPreview:
    """Cached operator portrait, with a textured-player renderer for skin inputs."""
    def __init__(self, skin_path: Path | None = None, *, portrait_path: Path | None = None):
        self.skin = (QImage(str(skin_path)) if skin_path else QImage()).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self.portrait = (QImage(str(portrait_path)) if portrait_path else QImage()).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self._image = QImage(); self.rebuilds = 0

    def image(self):
        if not self._image.isNull(): return self._image
        image = QImage(100,140,QImage.Format_ARGB32_Premultiplied); image.fill(Qt.transparent)
        if not self.portrait.isNull():
            # One nearest-neighbour fit at load time; inventory animation only
            # composites this thumbnail, never the full-resolution artwork.
            tile = self.portrait.scaled(image.size(), Qt.KeepAspectRatio, Qt.FastTransformation)
            p = QPainter(image)
            p.drawImage(QPointF((image.width()-tile.width())/2, (image.height()-tile.height())/2), tile)
            p.end(); self._image = image; self.rebuilds += 1
            return image
        if self.skin.isNull(): return image
        yaw, pitch = math.radians(-22), math.radians(9)
        def project(x,y,z):
            xx=x*math.cos(yaw)+z*math.sin(yaw); zz=-x*math.sin(yaw)+z*math.cos(yaw)
            return QPointF(50+xx*3.4,10+(y*math.cos(pitch)-zz*math.sin(pitch))*3.4), y*math.sin(pitch)+zz*math.cos(pitch)
        faces=[]
        def cube(cx,cy,w,h,d,u,v,pad=0):
            x0,x1=cx-w/2-pad,cx+w/2+pad; y0,y1=cy-h/2-pad,cy+h/2+pad;z0,z1=-d/2-pad,d/2+pad
            # UVs follow the actual wide-player model's box unfolding.
            polygons=[([(x0,y0,z0),(x1,y0,z0),(x0,y1,z0)],(u+d,v+d,w,h),.98),
                      ([(x0,y0,z1),(x0,y0,z0),(x0,y1,z1)],(u+d+w,v+d,d,h),.72),
                      ([(x0,y0,z1),(x1,y0,z1),(x0,y0,z0)],(u+d,v,w,d),1.0)]
            for points,uv,shade in polygons:
                projected=[project(*point) for point in points]
                faces.append((sum(depth for _,depth in projected)/3,[p for p,_ in projected],uv,shade))
        for cx,cy,w,h,d,u,v,outer_u,outer_v in [
            (-2,26,4,12,4,0,16,0,32),(2,26,4,12,4,16,48,0,48),
            (-6,14,4,12,4,40,16,40,32),(6,14,4,12,4,32,48,48,48),
            (0,14,8,12,4,16,16,16,32),(0,4,8,8,8,0,0,32,0)]:
            cube(cx,cy,w,h,d,u,v);cube(cx,cy,w,h,d,outer_u,outer_v,.25)
        p=QPainter(image);p.setRenderHint(QPainter.SmoothPixmapTransform,False)
        for _,points,uv,shade in sorted(faces,key=lambda row:row[0],reverse=True):
            tile=self.skin.copy(*uv)
            if shade<1:
                tint=QPainter(tile);tint.setCompositionMode(QPainter.CompositionMode_SourceAtop)
                tint.fillRect(tile.rect(),QColor(0,0,0,round(255*(1-shade))));tint.end()
            a,b,c=points
            p.save();p.setTransform(QTransform((b.x()-a.x())/tile.width(),(b.y()-a.y())/tile.width(),
                (c.x()-a.x())/tile.height(),(c.y()-a.y())/tile.height(),a.x(),a.y()))
            p.drawImage(0,0,tile);p.restore()
        p.end();self._image=image;self.rebuilds+=1
        return image

    def face(self):
        face=self.skin.copy(8,8,8,8);p=QPainter(face);p.drawImage(0,0,self.skin.copy(40,8,8,8));p.end();return face
