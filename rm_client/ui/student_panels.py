"""Minecraft inventory/scoreboard and Jello student panels.

The static panel is cached at device DPR; animations composite that image on
the existing GPU target layer. No glass material, shader or video path changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from ..student_ui import active_buffs, damage_rows, device_rows, number, presentation_data, settlement_rows, value_text
from .clickgui_gpu import ClickGuiDrawList
from .animation import Easings
from .jello_clickgui import JelloMainTimeline
from .jello_locale import module_label, chinese_enabled
from .minecraft_presentation import MinecraftItemAtlas


@dataclass(frozen=True)
class PanelHit:
    rect: QRectF
    action: str
    payload: Any = None
    tooltip: str = ""


def pixel_icon(kind: int, variant: str = "") -> QImage:
    """Original 16px voxel badges, deliberately not copied item artwork."""
    image = QImage(16, 16, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    palette = {1: "#ff7055", 2: "#a884ef", 3: "#55ddff", 4: "#ffda55", 5: "#72ed8a", 6: "#e9ba72", 7: "#55c6b6", 8: "#ffd65a", 9: "#ee5577"}
    base = QColor(palette.get(kind, "#55aaff"))
    # Isometric cube with a recognisable sign on its front face.
    for x, y, w, h, c in [(4, 2, 8, 2, base.lighter(140)), (2, 4, 12, 2, base),
                           (2, 6, 6, 7, base.darker(120)), (8, 6, 6, 7, base.darker(170)),
                           (4, 13, 8, 1, base.darker(190))]:
        p.fillRect(x, y, w, h, c)
    white = QColor("#edffff")
    if kind == 3:  # Cooling: cyan snowflake, not a vanilla armour sprite.
        for r in [(5, 6, 1, 6), (3, 8, 5, 1), (4, 7, 3, 1), (4, 10, 3, 1)]: p.fillRect(*r, white)
    elif kind == 1:
        for r in [(5, 6, 1, 6), (4, 9, 3, 1), (4, 11, 3, 1)]: p.fillRect(*r, white)
    elif kind == 2:
        for r in [(3, 6, 4, 1), (3, 7, 1, 3), (6, 7, 1, 3), (4, 10, 2, 1), (4, 11, 1, 1)]: p.fillRect(*r, white)
        if "易伤" in variant:
            p.fillRect(5, 7, 1, 4, QColor("#ff5555"))
    elif kind == 8:  # Rune: five radial voxel lights around a dark hub.
        for r in [(5,6,1,2),(3,7,2,1),(6,8,2,1),(3,10,2,1),(5,10,1,2)]:p.fillRect(*r,white)
        p.fillRect(5,8,1,2,QColor("#55ffff"))
    elif kind == 9:  # Double vulnerability: broken shield and two red chips.
        for r in [(3,6,4,1),(3,7,1,3),(6,7,1,3),(4,10,2,1)]:p.fillRect(*r,white)
        p.fillRect(5,7,1,4,QColor("#4c1534"));p.fillRect(10,6,1,3,white);p.fillRect(12,6,1,3,white)
    elif kind == 5:
        p.fillRect(3, 8, 5, 2, white); p.fillRect(5, 6, 1, 6, white)
    elif kind == 4:
        for r in [(5, 6, 2, 2), (4, 8, 2, 2), (5, 10, 1, 2)]: p.fillRect(*r, white)
    else:
        p.fillRect(4, 7, 3, 4, white); p.fillRect(5, 6, 1, 1, white)
    p.end()
    return image


class StudentPanelRenderer:
    def __init__(self, asset_root: Path) -> None:
        self.asset_root = Path(asset_root)
        self.inventory = QImage(str(self.asset_root / "inventory.png"))
        self.items = MinecraftItemAtlas(self.asset_root)
        self._cache_key = None
        self._cache_image = QImage()
        self._cache_hits: tuple[PanelHit, ...] = ()
        self.icons = {kind: pixel_icon(kind) for kind in range(1, 10)}
        self.vulnerability_icon = pixel_icon(2,"易伤")
        self.rebuilds = 0
        self._shadow_images: dict[str, QImage] = {}
        self._status_key = None
        self._status_image = QImage()
        self.status_rebuilds = 0

    @staticmethod
    def font(host: Any, size: float, medium: bool = False) -> QFont:
        font = QFont(host.font("jello_medium" if medium else "jello_light", size))
        font.setFamilies([font.family(), "Microsoft YaHei UI", "Microsoft YaHei", "DengXian", "sans-serif"])
        return font

    @staticmethod
    def geometry(host: Any, width: int, height: int) -> tuple[QRectF, float]:
        state = host.student_ui
        if state.panel in {"inventory", "damage"}:
            module = host.registry.get("MinecraftCombatHUD")
            desired = host.minecraft_hud.layout(width, height, host.setting_mode(module, "GUI Scale", "Auto"),
                scale_multiplier=host.get_setting_number(module, "Scale Multiplier", 1.0)).scale
            logical_w,logical_h = (190,220) if state.panel=="inventory" else (280,170)
            scale = min(desired, (width - 32) / logical_w, (height - 32) / logical_h)
            w, h = logical_w * scale, logical_h * scale
        else:
            scale = min(host.get_gui_scale(), (width - 32) / 740, (height - 32) / 550)
            w, h = 740 * scale, 550 * scale
        scale = max(0.1, scale)
        return QRectF((width-w)/2, 10 if state.panel=="damage" else (height-h)/2, w, h), scale

    def draw(self, host: Any, p: QPainter, width: int, height: int) -> None:
        state = host.student_ui
        if not state.visible or not state.panel:
            return
        panel, scale = self.geometry(host, width, height)
        progress = Easings.ease_out_cubic(state.progress)
        offset = (1 - progress) * 18 * scale
        panel = panel.translated(0, offset)
        dpr = host.devicePixelRatioF()
        module = host.registry.get("SkillConfiguration")
        key = (state.panel, round(panel.width(), 2), round(panel.height(), 2), round(dpr, 2),
               state.page, state.category, state.selected, state.selected_slot, state.gate, state.quantity, state.dart_target, state.note,
               host.registry.enabled_revision, chinese_enabled(host.registry),
               tuple((s.name, str(s.value)) for s in module.settings) if module else (),
               str(host.minecraft_hud.assignments(host.registry.get("MinecraftCombatHUD"))),
               str(self.content_rows(host)), str(presentation_data(host.state)))
        if key != self._cache_key:
            image = QImage(max(1, round(panel.width() * dpr)), max(1, round(panel.height() * dpr)), QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, state.panel != "inventory" and state.panel != "damage")
            local = QRectF(0, 0, panel.width(), panel.height())
            hits: list[PanelHit] = []
            if state.panel == "inventory":
                self.inventory_panel(host, painter, local, scale, hits)
            elif state.panel == "damage":
                self.tab_panel(host, painter, local, scale, hits)
            else:
                self.jello_panel(host, painter, local, scale, hits)
            painter.end()
            self._cache_key, self._cache_image, self._cache_hits = key, image, tuple(hits)
            self.rebuilds += 1
        p.save()
        p.setOpacity(p.opacity() * progress)
        if state.panel!="damage":p.fillRect(QRectF(0,0,width,height),QColor(0,0,0,100))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, state.panel not in {"inventory","damage"})
        timeline = JelloMainTimeline()
        timeline.progress = state.progress
        timeline.target = 1.0 if state.opened else 0.0
        visual = timeline.visual_factor() if state.panel not in {"inventory", "damage"} else 1.0
        image_rect = QRectF(panel.center().x() - panel.width()*visual/2,
                           panel.center().y() - panel.height()*visual/2,
                           panel.width()*visual, panel.height()*visual)
        if state.panel not in {"inventory", "damage"}:
            shadows = ClickGuiDrawList()
            host.jello_clickgui._build_shadow(shadows, image_rect, 20.0*scale*visual, 1.0)
            for item in shadows.images:
                if item.source not in self._shadow_images:
                    # The JAR's eight shadows are black RGB plus alpha. GPU
                    # multiplicative LIGHT_GREYISH_BLUE tint leaves them black;
                    # SourceIn recolouring would wrongly create a white glow.
                    self._shadow_images[item.source] = QImage(item.source)
                p.drawImage(item.rect,self._shadow_images[item.source])
        p.drawImage(image_rect, self._cache_image)
        host.hotspots.clear()
        if state.opened and state.progress >= 0.65:
            # A student modal owns the complete hit list. Background hotkeys and
            # controls never receive events through the cached HUD.
            host.hotspots.clear()
            for hit in self._cache_hits:
                rect = QRectF(image_rect.left()+hit.rect.left()*visual,
                              image_rect.top()+hit.rect.top()*visual,
                              hit.rect.width()*visual,hit.rect.height()*visual)
                host.add_hotspot(rect, hit.action, hit.payload, tooltip=hit.tooltip)
                if state.panel == "inventory" and hit.action == "student_slot":
                    host.add_hotspot(rect, "student_clear_slot", hit.payload, button=3, tooltip="右键清空功能栏槽位")
        if state.dragging:
            target=host.registry.get(state.dragging)
            icon_size=min(48,16*scale)
            p.drawImage(QRectF(host.hover_point.x()-icon_size/2,host.hover_point.y()-icon_size/2,icon_size,icon_size),
                        self.items.image(state.dragging,target.category if target else "System"))
            ghost = QRectF(host.hover_point.x() + icon_size/2+5, host.hover_point.y() + 8, 220, 30)
            ghost.moveLeft(min(ghost.left(),max(4,width-ghost.width()-4)))
            ghost.moveTop(min(ghost.top(),height-34))
            p.fillRect(ghost, QColor(0, 0, 0, 190))
            self.text(host,p,ghost.adjusted(8,0,-8,0),module_label(state.dragging,chinese_enabled(host.registry)),11,1,"#ffffff")
        elif state.opened and state.progress >= 0.99:
            hit = next((h for h in reversed(host.hotspots) if h.rect.contains(host.hover_point) and h.tooltip),None)
            if hit:
                tooltip=QRectF(min(host.hover_point.x()+12,max(4,width-474)),
                               min(host.hover_point.y()+22,height-44),min(470,width-8),32)
                p.fillRect(tooltip,QColor(16,0,28,242))
                self.text(host,p,tooltip.adjusted(8,0,-8,0),hit.tooltip,10,1,"#ffffff")
        p.restore()

    def content_rows(self, host: Any) -> tuple[tuple[str, str], ...]:
        panel = host.student_ui.panel
        state = host.state
        data = presentation_data(state)
        if panel == "damage": return damage_rows(state)
        if panel == "settlement": return host.student_ui.settlement or settlement_rows(state)
        if panel == "skills":
            static = (getattr(state, "robot_statics", {}) or {}).get(state.robot_id, {})
            sync = getattr(state, "performance_sync", {}) or {}
            return (("可分配性能点", value_text(data.get("assignable_points"))), ("当前等级", value_text(static.get("level"))),
                    ("已同步底盘类型", value_text(sync.get("chassis"))), ("已同步发射机构", value_text(sync.get("shooter"))),
                    ("技能 / 性能选择", "仅本地草稿，不下发"))
        if panel == "darts":
            dart = getattr(state, "dart_status", {}) or {}
            detail = data.get("darts", {})
            detail = detail if isinstance(detail,dict) else {}
            gate = {0:"已关闭",1:"开启中",2:"已开启"}.get(dart.get("open"),"—")
            return (("当前目标（官方）", value_text(dart.get("target_id"))), ("闸门状态（官方）", gate),
                    ("飞镖初速度", value_text(detail.get("initial_speed"), " m/s")), ("已发射飞镖数", value_text(detail.get("fired"))),
                    ("发射站冷却", value_text(detail.get("cooldown"), " s")), ("检测模块", str(detail.get("detection", "等待官方状态"))))
        return ()

    def text(self, host: Any, p: QPainter, rect: QRectF, text: str, size: float, scale: float, color: str = "#333333", medium: bool = False, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter) -> None:
        if host.student_ui.panel in {"inventory", "damage"}:
            pixel_scale=scale if host.student_ui.panel=="inventory" and size<=6 else size*scale*96/72/8
            host.minecraft_hud.styled_font.draw(p,rect,text,pixel_scale,align,
                shadow=host.student_ui.panel=="damage",base=QColor(color))
            return
        font = self.font(host, size * scale, medium)
        if any(ord(char) > 255 for char in text):
            font = QFont("Microsoft YaHei UI")
            font.setPointSizeF(size * scale)
            font.setStyleName("Regular")
            font.setWeight(QFont.Weight.Normal)
        host.draw_text(p, rect, text, font, QColor(color), align)

    def button(self, host: Any, p: QPainter, rect: QRectF, label: str, scale: float, hits: list[PanelHit], action: str, payload: Any = None, primary: bool = False, pixel: bool = False) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#29a6ff" if primary else "#ededed"))
        if pixel:
            p.fillRect(rect,QColor("#373737"));inside=rect.adjusted(scale,scale,-scale,-scale)
            p.fillRect(inside,QColor("#777777" if primary else "#686868"))
            p.fillRect(QRectF(inside.left(),inside.top(),inside.width(),scale),QColor("#d4d4d4"))
            p.fillRect(QRectF(inside.left(),inside.bottom()-scale,inside.width(),scale),QColor("#353535"))
        else:p.drawRoundedRect(rect, 4 * scale, 4 * scale)
        pad=(1 if pixel else 5)*scale
        self.text(host, p, rect.adjusted(pad, 0, -pad, 0), label, 11 if not pixel else 4, scale,
                  "#ffff55" if pixel and primary else "#ffffff" if pixel or primary else "#333333", align=Qt.AlignmentFlag.AlignCenter)
        hits.append(PanelHit(rect, action, payload, label))

    def tab_panel(self, host, p, rect, s, hits):
        """Vanilla Tab-list chrome, score column and real item glyphs; no cards."""
        def r(x,y,w,h):return QRectF(x*s,y*s,w*s,h*s)
        font=host.minecraft_hud.styled_font
        p.fillRect(rect,QColor(0,0,0,90))
        p.fillRect(r(3,3,274,23),QColor(0,0,0,155))
        font.draw(p,r(12,3,256,12),"§e§lROBOMASTER",s,Qt.AlignHCenter)
        font.draw(p,r(10,15,260,10),"§7受伤害统计  §8/  §f"+str(host.state.match_title),s*.75,Qt.AlignHCenter)
        items=("diamond_sword","arrow","fire_charge","iron_ingot","firework_rocket","iron_chestplate","compass_16","paper","nether_star")
        for i,((label,value),item) in enumerate(zip(damage_rows(host.state),items)):
            row=r(5,30+i*12,270,11)
            p.fillRect(row,QColor(255,255,255,32))
            p.drawImage(r(7,31+i*12,9,9),self.items.images[item])
            font.draw(p,r(20,30+i*12,187,11),"§f"+label,s)
            font.draw(p,r(212,30+i*12,57,11),("§7" if value=="—" else "§e")+value,s,Qt.AlignRight)
        p.fillRect(r(3,143,274,23),QColor(0,0,0,155))
        font.draw(p,r(8,143,264,11),"§7按住 ~ 查看 · 松开收起",s*.9,Qt.AlignHCenter)
        font.draw(p,r(8,154,264,10),"§7累计快照 / 未收到的字段显示 —",s*.9,Qt.AlignHCenter)

    def jello_panel(self, host: Any, p: QPainter, rect: QRectF, s: float, hits: list[PanelHit]) -> None:
        panel = host.student_ui.panel
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#fefefe"))
        p.drawRoundedRect(rect,8*s,8*s)
        ink = "#333333"
        title = {"settlement": "比赛结算", "darts": "飞镖控制面板", "skills": "性能点 / 技能配置"}.get(panel, "补弹面板")
        self.text(host, p, QRectF(26*s, 5*s, 640*s, 60*s), title, 23, s, ink)
        self.button(host, p, QRectF(680*s, 18*s, 34*s, 30*s), "×", s, hits, "student_close")
        self.text(host, p, QRectF(26*s, 64*s, 688*s, 28*s), "裁判下行 / 未提供的字段显示 —" if panel != "skills" else "右侧为本地配置草稿，左侧为已同步状态", 11, s, "#8d959d")
        rows = self.content_rows(host)
        if panel == "settlement":
            for i,(label,value) in enumerate(rows):
                row,col=divmod(i,2); tile=QRectF((26+col*354)*s,(104+row*70)*s,336*s,60*s)
                p.setBrush(QColor("#f2f5f8"));p.drawRoundedRect(tile,4*s,4*s)
                self.text(host,p,tile.adjusted(12*s,3*s,-12*s,-30*s),label,10,s,"#888888")
                self.text(host,p,tile.adjusted(12*s,25*s,-12*s,-2*s),value,18 if label!="能量机关" else 9,s,"#29a6ff")
        else:
            for i,(label,value) in enumerate(rows):
                y=(108+i*49)*s
                self.text(host,p,QRectF(26*s,y,225*s,30*s),label,13,s)
                self.text(host,p,QRectF(250*s,y,180*s,30*s),value,12,s,"#77818a")
            if panel == "darts":
                self.text(host,p,QRectF(458*s,110*s,244*s,26*s),"选择目标（草稿）",12,s)
                for i,label in enumerate(("前哨站","基地","随机固定目标")):
                    self.button(host,p,QRectF(458*s,(149+i*44)*s,244*s,34*s),label,s,hits,"student_dart_target",label,host.student_ui.dart_target==label)
                self.button(host,p,QRectF(458*s,297*s,244*s,36*s),"开启飞镖闸门 [F]",s,hits,"student_draft","dart_gate",True)
                self.button(host,p,QRectF(458*s,343*s,244*s,36*s),"发射飞镖 [L]",s,hits,"student_draft","dart_fire")
                self.text(host,p,QRectF(458*s,391*s,244*s,26*s),"本轮仅前端，不接线、不发射",10,s,"#a77d2b")
            elif panel == "skills":
                mod=host.registry.get("SkillConfiguration")
                for i,name in enumerate(("Chassis Points","Shooter Points","Shooter Draft","Chassis Draft")):
                    setting=mod.get_setting(name)
                    label={"Chassis Points":"底盘性能点","Shooter Points":"发射性能点","Shooter Draft":"发射机构类型","Chassis Draft":"底盘类型"}[name]
                    y=(118+i*64)*s
                    display={"Cooling":"冷却优先","Rate":"射速优先","Burst":"爆发优先","Power":"功率型","Energy":"能量型"}.get(str(setting.value),setting.display_value())
                    self.text(host,p,QRectF(458*s,y,244*s,24*s),f"{label}  {display}",11,s)
                    if setting.kind=="number":
                        for j,(label,delta) in enumerate((("−",-1),("+",1))):
                            self.button(host,p,QRectF((458+j*126)*s,y+28*s,118*s,27*s),label,s,hits,"student_skill",(name,delta))
                    else:self.button(host,p,QRectF(458*s,y+28*s,244*s,27*s),"切换草稿",s,hits,"student_skill",(name,1))
        self.text(host,p,QRectF(26*s,468*s,688*s,55*s),host.student_ui.note or "Esc 关闭  ·  展示层不会改写裁判数据或绕过比赛控制授权",10,s,"#929292")

    def inventory_panel(self, host: Any, p: QPainter, root: QRectF, s: float, hits: list[PanelHit]) -> None:
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        base=QRectF(7*s,35*s,176*s,166*s)
        if self.inventory.isNull(): p.fillRect(base,QColor("#c6c6c6"))
        else:p.drawImage(base,self.inventory,QRectF(0,0,176,166))
        def r(x,y,w,h):return QRectF(base.left()+x*s,base.top()+y*s,w*s,h*s)
        self.text(host,p,QRectF(7*s,0,155*s,12*s),"模块背包  ·  功能栏编辑器",5,s,"#ffffff")
        self.button(host,p,QRectF(171*s,0,12*s,12*s),"×",s,hits,"student_close",pixel=True)
        categories=("Combat","Movement","Vision","Strategy","System","Render")
        for i,name in enumerate(categories):
            self.button(host,p,QRectF((7+i*29)*s,17*s,28*s,13*s),{"Combat":"战斗","Movement":"移动","Vision":"视觉","Strategy":"战术","System":"系统","Render":"渲染"}[name],s,hits,"student_category",name,host.student_ui.category==name,True)
        # Keep the original survival inventory silhouette/slots. Replace the
        # crafting recipes with a clearly labelled skill-workbench shortcut.
        # The original player well stays empty: no Steve, portrait or mascot.
        self.text(host,p,r(94,5,76,10),"技能/性能",4,s)
        mod=host.registry.get("SkillConfiguration")
        for i,(name,item) in enumerate((("Chassis Points","ChassisAssist"),("Shooter Points","FrictionWheel"),("Shooter Draft","ArmorAutoAim"),("Chassis Draft","PowerGuard"))):
            col,row=i%2,i//2;cell=r(98+18*col,18+18*row,16,16)
            p.drawImage(cell,self.items.image(item));hits.append(PanelHit(cell,"student_open","skills",name))
        output=r(154,28,16,16);p.drawImage(output,self.items.image("SkillConfiguration"))
        hits.append(PanelHit(output,"student_open","skills","打开技能 / 性能配置"))
        self.text(host,p,r(95,56,77,12),"可分配点: "+value_text(presentation_data(host.state).get("assignable_points")),3.7,s)
        p.fillRect(r(8,73,162,10),QColor("#c6c6c6"))
        self.text(host,p,r(8,73,162,10),"拖拽模块到九格功能栏",4,s)
        modules=host.registry.by_category(host.student_ui.category)
        max_page=max(0,(len(modules)-1)//27);host.student_ui.page=min(max_page,host.student_ui.page)
        visible=modules[host.student_ui.page*27:(host.student_ui.page+1)*27]
        for i,module in enumerate(visible):
            row,col=divmod(i,9);cell=r(8+18*col,84+18*row,16,16)
            p.drawImage(cell,self.items.image(module.name,module.category))
            hits.append(PanelHit(cell,"student_inventory_item",module.name,module_label(module.name,chinese_enabled(host.registry))+" · 拖拽到下方槽位（不启用模块）"))
        assignments=host.minecraft_hud.assignments(host.registry.get("MinecraftCombatHUD"))
        for i,name in enumerate(assignments):
            cell=r(8+18*i,142,16,16)
            if name!="Empty":
                module=host.registry.get(name)
                p.drawImage(cell,self.items.image(name,module.category if module else "System"))
            if i==host.student_ui.selected_slot:
                p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor("#55ffff"),max(1,s/2)));p.drawRect(cell)
            hits.append(PanelHit(cell,"student_slot",i,f"{i+1}: {module_label(name,chinese_enabled(host.registry))} · 点击分配，右键清空"))
        self.button(host,p,QRectF(7*s,205*s,30*s,12*s),"上一页",s,hits,"student_page",-1,pixel=True)
        self.text(host,p,QRectF(40*s,205*s,110*s,12*s),f"{host.student_ui.page+1}/{max_page+1}  E / Esc 关闭",4,s,"#ffffff",align=Qt.AlignmentFlag.AlignCenter)
        self.button(host,p,QRectF(153*s,205*s,30*s,12*s),"下一页",s,hits,"student_page",1,pixel=True)

    def draw_status(self, host: Any, p: QPainter, width: int, height: int) -> None:
        rows=device_rows(host.state,host.registry)
        buffs=active_buffs(host.state) if host.minecraft_hud_active() and host.registry.get("MinecraftBuffs").enabled else ()
        if not rows and not buffs:return
        # Lower-left reserved chat is separate. Status tiles use the map's own
        # occupied rectangle when present, otherwise a bounded top-left column.
        hud_scale=host.get_hud_scale(width,height)
        map_module=host.registry.get("TacticalMap")
        map_rect=host.tactical_map_rect(int(width/hud_scale),int(height/hud_scale)) if map_module and map_module.enabled else QRectF()
        x=12.0;y=max(100.0,(map_rect.bottom()+12)*hud_scale) if not map_rect.isEmpty() else 108.0
        band=host.buff_timeline_band(int(width/hud_scale),int(height/hud_scale))
        if band is not None:y=max(y,(band.bottom()+12)*hud_scale)
        bottom=height-host.match_chat_reserved_height()-90
        if y+len(rows)*22+len(buffs)*38>bottom:
            x=max(12.0,width*0.26);y=108.0
        mod=host.registry.get("MinecraftBuffs");s=host.get_setting_number(mod,"Icon Scale",1.0)
        s=min(s,max(0.1,(width-x-12)/232))
        image_w=max(min(292,width-x-12) if rows else 0,232*s if buffs else 0)
        image_h=min(bottom-y,len(rows)*22+5+len(buffs)*38*s)
        if image_w<=0 or image_h<=0:return
        dpr=host.devicePixelRatioF()
        key=(tuple(rows),str(buffs),round(s,3),round(image_w,2),round(image_h,2),round(dpr,2))
        if key!=self._status_key:
            image=QImage(max(1,round(image_w*dpr)),max(1,round(image_h*dpr)),QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr);image.fill(Qt.GlobalColor.transparent)
            painter=QPainter(image);local_y=0.0
            def label(rect,text,size,tint):
                font=QFont("Microsoft YaHei UI");font.setStyleName("Regular");font.setPointSizeF(size)
                host.draw_text(painter,rect,text,font,QColor(tint))
            for name,text in rows:
                rect=QRectF(0,local_y,min(292,image_w),21)
                painter.fillRect(rect,QColor(0,0,0,120))
                label(rect.adjusted(7,0,-7,0),f"{name}  ›  {text}",9,"#dddddd")
                local_y+=22
            local_y+=5
            for row in buffs:
                if local_y+36*s>image_h:break
                rect=QRectF(0,local_y,232*s,35*s);painter.fillRect(rect,QColor(0,0,0,160))
                kind=int(number(row.get("kind"),7) or 7);icon=self.icons.get(kind,self.icons[7])
                if kind==2 and "易伤" in str(row.get("name","")):icon=self.vulnerability_icon
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,False)
                effect=host.minecraft_hud.images.get("effect_background")
                if effect is not None:painter.drawImage(QRectF(1*s,local_y+1*s,32*s,32*s),effect)
                painter.drawImage(QRectF(3*s,local_y+3*s,28*s,28*s),icon)
                label(QRectF(36*s,local_y+2*s,188*s,16*s),str(row.get("name","增益"))+" "+str(row.get("level","")),9*s,"#ffffff")
                label(QRectF(36*s,local_y+18*s,188*s,15*s),value_text(row.get("left")," s"),8*s,"#aaaaaa")
                local_y+=38*s
            painter.end();self._status_key,self._status_image=key,image
            self.status_rebuilds+=1
        p.drawImage(QPointF(x,y),self._status_image)
