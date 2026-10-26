"""Original GameSettingPanel presentation adapted to native, safe client widgets.

No Unity/game process is loaded. Resources are preloaded once, never in paint.
This theme deliberately does not touch combat/economy liquid-glass materials.
"""
from __future__ import annotations

from functools import lru_cache
import json
import logging

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen, QPalette
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QGraphicsOpacityEffect, QTabBar, QPushButton, QWidget, QVBoxLayout, QLabel

from ..runtime_paths import RuntimePaths
from .jello_clickgui import JelloReversibleAnimation
from .jello_widgets import JelloDialog
from .endfield_source_motion import sample_weighted_curve


YELLOW = "#fff100"  # GameSettingPanel Selected/Bg: (1, .945098, 0)
INK = "#212121"
WHITE = "#eeeeee"
MIN_TEXT_PX = 16  # Logical pixels: never shrink CJK strokes with the whole page.


def settings_scale(width,height):
    # Source controls are authored at high-resolution canvas density (515px
    # fields / 100px icon rail), not at desktop logical-pixel density.
    return max(1/3,min(1.25,width/3840,height/2160))


@lru_cache(maxsize=1)
def resources():
    from PySide6.QtGui import QImage
    root = RuntimePaths.discover().asset("endfield_settings")
    names = ("icon_settings_computer", "icon_settings_audio", "icon_settings_control",
             "icon_settings_keystroke", "icon_settings_language", "icon_setting_controller",
             "deco_settings_bg_contour", "deco_settings_texture", "deco_settings_texture02",
             "tab_selected", "tab_fill", "close", "arrow", "row_bg", "button_bg", "bg_setting_dropdown",
             "toggle_bg", "toggle_ring", "toggle_line")
    specs = json.loads((root / "PROVENANCE.json").read_text(encoding="utf8"))["sprites"]
    clips = json.loads((root / "source_layout.json").read_text(encoding="utf8"))["clips"]
    images = {}
    for name in names:
        image = QImage(str(root / (name + ".png")))
        if image.isNull():
            raise ValueError("Missing Endfield settings sprite: " + name)
        rect = specs.get(name + ".png", {}).get("rect")
        if rect:
            # Unity sprite rectangles use bottom-left coordinates; exported
            # texture PNGs use top-left. Drop atlas extrusion before slicing.
            image = image.copy(round(rect["x"]),round(image.height()-rect["y"]-rect["height"]),
                               round(rect["width"]),round(rect["height"]))
        images[name] = image
    font_id = QFontDatabase.addApplicationFont(str(root / "defaultfont_cn.ttf"))
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise ValueError('Original Endfield settings font is missing or invalid')
    return (families[0], images, clips, specs)


def endfield_font(pixels=26, *, bold=False):
    font = QFont()
    font.setFamilies([resources()[0], "Microsoft YaHei UI", "DengXian", "Sans Serif"])
    font.setPixelSize(max(MIN_TEXT_PX, round(pixels)))
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return font


@lru_cache(maxsize=64)
def tinted_sprite(name, color):
    """Immutable source alpha, tinted once; never rebuild textures during motion."""
    image = resources()[1][name].copy()
    p=QPainter(image)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(image.rect(),QColor(color))
    p.end()
    return image


def nine_slice(p, image, rect, border=20, scale=1.0):
    """Source sprites retain their corners; only the middle spans stretch."""
    iw,ih=image.width(),image.height()
    if isinstance(border, dict):
        left,bottom,right,top=(float(border[k]) for k in ("x","y","z","w"))
    else:
        left=right=min(border,iw/2)
        bottom=top=min(border,ih/2)
    factor=min(scale,rect.width()/max(1,left+right),rect.height()/max(1,top+bottom))
    sx=(0,left,iw-right,iw)
    sy=(0,top,ih-bottom,ih)
    dx=(rect.left(),rect.left()+left*factor,rect.right()-right*factor,rect.right())
    dy=(rect.top(),rect.top()+top*factor,rect.bottom()-bottom*factor,rect.bottom())
    for y in range(3):
        for x in range(3):
            if dx[x+1] > dx[x] and dy[y+1] > dy[y]:
                p.drawImage(QRectF(dx[x],dy[y],dx[x+1]-dx[x],dy[y+1]-dy[y]),image,
                            QRectF(sx[x],sy[y],sx[x+1]-sx[x],sy[y+1]-sy[y]))


