"""设置打开时冻结并模糊客户端自己的GL帧，避免持续读回或外部窗口截屏。"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap, QColor, QRadialGradient
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene

from .resources import texture


def paint_background(painter, rect, backdrop=None):
    """主底与滚动软遮罩共用同一背景，边缘不会出现固定颜色的盖板。"""
    painter.fillRect(rect,QColor("#0a0d0e"))
    if backdrop is not None and not backdrop.isNull():
        painter.drawImage(QRectF(rect),backdrop)
        painter.fillRect(rect,QColor(7,10,11,220))
    glow = QRadialGradient(rect.width()*.3,rect.height()*.38,rect.width()*.65)
    glow.setColorAt(0,QColor(84,82,75,180))
    glow.setColorAt(1,QColor(22,25,26,0))
    painter.fillRect(rect,glow)
    painter.save()
    painter.setOpacity(.1)
    painter.drawImage(QRectF(rect.width()*.025,0,rect.width()*.1,rect.height()*.14),texture("background_deco"))
    painter.restore()


def capture_backdrop(host):
    if not isinstance(host,QOpenGLWidget) or not host.isValid():
        return QImage()
    frame = host.grabFramebuffer()
    if frame.isNull():
        return frame
    # 与游戏全屏模糊覆盖关系一致；内核由Qt适配，固定帧仅在打开时处理一次。
    frame = frame.scaled(max(1,frame.width()//4),max(1,frame.height()//4),
                         Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
    frame.setDevicePixelRatio(1)
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(frame))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(24)
    effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    image = QImage(frame.size(),QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    scene.render(painter,QRectF(image.rect()),QRectF(frame.rect()))
    painter.end()
    return image
