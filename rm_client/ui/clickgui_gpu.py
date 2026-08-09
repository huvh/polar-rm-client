from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import struct
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)


_GL_FLOAT = 0x1406
_GL_TRIANGLE_STRIP = 0x0005
_GL_BLEND = 0x0BE2
_GL_ONE = 1
_GL_ONE_MINUS_SRC_ALPHA = 0x0303
_GL_SCISSOR_TEST = 0x0C11
_GL_DEPTH_TEST = 0x0B71
_GL_CULL_FACE = 0x0B44
_GL_STENCIL_TEST = 0x0B90
_GL_FUNC_ADD = 0x8006
_GL_TEXTURE0 = 0x84C0
_GL_TEXTURE_2D = 0x0DE1


@dataclass(frozen=True)
class GpuRect:
    rect: QRectF
    radius: float
    fill: QColor
    outline: QColor = field(default_factory=lambda: QColor(0, 0, 0, 0))
    outline_width: float = 0.0
    gradient: QColor | None = None
    clip: QRectF | None = None


@dataclass(frozen=True)
class GpuText:
    rect: QRectF
    text: str
    font: QFont
    color: QColor
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    clip: QRectF | None = None
    shadow: bool = True
    rotation_degrees: float = 0.0
    render_scale: float = 1.0
    rotation_origin: QPointF | None = None
    raster_scale: float = 1.0
    preserve_weight: bool = False


@dataclass(frozen=True)
class GpuImage:
    rect: QRectF
    source: str
    tint: QColor = field(default_factory=lambda: QColor(255, 255, 255, 255))
    clip: QRectF | None = None


@dataclass(frozen=True)
class GpuUiCommand:
    """A stable, ordered UI command.

    The payload is deliberately immutable so a frame can be submitted without
    a builder mutating its geometry while the GPU is consuming it.
    """

    sequence: int
    payload: GpuRect | GpuText | GpuImage
    layer: int = 0
    opacity: float = 1.0


@dataclass
class ClickGuiDrawList:
    rects: list[GpuRect] = field(default_factory=list)
    texts: list[GpuText] = field(default_factory=list)
    images: list[GpuImage] = field(default_factory=list)
    commands: list[GpuUiCommand] = field(default_factory=list)
    default_text_shadow: bool = True
    default_text_raster_scale: float = 1.0
    default_text_preserve_weight: bool = False

    def _append(self, payload: GpuRect | GpuText | GpuImage, *, layer: int = 0, opacity: float = 1.0) -> None:
        self.commands.append(GpuUiCommand(len(self.commands), payload, layer, opacity))

    def rect(self, rect: QRectF, radius: float, fill: QColor, outline: QColor | None = None, outline_width: float = 0.0, gradient: QColor | None = None, clip: QRectF | None = None) -> None:
        payload = GpuRect(QRectF(rect), radius, QColor(fill), QColor(outline) if outline else QColor(0, 0, 0, 0), outline_width, QColor(gradient) if gradient else None, QRectF(clip) if clip else None)
        self.rects.append(payload)
        self._append(payload)

    def text(self, rect: QRectF, text: str, font: QFont, color: QColor, alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, clip: QRectF | None = None, *, shadow: bool | None = None, rotation_degrees: float = 0.0, render_scale: float = 1.0, rotation_origin: QPointF | None = None, raster_scale: float | None = None, preserve_weight: bool | None = None) -> None:
        if text:
            draw_shadow = self.default_text_shadow if shadow is None else bool(shadow)
            payload = GpuText(
                QRectF(rect),
                text,
                QFont(font),
                QColor(color),
                alignment,
                QRectF(clip) if clip else None,
                draw_shadow,
                float(rotation_degrees),
                max(0.01, float(render_scale)),
                QPointF(rotation_origin) if rotation_origin is not None else None,
                max(
                    0.25,
                    float(
                        self.default_text_raster_scale
                        if raster_scale is None
                        else raster_scale
                    ),
                ),
                (
                    self.default_text_preserve_weight
                    if preserve_weight is None
                    else bool(preserve_weight)
                ),
            )
            self.texts.append(payload)
            self._append(payload)

    def image(self, rect: QRectF, source: str | Path, tint: QColor | None = None, clip: QRectF | None = None) -> None:
        source_path = str(Path(source).expanduser().resolve())
        payload = GpuImage(
            QRectF(rect),
            source_path,
            QColor(tint) if tint is not None else QColor(255, 255, 255, 255),
            QRectF(clip) if clip else None,
        )
        self.images.append(payload)
        self._append(payload)

    def extend(self, other: "ClickGuiDrawList") -> None:
        """Append another list while preserving its internal draw order."""
        self.rects.extend(other.rects)
        self.texts.extend(other.texts)
        self.images.extend(other.images)
        for command in other.commands:
            self.commands.append(
                GpuUiCommand(len(self.commands), command.payload, command.layer, command.opacity)
            )


@dataclass
class _GlyphAtlas:
    texture: QOpenGLTexture
    glyphs: dict[str, "_Glyph"]
    raster_font: QFont
    ratio: float
    sample_scale: float
    raster_scale: float