def source_slice(p,name,rect,scale,color=None):
    image=tinted_sprite(name,color) if color else resources()[1][name]
    border=resources()[3].get(name+'.png',{}).get('border',20)
    nine_slice(p,image,rect,border,scale)


class EndfieldSettingRow(QWidget):
    """GameSettingItemCell/Content: 130px row, original 110px content/560px control."""
    def __init__(self,label,control,scale,parent):
        super().__init__(parent)
        self.label,self.control,self.scale=label,control,scale
        label.setParent(self)
        control.setParent(self)
        label.setMinimumWidth(0)
        control.setMinimumHeight(0)
        self.setMinimumHeight(round(130*scale))
        self.setMaximumHeight(round(130*scale))
        for widget in (control, *control.findChildren(QWidget)):
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.update()
        return super().eventFilter(watched,event)

    def enterEvent(self,event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self,event):
        super().leaveEvent(event)
        self.update()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        s=self.scale
        w=self.width()
        h=self.height()
        self.label.setGeometry(round(68*s),round(h/2-36*s),max(60,round(w-720*s)),round(72*s))
        control_height=max(round(76*s),self.control.fontMetrics().height()+8)
        spin=getattr(self.control,'spin',None)
        if spin is not None:
            # A source value-above-slider control needs both complete text and
            # the 14px track. Shrinking the whole field clipped number glyphs.
            control_height=max(control_height,spin.fontMetrics().height()+16)
        self.control.setGeometry(round(w-620*s),round((h-control_height)/2),round(515*s),control_height)

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s=self.scale
        area=QRectF(10*s,15*s,self.width()-90*s,100*s)
        p.setOpacity(.4)
        source_slice(p,'row_bg',area,s)
        p.setOpacity(.149)
        p.drawImage(QRectF(20*s,19*s,470*s,92*s),resources()[1]['deco_settings_bg_contour'])
        p.setOpacity(.10)
        p.drawImage(QRectF(self.width()-295*s,19*s,127*s,92*s),resources()[1]['deco_settings_texture'])
        focus = QApplication.focusWidget()
        if self.underMouse() or (focus is not None and self.isAncestorOf(focus)):
            # Source selection is an outlined row, never a flashing fill or
            # a layout-size change. The bounded halo needs no idle timer.
            p.setOpacity(1)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for width, alpha in ((9,18),(5,45),(1.5,240)):
                p.setPen(QPen(QColor(255,241,0,alpha),max(1,width*s)))
                p.drawRect(area.adjusted(0,-4*s,0,4*s))
        p.end()


class EndfieldRowsLayout(QVBoxLayout):
    def __init__(self,parent,scale=1.0):
        super().__init__(parent)
        self.scale=scale
        self.setContentsMargins(0,0,0,0)
        self.setSpacing(0)
        self.setAlignment(Qt.AlignmentFlag.AlignTop)

    def addRow(self,label,control=None):
        if control is None:
            self.addWidget(label)
            return
        if isinstance(label,str):
            label=QLabel(label)
        label.setWordWrap(True)
        self.addWidget(EndfieldSettingRow(label,control,self.scale,self.parentWidget()))

    def insertRow(self,index,label,control):
        if isinstance(label,str):
            label=QLabel(label)
        label.setWordWrap(True)
        self.insertWidget(index,EndfieldSettingRow(label,control,self.scale,self.parentWidget()))


