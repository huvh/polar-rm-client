"""实体键盘布局，以本体设置材质和原始按键高亮曲线绘制与命中。"""
import time

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, QEvent, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget, QToolTip, QSizePolicy

from ..settings.resources import ui_font
from ..settings.widgets import draw_sliced, draw_image
from .layout import KEYS, WIDTH, HEIGHT
from .resources import key_texture, highlight_alpha, source


class KeyboardView(QWidget):
    selected = Signal(str)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.keys = {key.name:key for key in KEYS}
        self.selected_key = "W"
        self.query = ""
        self.matches = set()
        self.hover = None
        self._hover_started = 0
        self._pressed = None
        self.held = set()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.setAccessibleName("快捷键实体键盘，点击键帽查看或添加绑定")
        self._timer = QTimer(self)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._advance)

    def mapping(self):
        scale = max(.01,min((self.width()-12)/WIDTH,(self.height()-12)/HEIGHT))
        return (self.width()-WIDTH*scale)/2,(self.height()-HEIGHT*scale)/2,scale

    def key_rect(self, name):
        x,y,scale = self.mapping()
        key = self.keys[name]
        return QRectF(x+key.x*scale,y+key.y*scale,key.width*scale,key.height*scale)

    def key_at(self, point):
        return next((key.name for key in KEYS if self.key_rect(key.name).contains(point)),None)

    def set_query(self, text):
        self.query = text.casefold().strip()
        self.matches = {self.owner.session.values[entry.identity] for entry in self.owner.session.entries
                        if self.query and self.query in (entry.title+" "+entry.category+" "+
                                                        self.owner.session.values[entry.identity]).casefold()}
        self.matches.update(key.name for key in KEYS if self.query and self.query in key.name.casefold())
        self.update()

    def _advance(self):
        self.update()
        if time.perf_counter()-self._hover_started >= source()["highlight_duration"]:
            self._timer.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        _x,_y,scale = self.mapping()
        for key in KEYS:
            rect = self.key_rect(key.name).adjusted(.5,.5,-.5,-.5)
            bound = self.owner.session.bound(key.name)
            selected = key.name == self.selected_key
            painter.save()
            if self.query and key.name not in self.matches:
                painter.setOpacity(.28)
            draw_sliced(painter,"row_bg",rect,scale*.65)
            draw_image(painter,"row_left",rect,.16)
            if selected:
                draw_image(painter,"tab_selected",rect)
            elif key.name == self.hover:
                alpha = highlight_alpha(time.perf_counter()-self._hover_started)
                painter.fillRect(rect,QColor(255,255,255,round(alpha*255)))
            if key.name in self.held or key.name == self._pressed:
                painter.fillRect(rect,QColor(255,255,255,round(255*source()["pressed_alpha"])))
            painter.setPen(QPen(QColor("#fff500" if self.query and key.name in self.matches else "#737672"),1))
            painter.drawRect(rect)
            image = key_texture(key.name)
            height = min(rect.height()*.83,52*scale)
            width = height*image.width()/max(1,image.height())
            if width > rect.width()-8:
                height *= max(1,rect.width()-8)/width
                width = max(1,rect.width()-8)
            compact_label = key.name in ("Insert","Home","PageUp","Delete","End","PageDown")
            if not image.isNull() and not compact_label:
                painter.drawImage(QRectF(rect.center().x()-width/2,rect.center().y()-height/2,width,height),image)
            else:
                painter.setFont(ui_font(max(10,20*scale)))
                painter.setPen(QColor("#252721" if selected else "#eeeeee"))
                painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,key.label)
            if bound:
                painter.fillRect(QRectF(rect.left()+5,rect.bottom()-4,max(5,rect.width()*.18),2),
                                 QColor("#34372a" if selected else "#e3e5de"))
            painter.restore()

    def mouseMoveEvent(self, event):
        key = self.key_at(event.position())
        if key != self.hover:
            self.hover = key
            self._hover_started = time.perf_counter()
            self._timer.start()
            if key is not None:
                entries = self.owner.session.bound(key)
                text = key+" · "+("、".join(entry.title for entry in entries) if entries else "未绑定")
                QToolTip.showText(event.globalPosition().toPoint(),text,self)
            else:
                QToolTip.hideText()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = self.key_at(event.position())
            self.setFocus()
            self.update()
        else:
            self._pressed = None
        event.accept()

    def mouseReleaseEvent(self, event):
        key = self.key_at(event.position())
        if event.button() == Qt.MouseButton.LeftButton and key is not None and key == self._pressed:
            self.selected.emit(key)
        self._pressed = None
        self.update()
        event.accept()

    def leaveEvent(self, event):
        self.hover = None
        self._timer.stop()
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event):
        self._pressed = None
        super().resizeEvent(event)

    def hideEvent(self, event):
        self._pressed = None
        self.held.clear()
        super().hideEvent(event)

    def focusOutEvent(self, event):
        self._pressed = None
        self.held.clear()
        self.update()
        super().focusOutEvent(event)

    def event(self, event):
        if event.type() in (QEvent.Type.KeyPress,QEvent.Type.KeyRelease):
            name = self.owner.session.host.key_name(event)
            if name in self.keys and name not in ("F11","F12","Escape"):
                if event.type() == QEvent.Type.KeyPress:
                    self.held.add(name)
                else:
                    self.held.discard(name)
                self.update()
                event.accept()
                return True
        return super().event(event)