@dataclass(frozen=True)
class SmallTextPolicy:
    """Rasterization policy for compact labels on low-resolution displays."""

    oversample_limit_px: float = 18.0
    oversample_scale: float = 2.0
    medium_limit_px: float = 16.0

    def sample_scale_for(self, physical_pixel_size: float) -> float:
        return self.oversample_scale if physical_pixel_size <= self.oversample_limit_px else 1.0

    def prepare_font(
        self,
        font: QFont,
        physical_pixel_size: float,
        sample_scale: float,
        *,
        preserve_weight: bool = False,
    ) -> QFont:
        prepared = QFont(font)
        prepared.setPixelSize(max(1, int(round(physical_pixel_size * sample_scale))))
        if (
            not preserve_weight
            and physical_pixel_size <= self.medium_limit_px
            and prepared.weight() < QFont.Weight.Medium
        ):
            prepared.setWeight(QFont.Weight.Medium)
        prepared.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        prepared.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        prepared.setKerning(True)
        return prepared

    @staticmethod
    def should_snap(rect: QRectF) -> bool:
        return (
            abs(rect.left() - round(rect.left())) < 0.001
            and abs(rect.top() - round(rect.top())) < 0.001
        )


@dataclass(frozen=True)
class _Glyph:
    u0: float
    v0: float
    u1: float
    v1: float
    advance: float
    offset_x: float
    offset_y: float
    width: float
    height: float


@dataclass(frozen=True)
class GlyphAtlasSnapshot:
    generation: int
    keys: tuple[tuple[str, float, int, float, float, bool], ...]


