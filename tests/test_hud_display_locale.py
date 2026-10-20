"""Display-boundary regressions. Real Qt raster/production methods, no devices."""
from __future__ import annotations

import ast
from dataclasses import fields, is_dataclass
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPolygonF
from PySide6.QtWidgets import QApplication
from rm_client.model import RobotState, build_default_registry
from rm_client.match_modes import MATCH_MODES
from rm_client.vision import VisionTarget
from rm_client.ui.hud_locale import HUD_ZH, hud_text, hud_template, HudDisplayText
from rm_client.ui.jello_locale import chinese_enabled
from rm_client.ui.minecraft_hud import MinecraftCombatHudRenderer, _draw_display_text
from rm_client.ui.polar.renderers import tactical_map as tm, module_list as ml, combat_target_hud as ct, esp_wireframe as ew

APP = QApplication.instance() or QApplication([])


def packed(value):
    if isinstance(value, QRectF): return tuple(round(v, 5) for v in value.getRect())
    if isinstance(value, QPointF): return (round(value.x(), 5), round(value.y(), 5))
    if isinstance(value, QPolygonF): return tuple(packed(v) for v in value)
    if isinstance(value, QPainterPath): return tuple((value.elementAt(i).x, value.elementAt(i).y, value.elementAt(i).type) for i in range(value.elementCount()))
    if isinstance(value, QColor): return value.rgba()
    if is_dataclass(value): return tuple((field.name, packed(getattr(value,field.name))) for field in fields(value))
    if isinstance(value, (tuple, list)): return tuple(packed(v) for v in value)
    if isinstance(value, (float, int, str, bool, type(None))): return value
    return type(value).__name__


class Painter:
    def __init__(self):
        self.image = QImage(1600, 1000, QImage.Format_ARGB32_Premultiplied)
        self.image.fill(0)
        self.painter = QPainter(self.image)
        self.geometry = []
        self.direct_text = []
    def __getattr__(self, name):
        fn = getattr(self.painter, name)
        if name == 'drawText':
            def draw(*args):
                self.direct_text.append((packed(args[0]), args[-1]))
                return fn(*args)
            return draw
        if name.startswith(('draw', 'fill')) or name in {'translate', 'scale', 'setClipRect'}:
            def draw(*args):
                self.geometry.append((name, packed(args)))
                return fn(*args)
            return draw
        return fn
    def close(self): self.painter.end()


class Commands:
    def __init__(self): self.texts = []; self.geometry = []
    def text(self, rect, text, *args, **kwargs): self.texts.append((packed(rect), str(text)))
    def rect(self, rect, *args, **kwargs): self.geometry.append(('rect', packed(rect), packed(args)))
    def image(self, rect, *args, **kwargs): self.geometry.append(('image', packed(rect), packed(args)))


