from __future__ import annotations

from dataclasses import dataclass
import math
import struct

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
)


_GL_BLEND = 0x0BE2
_GL_CULL_FACE = 0x0B44
_GL_DEPTH_TEST = 0x0B71
_GL_FLOAT = 0x1406
_GL_FUNC_ADD = 0x8006
_GL_ONE = 1
_GL_ONE_MINUS_SRC_ALPHA = 0x0303
_GL_SCISSOR_TEST = 0x0C11
_GL_TRIANGLES = 0x0004


@dataclass(frozen=True)
class IslandIconCommand:
    """A circular island icon with no rectangular fill primitive."""

    rect: QRectF
    kind: str
    color: QColor
    amount: float = 1.0


def island_icon_coverage(x: float, y: float) -> float:
    """Reference circle coverage used by alpha regression tests.

    Coordinates are normalized to ``0..1`` within the icon bounds. Corners
    are intentionally transparent; the GPU shader applies antialiasing only
    close to the circular edge.
    """

    dx = (float(x) - 0.5) * 2.0
    dy = (float(y) - 0.5) * 2.0
    return 1.0 if math.hypot(dx, dy) < 1.0 else 0.0


class IslandIconGpuRenderer:
    """Premultiplied SDF renderer for Dynamic Island status icons."""

    _KINDS = {"info": 0.0, "success": 1.0, "warning": 2.0, "module": 3.0}

    def __init__(self) -> None:
        self.available = False
        self.last_error = ""
        self.program: QOpenGLShaderProgram | None = None
        self.buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.vertex_array = QOpenGLVertexArrayObject()
        self.draw_calls = 0

    def initialize(self) -> bool:
        if self.available:
            return True
        try:
            self.program = self._build_program()
            if not self.vertex_array.create():
                raise RuntimeError("island icon VAO creation failed")
            if not self.buffer.create():
                raise RuntimeError("island icon VBO creation failed")
            self.available = True
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self.release()
            return False

    @staticmethod
    def _rgba(color: QColor) -> tuple[float, float, float, float]:
        return color.redF(), color.greenF(), color.blueF(), color.alphaF()

    def _vertices(self, commands: list[IslandIconCommand], ratio: float) -> bytes:
        packed = bytearray()
        for command in commands:
            rect = command.rect
            x0 = rect.left() * ratio
            y0 = rect.top() * ratio
            x1 = rect.right() * ratio
            y1 = rect.bottom() * ratio
            if x1 <= x0 or y1 <= y0:
                continue
            rgba = self._rgba(command.color)
            params = (
                self._KINDS.get(command.kind, 0.0),
                max(0.0, min(1.0, float(command.amount))),
            )
            vertices = (
                (x0, y0, -1.0, -1.0),
                (x1, y0, 1.0, -1.0),
                (x0, y1, -1.0, 1.0),
                (x0, y1, -1.0, 1.0),
                (x1, y0, 1.0, -1.0),
                (x1, y1, 1.0, 1.0),
            )
            for px, py, lx, ly in vertices:
                packed.extend(struct.pack("10f", px, py, lx, ly, *rgba, *params))
        return bytes(packed)

    def render(
        self,
        functions,
        commands: list[IslandIconCommand],
        width: int,
        height: int,
        device_pixel_ratio: float,
    ) -> bool:
        if not self.available or self.program is None:
            return False
        ratio = max(1.0, float(device_pixel_ratio))
        payload = self._vertices(commands, ratio)
        self.draw_calls = 0
        if not payload:
            return True
        try:
            physical_width = max(1, round(width * ratio))
            physical_height = max(1, round(height * ratio))
            functions.glViewport(0, 0, physical_width, physical_height)
            functions.glDisable(_GL_DEPTH_TEST)
            functions.glDisable(_GL_CULL_FACE)
            functions.glDisable(_GL_SCISSOR_TEST)
            functions.glEnable(_GL_BLEND)
            functions.glBlendEquation(_GL_FUNC_ADD)
            functions.glBlendFunc(_GL_ONE, _GL_ONE_MINUS_SRC_ALPHA)

            self.program.bind()
            functions.glUniform2f(
                self.program.uniformLocation("viewport"),
                float(physical_width),
                float(physical_height),
            )
            self.vertex_array.bind()
            self.buffer.bind()
            self.buffer.allocate(payload, len(payload))
            stride = 10 * 4
            for location, size, offset in (
                (0, 2, 0),
                (1, 2, 8),
                (2, 4, 16),
                (3, 2, 32),
            ):
                self.program.enableAttributeArray(location)
                self.program.setAttributeBuffer(location, _GL_FLOAT, offset, size, stride)
            functions.glDrawArrays(_GL_TRIANGLES, 0, len(payload) // stride)
            for location in range(4):
                self.program.disableAttributeArray(location)
            self.buffer.release()
            self.vertex_array.release()
            self.program.release()
            self.draw_calls = 1
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False
        finally:
            functions.glDisable(_GL_BLEND)
            functions.glDisable(_GL_SCISSOR_TEST)
            functions.glDisable(_GL_DEPTH_TEST)
            functions.glDisable(_GL_CULL_FACE)

    @staticmethod
    def _build_program() -> QOpenGLShaderProgram:
        vertex = """
            #version 330
            layout(location=0) in vec2 position;
            layout(location=1) in vec2 localPosition;
            layout(location=2) in vec4 iconColor;
            layout(location=3) in vec2 iconParams;
            uniform vec2 viewport;
            out vec2 local;
            out vec4 color;
            out vec2 params;
            void main() {
                vec2 ndc = vec2(
                    position.x / viewport.x * 2.0 - 1.0,
                    1.0 - position.y / viewport.y * 2.0
                );
                gl_Position = vec4(ndc, 0.0, 1.0);
                local = localPosition;
                color = iconColor;
                params = iconParams;
            }
        """
        fragment = """
            #version 330
            in vec2 local;
            in vec4 color;
            in vec2 params;
            out vec4 fragColor;

            float sdSegment(vec2 p, vec2 a, vec2 b) {
                vec2 pa = p - a;
                vec2 ba = b - a;
                float h = clamp(dot(pa, ba) / max(dot(ba, ba), 0.0001), 0.0, 1.0);
                return length(pa - ba * h);
            }

            float lineMask(vec2 p, vec2 a, vec2 b, float width) {
                float d = sdSegment(p, a, b);
                float aa = max(fwidth(d), 0.008);
                return 1.0 - smoothstep(width - aa, width + aa, d);
            }

            void main() {
                float radius = length(local);
                float edgeAa = max(fwidth(radius) * 1.25, 0.006);
                float circle = 1.0 - smoothstep(1.0 - edgeAa, 1.0 + edgeAa, radius);
                if (circle <= 0.0) discard;

                float kind = params.x;
                float amount = clamp(params.y, 0.0, 1.0);
                float symbol = 0.0;
                vec3 symbolColor = vec3(1.0);

                if (kind < 0.5) {
                    float extent = 0.34 * amount;
                    symbol = max(
                        lineMask(local, vec2(-extent, 0.0), vec2(extent, 0.0), 0.055),
                        lineMask(local, vec2(0.0, -extent), vec2(0.0, extent), 0.055)
                    );
                } else if (kind < 1.5) {
                    symbol = max(
                        lineMask(local, vec2(-0.38, 0.02), vec2(-0.10, 0.30), 0.060),
                        lineMask(local, vec2(-0.10, 0.30), vec2(0.42, -0.30), 0.060)
                    ) * amount;
                } else if (kind < 2.5) {
                    symbol = lineMask(local, vec2(0.0, -0.42), vec2(0.0, 0.16), 0.055) * amount;
                    float dotRadius = length(local - vec2(0.0, 0.42));
                    symbol = max(symbol, (1.0 - smoothstep(0.08, 0.11, dotRadius)) * amount);
                } else {
                    vec2 q = vec2(local.x / 0.68, local.y / 0.28);
                    float track = 1.0 - smoothstep(1.0, 1.08, length(max(abs(q) - vec2(0.72, 0.0), 0.0)) + min(max(abs(q).x - 0.72, abs(q).y), 0.0));
                    vec2 knobCenter = vec2(mix(-0.33, 0.33, amount), 0.0);
                    float knob = 1.0 - smoothstep(0.22, 0.25, length(local - knobCenter));
                    symbolColor = mix(vec3(0.10, 0.11, 0.14), vec3(0.98), knob);
                    symbol = max(track * 0.68, knob);
                }

                float rim = smoothstep(0.78, 0.98, radius) * (1.0 - smoothstep(0.98, 1.02, radius));
                float baseAlpha = color.a * circle;
                vec4 base = vec4(color.rgb * baseAlpha, baseAlpha);
                float rimAlpha = rim * 0.10 * circle;
                vec4 rimLayer = vec4(vec3(rimAlpha), rimAlpha);
                float symbolAlpha = symbol * 0.94 * circle;
                vec4 symbolLayer = vec4(symbolColor * symbolAlpha, symbolAlpha);
                vec4 composed = rimLayer + base * (1.0 - rimLayer.a);
                fragColor = symbolLayer + composed * (1.0 - symbolLayer.a);
            }
        """
        program = QOpenGLShaderProgram()
        if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vertex):
            raise RuntimeError(program.log())
        if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fragment):
            raise RuntimeError(program.log())
        if not program.link():
            raise RuntimeError(program.log())
        return program

    def release(self) -> None:
        if self.buffer.isCreated():
            self.buffer.destroy()
        if self.vertex_array.isCreated():
            self.vertex_array.destroy()
        if self.program is not None:
            self.program.removeAllShaders()
        self.program = None
        self.available = False
