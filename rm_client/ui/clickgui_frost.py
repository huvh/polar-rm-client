"""对 ClickGUI 当前页面做两遍 GPU 磨砂，覆盖层文字保持清晰。"""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtOpenGL import (
    QOpenGLFramebufferObject, QOpenGLShader, QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
)


def raster_frost(image, radius):
    """无 OpenGL 时保留同样的页面覆盖关系，使用 Qt 的模糊效果。"""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(image))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    result = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(0)
    painter = QPainter(result)
    bounds = QRectF(0, 0, image.width(), image.height())
    scene.render(painter, bounds, bounds)
    painter.end()
    return result


class ClickGuiFrost:
    def __init__(self):
        self.source = self.reduced = self.temporary = None
        self.program = None
        self.vao = QOpenGLVertexArrayObject()
        self.size = QSize()
        self.passes = 0

    def _prepare(self, width, height):
        size = QSize(width, height)
        if size != self.size:
            self.source = QOpenGLFramebufferObject(size)
            reduced_size = QSize(max(1,width//8),max(1,height//8))
            self.reduced = QOpenGLFramebufferObject(reduced_size)
            self.temporary = QOpenGLFramebufferObject(reduced_size)
            if not self.source.isValid() or not self.reduced.isValid() or not self.temporary.isValid():
                raise RuntimeError("Wiki frost framebuffer creation failed")
            self.size = size
        if self.program is None:
            self.program = QOpenGLShaderProgram()
            vertex = """#version 330
                out vec2 uv;
                void main() {
                    vec2 p = vec2(gl_VertexID & 1, (gl_VertexID >> 1) & 1);
                    uv = p; gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
                }
            """
            fragment = """#version 330
                in vec2 uv; out vec4 color;
                uniform sampler2D sourceTex;
                uniform sampler2D originalTex;
                uniform vec2 stepUV;
                uniform float amount;
                uniform int finalPass;
                void main() {
                    vec4 total = vec4(0.0); float weight = 0.0;
                    for (int i = -8; i <= 8; ++i) {
                        float w = exp(-float(i*i) / 18.0);
                        total += texture(sourceTex, clamp(uv + float(i) * stepUV,
                                         vec2(0.0), vec2(1.0))) * w;
                        weight += w;
                    }
                    vec4 blurred = total / weight;
                    color = finalPass == 1 ? mix(texture(originalTex, uv), blurred, amount) : blurred;
                }
            """
            for kind, source in ((QOpenGLShader.ShaderTypeBit.Vertex, vertex),
                                 (QOpenGLShader.ShaderTypeBit.Fragment, fragment)):
                if not self.program.addShaderFromSourceCode(kind, source):
                    raise RuntimeError(self.program.log())
            if not self.program.link() or not self.vao.create():
                raise RuntimeError("Wiki frost shader creation failed: " + self.program.log())

    def render(self, functions, width, height, draw_background, *, radius, amount):
        destination = functions.glGetIntegerv(0x8CA6)  # GL_DRAW_FRAMEBUFFER_BINDING
        try:
            self._prepare(width, height)
            if not self.source.bind():
                raise RuntimeError("Wiki frost source binding failed")
            functions.glViewport(0, 0, width, height)
            functions.glDisable(0x0C11)  # GL_SCISSOR_TEST
            functions.glClearColor(0, 0, 0, 0)
            functions.glClear(0x4000)
            if not draw_background():
                raise RuntimeError("Wiki frost background rendering failed")
            # 大半径必须先低通降采样；在全分辨率直接拉大采样间距会出现竖向条带。
            functions.glBindFramebuffer(0x8CA8,self.source.handle())  # GL_READ_FRAMEBUFFER
            functions.glBindFramebuffer(0x8CA9,self.reduced.handle())  # GL_DRAW_FRAMEBUFFER
            functions.glBlitFramebuffer(0,0,width,height,0,0,self.reduced.width(),self.reduced.height(),0x4000,0x2601)
            self.vao.bind()
            if not self.program.bind():
                raise RuntimeError("Wiki frost shader binding failed")
            functions.glDisable(0x0BE2)  # GL_BLEND
            functions.glDisable(0x0C11)
            functions.glUniform1i(self.program.uniformLocation("sourceTex"), 0)
            functions.glUniform1i(self.program.uniformLocation("originalTex"), 1)
            functions.glUniform1f(self.program.uniformLocation("amount"), float(amount))
            functions.glActiveTexture(0x84C1)
            functions.glBindTexture(0x0DE1, self.source.texture())
            for final, texture in ((False, self.reduced.texture()), (True, self.temporary.texture())):
                if final:
                    functions.glBindFramebuffer(0x8D40, int(destination))
                elif not self.temporary.bind():
                    raise RuntimeError("Wiki frost temporary binding failed")
                functions.glViewport(0,0,width if final else self.temporary.width(),height if final else self.temporary.height())
                functions.glActiveTexture(0x84C0)
                functions.glBindTexture(0x0DE1, texture)
                functions.glTexParameteri(0x0DE1, 0x2801, 0x2601)
                functions.glTexParameteri(0x0DE1, 0x2800, 0x2601)
                functions.glUniform1i(self.program.uniformLocation("finalPass"), int(final))
                functions.glUniform2f(self.program.uniformLocation("stepUV"),
                                      0 if final else radius / (8 * width),
                                      radius / (8 * height) if final else 0)
                functions.glDrawArrays(0x0005, 0, 4)
                self.passes += 1
        finally:
            functions.glBindFramebuffer(0x8D40, int(destination))
            if self.program:
                self.program.release()
            self.vao.release()
            functions.glActiveTexture(0x84C1)
            functions.glBindTexture(0x0DE1, 0)
            functions.glActiveTexture(0x84C0)

    def release(self):
        self.source = self.reduced = self.temporary = None
        self.size = QSize()
        if self.vao.isCreated():
            self.vao.destroy()
        if self.program:
            self.program.removeAllShaders()
        self.program = None