class Host(tm.TacticalMapMixin, ml.ModuleListMixin, ct.CombatTargetHudMixin, ew.EspWireframeMixin):
    def __init__(self, language):
        self.registry = build_default_registry()
        self.registry.get('ClickGui').get_setting('Language').value = language
        self.state = RobotState()
        self.match_mode_manager = NS(current=MATCH_MODES['RMUL3v3'])
        self.anim = NS(value=lambda key, value, *args, **kwargs: value)
        self.hover_point = QPointF(-50, -50)
        self.texts = []; self.hotspots = []; self.raw_colors = []; self.toasts = []
        self.side = 'Red'
        self._hud_stack_active = {}
    def draw_text(self, painter, rect, text, *args): self.texts.append((packed(rect), str(text)))
    draw_glass_text = draw_text
    def add_hotspot(self, rect, action, payload=None, **kwargs): self.hotspots.append((packed(rect), action, payload, kwargs.get('tooltip', '')))
    def font(self, *args): return QFont('DejaVu Sans', 8)
    def font_line_height(self, font): return QFontMetricsF(font).height()
    def text_advance(self, font, text): return QFontMetricsF(font).horizontalAdvance(text)
    def elide(self, p, font, text, width): return QFontMetricsF(font).elidedText(text, Qt.ElideRight, max(1, int(width)))
    def hud_accent(self): return QColor('#22aaff')
    def hud_danger(self): return QColor('#ff2233')
    def hud_success(self): return QColor('#44dd66')
    def hud_warning(self): return QColor('#ddaa33')
    def hud_state_color(self, key, ratio=0): return QColor('#aaddff')
    def _client_asset_path(self, *args): return ROOT.joinpath(*args)
    def height(self): return 720
    def width(self): return 1280
    def hud_clean(self): return True
    def hud_density(self): return 'DebugFull'
    def hud_surface(self, *args): return QColor('#112233')
    def hud_panel_outline(self, *args): return QColor('#334455')
    def draw_hud_liquid_glass(self, *args, **kwargs): pass
    def anim_duration(self, value): return value
    def high_res_optimize(self): return False
    def liquid_map_bool(self, key, default): return default
    def liquid_map_setting(self, key, default): return default
    def setting_bool(self, module, key, default):
        setting = module.get_setting(key) if module else None
        return bool(setting.value) if setting else default
    def setting_mode(self, module, key, default):
        setting = module.get_setting(key) if module else None
        return str(setting.value) if setting else default
    def get_setting_number(self, module, key, default):
        setting = module.get_setting(key) if module else None
        return float(setting.value) if setting else default
    def alliance_side(self): return self.side
    def format_time(self, seconds): return f'{int(seconds)//60}:{int(seconds)%60:02d}'
    def short_ring_number(self, value): return str(value)
    def short_outpost_value(self): return str(self.state.enemy_outpost_health)
    def animated_scalar(self, key, value, speed): return value
    def module_list_entries(self, *args, **kwargs):
        return [dict(module=self.registry.get(key), alpha=1, height=1, slide=0, order=i, order_animated=i, tag='COM') for i,key in enumerate(('ArmorAutoAim', 'ArmorLock'))]
    def liquid_status_color(self, label, ratio, fallback):
        self.raw_colors.append(label)
        return super().liquid_status_color(label, ratio, fallback)
    def toast(self, value): self.toasts.append(value)