class EndfieldActionButton(QPushButton):
    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s=self.height()/96
        area=QRectF(self.rect()).adjusted(2,2,-2,-2)
        p.setOpacity(1 if self.isEnabled() else .35)
        source_slice(p,'button_bg',area,s,'#fff100' if self.underMouse() else '#f2f1ef')
        p.setFont(endfield_font(28*s))
        p.setPen(QColor('#444444'))
        p.drawText(area,Qt.AlignmentFlag.AlignCenter,self.text())
        p.end()


class EndfieldSectionHeader(QWidget):
    def __init__(self,text,parent=None):
        super().__init__(parent)
        self.text=text
        self.scale=.5
    def paintEvent(self,event):
        p=QPainter(self)
        s=self.scale
        p.fillRect(QRectF(0,10*s,8*s,self.height()-20*s),QColor(YELLOW))
        p.setFont(endfield_font(30*s))
        p.setPen(QColor(YELLOW))
        p.drawText(QRectF(20*s,0,self.width(),self.height()),Qt.AlignmentFlag.AlignVCenter,self.text)
        x=min(self.width()-10,round((self.fontMetrics().horizontalAdvance(self.text)+70*s)))
        p.setPen(QPen(QColor(170,173,171,100),1))
        p.drawLine(x,self.height()-4,self.width(),self.height()-4)
        p.end()


