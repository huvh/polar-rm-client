"""Endfield Wiki 展示适配：六分类、目录、详情与可编辑终端设置。

只生成现有 GPU 指令与热点，不接管配置写入、模块门禁或设备生命周期。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF

from rm_client.model import CATEGORIES
from rm_client.ui.clickgui_gpu import ClickGuiDrawList
from rm_client.ui.endfield.wiki.state import EndfieldWikiState
from rm_client.ui.endfield.wiki.query import wiki_modules
from rm_client.ui.endfield.wiki.motion import WikiMotion
from rm_client.ui.endfield.wiki.decor import draw_background, draw_home_selection
from rm_client.ui.endfield.wiki.layers import draw_page_layers, draw_top_layer, draw_history, draw_scene_ground
from rm_client.ui.endfield.wiki.list_fade import fade_edges
from rm_client.ui.endfield.wiki.scroll import edge_offset
from rm_client.ui.endfield.wiki.background import WikiBackground
from rm_client.ui.jello_clickgui import JelloClickGuiRenderer
from rm_client.ui.jello_locale import (
    action_label, category_label, chinese_enabled, description_label, module_label,
    option_label, setting_label,
)


INK = "#424343"
MUTED = "#858684"
PAPER = "#e6e5e3"
YELLOW = "#fff45c"


class EndfieldWikiRenderer(JelloClickGuiRenderer):
    """保留旧 renderer 的字体预热和兼容绘制接口，替换实际页面。"""

    def __init__(self, asset_root: Path, legacy_assets: Path) -> None:
        self.wiki_root = Path(asset_root)
        self.pack = {}
        manifest = self.wiki_root / "layout.json"
        if manifest.is_file():
            self.pack = json.loads(manifest.read_text(encoding="utf-8"))
        self.wiki_images = {key: self.wiki_root / value
                            for key, value in self.pack.get("images", {}).items()}
        self.motion = WikiMotion(self.pack.get("clips", {}))
        font_path = self.wiki_root / self.pack.get("font", "missing.ttf")
        families = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(font_path)))
        self.wiki_family = families[0] if families else "Microsoft YaHei UI"
        super().__init__(legacy_assets)
        self._wiki_fonts = {}
        self.clock = time.perf_counter
        self.background = WikiBackground()

    @property
    def image_assets(self):
        return (*super().image_assets, *self.wiki_images.values())

    def _wiki_font(self, size: float, bold: bool = False):
        key = (round(size, 2), bold)
        if key not in self._wiki_fonts:
            font = QFont(self.wiki_family)
            # 共享 GPU 字库按 pointSizeF 建键，必须使用项目一致的点字号描述。
            font.setPointSizeF(max(6, size * 72.0 / 96.0))
            font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
            self._wiki_fonts[key] = font
        return self._wiki_fonts[key]

    @staticmethod
    def _color(value, alpha=1.0):
        color = QColor(value)
        color.setAlphaF(max(0.0, min(1.0, alpha)))
        return color

    def build(self, host, state: EndfieldWikiState, width, height, alpha):
        if not isinstance(state, EndfieldWikiState):
            return super().build(host, state, width, height, alpha)
        self.host, self.state = host, state
        self.now = self.clock()
        self.chinese = chinese_enabled(host.registry)
        self.opacity = min(1.0, max(0.0, float(alpha)) * 4.0)
        self.dx = self.dy = 0.0
        clickgui = host.registry.get("ClickGui")
        scale_setting = clickgui.get_setting("Scale") if clickgui else None
        requested_scale = float(scale_setting.value) if scale_setting else 1.0
        self.s = min(width / 1920.0, height / 1080.0) * max(0.5, requested_scale)
        state.list_scale = self.s
        self.ox, self.oy = (width - 1920 * self.s) / 2, (height - 1080 * self.s) / 2
        self.commands = ClickGuiDrawList(
            default_text_shadow=False, default_text_preserve_weight=True,
            default_text_raster_scale=1.0, copy_payloads=False,
        )
        host._hotspot_clip = None
        first_hotspot = len(host.hotspots)
        self.interactive = True
        self._rect_screen(QRectF(0, 0, width, height), PAPER)
        host.add_hotspot(QRectF(0, 0, width, height), "jello_noop")
        self.background.sync(self.motion,state,self.now,closing=not host.gui_visible or getattr(host.gui_timeline,"target",1)<.5)
        self.background_projection = self.background.projection(self.motion,self.pack["layers"]["ground"],self.now)
        timeline = host.gui_timeline
        closing = getattr(timeline, "target", 1.0) < 0.5
        page_elapsed = self.now - state.page_changed_at
        self.page_out = closing or (state.page_from is not None and page_elapsed < 1 / 6)
        self.view_category, self.view_module = (
            state.page_from if self.page_out and not closing and state.page_from is not None
            else (state.category, state.settings_module))
        self.page_at = ((1.0 - float(alpha)) / 6 if closing else
                        max(0.0, page_elapsed if self.page_out else page_elapsed - 1 / 6)
                        if state.page_from is not None else state.category_time if self.view_category else state.page_time)
        self.page_clip = ("wiki_group_" if self.view_category else "wiki_") + ("out" if self.page_out else "in")
        self._background()
        top_clip = "wiki_out" if self.page_out else "wiki_in"
        self._section(top_clip, "Main/TopNode", self._top,
                      at=self.page_at if not self.view_category else 1)
        module = host.registry.get(self.view_module or "")
        if module:
            self._detail(module)
        elif self.view_category:
            self._category()
        else:
            self._home()
        self._footer()
        if self.page_out:
            del host.hotspots[first_hotspot:]
            host.gui_scroll_viewports = []
            host.add_hotspot(QRectF(0, 0, width, height), "jello_noop")
        if (host.search_focus or host.search_query.strip()) and not state.search_open:
            state.open_search()
        if state.search_open:
            self._search_overlay(width, height, first_hotspot)
        else:
            self._tooltip()
        if hasattr(host, "append_minecraft_drop_overlay"):
            host.append_minecraft_drop_overlay(self.commands)
        if not host.gui_visible:
            del host.hotspots[first_hotspot:]
            host.gui_scroll_viewports = []
        return self.commands

    def _search_overlay(self, width, height, first_hotspot):
        state = self.state
        self.search_query = state.search_last_query if state.search_closing_at is not None else self.host.search_query
        if self.search_query != state.search_last_query:
            state.search_content_at = self.now
            state.search_last_query = self.search_query
            state.reset_search_selection()
        self.search_clip = "wiki_search_out" if state.search_closing_at is not None else "wiki_search_in"
        self.search_at = max(0.0, self.now - (state.search_closing_at if state.search_closing_at is not None
                                            else state.search_started_at))
        progress = self.motion.sample(self.search_clip, "NotchNode/Main/Right", "m_Alpha", self.search_at, 1)
        self.commands = ClickGuiDrawList(frosted_background=self.commands, frost_amount=progress,
            frost_radius=self.pack["layers"]["blur_radius"] * self.s, default_text_shadow=False, default_text_preserve_weight=True,
            copy_payloads=False)
        del self.host.hotspots[first_hotspot:]
        self.host.gui_scroll_viewports = []
        self.host.add_hotspot(QRectF(0, 0, width, height), "jello_noop")
        self._rect_screen(QRectF(0, 0, width, height), "#e0e0e0", alpha=.780392 * progress)
        old_opacity = self.opacity
        self.opacity *= progress
        draw_top_layer(self)
        self.opacity = old_opacity
        self._search_top()
        self._search_page()
        if state.search_closing_at is not None:
            del self.host.hotspots[first_hotspot:]
            self.host.gui_scroll_viewports = []
            self.host.add_hotspot(QRectF(0, 0, width, height), "jello_noop")

    def _r(self, x, y, w, h):
        return QRectF(self.ox + (x + self.dx) * self.s,
                      self.oy + (y + self.dy) * self.s, w * self.s, h * self.s)

    def _section(self, clip, path, draw, *, at=None):
        at = self.state.page_time if at is None else at
        old = self.opacity, self.dx, self.dy
        self.opacity *= self.motion.sample(clip, path, "m_Alpha", at, 1)
        self.dx += self.motion.sample(clip, path, "m_AnchoredPosition.x", at)
        self.dy -= self.motion.sample(clip, path, "m_AnchoredPosition.y", at)
        try:
            draw()
        finally:
            self.opacity, self.dx, self.dy = old

    def _rect_screen(self, rect, fill, outline=None, alpha=1.0):
        self.commands.rect(rect, 0, self._color(fill, self.opacity * alpha),
                           self._color(outline, self.opacity) if outline else None,
                           self.s if outline else 0)

    def _box(self, x, y, w, h, fill, outline=None, alpha=1.0, clip=None):
        self.commands.rect(self._r(x, y, w, h), 0, self._color(fill, self.opacity * alpha),
                           self._color(outline, self.opacity) if outline else None,
                           self.s if outline else 0, clip=clip)

    def _text(self, x, y, w, h, text, size=22, color=INK, *, bold=False,
              align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
              alpha=1.0, clip=None):
        if int(align) & int(Qt.TextFlag.TextWordWrap):
            font = self._wiki_font(size, bold)
            lines = self.wrapped_description(font, str(text), w)
            line_h = QFontMetricsF(font).height()
            for index, line in enumerate(lines):
                self.commands.text(self._r(x, y + index * line_h, w, line_h), line, font,
                                   self._color(color, self.opacity * alpha),
                                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, clip,
                                   render_scale=self.s)
            return
        self.commands.text(self._r(x, y, w, h), str(text), self._wiki_font(size, bold),
                           self._color(color, self.opacity * alpha), align, clip,
                           render_scale=self.s)

    def prewarm_jobs(self, registry, dpr):
        """在启动页空闲时分帧准备终端字库；绘制路径只消费现成资源。"""
        labels = {"0123456789 .-+/[]()%:›‹ONOFF", "POLAR TERMINAL", "POLAR 终端",
                  "搜索终端搜索结果终端设置返回查看模块详情快捷键已启用已关闭",
                  "Search MODULE DETAILS KEY BIND ENABLED DISABLED TERMINAL SETTINGS RESULTS",
                  "未找到匹配模块尝试中文名称模块或设置关键词点击修改绑定拖动开关可放入九格功能栏"}
        for category in CATEGORIES:
            labels.update((category_label(category, True), category_label(category, False)))
        for module in registry.modules:
            labels.update((module.name, module.description, module_label(module.name, True),
                           description_label(module.description, True)))
            for setting in module.settings:
                labels.update((setting.name, setting.description or "", setting_label(setting.name, True),
                               str(setting.value)))
                labels.update(option_label(str(option), True) for option in setting.options)
        for size in (9, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 26, 30, 38, 40):
            for bold in (False, True) if size in (16, 18, 22, 23, 24, 38, 40) else (False,):
                yield ("text", ((self._wiki_font(size, bold),), labels, dpr), {"preserve_weight": True})

    def _image(self, name, x, y, w, h, alpha=1.0, clip=None, tint="#ffffff", *, rotation=0, softness_y=0):
        source = self.wiki_images.get(name)
        if source is not None and source in self._available_images:
            self.commands.image(self._r(x, y, w, h), source,
                                self._color(tint, self.opacity * alpha), clip,
                                rotation_degrees=rotation, softness_y=softness_y * self.s)
            return True
        return False

    def _hot(self, x, y, w, h, action, payload=None, *, clip=None, button=1, tooltip=""):
        if not self.interactive or self.opacity < .02:
            return
        rect = self._r(x, y, w, h)
        if clip is not None:
            rect = rect.intersected(clip)
        if not tooltip:
            target = payload[1] if isinstance(payload, tuple) and len(payload) == 2 else payload
            if action == "jello_open_settings":
                target = self.host.registry.get(str(payload))
            if hasattr(target, "description"):
                tooltip = description_label(target.description or "", self.chinese)
        self.host.add_hotspot(rect, action, payload, button=button, tooltip=tooltip)

    def _tooltip(self):
        text = getattr(self.host, "hover_tooltip", "")
        if not text or self.state.dropdown_key or getattr(self.host, "drag", None):
            return
        lines = self.wrapped_description(self._wiki_font(18), text, 420)
        line_h = QFontMetricsF(self._wiki_font(18)).height()
        height = min(850, len(lines) * line_h + 30)
        x = max(24, min(1440, (self.host.hover_point.x()-self.ox)/self.s + 24))
        y = max(100, min(960-height, (self.host.hover_point.y()-self.oy)/self.s + 24))
        self._box(x, y, 450, height, "#f4f3ed", "#898a86")
        self._text(x + 15, y + 15, 420, height - 30, text, 18,
                   align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                   clip=self._r(x, y, 450, height))

    def _label(self, cn, en):
        return cn if self.chinese else en

    def _elide(self, value, size, width):
        return QFontMetricsF(self._wiki_font(size)).elidedText(
            str(value), Qt.TextElideMode.ElideRight, max(1, width))

    def _background(self):
        draw_scene_ground(self)
        draw_background(self)
        draw_page_layers(self)

    def _top(self):
        self._box(53, 25, 1407, 50, "#eeedeb", "#888987")
        self._image("folder", 68, 36.5, 35, 27)
        self._image("path_arrow", 119, 41, 10, 18)
        self._hot(55, 25, 79, 50, "wiki_home")
        crumbs = [(self._label("POLAR 终端", "POLAR TERMINAL"), "wiki_home" if self.view_category else None, None)]
        if self.view_category:
            crumbs.append((category_label(self.view_category, self.chinese), None, None))
        # 分栏里选择模块只更新同一页面的内容，不增加一层可返回的页面路径。
        self._breadcrumbs(crumbs, 141.5, 1445)
        self._box(1474, 25, 326, 50, "#eeedeb", "#888987")
        self._image("search", 1486, 30, 40, 40)
        self._text(1534, 25, 245, 50, self._label("搜索终端", "Search"), 26, MUTED)
        self._hot(1474, 25, 326, 50, "wiki_search")
        self._navigation_button(self.view_category is not None or self.view_module is not None)

    def _navigation_button(self, back):
        self._image("back" if back else "close", 1812, 11, 78, 78)
        self._hot(1811, 10, 80, 80, "wiki_back" if back else "wiki_close")

    def _search_top(self):
        old = self.opacity
        self.opacity *= self.motion.sample(self.search_clip, "NotchNode/Main/Right", "m_Alpha", self.search_at, 1)
        anchor = self.motion.sample(self.search_clip, "NotchNode/Main/TopNode/RightNode/InputField",
                                    "m_AnchorMin.x", self.search_at)
        # 与HistoryNode、TopWidget共用.8比例；498×50是源尺寸，不能直接当设计像素。
        unit, right, top = .8, 1800.8, 23.2
        width = 498 * unit * (1 - anchor)
        x = right - width
        self._box(x, top, width, 50 * unit, "#eeedeb", "#393939")
        self._image("search", x + 12 * unit, top + 5 * unit, 40 * unit, 40 * unit)
        text = self.search_query + self.state.search_preedit
        self._text(x + 60 * unit, top, width - 180 * unit, 50 * unit,
                   self._elide(text or self._label("请输入文字", "Enter text"), 26 * unit, width - 180 * unit),
                   26 * unit, INK if text else MUTED)
        self._hot(x, top, width, 50 * unit, "wiki_search")
        if self.search_query:
            self._text(right - 145 * unit, top, 30 * unit, 50 * unit, "×", 28 * unit)
            self._hot(right - 150 * unit, top, 42 * unit, 50 * unit, "wiki_clear_search")
        self._box(right-100*unit,top+6*unit,90*unit,38*unit,"#666666" if text.strip() else "#929292")
        self._text(right-100*unit,top+6*unit,90*unit,38*unit,self._label("搜索","Search"),24*unit,"#ffffff",
                   align=Qt.AlignmentFlag.AlignCenter)
        if text.strip():
            self._hot(right-100*unit,top,90*unit,50*unit,"wiki_submit_search")
        self._image("back",1817.6,12,78*unit,78*unit)
        self._hot(1816.8,11.2,80*unit,80*unit,"wiki_back")
        self.opacity = old

    def _breadcrumbs(self, crumbs, left, right):
        source = self.pack["breadcrumbs"]
        size, spacing = source["font_size"], source["spacing"]
        metrics = QFontMetricsF(self._wiki_font(size))
        paddings = [source["padding"]["normal" if i < len(crumbs) - 1 else "current"]
                    for i in range(len(crumbs))]
        widths = [metrics.horizontalAdvance(text) + p["m_Left"] + p["m_Right"]
                  for (text, _, _), p in zip(crumbs, paddings)]
        available = right - left - spacing * (len(crumbs) - 1)
        while sum(widths) > available:
            index = max(range(len(widths)), key=widths.__getitem__)
            widths[index] -= min(widths[index] - 60, sum(widths) - available)
        clip = self._r(left, 25, right - left, 50)
        for index, ((text, action, payload), width) in enumerate(zip(crumbs, widths)):
            parent = index < len(crumbs) - 1
            padding = paddings[index]
            hovered = action and self._r(left, 25, width, 50).contains(self.host.hover_point)
            if parent:
                self._path_background(left, width, source["background"], clip)
            if hovered and parent:
                self._path_background(left, width, source["highlight"], clip)
            text_width = width - padding["m_Left"] - padding["m_Right"]
            color = source["parent_color" if parent else "current_color"]
            tint = QColor.fromRgbF(*(color[c] for c in "rgba"))
            self._text(left + padding["m_Left"], 25, text_width, 50, self._elide(text, size, text_width),
                       size, tint, clip=clip)
            if action:
                self._hot(left, 25, width, 50, action, payload, clip=clip)
            if parent:
                self._image("path_arrow", left + width + 10, 41, 10, 18)
            left += width + spacing

    def _path_background(self, left, width, layer, clip):
        """两种状态共用本体九宫格，保留圆角和抗锯齿边缘，中心区域单独拉伸。"""
        source = self.pack["breadcrumbs"]
        bl, bt, br, bb = source["border"]
        height = 50 + layer["size_delta"]["y"]
        top = 50 - layer["position"]["y"] - height / 2
        xs, ys = (left, left + bl, left + width - br, left + width), (top, top + bt, top + height - bb, top + height)
        color = layer["color"]
        tint = QColor.fromRgbF(*(color[c] for c in "rgb"))
        for row, keys in enumerate(source["slices"]):
            for column, key in enumerate(keys):
                self._image(key, xs[column], ys[row], xs[column + 1] - xs[column], ys[row + 1] - ys[row],
                            color["a"], clip=clip, tint=tint)

    def _home(self):
        # 普通图层沿用原入场；选中层全部以原片段的绝对时刻驱动，不能把时钟压成一条透明度。
        for index, category in enumerate(CATEGORIES):
            x = 210 + index * 257
            rect = self._r(x - 16, 136, 238, 790)
            hovered = rect.contains(self.host.hover_point) or self.state.focus_index == index
            self.state.home_hover(category, hovered, self.now, self.motion)
            pose = self.state.home_hovers[category]
            mask = pose.track(self.motion, "ImgBgBlackmask", "m_Alpha", self.now)
            normal_alpha = 1.0 - max(0, min(1, mask))
            node = ("Teaching", "Monster", "Weapon", "Equipment", "Device", "Scientific")[index]
            path = f"Main/TotalNode/Btn{node}/Animation{node}"
            reveal = self.motion.sample(self.page_clip, path, "m_Alpha", self.page_at, 1)
            y = -self.motion.sample(self.page_clip, path, "m_AnchoredPosition.y", self.page_at)
            local_at = .667 if self.page_out else self.page_at
            number_alpha = self.motion.sample("wiki_btnoption_in", "NormalNode/ImgNumber", "m_Color.a", local_at, 1)
            number_y = 173.5 - self.motion.sample("wiki_btnoption_in", "NormalNode/ImgNumber", "m_AnchoredPosition.y", local_at, 173.5)
            self._image("number" + str(index + 1), x + 4, 385 + y + number_y, 194, 125,
                        reveal * number_alpha * normal_alpha)
            icon_y = 461 + y
            self._image(category + "Deco", x - 16, icon_y - 20, 238, 250,
                        .6 * reveal * normal_alpha)
            # 普通图标与详细选中图是互斥的；遮罩的软扩散不应拖延图标交接。
            self._image(category, x, icon_y, 204, 200, 0 if hovered else .70 * reveal * normal_alpha)
            draw_home_selection(self, category, x, icon_y, reveal, pose)
            self._text(x - 12, 656 + y, 224, 48, category_label(category, self.chinese), 26, INK,
                       align=Qt.AlignmentFlag.AlignCenter, alpha=reveal * normal_alpha)
            self._hot(x - 16, 136, 238, 790, "wiki_category", category)

    def _sidebar(self, selected):
        first = len(self.commands.commands)
        modules = wiki_modules(self.host.registry, selected.category, "")
        clip = self._r(55, 153, 400, 756)
        key = "wiki:" + selected.category
        maximum = max(0, len(modules) * 110 - 10 - 756) * self.s
        scroll = max(0, min(maximum, self.state.panel_scroll.get(key, 0)))
        if self.state.reveal_module and not self.page_out:
            index = next((i for i, m in enumerate(modules) if m is selected), 0)
            top = index * 110 * self.s
            scroll = max(0, min(maximum, min(scroll, top) if top < scroll
                                else max(scroll, top + 100 * self.s - clip.height())))
            self.state.reveal_module = False
        self.state.panel_scroll[key] = scroll
        self.host.gui_scroll_viewports.append({"mode": "jello_panel", "key": key,
                                               "maximum": maximum, "rect": clip})
        for index, module in enumerate(modules):
            y = 153 + index * 110 - (scroll+edge_offset(self.state,key)) / self.s
            if self._r(55, y, 400, 100).intersected(clip).isEmpty():
                continue
            self._section("wiki_group_leftcell_in", "",
                          lambda m=module, y=y: self._sidebar_row(m, m is selected, y, clip),
                          at=1 if self.page_out else self.page_at)
        fade_edges(self.commands,first,clip,self.pack["layers"]["scroll"]["softness_y"] * self.s)
        self._scrollbar(466, 153, 756, scroll, maximum)

    def _sidebar_row(self, module, active, y, clip):
        hovered = self._r(55, y, 400, 100).contains(self.host.hover_point) and not self.state.search_open
        button_color,outgoing,track = self._row_pose(module.name,hovered)
        normal = button_color("normal_bg")
        normal_alpha = track("ImgNormalBg", "m_Color.a", 0) if active else normal[3]
        self.commands.rect(self._r(55, y, 400, 100), 4 * self.s,
            self._color(QColor.fromRgbF(*normal[:3]), self.opacity * normal_alpha), clip=clip)
        icon = self.pack.get("module_icons", {}).get(module.name, "module_guide_system")
        label = self._elide(module_label(module.name, self.chinese), 30, 252)
        if not active:
            self._image(icon, 90, y + 25, 50, 50, clip=clip)
            self._text(143, y + 22, 252, 44, label, 30, "#393939", clip=clip)
            self._image("module_deco", 143, y + 69, 46, 7, .2, clip=clip)
        if active or outgoing:
            self._selected_row_background(button_color,track,55,y,400,100,clip)
            line_h = track("ImgLine", "m_SizeDelta.x", 86)
            self.commands.rect(self._r(64, y + (100 - line_h) / 2, 6, line_h), 3 * self.s,
                self._color("#fff100", self.opacity * track("ImgLine", "m_Color.a")), clip=clip)
            self._image(icon + "_selected", 55 + track("SelectIconImg", "m_AnchoredPosition.x", 60) - 25,
                        y + 25, 50, 50, track("SelectIconImg", "m_Color.a"), clip=clip)
            self._text(55 + track("TxtTitleSelected", "m_AnchoredPosition.x", 88), y + 22, 252, 44,
                       label, 30, "#ececec", alpha=track("TxtTitleSelected", "m_fontColor.a"), clip=clip)
            self._image("module_deco", 143, y + 69, 46, 7, track("Deco2Image", "m_Color.a", .35), clip=clip)
        self._hot(55, y, 400, 100, "jello_open_settings", module.name, clip=clip)

    def _category(self):
        modules = wiki_modules(self.host.registry, self.view_category, "")
        if modules:
            self._detail(modules[0])

    def _search_page(self):
        query = self.search_query
        if not query.strip():
            self._search_history()
            return
        modules = wiki_modules(self.host.registry, None, query)
        self._text(85, 132, 1300, 60, self._label("搜索结果", "SEARCH RESULTS"), 38, bold=True)
        self._text(85, 197, 1300, 30,
                   self._label("搜索模块名称、设置与说明", "Search modules, settings and descriptions"), 19, MUTED)
        self._text(1510, 150, 325, 35, f"{len(modules)} " + self._label("项结果", "RESULTS"), 19, MUTED,
                   align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if modules:
            self._search_results(modules)
        else:
            self._text(300, 410, 1320, 80, self._label("未找到匹配模块", "No matching modules"), 30,
                       align=Qt.AlignmentFlag.AlignCenter)
            self._text(300, 490, 1320, 50, self._label("尝试中文名称、模块 ID 或设置关键词", "Try a module ID or setting name"),
                       20, MUTED, align=Qt.AlignmentFlag.AlignCenter)

    def _search_history(self):
        draw_history(self)

    def _search_results(self, modules):
        selected_index = (self.state.focus_index if self.state.focus_index >= 0 else
                          next((i for i,m in enumerate(modules) if m.name == self.state.search_selection), 0)) % len(modules)
        selected = modules[selected_index]
        self.state.select_search(selected.name)
        at = self.search_at if self.state.search_closing_at is not None else min(
            self.search_at, max(0, self.now - self.state.search_content_at))
        self._section(self.search_clip, "NotchNode/Main/Left/ScrollView",
                      lambda: self._search_left(modules, selected_index), at=at)
        self._section(self.search_clip, "NotchNode/Main/Right",
            lambda: self._section(self.search_clip, "NotchNode/Main/Right/Bottom",
                                  lambda: self._switch_content(selected,self.state.search_from,
                                      self.state.search_changed_at,self._search_preview), at=at), at=at)

    def _row_palette(self, key, hovered):
        """目录与搜索共用本体Tab按钮的即时高亮、100ms移出和明暗状态。"""
        hover = self.state.row_hover(key, hovered, self.now)
        states = self.pack["tab_button"]["states"]
        return lambda field: [a+(b-a)*hover for a,b in
                              zip(states["Normal"][field],states["Highlighted"][field])]

    def _row_pose(self, key, hovered):
        """两种目录共用原选中底框展开与移出淡化，不重启列表入场。"""
        change = self.state.row_changes.get(key)
        outgoing = bool(change and not change[0] and self.now-change[1]<1/6)
        clip = "wiki_group_leftcellselect_out" if outgoing else "wiki_group_leftcellselect"
        at = max(0,self.now-change[1]) if change else 1
        return self._row_palette(key,hovered),outgoing,lambda path,attribute,default=1: \
            self.motion.sample(clip,path,attribute,at,default)

    def _selected_row_background(self, palette, track, x, y, width, height, clip):
        fill_clip = self._r(x,y,width*track("ImgBg","m_AnchorMax.x"),height).intersected(clip)
        selected = palette("selected_bg")
        self.commands.rect(self._r(x,y,width,height),4*self.s,
            self._color(QColor.fromRgbF(*selected[:3]),self.opacity*track("ImgBg","m_Color.a")),clip=fill_clip)
        deco_clip = self._r(x,y,width*track("ImgBgDeco","m_FillAmount"),height).intersected(clip)
        self._image("module_selected_bg",x,y,width,height,track("ImgBgDeco","m_Color.a"),
                    clip=deco_clip,tint=QColor.fromRgbF(*palette("selected_deco")))

    def _search_left(self, modules, selected_index):
        first = len(self.commands.commands)
        clip = self._r(85, 300, 580, 610)
        maximum = max(0, len(modules) * 72 - 610) * self.s
        scroll = max(0, min(maximum, self.state.panel_scroll.get("wiki:search", 0)))
        if self.state.focus_index >= 0:
            top = selected_index * 72 * self.s
            scroll = max(0, min(maximum, min(scroll, top) if top < scroll
                                else max(scroll, top + 68*self.s-clip.height())))
        self.state.panel_scroll["wiki:search"] = scroll
        self.host.gui_scroll_viewports.append({"mode": "jello_panel", "key": "wiki:search",
                                               "maximum": maximum, "rect": clip})
        for index, module in enumerate(modules):
            y = 300 + index * 72 - (scroll+edge_offset(self.state,"wiki:search")) / self.s
            if self._r(85, y, 580, 68).intersected(clip).isEmpty():
                continue
            chosen = index == selected_index
            hovered = self._r(85,y,580,68).intersected(clip).contains(self.host.hover_point)
            palette,outgoing,track = self._row_pose("search:"+module.name,hovered)
            color = palette("normal_bg")
            normal_alpha = track("ImgNormalBg","m_Color.a",0) if chosen else color[3]
            self.commands.rect(self._r(85,y,580,68),4*self.s,
                               self._color(QColor.fromRgbF(*color[:3]),self.opacity*normal_alpha),clip=clip)
            def labels(selected,alpha=1,dx=0):
                ink,muted = ("#ffffff","#c8c8c8") if selected else (INK,MUTED)
                self._text(101+dx,y+5,45,58,f"{index+1:02}",18,muted,clip=clip,alpha=alpha)
                self._text(166+dx,y+2,470,38,module_label(module.name,self.chinese),23,ink,
                           bold=selected,clip=clip,alpha=alpha)
                self._text(166+dx,y+40,470,24,category_label(module.category,self.chinese)+" / "+module.name,
                           15,muted,clip=clip,alpha=alpha)
            if not chosen:
                labels(False)
            if chosen or outgoing:
                self._selected_row_background(palette,track,85,y,580,68,clip)
                labels(True,track("TxtTitleSelected","m_fontColor.a"),
                       track("TxtTitleSelected","m_AnchoredPosition.x",88)-88)
            self._hot(85, y, 580, 68, "wiki_search_select", module.name, clip=clip)
        fade_edges(self.commands,first,clip,10*self.s)
        self._scrollbar(674, 300, 610, scroll, maximum)

    def _search_preview(self, selected):
        self._image(selected.category, 800, 310, 260, 260, 0.35)
        self._text(1110, 325, 700, 66, module_label(selected.name, self.chinese), 38, bold=True)
        self._text(1110, 399, 700, 40, selected.name, 21, MUTED)
        self._text(800, 610, 1005, 100, description_label(selected.description, self.chinese), 24,
                   align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap)
        self._text(800, 737, 1000, 40,
                   self._label("快捷键", "KEY BIND") + f" [ {selected.keybind} ]   /   "
                   + str(len(selected.settings)) + self._label(" 项设置", " SETTINGS"), 21, MUTED)
        self._box(800, 836, 1005, 64, YELLOW)
        self._text(820, 836, 965, 64, self._label("查看模块详情   ›", "MODULE DETAILS   ›"), 24,
                   bold=True, align=Qt.AlignmentFlag.AlignCenter)
        self._hot(800, 836, 1005, 64, "jello_open_settings", selected.name)

    def _detail(self, module):
        self._section(self.page_clip, "NotchNode/Main/Left/ScrollListLeft",
                      lambda: self._sidebar(module), at=self.page_at)
        self._section(self.page_clip, "NotchNode/Main/Center/ItemScrollListCenter",
                      lambda: self._detail_content(module), at=self.page_at)

    def _detail_content(self, module):
        self._switch_content(module,self.state.module_from,self.state.module_changed_at,self._detail_body)

    def _switch_content(self, module, previous_name, changed_at, draw):
        """目录详情和搜索预览共用本体ItemBig入场及Center退场，旧内容不发布热点。"""
        at = self.now - changed_at
        duration = self.motion.durations.get("itembigleft_in", 1 / 3)
        previous = self.host.registry.get(previous_name or "")
        if not previous or self.page_out or at >= duration:
            draw(module)
            return
        # WikiGroup 的 UpdateCount 实际播放 ItemBig 的 20px 淡入，而非展开列表的 200px 动画。
        # 终端保留旧设置面板，叠加本体 Center 的短退场透明度；两条轨道同时起播。
        opacity, dx, interactive = self.opacity, self.dx, self.interactive
        viewport_count = len(self.host.gui_scroll_viewports)
        try:
            self.interactive = False
            self.opacity *= self.motion.sample("wiki_group_out",
                "NotchNode/Main/Center/ItemScrollListCenter", "m_Alpha", at, 1)
            if self.opacity > .001:
                draw(previous)
            del self.host.gui_scroll_viewports[viewport_count:]
            self.opacity, self.interactive = opacity, interactive
            self.dx += self.motion.sample("itembigleft_in", "AnimationNode", "m_AnchoredPosition.x", at)
            self._section("itembigleft_in", "", lambda: draw(module), at=at)
        finally:
            self.opacity, self.dx, self.interactive = opacity, dx, interactive

    def _detail_body(self, module):
        self._text(515, 127, 1090, 64, module_label(module.name, self.chinese), 40, bold=True)
        self._text(515, 194, 1100, 30, module.name + "  /  " + category_label(module.category, self.chinese), 17, MUTED)
        self._box(1655, 143, 190, 46, YELLOW if module.enabled else "#c8c8c4")
        self._text(1655, 143, 190, 46, self._label("已启用", "ENABLED") if module.enabled else self._label("已关闭", "DISABLED"),
                   22, bold=True, align=Qt.AlignmentFlag.AlignCenter)
        self._hot(1655, 143, 190, 46, "jello_module_press", module.name)
        desc = description_label(module.description, self.chinese)
        self._text(515, 242, 1330, 76, desc, 21,
                   align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap)
        self._box(515, 331, 1330, 1, "#aaa9a5")
        bind = self._label("快捷键", "KEY BIND") + "  [ " + str(module.keybind) + " ]"
        self._box(515, 347, 410, 44, "#d4d3cf")
        self._text(533, 347, 374, 44, bind, 19)
        self._hot(515, 347, 410, 44, "module_bind", module.name)
        self._text(956, 347, 880, 44, self._label("点击修改绑定 · 拖动开关可放入九格功能栏", "Edit binding · Drag switch to a hotbar slot"), 17, MUTED)
        self._settings(module, 515, 416, 1330, 493)

    def _settings(self, module, x, y, width, height):
        clip = self._r(x, y, width, height)
        rows = []
        for setting in module.settings:
            expanded = self.state.expanded_action_group == f"{module.name}:{setting.name}"
            row_h = 78 + (len(setting.options) * 42 if setting.kind == "action_group" and expanded else 0)
            rows.append((setting, row_h))
        maximum = max(0.0, sum(row_h for _, row_h in rows) - height) * self.s
        scroll = self.state.settings_scroll_value(module.name, maximum)
        self.host.gui_scroll_viewports.append({"mode": "jello_settings", "key": module.name,
                                               "maximum": maximum, "rect": clip})
        cy = y - (scroll+edge_offset(self.state,module.name)) / self.s
        dropdown = None
        for setting, row_h in rows:
            if not self._r(x, cy, width, row_h).intersected(clip).isEmpty():
                self._box(x, cy, width, 72, "#edede9", alpha=0.8, clip=clip)
                self._text(x + 20, cy + 7, width - 640, 32,
                           self._elide(setting_label(setting.name, self.chinese), 22, width - 640), 22, clip=clip)
                self._text(x + 20, cy + 41, width - 470, 24,
                           self._elide(description_label(setting.description or "", self.chinese), 16, width - 470),
                           16, MUTED, clip=clip)
                result = self._control(module, setting, x, cy, width, clip)
                if result:
                    dropdown = result
            cy += row_h
        if not rows:
            self._text(x + 20, y + 30, width - 40, 60,
                       self._label("此模块通过顶部开关与快捷键操作", "Use the module switch and key bind above"), 23, MUTED)
        self._scrollbar(x + width + 8, y, height, scroll, maximum)
        if dropdown:
            self._mode_popup(*dropdown, clip)

    def _control(self, module, setting, x, y, width, clip):
        key = f"{module.name}:{setting.name}"
        cx = x + width - 440
        if setting.kind == "bool":
            active = self.state.checkbox_progress(key, bool(setting.value))
            self._box(x + width - 108, y + 19, 82, 34, "#c3c3bf", clip=clip)
            self._box(x + width - 108, y + 19, 82, 34, YELLOW, alpha=active, clip=clip)
            self._text(x + width - 108, y + 19, 82, 34, "ON" if setting.value else "OFF", 18,
                       bold=True, align=Qt.AlignmentFlag.AlignCenter, clip=clip)
            self._hot(x + width - 120, y + 6, 110, 59, "setting_toggle", setting, clip=clip)
        elif setting.kind == "number":
            ratio = setting.ratio()
            self._text(cx - 170, y + 17, 150, 36, setting.display_value(), 21,
                       align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, clip=clip)
            self._box(cx, y + 34, 400, 3, "#a9aaa6", clip=clip)
            self._box(cx, y + 34, 400 * ratio, 3, INK, clip=clip)
            self._box(cx + 400 * ratio - 6, y + 23, 12, 25, INK, clip=clip)
            self._hot(cx, y + 12, 400, 48, "setting_slider", setting, clip=clip)
        elif setting.kind == "mode":
            self._box(cx, y + 15, 414, 42, "#d7d7d2", clip=clip)
            self._text(cx + 16, y + 15, 365, 42,
                       self._elide(option_label(str(setting.value), self.chinese), 20, 365), 20, clip=clip)
            self._image("chevron", cx + 375, y + 22, 28, 28, clip=clip)
            self._hot(cx, y + 10, 414, 52, "jello_mode_dropdown", (key, setting), clip=clip)
            if self.state.dropdown_key == key:
                return setting, cx, y + 60, 414
        elif setting.kind == "text":
            value = str(setting.value)
            self._text(cx, y + 12, 414, 48, self._elide(value, 18, 414), 18, MUTED, clip=clip)
            self._hot(cx, y + 10, 414, 52, "wiki_copy_text", value, clip=clip, tooltip=value)
        elif setting.kind in ("action", "action_group"):
            expanded = self.state.expanded_action_group == key
            label = action_label("Hide" if expanded else "Show all", self.chinese) if setting.kind == "action_group" else action_label("Run", self.chinese)
            self._box(cx, y + 15, 414, 42, "#d3d3ce", clip=clip)
            self._text(cx + 16, y + 15, 382, 42, label + "  ›", 20, clip=clip)
            self._hot(cx, y + 10, 414, 52, "jello_toggle_old_group" if setting.kind == "action_group" else "config_action",
                      key if setting.kind == "action_group" else setting.name, clip=clip)
            if setting.kind == "action_group" and expanded:
                for index, option in enumerate(setting.options):
                    oy = y + 78 + index * 42
                    self._box(x + 20, oy, width - 40, 38, "#d8d8d3", clip=clip)
                    self._text(x + 38, oy, width - 76, 38, action_label(str(option), self.chinese), 20, clip=clip)
                    self._hot(x + 20, oy, width - 40, 38,
                              "jello_open_legacy" if setting.name == "Old ClickGUIs" else "config_action", option, clip=clip)
        return None

    def _mode_popup(self, setting, x, y, width, settings_clip):
        # 下拉独占滚轮和背景点击，不让它们穿透到底下的滑条。
        full = self._r(0, 88, 1920, 904)
        self.host.add_hotspot(full, "wiki_back", button=1)
        max_h = min(380, len(setting.options) * 42)
        y = max(105, min(y, 914 - max_h))
        clip = self._r(x, y, width, max_h)
        maximum = max(0, len(setting.options) * 42 - max_h) * self.s
        scroll = max(0.0, min(maximum, self.state.dropdown_scroll))
        if self.state.dropdown_focus >= 0:
            top = self.state.dropdown_focus * 42 * self.s
            scroll = max(0, min(maximum, min(scroll, top) if top < scroll
                                else max(scroll, top + 42*self.s-clip.height())))
        self.state.dropdown_scroll = scroll
        self.host.gui_scroll_viewports.append({"mode": "jello_dropdown", "key": self.state.dropdown_key,
                                               "maximum": maximum, "rect": clip})
        self._box(x, y, width, max_h, "#f2f1eb", INK)
        self.host.add_hotspot(clip, "jello_noop")
        for index, option in enumerate(setting.options):
            oy = y + 42 * index - scroll / self.s
            if self._r(x, oy, width, 42).intersected(clip).isEmpty():
                continue
            selected = option == setting.value
            hovered = self._r(x, oy, width, 42).contains(self.host.hover_point) or self.state.dropdown_focus == index
            if selected or hovered:
                self._box(x + 1, oy, width - 2, 42, YELLOW if selected else "#d9d9d4", clip=clip)
            self._text(x + 16, oy, width - 32, 42,
                       self._elide(option_label(str(option), self.chinese), 20, width - 32), 20, clip=clip)
            self._hot(x, oy, width, 42, "jello_mode_select", (setting, option), clip=clip)

    def _scrollbar(self, x, y, height, scroll, maximum):
        if maximum <= 0:
            return
        self._box(x, y, 3, height, "#c1c1bd")
        total = height + maximum / self.s
        handle = max(28, height * height / total)
        self._box(x, y + (height - handle) * scroll / maximum, 3, handle, INK)

    def _footer(self):
        self._box(53, 978, 1815, 1, "#aaa9a5", alpha=0.55)
        self._text(65, 994, 240, 42, self._label("‹  返回", "‹  BACK"), 22)
        self._hot(53, 987, 240, 58, "wiki_back")
        profile = str(self.host.current_profile()) if hasattr(self.host, "current_profile") else "default"
        self._text(365, 999, 650, 30, "POLAR-RM  /  " + profile, 16, MUTED)
        language = self._label("中文 / EN", "EN / 中文")
        self._text(1280, 995, 230, 38, language, 18,
                   align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._hot(1260, 990, 255, 48, "jello_toggle_language")
        self._text(1555, 995, 270, 38, self._label("终端设置", "TERMINAL SETTINGS"), 19,
                   align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._image("settings", 1840, 1001, 25, 25)
        self._hot(1555, 990, 310, 48, "jello_open_settings", "ClickGui")