class HudLocaleTests(unittest.TestCase):
    def capture(self, language, callback):
        host=Host(language); painter=Painter()
        try:
            with patch('time.perf_counter', return_value=1000), patch('time.time', return_value=1000): callback(host, painter)
            return host, painter.geometry, painter.direct_text
        finally: painter.close()
    def pair(self, callback):
        en, en_geo, en_direct = self.capture('English', callback)
        zh, zh_geo, zh_direct = self.capture('简体中文', callback)
        self.assertEqual(en_geo, zh_geo)
        self.assertEqual([v[0] for v in en.texts], [v[0] for v in zh.texts])
        self.assertEqual([v[:3] for v in en.hotspots], [v[:3] for v in zh.hotspots])
        self.assertEqual(en.raw_colors, zh.raw_colors)
        self.assertEqual([v[0] for v in en_direct], [v[0] for v in zh_direct])
        return en, zh
    def test_bounded_draw_boundary_inventory(self):
        # Each remaining untranslated draw argument is deliberately classified.
        # New raw display paths must be localized or explicitly audited here.
        retained = {
            'tactical_map': {
                ('draw_liquid_map_robots','text'),  # Robot IDs, metric distance
                ('draw_map_robots','label'),  # Robot ID
                ('draw_map_markers',"str(marker.get('label', ''))"),  # Opaque custom marker
            },
            'combat_target_hud': set(),
            'esp_wireframe': {
                ('_draw_localized_pill','display_text'),  # Explicit pretranslated copy
                ('draw_target_overlay','label'),  # Opaque detector labels + numeric telemetry
                ('draw_white_outline_lock','self.target_overlay_label(target)'),
                ('draw_minimal_bracket_lock','self.target_overlay_label(target)'),
                ('draw_rune_ring_lock','self.target_overlay_label(target)'),
                ('draw_3d_esp_box','label'),  # Opaque armor label / prediction P#
                ('draw_clean_3d_esp_box','label'),
                ('draw_polar_mechanical_wire','label'),
                ('_append_vision_wire_armor',"getattr(label, 'display', label)"),  # Explicit localized distance or raw P#
                ('draw_armor_3d_esp',"f'{armor.label.upper()} {armor.confidence:.0%}{self.robot_overlay_id_suffix(armor)}'"),
            },
            'module_list': {
                ('draw_module_list_debug_white','display_text'),  # Pretranslated, then measured in its display font
                ('draw_module_list_fast_rows','str(idx + 1)'),
                ('draw_string_with_shadow_mc','text'),  # Generic unused legacy text primitive
                ('draw_module_list_segmented',"'POLAR'"), ('draw_module_list_segmented',"'*'"),
                ('draw_module_list_dynamic_island',"'POLAR'"),
                ('draw_module_list_status_bars','str(idx + 1)'),
                ('draw_keybinds_strip','module.keybind'), ('draw_keybinds_hud','module.keybind'),
                ('draw_robot_list_hud','name'), ('draw_robot_list_hud','str(hp)'),  # Opaque robot names and HP
                ('draw_status_cards_hud','value'),  # Numeric telemetry and units
                ('draw_rm_indicators_hud','ammo'),  # Calibre / counts
                ('draw_rm_indicators_hud','link_text'),  # Templates localize owned wording, retain ports/codes
                ('draw_rm_indicators_hud','telem_text'),  # Numeric v/w/G diagnostic notation
                ('build_gpu_module_list','str(index + 1)'),
            },
        }
        for name, expected in retained.items():
            found=set()
            class Audit(ast.NodeVisitor):
                scope=''
                def visit_FunctionDef(self,node):
                    previous=self.scope;self.scope=node.name;self.generic_visit(node);self.scope=previous
                def visit_Call(self,node):
                    if isinstance(node.func,ast.Attribute) and node.func.attr in {'draw_text','draw_glass_text','text','drawText','draw_pill'}:
                        label=ast.unparse(node.args[1 if node.func.attr=='text' else 2])
                        if not any(word in label for word in ('hud_text(', 'hud_template(', 'hud_module_name(', 'category_label(', '_distance_label(', 'hud_buff_name(')):
                            found.add((self.scope,label))
                    self.generic_visit(node)
            Audit().visit(ast.parse((ROOT/'rm_client/ui/polar/renderers'/f'{name}.py').read_text()))
            self.assertEqual(found,expected,name)

    def test_status_vocab_english_and_unknown_data(self):
        for raw, translated in HUD_ZH.items():
            self.assertEqual(hud_text(raw, False), raw)
            self.assertEqual(hud_text(raw, True), translated)
        self.assertEqual(hud_template('AIR LOCK · {label} {confidence}', True, label='CUSTOM LOCK', confidence='98%'), '空中锁定 · CUSTOM LOCK 98%')
        for raw in ('POLAR','Minecraft','MQTT','UDP','DT7','PTE','LES','NO_STREAM','COM7','0x5A','17mm','42mm','m/s','rad/s','rpm','dps','P3','ID 7'):
            self.assertEqual(hud_text(raw, True), raw)
    def test_map_rows_remain_raw_for_every_mode_and_side(self):
        for mode in MATCH_MODES.values():
            for side in ('Red','Blue'):
                en=Host('English'); zh=Host('简体中文')
                for host in (en,zh):
                    host.match_mode_manager.current=mode;host.side=side
                    for module in host.registry.modules: module.enabled=True
                for name in ('map_status_groups','match_status_rows','match_status_ring_rows','map_telemetry_status_rows','match_header_text'):
                    self.assertEqual(packed(getattr(en,name)()),packed(getattr(zh,name)()))
                self.assertEqual(zh.state.control_owner,en.state.control_owner)
    def test_map_status_styles_geometry_and_payloads(self):
        for label in ('ENEMY','RED BASE YOU','OUTPOST','HEAT','POWER','CTRL','AMMO'):
            for mode in ('bar','card','mini','disc'):
                def draw(h,p):
                    args=(label,'ONLINE',.5,QColor('red'),'enemy_base','Blue BASE 1500/2000 SHIELD 40')
                    rect=QRectF(10,10,160,30)
                    if mode=='bar':h.draw_liquid_status_bar(p,rect,*args,minimal=False)
                    elif mode=='card':h.draw_liquid_status_card(p,rect,*args,minimal=False)
                    elif mode=='mini':h.draw_liquid_mini_status_chip(p,rect,args,'test','LiquidCards')
                    else:h.draw_blackhole_status_disc(p,QPointF(100,100),32,*args,True,'right')
                en,zh=self.pair(draw)
                self.assertNotEqual(en.texts,zh.texts)
                self.assertTrue(any('enemy_base'==entry[2] for entry in zh.hotspots))
    def test_map_stack_ring_and_telemetry_geometry(self):
        for method in ('draw_match_status_stack','draw_match_status_rings'):
            en,zh=self.pair(lambda h,p:getattr(h,method)(p,QRectF(50,50,280,80)))
            self.assertNotEqual(en.texts,zh.texts)
        self.pair(lambda h,p:h.draw_telemetry_strip(p,1280,720))
        self.pair(lambda h,p:h.draw_compact_telemetry_strip(p,1280,720,[('HEAT','80 / 100',.8,QColor('red'),'ThermalPowerPanel')]))
    def test_combat_card_and_target_styles_geometry(self):
        for aim in (0,50,90):
            frame=NS(aim_anim=aim,ammo_ghost=80,ammo_anim=60)
            en,zh=self.pair(lambda h,p:h.draw_combat_target_card(p,1280,720,'Enhanced',frame,75,30,show_status_line=True))
            self.assertIn('瞄准  '+('锁定' if aim>=80 else '跟踪' if aim>=40 else '待机'),[s for _,s in zh.texts])
        for kind in ('armor','energy'):
            target=VisionTarget(1,2,30,40,.98,'CUSTOM LOCK',kind=kind)
            for method in ('draw_target_round_compact','draw_target_bar_only','draw_target_card'):
                en,zh=self.pair(lambda h,p:getattr(h,method)(p,QRectF(10,20,224,82),target,*(['EnergyTargetHUD' if kind=='energy' else 'RobotTargetHUD'] if method=='draw_target_card' else [])))
                self.assertEqual(target.label,'CUSTOM LOCK')
                if kind=='energy' or method!='draw_target_bar_only': self.assertNotEqual(en.texts,zh.texts)
    def test_module_list_styles_and_gpu_preserve_ids_geometry(self):
        methods=('fast_rows','liquid_array','rainbow_right','glow_rows','segmented','dynamic_island','keybind_rows','status_bars','robot_cards')
        for method in methods:
            en,zh=self.pair(lambda h,p:getattr(h,'draw_module_list_'+method)(p,1280,*(['LiquidArray'] if method=='liquid_array' else [])))
            self.assertIn('装甲自瞄',[s for _,s in zh.texts],method)
            self.assertEqual(zh.registry.get('ArmorAutoAim').name,'ArmorAutoAim')
        self.pair(lambda h,p:h.draw_module_list_polar_text(p))
        with patch.object(ml,'ClickGuiDrawList',Commands):
            outputs=[]
            for language in ('English','简体中文'):
                h=Host(language); outputs.append(h.build_gpu_module_list(h.module_list_entries(),h.module_list_layout(1280,720),1,1280,720,'StatusBars'))
            self.assertEqual(outputs[0].geometry,outputs[1].geometry)
            self.assertEqual([r for r,_ in outputs[0].texts],[r for r,_ in outputs[1].texts])
            self.assertIn('装甲自瞄',[s for _,s in outputs[1].texts])
    def test_actual_keybinds_stay_exact_in_rows_and_tags(self):
        for key in ('CTRL','Ctrl','Control','ALT','SHIFT','None'):
            for method in ('draw_module_list_keybind_rows','draw_module_list_liquid_array'):
                def draw(h,p):
                    module=h.registry.get('ArmorAutoAim');module.keybind=key
                    h.registry.get('HUD').get_setting('Module Tags').value='Keybind'
                    h.module_list_entries=lambda *args,**kwargs:[dict(module=module,alpha=1,height=1,slide=0,order=0,order_animated=0,tag=h.module_list_tag(module,'Keybind'))]
                    getattr(h,method)(p,1280,*(['LiquidArrayTags'] if method=='draw_module_list_liquid_array' else []))
                en,zh=self.pair(draw)
                self.assertIn('开' if key=='None' else key,[text for _,text in zh.texts])
                self.assertEqual(zh.registry.get('ArmorAutoAim').keybind,key)
                if key=='CTRL':self.assertNotIn('控制',[text for _,text in zh.texts])

    def test_active_mods_cpu_gpu_and_language_switch(self):
        for gpu in (False, True):
            records=[]
            for language in ('English','简体中文'):
                def draw(h,p):
                    for module in h.registry.modules:module.enabled=False
                    h.registry.get('ArmorAutoAim').enabled=True
                    h.registry.get('HUD').get_setting('Jello List Animations').value=False
                    h.gui_motion=NS(now=1000)
                    h._jello_active_mods_frame_index=-1
                    h._collect_gpu_hud_commands=gpu
                    h.clickgui_gpu=NS(available=gpu)
                    h._gpu_hud_commands=Commands()
                    h.draw_module_list_debug_white(p,1280)
                h,geometry,direct=self.capture(language,draw)
                records.append((geometry,h._gpu_hud_commands if gpu else direct + h.texts))
            if gpu:
                en,zh=records[0][1].texts,records[1][1].texts
            else:en,zh=records[0][1],records[1][1]
            # Translation changes advance, not the right anchor. Requiring
            # equal English/Chinese rectangles preserved the original bug.
            self.assertEqual(len(en), len(zh))
            for (english_rect, _), (chinese_rect, _) in zip(en, zh):
                self.assertAlmostEqual(english_rect[0] + english_rect[2],
                                       chinese_rect[0] + chinese_rect[2], places=3)
                self.assertEqual(english_rect[1], chinese_rect[1])
                self.assertGreaterEqual(english_rect[0], 0)
                self.assertGreaterEqual(chinese_rect[0], 0)
                self.assertLessEqual(english_rect[0] + english_rect[2], 1280)
                self.assertLessEqual(chinese_rect[0] + chinese_rect[2], 1280)
            self.assertNotEqual(en[0][0][2], zh[0][0][2])
            self.assertEqual(en[0][1],'ArmorAutoAim')
            self.assertEqual(zh[0][1],'装甲自瞄')

    def test_map_header_preserves_title_and_custom_markers(self):
        def draw(h,p):
            h.match_mode_manager.current=NS(title='CUSTOM LOCK',key='RMUL3v3')
            h.state.current_stage='MATCH'
            h.draw_match_header(p,1280)
        en,zh=self.pair(draw)
        self.assertIn('CUSTOM LOCK',zh.texts[0][1])
        self.assertIn('比赛中',zh.texts[0][1])
        self.assertEqual(en.match_header_text(),zh.match_header_text())
        def marker(h,p):
            h.state.map_markers=[dict(x=1,y=2,label='ENEMY LOCK CUSTOM',kind='marker')]
            h.map_point=lambda *args:QPointF(40,50)
            h.draw_map_markers(p,QRectF(0,0,240,120),NS())
        en,zh=self.pair(marker)
        self.assertEqual(en.texts,zh.texts)
        self.assertEqual(zh.texts[0][1],'ENEMY LOCK CUSTOM')

    def test_status_cards_and_indicators_preserve_state(self):
        self.pair(lambda h,p:h.draw_status_cards_hud(p,1280))
        for authority in ('PASSIVE','CLIENT','LOCKOUT','ESTOP'):
            def draw(h,p):
                h.state.polar_link_active=True
                h.state.backend_stats={'polar_link':dict(port='COM7',resolved_port='COM7',link_alive=True,role_hud_code='INF',role_id=3,segments_received=9,authority={'state':authority})}
                h.draw_rm_indicators_hud(p,1280)
            en,zh=self.pair(draw)
            self.assertEqual(en.state.backend_stats,zh.state.backend_stats)
            self.assertTrue(any('COM7' in text and 'INF#3' in text for _,text in zh.texts))
            self.assertTrue(any(hud_text(authority,True) in text for _,text in zh.texts))
    def test_event_menu_raw_dispatch_all_choices_and_cancel(self):
        for selection in range(5):
            calls=[]
            for language in ('English','简体中文'):
                h=Host(language); output=[]; captions=[]; responses=iter((selection,0))
                def item(owner,title,label,options,*args):
                    captions.extend((title,label,*options));return options[next(responses)],True
                def integer(owner,title,label,*args): captions.extend((title,label));return 2,True
                h.backend=NS(referee=NS(profile_id='rm2026-v1.3.1'),**{name:(lambda *args,_name=name,**kwargs:output.append((_name,args,kwargs)) or (True,'OK')) for name in ('publish_rune_activate','publish_dart_command','publish_sentry_command','publish_assembly_command','publish_performance_from_registry')})
                with patch.object(tm.QInputDialog,'getItem',side_effect=item),patch.object(tm.QInputDialog,'getInt',side_effect=integer):h.open_event_command_menu()
                normalized=[(name, ('registry',) if name=='publish_performance_from_registry' else args,kwargs) for name,args,kwargs in output]
                calls.append(normalized)
                self.assertEqual(len(output),1)
                self.assertIn('Event commands' if language=='English' else '赛事指令',captions)
            self.assertEqual(*calls)
        for cancellation in (0,1,2):
            h=Host('简体中文');calls=[];count=[0]
            h.backend=NS(referee=NS(profile_id='rm2026-v1.3.1'),publish_dart_command=lambda *args:calls.append(args))
            def item(owner,title,label,options,*args):
                i=count[0];count[0]+=1;return options[1 if i==0 else 0],i!=cancellation
            def integer(*args):i=count[0];count[0]+=1;return 1,i!=cancellation
            with patch.object(tm.QInputDialog,'getItem',side_effect=item),patch.object(tm.QInputDialog,'getInt',side_effect=integer):h.open_event_command_menu()
            self.assertEqual(calls,[])
    def test_minecraft_layout_cache_glyph_route_and_drop(self):
        renderer=MinecraftCombatHudRenderer(ROOT/'assets/minecraft_hud')
        self.assertTrue(renderer.available)
        h=Host('English');state=h.state;state.match_title='CUSTOM LOCK'
        out=QImage(1280,720,QImage.Format_ARGB32_Premultiplied);p=QPainter(out)
        labels=[];original=renderer._draw_scoreboard
        def score(painter,rect,lines,scale):labels.append((packed(rect),lines));return original(painter,rect,lines,scale)
        try:
            with patch.object(renderer,'_draw_scoreboard',side_effect=score),patch('time.perf_counter',return_value=1000):
                en=renderer.draw(p,1280,720,state,h.registry,h.registry.get('MinecraftCombatHUD'))
                count=renderer.layer_rebuilds
                h.registry.get('ClickGui').get_setting('Language').value='简体中文'
                zh=renderer.draw(p,1280,720,state,h.registry,h.registry.get('MinecraftCombatHUD'))
                self.assertEqual(renderer.layer_rebuilds,count+1) # language change bypasses telemetry throttle
            self.assertEqual(en,zh)
            self.assertEqual(labels[0][0],labels[1][0])
            self.assertEqual(labels[0][1][0][0],labels[1][1][0][0])
            self.assertIn('剩余时间',labels[1][1][3][0])
            for glyph in '冷却功率剩余时间':self.assertIn(ord(glyph),renderer.styled_font.hex_data)
        finally:p.end()
        spy=NS(font=NS(draw=lambda *args:'bitmap',logical_width=lambda raw:30),styled_font=NS(draw=lambda *args,**kwargs:labels.append(args[2])))
        self.assertEqual(_draw_display_text(spy,None,0,0,HudDisplayText('COOL','COOL'),QColor('red'),1),'bitmap')
        _draw_display_text(spy,None,0,0,HudDisplayText('COOL','冷却'),QColor('red'),1)
        self.assertEqual(labels[-1],'冷却')
        commands=[]
        for language in ('English','简体中文'):
            h=Host(language);c=Commands();renderer.append_drop_overlay(c,1280,720,'ArmorAutoAim',QPointF(200,300),renderer.assignments(h.registry.get('MinecraftCombatHUD')),QFont(),registry=h.registry);commands.append(c)
        self.assertEqual(commands[0].geometry,commands[1].geometry)
        self.assertEqual([r for r,_ in commands[0].texts],[r for r,_ in commands[1].texts])
        self.assertEqual(commands[1].texts[-1][1],'放置 装甲自瞄')
    def test_esp_distance_gpu_and_pill_keep_raw_geometry(self):
        raw='DIST 4.5m'
        outputs=[]
        for language in ('English','简体中文'):
            h=Host(language);p=Painter()
            try:ew._draw_localized_pill(h,p,QPointF(30,40),raw,ew._distance_label(raw,h.registry),QColor('red'));outputs.append((p.geometry,h.texts))
            finally:p.close()
        self.assertEqual(outputs[0][0],outputs[1][0])
        self.assertEqual(outputs[1][1][0][1],'距离 4.5m')
        front=[QPointF(10,10),QPointF(40,10),QPointF(40,40),QPointF(10,40)]
        batch_outputs=[]
        for language in ('English','简体中文'):
            h=Host(language);batch=ew.VisionWireBatch();label=HudDisplayText(raw,ew._distance_label(raw,h.registry))
            h._append_vision_wire_armor(batch,front,[p+QPointF(2,2) for p in front],width=1,alpha=1,predicted=False,label=label)
            batch_outputs.append(batch)
        self.assertEqual(packed(batch_outputs[0].lines),packed(batch_outputs[1].lines))
        self.assertEqual(batch_outputs[0].labels.commands[0].payload.rect,batch_outputs[1].labels.commands[0].payload.rect)
        self.assertEqual(batch_outputs[1].labels.commands[0].payload.text,'距离 4.5m')


if __name__=='__main__': unittest.main()