class EndfieldLoadBars(QWidget):
    """Source load-bar presentation; unavailable hardware data stays unknown."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.scale=.5
        self.setToolTip('未接入硬件采集时显示“未采集”，不会伪造设备负载或显存读数。')
    def paintEvent(self,event):
        p=QPainter(self)
        s=self.scale
        p.setFont(endfield_font(30*s))
        for i,title in enumerate(('设备负载','预计显存占用')):
            rect=QRectF(0,i*82*s,self.width(),72*s)
            p.setOpacity(.4)
            source_slice(p,'row_bg',rect,s)
            p.setOpacity(1)
            p.setPen(QColor(WHITE))
            p.drawText(rect.adjusted(58*s,0,0,0),Qt.AlignmentFlag.AlignVCenter,title)
            p.setPen(QColor('#a8aaa8'))
            p.drawText(rect.adjusted(300*s,0,0,0),Qt.AlignmentFlag.AlignVCenter,'未采集')
            gauge=QRectF(rect.right()-720*s,rect.center().y()-5*s,660*s,10*s)
            p.fillRect(gauge,QColor(180,183,180,50))
            p.setPen(QPen(QColor('#8b8d8b'),1))
            for n in range(6):
                x=gauge.left()+gauge.width()*n/5
                p.drawLine(QPointF(x,gauge.top()-2*s),QPointF(x,gauge.bottom()+2*s))
        p.end()


def sample_curve(clip, path, attribute, seconds):
    curves = resources()[2][clip]["curves"]
    keys = next(row["curve"]["m_Curve"] for row in curves if row["path"] == path and row["attribute"] == attribute)
    return sample_weighted_curve(keys, seconds)


def capture_settings_backdrop(host):
    """Read Esc's world-only GPU blur once, BEFORE scene invalidation.

    The semantic menu action hands this image to the next dialog after the
    native exit clip. Never read arbitrary stale FBOs or capture the desktop.
    """
    compositor = getattr(host,'gpu_compositor',None)
    treatment = getattr(compositor,'_backdrop_treatment',None)
    image = None
    if (getattr(compositor,'_treated_blur_valid',False)
            and getattr(treatment,'blur_kernel',None)=='endfield_gaussian'):
        try:
            host.makeCurrent()
            try:
                candidate = compositor.treated_blur_fbo.toImage()
                if not candidate.isNull():
                    image = candidate
            finally:host.doneCurrent()
        except Exception:
            logging.getLogger(__name__).exception('Could not reuse Esc world backdrop')
    host._endfield_settings_backdrop = image
    return image


class EndfieldPageTransition(QObject):
    """Original tab-change alpha clip, without moving controls or hit areas."""
    def __init__(self,parent):
        super().__init__(parent)
        self._page = self._effect = None
        self.motion = QVariantAnimation(self)
        self.motion.setDuration(round(1000*20/60))
        self.motion.setStartValue(0.0)
        self.motion.setEndValue(20/60)
        self.motion.valueChanged.connect(self._step)
        self.motion.finished.connect(self.cancel)

    def start(self,page):
        self.cancel()
        self._page = page
        self._effect = QGraphicsOpacityEffect(page)
        self._effect.setOpacity(0)
        page.setGraphicsEffect(self._effect)
        self.motion.start()

    def _step(self,seconds):
        if self._effect is not None:
            self._effect.setOpacity(sample_curve('gamesetting_change',
                'Main/ContentNode/SettingListNode','m_Alpha',seconds))

    def cancel(self,*_args):
        self.motion.stop()
        page,self._page = self._page,None
        self._effect = None
        if page is not None:
            page.setGraphicsEffect(None)


class EndfieldDialog(JelloDialog):
    """Reuse fullscreen/input ownership, replace Jello zoom with authored slides."""
    def __init__(self, parent=None, **kwargs):
        resources()
        super().__init__(parent, **kwargs)
        self._world_backdrop = getattr(parent,'_endfield_settings_backdrop',None)
        if self._world_backdrop is None and parent is not None:
            self._world_backdrop = capture_settings_backdrop(parent)
        if parent is not None:
            parent._endfield_settings_backdrop = None
        self.timeline = JelloReversibleAnimation(25 / 60, 10 / 60)
        self.panel.setObjectName("EndfieldPanel")
        self.panel.setStyleSheet("QWidget#EndfieldPanel {background:transparent;}")
        self.panel.layout().setContentsMargins(28, 20, 28, 22)
        self.theme_scale = 1.0

    def _position_panel(self):
        self.panel.setGeometry(self.rect())

    def visual_factor(self):
        return 1.0  # No Jello elastic enlargement / text resampling in settings.

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#343638"))
        if self._world_backdrop is not None:
            image=self._world_backdrop
            factor=max(self.width()/image.width(),self.height()/image.height())
            source=QRectF(0,0,self.width()/factor,self.height()/factor)
            source.moveCenter(QPointF(image.width()/2,image.height()/2))
            painter.drawImage(QRectF(self.rect()),image,source)
            painter.fillRect(self.rect(),QColor(12,15,14,140))
        scale = self.theme_scale
        if self._surface is not None:
            opening = self.timeline.target > .5
            clip = "gamesetting_in" if opening else "gamesetting_out"
            duration = self.timeline.forward_duration if opening else self.timeline.reverse_duration
            seconds = (self.timeline.progress if opening else 1-self.timeline.progress) * duration
            top_offset = -sample_curve(clip, "Main/TopNode", "m_AnchoredPosition.y", seconds)*scale
            content_offset = (-45-sample_curve(clip, "Main/ContentNode", "m_AnchoredPosition.y", seconds))*scale
            alpha = sample_curve(clip, "Main/ContentNode", "m_Alpha", seconds)
            split = min(self.height(), round(110*scale))
            # One DPR-aware snapshot; authored header/content move independently.
            for area, offset in ((QRectF(0,0,self.width(),split),top_offset),
                                 (QRectF(0,split,self.width(),self.height()-split),content_offset)):
                painter.save()
                painter.setClipRect(area.translated(0,offset))
                painter.setOpacity(alpha)
                painter.drawPixmap(QPointF(0,offset), self._surface)
                painter.restore()
        painter.end()


class EndfieldCheckBox(QCheckBox):
    """GameSettingPanel's two-segment toggle; native focus/keyboard semantics."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._value = float(self.isChecked())
        self._motion = QVariantAnimation(self)
        self._motion.setDuration(200)
        self._motion_from = self._value
        self._motion_to = self._value
        self._motion.valueChanged.connect(self._step)
        self.toggled.connect(self._toggle)
        self.setMinimumSize(0, 0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _step(self, value):
        clip = 'common_toggle_to_left01' if self._motion_to else 'common_toggle_to_right01'
        anchored = sample_curve(clip,'SelectedBG','m_AnchorMax.x',float(value)*.2)
        fraction = 1-anchored if self._motion_to else anchored
        self._value = self._motion_from + (self._motion_to-self._motion_from)*fraction
        self.update()

    def _toggle(self, checked):
        self._motion.stop()
        if not self.isVisible():
            self._value = float(checked)
            self.update()
            return
        self._motion_from,self._motion_to = self._value,float(checked)
        self._motion.setStartValue(0.0)
        self._motion.setEndValue(1.0)
        self._motion.start()

    def sizeHint(self):
        return QSize(270, 46)

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.rect()).adjusted(1, 2, -1, -2)
        p.setBrush(QColor("#626262"))
        p.drawRoundedRect(rect, rect.height()/2, rect.height()/2)
        half = rect.width()/2
        selected = QRectF(rect.left()+(1-self._value)*half,rect.top(),half,rect.height())
        source_slice(p,'toggle_bg',selected,self.height()/78,WHITE)
        p.setFont(self.font())
        for i, text in enumerate(("开", "关")):
            p.setPen(QColor(INK if abs(self._value-(1-i)) < .5 else "#cccccc"))
            p.drawText(QRectF(rect.left()+i*half,rect.top(),half,rect.height()), Qt.AlignmentFlag.AlignCenter, text)
        if self.hasFocus():
            p.setPen(QPen(QColor(YELLOW), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
        p.end()


class EndfieldComboBox(QComboBox):
    """Original capsule presentation with native Qt popup/input ownership.

    Do not inherit Jello's 220ms popup resize: it changes option geometry and
    is not an animation present in the exported settings clips.
    """
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view().setStyleSheet('QAbstractItemView {background:#eeeeee;color:#333333;'
            'border:1px solid #999999;selection-background-color:#fff100;'
            'selection-color:#212121;outline:0;padding:4px;}')
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5,.5,-.5,-.5)
        source_slice(p,'toggle_bg',rect,self.height()/78,'#ffffff' if self.underMouse() else '#eeeeee')
        p.setFont(self.font())
        p.setPen(QColor('#444444'))
        text_rect = rect.adjusted(18,0,-42,0)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.fontMetrics().elidedText(self.currentText(), Qt.TextElideMode.ElideRight, max(1,round(text_rect.width()))))
        x,y = rect.right()-24,rect.center().y()
        p.drawImage(QRectF(x-6,y-4,12,8),tinted_sprite('arrow','#444444'))
        p.end()