class ClickGuiGpuRenderer:
    """独立 GPU ClickGUI 渲染器；不与 QPainter 在同一层交替绘制。"""

    def __init__(self) -> None:
        self.available = False
        self.last_error = ""
        self.rect_program: QOpenGLShaderProgram | None = None
        self.text_program: QOpenGLShaderProgram | None = None
        self.image_program: QOpenGLShaderProgram | None = None
        self.buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.instance_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.vertex_array = QOpenGLVertexArrayObject()
        self.rect_uniforms: dict[str, int] = {}
        self.text_uniforms: dict[str, int] = {}
        self.image_uniforms: dict[str, int] = {}
        self.atlases: dict[tuple[str, float, int, float, float, bool], _GlyphAtlas] = {}
        self.image_textures: dict[str, QOpenGLTexture] = {}
        self._atlas_chars: dict[tuple[str, float, int, float, float, bool], set[str]] = {}
        self.draw_calls = 0
        self._pixel_ratio = 1.0
        self.last_submit_ms = 0.0
        self.atlas_hits = 0
        self.atlas_misses = 0
        self.atlas_generation = 0
        self.atlas_snapshot = GlyphAtlasSnapshot(0, ())
        self._atlas_locked = False
        self.small_text_policy = SmallTextPolicy()

    def initialize(self) -> bool:
        if self.available:
            return True
        try:
            self.rect_program = self._build_rect_program()
            self.text_program = self._build_text_program()
            self.image_program = self._build_image_program()
            if not self.vertex_array.create():
                raise RuntimeError("GPU vertex array creation failed")
            self.buffer.create()
            if not self.buffer.isCreated():
                raise RuntimeError("GPU vertex buffer creation failed")
            self.buffer.bind()
            self.buffer.allocate(struct.pack("8f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0), 32)
            self.buffer.release()
            self.instance_buffer.create()
            if not self.instance_buffer.isCreated():
                raise RuntimeError("GPU instance buffer creation failed")
            self.rect_uniforms = self._uniform_locations(self.rect_program, ("viewport",))
            self.text_uniforms = self._uniform_locations(self.text_program, ("viewport", "glyph"))
            self.image_uniforms = self._uniform_locations(
                self.image_program,
                ("viewport", "rect", "sourceTexture", "tint"),
            )
            self.available = True
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self.available = False
            return False

    def prewarm(
        self,
        fonts: tuple[QFont, ...],
        labels,
        device_pixel_ratio: float = 1.0,
        *,
        raster_scale: float = 1.0,
        preserve_weight: bool = False,
    ) -> None:
        """Populate stable glyph atlases before an interactive GUI open."""
        if not self.available:
            return
        self._pixel_ratio = max(1.0, float(device_pixel_ratio))
        characters = set("".join(str(label) for label in labels))
        if not characters:
            return
        for font in fonts:
            self._ensure_atlas(
                font,
                "".join(characters),
                raster_scale=raster_scale,
                preserve_weight=preserve_weight,
            )

    def prewarm_images(self, sources) -> None:
        """Upload stable UI sprites while an OpenGL context is current."""
        if not self.available:
            return
        for source in sources:
            self._ensure_image_texture(str(Path(source).expanduser().resolve()))

    @staticmethod
    def _uniform_locations(program: QOpenGLShaderProgram, names: tuple[str, ...]) -> dict[str, int]:
        locations = {name: program.uniformLocation(name) for name in names}
        if any(value < 0 for value in locations.values()):
            raise RuntimeError("GPU shader uniform missing")
        return locations

    @staticmethod
    def _vertex_source() -> str:
        return """
            #version 330
            layout(location=0) in vec2 position;
            uniform vec2 viewport;
            uniform vec4 rect;
            out vec2 localUv;
            void main() {
                localUv = position;
                vec2 pixel = rect.xy + position * rect.zw;
                vec2 ndc = vec2(pixel.x / viewport.x * 2.0 - 1.0, 1.0 - pixel.y / viewport.y * 2.0);
                gl_Position = vec4(ndc, 0.0, 1.0);
            }
        """

    @staticmethod
    def _rect_vertex_source() -> str:
        return """
            #version 330
            layout(location=0) in vec2 position;
            layout(location=1) in vec4 instanceRect;
            layout(location=2) in vec4 instanceFill;
            layout(location=3) in vec4 instanceOutline;
            layout(location=4) in float instanceRadius;
            layout(location=5) in float instanceOutlineWidth;
            layout(location=6) in vec4 instanceGradient;
            layout(location=7) in float instanceHasGradient;
            uniform vec2 viewport;
            out vec2 localUv;
            flat out vec2 rectSize;
            flat out vec4 fillColor;
            flat out vec4 outlineColor;
            flat out float radius;
            flat out float outlineWidth;
            flat out vec4 gradientColor;
            flat out float hasGradient;
            void main() {
                localUv = position;
                rectSize = instanceRect.zw;
                fillColor = instanceFill;
                outlineColor = instanceOutline;
                radius = instanceRadius;
                outlineWidth = instanceOutlineWidth;
                gradientColor = instanceGradient;
                hasGradient = instanceHasGradient;
                vec2 pixel = instanceRect.xy + position * instanceRect.zw;
                vec2 ndc = vec2(pixel.x / viewport.x * 2.0 - 1.0, 1.0 - pixel.y / viewport.y * 2.0);
                gl_Position = vec4(ndc, 0.0, 1.0);
            }
        """

    def _build_rect_program(self) -> QOpenGLShaderProgram:
        fragment = """
            #version 330
            in vec2 localUv;
            flat in vec2 rectSize;
            flat in vec4 fillColor;
            flat in vec4 outlineColor;
            flat in float radius;
            flat in float outlineWidth;
            flat in vec4 gradientColor;
            flat in float hasGradient;
            out vec4 fragColor;
            float roundedBoxSdf(vec2 p, vec2 b, float r) {
                vec2 q = abs(p) - b + vec2(r);
                return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
            }
            void main() {
                vec2 size = rectSize;
                float r = min(radius, min(size.x, size.y) * 0.5);
                float distance = roundedBoxSdf((localUv - 0.5) * size, size * 0.5, r);
                float edge = max(fwidth(distance), 0.8);
                float inside = 1.0 - smoothstep(-edge, edge, distance);
                vec4 base = hasGradient > 0.5 ? mix(fillColor, gradientColor, localUv.x) : fillColor;
                if (outlineWidth > 0.0) {
                    float inner = 1.0 - smoothstep(-outlineWidth - edge, -outlineWidth + edge, distance);
                    base = mix(outlineColor, base, inner);
                }
                float alpha = base.a * inside;
                fragColor = vec4(base.rgb * alpha, alpha);
            }
        """
        return self._build_program(self._rect_vertex_source(), fragment)

    def _build_text_program(self) -> QOpenGLShaderProgram:
        vertex = """
            #version 330
            layout(location=0) in vec2 position;
            layout(location=1) in vec4 instanceRect;
            layout(location=2) in vec4 instanceUv;
            layout(location=3) in vec4 instanceColor;
            layout(location=4) in float instanceRotation;
            layout(location=5) in vec2 instanceRotationOrigin;
            uniform vec2 viewport;
            out vec2 uv;
            flat out vec4 glyphColor;
            void main() {
                vec2 unrotated = instanceRect.xy + position * instanceRect.zw;
                vec2 local = unrotated - instanceRotationOrigin;
                float c = cos(instanceRotation);
                float s = sin(instanceRotation);
                vec2 rotated = vec2(
                    c * local.x - s * local.y,
                    s * local.x + c * local.y
                );
                vec2 pixel = instanceRotationOrigin + rotated;
                vec2 ndc = vec2(pixel.x / viewport.x * 2.0 - 1.0, 1.0 - pixel.y / viewport.y * 2.0);
                gl_Position = vec4(ndc, 0.0, 1.0);
                uv = mix(instanceUv.xy, instanceUv.zw, position);
                glyphColor = instanceColor;
            }
        """
        fragment = """
            #version 330
            in vec2 uv;
            flat in vec4 glyphColor;
            out vec4 fragColor;
            uniform sampler2D glyph;
            void main() {
                // QOpenGLTexture already applies the QImage-to-texture
                // orientation conversion. A second flip samples another row.
                float alpha = texture(glyph, uv).a;
                alpha *= glyphColor.a;
                fragColor = vec4(glyphColor.rgb * alpha, alpha);
            }
        """
        return self._build_program(vertex, fragment)

    def _build_image_program(self) -> QOpenGLShaderProgram:
        fragment = """
            #version 330
            in vec2 localUv;
            out vec4 fragColor;
            uniform sampler2D sourceTexture;
            uniform vec4 tint;
            void main() {
                vec4 sampleColor = texture(sourceTexture, localUv);
                float alpha = sampleColor.a * tint.a;
                fragColor = vec4(sampleColor.rgb * tint.rgb * alpha, alpha);
            }
        """
        return self._build_program(self._vertex_source(), fragment)

    @staticmethod
    def _build_program(vertex: str, fragment: str) -> QOpenGLShaderProgram:
        program = QOpenGLShaderProgram()
        if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vertex):
            raise RuntimeError(program.log())
        if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fragment):
            raise RuntimeError(program.log())
        if not program.link():
            raise RuntimeError(program.log())
        return program

    @staticmethod
    def _rgba(color: QColor) -> tuple[float, float, float, float]:
        return (color.redF(), color.greenF(), color.blueF(), color.alphaF())

    def render(
        self,
        functions,
        commands: ClickGuiDrawList,
        width: int,
        height: int,
        device_pixel_ratio: float = 1.0,
        *,
        atlas_prepared: bool = False,
    ) -> bool:
        """Render a logical-pixel draw list into the current DPR-sized framebuffer."""
        if (
            not self.available
            or self.rect_program is None
            or self.text_program is None
            or self.image_program is None
        ):
            return False
        self._pixel_ratio = max(1.0, float(device_pixel_ratio))
        try:
            if atlas_prepared:
                if not self._resources_ready(commands):
                    self.last_error = "ClickGUI GPU resource snapshot is incomplete for this frame"
                    return False
            else:
                self.prepare_frame(commands, self._pixel_ratio)
        except Exception as exc:
            self.last_error = str(exc)
            return False
        try:
            started = time.perf_counter()
            self.draw_calls = 0
            self._atlas_locked = True
            framebuffer_width = max(1, round(width * self._pixel_ratio))
            framebuffer_height = max(1, round(height * self._pixel_ratio))
            self.vertex_array.bind()
            functions.glViewport(0, 0, framebuffer_width, framebuffer_height)
            functions.glDisable(_GL_DEPTH_TEST)
            functions.glDisable(_GL_CULL_FACE)
            functions.glDisable(_GL_STENCIL_TEST)
            functions.glDisable(_GL_SCISSOR_TEST)
            functions.glDepthMask(False)
            functions.glColorMask(True, True, True, True)
            functions.glEnable(_GL_BLEND)
            functions.glBlendEquation(_GL_FUNC_ADD)
            functions.glBlendFunc(_GL_ONE, _GL_ONE_MINUS_SRC_ALPHA)
            self._draw_ordered_commands(functions, commands, framebuffer_width, framebuffer_height)
            functions.glDisable(_GL_SCISSOR_TEST)
            functions.glDisable(_GL_BLEND)
            functions.glDepthMask(True)
            functions.glActiveTexture(_GL_TEXTURE0)
            functions.glBindTexture(_GL_TEXTURE_2D, 0)
            self.vertex_array.release()
            self.last_submit_ms = (time.perf_counter() - started) * 1000.0
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self.available = False
            try:
                functions.glDisable(_GL_SCISSOR_TEST)
                functions.glDisable(_GL_BLEND)
                functions.glDepthMask(True)
                functions.glActiveTexture(_GL_TEXTURE0)
                functions.glBindTexture(_GL_TEXTURE_2D, 0)
                self.vertex_array.release()
            except Exception:
                pass
            return False
        finally:
            self._atlas_locked = False

    def prepare_frame(
        self,
        commands: ClickGuiDrawList,
        device_pixel_ratio: float = 1.0,
    ) -> GlyphAtlasSnapshot:
        """Publish every glyph page before a destination FBO is bound."""
        if not self.available:
            return self.atlas_snapshot
        if self._atlas_locked:
            raise RuntimeError("glyph atlas preparation attempted during a render pass")
        self._pixel_ratio = max(1.0, float(device_pixel_ratio))
        self._prepare_atlases(commands)
        self._prepare_images(commands)
        return self.atlas_snapshot

    def _resources_ready(self, draw_list: ClickGuiDrawList) -> bool:
        source = (
            [command.payload for command in draw_list.commands if isinstance(command.payload, GpuText)]
            if draw_list.commands
            else list(draw_list.texts)
        )
        for command in source:
            atlas = self.atlases.get(
                self._font_key(
                    command.font,
                    command.raster_scale,
                    command.preserve_weight,
                )
            )
            if atlas is None or any(character not in atlas.glyphs for character in command.text):
                return False
        image_source = (
            [command.payload for command in draw_list.commands if isinstance(command.payload, GpuImage)]
            if draw_list.commands
            else list(draw_list.images)
        )
        if any(command.source not in self.image_textures for command in image_source):
            return False
        return True

    def _prepare_atlases(self, draw_list: ClickGuiDrawList) -> None:
        """Publish every glyph needed by this frame before drawing begins."""
        grouped: dict[
            tuple[str, float, int, float, float, bool],
            tuple[QFont, set[str], float, bool],
        ] = {}
        source = (
            [command.payload for command in draw_list.commands if isinstance(command.payload, GpuText)]
            if draw_list.commands
            else list(draw_list.texts)
        )
        for command in source:
            key = self._font_key(
                command.font,
                command.raster_scale,
                command.preserve_weight,
            )
            if key not in grouped:
                grouped[key] = (
                    QFont(command.font),
                    set(),
                    command.raster_scale,
                    command.preserve_weight,
                )
            grouped[key][1].update(command.text)
        for font, characters, raster_scale, preserve_weight in grouped.values():
            if characters:
                self._ensure_atlas(
                    font,
                    "".join(sorted(characters)),
                    raster_scale=raster_scale,
                    preserve_weight=preserve_weight,
                )
        self.atlas_snapshot = GlyphAtlasSnapshot(
            self.atlas_generation,
            tuple(sorted(self.atlases)),
        )

    def _prepare_images(self, draw_list: ClickGuiDrawList) -> None:
        source = (
            [command.payload for command in draw_list.commands if isinstance(command.payload, GpuImage)]
            if draw_list.commands
            else list(draw_list.images)
        )
        for command in source:
            self._ensure_image_texture(command.source)

    @staticmethod
    def _apply_opacity(
        payload: GpuRect | GpuText | GpuImage,
        opacity: float,
    ) -> GpuRect | GpuText | GpuImage:
        opacity = max(0.0, min(1.0, float(opacity)))
        if opacity >= 0.999:
            return payload

        def faded(source: QColor) -> QColor:
            result = QColor(source)
            result.setAlphaF(source.alphaF() * opacity)
            return result

        if isinstance(payload, GpuRect):
            return GpuRect(
                QRectF(payload.rect),
                payload.radius,
                faded(payload.fill),
                faded(payload.outline),
                payload.outline_width,
                faded(payload.gradient) if payload.gradient is not None else None,
                QRectF(payload.clip) if payload.clip is not None else None,
            )
        if isinstance(payload, GpuImage):
            return GpuImage(
                QRectF(payload.rect),
                payload.source,
                faded(payload.tint),
                QRectF(payload.clip) if payload.clip is not None else None,
            )
        return GpuText(
            QRectF(payload.rect),
            payload.text,
            QFont(payload.font),
            faded(payload.color),
            payload.alignment,
            QRectF(payload.clip) if payload.clip is not None else None,
            payload.shadow,
            payload.rotation_degrees,
            payload.render_scale,
            QPointF(payload.rotation_origin) if payload.rotation_origin is not None else None,
            payload.raster_scale,
            payload.preserve_weight,
        )

    def _draw_ordered_commands(
        self,
        functions,
        draw_list: ClickGuiDrawList,
        width: int,
        height: int,
    ) -> None:
        """Batch adjacent commands without changing their visual order."""
        if not draw_list.commands:
            self._draw_rect_batches(functions, draw_list.rects, width, height)
            self._draw_text_batches(functions, draw_list.texts, width, height)
            self._draw_image_batches(functions, draw_list.images, width, height)
            return
        index = 0
        commands = draw_list.commands
        while index < len(commands):
            first = commands[index]
            payload_type = type(first.payload)
            layer = first.layer
            end = index + 1
            while (
                end < len(commands)
                and type(commands[end].payload) is payload_type
                and commands[end].layer == layer
            ):
                end += 1
            payloads = [
                self._apply_opacity(command.payload, command.opacity)
                for command in commands[index:end]
            ]
            if payload_type is GpuRect:
                self._draw_rect_batches(functions, payloads, width, height)
            elif payload_type is GpuText:
                self._draw_text_batches(functions, payloads, width, height)
            else:
                self._draw_image_batches(functions, payloads, width, height)
            index = end

    def _bind_quad(self, program: QOpenGLShaderProgram) -> None:
        self.buffer.bind()
        program.enableAttributeArray(0)
        program.setAttributeBuffer(0, _GL_FLOAT, 0, 2, 8)

    def _unbind_quad(self, program: QOpenGLShaderProgram) -> None:
        program.disableAttributeArray(0)
        self.buffer.release()

    def _draw_rect_batches(self, functions, commands: list[GpuRect], width: int, height: int) -> None:
        """按连续裁剪区批量提交圆角面板，保留绘制顺序并减少提交次数。"""
        index = 0
        while index < len(commands):
            clip = commands[index].clip
            end = index + 1
            while end < len(commands) and commands[end].clip == clip:
                end += 1
            self._apply_clip(functions, clip, width, height)
            self._draw_rect_batch(functions, commands[index:end], width, height)
            index = end

    def _draw_rect_batch(self, functions, commands: list[GpuRect], width: int, height: int) -> None:
        assert self.rect_program is not None
        program = self.rect_program
        program.bind()
        uniforms = self.rect_uniforms
        ratio = self._pixel_ratio
        program.setUniformValue(
            uniforms["viewport"],
            # ``render`` passes framebuffer dimensions to every draw helper.
            # Instance coordinates are converted from logical pixels exactly
            # once below, so multiplying the viewport by DPR again would make
            # the whole ClickGUI half-sized on a 200% Windows display.
            float(width),
            float(height),
        )
        packed = bytearray()
        for command in commands:
            packed.extend(struct.pack(
                "19f",
                command.rect.left() * ratio,
                command.rect.top() * ratio,
                command.rect.width() * ratio,
                command.rect.height() * ratio,
                *self._rgba(command.fill),
                *self._rgba(command.outline),
                command.radius * ratio,
                command.outline_width * ratio,
                *self._rgba(command.gradient or command.fill),
                1.0 if command.gradient else 0.0,
            ))
        self._bind_quad(program)
        self.instance_buffer.bind()
        self.instance_buffer.allocate(bytes(packed), len(packed))
        stride = 19 * 4
        offsets = ((1, 4, 0), (2, 4, 16), (3, 4, 32), (4, 1, 48), (5, 1, 52), (6, 4, 56), (7, 1, 72))
        for location, size, offset in offsets:
            program.enableAttributeArray(location)
            program.setAttributeBuffer(location, _GL_FLOAT, offset, size, stride)
            functions.glVertexAttribDivisor(location, 1)
        functions.glDrawArraysInstanced(_GL_TRIANGLE_STRIP, 0, 4, len(commands))
        for location, _size, _offset in offsets:
            functions.glVertexAttribDivisor(location, 0)
            program.disableAttributeArray(location)
        self.instance_buffer.release()
        self._unbind_quad(program)
        program.release()
        self.draw_calls += 1

    def _ensure_image_texture(self, source: str) -> QOpenGLTexture:
        cached = self.image_textures.get(source)
        if cached is not None:
            return cached
        if self._atlas_locked:
            raise RuntimeError("image texture mutation attempted during a render pass")
        image = QImage(source)
        if image.isNull():
            raise RuntimeError(f"ClickGUI image could not be loaded: {source}")
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        texture = QOpenGLTexture(
            image,
            QOpenGLTexture.MipMapGeneration.DontGenerateMipMaps,
        )
        texture.setMinificationFilter(QOpenGLTexture.Filter.Linear)
        texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
        texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        self.image_textures[source] = texture
        return texture

    def _draw_image_batches(
        self,
        functions,
        commands: list[GpuImage],
        width: int,
        height: int,
    ) -> None:
        if not commands:
            return
        assert self.image_program is not None
        program = self.image_program
        program.bind()
        uniforms = self.image_uniforms
        ratio = self._pixel_ratio
        program.setUniformValue(
            uniforms["viewport"],
            float(width),
            float(height),
        )
        program.setUniformValue(uniforms["sourceTexture"], 0)
        self._bind_quad(program)
        for command in commands:
            self._apply_clip(functions, command.clip, width, height)
            texture = self.image_textures.get(command.source)
            if texture is None:
                raise RuntimeError(f"ClickGUI image was not prepared: {command.source}")
            program.setUniformValue(
                uniforms["rect"],
                float(command.rect.left() * ratio),
                float(command.rect.top() * ratio),
                float(command.rect.width() * ratio),
                float(command.rect.height() * ratio),
            )
            red, green, blue, alpha = self._rgba(command.tint)
            program.setUniformValue(uniforms["tint"], red, green, blue, alpha)
            functions.glActiveTexture(_GL_TEXTURE0)
            texture.bind(0)
            functions.glDrawArrays(_GL_TRIANGLE_STRIP, 0, 4)
            texture.release()
            self.draw_calls += 1
        self._unbind_quad(program)
        program.release()

    def _font_key(
        self,
        font: QFont,
        raster_scale: float = 1.0,
        preserve_weight: bool = False,
    ) -> tuple[str, float, int, float, float, bool]:
        return (
            font.family(),
            round(font.pointSizeF(), 2),
            int(font.weight()),
            self._pixel_ratio,
            round(max(0.25, float(raster_scale)), 2),
            bool(preserve_weight),
        )

    @staticmethod
    def _clip_key(clip: QRectF | None) -> tuple[float, float, float, float] | None:
        if clip is None:
            return None
        return (round(clip.x(), 2), round(clip.y(), 2), round(clip.width(), 2), round(clip.height(), 2))

    def _ensure_atlas(
        self,
        font: QFont,
        text: str,
        *,
        raster_scale: float = 1.0,
        preserve_weight: bool = False,
    ) -> _GlyphAtlas:
        """Create a complete atlas page and swap it only at a frame boundary."""
        raster_scale = max(0.25, float(raster_scale))
        key = self._font_key(font, raster_scale, preserve_weight)
        chars = self._atlas_chars.setdefault(key, set())
        before = set(chars)
        chars.update(text)
        if len(chars) > 1024:
            chars.intersection_update(set(sorted(chars)[:1024]))
        current = self.atlases.get(key)
        if current is not None and chars == before:
            self.atlas_hits += 1
            return current
        if self._atlas_locked:
            raise RuntimeError("glyph atlas mutation attempted during a render pass")
        self.atlas_misses += 1

        raster_font = QFont(font)
        # Snap sizes to whole device pixels — fractional pt × dpr is a top cause of mushy 1K GUI text.
        if font.pointSizeF() > 0:
            logical_px = font.pointSizeF() * (96.0 / 72.0)
        elif font.pixelSize() > 0:
            logical_px = float(font.pixelSize())
        else:
            logical_px = 12.0
        physical_px = max(1.0, logical_px * self._pixel_ratio * raster_scale)
        sample_scale = self.small_text_policy.sample_scale_for(physical_px)
        raster_font = self.small_text_policy.prepare_font(
            font,
            physical_px,
            sample_scale,
            preserve_weight=preserve_weight,
        )
        raster_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        raster_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        raster_font.setKerning(True)

        metrics = QFontMetricsF(raster_font)
        ordered_chars = sorted(chars)
        bounds_by_char = {char: metrics.boundingRect(char) for char in ordered_chars}
        padding = max(
            4,
            int(math.ceil(self._pixel_ratio * sample_scale * raster_scale * 2.0)),
        )
        max_glyph_width = max(
            1,
            int(math.ceil(max((bounds.width() for bounds in bounds_by_char.values()), default=1.0))),
        )
        max_glyph_height = max(
            1,
            int(math.ceil(max((bounds.height() for bounds in bounds_by_char.values()), default=1.0))),
        )
        cell_width = max_glyph_width + padding * 2
        cell_height = max_glyph_height + padding * 2
        max_texture_size = 4096
        max_columns = max(1, max_texture_size // cell_width)
        desired_columns = max(
            1,
            int(math.ceil(math.sqrt(max(1, len(ordered_chars)) * cell_height / cell_width))),
        )
        columns = min(max_columns, desired_columns)
        rows = int(math.ceil(max(1, len(ordered_chars)) / columns))
        while rows * cell_height > max_texture_size and columns < max_columns:
            columns += 1
            rows = int(math.ceil(len(ordered_chars) / columns))
        if columns * cell_width > max_texture_size or rows * cell_height > max_texture_size:
            raise RuntimeError(
                f"glyph atlas exceeds {max_texture_size}px for {font.family()} {font.pointSizeF():g}pt"
            )
        atlas_width = max(1, columns * cell_width)
        atlas_height = max(1, rows * cell_height)
        image = QImage(atlas_width, atlas_height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setFont(raster_font)
        painter.setPen(QColor(255, 255, 255, 255))
        glyphs: dict[str, _Glyph] = {}
        for index, char in enumerate(ordered_chars):
            col = index % columns
            row = index // columns
            bounds = bounds_by_char[char]
            atlas_x = float(col * cell_width + padding)
            atlas_y = float(row * cell_height + padding)
            advance = max(0.0, metrics.horizontalAdvance(char))
            glyph_width = max(0.0, bounds.width())
            glyph_height = max(0.0, bounds.height())
            if glyph_width > 0.0 and glyph_height > 0.0:
                # Integer baseline position for stable stems at 1K.
                pen_x = round(atlas_x - bounds.left())
                pen_y = round(atlas_y - bounds.top())
                if sample_scale > 1.0:
                    painter.setPen(QColor(255, 255, 255, 72))
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        painter.drawText(QPointF(pen_x + dx, pen_y + dy), char)
                    painter.setPen(QColor(255, 255, 255, 255))
                painter.drawText(QPointF(pen_x, pen_y), char)
            # Tight UV (no 0.5 inset) so Nearest sampling does not thin strokes.
            inset = 0.5 if glyph_width > 1.0 and glyph_height > 1.0 else 0.0
            normalization_scale = sample_scale * raster_scale
            glyphs[char] = _Glyph(
                (atlas_x + inset) / atlas_width,
                (atlas_y + inset) / atlas_height,
                (atlas_x + glyph_width - inset) / atlas_width,
                (atlas_y + glyph_height - inset) / atlas_height,
                advance / normalization_scale,
                bounds.left() / normalization_scale,
                bounds.top() / normalization_scale,
                glyph_width / normalization_scale,
                glyph_height / normalization_scale,
            )
        painter.end()

        new_texture = QOpenGLTexture(
            image,
            QOpenGLTexture.MipMapGeneration.DontGenerateMipMaps,
        )
        # Nearest keeps ClickGUI labels crisp at 1K; Linear was milk-blurring small Poppins.
        new_texture.setMinificationFilter(QOpenGLTexture.Filter.Linear)
        new_texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
        new_texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        published = _GlyphAtlas(
            new_texture,
            glyphs,
            raster_font,
            self._pixel_ratio,
            sample_scale,
            raster_scale,
        )
        old = self.atlases.get(key)
        self.atlases[key] = published
        self.atlas_generation += 1
        if old is not None:
            old.texture.destroy()
        return published

    def _draw_text_batches(self, functions, commands: list[GpuText], width: int, height: int) -> None:
        if not commands:
            return
        required = {
            self._font_key(command.font, command.raster_scale, command.preserve_weight)
            for command in commands
        }
        missing = required - set(self.atlases)
        if missing:
            raise RuntimeError(f"glyph atlas was not prepared for {len(missing)} font page(s)")

        # Preserve command order. Only adjacent text sharing a font page and
        # clip may be submitted together; global font grouping moved labels
        # across glass/control layers and made them appear doubled or pale.
        index = 0
        while index < len(commands):
            font_key = self._font_key(
                commands[index].font,
                commands[index].raster_scale,
                commands[index].preserve_weight,
            )
            clip_key = self._clip_key(commands[index].clip)
            end = index + 1
            while (
                end < len(commands)
                and self._font_key(
                    commands[end].font,
                    commands[end].raster_scale,
                    commands[end].preserve_weight,
                ) == font_key
                and self._clip_key(commands[end].clip) == clip_key
            ):
                end += 1
            items = commands[index:end]
            self._apply_clip(functions, items[0].clip, width, height)
            # Lighter drop shadow so main strokes stay readable on 1K glass panels.
            shadows: list[GpuText] = []
            for item in items:
                if not item.shadow or item.color.alpha() < 40:
                    continue
                shadow_alpha = max(28, min(96, round(item.color.alpha() * 0.42)))
                shadow_rect = QRectF(item.rect)
                shadow_rect.translate(1.0, 1.0)
                shadows.append(
                    GpuText(
                        shadow_rect,
                        item.text,
                        QFont(item.font),
                        QColor(0, 0, 0, shadow_alpha),
                        item.alignment,
                        QRectF(item.clip) if item.clip is not None else None,
                        False,
                        item.rotation_degrees,
                        item.render_scale,
                        (
                            QPointF(item.rotation_origin) + QPointF(1.0, 1.0)
                            if item.rotation_origin is not None
                            else None
                        ),
                        item.raster_scale,
                        item.preserve_weight,
                    )
                )
            atlas = self.atlases[font_key]
            if shadows:
                self._draw_text_batch(functions, shadows, atlas, width, height)
            self._draw_text_batch(functions, items, atlas, width, height)
            index = end

    def _draw_text_batch(self, functions, commands: list[GpuText], atlas: _GlyphAtlas, width: int, height: int) -> None:
        assert self.text_program is not None
        metrics = QFontMetricsF(atlas.raster_font)
        ratio = self._pixel_ratio
        normalization_scale = max(0.25, atlas.sample_scale * atlas.raster_scale)
        packed = bytearray()
        for command in commands:
            draw_scale = max(0.01, float(command.render_scale))
            rect = QRectF(
                command.rect.left() * ratio,
                command.rect.top() * ratio,
                command.rect.width() * ratio,
                command.rect.height() * ratio,
            )
            text_width = sum(
                atlas.glyphs[char].advance
                for char in command.text
                if char in atlas.glyphs
            ) * draw_scale
            line_height = min(rect.height(), metrics.height() / normalization_scale * draw_scale)
            if command.alignment & Qt.AlignmentFlag.AlignHCenter:
                x = rect.center().x() - min(rect.width(), text_width) * 0.5
            elif command.alignment & Qt.AlignmentFlag.AlignRight:
                x = rect.right() - min(rect.width(), text_width)
            else:
                x = rect.left()
            if command.alignment & Qt.AlignmentFlag.AlignVCenter:
                y = rect.center().y() - line_height * 0.5
            elif command.alignment & Qt.AlignmentFlag.AlignBottom:
                y = rect.bottom() - line_height
            else:
                y = rect.top()
            snap = self.small_text_policy.should_snap(command.rect)
            if snap:
                x = float(round(x))
                y = float(round(y))
            baseline = y + metrics.ascent() / normalization_scale * draw_scale
            if snap:
                baseline = float(round(baseline))
            cursor = x
            for char in command.text:
                glyph = atlas.glyphs.get(char)
                if glyph is None:
                    continue
                # Integer quad origin → Nearest atlas samples stay sharp at 1K.
                glyph_x = cursor + glyph.offset_x * draw_scale
                glyph_y = baseline + glyph.offset_y * draw_scale
                if snap:
                    glyph_x = float(round(glyph_x))
                    glyph_y = float(round(glyph_y))
                glyph_w = max(0.5, glyph.width * draw_scale) if glyph.width > 0.0 else 0.0
                glyph_h = max(0.5, glyph.height * draw_scale) if glyph.height > 0.0 else 0.0
                if (
                    glyph_w > 0.0
                    and glyph_h > 0.0
                    and glyph_x + glyph_w >= rect.left()
                    and glyph_x <= rect.right()
                ):
                    if command.rotation_origin is not None:
                        pivot_x = command.rotation_origin.x() * ratio
                        pivot_y = command.rotation_origin.y() * ratio
                    else:
                        pivot_x = glyph_x + glyph_w * 0.5
                        pivot_y = glyph_y + glyph_h * 0.5
                    packed.extend(struct.pack(
                        "15f",
                        glyph_x, glyph_y, glyph_w, glyph_h,
                        glyph.u0, glyph.v0, glyph.u1, glyph.v1,
                        *self._rgba(command.color),
                        math.radians(command.rotation_degrees),
                        pivot_x,
                        pivot_y,
                    ))
                cursor += glyph.advance * draw_scale
        if not packed:
            return
        program = self.text_program
        program.bind()
        program.setUniformValue(
            self.text_uniforms["viewport"],
            float(width),
            float(height),
        )
        atlas.texture.bind(0)
        program.setUniformValue(self.text_uniforms["glyph"], 0)
        self._bind_quad(program)
        self.instance_buffer.bind()
        self.instance_buffer.allocate(bytes(packed), len(packed))
        offsets = ((1, 4, 0), (2, 4, 16), (3, 4, 32), (4, 1, 48), (5, 2, 52))
        stride = 15 * 4
        for location, size, offset in offsets:
            program.enableAttributeArray(location)
            program.setAttributeBuffer(location, _GL_FLOAT, offset, size, stride)
            functions.glVertexAttribDivisor(location, 1)
        functions.glDrawArraysInstanced(_GL_TRIANGLE_STRIP, 0, 4, len(packed) // stride)
        for location, _size, _offset in offsets:
            functions.glVertexAttribDivisor(location, 0)
            program.disableAttributeArray(location)
        self.instance_buffer.release()
        self._unbind_quad(program)
        atlas.texture.release()
        program.release()
        self.draw_calls += 1

    def _apply_clip(self, functions, clip: QRectF | None, width: int, height: int) -> None:
        if clip is None:
            functions.glDisable(_GL_SCISSOR_TEST)
            return
        ratio = self._pixel_ratio
        # ``width``/``height`` are already framebuffer pixels here.  Only the
        # logical clip rectangle needs DPR conversion.
        framebuffer_width = max(1, int(width))
        framebuffer_height = max(1, int(height))
        x = max(0, int(math.floor(clip.left() * ratio)))
        y = max(0, int(math.floor(framebuffer_height - clip.bottom() * ratio)))
        w = max(0, min(framebuffer_width - x, int(math.ceil(clip.width() * ratio))))
        h = max(0, min(framebuffer_height - y, int(math.ceil(clip.height() * ratio))))
        functions.glEnable(_GL_SCISSOR_TEST)
        functions.glScissor(x, y, w, h)

    def release(self) -> None:
        for atlas in self.atlases.values():
            atlas.texture.destroy()
        self.atlases.clear()
        self._atlas_chars.clear()
        for texture in self.image_textures.values():
            texture.destroy()
        self.image_textures.clear()
        if self.buffer.isCreated():
            self.buffer.destroy()
        if self.instance_buffer.isCreated():
            self.instance_buffer.destroy()
        if self.vertex_array.isCreated():
            self.vertex_array.destroy()
        for program in (self.rect_program, self.text_program, self.image_program):
            if program is not None:
                program.removeAllShaders()
        self.rect_program = None
        self.text_program = None
        self.image_program = None
        self.available = False
