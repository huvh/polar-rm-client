"""Minecraft server chat: square backgrounds, section colours, wrapping.

Latin glyphs reuse the game's bitmap sheet. Chinese explicitly uses YaHei UI
Regular rather than the bitmap compositor's '?' substitution or serif fallback.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import re

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

from .minecraft_hud import MinecraftBitmapFont


MC_COLORS = dict(zip("0123456789abcdef", ("#000000", "#0000aa", "#00aa00", "#00aaaa", "#aa0000", "#aa00aa", "#ffaa00", "#aaaaaa", "#555555", "#5555ff", "#55ff55", "#55ffff", "#ff5555", "#ff55ff", "#ffff55", "#ffffff")))


class MinecraftServerChatRenderer:
    def __init__(self, asset_root: Path) -> None:
        self.bitmap = MinecraftBitmapFont(Path(asset_root) / "ascii.png")
        self._cache: OrderedDict[tuple, tuple[QImage, ...]] = OrderedDict()
        self.last_height = 0.0

    @staticmethod
    def characters(text: str, base: str):
        color = base
        bold = False
        i = 0
        while i < len(text):
            if text[i] == "§" and i + 1 < len(text):
                code = text[i + 1].lower()
                if code in MC_COLORS: color, bold = MC_COLORS[code], False
                elif code == "l": bold = True
                elif code == "r": color, bold = base, False
                i += 2
                continue
            yield text[i], color, bold
            i += 1

    def lines(self, text: str, width: int, base: str, dpr: float) -> tuple[QImage, ...]:
        key=(text,width,base,round(dpr,2))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        font=QFont("Microsoft YaHei UI");font.setPixelSize(15);font.setWeight(QFont.Weight.Normal)
        metrics=QFontMetricsF(font)
        rows=[[]];x=0.0
        for char,color,bold in self.characters(text,base):
            # ascii.png does not map Latin-1 codepoints directly. Middle dots
            # and other punctuation must use YaHei, not an unrelated tile.
            advance=float(self.bitmap.logical_width(char)*2) if 32<=ord(char)<127 else metrics.horizontalAdvance(char)
            if char=="\n" or (x+advance>width and rows[-1]):rows.append([]);x=0.0
            if char=="\n":continue
            rows[-1].append((x,char,color,bold,advance));x+=advance
        images=[]
        for row in rows:
            image=QImage(max(1,round(width*dpr)),max(1,round(20*dpr)),QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr);image.fill(Qt.GlobalColor.transparent)
            p=QPainter(image);p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,False)
            for x,char,color,bold,advance in row:
                c=QColor(color)
                if 32<=ord(char)<127:
                    self.bitmap.draw(p,x,2,char,c,2)
                    if bold:self.bitmap.draw(p,x+1,2,char,c,2)
                else:
                    font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal);p.setFont(font)
                    p.setPen(QColor(0,0,0,210));p.drawText(QRectF(x+1,1,advance+2,19),int(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter),char)
                    p.setPen(c);p.drawText(QRectF(x,0,advance+2,19),int(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter),char)
            p.end();images.append(image)
        result=tuple(images);self._cache[key]=result
        while len(self._cache)>200:self._cache.popitem(last=False)
        return result

    def draw(self, host, p: QPainter, width: int, height: int, now: float) -> None:
        module=host.registry.get("MatchChat")
        if not module or not module.enabled:
            self.last_height=0;return
        opened=host.match_chat.input_open
        rows=host.match_chat.visible_messages(now=now,closed_lines=int(host.get_setting_number(module,"Closed Lines",6)),open_lines=int(host.get_setting_number(module,"Open Lines",16)),fade_seconds=host.get_setting_number(module,"Fade Seconds",10))
        if not rows and not opened:self.last_height=0;return
        chat_width=int(min(540,max(150,width*0.42)))
        margin=4.0;bottom=height-54.0
        max_lines=min(int(host.get_setting_number(module,"Open Lines" if opened else "Closed Lines",16 if opened else 6)),max(1,int((height-180)/20)))
        visual=[]
        for message,alpha in rows:
            prefix="§7[本地] §f<你> " if message.source=="you" else "§c[裁判] §r" if message.source=="referee" and not message.text.startswith("§") else ""
            base={"success":"#55ff55","warning":"#ffff55","danger":"#ff5555","chat":"#ffffff"}.get(message.level,"#ffffff")
            visual.extend((image,alpha) for image in self.lines(prefix+message.text,chat_width-8,base,host.devicePixelRatioF()))
        visual=visual[-max_lines:]
        p.save();p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,False)
        if opened:
            input_rect=QRectF(margin,bottom-22,min(width-8,chat_width+8),22)
            p.fillRect(input_rect,QColor(0,0,0,190))
            cursor="_" if int(now*2)%2==0 else ""
            input_rows=self.lines("§7[本地发送] §f"+host.match_chat.input_text+cursor,int(input_rect.width()-8),"#ffffff",host.devicePixelRatioF())
            p.drawImage(input_rect.left()+4,input_rect.top()+1,input_rows[-1])
            bottom-=26
        for index,(image,alpha) in enumerate(reversed(visual)):
            p.setOpacity(alpha);rect=QRectF(margin,bottom-(index+1)*20,chat_width,20)
            p.fillRect(rect,QColor(0,0,0,140 if opened else 100));p.drawImage(rect.left()+4,rect.top(),image)
        p.restore();self.last_height=len(visual)*20+(26 if opened else 0)+10