class EndfieldCloseButton(QPushButton):
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect())
        p.setOpacity(.8 if self.underMouse() else 1)
        p.drawImage(area,resources()[1]['close'])
        p.end()


class EndfieldTabBar(QTabBar):
    ICONS = ("icon_settings_computer", "icon_settings_audio", "icon_settings_control",
             "icon_settings_keystroke", "icon_setting_controller", "icon_settings_language")
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scale = 1.0
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setMouseTracking(True)
        resources()
        self._icons = []
        for name in self.ICONS:
            normal = resources()[1][name]
            selected = normal.copy()
            p = QPainter(selected)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            p.fillRect(selected.rect(),QColor(INK))
            p.end()
            self._icons.append((normal, selected))

    def tabSizeHint(self, index):
        return QSize(round(168*self.scale),round(100*self.scale))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.scale
        for i in range(self.count()):
            rect = QRectF(self.tabRect(i)).adjusted(1,0,-1,0)
            selected = i == self.currentIndex()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#faf9f9"))
            if selected:
                p.drawImage(rect.adjusted(-2*s,-6*s,2*s,6*s),resources()[1]['tab_selected'])
            else:
                p.setOpacity(.25 if self.tabAt(self.mapFromGlobal(self.cursor().pos()))==i else .12)
                p.drawImage(rect,resources()[1]['deco_settings_texture'])
                p.setOpacity(1)
                p.setPen(QPen(QColor(230,230,230,35),1))
                p.drawLine(rect.topRight(),rect.bottomRight())
            image = self._icons[i % len(self.ICONS)][int(selected)]
            p.drawImage(QRectF(rect.center().x()-25*s,rect.center().y()-25*s,50*s,50*s),image)
        p.end()


