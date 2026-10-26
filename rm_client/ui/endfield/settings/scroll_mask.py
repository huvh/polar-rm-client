"""本体设置列表的纵向50单位软边，局部合成背景，不抓取控件或GL帧。"""
from PySide6.QtCore import Qt, QRectF, QPoint
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

from .background import paint_background


class ScrollMask(QWidget):
    def __init__(self, scroll):
        super().__init__(scroll.viewport())
        self.scroll = scroll
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def refresh(self):
        self.setGeometry(self.scroll.viewport().rect())
        self.raise_()
        self.update()

    def paintEvent(self, event):
        scroll = self.scroll
        surface = scroll.parentWidget()
        while surface is not None and not hasattr(surface,"backdrop"):
            surface = surface.parentWidget()
        if surface is None or scroll.verticalScrollBar().maximum() <= 0:
            return
        scale = scroll.motion.scale
        height = max(1,round(scroll.motion.config["mask_softness"]["y"]*scale))
        origin = self.mapTo(surface,QPoint())
        ratio = self.devicePixelRatioF()
        painter = QPainter(self)
        for top in (True,False):
            if top and scroll.motion.position <= 0:
                continue
            if not top and scroll.motion.position >= scroll.motion.maximum:
                continue
            y = 0 if top else self.height()-height
            image = QImage(round(self.width()*ratio),round(height*ratio),QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            layer = QPainter(image)
            layer.scale(ratio,ratio)
            layer.translate(-origin.x(),-origin.y()-y)
            paint_background(layer,surface.rect(),surface.backdrop)
            layer.resetTransform()
            layer.scale(ratio,ratio)
            layer.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            gradient = QLinearGradient(0,0,0,height)
            bottom_strength = max(0,min(1,1+scroll.motion.config["mask_padding"]["w"]/
                                        max(1,scroll.motion.config["mask_softness"]["y"])))
            gradient.setColorAt(0,QColor(0,0,0,255 if top else 0))
            gradient.setColorAt(1,QColor(0,0,0,0 if top else round(255*bottom_strength)))
            layer.fillRect(QRectF(0,0,self.width(),height),gradient)
            layer.end()
            image.setDevicePixelRatio(ratio)
            painter.drawImage(QPoint(0,y),image)
