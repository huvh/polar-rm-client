"""GameSettingKeycodePopup独立按键输入模态，保留原版闪现与横向展开轨道。"""
import time

from PySide6.QtCore import Qt, QTimer, QRectF, QRect, QEvent
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QDialog, QWidget, QVBoxLayout, QLabel, QPushButton, QGraphicsOpacityEffect

from ...emergency_shortcut import install_estop_shortcut
from ..settings.geometry import SettingsGeometryGuard
from ..settings.resources import ui_font
from .resources import source, motion, texture


class KeyCapturePopup(QDialog):
    def __init__(self, owner, entry):
        super().__init__(owner,Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("EndfieldKeyCapture")
        self.owner, self.entry = owner, entry
        self.selected_key = None
        self._closing = False
        self._result = QDialog.DialogCode.Rejected
        self._started = time.perf_counter()
        self.card = QWidget(self)
        layout = QVBoxLayout(self.card)
        self.title = QLabel(entry.title)
        self.title.setStyleSheet("color:#eeeeee;")
        self.hint = QLabel("请按下新的快捷键")
        self.status = QLabel("Esc 取消 · F12 急停始终有效")
        for label in (self.title,self.hint,self.status):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            layout.addWidget(label)
        cancel = QPushButton("取消 · Esc")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel,alignment=Qt.AlignmentFlag.AlignCenter)
        self.card.setStyleSheet("QWidget{color:#444;background:transparent;} QPushButton{background:#eeeded;color:#444;border:1px solid #fff;border-radius:16px;padding:6px 28px;}")
        self._effect = QGraphicsOpacityEffect(self.card)
        self.card.setGraphicsEffect(self._effect)
        self._timer = QTimer(self)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._advance)
        self._geometry_guard = SettingsGeometryGuard(owner,self)
        self.estop_shortcut = install_estop_shortcut(self,owner.session.host)

    def fit_client_geometry(self, rect):
        self.setGeometry(rect)

    def showEvent(self, event):
        super().showEvent(event)
        self._geometry_guard.sync()
        self._started = time.perf_counter()
        self._timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        scale = min(self.width()/1920,self.height()/1080)
        width,height = (round(value*scale) for value in source()["popup_size"])
        self.card.setGeometry(QRect((self.width()-width)//2,(self.height()-height)//2,width,height))
        self.card.layout().setContentsMargins(round(34*scale),round(20*scale),round(34*scale),round(20*scale))
        self.card.setFont(ui_font(max(13,26*scale)))
        self.title.setFont(ui_font(max(16,source()["title_font_size"]*scale)))

    def keyPressEvent(self, event):
        event.accept()
        if event.isAutoRepeat() or self._closing:
            return
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        if event.key() in (Qt.Key.Key_F11,Qt.Key.Key_F12):
            return
        key = self.owner.session.host.key_name(event)
        key = next((key_name for key_name in self.owner.keys if key_name.casefold() == key.casefold()),key)
        if key not in self.owner.keys:
            self.status.setText("此按键不支持绑定，请重新按键")
            return
        reason = self.owner.session.reason(self.entry,key)
        if reason:
            self.status.setText(reason)
        else:
            self.selected_key = key
            self.accept()

    def event(self, event):
        # Tab属于可绑定输入，不能先交给QDialog的焦点遍历。
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Tab:
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def done(self, result):
        if self._closing:
            return
        self._closing = True
        self._result = result
        self._started = time.perf_counter()
        self._timer.start()

    def _advance(self):
        clip = "gamesettingkeycodepopup_out" if self._closing else "gamesettingkeycodepopup_in"
        at = time.perf_counter()-self._started
        alpha = motion().sample(clip,"Main" if self._closing else "Main/Content","m_Alpha",at,1)
        self._effect.setOpacity(max(0,min(1,alpha)))
        self.update()
        if at >= motion().durations[clip]:
            self._timer.stop()
            if self._closing:
                super().done(self._result)

    def paintEvent(self, event):
        painter = QPainter(self)
        at = time.perf_counter()-self._started
        clip = "gamesettingkeycodepopup_out" if self._closing else "gamesettingkeycodepopup_in"
        main_alpha = motion().sample(clip,"Main","m_Alpha",at,1)
        shade = .5 if self._closing else motion().sample(clip,"Main/CommonPopUpBg/Mask","m_Color.a",at,.5)
        painter.fillRect(self.rect(),QColor(0,0,0,round(255*shade*main_alpha)))
        rect = QRectF(self.card.geometry())
        if not self._closing:
            value = motion().sample(clip,"Main/CommonPopUpBg/Content/BG","m_SizeDelta.x",at,428)
            rect.setWidth(rect.width()*max(0,min(1,(value+1912.4094)/2340.4094)))
            rect.moveCenter(QRectF(self.card.geometry()).center())
        painter.setOpacity(main_alpha)
        painter.drawImage(rect.adjusted(-10,-10,10,10),texture("pup_up_shadow"))
        painter.drawImage(rect,texture("pup_up_bg"))