def theme_stylesheet(scale=1.0):
    s = max(1/3, min(1.25, scale))
    px = lambda n: max(1, round(n*s))
    family = resources()[0]
    return f"""
    QWidget {{font-family:"{family}","Microsoft YaHei UI";font-size:{max(MIN_TEXT_PX,px(30))}px;color:{WHITE};background:transparent;}}
    QLabel {{background:transparent;}}
    QScrollArea,QScrollArea > QWidget > QWidget,QTabWidget::pane {{background:transparent;border:0;}}
    QTabWidget::tab-bar {{alignment:center;}}
    QTabBar::tab {{background:transparent;}}
    QGroupBox {{background:transparent;border:0;margin-top:{px(47)}px;padding:0;}}
    QGroupBox::title {{subcontrol-origin:margin;left:{px(18)}px;top:0;color:{WHITE};font-size:{max(MIN_TEXT_PX,px(30))}px;}}
    QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit {{background:#5a5c5e;border:1px solid #747577;border-radius:3px;padding:{px(10)}px {px(14)}px;min-height:{px(38)}px;selection-background-color:{YELLOW};selection-color:{INK};}}
    QComboBox:focus,QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus {{border-color:{YELLOW};}}
    QComboBox QAbstractItemView,QListWidget {{background:#444648;color:{WHITE};border:1px solid #868789;selection-background-color:{YELLOW};selection-color:{INK};padding:{px(8)}px;outline:0;}}
    QPushButton {{background:#555759;border:1px solid #a7a8a8;border-radius:{px(26)}px;padding:{px(12)}px {px(26)}px;min-height:{px(32)}px;}}
    QPushButton:hover {{background:#717375;border-color:{YELLOW};}}
    QPushButton:pressed {{background:#8c8c82;color:{INK};}}
    QPushButton:focus {{border-color:{YELLOW};}}
    QPushButton[primary="true"] {{background:{YELLOW};color:{INK};border-color:{YELLOW};}}
    QPushButton:disabled {{color:#929496;background:#36383a;border-color:#56585a;}}
    QSlider::groove:horizontal {{height:{px(4)}px;background:#818283;}}
    QSlider::sub-page:horizontal {{background:{WHITE};}}
    QSlider::handle:horizontal {{width:{px(44)}px;height:{px(18)}px;margin:-{px(7)}px 0;background:{WHITE};border:0;border-radius:{px(8)}px;}}
    QScrollBar:vertical {{background:#333537;width:{px(8)}px;border:0;}}
    QScrollBar::handle:vertical {{background:#afb1b0;min-height:{px(36)}px;}}
    QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
    QToolTip {{background:#303234;color:{WHITE};border:1px solid #777;padding:8px;}}
    """


def apply_endfield_widgets(widget, *, scale=None, stylesheet=True):
    scale = scale if scale is not None else settings_scale(widget.width(),widget.height())
    widget.setFont(endfield_font(26*scale))
    palette = widget.palette()
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base):
        palette.setColor(role,QColor("#303234"))
    for role in (QPalette.ColorRole.WindowText,QPalette.ColorRole.Text,QPalette.ColorRole.ButtonText):
        palette.setColor(role,QColor(WHITE))
    widget.setPalette(palette)
    if stylesheet:
        widget.setStyleSheet(theme_stylesheet(scale))
